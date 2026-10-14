import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path

import httpx
import pytest
import respx

from anthropic_prospector.config import Settings
from anthropic_prospector.scrapers.http import (
    MAX_RETRY_AFTER_S,
    MIN_HOST_INTERVAL_S,
    DiskCache,
    Fetcher,
    FetchError,
    Page,
    ResponseTooLarge,
)

URL = "https://a.test/x"


class Env:
    """Controllable clock plus a fake sleep that records its argument and advances the clock."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def env() -> Env:
    return Env()


@pytest.fixture
def cache(tmp_path: Path, env: Env) -> DiskCache:
    return DiskCache(tmp_path, ttl_s=3600, clock=env.clock)


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(follow_redirects=True) as c:
        yield c


@pytest.fixture
def fetcher(client: httpx.AsyncClient, cache: DiskCache, env: Env) -> Fetcher:
    return Fetcher(Settings(), client=client, cache=cache, sleep=env.sleep, clock=env.clock)


def cached_files(cache: DiskCache) -> list[Path]:
    return list(cache.directory.glob("*.json"))


async def test_200_is_cached(fetcher: Fetcher, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(URL).respond(200, text="hello")
    first = await fetcher.get(URL)
    second = await fetcher.get(URL)
    assert first.ok
    assert first.text == "hello"
    assert not first.from_cache
    assert second.from_cache
    assert second.text == "hello"
    assert route.call_count == 1


async def test_404_is_returned_and_cached(
    fetcher: Fetcher, cache: DiskCache, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get(URL).respond(404, text="nope")
    first = await fetcher.get(URL)
    second = await fetcher.get(URL)
    assert first.status == 404
    assert not first.ok
    assert second.from_cache
    assert second.status == 404
    assert route.call_count == 1
    assert len(cached_files(cache)) == 1


async def test_500_then_200_retries(
    fetcher: Fetcher, cache: DiskCache, env: Env, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get(URL).mock(
        side_effect=[httpx.Response(500), httpx.Response(200, text="ok")]
    )
    page = await fetcher.get(URL)
    assert page.status == 200
    assert page.text == "ok"
    assert route.call_count == 2
    assert len(env.sleeps) == 1
    assert 0.5 <= env.sleeps[0] <= 0.75
    # only the final 200 is cached
    assert len(cached_files(cache)) == 1
    assert cache.get(URL) is not None


async def test_503_three_times_raises(
    fetcher: Fetcher, cache: DiskCache, env: Env, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get(URL).respond(503)
    with pytest.raises(FetchError) as excinfo:
        await fetcher.get(URL)
    assert excinfo.value.status == 503
    assert route.call_count == 3
    assert len(env.sleeps) == 2
    assert cached_files(cache) == []


async def test_transport_error_three_times_raises(
    fetcher: Fetcher, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get(URL).mock(side_effect=httpx.ConnectError)
    with pytest.raises(FetchError) as excinfo:
        await fetcher.get(URL)
    assert excinfo.value.status is None
    assert route.call_count == 3


@pytest.mark.parametrize(
    ("header", "low", "high"),
    [
        ("7", 7.0, 7.0),
        ("120", MAX_RETRY_AFTER_S, MAX_RETRY_AFTER_S),
        (None, 5.0, 10.5),  # an HTTP-date 10 s ahead, built when the test runs
    ],
    ids=["seconds", "capped", "http-date"],
)
async def test_retry_after(
    fetcher: Fetcher,
    env: Env,
    respx_mock: respx.MockRouter,
    header: str | None,
    low: float,
    high: float,
) -> None:
    if header is None:
        header = format_datetime(datetime.now(UTC) + timedelta(seconds=10), usegmt=True)
    respx_mock.get(URL).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": header}),
            httpx.Response(200, text="ok"),
        ]
    )
    page = await fetcher.get(URL)
    assert page.ok
    assert len(env.sleeps) == 1
    assert low <= env.sleeps[0] <= high


async def test_pacing_same_host_sleeps(
    fetcher: Fetcher, env: Env, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("https://a.test/one").respond(200, text="1")
    respx_mock.get("https://a.test/two").respond(200, text="2")
    await fetcher.get("https://a.test/one")
    assert env.sleeps == []
    await fetcher.get("https://a.test/two")
    assert env.sleeps == [MIN_HOST_INTERVAL_S]


async def test_pacing_different_hosts_no_sleep(
    fetcher: Fetcher, env: Env, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("https://a.test/x").respond(200, text="1")
    respx_mock.get("https://b.test/x").respond(200, text="2")
    await fetcher.get("https://a.test/x")
    await fetcher.get("https://b.test/x")
    assert env.sleeps == []


async def test_max_bytes_caps_body(fetcher: Fetcher, respx_mock: respx.MockRouter) -> None:
    respx_mock.get(URL).respond(200, content=b"a" * 10_000)
    page = await fetcher.get(URL, max_bytes=1000)
    assert len(page.text) == 1000


async def test_truncated_page_is_flagged_and_not_cached(
    fetcher: Fetcher, cache: DiskCache, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get(URL).respond(200, content=b"a" * 1001)
    first = await fetcher.get(URL, max_bytes=1000)
    second = await fetcher.get(URL, max_bytes=1000)
    assert first.truncated is True
    assert second.truncated is True
    assert route.call_count == 2
    assert cached_files(cache) == []


async def test_body_of_exactly_max_bytes_is_not_truncated(
    fetcher: Fetcher, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get(URL).respond(200, content=b"a" * 1000)
    assert (await fetcher.get(URL, max_bytes=1000)).truncated is False


async def test_get_json_truncated_raises_response_too_large(
    fetcher: Fetcher, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get(URL).respond(200, content=b"[" + b"1," * 1000 + b"1]")
    with pytest.raises(ResponseTooLarge) as excinfo:
        await fetcher.get_json(URL, max_bytes=1000)
    assert isinstance(excinfo.value, FetchError)


async def test_get_json_parses(fetcher: Fetcher, respx_mock: respx.MockRouter) -> None:
    respx_mock.get(URL).respond(200, json={"a": [1, 2]})
    assert await fetcher.get_json(URL) == (200, {"a": [1, 2]})


async def test_get_json_invalid_body_raises(fetcher: Fetcher, respx_mock: respx.MockRouter) -> None:
    respx_mock.get(URL).respond(200, text="<html>not json</html>")
    with pytest.raises(FetchError):
        await fetcher.get_json(URL)


async def test_get_json_404(fetcher: Fetcher, respx_mock: respx.MockRouter) -> None:
    respx_mock.get(URL).respond(404, text="missing")
    assert await fetcher.get_json(URL) == (404, None)


def test_cache_entry_expires(tmp_path: Path, env: Env) -> None:
    cache = DiskCache(tmp_path, ttl_s=3600, clock=env.clock)
    cache.put(Page(url=URL, status=200, text="t"))
    assert cache.get(URL) is not None
    env.now = 3600 + 1
    assert cache.get(URL) is None


def test_cache_ttl_zero_disables(tmp_path: Path, env: Env) -> None:
    cache = DiskCache(tmp_path, ttl_s=0, clock=env.clock)
    cache.put(Page(url=URL, status=200, text="t"))
    assert cache.get(URL) is None
    assert list(tmp_path.iterdir()) == []


def test_cache_corrupt_file_is_a_miss(tmp_path: Path, env: Env) -> None:
    cache = DiskCache(tmp_path, ttl_s=3600, clock=env.clock)
    cache.put(Page(url=URL, status=200, text="t"))
    (path,) = tmp_path.glob("*.json")
    path.write_text("{not json", encoding="utf-8")
    assert cache.get(URL) is None


def test_cache_url_mismatch_is_a_miss(tmp_path: Path, env: Env) -> None:
    cache = DiskCache(tmp_path, ttl_s=3600, clock=env.clock)
    cache.put(Page(url=URL, status=200, text="t"))
    (path,) = tmp_path.glob("*.json")
    entry = json.loads(path.read_text(encoding="utf-8"))
    entry["url"] = "https://other.test/y"
    path.write_text(json.dumps(entry), encoding="utf-8")
    assert cache.get(URL) is None


async def test_redirect_final_url(fetcher: Fetcher, respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://a.test/old").respond(301, headers={"Location": "https://a.test/new"})
    respx_mock.get("https://a.test/new").respond(200, text="new")
    page = await fetcher.get("https://a.test/old")
    assert page.url == "https://a.test/old"
    assert page.final_url == "https://a.test/new"
    again = await fetcher.get("https://a.test/old")
    assert again.from_cache
    assert again.final_url == "https://a.test/new"


async def test_no_redirect_has_no_final_url(fetcher: Fetcher, respx_mock: respx.MockRouter) -> None:
    respx_mock.get(URL).respond(200, text="x")
    assert (await fetcher.get(URL)).final_url is None


async def test_injected_client_is_not_closed(cache: DiskCache) -> None:
    client = httpx.AsyncClient()
    async with Fetcher(Settings(), client=client, cache=cache):
        pass
    assert not client.is_closed
    await client.aclose()


async def test_owned_client_is_closed(cache: DiskCache) -> None:
    async with Fetcher(Settings(), cache=cache) as fetcher:
        assert not fetcher._client.is_closed
    assert fetcher._client.is_closed
