"""One polite HTTP client for every scraper.

* Concurrency: a global cap, a per-host cap, and a minimum gap between requests to the
  same host.
* Retries: exponential backoff with jitter on 408/425/429/5xx and transport errors,
  honouring a Retry-After header (capped).
* Cache: 200 and 404 responses are kept on disk for cache_ttl_hours, so reruns and
  resumed batches do not hit the same hosts again.
* Size cap: a body is read up to a byte limit and never further.
"""

import asyncio
import hashlib
import json
import math
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from types import TracebackType
from typing import Any, Final, Self
from urllib.parse import urlsplit

import httpx

from anthropic_prospector.config import USER_AGENT, Settings

MAX_ATTEMPTS: Final = 3
RETRY_STATUSES: Final = frozenset({408, 425, 429, 500, 502, 503, 504})
CACHED_STATUSES: Final = frozenset({200, 404})
MAX_RETRY_AFTER_S: Final = 30.0
MIN_HOST_INTERVAL_S: Final = 0.25
DEFAULT_MAX_BYTES: Final = 2_000_000


class FetchError(Exception):
    """A request failed for good: transport errors or retryable statuses after retries."""

    def __init__(self, url: str, message: str, *, status: int | None = None) -> None:
        super().__init__(f"{url}: {message}")
        self.url = url
        self.status = status


class ResponseTooLarge(FetchError):
    """The body was cut at the byte cap, so it cannot be parsed as a whole."""


@dataclass(frozen=True)
class Page:
    url: str
    status: int
    text: str
    from_cache: bool = False
    final_url: str | None = None  # where redirects ended, when that differs from `url`
    truncated: bool = False  # the body was longer than the byte cap and was cut

    @property
    def ok(self) -> bool:
        return self.status == 200

    def json(self) -> Any:
        return json.loads(self.text)


class DiskCache:
    """URL -> Page on disk, one JSON file per URL, expired after `ttl_s` seconds."""

    def __init__(
        self, directory: Path, ttl_s: float, *, clock: Callable[[], float] = time.time
    ) -> None:
        self.directory = directory
        self.ttl_s = ttl_s
        self._clock = clock

    def _path(self, url: str) -> Path:
        return self.directory / f"{hashlib.sha256(url.encode()).hexdigest()}.json"

    def get(self, url: str) -> Page | None:
        if self.ttl_s <= 0:
            return None
        try:
            entry = json.loads(self._path(url).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if self._clock() - entry["stored_at"] > self.ttl_s or entry.get("url") != url:
            return None
        return Page(
            url=url,
            status=entry["status"],
            text=entry["text"],
            from_cache=True,
            final_url=entry.get("final_url"),
        )

    def put(self, page: Page) -> None:
        if self.ttl_s <= 0:
            return
        entry = asdict(page) | {"stored_at": self._clock(), "from_cache": False}
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            tmp = self._path(page.url).with_suffix(".tmp")
            tmp.write_text(json.dumps(entry), encoding="utf-8")
            tmp.replace(self._path(page.url))
        except OSError:
            pass  # a cache that cannot be written only costs a refetch


class Fetcher:
    """Async GETs with caching, pacing and retries. Use as an async context manager."""

    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.AsyncClient | None = None,
        cache: DiskCache | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client or httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT},
            timeout=httpx.Timeout(
                settings.http_read_timeout_s, connect=settings.http_connect_timeout_s
            ),
            follow_redirects=True,
        )
        self._owns_client = client is None
        self._cache = cache or DiskCache(
            settings.cache_dir / "http", settings.cache_ttl_hours * 3600
        )
        self._global = asyncio.Semaphore(settings.http_concurrency)
        self._per_host = settings.per_host_concurrency
        self._hosts: dict[str, asyncio.Semaphore] = {}
        self._next_slot: dict[str, float] = {}
        self._sleep = sleep
        self._clock = clock

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def get(self, url: str, *, max_bytes: int = DEFAULT_MAX_BYTES) -> Page:
        """Fetch `url`. Returns any page under 500 (callers judge 404 and friends);
        raises FetchError for transport errors and retryable statuses after retries."""
        if (cached := self._cache.get(url)) is not None:
            return cached
        host = urlsplit(url).hostname or ""
        semaphore = self._hosts.setdefault(host, asyncio.Semaphore(self._per_host))
        last_error = "no attempt made"
        for attempt in range(MAX_ATTEMPTS):
            # Per-host first, so requests queued on a busy host never hold global slots.
            async with semaphore, self._global:
                await self._pace(host)
                try:
                    page, retry_after = await self._fetch(url, max_bytes)
                except httpx.TransportError as exc:
                    page, retry_after, last_error = None, None, f"{type(exc).__name__}: {exc}"
            if page is not None:
                if page.status not in RETRY_STATUSES:
                    if page.status in CACHED_STATUSES and not page.truncated:
                        self._cache.put(page)
                    return page
                last_error = f"HTTP {page.status}"
            if attempt + 1 < MAX_ATTEMPTS:
                await self._sleep(self._backoff(attempt, retry_after))
        status = page.status if page is not None else None
        raise FetchError(
            url, f"gave up after {MAX_ATTEMPTS} attempts ({last_error})", status=status
        )

    async def get_json(self, url: str, *, max_bytes: int = DEFAULT_MAX_BYTES) -> tuple[int, Any]:
        """(status, parsed JSON or None). Raises FetchError when a 200 body is not JSON,
        and its subclass ResponseTooLarge when the body did not fit in `max_bytes`."""
        page = await self.get(url, max_bytes=max_bytes)
        if not page.ok:
            return page.status, None
        if page.truncated:
            raise ResponseTooLarge(
                url, f"response is larger than {max_bytes:,} bytes", status=page.status
            )
        try:
            return page.status, page.json()
        except ValueError as exc:
            raise FetchError(url, "response is not valid JSON", status=page.status) from exc

    async def _fetch(self, url: str, max_bytes: int) -> tuple[Page, float | None]:
        async with self._client.stream("GET", url) as response:
            chunks: list[bytes] = []
            size = 0
            async for chunk in response.aiter_bytes():
                chunks.append(chunk)
                size += len(chunk)
                if size > max_bytes:
                    break
            body = b"".join(chunks)
            text = body[:max_bytes].decode(response.encoding or "utf-8", errors="replace")
            retry_after = _retry_after(response.headers.get("retry-after"))
            page = Page(
                url=url,
                status=response.status_code,
                text=text,
                final_url=str(response.url) if response.history else None,
                truncated=len(body) > max_bytes,
            )
            return page, retry_after

    async def _pace(self, host: str) -> None:
        now = self._clock()
        slot = max(now, self._next_slot.get(host, now))
        self._next_slot[host] = slot + MIN_HOST_INTERVAL_S  # reserve before waiting
        if slot > now:
            await self._sleep(slot - now)

    @staticmethod
    def _backoff(attempt: int, retry_after: float | None) -> float:
        if retry_after is not None:
            return min(retry_after, MAX_RETRY_AFTER_S)
        return 0.5 * 2.0**attempt + random.uniform(0, 0.25)


def _retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    seconds = (when - datetime.now(UTC)).total_seconds()
    return max(0.0, seconds) if math.isfinite(seconds) else None
