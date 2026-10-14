"""Live signal collection: ATS board, company web pages and DNS, merged into TechStackSignals.

The three sources are read independently and fail independently. Every observation becomes
an Evidence record that the signals cite. Sightings of one signal in several sources combine
by noisy-OR, 1 - Π(1 - cᵢ), capped below certainty: public text suggests usage, never
proves it. A sentence repeated across pages or postings (navigation, boilerplate) counts
once, and only engineering, data and AI postings are read for signals: a sales role that
mentions SOC 2 says nothing about the product.

A source that answers with nothing (no board, no AI mentions) is a real observation, and
the result stays live. Only when no source can be reached at all (offline, egress blocked)
does the target fall back to the injected `fallback`, with a warning; with strict=True it
raises CollectionError instead. Reserved example domains are never fetched.
"""

import asyncio
import math
import re
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final, TypeVar

from anthropic_prospector.models import (
    MAX_AI_ROLES,
    ATSPlatform,
    CloudProvider,
    CloudSignal,
    CompetitorKind,
    CompetitorSignal,
    DataSource,
    Evidence,
    EvidenceKind,
    JobPosting,
    SignalKeyword,
    StartupProfile,
    TechStackSignals,
)
from anthropic_prospector.scrapers.ats import Board, find_board
from anthropic_prospector.scrapers.dns_intel import (
    DnsReport,
    DohResolver,
    FallbackResolver,
    Resolver,
    SystemResolver,
    inspect_domain,
)
from anthropic_prospector.scrapers.http import Fetcher
from anthropic_prospector.scrapers.keywords import (
    Mention,
    find_clouds,
    find_competitors,
    find_keywords,
    is_ai_role,
)
from anthropic_prospector.scrapers.web_intel import SiteReport, read_site

RESERVED_SUFFIXES: Final = (".example", ".invalid", ".localhost", ".test")  # RFC 2606/6761
RESERVED_DOMAINS: Final = frozenset({"example.com", "example.net", "example.org"})
JOB_POST_WEIGHT: Final = 0.6
TRUST_PAGE_WEIGHT: Final = 0.8  # security, trust and subprocessor pages name vendors outright
WEB_PAGE_WEIGHT: Final = 0.5
MAX_CONFIDENCE: Final = 0.95
PRIMARY_CLOUD_MIN: Final = 0.5  # each of two providers above this makes the account multi-cloud
MAX_EVIDENCE: Final = 30
MAX_CITES: Final = 3  # evidence ids kept per signal

_TECH_TITLE: Final = re.compile(
    r"\b(engineer(ing)?|developer|scientist|architect|research|data|ml|ai|platform|"
    r"infrastructure|sre|devops|security)\b",
    re.IGNORECASE,
)

_K = TypeVar("_K")
Fallback = Callable[[StartupProfile], TechStackSignals]


class CollectionError(Exception):
    """No live source could be read, and falling back to illustrative data was not allowed."""

    def __init__(self, domain: str, reasons: Sequence[str]) -> None:
        super().__init__(f"{domain}: {' '.join(reasons)}")
        self.domain = domain
        self.reasons = list(reasons)


def is_reserved(domain: str) -> bool:
    """Reserved for documentation and testing (RFC 2606, RFC 6761): never on the network."""
    return domain.endswith(RESERVED_SUFFIXES) or any(
        domain == name or domain.endswith(f".{name}") for name in RESERVED_DOMAINS
    )


async def collect(
    profile: StartupProfile,
    *,
    fetcher: Fetcher,
    resolver: Resolver | None = None,
    fallback: Fallback | None = None,
    strict: bool = False,
    now: datetime | None = None,
) -> TechStackSignals:
    """Live signals for one company. See the module docstring for when it falls back.

    Share one `resolver` across a batch: FallbackResolver remembers that system DNS is
    blocked, so only the first target pays for finding out.
    """
    observed_at = now or datetime.now(UTC)
    if is_reserved(profile.domain):
        note = f"{profile.domain} is a reserved example domain, so nothing was fetched."
        return _fall_back(profile, note, [], fallback, strict)

    resolver = resolver or FallbackResolver(SystemResolver(), DohResolver(fetcher))
    site, dns_report = await asyncio.gather(
        read_site(fetcher, profile), inspect_domain(profile.domain, resolver)
    )
    lookup = await find_board(fetcher, profile, site.board_refs)
    warnings = [*site.warnings, *dns_report.warnings, *lookup.warnings]
    if not (site.reached or dns_report.reached or lookup.reached):
        note = f"No live source could be reached for {profile.domain}."
        return _fall_back(profile, note, warnings, fallback, strict)
    return _merge(profile, site, dns_report, lookup.board, warnings, observed_at)


def _fall_back(
    profile: StartupProfile,
    note: str,
    reasons: list[str],
    fallback: Fallback | None,
    strict: bool,
) -> TechStackSignals:
    if strict or fallback is None:
        raise CollectionError(profile.domain, [note, *reasons])
    signals = fallback(profile)
    notes = [*signals.warnings, f"{note} Showing illustrative data instead.", *reasons]
    return signals.model_copy(
        update={"data_source": DataSource.MOCK, "warnings": list(dict.fromkeys(notes))}
    )


@dataclass
class _Sightings:
    """Where one signal was seen: a weight per source, and what to cite for it."""

    weights: list[float] = field(default_factory=list)
    cites: list[tuple[EvidenceKind, str | None, str]] = field(default_factory=list)
    ids: list[str] = field(default_factory=list)
    sentences: set[str] = field(default_factory=set)

    def add(self, kind: EvidenceKind, url: str, weight: float, found: list[Mention]) -> None:
        fresh = [m for m in found if m.sentence.lower() not in self.sentences]
        if not fresh:
            return  # boilerplate already counted from another page or posting
        self.sentences.update(m.sentence.lower() for m in found)
        self.weights.append(weight)
        self.cites.append((kind, url, fresh[0].sentence))

    @property
    def confidence(self) -> float:
        miss = math.prod(1.0 - weight for weight in self.weights)
        return round(min(1.0 - miss, MAX_CONFIDENCE), 2)


class _Ledger:
    """Numbers evidence E1, E2, ... in citation order, once per distinct observation."""

    def __init__(self, observed_at: datetime) -> None:
        self.evidence: list[Evidence] = []
        self._ids: dict[tuple[EvidenceKind, str | None, str], str] = {}
        self._observed_at = observed_at

    def cite(self, kind: EvidenceKind, url: str | None, snippet: str) -> str | None:
        key = (kind, url, snippet)
        if key not in self._ids:
            if len(self.evidence) >= MAX_EVIDENCE:
                return None
            evidence_id = f"E{len(self.evidence) + 1}"
            self.evidence.append(
                Evidence(
                    id=evidence_id,
                    kind=kind,
                    source_url=url,
                    snippet=snippet,
                    observed_at=self._observed_at,
                )
            )
            self._ids[key] = evidence_id
        return self._ids[key]


def _merge(
    profile: StartupProfile,
    site: SiteReport,
    dns_report: DnsReport,
    board: Board | None,
    warnings: list[str],
    observed_at: datetime,
) -> TechStackSignals:
    postings = board.postings if board else []
    ai_postings = [p for p in postings if is_ai_role(p.title, p.description_text)]

    keywords: defaultdict[SignalKeyword, _Sightings] = defaultdict(_Sightings)
    competitors: defaultdict[CompetitorKind, _Sightings] = defaultdict(_Sightings)
    clouds: defaultdict[CloudProvider, _Sightings] = defaultdict(_Sightings)
    sources: list[tuple[EvidenceKind, str, str, float]] = [
        ("job_posting", p.url, f"{p.title}\n{p.description_text}", JOB_POST_WEIGHT)
        for p in postings
        if _is_technical(p)
    ]
    sources += [
        ("web", page.url, page.text, TRUST_PAGE_WEIGHT if page.trust else WEB_PAGE_WEIGHT)
        for page in site.pages
    ]
    for kind, url, text, weight in sources:
        for keyword, found in find_keywords(text).items():
            keywords[keyword].add(kind, url, weight, found)
        for competitor, found in find_competitors(text).items():
            competitors[competitor].add(kind, url, weight, found)
        for provider, found_cloud in find_clouds(text).items():
            clouds[provider].add(kind, url, weight, found_cloud)
    for hint in dns_report.hints:
        clouds[hint.provider].weights.append(hint.confidence)
        clouds[hint.provider].cites.append(("dns", None, hint.snippet))
    if dns_report.fronted_by and not dns_report.hints:
        warnings.append(
            f"{profile.domain} is served through {' and '.join(dns_report.fronted_by)}, "
            "which hides the hosting cloud from DNS."
        )

    # Every signal gets its first citation before any gets a second, so the cap on
    # evidence never leaves a signal uncited.
    ledger = _Ledger(observed_at)
    groups: list[Iterable[_Sightings]] = [
        competitors.values(),
        clouds.values(),
        keywords.values(),
    ]
    for rank in range(MAX_CITES):
        for group in groups:
            for seen in group:
                if rank < len(seen.cites) and (cited := ledger.cite(*seen.cites[rank])):
                    seen.ids.append(cited)

    cloud = [
        CloudSignal(provider=provider, confidence=seen.confidence, evidence_ids=seen.ids)
        for provider, seen in _ranked(clouds)
    ]
    strong = [signal.provider for signal in cloud if signal.confidence >= PRIMARY_CLOUD_MIN]
    primary = (
        CloudProvider.MULTI if len(strong) > 1 else strong[0] if strong else CloudProvider.UNKNOWN
    )
    return TechStackSignals(
        domain=profile.domain,
        ats=board.ref.platform if board else ATSPlatform.UNKNOWN,
        ats_board_token=board.ref.token if board else None,
        total_open_roles=board.total_roles if board else 0,
        ai_role_count=len(ai_postings),
        ai_roles=ai_postings[:MAX_AI_ROLES],
        cloud=cloud,
        primary_cloud=primary,
        competitors=[
            CompetitorSignal(kind=kind, confidence=seen.confidence, evidence_ids=seen.ids)
            for kind, seen in _ranked(competitors)
        ],
        keyword_hits={keyword: len(seen.weights) for keyword, seen in keywords.items()},
        keyword_evidence={keyword: seen.ids for keyword, seen in keywords.items() if seen.ids},
        evidence=ledger.evidence,
        data_source=DataSource.LIVE,
        collected_at=observed_at,
        warnings=list(dict.fromkeys(warnings)),
    )


def _is_technical(posting: JobPosting) -> bool:
    return bool(_TECH_TITLE.search(posting.title)) or is_ai_role(
        posting.title, posting.description_text
    )


def _ranked(found: Mapping[_K, _Sightings]) -> list[tuple[_K, _Sightings]]:
    """Cited signals, strongest first; ties keep first-seen order."""
    cited = [(key, seen) for key, seen in found.items() if seen.ids]
    return sorted(cited, key=lambda item: -item[1].confidence)
