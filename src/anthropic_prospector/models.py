"""Domain contracts shared by every layer of anthropic-prospector.

This module is the root of the import graph: it imports only the standard library and
pydantic, never another module in this package (tests/test_import_dag.py enforces this).
Domain rules that computed fields depend on (territory, MEDDPICC weights, tier cut-offs,
wedge priority) therefore live here rather than in config.py.

Two model families:

* `_Contract` models carry data between layers. They forbid unknown fields, validate on
  assignment, and accept their own JSON dumps (computed fields are ignored on input).
* `_LLMSchema` models are the narrow shapes the LLM fills in. Every field is required and
  none is computed, so `model_json_schema()` is a faithful structured-output contract.
"""

import math
import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, date, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Annotated, Any, Final, Literal, Self
from urllib.parse import urlsplit

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    NonNegativeFloat,
    NonNegativeInt,
    PositiveInt,
    ValidationInfo,
    computed_field,
    field_validator,
    model_validator,
)

__all__ = [
    "DISCLAIMER",
    "HEADLINE_MAX_CHARS",
    "MAX_AI_ROLES",
    "MEDDPICC_WEIGHTS",
    "POSTING_TEXT_MAX_CHARS",
    "SNIPPET_MAX_CHARS",
    "TERRITORY_STATES",
    "TIER_RULES",
    "US_STATES",
    "WEDGE_PRIORITY",
    "ATSPlatform",
    "AnalysisResult",
    "AnthropicValueProps",
    "BriefNarrative",
    "Channel",
    "CloudProvider",
    "CloudSignal",
    "CompetitorKind",
    "CompetitorSignal",
    "Confidence",
    "Contact",
    "DataSource",
    "Domain",
    "ElementRefinement",
    "ElementScore",
    "ElementStatus",
    "Evidence",
    "EvidenceKind",
    "FundingStage",
    "Health",
    "ImpactEstimate",
    "JobPosting",
    "LLMUsage",
    "MEDDPICCElement",
    "MEDDPICCScorecard",
    "ObjectionHandle",
    "OutboundTouch",
    "Persona",
    "PersonaTarget",
    "Recommendation",
    "RowError",
    "SDROutboundBrief",
    "Score10",
    "Score100",
    "ScorecardRefinement",
    "SignalKeyword",
    "StartupProfile",
    "StateCode",
    "TargetBatch",
    "TechStackSignals",
    "Tier",
    "UtcDatetime",
    "WebUrl",
    "WedgeId",
    "WedgeMatch",
    "clip",
    "normalize_domain",
    "normalize_state",
]

# --------------------------------------------------------------------------- enums


class DataSource(StrEnum):
    """Where a record's facts came from. Mock data is never presented as live."""

    LIVE = "live"
    MOCK = "mock"
    HYBRID = "hybrid"


class ATSPlatform(StrEnum):
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    ASHBY = "ashby"
    UNKNOWN = "unknown"


class CloudProvider(StrEnum):
    AWS = "aws"
    GCP = "gcp"
    AZURE = "azure"
    MULTI = "multi"
    UNKNOWN = "unknown"


class CompetitorKind(StrEnum):
    OPENAI = "openai"
    LANGCHAIN = "langchain"
    VLLM = "vllm"
    AZURE_OPENAI = "azure_openai"
    OTHER_LLM = "other_llm"
    ANTHROPIC_EXISTING = "anthropic_existing"  # already uses Claude: route to the AE


class WedgeId(StrEnum):
    PROMPT_CACHING = "prompt_caching"
    EXTENDED_THINKING = "extended_thinking"
    CLOUD_DRAWDOWN = "cloud_drawdown"


class FundingStage(StrEnum):
    PRE_SEED = "pre_seed"
    SEED = "seed"
    SERIES_A = "series_a"
    SERIES_B = "series_b"
    SERIES_C_PLUS = "series_c_plus"
    UNKNOWN = "unknown"


class MEDDPICCElement(StrEnum):
    """Declared in canonical M-E-D-D-P-I-C-C order; scorecards are sorted by it."""

    METRICS = "metrics"
    ECONOMIC_BUYER = "economic_buyer"
    DECISION_CRITERIA = "decision_criteria"
    DECISION_PROCESS = "decision_process"
    PAPER_PROCESS = "paper_process"
    IDENTIFY_PAIN = "identify_pain"
    CHAMPION = "champion"
    COMPETITION = "competition"


class ElementStatus(StrEnum):
    UNKNOWN = "unknown"
    HYPOTHESIZED = "hypothesized"
    VALIDATED = "validated"


class Health(StrEnum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"
    GREY = "grey"  # unknown, which is not the same as bad


class Tier(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class Recommendation(StrEnum):
    PURSUE = "pursue"
    NURTURE = "nurture"
    DISQUALIFY = "disqualify"
    ROUTE_TO_AE = "route_to_ae"


class Persona(StrEnum):
    ENG_LEADER = "eng_leader"
    AI_ML_LEAD = "ai_ml_lead"
    CTO_FOUNDER = "cto_founder"
    FINANCE = "finance"
    PROCUREMENT = "procurement"


class Channel(StrEnum):
    EMAIL = "email"
    LINKEDIN = "linkedin"
    CALL = "call"


class SignalKeyword(StrEnum):
    """Use-case and buying signals found in job posts and pages. Wedge rules key off these."""

    RAG = "rag"
    AGENTS = "agents"
    EVALS = "evals"
    CODE_GENERATION = "code_generation"
    DOCUMENT_PROCESSING = "document_processing"
    LONG_CONTEXT = "long_context"
    CUSTOMER_SUPPORT = "customer_support"
    MULTI_STEP_REASONING = "multi_step_reasoning"
    INFERENCE_COST = "inference_cost"
    LATENCY = "latency"
    FINE_TUNING = "fine_tuning"
    SELF_HOSTED_MODELS = "self_hosted_models"
    GPU_INFRA = "gpu_infra"
    COMPLIANCE = "compliance"


EvidenceKind = Literal["job_posting", "dns", "web", "user_input", "mock"]

# --------------------------------------------------------------------------- domain rules

TERRITORY_STATES: Final[frozenset[str]] = frozenset({"CA", "WA", "OR", "AZ"})

MEDDPICC_WEIGHTS: Final[Mapping[MEDDPICCElement, int]] = MappingProxyType(
    {
        MEDDPICCElement.IDENTIFY_PAIN: 20,
        MEDDPICCElement.METRICS: 15,
        MEDDPICCElement.ECONOMIC_BUYER: 15,
        MEDDPICCElement.CHAMPION: 15,
        MEDDPICCElement.DECISION_CRITERIA: 10,
        MEDDPICCElement.DECISION_PROCESS: 10,
        MEDDPICCElement.COMPETITION: 10,
        MEDDPICCElement.PAPER_PROCESS: 5,
    }
)

# (tier, minimum total_score, minimum coverage_pct). First match wins; anything else is D.
TIER_RULES: Final[tuple[tuple[Tier, int, float], ...]] = (
    (Tier.A, 70, 50.0),
    (Tier.B, 55, 37.5),
    (Tier.C, 40, 25.0),
)

# Tie-break between wedges with equal fit scores, most broadly applicable first.
WEDGE_PRIORITY: Final[tuple[WedgeId, ...]] = (
    WedgeId.PROMPT_CACHING,
    WedgeId.CLOUD_DRAWDOWN,
    WedgeId.EXTENDED_THINKING,
)

DISCLAIMER: Final = (
    "Signals are inferred from public data and may be incomplete or out of date. "
    "Verify them before outreach."
)

SNIPPET_MAX_CHARS: Final = 280
POSTING_TEXT_MAX_CHARS: Final = 6000
MAX_AI_ROLES: Final = 10
HEADLINE_MAX_CHARS: Final = 120

US_STATES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "AL": "Alabama",
        "AK": "Alaska",
        "AZ": "Arizona",
        "AR": "Arkansas",
        "CA": "California",
        "CO": "Colorado",
        "CT": "Connecticut",
        "DE": "Delaware",
        "DC": "District of Columbia",
        "FL": "Florida",
        "GA": "Georgia",
        "HI": "Hawaii",
        "ID": "Idaho",
        "IL": "Illinois",
        "IN": "Indiana",
        "IA": "Iowa",
        "KS": "Kansas",
        "KY": "Kentucky",
        "LA": "Louisiana",
        "ME": "Maine",
        "MD": "Maryland",
        "MA": "Massachusetts",
        "MI": "Michigan",
        "MN": "Minnesota",
        "MS": "Mississippi",
        "MO": "Missouri",
        "MT": "Montana",
        "NE": "Nebraska",
        "NV": "Nevada",
        "NH": "New Hampshire",
        "NJ": "New Jersey",
        "NM": "New Mexico",
        "NY": "New York",
        "NC": "North Carolina",
        "ND": "North Dakota",
        "OH": "Ohio",
        "OK": "Oklahoma",
        "OR": "Oregon",
        "PA": "Pennsylvania",
        "RI": "Rhode Island",
        "SC": "South Carolina",
        "SD": "South Dakota",
        "TN": "Tennessee",
        "TX": "Texas",
        "UT": "Utah",
        "VT": "Vermont",
        "VA": "Virginia",
        "WA": "Washington",
        "WV": "West Virginia",
        "WI": "Wisconsin",
        "WY": "Wyoming",
    }
)
_STATE_CODES_BY_NAME: Final = {name.lower(): code for code, name in US_STATES.items()}

# --------------------------------------------------------------------------- normalizers

_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*://")
_HOST_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")


def normalize_domain(value: str) -> str:
    """Reduce a URL or hostname to a bare lowercase host: no scheme, www., port or path.

    Internationalized names are converted to their ASCII (punycode) form.
    """
    host = _SCHEME.sub("", value.strip().lower())
    host = re.split(r"[/?#]", host, maxsplit=1)[0]
    host = host.rpartition("@")[2].partition(":")[0].rstrip(".")
    host = host.removeprefix("www.")
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError(f"invalid domain: {value!r}") from exc
    labels = host.split(".")
    if len(host) > 253 or len(labels) < 2 or not all(map(_HOST_LABEL.match, labels)):
        raise ValueError(f"invalid domain: {value!r}")
    if not any(ch.isalpha() for ch in labels[-1]):
        raise ValueError(f"invalid domain (an IP address is not a company domain): {value!r}")
    return host


def normalize_state(value: str) -> str:
    """Accept a two-letter US state code or a full state name; return the code."""
    cleaned = " ".join(value.split())
    if cleaned.upper() in US_STATES:
        return cleaned.upper()
    if code := _STATE_CODES_BY_NAME.get(cleaned.lower()):
        return code
    raise ValueError(f"not a US state code or name: {value!r}")


def clip(text: str, limit: int) -> str:
    """Trim surrounding whitespace and cut to at most `limit` characters, marking cuts with '…'."""
    if limit < 1:
        raise ValueError("limit must be at least 1")
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _clip_to(limit: int) -> Callable[[Any], Any]:
    def clip_if_text(value: Any) -> Any:
        return clip(value, limit) if isinstance(value, str) else value

    return clip_if_text


def _require_http_url(value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError(f"expected an absolute http(s) URL, got {value!r}")
    return value


def _as_utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


# --------------------------------------------------------------------------- field types

Confidence = Annotated[float, Field(ge=0.0, le=1.0)]
Score10 = Annotated[int, Field(ge=0, le=10)]
Score100 = Annotated[int, Field(ge=0, le=100)]
Domain = Annotated[str, AfterValidator(normalize_domain)]
StateCode = Annotated[str, AfterValidator(normalize_state)]
WebUrl = Annotated[str, AfterValidator(_require_http_url)]
UtcDatetime = Annotated[AwareDatetime, AfterValidator(_as_utc)]
# Scraped free text is clipped rather than rejected: its length is the source's choice.
Snippet = Annotated[str, BeforeValidator(_clip_to(SNIPPET_MAX_CHARS))]
PostingText = Annotated[str, BeforeValidator(_clip_to(POSTING_TEXT_MAX_CHARS))]

# --------------------------------------------------------------------------- base classes


class _Contract(BaseModel):
    """Data passed between layers."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, validate_assignment=True)

    @model_validator(mode="before")
    @classmethod
    def _ignore_computed_fields(cls, data: Any) -> Any:
        # Computed fields are outputs. Dropping them on input lets every contract load its
        # own JSON dump (batch checkpoints, exported briefs) despite extra="forbid".
        if isinstance(data, dict) and cls.model_computed_fields:
            return {k: v for k, v in data.items() if k not in cls.model_computed_fields}
        return data


class _LLMSchema(BaseModel):
    """A shape the LLM fills in. Every field is required, so the JSON schema hides nothing."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# --------------------------------------------------------------------------- signals


class Evidence(_Contract):
    """One piece of public evidence. Every downstream claim cites these ids."""

    id: str = Field(pattern=r"^E[1-9]\d*$")
    kind: EvidenceKind
    source_url: WebUrl | None = None
    snippet: Snippet
    observed_at: UtcDatetime


def _unique_evidence_ids(evidence: Iterable[Evidence]) -> set[str]:
    counts = Counter(e.id for e in evidence)
    if duplicates := sorted(i for i, n in counts.items() if n > 1):
        raise ValueError(f"duplicate evidence ids: {', '.join(duplicates)}")
    return set(counts)


def _require_cited(cited: Iterable[str], known: set[str], where: str) -> None:
    if missing := sorted(set(cited) - known):
        raise ValueError(f"{where} cite unknown evidence ids: {', '.join(missing)}")


class JobPosting(_Contract):
    ats: ATSPlatform
    external_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    url: WebUrl
    location: str | None = None
    department: str | None = None
    description_text: PostingText = ""
    posted_at: UtcDatetime | None = None


class CloudSignal(_Contract):
    provider: CloudProvider
    confidence: Confidence
    evidence_ids: list[str] = Field(min_length=1)

    @field_validator("provider")
    @classmethod
    def _one_concrete_provider(cls, value: CloudProvider) -> CloudProvider:
        if value in (CloudProvider.MULTI, CloudProvider.UNKNOWN):
            raise ValueError("a cloud signal names one concrete provider")
        return value


class CompetitorSignal(_Contract):
    kind: CompetitorKind
    confidence: Confidence
    evidence_ids: list[str] = Field(min_length=1)


class TechStackSignals(_Contract):
    domain: Domain
    ats: ATSPlatform = ATSPlatform.UNKNOWN
    ats_board_token: str | None = None
    total_open_roles: NonNegativeInt = 0
    ai_role_count: NonNegativeInt = 0
    ai_roles: list[JobPosting] = Field(default_factory=list, max_length=MAX_AI_ROLES)
    cloud: list[CloudSignal] = Field(default_factory=list)
    primary_cloud: CloudProvider = CloudProvider.UNKNOWN
    competitors: list[CompetitorSignal] = Field(default_factory=list)
    keyword_hits: dict[SignalKeyword, NonNegativeInt] = Field(default_factory=dict)
    evidence: list[Evidence] = Field(default_factory=list)
    data_source: DataSource
    collected_at: UtcDatetime
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.ai_role_count > self.total_open_roles:
            raise ValueError("ai_role_count cannot exceed total_open_roles")
        if len(self.ai_roles) > self.ai_role_count:
            raise ValueError("ai_roles lists more postings than ai_role_count")

        known = _unique_evidence_ids(self.evidence)
        signals: list[CloudSignal | CompetitorSignal] = [*self.cloud, *self.competitors]
        _require_cited((i for s in signals for i in s.evidence_ids), known, "signals")

        providers = [s.provider for s in self.cloud]
        if len(set(providers)) != len(providers):
            raise ValueError("each cloud provider may have at most one signal")
        kinds = [s.kind for s in self.competitors]
        if len(set(kinds)) != len(kinds):
            raise ValueError("each competitor may have at most one signal")

        if self.primary_cloud is CloudProvider.MULTI:
            if len(providers) < 2:
                raise ValueError("primary_cloud 'multi' needs signals for two or more providers")
        elif self.primary_cloud not in (CloudProvider.UNKNOWN, *providers):
            raise ValueError(f"primary_cloud {self.primary_cloud!s} has no supporting signal")
        return self


# --------------------------------------------------------------------------- profile


class Contact(_Contract):
    """Supplied by the user (targets CSV). Never scraped, never guessed."""

    name: str = Field(min_length=1)
    title: str = Field(min_length=1)
    persona: Persona | None = None
    linkedin_url: WebUrl | None = None


class StartupProfile(_Contract):
    company_name: str = Field(min_length=1)
    domain: Domain
    # Empty means "derive from domain"; the validator fills in https://<domain>.
    website_url: WebUrl = Field(default="", validate_default=True)
    hq_city: str | None = None
    hq_state: StateCode
    description: str | None = None
    vertical: str | None = None
    employee_count: int | None = Field(default=None, ge=1)
    funding_stage: FundingStage = FundingStage.UNKNOWN
    total_funding_usd: NonNegativeInt | None = None
    last_round_date: date | None = None
    investors: list[str] = Field(default_factory=list)
    founded_year: int | None = Field(default=None, ge=1900, le=2100)
    ats_hint: ATSPlatform | None = None
    ats_board_token: str | None = None
    contacts: list[Contact] = Field(default_factory=list)
    tech_stack: TechStackSignals | None = None

    @field_validator("website_url", mode="before")
    @classmethod
    def _default_website(cls, value: Any, info: ValidationInfo) -> Any:
        if value in (None, "") and "domain" in info.data:
            return f"https://{info.data['domain']}"
        return value

    @model_validator(mode="after")
    def _tech_stack_matches(self) -> Self:
        if self.tech_stack is not None and self.tech_stack.domain != self.domain:
            raise ValueError(
                f"tech_stack is for {self.tech_stack.domain}, profile is for {self.domain}"
            )
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def in_territory(self) -> bool:
        return self.hq_state in TERRITORY_STATES


# --------------------------------------------------------------------------- wedges


class ImpactEstimate(_Contract):
    """Illustrative only: a range to validate in discovery, never a promised saving."""

    label: str = Field(min_length=1)
    low_pct: float | None = Field(default=None, ge=0, le=100)
    high_pct: float | None = Field(default=None, ge=0, le=100)
    assumptions: str = Field(min_length=1)

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.low_pct is not None and self.high_pct is not None and self.low_pct > self.high_pct:
            raise ValueError("low_pct cannot exceed high_pct")
        return self


class WedgeMatch(_Contract):
    wedge_id: WedgeId
    title: str = Field(min_length=1)
    fit_score: Score100
    confidence: Confidence
    trigger_evidence_ids: list[str] = Field(default_factory=list)
    hypothesis: str = Field(min_length=1)
    proof_points: list[str] = Field(default_factory=list)
    discovery_questions: list[str] = Field(default_factory=list)
    impact: ImpactEstimate | None = None


class AnthropicValueProps(_Contract):
    domain: Domain
    wedges: list[WedgeMatch] = Field(default_factory=list)
    primary_wedge: WedgeId | None = None
    overall_fit: Score100 = 0
    suppressions: list[str] = Field(default_factory=list)
    rationale: str = Field(min_length=1)

    @field_validator("wedges")
    @classmethod
    def _ranked(cls, wedges: list[WedgeMatch]) -> list[WedgeMatch]:
        ids = [w.wedge_id for w in wedges]
        if len(set(ids)) != len(ids):
            raise ValueError("each wedge may appear at most once")
        return sorted(wedges, key=lambda w: (-w.fit_score, WEDGE_PRIORITY.index(w.wedge_id)))

    @model_validator(mode="after")
    def _primary_is_top(self) -> Self:
        if self.primary_wedge is not None and (
            not self.wedges or self.wedges[0].wedge_id is not self.primary_wedge
        ):
            raise ValueError("primary_wedge must be the top-ranked wedge (or None if suppressed)")
        return self


# --------------------------------------------------------------------------- MEDDPICC


class ElementScore(_Contract):
    element: MEDDPICCElement
    score: Score10 | None = None  # None means unknown
    status: ElementStatus = ElementStatus.UNKNOWN
    evidence_ids: list[str] = Field(default_factory=list)
    rationale: str = Field(min_length=1)
    gaps: list[str] = Field(default_factory=list)
    next_action: str = Field(min_length=1)
    confidence: Confidence

    @model_validator(mode="after")
    def _status_matches_score(self) -> Self:
        if (self.status is ElementStatus.UNKNOWN) != (self.score is None):
            raise ValueError("score must be None exactly when status is 'unknown'")
        if self.status is ElementStatus.VALIDATED and not self.evidence_ids:
            raise ValueError("a validated element must cite evidence")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def health(self) -> Health:
        if self.score is None:
            return Health.GREY
        if self.score >= 7:
            return Health.GREEN
        if self.score >= 4:
            return Health.YELLOW
        return Health.RED


class MEDDPICCScorecard(_Contract):
    # Pydantic < 2.10 reserves the whole "model_" prefix and warns about `model_id`.
    model_config = ConfigDict(protected_namespaces=())

    domain: Domain
    elements: list[ElementScore]
    recommendation: Recommendation
    summary: str = Field(min_length=1)
    generated_by: Literal["rules", "llm", "mock"]
    model_id: str | None = None
    data_source: DataSource

    @field_validator("elements")
    @classmethod
    def _one_per_element(cls, elements: list[ElementScore]) -> list[ElementScore]:
        counts = Counter(e.element for e in elements)
        missing = [str(e) for e in MEDDPICCElement if e not in counts]
        repeated = [str(e) for e, n in counts.items() if n > 1]
        if missing or repeated:
            raise ValueError(
                "a scorecard has exactly one entry per MEDDPICC element "
                f"(missing: {missing or 'none'}; repeated: {repeated or 'none'})"
            )
        order = list(MEDDPICCElement)
        return sorted(elements, key=lambda e: order.index(e.element))

    def element(self, element: MEDDPICCElement) -> ElementScore:
        return next(e for e in self.elements if e.element is element)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_score(self) -> int:
        """Weighted score over the known elements only, renormalized to 0-100.

        Unknown elements lower coverage_pct, not the score: pre-discovery, most of
        MEDDPICC is legitimately unknown, and unknown is not the same as bad.
        """
        scored = [
            (MEDDPICC_WEIGHTS[e.element], e.score) for e in self.elements if e.score is not None
        ]
        weight = sum(w for w, _ in scored)
        if weight == 0:
            return 0
        return math.floor(sum(w * s for w, s in scored) * 10 / weight + 0.5)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def coverage_pct(self) -> float:
        known = sum(1 for e in self.elements if e.score is not None)
        return round(100 * known / len(MEDDPICCElement), 1)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def tier(self) -> Tier:
        for tier, min_score, min_coverage in TIER_RULES:
            if self.total_score >= min_score and self.coverage_pct >= min_coverage:
                return tier
        return Tier.D


# --------------------------------------------------------------------------- LLM-facing schemas


class ElementRefinement(_LLMSchema):
    element: MEDDPICCElement
    rationale: str = Field(min_length=1)
    discovery_questions: list[str]
    evidence_ids: list[str]
    proposed_status: ElementStatus

    @model_validator(mode="after")
    def _validated_needs_evidence(self) -> Self:
        if self.proposed_status is ElementStatus.VALIDATED and not self.evidence_ids:
            raise ValueError("proposing 'validated' requires citing evidence ids")
        return self


class ScorecardRefinement(_LLMSchema):
    elements: list[ElementRefinement]
    summary: str = Field(min_length=1)

    @field_validator("elements")
    @classmethod
    def _unique(cls, elements: list[ElementRefinement]) -> list[ElementRefinement]:
        if len({e.element for e in elements}) != len(elements):
            raise ValueError("each element may be refined at most once")
        return elements


class OutboundTouch(_LLMSchema):
    step: int = Field(ge=1)
    channel: Channel
    day_offset: int = Field(ge=0)
    subject: str | None
    body: str = Field(min_length=1)
    cta: str = Field(min_length=1)

    @model_validator(mode="after")
    def _email_has_subject(self) -> Self:
        if self.channel is Channel.EMAIL and not self.subject:
            raise ValueError("an email touch needs a subject line")
        return self


class ObjectionHandle(_LLMSchema):
    objection: str = Field(min_length=1)
    response: str = Field(min_length=1)


class PersonaTarget(_LLMSchema):
    persona: Persona
    title_patterns: list[str]
    angle: str = Field(min_length=1)


class BriefNarrative(_LLMSchema):
    headline: str = Field(min_length=1, max_length=HEADLINE_MAX_CHARS)
    why_now: list[str]
    talk_track: str = Field(min_length=1)
    call_opener: str = Field(min_length=1)
    personas: list[PersonaTarget]
    touches: list[OutboundTouch] = Field(min_length=3, max_length=4)
    objections: list[ObjectionHandle]
    discovery_questions: list[str]

    @field_validator("touches")
    @classmethod
    def _sequenced(cls, touches: list[OutboundTouch]) -> list[OutboundTouch]:
        if [t.step for t in touches] != list(range(1, len(touches) + 1)):
            raise ValueError("touch steps must run 1, 2, 3, ... in order")
        offsets = [t.day_offset for t in touches]
        if offsets != sorted(offsets):
            raise ValueError("touch day offsets must not go backwards")
        return touches


# --------------------------------------------------------------------------- outputs


class SDROutboundBrief(_Contract):
    """The final artifact. Assembled deterministically; the LLM only writes `narrative`."""

    generated_at: UtcDatetime
    profile: StartupProfile
    value_props: AnthropicValueProps
    scorecard: MEDDPICCScorecard
    narrative: BriefNarrative
    evidence: list[Evidence] = Field(default_factory=list)
    data_source: DataSource
    disclaimer: str = DISCLAIMER

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        domains = {self.profile.domain, self.value_props.domain, self.scorecard.domain}
        if len(domains) != 1:
            raise ValueError(f"profile/value_props/scorecard domains differ: {sorted(domains)}")
        known = _unique_evidence_ids(self.evidence)
        _require_cited(
            [
                *(i for w in self.value_props.wedges for i in w.trigger_evidence_ids),
                *(i for e in self.scorecard.elements for i in e.evidence_ids),
            ],
            known,
            "value props and scorecard",
        )
        return self


class LLMUsage(_Contract):
    input_tokens: NonNegativeInt = 0
    output_tokens: NonNegativeInt = 0
    cache_read_tokens: NonNegativeInt = 0
    cache_write_tokens: NonNegativeInt = 0
    est_cost_usd: NonNegativeFloat = 0.0

    def __add__(self, other: Self) -> Self:
        return type(self)(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            cache_write_tokens=self.cache_write_tokens + other.cache_write_tokens,
            est_cost_usd=self.est_cost_usd + other.est_cost_usd,
        )


class AnalysisResult(_Contract):
    """One target's outcome. A failed target keeps its errors instead of a brief."""

    company_name: str = Field(min_length=1)
    domain: Domain
    brief: SDROutboundBrief | None = None
    errors: list[str] = Field(default_factory=list)
    timings_ms: dict[str, NonNegativeInt] = Field(default_factory=dict)
    usage: LLMUsage | None = None

    @model_validator(mode="after")
    def _brief_or_errors(self) -> Self:
        if self.brief is None and not self.errors:
            raise ValueError("a result without a brief must record at least one error")
        if self.brief is not None and self.brief.profile.domain != self.domain:
            raise ValueError("brief is for a different domain")
        return self

    @property
    def ok(self) -> bool:
        return self.brief is not None


# --------------------------------------------------------------------------- targets file


class RowError(_Contract):
    """A targets-file row that could not become a StartupProfile. The batch carries on."""

    line: PositiveInt
    domain: str | None = None  # the raw value, which may itself be the problem
    message: str = Field(min_length=1)


class TargetBatch(_Contract):
    source: str
    profiles: list[StartupProfile] = Field(default_factory=list)
    errors: list[RowError] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @field_validator("profiles")
    @classmethod
    def _one_per_domain(cls, profiles: list[StartupProfile]) -> list[StartupProfile]:
        counts = Counter(p.domain for p in profiles)
        if repeated := sorted(d for d, n in counts.items() if n > 1):
            raise ValueError(f"each domain may appear once: {', '.join(repeated)}")
        return profiles
