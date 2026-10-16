"""Snapshot and behaviour tests for the Rich views.

Snapshots live in tests/snapshots/<view>_<width>.txt. After an intended change, review the
diff and refresh them with:

    UPDATE_SNAPSHOTS=1 pytest tests/test_render.py
"""

import asyncio
import io
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from rich.console import Console, RenderableType

from anthropic_prospector.config import Settings
from anthropic_prospector.models import (
    AnalysisResult,
    DataSource,
    LLMUsage,
    RowError,
)
from anthropic_prospector.render import (
    BatchProgress,
    account_view,
    ascii_only,
    banner,
    batch_view,
    doctor_view,
    failures_view,
    scorecard_view,
    usage_view,
)
from anthropic_prospector.service import DataMode, analyze, analyze_batch, rank, resolve_target
from anthropic_prospector.targets import load_targets

SNAPSHOTS = Path(__file__).parent / "snapshots"
REPO_ROOT = Path(__file__).resolve().parents[1]
UPDATE = os.environ.get("UPDATE_SNAPSHOTS") == "1"
NOW = datetime(2026, 10, 1, 16, tzinfo=UTC)
WIDTHS = (60, 80, 120)


class AsciiIO(io.StringIO):
    encoding = "ascii"


def make(width: int, file: io.StringIO | None = None) -> Console:
    return Console(
        file=file or io.StringIO(),
        width=width,
        color_system=None,
        force_terminal=False,
        highlight=False,
        emoji=False,
        legacy_windows=False,
    )


def render(console: Console, *renderables: RenderableType) -> str:
    for item in renderables:
        console.print(item)
    assert isinstance(console.file, io.StringIO)
    return console.file.getvalue()


@pytest.fixture(scope="module")
def result() -> AnalysisResult:
    profile = resolve_target("lexiconlegal.example")
    return asyncio.run(analyze(profile, Settings(), mode=DataMode.OFFLINE, now=NOW))


@pytest.fixture(scope="module")
def ranked() -> list[AnalysisResult]:
    profiles = load_targets(REPO_ROOT / "targets.csv").profiles
    report = asyncio.run(analyze_batch(profiles, Settings(), mode=DataMode.OFFLINE, now=NOW))
    return rank(report.results)


def _scorecard(result: AnalysisResult, ranked: list[AnalysisResult], console: Console) -> str:
    return render(console, scorecard_view(result, console))


def _account(result: AnalysisResult, ranked: list[AnalysisResult], console: Console) -> str:
    return render(console, account_view(result, console))


def _batch(result: AnalysisResult, ranked: list[AnalysisResult], console: Console) -> str:
    rows = list(enumerate(ranked, start=1))[:10]
    return render(
        console,
        banner(data=DataSource.MOCK, llm_model=None, mode="offline"),
        batch_view(rows, console, total=len(ranked)),
        usage_view(LLMUsage(), llm_model=None, data_counts={DataSource.MOCK: len(ranked)}),
    )


VIEWS: dict[str, Callable[[AnalysisResult, list[AnalysisResult], Console], str]] = {
    "scorecard": _scorecard,
    "account": _account,
    "batch": _batch,
}


@pytest.mark.parametrize("width", WIDTHS)
@pytest.mark.parametrize("view", sorted(VIEWS))
def test_snapshot(
    view: str, width: int, result: AnalysisResult, ranked: list[AnalysisResult]
) -> None:
    actual = VIEWS[view](result, ranked, make(width))
    assert all(len(line) <= width for line in actual.splitlines())
    path = SNAPSHOTS / f"{view}_{width}.txt"
    if UPDATE:
        SNAPSHOTS.mkdir(exist_ok=True)
        path.write_text(actual, encoding="utf-8")
    assert path.exists(), f"no snapshot; run UPDATE_SNAPSHOTS=1 pytest {Path(__file__).name}"
    assert actual == path.read_text(encoding="utf-8")


def test_ascii_terminal_uses_ascii_glyphs(result: AnalysisResult) -> None:
    console = make(120, AsciiIO())
    assert ascii_only(console)
    output = render(console, scorecard_view(result, console))
    console = make(120, AsciiIO())
    output += render(console, account_view(result, console))
    for glyph in "✓◐✗○★█░→×╭│":  # noqa: RUF001
        assert glyph not in output
    assert "~ partial" in output or "+ strong" in output


def test_markup_is_never_interpreted(result: AnalysisResult) -> None:
    name = "Evil [bold]Corp[/bold]"
    assert result.brief is not None
    brief = result.brief
    evil = result.model_copy(
        update={
            "company_name": name,
            "brief": brief.model_copy(
                update={"profile": brief.profile.model_copy(update={"company_name": name})}
            ),
        }
    )
    for view in (scorecard_view, account_view):
        console = make(120)
        assert name in render(console, view(evil, console))


def test_failed_result_says_not_analyzed() -> None:
    failed = AnalysisResult(company_name="Zed", domain="zed.example", errors=["boom"])
    for view in (scorecard_view, account_view):
        console = make(120)
        output = render(console, view(failed, console))
        assert "not analyzed" in output
        assert "boom" in output


def test_failures_view() -> None:
    assert failures_view([], []) is None
    table = failures_view([RowError(line=4, domain="x.example", message="bad state")], [])
    assert table is not None
    output = render(make(100), table)
    assert "line 4" in output
    assert "bad state" in output


def test_usage_view() -> None:
    usage = LLMUsage(
        input_tokens=1000, output_tokens=200, cache_read_tokens=3000, est_cost_usd=0.0123
    )
    live = usage_view(usage, llm_model="claude-sonnet-5-5", data_counts={}).plain
    assert "3,000" in live
    assert "75%" in live
    assert "$0.01" in live
    assert "$0.00" in usage_view(usage, llm_model=None, data_counts={}).plain


def test_doctor_view() -> None:
    console = make(100)
    output = render(
        console,
        doctor_view([("a", True, "fine"), ("b", False, "broken"), ("c", None, "fyi")], console),
    )
    assert "ok" in output
    assert "problem" in output
    assert "info" in output


def test_batch_progress_prints_a_line_per_advance(
    result: AnalysisResult, ranked: list[AnalysisResult]
) -> None:
    console = make(100)
    assert result.brief is not None
    odd = result.model_copy(update={"company_name": "[red]X"})
    with BatchProgress(console, 2) as progress:
        progress.advance(result)
        progress.advance(odd)
    output = render(console)
    assert f"[1/2] {result.company_name}: {_outcome(result)}" in output
    assert f"[2/2] [red]X: {_outcome(result)}" in output
    assert "PURSUE" in output.splitlines()[0]


def _outcome(result: AnalysisResult) -> str:
    assert result.brief is not None
    return result.brief.scorecard.recommendation.name.replace("_", " ")


def test_banner() -> None:
    live = banner(data=DataSource.LIVE, llm_model="claude-sonnet-5-5", mode="live").plain
    assert "LIVE" in live
    assert "claude-sonnet-5-5" in live
    assert "none analyzed" in banner(data=None, llm_model=None, mode="offline").plain
