"""Contract tests for models.py: validation rules, computed fields, schemas and round-trips."""

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta, timezone
from enum import StrEnum
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from anthropic_prospector import models
from anthropic_prospector.models import (
    DISCLAIMER,
    MEDDPICC_WEIGHTS,
    TERRITORY_STATES,
    US_STATES,
    WEDGE_PRIORITY,
    AnalysisResult,
    AnthropicValueProps,
    ATSPlatform,
    BriefNarrative,
    Channel,
    CloudProvider,
    CompetitorKind,
    DataSource,
    ElementRefinement,
    ElementScore,
    ElementStatus,
    Evidence,
    FundingStage,
    Health,
    ImpactEstimate,
    JobPosting,
    LLMUsage,
    MEDDPICCElement,
    MEDDPICCScorecard,
    ObjectionHandle,
    OutboundTouch,
    Persona,
    PersonaTarget,
    Recommendation,
    ScorecardRefinement,
    SDROutboundBrief,
    StartupProfile,
    TechStackSignals,
    Tier,
    WedgeId,
    WedgeMatch,
    clip,
    normalize_domain,
    normalize_state,
)

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
PAIN = MEDDPICCElement.IDENTIFY_PAIN
COMPETITION = MEDDPICCElement.COMPETITION
METRICS = MEDDPICCElement.METRICS
PAPER = MEDDPICCElement.PAPER_PROCESS

# --------------------------------------------------------------------------- builders


def make_evidence(n: int = 1, **overrides: Any) -> Evidence:
    data: dict[str, Any] = {
        "id": f"E{n}",
        "kind": "job_posting",
        "source_url": f"https://boards.greenhouse.io/acme/jobs/{n}",
        "snippet": "Build LLM features with LangChain and the OpenAI API.",
        "observed_at": NOW,
    }
    return Evidence.model_validate(data | overrides)


def make_posting(n: int = 1, **overrides: Any) -> JobPosting:
    data: dict[str, Any] = {
        "ats": "greenhouse",
        "external_id": str(4000 + n),
        "title": "Senior ML Engineer, LLM Platform",
        "url": f"https://boards.greenhouse.io/acme/jobs/{4000 + n}",
        "location": "San Francisco, CA",
        "description_text": "Own our RAG pipeline, evals and inference cost.",
    }
    return JobPosting.model_validate(data | overrides)


def make_tech_stack(**overrides: Any) -> TechStackSignals:
    data: dict[str, Any] = {
        "domain": "acme.example",
        "ats": "greenhouse",
        "ats_board_token": "acme",
        "total_open_roles": 12,
        "ai_role_count": 3,
        "ai_roles": [make_posting()],
        "cloud": [{"provider": "aws", "confidence": 0.85, "evidence_ids": ["E2"]}],
        "primary_cloud": "aws",
        "competitors": [{"kind": "openai", "confidence": 0.7, "evidence_ids": ["E1"]}],
        "keyword_hits": {"rag": 3, "evals": 1},
        "evidence": [
            make_evidence(1),
            make_evidence(2, kind="dns", source_url=None, snippet="app CNAME elb.amazonaws.com"),
        ],
        "data_source": "mock",
        "collected_at": NOW,
    }
    return TechStackSignals.model_validate(data | overrides)


def make_profile(**overrides: Any) -> StartupProfile:
    data: dict[str, Any] = {
        "company_name": "Acme AI",
        "domain": "acme.example",
        "hq_city": "San Francisco",
        "hq_state": "CA",
        "vertical": "Legal tech",
        "employee_count": 85,
        "funding_stage": "series_b",
    }
    return StartupProfile.model_validate(data | overrides)


def make_wedge(wedge_id: WedgeId, fit: int, **overrides: Any) -> WedgeMatch:
    data: dict[str, Any] = {
        "wedge_id": wedge_id,
        "title": f"{wedge_id} wedge",
        "fit_score": fit,
        "confidence": 0.6,
        "trigger_evidence_ids": ["E1"],
        "hypothesis": "Repeated long prompts are re-billed on every call.",
    }
    return WedgeMatch.model_validate(data | overrides)


def make_value_props(**overrides: Any) -> AnthropicValueProps:
    data: dict[str, Any] = {
        "domain": "acme.example",
        "wedges": [
            make_wedge(WedgeId.PROMPT_CACHING, 80),
            make_wedge(WedgeId.CLOUD_DRAWDOWN, 65, trigger_evidence_ids=["E2"]),
        ],
        "primary_wedge": "prompt_caching",
        "overall_fit": 74,
        "rationale": "OpenAI incumbent with long repeated prompts, running on AWS.",
    }
    return AnthropicValueProps.model_validate(data | overrides)


def make_element(element: MEDDPICCElement, score: int | None, **overrides: Any) -> ElementScore:
    data: dict[str, Any] = {
        "element": element,
        "score": score,
        "status": "unknown" if score is None else "hypothesized",
        "rationale": "Inferred from public signals.",
        "next_action": "Confirm in discovery.",
        "confidence": 0.0 if score is None else 0.5,
    }
    return ElementScore.model_validate(data | overrides)


def make_scorecard(
    scores: Mapping[MEDDPICCElement, int | None] | None = None, **overrides: Any
) -> MEDDPICCScorecard:
    scores = scores or {}
    data: dict[str, Any] = {
        "domain": "acme.example",
        "elements": [make_element(e, scores.get(e)) for e in MEDDPICCElement],
        "recommendation": "pursue",
        "summary": "Clear pain signal; economic buyer unknown.",
        "generated_by": "rules",
        "data_source": "mock",
    }
    return MEDDPICCScorecard.model_validate(data | overrides)


def make_touch(step: int, channel: str, day: int, **overrides: Any) -> OutboundTouch:
    data: dict[str, Any] = {
        "step": step,
        "channel": channel,
        "day_offset": day,
        "subject": "Prompt caching for Acme's RAG costs" if channel == "email" else None,
        "body": "Saw you're hiring for LLM platform work.",
        "cta": "Worth a 20-minute look?",
    }
    return OutboundTouch.model_validate(data | overrides)


def make_narrative(**overrides: Any) -> BriefNarrative:
    data: dict[str, Any] = {
        "headline": "Acme is scaling RAG on OpenAI; caching could recover margin",
        "why_now": ["Series B raise", "3 open LLM platform roles"],
        "talk_track": "Lead with inference cost, then quality on long documents.",
        "call_opener": "You're hiring two LLM platform engineers. Is inference cost on the list?",
        "personas": [
            {"persona": "ai_ml_lead", "title_patterns": ["Head of AI"], "angle": "Quality"}
        ],
        "touches": [
            make_touch(1, "email", 0),
            make_touch(2, "linkedin", 2),
            make_touch(3, "call", 5),
        ],
        "objections": [{"objection": "We're locked into OpenAI.", "response": "Run a side test."}],
        "discovery_questions": ["What share of each prompt repeats across calls?"],
    }
    return BriefNarrative.model_validate(data | overrides)


def make_brief(**overrides: Any) -> SDROutboundBrief:
    elements = [make_element(e, None) for e in MEDDPICCElement if e is not PAIN]
    elements.append(make_element(PAIN, 8, evidence_ids=["E1"]))
    data: dict[str, Any] = {
        "generated_at": NOW,
        "profile": make_profile(tech_stack=make_tech_stack()),
        "value_props": make_value_props(),
        "scorecard": make_scorecard(elements=elements),
        "narrative": make_narrative(),
        "evidence": make_tech_stack().evidence,
        "data_source": "mock",
    }
    return SDROutboundBrief.model_validate(data | overrides)


def make_result(**overrides: Any) -> AnalysisResult:
    data: dict[str, Any] = {
        "company_name": "Acme AI",
        "domain": "acme.example",
        "brief": make_brief(),
        "timings_ms": {"collect": 120, "score": 4},
        "usage": LLMUsage(input_tokens=1200, output_tokens=300, cache_read_tokens=900),
    }
    return AnalysisResult.model_validate(data | overrides)


# --------------------------------------------------------------------------- module surface


def test_public_names_exist() -> None:
    for name in models.__all__:
        assert hasattr(models, name), name


@pytest.mark.parametrize(
    ("enum", "values"),
    [
        (DataSource, ["live", "mock", "hybrid"]),
        (ATSPlatform, ["greenhouse", "lever", "ashby", "unknown"]),
        (CloudProvider, ["aws", "gcp", "azure", "multi", "unknown"]),
        (
            CompetitorKind,
            ["openai", "langchain", "vllm", "azure_openai", "other_llm", "anthropic_existing"],
        ),
        (WedgeId, ["prompt_caching", "extended_thinking", "cloud_drawdown"]),
        (FundingStage, ["pre_seed", "seed", "series_a", "series_b", "series_c_plus", "unknown"]),
        (
            MEDDPICCElement,
            [
                "metrics",
                "economic_buyer",
                "decision_criteria",
                "decision_process",
                "paper_process",
                "identify_pain",
                "champion",
                "competition",
            ],
        ),
        (ElementStatus, ["unknown", "hypothesized", "validated"]),
        (Health, ["green", "yellow", "red", "grey"]),
        (Tier, ["A", "B", "C", "D"]),
        (Recommendation, ["pursue", "nurture", "disqualify", "route_to_ae"]),
        (Persona, ["eng_leader", "ai_ml_lead", "cto_founder", "finance", "procurement"]),
        (Channel, ["email", "linkedin", "call"]),
    ],
    ids=lambda v: v.__name__ if isinstance(v, type) else "",
)
def test_enum_values_are_stable(enum: type[StrEnum], values: list[str]) -> None:
    # Values are persisted in JSON, CSV and LLM schemas; renaming one is a breaking change.
    assert [member.value for member in enum] == values


def test_every_contract_keeps_the_strict_config() -> None:
    # A subclass that sets its own model_config must still inherit the contract settings.
    contracts = [
        obj
        for name in models.__all__
        if isinstance(obj := getattr(models, name), type)
        and issubclass(obj, BaseModel)
        and obj not in LLM_SCHEMAS
    ]
    assert MEDDPICCScorecard in contracts
    for contract in contracts:
        assert contract.model_config.get("extra") == "forbid", contract
        assert contract.model_config.get("validate_assignment") is True, contract


def test_domain_rules_are_complete() -> None:
    assert sum(MEDDPICC_WEIGHTS.values()) == 100
    assert set(MEDDPICC_WEIGHTS) == set(MEDDPICCElement)
    assert sorted(WEDGE_PRIORITY) == sorted(WedgeId)  # every wedge has a tie-break rank
    assert {"CA", "WA", "OR", "AZ"} == TERRITORY_STATES
    assert len(US_STATES) == 51  # 50 states + DC
    assert set(US_STATES) >= TERRITORY_STATES


# --------------------------------------------------------------------------- normalizers


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("acme.example", "acme.example"),
        ("HTTPS://WWW.Acme.Example/careers?ref=x#top", "acme.example"),
        ("http://acme.example:8443/", "acme.example"),
        ("acme.example.", "acme.example"),
        ("  app.acme.example  ", "app.acme.example"),
        ("user@acme.example", "acme.example"),
        ("bücher.example", "xn--bcher-kva.example"),
    ],
)
def test_normalize_domain(raw: str, expected: str) -> None:
    assert normalize_domain(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "localhost",
        "-acme.example",
        "acme-.example",
        "acme..example",
        "acme_corp.example",
        "192.168.0.1",
        "a" * 64 + ".example",
    ],
)
def test_normalize_domain_rejects(raw: str) -> None:
    with pytest.raises(ValueError, match="invalid domain"):
        normalize_domain(raw)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("CA", "CA"),
        ("ca", "CA"),
        ("California", "CA"),
        ("  new   york ", "NY"),
        ("Washington", "WA"),
    ],
)
def test_normalize_state(raw: str, expected: str) -> None:
    assert normalize_state(raw) == expected


@pytest.mark.parametrize("raw", ["XX", "Calif", "Ontario", ""])
def test_normalize_state_rejects(raw: str) -> None:
    with pytest.raises(ValueError, match="not a US state"):
        normalize_state(raw)


def test_clip() -> None:
    assert clip("  short  ", 10) == "short"
    clipped = clip("word " * 100, 50)
    assert len(clipped) <= 50
    assert clipped.endswith("…")
    with pytest.raises(ValueError, match="limit"):
        clip("text", 0)


# --------------------------------------------------------------------------- evidence & signals


def test_evidence_snippet_is_clipped_not_rejected() -> None:
    snippet = make_evidence(snippet="x" * 300).snippet
    assert len(snippet) == 280
    assert snippet.endswith("…")


@pytest.mark.parametrize("bad_id", ["e1", "E0", "E01", "X1", "E"])
def test_evidence_ids_are_e_numbered(bad_id: str) -> None:
    with pytest.raises(ValidationError):
        make_evidence(id=bad_id)


def test_evidence_time_is_aware_and_normalized_to_utc() -> None:
    pacific = timezone(timedelta(hours=-7))
    observed = make_evidence(observed_at=datetime(2026, 10, 14, 5, 0, tzinfo=pacific)).observed_at
    assert observed == NOW
    assert observed.utcoffset() == timedelta(0)
    with pytest.raises(ValidationError, match="timezone"):
        make_evidence(observed_at="2026-10-14T12:00:00")


def test_posting_text_is_clipped_and_urls_must_be_absolute() -> None:
    assert len(make_posting(description_text="y" * 7000).description_text) == 6000
    for url in ("boards.greenhouse.io/acme/jobs/1", "ftp://boards.greenhouse.io/acme"):
        with pytest.raises(ValidationError, match="absolute http"):
            make_posting(url=url)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"ai_role_count": 13}, "cannot exceed total_open_roles"),
        ({"ai_role_count": 0}, "more postings than ai_role_count"),
        (
            {"competitors": [{"kind": "openai", "confidence": 0.7, "evidence_ids": ["E9"]}]},
            "unknown evidence ids: E9",
        ),
        ({"evidence": [make_evidence(1), make_evidence(1)]}, "duplicate evidence ids: E1"),
        (
            {
                "cloud": [
                    {"provider": "aws", "confidence": 0.8, "evidence_ids": ["E2"]},
                    {"provider": "aws", "confidence": 0.5, "evidence_ids": ["E1"]},
                ]
            },
            "at most one signal",
        ),
        ({"primary_cloud": "gcp"}, "has no supporting signal"),
        ({"primary_cloud": "multi"}, "two or more providers"),
        (
            {"cloud": [{"provider": "multi", "confidence": 0.8, "evidence_ids": ["E2"]}]},
            "one concrete provider",
        ),
        (
            {"cloud": [{"provider": "aws", "confidence": 0.8, "evidence_ids": []}]},
            "at least 1 item",
        ),
        (
            {"ai_role_count": 11, "ai_roles": [make_posting(n) for n in range(11)]},
            "at most 10 items",
        ),
    ],
)
def test_tech_stack_invariants(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        make_tech_stack(**overrides)


def test_multi_cloud_needs_two_supported_providers() -> None:
    signals = make_tech_stack(
        cloud=[
            {"provider": "aws", "confidence": 0.8, "evidence_ids": ["E2"]},
            {"provider": "gcp", "confidence": 0.6, "evidence_ids": ["E1"]},
        ],
        primary_cloud="multi",
    )
    assert signals.primary_cloud is CloudProvider.MULTI


# --------------------------------------------------------------------------- profile


def test_profile_normalizes_domain_and_derives_website() -> None:
    profile = make_profile(domain="https://www.Acme.example/careers")
    assert profile.domain == "acme.example"
    assert profile.website_url == "https://acme.example"
    assert make_profile(website_url="https://acme.example/home").website_url == (
        "https://acme.example/home"
    )


@pytest.mark.parametrize(
    ("state", "expected"),
    [("CA", True), ("wa", True), ("Oregon", True), ("AZ", True), ("NV", False), ("NY", False)],
)
def test_in_territory(state: str, expected: bool) -> None:
    assert make_profile(hq_state=state).in_territory is expected


def test_computed_fields_are_dumped_and_ignored_on_input() -> None:
    profile = make_profile(hq_state="NY")
    dumped = profile.model_dump(mode="json")
    assert dumped["in_territory"] is False
    dumped["in_territory"] = True  # a stale or forged value never wins
    assert StartupProfile.model_validate(dumped).in_territory is False


def test_assignment_is_validated() -> None:
    profile = make_profile()
    profile.hq_state = "washington"
    assert profile.hq_state == "WA"
    with pytest.raises(ValidationError, match="not a US state"):
        profile.hq_state = "Ontario"


def test_profile_rejects_unknown_fields_and_bad_values() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        make_profile(arr_usd=1_000_000)
    with pytest.raises(ValidationError):
        make_profile(employee_count=0)
    with pytest.raises(ValidationError, match="absolute http"):
        make_profile(contacts=[{"name": "Dana", "title": "CTO", "linkedin_url": "linkedin.com/x"}])


def test_profile_tech_stack_must_match_domain() -> None:
    with pytest.raises(ValidationError, match=r"tech_stack is for other\.example"):
        make_profile(tech_stack=make_tech_stack(domain="other.example"))


# --------------------------------------------------------------------------- wedges


def test_wedges_rank_by_fit_then_priority() -> None:
    value_props = make_value_props(
        wedges=[
            make_wedge(WedgeId.EXTENDED_THINKING, 70),
            make_wedge(WedgeId.CLOUD_DRAWDOWN, 70),
            make_wedge(WedgeId.PROMPT_CACHING, 55),
        ],
        primary_wedge="cloud_drawdown",
    )
    assert [w.wedge_id for w in value_props.wedges] == [
        WedgeId.CLOUD_DRAWDOWN,
        WedgeId.EXTENDED_THINKING,
        WedgeId.PROMPT_CACHING,
    ]


def test_value_props_invariants() -> None:
    with pytest.raises(ValidationError, match="top-ranked wedge"):
        make_value_props(primary_wedge="cloud_drawdown")
    with pytest.raises(ValidationError, match="at most once"):
        make_value_props(
            wedges=[make_wedge(WedgeId.PROMPT_CACHING, 80), make_wedge(WedgeId.PROMPT_CACHING, 60)]
        )
    suppressed = make_value_props(primary_wedge=None, suppressions=["Already a Claude customer"])
    assert suppressed.primary_wedge is None


def test_impact_range_is_ordered() -> None:
    with pytest.raises(ValidationError, match="cannot exceed"):
        ImpactEstimate(label="Input cost", low_pct=40, high_pct=10, assumptions="Prefix share")


# --------------------------------------------------------------------------- MEDDPICC


@pytest.mark.parametrize(
    ("score", "health"),
    [
        (None, Health.GREY),
        (0, Health.RED),
        (3, Health.RED),
        (4, Health.YELLOW),
        (6, Health.YELLOW),
        (7, Health.GREEN),
        (10, Health.GREEN),
    ],
)
def test_element_health(score: int | None, health: Health) -> None:
    assert make_element(METRICS, score).health is health


@pytest.mark.parametrize(
    ("score", "overrides", "message"),
    [
        (5, {"status": "unknown"}, "exactly when status is 'unknown'"),
        (None, {"status": "hypothesized"}, "exactly when status is 'unknown'"),
        (8, {"status": "validated", "evidence_ids": []}, "must cite evidence"),
        (11, {}, "less than or equal to 10"),
    ],
)
def test_element_invariants(score: int | None, overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        make_element(METRICS, score, **overrides)


def test_scorecard_needs_each_element_exactly_once() -> None:
    elements = [make_element(e, None) for e in MEDDPICCElement]
    with pytest.raises(ValidationError, match=r"missing: \['competition'\]"):
        make_scorecard(elements=elements[:-1])
    with pytest.raises(ValidationError, match=r"repeated: \['metrics'\]"):
        make_scorecard(elements=[*elements, make_element(METRICS, None)])


def test_scorecard_sorts_into_canonical_order() -> None:
    elements = [make_element(e, None) for e in reversed(MEDDPICCElement)]
    card = make_scorecard(elements=elements)
    assert [e.element for e in card.elements] == list(MEDDPICCElement)
    assert card.element(PAIN).element is PAIN


@pytest.mark.parametrize(
    ("scores", "total", "coverage", "tier"),
    [
        ({}, 0, 0.0, Tier.D),
        (dict.fromkeys(MEDDPICCElement, 10), 100, 100.0, Tier.A),
        # (20*8 + 10*6 + 15*4) * 10 / 45 = 62.2: unknowns lower coverage, not the score.
        ({PAIN: 8, COMPETITION: 6, METRICS: 4}, 62, 37.5, Tier.B),
        ({PAIN: 4, COMPETITION: 5}, 43, 25.0, Tier.C),
        # (15*0 + 5*1) * 10 / 20 = 2.5, which rounds half up.
        ({METRICS: 0, PAPER: 1}, 3, 25.0, Tier.D),
    ],
)
def test_scorecard_totals(
    scores: dict[MEDDPICCElement, int], total: int, coverage: float, tier: Tier
) -> None:
    card = make_scorecard(scores)
    assert card.total_score == total
    assert card.coverage_pct == coverage
    assert card.tier is tier


# --------------------------------------------------------------------------- LLM-facing schemas

LLM_SCHEMAS: list[type[BaseModel]] = [
    ElementRefinement,
    ScorecardRefinement,
    OutboundTouch,
    ObjectionHandle,
    PersonaTarget,
    BriefNarrative,
]


@pytest.mark.parametrize("schema", LLM_SCHEMAS, ids=lambda s: s.__name__)
def test_llm_schema_is_strict_and_complete(schema: type[BaseModel]) -> None:
    js = schema.model_json_schema()
    rendered = json.dumps(js)
    objects = [js, *(d for d in js.get("$defs", {}).values() if d.get("type") == "object")]
    for obj in objects:
        assert obj["additionalProperties"] is False
        assert set(obj["required"]) == set(obj["properties"]), "no optional fields"
    assert "readOnly" not in rendered, "no computed fields"


def test_touch_rules() -> None:
    with pytest.raises(ValidationError, match="needs a subject"):
        make_touch(1, "email", 0, subject=None)
    assert make_touch(2, "linkedin", 2).subject is None


@pytest.mark.parametrize(
    ("touches", "message"),
    [
        ([make_touch(1, "email", 0), make_touch(2, "call", 3)], "at least 3 items"),
        ([make_touch(n, "call", n) for n in range(1, 6)], "at most 4 items"),
        ([make_touch(n, "call", n) for n in (1, 3, 4)], "steps must run"),
        ([make_touch(n, "call", d) for n, d in ((1, 0), (2, 5), (3, 2))], "must not go backwards"),
    ],
)
def test_narrative_sequencing(touches: list[OutboundTouch], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        make_narrative(touches=touches)


def test_narrative_headline_limit() -> None:
    with pytest.raises(ValidationError, match="at most 120 characters"):
        make_narrative(headline="h" * 121)


def test_refinement_rules() -> None:
    with pytest.raises(ValidationError, match="requires citing evidence"):
        ElementRefinement(
            element=PAIN,
            rationale="r",
            discovery_questions=[],
            evidence_ids=[],
            proposed_status=ElementStatus.VALIDATED,
        )
    one = ElementRefinement(
        element=PAIN,
        rationale="r",
        discovery_questions=[],
        evidence_ids=["E1"],
        proposed_status=ElementStatus.VALIDATED,
    )
    with pytest.raises(ValidationError, match="at most once"):
        ScorecardRefinement(elements=[one, one], summary="s")


# --------------------------------------------------------------------------- brief & results


def test_brief_defaults_and_consistency() -> None:
    brief = make_brief()
    assert brief.disclaimer == DISCLAIMER
    assert brief.profile.in_territory


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"scorecard": make_scorecard(domain="other.example")}, "domains differ"),
        (
            {
                "scorecard": make_scorecard(
                    elements=[
                        *(make_element(e, None) for e in MEDDPICCElement if e is not PAIN),
                        make_element(PAIN, 8, evidence_ids=["E7"]),
                    ]
                )
            },
            "unknown evidence ids: E7",
        ),
        ({"evidence": [make_evidence(1), make_evidence(1)]}, "duplicate evidence ids"),
    ],
)
def test_brief_integrity(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        make_brief(**overrides)


def test_analysis_result_records_failures() -> None:
    assert make_result().ok
    failed = make_result(brief=None, errors=["ATS board not found"])
    assert not failed.ok
    with pytest.raises(ValidationError, match="at least one error"):
        make_result(brief=None)
    with pytest.raises(ValidationError, match="different domain"):
        make_result(domain="other.example")


def test_usage_adds_up() -> None:
    total = LLMUsage(input_tokens=10, est_cost_usd=0.5) + LLMUsage(output_tokens=4, est_cost_usd=1)
    assert (total.input_tokens, total.output_tokens, total.est_cost_usd) == (10, 4, 1.5)


ROUND_TRIP: list[Callable[[], BaseModel]] = [
    make_evidence,
    make_posting,
    make_tech_stack,
    lambda: make_profile(tech_stack=make_tech_stack(), contacts=[{"name": "Dana", "title": "CTO"}]),
    make_value_props,
    lambda: make_scorecard({PAIN: 8, COMPETITION: 6}),
    make_narrative,
    make_brief,
    make_result,
    lambda: make_result(brief=None, errors=["timeout"]),
]


@pytest.mark.parametrize("build", ROUND_TRIP)
def test_json_round_trip(build: Callable[[], BaseModel]) -> None:
    original = build()
    assert type(original).model_validate_json(original.model_dump_json()) == original
