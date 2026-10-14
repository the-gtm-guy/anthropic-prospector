"""Golden-file regression suite: the 12 fixtures through the full offline pipeline.

Each fixture's wedges, MEDDPICC scores and routing are locked in tests/golden/<domain>.json.
A rule change that moves any of them fails here. Review the change, then refresh with:

    UPDATE_GOLDEN=1 pytest tests/test_golden.py
"""

import json
import os
import socket
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from anthropic_prospector.mock import fixture_domains, fixture_profile, mock_signals
from anthropic_prospector.models import LLMUsage, Recommendation, SDROutboundBrief, WedgeId
from anthropic_prospector.pipeline import MockLLMClient, run_pipeline, to_markdown
from anthropic_prospector.targets import load_targets

GOLDEN = Path(__file__).parent / "golden"
REPO_ROOT = Path(__file__).resolve().parents[1]
UPDATE = os.environ.get("UPDATE_GOLDEN") == "1"
WHEN = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)

# The intended outcome of each fixture scenario, stated independently of the golden files.
SCENARIOS: dict[str, tuple[WedgeId | None, Recommendation]] = {
    "lexiconlegal.example": (WedgeId.PROMPT_CACHING, Recommendation.PURSUE),
    "arroyofinance.example": (WedgeId.PROMPT_CACHING, Recommendation.PURSUE),
    "cascadecompliance.example": (WedgeId.PROMPT_CACHING, Recommendation.PURSUE),
    "tidewater.example": (WedgeId.EXTENDED_THINKING, Recommendation.PURSUE),
    "quartzdev.example": (WedgeId.EXTENDED_THINKING, Recommendation.PURSUE),
    "ridgelinehealth.example": (WedgeId.CLOUD_DRAWDOWN, Recommendation.PURSUE),
    "mesainsure.example": (WedgeId.CLOUD_DRAWDOWN, Recommendation.PURSUE),
    "willamettecommerce.example": (WedgeId.CLOUD_DRAWDOWN, Recommendation.PURSUE),
    "kelplearning.example": (WedgeId.PROMPT_CACHING, Recommendation.NURTURE),
    "hudsonledger.example": (WedgeId.CLOUD_DRAWDOWN, Recommendation.ROUTE_TO_OWNER),
    "fjordsupport.example": (None, Recommendation.ROUTE_TO_AE),
    "saguarofreight.example": (None, Recommendation.DISQUALIFY),
}


def _brief(domain: str) -> SDROutboundBrief:
    profile = fixture_profile(domain)
    assert profile is not None
    brief, _ = run_pipeline(profile, MockLLMClient(), generated_at=WHEN)
    return brief


def summarize(brief: SDROutboundBrief) -> dict[str, Any]:
    card, vp = brief.scorecard, brief.value_props
    return {
        "recommendation": card.recommendation,
        "tier": card.tier,
        "total_score": card.total_score,
        "coverage_pct": card.coverage_pct,
        "primary_wedge": vp.primary_wedge,
        "overall_fit": vp.overall_fit,
        "wedges": {
            w.wedge_id: {
                "fit": w.fit_score,
                "confidence": w.confidence,
                "evidence": w.trigger_evidence_ids,
            }
            for w in vp.wedges
        },
        "suppressions": vp.suppressions,
        "meddpicc": {
            e.element: {"score": e.score, "status": e.status, "evidence": e.evidence_ids}
            for e in card.elements
        },
        "headline": brief.narrative.headline,
    }


@pytest.mark.parametrize("domain", fixture_domains())
def test_fixture_matches_golden(domain: str) -> None:
    actual = json.loads(json.dumps(summarize(_brief(domain))))
    path = GOLDEN / f"{domain}.json"
    if UPDATE:
        path.write_text(json.dumps(actual, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    assert path.exists(), f"no golden file; run UPDATE_GOLDEN=1 pytest {Path(__file__).name}"
    assert actual == json.loads(path.read_text(encoding="utf-8"))


def test_golden_files_match_the_fixtures() -> None:
    assert sorted(p.stem for p in GOLDEN.glob("*.json")) == fixture_domains()
    assert sorted(SCENARIOS) == fixture_domains()


@pytest.mark.parametrize("domain", sorted(SCENARIOS))
def test_scenario_outcome(domain: str) -> None:
    brief = _brief(domain)
    assert (brief.value_props.primary_wedge, brief.scorecard.recommendation) == SCENARIOS[domain]


def test_offline_pipeline_is_free_and_never_touches_the_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("network access during an offline run")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    total = LLMUsage()
    for domain in fixture_domains():
        profile = fixture_profile(domain)
        assert profile is not None
        brief, usage = run_pipeline(profile, MockLLMClient(), generated_at=WHEN)
        assert brief.scorecard.generated_by == "mock"
        total = total + usage
    assert total == LLMUsage()
    assert total.est_cost_usd == 0.0


def test_every_shipped_target_qualifies_offline() -> None:
    batch = load_targets(REPO_ROOT / "targets.csv")
    for profile in batch.profiles:
        profile.tech_stack = mock_signals(profile, collected_at=WHEN)
        brief, usage = run_pipeline(profile, MockLLMClient(), generated_at=WHEN)
        assert usage == LLMUsage()
        assert to_markdown(brief).startswith(f"# {profile.company_name}")
