"""Contract tests for the ATS adapters, run against recorded payloads."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from anthropic_prospector.models import ATSPlatform, JobPosting
from anthropic_prospector.scrapers.ats.ashby import AshbyAdapter
from anthropic_prospector.scrapers.ats.base import ATSAdapter, ParsedBoard
from anthropic_prospector.scrapers.ats.greenhouse import GreenhouseAdapter
from anthropic_prospector.scrapers.ats.lever import LeverAdapter

_FIXTURES = Path(__file__).parent / "fixtures" / "ats"

GARBAGE: list[Any] = [None, {}, [], "text", {"jobs": None}, {"jobs": "x"}, [1, "a", None]]
ADAPTERS: list[ATSAdapter] = [GreenhouseAdapter(), LeverAdapter(), AshbyAdapter()]


def _load(name: str) -> Any:
    return json.loads((_FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _by_title(board: ParsedBoard) -> dict[str, JobPosting]:
    return {p.title: p for p in board.postings}


def _assert_clean_text(posting: JobPosting) -> None:
    assert "<" not in posting.description_text
    assert "trackHiringFunnel" not in posting.description_text
    assert "track()" not in posting.description_text
    assert "color:red" not in posting.description_text


@pytest.mark.parametrize("adapter", ADAPTERS)
@pytest.mark.parametrize("payload", GARBAGE)
def test_garbage_payload_is_empty_board(adapter: ATSAdapter, payload: Any) -> None:
    assert adapter.parse(payload) == ParsedBoard()


# ------------------------------------------------------------------ greenhouse


def test_greenhouse_board_url() -> None:
    assert GreenhouseAdapter().board_url("examplecorp") == (
        "https://boards-api.greenhouse.io/v1/boards/examplecorp/jobs?content=true"
    )


def test_greenhouse_summary_url() -> None:
    assert GreenhouseAdapter().summary_url("acme") == (
        "https://boards-api.greenhouse.io/v1/boards/acme/jobs"
    )


def test_lever_and_ashby_have_no_summary_url() -> None:
    assert LeverAdapter().summary_url("acme") is None
    assert AshbyAdapter().summary_url("acme") is None


def test_greenhouse_parses_summary_payload() -> None:
    payload = {
        "jobs": [
            {
                "id": 7,
                "title": "ML Engineer",
                "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/7",
                "first_published": "2026-01-02T03:04:05-05:00",
                "location": {"name": "Remote"},
            }
        ]
    }
    board = GreenhouseAdapter().parse(payload)
    assert len(board.postings) == 1
    assert board.postings[0].description_text == ""
    assert board.postings[0].title == "ML Engineer"
    assert board.skipped == 0


def test_greenhouse_parse_counts_and_platform() -> None:
    board = GreenhouseAdapter().parse(_load("greenhouse_board"))
    assert len(board.postings) == 3
    assert board.skipped == 2
    assert {p.ats for p in board.postings} == {ATSPlatform.GREENHOUSE}


def test_greenhouse_ai_role_normalized() -> None:
    posting = _by_title(GreenhouseAdapter().parse(_load("greenhouse_board")))["Senior AI Engineer"]
    assert posting.external_id == "4012345001"
    assert posting.url == "https://boards.greenhouse.io/examplecorp/jobs/4012345001"
    assert posting.location == "San Francisco, CA"
    assert posting.department == "Engineering"
    assert posting.posted_at == datetime(2025, 3, 10, 16, 30, tzinfo=UTC)
    assert posting.posted_at is not None
    assert posting.posted_at.utcoffset() == timedelta(0)
    assert "RAG" in posting.description_text
    assert "LangChain" in posting.description_text
    _assert_clean_text(posting)


def test_greenhouse_drift_case() -> None:
    posting = _by_title(GreenhouseAdapter().parse(_load("greenhouse_board")))["Account Executive"]
    assert posting.location is None
    assert posting.department is None
    assert posting.posted_at == datetime(2025, 2, 1, 12, 0, tzinfo=UTC)
    assert "Enterprise SaaS" in posting.description_text
    assert "Forecasting" in posting.description_text
    _assert_clean_text(posting)


def test_greenhouse_missing_dates_are_none() -> None:
    posting = _by_title(GreenhouseAdapter().parse(_load("greenhouse_board")))["Office Manager"]
    assert posting.posted_at is None
    assert posting.department == "Operations"


# ------------------------------------------------------------------ lever


def test_lever_board_url() -> None:
    assert LeverAdapter().board_url("examplecorp") == (
        "https://api.lever.co/v0/postings/examplecorp?mode=json"
    )


def test_lever_eu_board_url() -> None:
    assert LeverAdapter(eu=True).board_url("examplecorp") == (
        "https://api.eu.lever.co/v0/postings/examplecorp?mode=json"
    )


def test_lever_parse_counts_and_platform() -> None:
    board = LeverAdapter().parse(_load("lever_board"))
    assert len(board.postings) == 2
    assert board.skipped == 2
    assert {p.ats for p in board.postings} == {ATSPlatform.LEVER}


def test_lever_ai_role_normalized() -> None:
    posting = _by_title(LeverAdapter().parse(_load("lever_board")))["Machine Learning Engineer"]
    assert posting.external_id == "a1b2c3d4-0000-4000-8000-000000000001"
    assert posting.url.startswith("https://jobs.lever.co/examplecorp/")
    assert posting.location == "New York, NY"
    assert posting.department == "Engineering"
    assert "RAG" in posting.description_text
    assert "What you'll do" in posting.description_text
    assert "Write evals" in posting.description_text
    assert posting.description_text.endswith("We are an equal opportunity employer.")
    _assert_clean_text(posting)


def test_lever_epoch_ms_converts_to_utc() -> None:
    posting = _by_title(LeverAdapter().parse(_load("lever_board")))["Machine Learning Engineer"]
    assert posting.posted_at == datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC)
    assert posting.posted_at is not None
    assert posting.posted_at.utcoffset() == timedelta(0)


def test_lever_html_only_posting_without_created_at() -> None:
    posting = _by_title(LeverAdapter().parse(_load("lever_board")))["Account Executive"]
    assert posting.posted_at is None
    assert posting.location is None
    assert posting.department == "Sales"  # falls back to team
    assert "Close enterprise deals." in posting.description_text
    assert "Competitive commission." in posting.description_text
    _assert_clean_text(posting)


# ------------------------------------------------------------------ ashby


def test_ashby_board_url() -> None:
    assert AshbyAdapter().board_url("examplecorp") == (
        "https://api.ashbyhq.com/posting-api/job-board/examplecorp?includeCompensation=false"
    )


def test_ashby_parse_counts_and_platform() -> None:
    board = AshbyAdapter().parse(_load("ashby_board"))
    assert len(board.postings) == 2
    assert board.skipped == 2  # unlisted job is neither a posting nor a skip
    assert {p.ats for p in board.postings} == {ATSPlatform.ASHBY}
    assert "Hidden Role" not in _by_title(board)


def test_ashby_ai_role_normalized() -> None:
    posting = _by_title(AshbyAdapter().parse(_load("ashby_board")))["AI Research Engineer"]
    assert posting.external_id == "b1b2c3d4-0000-4000-8000-000000000001"
    assert (
        posting.url == "https://jobs.ashbyhq.com/examplecorp/b1b2c3d4-0000-4000-8000-000000000001"
    )
    assert posting.location == "Remote - US"
    assert posting.department == "Engineering"
    assert posting.posted_at == datetime(2025, 4, 1, 6, 0, tzinfo=UTC)
    assert posting.posted_at is not None
    assert posting.posted_at.utcoffset() == timedelta(0)
    assert "RAG" in posting.description_text
    _assert_clean_text(posting)


def test_ashby_html_only_and_apply_url_only() -> None:
    posting = _by_title(AshbyAdapter().parse(_load("ashby_board")))["Account Executive"]
    assert posting.url.endswith("/application")
    assert posting.location is None
    assert posting.department == "Sales"  # falls back to team
    assert posting.posted_at == datetime(2025, 1, 15, tzinfo=UTC)
    assert "Sell to mid-market teams." in posting.description_text
    assert "Pipeline" in posting.description_text
    _assert_clean_text(posting)
