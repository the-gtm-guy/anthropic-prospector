"""Signals from a company's own public web pages.

A few well-known paths are read: the homepage, careers and jobs pages (which link to the
ATS board), and security, trust and subprocessor pages (which name cloud and model vendors
outright). robots.txt is honoured, bodies are capped, and nothing is rendered: a page built
in the browser by JavaScript yields little text, which is reported rather than guessed at.
"""

import asyncio
import hashlib
from dataclasses import dataclass, field
from typing import Final
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from anthropic_prospector.config import USER_AGENT
from anthropic_prospector.models import StartupProfile
from anthropic_prospector.scrapers.ats import BoardRef, board_links
from anthropic_prospector.scrapers.ats.base import html_to_text
from anthropic_prospector.scrapers.http import Fetcher, FetchError, Page

PATHS: Final = ("/", "/careers", "/jobs", "/security", "/trust", "/subprocessors")
TRUST_PATHS: Final = frozenset({"/security", "/trust", "/subprocessors"})
PAGE_MAX_BYTES: Final = 1_000_000
ROBOTS_MAX_BYTES: Final = 100_000
JS_SHELL_MAX_CHARS: Final = 200  # less visible text than this, plus scripts: a JS shell


@dataclass(frozen=True)
class SitePage:
    url: str  # where the text came from, after redirects
    text: str  # visible text, one block per line
    trust: bool  # a security, trust or subprocessor page


@dataclass(frozen=True)
class SiteReport:
    pages: list[SitePage] = field(default_factory=list)
    board_refs: list[BoardRef] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    reached: bool = False  # the site answered at all, if only for robots.txt


async def read_site(fetcher: Fetcher, profile: StartupProfile) -> SiteReport:
    parts = urlsplit(profile.website_url)
    base = f"{parts.scheme}://{parts.netloc}"
    try:
        robots = await fetcher.get(f"{base}/robots.txt", max_bytes=ROBOTS_MAX_BYTES)
    except FetchError as exc:
        return SiteReport(warnings=[f"Website unreachable: {exc}"])

    rules = _robots_rules(robots)
    allowed = [path for path in PATHS if rules.can_fetch(USER_AGENT, base + path)]
    warnings: list[str] = []
    if len(allowed) < len(PATHS):
        warnings.append(
            f"robots.txt on {base} disallows {len(PATHS) - len(allowed)} of the "
            f"{len(PATHS)} pages this tool reads; they were skipped."
        )

    results = await asyncio.gather(
        *(fetcher.get(base + path, max_bytes=PAGE_MAX_BYTES) for path in allowed),
        return_exceptions=True,
    )
    pages: list[SitePage] = []
    refs: list[BoardRef] = []
    seen: set[str] = set()
    js_shells: list[str] = []
    for path, result in zip(allowed, results, strict=True):
        if isinstance(result, FetchError):
            warnings.append(f"Could not read {result}")  # the error names the URL
            continue
        if isinstance(result, BaseException):
            raise result
        if not result.ok:
            continue  # most sites have no /trust or /subprocessors page
        refs += board_links(result.text) + board_links(result.final_url or "")
        text = html_to_text(result.text)
        if _looks_like_js_shell(result.text, text):
            js_shells.append(result.final_url or result.url)
        digest = hashlib.sha256(text.encode()).hexdigest()
        if text and digest not in seen:  # single-page apps answer every path alike
            seen.add(digest)
            pages.append(SitePage(result.final_url or result.url, text, path in TRUST_PATHS))
    if js_shells:
        warnings.append(
            f"Pages rendered by JavaScript, so little of their text could be read: "
            f"{', '.join(js_shells)}."
        )
    return SiteReport(pages, list(dict.fromkeys(refs)), warnings, reached=True)


def _robots_rules(page: Page) -> RobotFileParser:
    """Rules from robots.txt: 401/403 forbid everything, a missing file allows everything."""
    rules = RobotFileParser()
    if page.status in (401, 403):
        rules.parse(["User-agent: *", "Disallow: /"])
    elif page.ok:
        rules.parse(page.text.splitlines())
    else:
        rules.parse([])
    return rules


def _looks_like_js_shell(markup: str, text: str) -> bool:
    return len(text) < JS_SHELL_MAX_CHARS and "<script" in markup.lower()
