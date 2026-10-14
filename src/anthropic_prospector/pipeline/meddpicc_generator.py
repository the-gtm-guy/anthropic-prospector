"""MEDDPICC scorecards: a deterministic baseline from public signals, then LLM refinement.

The baseline is honest about what public data can show before any conversation: elements
start unknown or hypothesized, and scores are capped below what discovery can earn.
Refinement sharpens the reasoning and discovery questions. It never changes a score, never
turns an unknown element into a known one, and can mark an element validated only by
citing evidence that exists.
"""

import math
import re
from collections.abc import Iterable
from typing import Final

from anthropic_prospector.models import (
    AnthropicValueProps,
    CompetitorKind,
    ElementRefinement,
    ElementScore,
    ElementStatus,
    FundingStage,
    LLMUsage,
    MEDDPICCElement,
    MEDDPICCScorecard,
    Persona,
    Recommendation,
    ScorecardRefinement,
    SignalKeyword,
    StartupProfile,
    TechStackSignals,
    Tier,
)
from anthropic_prospector.pipeline.labels import (
    CLOUD_NAMES,
    COMPETITOR_NAMES,
    ELEMENT_LABELS,
    MARKETPLACES,
    PERSONA_LABELS,
    STAGE_LABELS,
    join,
)
from anthropic_prospector.pipeline.llm import LLMClient, StructuredRequest
from anthropic_prospector.pipeline.prompts import REFINE_TASK, SYSTEM_PROMPT, account_block

E = MEDDPICCElement

# Before discovery the tier tracks qualification depth (tier A needs discovery data), so
# whether to start outreach is driven by the strength of the opening angle instead.
PURSUE_MIN_FIT: Final = 60

_PERSONA_PATTERNS: Final = (
    (
        Persona.CTO_FOUNDER,
        r"\b(cto|ceo|chief (technology|executive) officer|co-?founder|founder)\b",
    ),
    (Persona.AI_ML_LEAD, r"\b(ai|ml|machine learning|data science|applied scientist)\b"),
    (
        Persona.ENG_LEADER,
        r"\b(vp|vice president|head|director)\b.*\b(engineering|platform|infrastructure)\b"
        r"|\bengineering manager\b",
    ),
    (Persona.FINANCE, r"\b(cfo|finance|controller)\b"),
    (Persona.PROCUREMENT, r"\b(procurement|purchasing|vendor management)\b"),
)
_METRIC_NAMES: Final = {
    SignalKeyword.INFERENCE_COST: "inference cost",
    SignalKeyword.LATENCY: "latency",
}
_CRITERIA_NAMES: Final = {
    SignalKeyword.COMPLIANCE: "security and compliance reviews",
    SignalKeyword.LATENCY: "latency",
    SignalKeyword.EVALS: "eval results",
}


def infer_persona(title: str) -> Persona | None:
    lowered = title.lower()
    return next((p for p, pattern in _PERSONA_PATTERNS if re.search(pattern, lowered)), None)


def buyer_persona(profile: StartupProfile) -> Persona:
    """Who likely owns the budget: the CTO or a founder under ~100 people, else a VP of Eng."""
    size = profile.employee_count
    return Persona.CTO_FOUNDER if size is None or size < 100 else Persona.ENG_LEADER


def has_ai_signal(signals: TechStackSignals) -> bool:
    return bool(signals.ai_role_count or signals.competitors or signals.keyword_hits)


# --------------------------------------------------------------------------- baseline


def baseline_scorecard(
    profile: StartupProfile, value_props: AnthropicValueProps
) -> MEDDPICCScorecard:
    if profile.tech_stack is None:
        raise ValueError(f"{profile.domain} has no collected signals")
    signals = profile.tech_stack
    buyer_name, buyer = _economic_buyer(profile)
    elements = [
        _metrics(profile, signals),
        buyer,
        _decision_criteria(signals),
        _decision_process(profile),
        _paper_process(signals),
        _identify_pain(signals, value_props),
        _champion(profile, signals, skip=buyer_name),
        _competition(signals),
    ]
    draft = MEDDPICCScorecard(
        domain=profile.domain,
        elements=elements,
        recommendation=Recommendation.NURTURE,
        summary="pending",
        generated_by="rules",
        data_source=signals.data_source,
    )
    recommendation = _recommend(profile, signals, value_props, draft.tier)
    return MEDDPICCScorecard(
        domain=profile.domain,
        elements=elements,
        recommendation=recommendation,
        summary=_summary(draft, recommendation),
        generated_by="rules",
        data_source=signals.data_source,
    )


def _element(
    element: MEDDPICCElement,
    score: int | None = None,
    *,
    rationale: str,
    next_action: str,
    gaps: Iterable[str] = (),
    evidence: Iterable[str] = (),
    status: ElementStatus | None = None,
    confidence: float = 0.0,
) -> ElementScore:
    if status is None:
        status = ElementStatus.UNKNOWN if score is None else ElementStatus.HYPOTHESIZED
    return ElementScore(
        element=element,
        score=score,
        status=status,
        evidence_ids=list(dict.fromkeys(evidence)),
        rationale=rationale,
        gaps=list(gaps),
        next_action=next_action,
        confidence=confidence if score is not None else 0.0,
    )


def _keyword_evidence(signals: TechStackSignals, keywords: Iterable[SignalKeyword]) -> list[str]:
    return [i for k in keywords for i in signals.keyword_evidence.get(k, [])]


def _metrics(profile: StartupProfile, signals: TechStackSignals) -> ElementScore:
    tracked = [k for k in _METRIC_NAMES if signals.keyword_hits.get(k)]
    if tracked:
        names = join([_METRIC_NAMES[k] for k in tracked])
        return _element(
            E.METRICS,
            4,
            evidence=_keyword_evidence(signals, tracked),
            rationale=f"Job posts already talk about {names}, a natural success metric.",
            gaps=["Get their current numbers and the target."],
            next_action=f"Ask for current {names} and the target that would justify a change.",
            confidence=0.5,
        )
    if profile.funding_stage in (
        FundingStage.SERIES_A,
        FundingStage.SERIES_B,
        FundingStage.SERIES_C_PLUS,
    ):
        stage = STAGE_LABELS[profile.funding_stage]
        return _element(
            E.METRICS,
            3,
            rationale=f"Post-{stage} growth targets imply unit-economics metrics; none are public.",
            gaps=["Find the metric their AI features are judged by."],
            next_action="Ask how they will measure success for their AI features.",
            confidence=0.3,
        )
    return _element(
        E.METRICS,
        rationale="No public metric to anchor a business case.",
        gaps=["Find the metric their AI features are judged by."],
        next_action="Ask how they will measure success for their AI features.",
    )


def _economic_buyer(profile: StartupProfile) -> tuple[str | None, ElementScore]:
    persona = buyer_persona(profile)
    label = PERSONA_LABELS[persona]
    size = f"~{profile.employee_count} people" if profile.employee_count else "this stage"
    for contact in profile.contacts:
        if (contact.persona or infer_persona(contact.title)) is persona:
            return contact.name, _element(
                E.ECONOMIC_BUYER,
                5,
                rationale=f"{contact.name} ({contact.title}) is the likely budget owner at {size}.",
                gaps=["Confirm they own the AI budget and sign."],
                next_action=f"Confirm with {contact.name} who signs for AI spend.",
                confidence=0.4,
            )
    return None, _element(
        E.ECONOMIC_BUYER,
        rationale=f"Likely the {label} at {size}; no contact on file.",
        gaps=["Name and confirm the budget owner."],
        next_action=f"Identify the {label} and confirm they own the AI budget.",
    )


def _champion(
    profile: StartupProfile, signals: TechStackSignals, *, skip: str | None
) -> ElementScore:
    for contact in profile.contacts:
        persona = contact.persona or infer_persona(contact.title)
        if contact.name != skip and persona in (Persona.AI_ML_LEAD, Persona.ENG_LEADER):
            return _element(
                E.CHAMPION,
                4,
                rationale=f"{contact.name} ({contact.title}) leads the team doing the AI work.",
                gaps=["Test whether they will sell internally."],
                next_action=(
                    f"Give {contact.name} a cost or quality result to take to the budget owner."
                ),
                confidence=0.4,
            )
    if signals.ai_roles:
        role = signals.ai_roles[0].title
        return _element(
            E.CHAMPION,
            rationale=(
                f"No contact on file; the hiring manager for '{role}' is the likely champion."
            ),
            gaps=["Find and test a champion."],
            next_action=f"Find the hiring manager for '{role}'.",
        )
    return _element(
        E.CHAMPION,
        rationale="No contact or AI team visible yet.",
        gaps=["Find who owns AI work."],
        next_action="Ask who owns AI initiatives.",
    )


def _decision_criteria(signals: TechStackSignals) -> ElementScore:
    found = [k for k in _CRITERIA_NAMES if signals.keyword_hits.get(k)]
    if not found:
        return _element(
            E.DECISION_CRITERIA,
            rationale="No public signal of how they judge model vendors.",
            gaps=["List the criteria a vendor must pass."],
            next_action="Ask what a model vendor must pass to get approved.",
        )
    names = join([_CRITERIA_NAMES[k] for k in found])
    return _element(
        E.DECISION_CRITERIA,
        5,
        evidence=_keyword_evidence(signals, found),
        rationale=f"Public signals suggest they will judge vendors on {names}.",
        gaps=["Confirm the criteria and how they are weighted."],
        next_action="Ask which criteria a model vendor must pass, and who checks them.",
        confidence=0.45,
    )


def _decision_process(profile: StartupProfile) -> ElementScore:
    size = profile.employee_count
    if size is not None and size <= 50:
        return _element(
            E.DECISION_PROCESS,
            4,
            rationale=f"At ~{size} people the founders likely decide, with a short evaluation.",
            gaps=["Confirm who else weighs in."],
            next_action="Ask what a trial must show and how long they would give it.",
            confidence=0.3,
        )
    return _element(
        E.DECISION_PROCESS,
        rationale="Not visible from public data.",
        gaps=["Map evaluators, approvers and the timeline."],
        next_action="Ask how they chose their current model vendor and how long it took.",
    )


def _paper_process(signals: TechStackSignals) -> ElementScore:
    found = [s for s in signals.cloud if s.provider in MARKETPLACES]
    if not found:
        return _element(
            E.PAPER_PROCESS,
            rationale="How they buy software is not visible.",
            gaps=["Learn how they buy software: direct or through a cloud marketplace."],
            next_action="Ask how they usually buy developer tools and APIs.",
        )
    best = max(found, key=lambda s: s.confidence)
    marketplace = MARKETPLACES[best.provider]
    return _element(
        E.PAPER_PROCESS,
        4,
        evidence=best.evidence_ids,
        rationale=(
            f"They run on {CLOUD_NAMES[best.provider]}, so Claude could be bought through "
            f"{marketplace} on their existing cloud agreement."
        ),
        gaps=["Confirm marketplace purchasing is allowed and what security review needs."],
        next_action=f"Ask whether they can buy through {marketplace} and what review it needs.",
        confidence=round(0.5 * best.confidence, 2),
    )


def _identify_pain(signals: TechStackSignals, value_props: AnthropicValueProps) -> ElementScore:
    top = value_props.wedges[0] if value_props.wedges else None
    if top is None or not has_ai_signal(signals) or top.fit_score < 20:
        return _element(
            E.IDENTIFY_PAIN,
            rationale="No public signal of an LLM workload yet.",
            gaps=["Find what business problem AI would solve for them this year."],
            next_action="Ask where AI sits on this year's roadmap and what is blocking it.",
        )
    return _element(
        E.IDENTIFY_PAIN,
        min(8, math.floor(top.fit_score / 12.5 + 0.5)),
        evidence=top.trigger_evidence_ids,
        rationale=(
            f"Signals point to a {top.title.lower()} fit ({top.fit_score}/100). {top.hypothesis}"
        ),
        gaps=["Confirm the pain in the buyer's words and what it costs today."],
        next_action=top.discovery_questions[0] if top.discovery_questions else "Confirm the pain.",
        confidence=round(0.6 * top.confidence, 2),
    )


def _competition(signals: TechStackSignals) -> ElementScore:
    if not signals.competitors:
        seen = "AI work is visible but" if signals.ai_role_count else "No AI work is visible, and"
        return _element(
            E.COMPETITION,
            rationale=f"{seen} the model vendor is not.",
            gaps=["Learn which model vendor or approach they use today."],
            next_action="Ask which models they use today and why.",
        )
    evidence = [i for c in signals.competitors for i in c.evidence_ids]
    confidence = max(c.confidence for c in signals.competitors)
    others = [
        COMPETITOR_NAMES[c.kind]
        for c in signals.competitors
        if c.kind is not CompetitorKind.ANTHROPIC_EXISTING
    ]
    if len(others) < len(signals.competitors):
        return _element(
            E.COMPETITION,
            8,
            status=ElementStatus.VALIDATED,
            evidence=evidence,
            rationale=f"Already building on Claude; also seen: {join(others) or 'nothing else'}.",
            gaps=["Find workloads still on other vendors."],
            next_action="Hand to the account team to expand existing Claude usage.",
            confidence=confidence,
        )
    return _element(
        E.COMPETITION,
        6,
        status=ElementStatus.VALIDATED,
        evidence=evidence,
        rationale=f"Public evidence shows {join(others)}.",
        gaps=["Learn what they like and dislike about the incumbent."],
        next_action="Ask what would make them run a side-by-side on one workload.",
        confidence=confidence,
    )


def _recommend(
    profile: StartupProfile, signals: TechStackSignals, value_props: AnthropicValueProps, tier: Tier
) -> Recommendation:
    if any(c.kind is CompetitorKind.ANTHROPIC_EXISTING for c in signals.competitors):
        return Recommendation.ROUTE_TO_AE
    if not profile.in_territory:
        return Recommendation.ROUTE_TO_OWNER
    if not has_ai_signal(signals):
        return Recommendation.DISQUALIFY
    top_fit = value_props.wedges[0].fit_score if value_props.wedges else 0
    if value_props.primary_wedge is not None and top_fit >= PURSUE_MIN_FIT and tier is not Tier.D:
        return Recommendation.PURSUE
    return Recommendation.NURTURE


def _summary(card: MEDDPICCScorecard, recommendation: Recommendation) -> str:
    known = sorted((e for e in card.elements if e.score is not None), key=lambda e: -(e.score or 0))
    strongest = join([ELEMENT_LABELS[e.element].lower() for e in known[:2]]) or "nothing yet"
    gaps = join([ELEMENT_LABELS[e.element].lower() for e in card.elements if e.score is None][:3])
    return (
        f"Tier {card.tier}: {card.total_score}/100 on {card.coverage_pct:g}% coverage. "
        f"Strongest: {strongest}. Biggest gaps: {gaps or 'none'}. "
        f"Recommendation: {recommendation.replace('_', ' ')}."
    )


# --------------------------------------------------------------------------- refinement


def rules_refinement(scorecard: MEDDPICCScorecard) -> ScorecardRefinement:
    """The deterministic refinement: the baseline's own reasoning, unchanged."""
    return ScorecardRefinement(
        elements=[
            ElementRefinement(
                element=e.element,
                rationale=e.rationale,
                discovery_questions=[e.next_action],
                evidence_ids=e.evidence_ids,
                proposed_status=e.status,
            )
            for e in scorecard.elements
        ],
        summary=scorecard.summary,
    )


def refinement_request(
    profile: StartupProfile, value_props: AnthropicValueProps, scorecard: MEDDPICCScorecard
) -> StructuredRequest[ScorecardRefinement]:
    known = {e.id for e in (profile.tech_stack.evidence if profile.tech_stack else [])}

    def check(refinement: ScorecardRefinement) -> None:
        cited = {i for e in refinement.elements for i in e.evidence_ids}
        if missing := sorted(cited - known):
            raise ValueError(
                f"cites evidence ids that do not exist: {', '.join(missing)}. "
                "Cite only ids listed in <evidence>."
            )

    return StructuredRequest(
        schema=ScorecardRefinement,
        system=SYSTEM_PROMPT,
        user=f"{account_block(profile, value_props, scorecard)}\n\n{REFINE_TASK}",
        deterministic=lambda: rules_refinement(scorecard),
        check=check,
    )


def refine_scorecard(
    scorecard: MEDDPICCScorecard,
    profile: StartupProfile,
    value_props: AnthropicValueProps,
    llm: LLMClient,
) -> tuple[MEDDPICCScorecard, LLMUsage]:
    refinement, usage = llm.generate(refinement_request(profile, value_props, scorecard))
    return merge_refinement(scorecard, refinement, model_id=llm.model_id), usage


def merge_refinement(
    scorecard: MEDDPICCScorecard, refinement: ScorecardRefinement, *, model_id: str | None
) -> MEDDPICCScorecard:
    """Apply a refinement without letting it move a score or invent a known element."""
    by_element = {r.element: r for r in refinement.elements}
    elements = []
    for element in scorecard.elements:
        r = by_element.get(element.element)
        if r is None:
            elements.append(element)
            continue
        status = element.status
        if status is not ElementStatus.UNKNOWN and r.proposed_status is not ElementStatus.UNKNOWN:
            status = r.proposed_status
        elements.append(
            ElementScore.model_validate(
                element.model_dump()
                | {
                    "rationale": r.rationale,
                    "status": status,
                    "evidence_ids": list(dict.fromkeys([*element.evidence_ids, *r.evidence_ids])),
                    "next_action": r.discovery_questions[0]
                    if r.discovery_questions
                    else element.next_action,
                }
            )
        )
    return MEDDPICCScorecard(
        domain=scorecard.domain,
        elements=elements,
        recommendation=scorecard.recommendation,
        summary=refinement.summary,
        generated_by="mock" if model_id is None else "llm",
        model_id=model_id,
        data_source=scorecard.data_source,
    )
