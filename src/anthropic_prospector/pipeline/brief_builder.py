"""Assemble the SDR outbound brief and render it as Markdown.

The brief is assembled deterministically from the profile, value props and scorecard; the
LLM writes only the narrative. rules_narrative() is the deterministic narrative: what the
mock returns, and the shape the live model is asked to improve on.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from anthropic_prospector.models import (
    HEADLINE_MAX_CHARS,
    AnthropicValueProps,
    BriefNarrative,
    Channel,
    CloudProvider,
    CompetitorKind,
    DataSource,
    FundingStage,
    LLMUsage,
    MEDDPICCScorecard,
    ObjectionHandle,
    OutboundTouch,
    Persona,
    PersonaTarget,
    Recommendation,
    SDROutboundBrief,
    StartupProfile,
    TechStackSignals,
    WedgeId,
    clip,
)
from anthropic_prospector.pipeline.labels import (
    CLOUD_NAMES,
    COMPETITOR_NAMES,
    ELEMENT_LABELS,
    MARKETPLACES,
    STAGE_LABELS,
    join,
)
from anthropic_prospector.pipeline.llm import LLMClient, StructuredRequest
from anthropic_prospector.pipeline.prompts import NARRATIVE_TASK, SYSTEM_PROMPT, account_block

CHANNEL_LABELS = {Channel.EMAIL: "Email", Channel.LINKEDIN: "LinkedIn", Channel.CALL: "Call"}

TITLE_PATTERNS = {
    Persona.CTO_FOUNDER: ["CTO", "Co-founder", "CEO"],
    Persona.ENG_LEADER: ["VP Engineering", "Head of Engineering", "Head of Platform"],
    Persona.AI_ML_LEAD: ["Head of AI", "ML Lead", "Staff ML Engineer"],
    Persona.FINANCE: ["CFO", "VP Finance"],
    Persona.PROCUREMENT: ["Head of Procurement"],
}


@dataclass(frozen=True)
class _Angle:
    headline: str
    subject: str
    hook: str
    talk_track: str
    cta: str
    buyer_angle: str
    champion_angle: str


def _angle(wedge: WedgeId | None, profile: StartupProfile, signals: TechStackSignals) -> _Angle:
    name = profile.company_name
    if wedge is WedgeId.PROMPT_CACHING:
        return _Angle(
            headline=f"{name}: cut the cost of repeated context with Claude prompt caching",
            subject=f"Repeated context at {name}",
            hook=(
                "Teams that send the same long context on every call (retrieved documents, system "
                "prompts, tool definitions) can cache it with Claude, so repeat reads bill at a "
                "fraction of the input price."
            ),
            talk_track=(
                "Ask how much of each prompt repeats across calls. Explain prompt caching: the "
                "repeated prefix is cached, cache reads bill at 0.1x the input price on Claude "
                "Sonnet 5.5, and time to first token drops. Offer a side-by-side on one "
                "high-volume workflow, measured on their own evals."
            ),
            cta="Worth 20 minutes to size it on one workflow?",
            buyer_angle="Lower input-token spend as usage grows, without a rewrite.",
            champion_angle="Faster, cheaper calls on the workloads their team owns.",
        )
    if wedge is WedgeId.EXTENDED_THINKING:
        return _Angle(
            headline=f"{name}: more reliable multi-step agents with Claude extended thinking",
            subject=f"Multi-step reliability at {name}",
            hook=(
                "Claude's extended thinking lets one call plan, check and revise before it "
                "answers, which often replaces a brittle chain of planner and verifier calls."
            ),
            talk_track=(
                "Ask where multi-step tasks fail today and how many calls the hardest workflow "
                "chains together. Explain that current Claude models think adaptively, with effort "
                "tunable from low to max per route. Offer to run their hardest eval cases "
                "through Claude."
            ),
            cta="Open to running your hardest eval cases through Claude?",
            buyer_angle="Fewer failed runs on the workflows customers notice.",
            champion_angle="Simpler orchestration: fewer chained calls to build and debug.",
        )
    if wedge is WedgeId.CLOUD_DRAWDOWN:
        marketplace = _marketplace(signals)
        return _Angle(
            headline=f"{name}: buy Claude through {marketplace} on your existing cloud account",
            subject=f"Claude through {marketplace}",
            hook=(
                f"Claude is sold through {marketplace}, so it can be bought and billed through the "
                "cloud account you already have."
            ),
            talk_track=(
                "Ask how AI spend is bought today and whether they have a committed-spend "
                f"agreement. Explain that Claude is available through {marketplace}; whether it "
                "counts toward a commitment depends on their agreement, so offer to confirm with "
                "the Anthropic partner team. Then connect it to one workload."
            ),
            cta=f"Should I find out what buying through {marketplace} would look like for you?",
            buyer_angle=f"Buy through {marketplace} on the existing cloud agreement.",
            champion_angle="Use Claude without a new procurement cycle.",
        )
    return _Angle(
        headline=f"{name}: where Claude could fit as AI plans take shape",
        subject=f"AI plans at {name}",
        hook=(
            "When teams start building with LLMs, the first choices (model, cost model, how to "
            "buy) are the hardest to change later."
        ),
        talk_track=(
            "There is no strong public AI signal yet. Keep it light: ask whether AI features are "
            "on this year's roadmap and who would own them, and offer a short overview."
        ),
        cta="Worth a short call when AI is on the roadmap?",
        buyer_angle="Make the first AI decisions with the long-term cost model in view.",
        champion_angle="A short overview before the team commits to a stack.",
    )


def _marketplace(signals: TechStackSignals) -> str:
    found = sorted(signals.cloud, key=lambda s: -s.confidence)
    names = [MARKETPLACES[s.provider] for s in found if s.provider in MARKETPLACES]
    return names[0] if names else "your cloud marketplace"


def _money(dollars: int) -> str:
    if dollars >= 1_000_000_000:
        return f"${dollars / 1_000_000_000:g}B"
    return f"${dollars / 1_000_000:g}M"


def _opener(profile: StartupProfile, signals: TechStackSignals) -> str:
    """A natural first line for an email: the freshest public trigger."""
    if signals.ai_roles:
        return f"Saw {profile.company_name} is hiring a {signals.ai_roles[0].title}."
    if profile.last_round_date and profile.funding_stage is not FundingStage.UNKNOWN:
        stage = STAGE_LABELS[profile.funding_stage]
        return f"Congrats on the {stage} round in {profile.last_round_date:%B %Y}."
    return f"I've been following {profile.company_name}'s work."


def _why_now(profile: StartupProfile, signals: TechStackSignals) -> list[str]:
    items = []
    if profile.last_round_date and profile.funding_stage is not FundingStage.UNKNOWN:
        raised = (
            f" ({_money(profile.total_funding_usd)} raised to date)"
            if profile.total_funding_usd
            else ""
        )
        when = profile.last_round_date.strftime("%b %Y")
        items.append(f"Raised a {STAGE_LABELS[profile.funding_stage]} round in {when}{raised}.")
    if signals.ai_role_count:
        n = signals.ai_role_count
        example = f", including '{signals.ai_roles[0].title}'" if signals.ai_roles else ""
        items.append(
            f"Hiring for {n} AI/ML role{'s' if n != 1 else ''} out of {signals.total_open_roles} "
            f"openings{example}."
        )
    incumbents = [
        COMPETITOR_NAMES[c.kind]
        for c in signals.competitors
        if c.kind is not CompetitorKind.ANTHROPIC_EXISTING
    ]
    if any(c.kind is CompetitorKind.ANTHROPIC_EXISTING for c in signals.competitors):
        items.append("Already building on Claude.")
    if incumbents:
        items.append(f"Building with {join(incumbents)} today.")
    clouds = [CLOUD_NAMES[s.provider] for s in signals.cloud if s.provider in CLOUD_NAMES]
    if clouds:
        items.append(f"Runs on {join(clouds)}.")
    return items or ["No strong public trigger yet."]


def _objections(
    signals: TechStackSignals, wedge: WedgeId | None, marketplace: str
) -> list[ObjectionHandle]:
    kinds = {c.kind for c in signals.competitors}
    handles = []
    if CompetitorKind.OPENAI in kinds or CompetitorKind.OTHER_LLM in kinds:
        handles.append(
            ObjectionHandle(
                objection="We're standardized on another model provider.",
                response=(
                    "Most teams don't switch wholesale. Run one cost-heavy workflow on Claude and "
                    "compare cost and quality on your own evals."
                ),
            )
        )
    if CompetitorKind.AZURE_OPENAI in kinds or CloudProvider.AZURE in {
        s.provider for s in signals.cloud
    }:
        handles.append(
            ObjectionHandle(
                objection="We're an Azure shop.",
                response=(
                    "Claude is available on Microsoft Foundry, billed through the Microsoft "
                    "Marketplace."
                ),
            )
        )
    if CompetitorKind.LANGCHAIN in kinds:
        handles.append(
            ObjectionHandle(
                objection="Our stack is built around LangChain.",
                response=(
                    "LangChain supports Claude, so a trial is mostly a model swap behind the same "
                    "chains."
                ),
            )
        )
    if CompetitorKind.VLLM in kinds:
        handles.append(
            ObjectionHandle(
                objection="We self-host open models for cost and data control.",
                response=(
                    "Compare the full cost, GPU capacity and on-call time included, against Claude "
                    "billed and governed through your cloud account."
                ),
            )
        )
    if wedge is WedgeId.CLOUD_DRAWDOWN:
        handles.append(
            ObjectionHandle(
                objection="Procurement takes months.",
                response=(
                    f"Buying through {marketplace} can reuse your existing cloud agreement; we can "
                    "confirm what applies to you with the partner team."
                ),
            )
        )
    handles.append(
        ObjectionHandle(
            objection="It's not a priority this quarter.",
            response=(
                "Understood. Which quarter would it be, and what would need to be true by then?"
            ),
        )
    )
    return handles[:4]


def rules_narrative(
    profile: StartupProfile, value_props: AnthropicValueProps, scorecard: MEDDPICCScorecard
) -> BriefNarrative:
    if profile.tech_stack is None:
        raise ValueError(f"{profile.domain} has no collected signals")
    signals = profile.tech_stack
    wedge = value_props.primary_wedge
    angle = _angle(wedge, profile, signals)
    why_now = _why_now(profile, signals)
    top = value_props.wedges[0] if value_props.wedges else None
    questions = list(top.discovery_questions) if top and wedge else []
    questions += [e.next_action for e in scorecard.elements if e.score is None][:2]
    questions = list(dict.fromkeys(questions)) or ["What would make AI a priority this year?"]

    audience = {
        Recommendation.ROUTE_TO_AE: "For the account team (existing Claude customer): ",
        Recommendation.ROUTE_TO_OWNER: "For the owning rep (outside this territory): ",
    }.get(scorecard.recommendation, "")
    role = signals.ai_roles[0].title if signals.ai_roles else None
    opener = (
        (
            f"Saw {profile.company_name} is hiring a {role}. {angle.hook} Is that on your radar "
            "this quarter?"
        )
        if role
        else f"{angle.hook} Is that on your radar at {profile.company_name} this quarter?"
    )

    buyer = Persona.CTO_FOUNDER if (profile.employee_count or 0) < 100 else Persona.ENG_LEADER
    personas = [
        PersonaTarget(persona=buyer, title_patterns=TITLE_PATTERNS[buyer], angle=angle.buyer_angle),
        PersonaTarget(
            persona=Persona.AI_ML_LEAD,
            title_patterns=TITLE_PATTERNS[Persona.AI_ML_LEAD],
            angle=angle.champion_angle,
        ),
    ]
    if wedge is WedgeId.CLOUD_DRAWDOWN:
        personas.append(
            PersonaTarget(
                persona=Persona.FINANCE,
                title_patterns=TITLE_PATTERNS[Persona.FINANCE],
                angle="AI spend through an existing cloud agreement, if the terms allow it.",
            )
        )

    touches = [
        OutboundTouch(
            step=1,
            channel=Channel.EMAIL,
            day_offset=0,
            subject=angle.subject,
            body=f"Hi [First name],\n\n{_opener(profile, signals)} {angle.hook}\n\n{questions[0]}",
            cta=angle.cta,
        ),
        OutboundTouch(
            step=2,
            channel=Channel.LINKEDIN,
            day_offset=2,
            subject=None,
            body=clip(
                (
                    f"Hi [First name], I work with startups building on LLMs. {angle.hook} Glad to "
                    "connect."
                ),
                300,
            ),
            cta="Connect",
        ),
        OutboundTouch(
            step=3,
            channel=Channel.CALL,
            day_offset=5,
            subject=None,
            body=f"{opener}\n\n{angle.talk_track}",
            cta="Book a 20-minute technical session.",
        ),
        OutboundTouch(
            step=4,
            channel=Channel.EMAIL,
            day_offset=9,
            subject=f"Re: {angle.subject}",
            body=(
                "Hi [First name],\n\nOne question usually tells us whether this is worth a look: "
                f"{questions[min(1, len(questions) - 1)]}\n\nIf it isn't a priority this quarter, "
                "I'll close the loop."
            ),
            cta="A yes or no helps either way.",
        ),
    ]
    return BriefNarrative(
        headline=clip(angle.headline, HEADLINE_MAX_CHARS),
        why_now=why_now,
        talk_track=f"{audience}{angle.talk_track}",
        call_opener=opener,
        personas=personas,
        touches=touches,
        objections=_objections(signals, wedge, _marketplace(signals)),
        discovery_questions=questions,
    )


def narrative_request(
    profile: StartupProfile, value_props: AnthropicValueProps, scorecard: MEDDPICCScorecard
) -> StructuredRequest[BriefNarrative]:
    return StructuredRequest(
        schema=BriefNarrative,
        system=SYSTEM_PROMPT,
        user=f"{account_block(profile, value_props, scorecard)}\n\n{NARRATIVE_TASK}",
        deterministic=lambda: rules_narrative(profile, value_props, scorecard),
    )


def build_brief(
    profile: StartupProfile,
    value_props: AnthropicValueProps,
    scorecard: MEDDPICCScorecard,
    llm: LLMClient,
    *,
    generated_at: datetime | None = None,
) -> tuple[SDROutboundBrief, LLMUsage]:
    if profile.tech_stack is None:
        raise ValueError(f"{profile.domain} has no collected signals")
    narrative, usage = llm.generate(narrative_request(profile, value_props, scorecard))
    brief = SDROutboundBrief(
        generated_at=generated_at or datetime.now(UTC),
        profile=profile,
        value_props=value_props,
        scorecard=scorecard,
        narrative=narrative,
        evidence=profile.tech_stack.evidence,
        data_source=profile.tech_stack.data_source,
    )
    return brief, usage


# --------------------------------------------------------------------------- Markdown


def _text(value: object) -> str:
    """One line of untrusted text, safe inside Markdown: no HTML, no table breaks."""
    flat = " ".join(str(value).split())
    return flat.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("|", "\\|")


def _label(value: str) -> str:
    return value.replace("_", " ").capitalize()


def to_markdown(brief: SDROutboundBrief) -> str:
    profile, vp, card, story = brief.profile, brief.value_props, brief.scorecard, brief.narrative
    signals = profile.tech_stack
    lines = [f"# {_text(profile.company_name)}: SDR outbound brief", ""]
    if brief.data_source is not DataSource.LIVE:
        lines += [
            f"> **ILLUSTRATIVE DATA.** Built from {brief.data_source.value} signals, not a live "
            "collection. Do not use it for real outreach.",
            "",
        ]
    primary = next((w for w in vp.wedges if w.wedge_id is vp.primary_wedge), None)
    lead = f"{primary.title} (fit {primary.fit_score})" if primary else "none"
    lines += [
        f"**Recommendation:** {_label(card.recommendation)} · **Tier:** {card.tier} · "
        f"**MEDDPICC:** {card.total_score}/100 ({card.coverage_pct:g}% coverage) · "
        f"**Primary wedge:** {lead}",
        "",
        f"## {_text(story.headline)}",
        "",
    ]
    if vp.suppressions:
        lines += [*(f"- **Note:** {_text(s)}" for s in vp.suppressions), ""]

    hq = ", ".join(filter(None, [profile.hq_city, profile.hq_state]))
    territory = "in territory" if profile.in_territory else "outside territory"
    stage = STAGE_LABELS.get(profile.funding_stage, "unknown")
    if profile.total_funding_usd:
        stage += f" · {_money(profile.total_funding_usd)} raised"
    if profile.last_round_date:
        stage += f" · last round {profile.last_round_date.strftime('%b %Y')}"
    snapshot = [
        ("Domain", profile.domain),
        ("HQ", f"{hq} ({territory})"),
        ("Stage", stage),
        ("Headcount", profile.employee_count or "unknown"),
        ("Vertical", profile.vertical or "unknown"),
    ]
    if signals is not None:
        clouds = [CLOUD_NAMES[s.provider] for s in signals.cloud if s.provider in CLOUD_NAMES]
        snapshot += [
            ("Hiring", f"{signals.ai_role_count} AI/ML of {signals.total_open_roles} open roles"),
            ("Cloud", join(clouds) or "not visible"),
            (
                "Incumbents",
                join([COMPETITOR_NAMES[c.kind] for c in signals.competitors]) or "none seen",
            ),
        ]
    lines += ["## Snapshot", "", "| | |", "|---|---|"]
    lines += [f"| {key} | {_text(value)} |" for key, value in snapshot]
    lines += ["", "## Why now", "", *(f"- {_text(item)}" for item in story.why_now), ""]

    lines += ["## Wedges", "", "| Wedge | Fit | Confidence | Evidence |", "|---|---|---|---|"]
    lines += [
        (
            f"| {w.title} | {w.fit_score} | {w.confidence:.0%} | "
            f"{', '.join(w.trigger_evidence_ids) or '-'} |"
        )
        for w in vp.wedges
    ]
    lines += ["", f"_{_text(vp.rationale)}_", ""]
    if primary:
        lines += [f"### {primary.title}", "", _text(primary.hypothesis), "", "**Proof points**", ""]
        lines += [f"- {_text(p)}" for p in primary.proof_points]
        if primary.impact:
            lines += [
                "",
                (
                    f"**Impact (illustrative):** {_text(primary.impact.label)}. "
                    f"{_text(primary.impact.assumptions)}"
                ),
            ]
        lines += [""]

    lines += [
        "## MEDDPICC scorecard",
        "",
        "| Element | Score | Status | Health | Evidence | Next action |",
        "|---|---|---|---|---|---|",
    ]
    lines += [
        f"| {ELEMENT_LABELS[e.element]} | {'-' if e.score is None else e.score} | {e.status} | "
        f"{e.health} | {', '.join(e.evidence_ids) or '-'} | {_text(e.next_action)} |"
        for e in card.elements
    ]
    lines += ["", _text(card.summary), ""]

    lines += [
        "## Talk track",
        "",
        _text(story.talk_track),
        "",
        "## Call opener",
        "",
        _text(story.call_opener),
        "",
    ]
    lines += ["## Sequence", ""]
    for touch in story.touches:
        channel = CHANNEL_LABELS[touch.channel]
        lines += [f"### Step {touch.step} · Day {touch.day_offset} · {channel}", ""]
        if touch.subject:
            lines += [f"**Subject:** {_text(touch.subject)}", ""]
        for paragraph in touch.body.split("\n\n"):
            lines += [_text(paragraph), ""]
        lines += [f"**CTA:** {_text(touch.cta)}", ""]
    lines += ["## Personas", ""]
    lines += [
        f"- **{_label(p.persona)}** ({_text(', '.join(p.title_patterns))}): {_text(p.angle)}"
        for p in story.personas
    ]
    lines += ["", "## Objections", ""]
    lines += [f"- **{_text(o.objection)}** {_text(o.response)}" for o in story.objections]
    lines += [
        "",
        "## Discovery questions",
        "",
        *(f"- {_text(q)}" for q in story.discovery_questions),
        "",
    ]

    lines += ["## Evidence", ""]
    for e in brief.evidence:
        source = f" ([source]({e.source_url}))" if e.source_url else ""
        lines.append(f"- **{e.id}** ({_label(e.kind)}): {_text(e.snippet)}{source}")
    by = card.model_id or ("mock LLM" if card.generated_by == "mock" else "rules")
    lines += [
        "",
        "---",
        "",
        f"_{_text(brief.disclaimer)} Data source: {brief.data_source}. Generated "
        f"{brief.generated_at:%Y-%m-%d %H:%M} UTC by {_text(by)}._",
        "",
    ]
    return "\n".join(lines)
