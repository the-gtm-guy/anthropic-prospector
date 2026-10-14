"""Board discovery: link parsing, slug guessing, company matching and find_board()."""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from anthropic_prospector.config import Settings
from anthropic_prospector.models import ATSPlatform, JobPosting, StartupProfile
from anthropic_prospector.scrapers.ats import (
    BoardRef,
    board_links,
    find_board,
    guess_slugs,
    mentions_company,
)
from anthropic_prospector.scrapers.http import DiskCache, Fetcher

_FIXTURES = Path(__file__).parent / "fixtures" / "ats"
GH = ATSPlatform.GREENHOUSE
LEVER = ATSPlatform.LEVER
ASHBY = ATSPlatform.ASHBY


def _fixture(name: str) -> Any:
    return json.loads((_FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


async def _no_sleep(seconds: float) -> None:
    return None


def _fetcher(tmp_path: Path) -> Fetcher:
    return Fetcher(
        Settings(),
        client=httpx.AsyncClient(follow_redirects=True),
        cache=DiskCache(tmp_path, ttl_s=0),
        sleep=_no_sleep,
    )


def _profile(**kwargs: Any) -> StartupProfile:
    return StartupProfile(
        company_name="Acme Robotics", domain="acmerobotics.com", hq_state="CA", **kwargs
    )


def _gh_board(*texts: str) -> dict[str, Any]:
    return {
        "jobs": [
            {
                "id": i,
                "title": "Engineer",
                "absolute_url": f"https://boards.greenhouse.io/x/jobs/{i}",
                "content": text,
            }
            for i, text in enumerate(texts, start=1)
        ]
    }


def _posting(*, url: str = "https://boards.greenhouse.io/x/jobs/1", text: str = "") -> JobPosting:
    return JobPosting(ats=GH, external_id="1", title="Engineer", url=url, description_text=text)


GH_API = "boards-api.greenhouse.io"
LEVER_API = "api.lever.co"
LEVER_EU_API = "api.eu.lever.co"
ASHBY_API = "api.ashbyhq.com"


# ------------------------------------------------------------------ board_links


@pytest.mark.parametrize(
    ("markup", "expected"),
    [
        ('<a href="https://boards.greenhouse.io/acme/jobs/123">', [BoardRef(GH, "acme")]),
        ("https://job-boards.greenhouse.io/acme", [BoardRef(GH, "acme")]),
        (
            '<script src="https://boards.greenhouse.io/embed/job_board/js?for=acme"></script>',
            [BoardRef(GH, "acme")],
        ),
        (
            "https://boards.greenhouse.io/embed/job_board?b=x&amp;for=acme",
            [BoardRef(GH, "acme")],
        ),
        ("https://boards-api.greenhouse.io/v1/boards/acme/jobs", [BoardRef(GH, "acme")]),
        ("https://jobs.lever.co/acme/abc-123", [BoardRef(LEVER, "acme", eu=False)]),
        ("https://jobs.eu.lever.co/acme", [BoardRef(LEVER, "acme", eu=True)]),
        ("https://api.lever.co/v0/postings/acme?mode=json", [BoardRef(LEVER, "acme")]),
        ("Apply at jobs.ashbyhq.com/acme.", [BoardRef(ASHBY, "acme")]),
        ("https://api.ashbyhq.com/posting-api/job-board/acme", [BoardRef(ASHBY, "acme")]),
        ("<a href='https://example.com/careers'>Careers</a>", []),
        (
            "https://jobs.lever.co/acme https://boards.greenhouse.io/acme "
            "https://jobs.lever.co/acme",
            [BoardRef(LEVER, "acme"), BoardRef(GH, "acme")],
        ),
    ],
)
def test_board_links(markup: str, expected: list[BoardRef]) -> None:
    assert board_links(markup) == expected


# ------------------------------------------------------------------ guess_slugs


def test_guess_slugs() -> None:
    lexicon = StartupProfile(
        company_name="Lexicon Legal AI", domain="lexiconlegal.com", hq_state="CA"
    )
    assert guess_slugs(lexicon) == ["lexiconlegalai", "lexiconlegal", "lexicon-legal-ai"]
    kelp = StartupProfile(company_name="Kelp", domain="kelp.io", hq_state="CA")
    assert guess_slugs(kelp) == ["kelp"]


# ------------------------------------------------------------------ mentions_company


@pytest.mark.parametrize(
    ("posting", "expected"),
    [
        (_posting(url="https://acmerobotics.com/jobs/1"), True),
        (_posting(url="https://careers.acmerobotics.com/jobs/1"), True),
        (_posting(text="Join Acme Robotics and build arms."), True),
        (_posting(text="Join Acme\n  Robotics and build arms."), True),
        (_posting(text="Details at acmerobotics.com/about."), True),
        (_posting(text="Globex Corporation builds widgets."), False),
    ],
)
def test_mentions_company(posting: JobPosting, expected: bool) -> None:
    profile = StartupProfile(
        company_name="Acme Robotics Labs", domain="acmerobotics.com", hq_state="CA"
    )
    assert mentions_company([posting], profile) is expected


# ------------------------------------------------------------------ find_board


async def test_explicit_token_with_hint_requests_only_that_platform(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    gh = respx_mock.get(host=GH_API).respond(200, json=_fixture("greenhouse_board"))
    other = respx_mock.get(host=LEVER_API).respond(404)
    ashby = respx_mock.get(host=ASHBY_API).respond(404)
    lookup = await find_board(
        _fetcher(tmp_path), _profile(ats_hint=GH, ats_board_token="examplecorp")
    )
    assert lookup.board is not None
    assert lookup.board.ref == BoardRef(GH, "examplecorp")
    assert len(lookup.board.postings) == 3
    assert lookup.reached
    assert not any("No public" in w for w in lookup.warnings)
    assert gh.call_count == 1
    assert not other.called
    assert not ashby.called


async def test_explicit_token_without_hint_tries_platforms_in_order(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    gh = respx_mock.get(host=GH_API).respond(404)
    lever = respx_mock.get(host=LEVER_API).respond(200, json=_fixture("lever_board"))
    ashby = respx_mock.get(host=ASHBY_API).respond(404)
    lookup = await find_board(_fetcher(tmp_path), _profile(ats_board_token="examplecorp"))
    assert lookup.board is not None
    assert lookup.board.ref == BoardRef(LEVER, "examplecorp")
    assert gh.called
    assert lever.called
    assert not ashby.called


async def test_lever_hint_falls_back_to_eu_host(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    us = respx_mock.get(host=LEVER_API).respond(404)
    eu = respx_mock.get(host=LEVER_EU_API).respond(200, json=_fixture("lever_board"))
    lookup = await find_board(
        _fetcher(tmp_path), _profile(ats_hint=LEVER, ats_board_token="examplecorp")
    )
    assert lookup.board is not None
    assert lookup.board.ref.eu is True
    assert us.called
    assert eu.called


async def test_linked_refs_beat_guesses(tmp_path: Path, respx_mock: respx.MockRouter) -> None:
    ashby = respx_mock.get(host=ASHBY_API, path="/posting-api/job-board/acme-co").respond(
        200, json=_fixture("ashby_board")
    )
    guesses = respx_mock.get(host__regex=r"boards-api\.greenhouse\.io|api\.lever\.co").respond(404)
    lookup = await find_board(_fetcher(tmp_path), _profile(), linked=[BoardRef(ASHBY, "acme-co")])
    assert lookup.board is not None
    assert lookup.board.ref == BoardRef(ASHBY, "acme-co")
    assert ashby.call_count == 1
    assert not guesses.called


async def test_guessed_board_accepted_when_posting_names_company(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get(host=GH_API, path="/v1/boards/acmerobotics/jobs").respond(
        200, json=_gh_board("Acme Robotics builds arms.")
    )
    respx_mock.get(host__regex=r".*").respond(404)
    lookup = await find_board(_fetcher(tmp_path), _profile())
    assert lookup.board is not None
    assert lookup.board.ref == BoardRef(GH, "acmerobotics")


async def test_guessed_board_for_another_company_is_ignored(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get(host=GH_API, path="/v1/boards/acmerobotics/jobs").respond(
        200, json=_gh_board("Globex Corporation builds widgets.")
    )
    respx_mock.get(host__regex=r".*").respond(404)
    lookup = await find_board(_fetcher(tmp_path), _profile())
    assert lookup.board is None
    assert lookup.reached
    assert any(w.startswith("Ignored the") for w in lookup.warnings)
    assert lookup.warnings[-1].startswith("No public Greenhouse, Lever or Ashby job board")


async def test_empty_guessed_board_is_ignored_quietly(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get(host=GH_API, path="/v1/boards/acmerobotics/jobs").respond(200, json={"jobs": []})
    respx_mock.get(host__regex=r".*").respond(404)
    lookup = await find_board(_fetcher(tmp_path), _profile())
    assert lookup.board is None
    assert not any("Ignored" in w for w in lookup.warnings)


async def test_unreachable_apis(tmp_path: Path, respx_mock: respx.MockRouter) -> None:
    respx_mock.route().mock(side_effect=httpx.ConnectError)
    lookup = await find_board(_fetcher(tmp_path), _profile())
    assert lookup.board is None
    assert not lookup.reached
    assert any("Could not read the" in w for w in lookup.warnings)


async def test_http_403_warns_and_moves_on(tmp_path: Path, respx_mock: respx.MockRouter) -> None:
    respx_mock.get(host=GH_API).respond(403)
    respx_mock.get(host=LEVER_API).respond(200, json=_fixture("lever_board"))
    lookup = await find_board(_fetcher(tmp_path), _profile(ats_board_token="examplecorp"))
    assert any("answered HTTP 403" in w for w in lookup.warnings)
    assert lookup.board is not None
    assert lookup.board.ref.platform is LEVER


async def test_unreadable_postings_are_counted(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get(host=GH_API).respond(200, json=_fixture("greenhouse_board"))
    lookup = await find_board(
        _fetcher(tmp_path), _profile(ats_hint=GH, ats_board_token="examplecorp")
    )
    assert lookup.board is not None
    assert lookup.board.skipped > 0
    assert any("could not be read" in w for w in lookup.warnings)
    assert lookup.board.total_roles == len(lookup.board.postings) + lookup.board.skipped


async def test_too_large_greenhouse_board_falls_back_to_titles(
    tmp_path: Path, respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("anthropic_prospector.scrapers.ats.BOARD_MAX_BYTES", 2000)
    summary = "https://boards-api.greenhouse.io/v1/boards/acme/jobs"
    respx_mock.get(summary, params={"content": "true"}).respond(
        200, json=_gh_board(*["x" * 100] * 50)
    )
    respx_mock.get(summary, params=None).respond(
        200,
        json={
            "jobs": [
                {"id": 1, "title": "Engineer", "absolute_url": "https://boards.greenhouse.io/a/1"}
            ]
        },
    )
    lookup = await find_board(_fetcher(tmp_path), _profile(ats_hint=GH, ats_board_token="acme"))
    assert lookup.board is not None
    assert len(lookup.board.postings) == 1
    assert lookup.board.api_url == summary
    assert any("too large to read in full" in w for w in lookup.warnings)


async def test_too_large_board_without_summary_is_a_warning(
    tmp_path: Path, respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("anthropic_prospector.scrapers.ats.BOARD_MAX_BYTES", 2000)
    big = [{"id": str(i), "text": "x" * 100} for i in range(50)]
    respx_mock.get(host=LEVER_API).respond(200, json=big)
    respx_mock.get(host=LEVER_EU_API).respond(200, json=big)
    respx_mock.get(host__regex=r".*").respond(404)
    lookup = await find_board(_fetcher(tmp_path), _profile(ats_hint=LEVER, ats_board_token="acme"))
    assert lookup.board is None
    assert lookup.reached
    assert any("larger than" in w for w in lookup.warnings)


async def test_non_json_body_warns_but_counts_as_reached(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get(host=GH_API).respond(200, text="<html>not json</html>")
    respx_mock.get(host__regex=r".*").respond(404)
    lookup = await find_board(_fetcher(tmp_path), _profile(ats_hint=GH, ats_board_token="acme"))
    assert any("Could not read the" in w for w in lookup.warnings)
    assert lookup.reached
