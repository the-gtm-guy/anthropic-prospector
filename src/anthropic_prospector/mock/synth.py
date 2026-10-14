"""Deterministic synthetic signals for domains that have no fixture.

Same domain, same signals, on any machine and any Python version: every choice comes from
sha256(domain), never from `random` or `hash()`. The output is marked synthetic wherever
it could be read: data_source=mock, evidence kind "mock", a "[synthetic]" prefix on every
snippet, and URLs on the reserved `.invalid` TLD so nothing links to a real site.
"""

import hashlib
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Final, TypeVar

from anthropic_prospector.models import (
    ATSPlatform,
    CloudProvider,
    CloudSignal,
    CompetitorKind,
    CompetitorSignal,
    DataSource,
    Evidence,
    JobPosting,
    SignalKeyword,
    StartupProfile,
    TechStackSignals,
)

SYNTHETIC_WARNING: Final = "synthetic signals: no fixture or live data for this domain"

_T = TypeVar("_T")

_ATS_CHOICES: Final = (ATSPlatform.GREENHOUSE, ATSPlatform.LEVER, ATSPlatform.ASHBY)

_AI_ROLE_TITLES: Final = (
    "Senior ML Engineer, LLM Platform",
    "AI Engineer, Agents",
    "Applied Scientist, NLP",
    "Staff Engineer, AI Infrastructure",
    "ML Engineer, Evaluation",
    "Product Engineer, Generative AI",
)

# (cumulative percent, providers). The last band is hosting hidden behind a CDN.
_CLOUD_MIX: Final[tuple[tuple[int, tuple[CloudProvider, ...]], ...]] = (
    (50, (CloudProvider.AWS,)),
    (72, (CloudProvider.GCP,)),
    (82, (CloudProvider.AZURE,)),
    (92, (CloudProvider.AWS, CloudProvider.GCP)),
    (100, ()),
)

_CLOUD_EVIDENCE: Final = {
    CloudProvider.AWS: "DNS: the app host is a CNAME for an AWS load balancer.",
    CloudProvider.GCP: "DNS: the app host is served from Google Cloud Run.",
    CloudProvider.AZURE: "DNS: the app host is a CNAME for an Azure Front Door endpoint.",
}

# Rolled in order. vLLM and existing Claude usage are deliberately rare.
_COMPETITOR_ODDS: Final = (
    (CompetitorKind.OPENAI, 0.6),
    (CompetitorKind.LANGCHAIN, 0.4),
    (CompetitorKind.VLLM, 0.12),
    (CompetitorKind.OTHER_LLM, 0.1),
    (CompetitorKind.ANTHROPIC_EXISTING, 0.06),
)

_KEYWORD_PHRASES: Final = {
    SignalKeyword.RAG: "retrieval-augmented generation (RAG)",
    SignalKeyword.AGENTS: "building LLM agents",
    SignalKeyword.EVALS: "LLM evals",
    SignalKeyword.CODE_GENERATION: "code generation",
    SignalKeyword.DOCUMENT_PROCESSING: "document processing",
    SignalKeyword.LONG_CONTEXT: "long-context prompts",
    SignalKeyword.CUSTOMER_SUPPORT: "AI customer support",
    SignalKeyword.MULTI_STEP_REASONING: "multi-step reasoning",
    SignalKeyword.INFERENCE_COST: "inference cost",
    SignalKeyword.LATENCY: "model latency",
    SignalKeyword.FINE_TUNING: "fine-tuning models",
    SignalKeyword.SELF_HOSTED_MODELS: "self-hosted models",
    SignalKeyword.GPU_INFRA: "GPU infrastructure",
    SignalKeyword.COMPLIANCE: "SOC 2 and security reviews",
}

_COMPETITOR_EVIDENCE: Final = {
    CompetitorKind.OPENAI: "Job post asks for production experience with the OpenAI API.",
    CompetitorKind.AZURE_OPENAI: "Job post lists Azure OpenAI in the stack.",
    CompetitorKind.LANGCHAIN: "Job post lists LangChain for LLM orchestration.",
    CompetitorKind.VLLM: "Job post mentions serving open-weight models with vLLM.",
    CompetitorKind.OTHER_LLM: "Job post mentions fine-tuning open-weight models.",
    CompetitorKind.ANTHROPIC_EXISTING: "Job post mentions building with Claude.",
}


class _Dice:
    """A deterministic stream of choices seeded by a string."""

    def __init__(self, seed: str) -> None:
        self._seed = seed.encode()
        self._counter = 0

    def _next(self) -> int:
        block = hashlib.sha256(self._seed + self._counter.to_bytes(8, "big")).digest()
        self._counter += 1
        return int.from_bytes(block[:8], "big")

    def below(self, n: int) -> int:
        return self._next() % n

    def chance(self, p: float) -> bool:
        return self._next() < p * 2**64

    def choice(self, items: Sequence[_T]) -> _T:
        return items[self.below(len(items))]

    def sample(self, items: Sequence[_T], k: int) -> list[_T]:
        pool = list(items)
        k = min(k, len(pool))
        for i in range(k):
            j = i + self.below(len(pool) - i)
            pool[i], pool[j] = pool[j], pool[i]
        return pool[:k]

    def confidence(self) -> float:
        return round(0.55 + self.below(40) / 100, 2)


def synthesize_signals(
    profile: StartupProfile, *, collected_at: datetime | None = None
) -> TechStackSignals:
    dice = _Dice(profile.domain)
    observed = collected_at or datetime.now(UTC)
    evidence: list[Evidence] = []

    def cite(snippet: str) -> list[str]:
        evidence.append(
            Evidence(
                id=f"E{len(evidence) + 1}",
                kind="mock",
                snippet=f"[synthetic] {snippet}",
                observed_at=observed,
            )
        )
        return [evidence[-1].id]

    ats = profile.ats_hint
    if ats is None or ats is ATSPlatform.UNKNOWN:
        ats = dice.choice(_ATS_CHOICES)

    headcount = profile.employee_count or 20 + dice.below(180)
    total_open_roles = max(1, round(headcount * (6 + dice.below(10)) / 100))
    has_ai = not dice.chance(0.15)
    ai_role_count = min(total_open_roles, 1 + dice.below(5)) if has_ai else 0
    ai_roles = [
        JobPosting(
            ats=ats,
            external_id=f"synthetic-{n}",
            title=title,
            url=f"https://jobs.invalid/{profile.domain}/{n}",
            description_text=f"[synthetic] {title} at {profile.company_name}.",
        )
        for n, title in enumerate(dice.sample(_AI_ROLE_TITLES, min(ai_role_count, 3)), start=1)
    ]

    roll = dice.below(100)
    providers = next(group for cutoff, group in _CLOUD_MIX if roll < cutoff)
    cloud = [
        CloudSignal(provider=p, confidence=dice.confidence(), evidence_ids=cite(_CLOUD_EVIDENCE[p]))
        for p in providers
    ]
    if len(providers) > 1:
        primary_cloud = CloudProvider.MULTI
    else:
        primary_cloud = providers[0] if providers else CloudProvider.UNKNOWN

    competitors: list[CompetitorSignal] = []
    keyword_hits: dict[SignalKeyword, int] = {}
    keyword_evidence: dict[SignalKeyword, list[str]] = {}
    if has_ai:
        for kind, odds in _COMPETITOR_ODDS:
            if dice.chance(odds):
                found = (
                    CompetitorKind.AZURE_OPENAI
                    if kind is CompetitorKind.OPENAI and CloudProvider.AZURE in providers
                    else kind
                )
                competitors.append(
                    CompetitorSignal(
                        kind=found,
                        confidence=dice.confidence(),
                        evidence_ids=cite(_COMPETITOR_EVIDENCE[found]),
                    )
                )
        for keyword in dice.sample(list(SignalKeyword), 2 + dice.below(4)):
            keyword_hits[keyword] = 1 + dice.below(5)
            keyword_evidence[keyword] = cite(f"Job post mentions {_KEYWORD_PHRASES[keyword]}.")

    return TechStackSignals(
        domain=profile.domain,
        ats=ats,
        ats_board_token=profile.ats_board_token,
        total_open_roles=total_open_roles,
        ai_role_count=ai_role_count,
        ai_roles=ai_roles,
        cloud=cloud,
        primary_cloud=primary_cloud,
        competitors=competitors,
        keyword_hits=keyword_hits,
        keyword_evidence=keyword_evidence,
        evidence=evidence,
        data_source=DataSource.MOCK,
        collected_at=observed,
        warnings=[SYNTHETIC_WARNING],
    )
