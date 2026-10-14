"""read_site(): robots.txt handling, page dedupe, JS shells, redirects and error reporting."""

from pathlib import Path

import httpx
import respx

from anthropic_prospector.config import Settings
from anthropic_prospector.models import ATSPlatform, StartupProfile
from anthropic_prospector.scrapers.ats import BoardRef
from anthropic_prospector.scrapers.http import DiskCache, Fetcher
from anthropic_prospector.scrapers.web_intel import read_site

SITE = "https://acme.test"
FILLER = "Acme builds robots for warehouses and factories around the world. " * 5


def html(body: str) -> str:
    return f"<html><body><p>{FILLER}</p><p>{body}</p></body></html>"


async def _no_sleep(seconds: float) -> None:
    return None


def _fetcher(tmp_path: Path) -> Fetcher:
    return Fetcher(
        Settings(),
        client=httpx.AsyncClient(follow_redirects=True),
        cache=DiskCache(tmp_path, ttl_s=0),
        sleep=_no_sleep,
    )


def _profile() -> StartupProfile:
    return StartupProfile(company_name="Acme Robotics", domain="acme.test", hq_state="CA")


async def test_homepage_with_embed_and_no_other_pages(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get(f"{SITE}/robots.txt").respond(404)
    respx_mock.get(f"{SITE}/").respond(
        200,
        html=html(
            "We run on AWS and use OpenAI."
            '<script src="https://boards.greenhouse.io/embed/job_board/js?for=acme"></script>'
        ),
    )
    respx_mock.get(host="acme.test").respond(404)
    report = await read_site(_fetcher(tmp_path), _profile())
    assert len(report.pages) == 1
    assert report.pages[0].url == f"{SITE}/"
    assert report.pages[0].trust is False
    assert "AWS" in report.pages[0].text
    assert report.board_refs == [BoardRef(ATSPlatform.GREENHOUSE, "acme")]
    assert report.reached
    assert report.warnings == []


async def test_robots_disallow_skips_page(tmp_path: Path, respx_mock: respx.MockRouter) -> None:
    respx_mock.get(f"{SITE}/robots.txt").respond(200, text="User-agent: *\nDisallow: /careers")
    careers = respx_mock.get(f"{SITE}/careers").respond(200, html=html("Careers"))
    respx_mock.get(host="acme.test").respond(404)
    report = await read_site(_fetcher(tmp_path), _profile())
    assert not careers.called
    assert any("robots.txt" in w and "disallows 1 of the 6" in w for w in report.warnings)


async def test_robots_403_forbids_everything(tmp_path: Path, respx_mock: respx.MockRouter) -> None:
    robots = respx_mock.get(f"{SITE}/robots.txt").respond(403)
    rest = respx_mock.get(host="acme.test").respond(200, html=html("hi"))
    report = await read_site(_fetcher(tmp_path), _profile())
    assert robots.call_count == 1
    assert not rest.called
    assert report.pages == []
    assert report.reached
    assert any("6 of the 6" in w for w in report.warnings)


async def test_robots_unreachable(tmp_path: Path, respx_mock: respx.MockRouter) -> None:
    respx_mock.get(f"{SITE}/robots.txt").mock(side_effect=httpx.ConnectError)
    rest = respx_mock.get(host="acme.test").respond(200, html=html("hi"))
    report = await read_site(_fetcher(tmp_path), _profile())
    assert not report.reached
    assert len(report.warnings) == 1
    assert report.warnings[0].startswith("Website unreachable")
    assert not rest.called


async def test_single_page_app_yields_one_page(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get(f"{SITE}/robots.txt").respond(404)
    respx_mock.get(host="acme.test").respond(200, html=html("Same shell everywhere."))
    report = await read_site(_fetcher(tmp_path), _profile())
    assert len(report.pages) == 1


async def test_js_shell_is_reported(tmp_path: Path, respx_mock: respx.MockRouter) -> None:
    respx_mock.get(f"{SITE}/robots.txt").respond(404)
    respx_mock.get(f"{SITE}/").respond(
        200, html='<div id="root"></div><script src="/app.js"></script>'
    )
    respx_mock.get(host="acme.test").respond(404)
    report = await read_site(_fetcher(tmp_path), _profile())
    assert any("rendered by JavaScript" in w for w in report.warnings)


async def test_subprocessors_page_is_trusted(tmp_path: Path, respx_mock: respx.MockRouter) -> None:
    respx_mock.get(f"{SITE}/robots.txt").respond(404)
    respx_mock.get(f"{SITE}/subprocessors").respond(200, html=html("Subprocessors: AWS."))
    respx_mock.get(host="acme.test").respond(404)
    report = await read_site(_fetcher(tmp_path), _profile())
    assert [(p.url, p.trust) for p in report.pages] == [(f"{SITE}/subprocessors", True)]


async def test_redirect_to_ats_board(tmp_path: Path, respx_mock: respx.MockRouter) -> None:
    respx_mock.get(f"{SITE}/robots.txt").respond(404)
    respx_mock.get(f"{SITE}/careers").respond(
        302, headers={"Location": "https://jobs.lever.co/acme"}
    )
    respx_mock.get("https://jobs.lever.co/acme").respond(200, html=html("Open roles."))
    respx_mock.get(host="acme.test").respond(404)
    report = await read_site(_fetcher(tmp_path), _profile())
    assert BoardRef(ATSPlatform.LEVER, "acme") in report.board_refs
    assert [p.url for p in report.pages] == ["https://jobs.lever.co/acme"]


async def test_one_failing_page_does_not_lose_the_rest(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get(f"{SITE}/robots.txt").respond(404)
    respx_mock.get(f"{SITE}/security").mock(side_effect=httpx.ConnectError)
    respx_mock.get(f"{SITE}/").respond(200, html=html("Home."))
    respx_mock.get(host="acme.test").respond(404)
    report = await read_site(_fetcher(tmp_path), _profile())
    assert any(w.startswith(f"Could not read {SITE}/security") for w in report.warnings)
    assert [p.url for p in report.pages] == [f"{SITE}/"]
