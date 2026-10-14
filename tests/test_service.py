"""The composition root: target resolution, isolated batches, checkpoints, ranking, outputs."""

import csv
import json
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest

from anthropic_prospector.config import Settings
from anthropic_prospector.mock import fixture_profiles, mock_signals
from anthropic_prospector.models import (
    AnalysisResult,
    DataSource,
    LLMUsage,
    Recommendation,
    SDROutboundBrief,
    StartupProfile,
    Tier,
)
from anthropic_prospector.pipeline import AnthropicLLMClient, MockLLMClient, run_pipeline
from anthropic_prospector.pipeline.llm import LLMError, StructuredRequest, T
from anthropic_prospector.service import (
    RANKED_COLUMNS,
    DataMode,
    TargetNotFound,
    analyze,
    analyze_batch,
    batch_data_source,
    diagnose,
    export_brief,
    filter_states,
    load_checkpoint,
    make_llm,
    plan_run,
    rank,
    resolve_target,
    shortlist,
    write_batch_outputs,
)
from anthropic_prospector.targets import load_targets

NOW = datetime(2026, 10, 1, 16, tzinfo=UTC)
TARGETS = load_targets(Path(__file__).resolve().parents[1] / "targets.csv")
OFFLINE = DataMode.OFFLINE
ORDER = [
    Recommendation.PURSUE,
    Recommendation.NURTURE,
    Recommendation.ROUTE_TO_AE,
    Recommendation.ROUTE_TO_OWNER,
    Recommendation.DISQUALIFY,
]


def profiles(count: int | None = None) -> list[StartupProfile]:
    return list(TARGETS.profiles)[:count]


def break_pipeline(monkeypatch: pytest.MonkeyPatch, domain: str | None) -> None:
    """Make run_pipeline raise for `domain` (for every domain when None)."""

    def wrapper(profile: StartupProfile, llm: Any, **kwargs: Any) -> Any:
        if domain is None or profile.domain == domain:
            raise RuntimeError("boom")
        return run_pipeline(profile, llm, **kwargs)

    monkeypatch.setattr("anthropic_prospector.service.run_pipeline", wrapper)


class FailingLLM:
    model_id = "fake"

    def generate(self, request: StructuredRequest[T]) -> tuple[T, LLMUsage]:
        raise LLMError(
            "overloaded", transient=True, usage=LLMUsage(input_tokens=10, est_cost_usd=0.01)
        )


async def full_batch() -> list[AnalysisResult]:
    return (await analyze_batch(profiles(), Settings(), mode=OFFLINE, now=NOW)).results


def brief_of(result: AnalysisResult) -> SDROutboundBrief:
    assert result.brief is not None
    return result.brief


# --- targets ----------------------------------------------------------------------------


def test_resolve_target_from_example_url() -> None:
    profile = resolve_target("https://www.lexiconlegal.example/about")
    assert profile.company_name == "Lexicon Legal AI"
    assert profile.tech_stack is None


def test_resolve_target_batch_wins() -> None:
    renamed = profiles()[0].model_copy(update={"company_name": "Renamed Co"})
    batch = TARGETS.model_copy(update={"profiles": [renamed]})
    assert resolve_target("lexiconlegal.example", batch=batch).company_name == "Renamed Co"


def test_resolve_target_unknown_needs_state() -> None:
    with pytest.raises(TargetNotFound):
        resolve_target("acme-robotics.com")
    profile = resolve_target("acme-robotics.com", hq_state="wa")
    assert (profile.company_name, profile.hq_state) == ("Acme Robotics", "WA")


def test_resolve_target_rejects_non_domain() -> None:
    with pytest.raises(ValueError, match="domain"):
        resolve_target("not a domain!!")


def test_filter_states() -> None:
    kept = filter_states(fixture_profiles(), ["ca", "AZ"])
    assert kept
    assert {p.hq_state for p in kept} <= {"CA", "AZ"}
    assert len(kept) == len([p for p in fixture_profiles() if p.hq_state in {"CA", "AZ"}])


# --- modes ------------------------------------------------------------------------------


def test_plan_without_key_is_mock() -> None:
    settings = Settings()
    assert plan_run(settings, DataMode.AUTO).llm_model is None
    assert isinstance(make_llm(settings, DataMode.AUTO), MockLLMClient)


def test_plan_with_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    settings = Settings()
    assert plan_run(settings, DataMode.AUTO).llm_model == "claude-sonnet-5-5"
    assert isinstance(make_llm(settings, DataMode.AUTO), AnthropicLLMClient)
    assert plan_run(settings, OFFLINE).llm_model is None
    assert isinstance(make_llm(settings, OFFLINE), MockLLMClient)


# --- analysis ---------------------------------------------------------------------------


async def test_analyze_offline() -> None:
    result = await analyze(profiles()[0], Settings(), mode=OFFLINE, now=NOW)
    assert result.ok
    assert brief_of(result).data_source is DataSource.MOCK
    assert result.usage is not None
    assert result.usage.est_cost_usd == 0
    assert {"collect", "pipeline"} <= set(result.timings_ms)
    assert result.errors == []


async def test_analyze_batch_all_targets() -> None:
    seen: list[AnalysisResult] = []
    report = await analyze_batch(
        profiles(), Settings(), mode=OFFLINE, now=NOW, on_result=seen.append
    )
    assert [r.domain for r in report.results] == [p.domain for p in profiles()]
    assert report.failed == []
    assert batch_data_source(report.results) is DataSource.MOCK
    assert len(seen) == len(profiles())


async def test_pipeline_failure_is_isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    victim = profiles()[1].domain
    break_pipeline(monkeypatch, victim)
    report = await analyze_batch(profiles(4), Settings(), mode=OFFLINE, now=NOW)
    for result in report.results:
        if result.domain == victim:
            assert result.brief is None
            assert "Qualification failed: RuntimeError: boom" in result.errors[0]
        else:
            assert result.ok


async def test_collection_failure_is_isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    victim = profiles()[1].domain

    def flaky(profile: StartupProfile, **kwargs: Any) -> Any:
        if profile.domain == victim:
            raise RuntimeError("no signals")
        return mock_signals(profile, **kwargs)

    monkeypatch.setattr("anthropic_prospector.service.mock_signals", flaky)
    report = await analyze_batch(profiles(4), Settings(), mode=OFFLINE, now=NOW)
    for result in report.results:
        if result.domain == victim:
            assert "Signal collection failed" in result.errors[0]
        else:
            assert result.ok


async def test_llm_failure_degrades_to_rules_text() -> None:
    result = await analyze(profiles()[0], Settings(), mode=OFFLINE, llm=FailingLLM(), now=NOW)
    assert result.ok
    assert "Claude call failed" in result.errors[0]
    assert result.usage is not None
    assert result.usage.input_tokens == 10
    assert result.usage.est_cost_usd == pytest.approx(0.01)


async def test_budget_skips_remaining(monkeypatch: pytest.MonkeyPatch) -> None:
    def costly(profile: StartupProfile, llm: Any, **kwargs: Any) -> Any:
        brief, _ = run_pipeline(profile, llm, **kwargs)
        return brief, LLMUsage(est_cost_usd=1.0)

    monkeypatch.setattr("anthropic_prospector.service.run_pipeline", costly)
    report = await analyze_batch(
        profiles(4), Settings(), mode=OFFLINE, concurrency=1, max_cost_usd=1.5, now=NOW
    )
    assert len([r for r in report.results if r.ok]) == 2
    assert len(report.failed) == 2
    assert all("budget" in r.errors[0] for r in report.failed)


# --- checkpoints ------------------------------------------------------------------------


async def test_checkpoint_written_and_loaded(tmp_path: Path) -> None:
    path = tmp_path / "c.jsonl"
    await analyze_batch(profiles(3), Settings(), mode=OFFLINE, checkpoint=path, now=NOW)
    assert len(path.read_text().splitlines()) == 3
    loaded, unreadable = load_checkpoint(path)
    assert len(loaded) == 3
    assert unreadable == 0


async def test_resume_reuses_results(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "c.jsonl"
    await analyze_batch(profiles(3), Settings(), mode=OFFLINE, checkpoint=path, now=NOW)
    break_pipeline(monkeypatch, None)
    seen: list[AnalysisResult] = []
    report = await analyze_batch(
        profiles(3),
        Settings(),
        mode=OFFLINE,
        checkpoint=path,
        resume=True,
        on_result=seen.append,
        now=NOW,
    )
    assert all(r.ok for r in report.results)
    assert report.resumed == {p.domain for p in profiles(3)}
    assert len(seen) == 3
    assert report.usage == LLMUsage()


async def test_resume_retries_failures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "c.jsonl"
    victim = profiles()[0].domain
    with monkeypatch.context() as patch:
        break_pipeline(patch, victim)
        first = await analyze_batch(profiles(3), Settings(), mode=OFFLINE, checkpoint=path, now=NOW)
    assert [r.domain for r in first.failed] == [victim]
    report = await analyze_batch(
        profiles(3), Settings(), mode=OFFLINE, checkpoint=path, resume=True, now=NOW
    )
    assert all(r.ok for r in report.results)
    assert victim not in report.resumed
    assert load_checkpoint(path)[0][victim].ok


async def test_unreadable_checkpoint_line(tmp_path: Path) -> None:
    path = tmp_path / "c.jsonl"
    await analyze_batch(profiles(1), Settings(), mode=OFFLINE, checkpoint=path, now=NOW)
    with path.open("a") as f:
        f.write('{"company_name": "x"')
    assert load_checkpoint(path)[1] == 1
    report = await analyze_batch(
        profiles(1), Settings(), mode=OFFLINE, checkpoint=path, resume=True, now=NOW
    )
    assert any("unreadable" in note for note in report.notes)


async def test_no_resume_starts_afresh(tmp_path: Path) -> None:
    path = tmp_path / "c.jsonl"
    for _ in range(2):
        await analyze_batch(profiles(3), Settings(), mode=OFFLINE, checkpoint=path, now=NOW)
    assert len(path.read_text().splitlines()) == 3


# --- ranking and outputs ----------------------------------------------------------------


async def test_rank_orders_by_recommendation_then_fit() -> None:
    failed = AnalysisResult(company_name="Zed", domain="zed.example", errors=["x"])
    ranked = rank([failed, *await full_batch()])
    assert ranked[-1] is failed
    analyzed = [brief_of(r) for r in ranked[:-1]]
    positions = [ORDER.index(b.scorecard.recommendation) for b in analyzed]
    assert positions == sorted(positions)
    for a, b in pairwise(analyzed):
        if a.scorecard.recommendation == b.scorecard.recommendation:
            assert a.value_props.overall_fit >= b.value_props.overall_fit


async def test_shortlist() -> None:
    failed = AnalysisResult(company_name="Zed", domain="zed.example", errors=["x"])
    ranked = rank([failed, *await full_batch()])
    top_tiers = shortlist(ranked, min_tier=Tier.C)
    assert all(brief_of(r).scorecard.tier in {Tier.A, Tier.B, Tier.C} for r in top_tiers)
    assert len(shortlist(ranked, top=3)) == 3
    assert failed not in shortlist(ranked)


async def test_batch_data_source() -> None:
    results = (await analyze_batch(profiles(2), Settings(), mode=OFFLINE, now=NOW)).results
    assert batch_data_source([]) is None
    assert batch_data_source(results) is DataSource.MOCK
    live = results[0].model_copy(
        update={"brief": brief_of(results[0]).model_copy(update={"data_source": DataSource.LIVE})}
    )
    assert batch_data_source([live, results[1]]) is DataSource.HYBRID


async def test_export_brief(tmp_path: Path) -> None:
    brief = brief_of(await analyze(profiles()[0], Settings(), mode=OFFLINE, now=NOW))

    written = export_brief(brief, tmp_path)
    assert written == tmp_path / "lexiconlegal-example.md"
    assert "ILLUSTRATIVE" in written.read_text()

    as_json = export_brief(brief, tmp_path / "out" / "brief.json")
    assert "scorecard" in json.loads(as_json.read_text())

    with pytest.raises(FileExistsError):
        export_brief(brief, as_json)
    as_json.write_text("old")
    export_brief(brief, as_json, force=True)
    assert "scorecard" in json.loads(as_json.read_text())

    with pytest.raises(ValueError, match="format is json"):
        export_brief(brief, tmp_path / "x.md", fmt="json")


async def test_write_batch_outputs(tmp_path: Path) -> None:
    ranked = rank(await full_batch())
    outputs = write_batch_outputs(ranked, ranked[:2], tmp_path)
    with outputs.ranked_csv.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    assert tuple(reader.fieldnames or ()) == RANKED_COLUMNS
    assert len(rows) == len(ranked)
    assert [bool(row["brief"]) for row in rows] == [True, True] + [False] * (len(ranked) - 2)
    assert len(outputs.briefs) == 2
    assert all(
        (tmp_path / row["brief"]).is_file()
        and (tmp_path / "briefs") in (tmp_path / row["brief"]).parents
        for row in rows
        if row["brief"]
    )


# --- doctor -----------------------------------------------------------------------------


def test_diagnose(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROSPECTOR_CACHE_DIR", str(tmp_path))
    checks = {c.name: c for c in diagnose(Settings())}
    assert {"Anthropic API key", "Model", "Cache"} <= set(checks)
    assert checks["Anthropic API key"].ok is None
    assert checks["Cache"].ok is True
