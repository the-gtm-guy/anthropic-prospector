"""The displacement matrix: map collected signals to Anthropic wedges, deterministically.

Each wedge's fit is a weighted sum of triggers. A trigger reads one kind of signal (keyword
hits, competitor or cloud signals) and returns a strength in [0, 1] with the evidence ids
behind it, so every fit score traces back to public evidence. Weights in a wedge sum to 1,
so a fit of 100 means every trigger fired at full strength.
"""

import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Final

from anthropic_prospector.models import (
    TERRITORY_STATES,
    WEDGE_PRIORITY,
    AnthropicValueProps,
    CloudProvider,
    CompetitorKind,
    ImpactEstimate,
    SignalKeyword,
    StartupProfile,
    TechStackSignals,
    WedgeId,
    WedgeMatch,
)
from anthropic_prospector.pipeline.labels import MARKETPLACES

MIN_PRIMARY_FIT: Final = 30  # below this no wedge is confident enough to lead outreach


@dataclass(frozen=True)
class Reading:
    strength: float  # 0..1
    evidence_ids: tuple[str, ...] = ()


Measure = Callable[[TechStackSignals], Reading]


@dataclass(frozen=True)
class Trigger:
    label: str
    weight: float
    measure: Measure


@dataclass(frozen=True)
class WedgeRule:
    wedge_id: WedgeId
    title: str
    triggers: tuple[Trigger, ...]
    proof_points: tuple[str, ...]
    discovery_questions: tuple[str, ...]
    impact: ImpactEstimate


def _unique(ids: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(ids))


def keywords(*wanted: SignalKeyword, saturation: int) -> Measure:
    """Hits across `wanted`, full strength at `saturation` hits."""

    def measure(signals: TechStackSignals) -> Reading:
        hits = sum(signals.keyword_hits.get(k, 0) for k in wanted)
        ids = _unique(i for k in wanted for i in signals.keyword_evidence.get(k, []))
        return Reading(min(1.0, hits / saturation), ids if hits else ())

    return measure


def competitors(*kinds: CompetitorKind) -> Measure:
    """The most confident matching competitor signal."""

    def measure(signals: TechStackSignals) -> Reading:
        found = [c for c in signals.competitors if c.kind in kinds]
        if not found:
            return Reading(0.0)
        return Reading(
            max(c.confidence for c in found), _unique(i for c in found for i in c.evidence_ids)
        )

    return measure


def clouds(*providers: CloudProvider) -> Measure:
    """The most confident matching cloud signal."""

    def measure(signals: TechStackSignals) -> Reading:
        found = [s for s in signals.cloud if s.provider in providers]
        if not found:
            return Reading(0.0)
        return Reading(
            max(s.confidence for s in found), _unique(i for s in found for i in s.evidence_ids)
        )

    return measure


def strongest(*measures: Measure) -> Measure:
    """Whichever of several measures reads strongest."""

    def measure(signals: TechStackSignals) -> Reading:
        return max((m(signals) for m in measures), key=lambda r: r.strength)

    return measure


LLM_SPEND = (
    CompetitorKind.OPENAI,
    CompetitorKind.AZURE_OPENAI,
    CompetitorKind.OTHER_LLM,
    CompetitorKind.LANGCHAIN,
)

WEDGE_RULES: Final = (
    WedgeRule(
        wedge_id=WedgeId.PROMPT_CACHING,
        title="Prompt caching",
        triggers=(
            Trigger(
                "RAG, long-document or support workloads",
                0.45,
                keywords(
                    SignalKeyword.RAG,
                    SignalKeyword.LONG_CONTEXT,
                    SignalKeyword.DOCUMENT_PROCESSING,
                    SignalKeyword.CUSTOMER_SUPPORT,
                    saturation=8,
                ),
            ),
            Trigger("existing LLM API spend", 0.25, competitors(*LLM_SPEND)),
            Trigger(
                "inference cost is a stated priority",
                0.2,
                keywords(SignalKeyword.INFERENCE_COST, saturation=2),
            ),
            Trigger("self-hosted inference to replace", 0.1, competitors(CompetitorKind.VLLM)),
        ),
        proof_points=(
            "On Claude Sonnet 5.5, cache reads bill at 0.1x the base input price and a "
            "5-minute cache write at 1.25x, so a prefix reused twice already costs less.",
            "Caching a long shared prefix also cuts time to first token.",
            "Prefixes from 512 tokens cache on current Claude models.",
        ),
        discovery_questions=(
            "Roughly what share of each prompt is the same across calls (system prompt, "
            "retrieved documents, tool definitions)?",
            "What is your monthly input-token volume, and which workload drives most of it?",
            "Which AI features are most cost-sensitive as usage grows?",
        ),
        impact=ImpactEstimate(
            label="Input-token spend on repeated context",
            assumptions=(
                "Illustration only: if 70% of input tokens are a shared prefix that hits the "
                "cache, those tokens bill at 0.1x, cutting input spend by about 63% "
                "(0.7 x 0.9), before cache-write costs. Needs: monthly input tokens, the share "
                "of each prompt that repeats, and the cache hit rate."
            ),
        ),
    ),
    WedgeRule(
        wedge_id=WedgeId.EXTENDED_THINKING,
        title="Extended thinking",
        triggers=(
            Trigger(
                "agent, multi-step or code-generation work",
                0.5,
                keywords(
                    SignalKeyword.AGENTS,
                    SignalKeyword.MULTI_STEP_REASONING,
                    SignalKeyword.CODE_GENERATION,
                    saturation=8,
                ),
            ),
            Trigger(
                "orchestration chains in LangChain or LangGraph",
                0.2,
                competitors(CompetitorKind.LANGCHAIN),
            ),
            Trigger(
                "quality measured with evals", 0.15, keywords(SignalKeyword.EVALS, saturation=3)
            ),
            Trigger(
                "reasoning over long documents",
                0.15,
                keywords(SignalKeyword.LONG_CONTEXT, saturation=3),
            ),
        ),
        proof_points=(
            "Extended thinking was introduced with Claude 3.7 Sonnet (now retired); current "
            "models such as Claude Sonnet 5.5 think adaptively.",
            "Effort is tunable per request, from low to max, trading thoroughness against "
            "token spend.",
            "One call can plan, check and revise before answering, instead of a hand-built "
            "chain of planner and verifier calls.",
        ),
        discovery_questions=(
            "Where do multi-step tasks fail today: planning, tool use or checking the answer?",
            "How many model calls does your hardest workflow chain together?",
            "How do you measure reasoning quality in your evals?",
        ),
        impact=ImpactEstimate(
            label="Calls and failures per complex task",
            assumptions=(
                "Depends on how many chained calls the hardest workflow makes today and how "
                "often it fails; measure on the prospect's own evals before claiming a gain."
            ),
        ),
    ),
    WedgeRule(
        wedge_id=WedgeId.CLOUD_DRAWDOWN,
        title="Cloud marketplace",
        triggers=(
            Trigger(
                "runs on a cloud that sells Claude",
                0.6,
                clouds(CloudProvider.AWS, CloudProvider.GCP, CloudProvider.AZURE),
            ),
            Trigger(
                "LLM spend that could move onto the cloud account",
                0.2,
                competitors(
                    CompetitorKind.OPENAI, CompetitorKind.AZURE_OPENAI, CompetitorKind.OTHER_LLM
                ),
            ),
            Trigger(
                "self-hosted models on GPUs",
                0.2,
                strongest(
                    competitors(CompetitorKind.VLLM),
                    keywords(
                        SignalKeyword.SELF_HOSTED_MODELS, SignalKeyword.GPU_INFRA, saturation=4
                    ),
                ),
            ),
        ),
        proof_points=(
            "Current Claude models are sold through Amazon Bedrock, Google Cloud Vertex AI and "
            "Microsoft Foundry, billed through the customer's cloud account.",
            "Claude on Microsoft Foundry is billed through the Microsoft Marketplace.",
            "Commit drawdown depends on each customer's agreement: confirm eligibility with "
            "the Anthropic partner team before raising it.",
        ),
        discovery_questions=(
            "Do you have a committed-spend agreement with your cloud provider, and how much of "
            "it is unallocated this year?",
            "Would buying Claude through your cloud marketplace shorten procurement and "
            "security review?",
            "Which regions and data-residency requirements apply to your AI workloads?",
        ),
        impact=ImpactEstimate(
            label="AI spend billed through an existing cloud account",
            assumptions=(
                "Depends on the customer's cloud commitment terms and unallocated balance; "
                "eligibility must be confirmed with the Anthropic partner team."
            ),
        ),
    ),
)


def build_value_props(profile: StartupProfile) -> AnthropicValueProps:
    """Rank the wedges for one account and pick the angle to lead with."""
    if profile.tech_stack is None:
        raise ValueError(f"{profile.domain} has no collected signals")
    signals = profile.tech_stack
    wedges = [_match(rule, profile, signals) for rule in WEDGE_RULES]
    # Same order AnthropicValueProps enforces, so `primary` is always its top wedge.
    ranked = sorted(wedges, key=lambda w: (-w.fit_score, WEDGE_PRIORITY.index(w.wedge_id)))
    top, second = ranked[0], ranked[1]

    suppressions = _suppressions(profile, signals, top)
    blocks_outreach = bool(suppressions) and not _only_out_of_territory(profile, suppressions)
    primary = None if blocks_outreach or top.fit_score < MIN_PRIMARY_FIT else top.wedge_id
    if primary is None and top.fit_score < MIN_PRIMARY_FIT and not suppressions:
        suppressions.append(f"No wedge reaches a fit of {MIN_PRIMARY_FIT}: nurture for now.")

    overall = math.floor(0.7 * top.fit_score + 0.3 * second.fit_score + 0.5)
    return AnthropicValueProps(
        domain=profile.domain,
        wedges=wedges,
        primary_wedge=primary,
        overall_fit=overall,
        suppressions=suppressions,
        rationale=_rationale(top, second, primary),
    )


def _match(rule: WedgeRule, profile: StartupProfile, signals: TechStackSignals) -> WedgeMatch:
    total = backed = 0.0
    reasons: list[str] = []
    evidence: list[str] = []
    for trigger in rule.triggers:
        reading = trigger.measure(signals)
        if reading.strength <= 0:
            continue
        contribution = trigger.weight * reading.strength
        total += contribution
        reasons.append(trigger.label)
        evidence.extend(reading.evidence_ids)
        if reading.evidence_ids:
            backed += contribution
    return WedgeMatch(
        wedge_id=rule.wedge_id,
        title=rule.title,
        fit_score=math.floor(100 * min(total, 1.0) + 0.5),
        # The share of the fit that rests on cited evidence rather than bare counts.
        confidence=round(backed / total, 2) if total else 0.0,
        trigger_evidence_ids=list(_unique(evidence)),
        hypothesis=_hypothesis(rule.wedge_id, profile, signals, reasons),
        proof_points=list(rule.proof_points),
        discovery_questions=list(rule.discovery_questions),
        impact=rule.impact,
    )


def _hypothesis(
    wedge_id: WedgeId, profile: StartupProfile, signals: TechStackSignals, reasons: list[str]
) -> str:
    name = profile.company_name
    seen = f"signals: {'; '.join(reasons)}" if reasons else "no strong public signal yet"
    if wedge_id is WedgeId.PROMPT_CACHING:
        return (
            f"{name} appears to send large, repeated context to an LLM ({seen}). Prompt "
            "caching bills repeated prefixes at a fraction of the input price, so input spend "
            "should fall as volume grows."
        )
    if wedge_id is WedgeId.EXTENDED_THINKING:
        return (
            f"{name} appears to run multi-step AI work ({seen}). Extended thinking lets one "
            "call plan, check and revise, which can replace brittle chains of calls."
        )
    marketplaces = [MARKETPLACES[s.provider] for s in signals.cloud if s.provider in MARKETPLACES]
    route = " or ".join(marketplaces) if marketplaces else "a cloud marketplace"
    return (
        f"{name} could buy Claude through {route} on its existing cloud account ({seen}); "
        "commit eligibility must be confirmed with the Anthropic partner team."
    )


def _suppressions(profile: StartupProfile, signals: TechStackSignals, top: WedgeMatch) -> list[str]:
    notes = []
    existing = [c for c in signals.competitors if c.kind is CompetitorKind.ANTHROPIC_EXISTING]
    if existing:
        cited = ", ".join(existing[0].evidence_ids)
        notes.append(
            f"Already building on Claude ({cited}): route to the account team, no cold outbound."
        )
    if not signals.ai_role_count and not signals.competitors and not signals.keyword_hits:
        notes.append("No AI or LLM signal in public data: nurture until one appears.")
    if not profile.in_territory:
        territory = "/".join(sorted(TERRITORY_STATES))
        notes.append(
            f"HQ in {profile.hq_state} is outside the {territory} territory: route to the "
            "owning rep."
        )
    return notes


def _only_out_of_territory(profile: StartupProfile, suppressions: list[str]) -> bool:
    # Out-of-territory accounts keep their primary wedge so the owning rep can use it.
    return not profile.in_territory and len(suppressions) == 1


def _rationale(top: WedgeMatch, second: WedgeMatch, primary: WedgeId | None) -> str:
    lead = "Leads with" if primary is not None else "Strongest angle, not leading outreach:"
    return (
        f"{lead} {top.title.lower()} (fit {top.fit_score}); "
        f"{second.title.lower()} is the second angle (fit {second.fit_score})."
    )
