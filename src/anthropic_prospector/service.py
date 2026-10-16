"""Composition root: where data collection, the qualification pipeline and the LLM meet.

The CLI talks to this module only. analyze() qualifies one account; analyze_batch()
qualifies a territory concurrently, with every target isolated: a failure becomes that
target's error and never stops the batch. A batch can checkpoint each finished account to
a JSONL file, so a rerun with resume=True picks up where an interrupted run stopped.

Two independent switches decide what is real:

* Data. DataMode.OFFLINE uses the mock layer and never touches the network. AUTO reads
  public sources and falls back to illustrative data for a target nothing could be read
  for. LIVE reads public sources only and fails such a target instead.
* LLM. Claude when ANTHROPIC_API_KEY is set (and the run is not offline), otherwise the
  zero-cost mock, which runs the same pipeline with rules-based text.
"""

import asyncio
import csv
import functools
import io
import re
import tempfile
import time
from collections.abc import AsyncIterator, Callable, Iterable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Final, Literal, TextIO

from pydantic import ValidationError

from anthropic_prospector.config import Settings
from anthropic_prospector.mock import fixture_profile, mock_signals
from anthropic_prospector.models import (
    AnalysisResult,
    DataSource,
    LLMUsage,
    Recommendation,
    SDROutboundBrief,
    StartupProfile,
    TargetBatch,
    TechStackSignals,
    Tier,
    normalize_domain,
)
from anthropic_prospector.pipeline import (
    AnthropicLLMClient,
    LLMClient,
    LLMError,
    MockLLMClient,
    run_pipeline,
    to_markdown,
)
from anthropic_prospector.pipeline.llm import PRICES
from anthropic_prospector.scrapers.collect import CollectionError, collect
from anthropic_prospector.scrapers.dns_intel import (
    DnsUnavailable,
    DohResolver,
    FallbackResolver,
    Resolver,
    SystemResolver,
)
from anthropic_prospector.scrapers.http import Fetcher, FetchError

DEFAULT_CONCURRENCY: Final = 4
CHECKPOINT_NAME: Final = "checkpoint.jsonl"
RANKED_NAME: Final = "ranked.csv"
RANKED_COLUMNS: Final = (
    "rank",
    "company_name",
    "domain",
    "hq_state",
    "in_territory",
    "recommendation",
    "tier",
    "meddpicc_total",
    "coverage_pct",
    "primary_wedge",
    "overall_fit",
    "data_source",
    "brief",
    "errors",
)
BriefFormat = Literal["md", "json"]
_SUFFIX_FORMATS: Final[dict[str, BriefFormat]] = {".md": "md", ".json": "json"}

# Most worth an SDR's time first. Tier measures qualification depth, which is mostly
# unknown before discovery, so wedge fit orders accounts within a recommendation.
_RECOMMENDATION_ORDER: Final = {
    Recommendation.PURSUE: 0,
    Recommendation.NURTURE: 1,
    Recommendation.ROUTE_TO_AE: 2,
    Recommendation.ROUTE_TO_OWNER: 3,
    Recommendation.DISQUALIFY: 4,
}
_TIER_ORDER: Final = {Tier.A: 0, Tier.B: 1, Tier.C: 2, Tier.D: 3}


class DataMode(StrEnum):
    OFFLINE = "offline"  # the mock layer only; nothing touches the network
    AUTO = "auto"  # public sources, falling back to illustrative data per target
    LIVE = "live"  # public sources only; a target that cannot be read fails


class TargetNotFound(LookupError):
    """A domain with no profile in the targets file or the bundled examples."""


@dataclass(frozen=True)
class RunPlan:
    """What a run will use, for the banner and `doctor`."""

    data_mode: DataMode
    llm_model: str | None  # None: the mock LLM

    @property
    def live_llm(self) -> bool:
        return self.llm_model is not None


@dataclass(frozen=True)
class BatchReport:
    results: list[AnalysisResult]  # one per input profile, in input order
    resumed: frozenset[str] = frozenset()  # domains whose results came from the checkpoint
    notes: list[str] = field(default_factory=list)  # e.g. unreadable checkpoint lines

    @property
    def usage(self) -> LLMUsage:
        """LLM usage of this run; resumed results were paid for by an earlier run."""
        total = LLMUsage()
        for result in self.results:
            if result.usage is not None and result.domain not in self.resumed:
                total += result.usage
        return total

    @property
    def failed(self) -> list[AnalysisResult]:
        return [result for result in self.results if not result.ok]


@dataclass(frozen=True)
class BatchOutputs:
    ranked_csv: Path
    briefs: dict[str, Path]  # domain -> exported brief


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool | None  # None: informational
    detail: str


# --- modes ------------------------------------------------------------------------------


def plan_run(settings: Settings, mode: DataMode) -> RunPlan:
    live_llm = mode is not DataMode.OFFLINE and settings.has_anthropic_key
    return RunPlan(mode, settings.anthropic_model if live_llm else None)


def make_llm(settings: Settings, mode: DataMode) -> LLMClient:
    if plan_run(settings, mode).live_llm:
        return AnthropicLLMClient.from_settings(settings)
    return MockLLMClient()


# --- targets ----------------------------------------------------------------------------


def resolve_target(
    target: str,
    *,
    batch: TargetBatch | None = None,
    company_name: str | None = None,
    hq_state: str | None = None,
) -> StartupProfile:
    """The profile for a domain or URL: from the targets file, else the bundled examples,
    else built from the name and state given on the command line.

    Raises ValueError for something that is not a domain, TargetNotFound when the domain is
    unknown and no state was given.
    """
    domain = normalize_domain(target)
    if batch is not None:
        for profile in batch.profiles:
            if profile.domain == domain:
                return profile
    example = fixture_profile(domain)
    if example is not None:
        return example.model_copy(update={"tech_stack": None})  # signals are read afresh
    if hq_state is None:
        raise TargetNotFound(
            f"{domain} is not in the targets file or the bundled examples. "
            "Pass --state (and optionally --name) to qualify it anyway."
        )
    return StartupProfile(
        company_name=company_name or _name_from_domain(domain), domain=domain, hq_state=hq_state
    )


def _name_from_domain(domain: str) -> str:
    return " ".join(word.capitalize() for word in re.split(r"[-_]", domain.split(".")[0]))


def filter_states(
    profiles: Iterable[StartupProfile], states: Iterable[str]
) -> list[StartupProfile]:
    wanted = {state.upper() for state in states}
    return [profile for profile in profiles if profile.hq_state in wanted]


# --- analysis ---------------------------------------------------------------------------


async def analyze(
    profile: StartupProfile,
    settings: Settings,
    *,
    mode: DataMode = DataMode.AUTO,
    llm: LLMClient | None = None,
    fetcher: Fetcher | None = None,
    resolver: Resolver | None = None,
    now: datetime | None = None,
) -> AnalysisResult:
    """Qualify one account. Never raises for a failed analysis: see AnalysisResult.errors."""
    report = await analyze_batch(
        [profile],
        settings,
        mode=mode,
        concurrency=1,
        llm=llm,
        fetcher=fetcher,
        resolver=resolver,
        now=now,
    )
    return report.results[0]


async def analyze_batch(
    profiles: Sequence[StartupProfile],
    settings: Settings,
    *,
    mode: DataMode = DataMode.AUTO,
    concurrency: int = DEFAULT_CONCURRENCY,
    checkpoint: Path | None = None,
    resume: bool = False,
    max_cost_usd: float | None = None,
    on_result: Callable[[AnalysisResult], None] | None = None,
    llm: LLMClient | None = None,
    fetcher: Fetcher | None = None,
    resolver: Resolver | None = None,
    now: datetime | None = None,
) -> BatchReport:
    """Qualify `profiles` concurrently, one result per profile, in input order.

    With `checkpoint`, every finished result is appended to that JSONL file as it lands.
    With `resume`, accounts that succeeded in the checkpoint are reused, not rerun; failed
    ones are retried. Without `resume` the checkpoint starts empty. Once `max_cost_usd` of
    estimated LLM spend is reached, accounts not yet started are skipped with an error.
    """
    if concurrency < 1:
        raise ValueError("concurrency must be at least 1")
    notes: list[str] = []
    succeeded: dict[str, AnalysisResult] = {}
    if checkpoint is not None and resume:
        previous, unreadable = load_checkpoint(checkpoint)
        succeeded = {domain: result for domain, result in previous.items() if result.ok}
        if unreadable:
            notes.append(f"Ignored {unreadable} unreadable line(s) in {checkpoint}.")
    results: list[AnalysisResult | None] = [succeeded.get(p.domain) for p in profiles]
    resumed = frozenset(r.domain for r in results if r is not None)
    if on_result is not None:
        for result in results:
            if result is not None:
                on_result(result)

    analyst = _Analyst(mode, llm or make_llm(settings, mode), now)
    async with _sources(settings, mode, fetcher, resolver) as (live_fetcher, live_resolver):
        analyst.attach(live_fetcher, live_resolver)
        with _CheckpointWriter(checkpoint, append=resume) as writer:
            semaphore = asyncio.Semaphore(concurrency)
            spent = 0.0

            async def work(index: int) -> None:
                nonlocal spent
                profile = profiles[index]
                async with semaphore:
                    if max_cost_usd is not None and spent >= max_cost_usd:
                        result = _failure(
                            profile, f"Skipped: the ${max_cost_usd:.2f} LLM budget is spent."
                        )
                    else:
                        result = await analyst.analyze(profile)
                        if result.usage is not None:
                            spent += result.usage.est_cost_usd
                writer.write(result)
                results[index] = result
                if on_result is not None:
                    on_result(result)

            await asyncio.gather(*(work(i) for i, r in enumerate(results) if r is None))

    return BatchReport([result for result in results if result is not None], resumed, notes)


class _Analyst:
    """Runs one account through collection and the pipeline, isolating its failures."""

    def __init__(self, mode: DataMode, llm: LLMClient, now: datetime | None) -> None:
        self._mode = mode
        self._llm = llm
        self._now = now or datetime.now(UTC)
        self._fetcher: Fetcher | None = None
        self._resolver: Resolver | None = None

    def attach(self, fetcher: Fetcher | None, resolver: Resolver | None) -> None:
        self._fetcher = fetcher
        self._resolver = resolver

    async def analyze(self, profile: StartupProfile) -> AnalysisResult:
        timings: dict[str, int] = {}
        started = time.perf_counter()
        try:
            signals = await self._signals(profile)
        except CollectionError as exc:
            return _failure(profile, f"Could not read any public source: {exc}")
        except Exception as exc:  # isolate: one account's failure never stops a batch
            return _failure(profile, f"Signal collection failed: {_describe(exc)}")
        timings["collect"] = _elapsed_ms(started)

        enriched = profile.model_copy(update={"tech_stack": signals})
        errors: list[str] = []
        started = time.perf_counter()
        try:
            brief, usage = await self._pipeline(enriched, self._llm)
        except LLMError as exc:
            # The deterministic core still qualifies the account; only Claude's text is lost.
            try:
                brief, fallback_usage = await self._pipeline(enriched, MockLLMClient())
            except Exception as inner:
                return _failure(profile, f"Qualification failed: {_describe(inner)}")
            usage = exc.usage + fallback_usage  # tokens spent before the failure still count
            errors.append(f"Claude call failed ({exc}); used the rules-based text instead.")
        except Exception as exc:
            return _failure(profile, f"Qualification failed: {_describe(exc)}")
        timings["pipeline"] = _elapsed_ms(started)
        return AnalysisResult(
            company_name=profile.company_name,
            domain=profile.domain,
            brief=brief,
            errors=errors,
            timings_ms=timings,
            usage=usage,
        )

    async def _signals(self, profile: StartupProfile) -> TechStackSignals:
        if self._fetcher is None:
            return mock_signals(profile, collected_at=self._now)
        return await collect(
            profile,
            fetcher=self._fetcher,
            resolver=self._resolver,
            fallback=functools.partial(mock_signals, collected_at=self._now),
            strict=self._mode is DataMode.LIVE,
            now=self._now,
        )

    async def _pipeline(
        self, profile: StartupProfile, llm: LLMClient
    ) -> tuple[SDROutboundBrief, LLMUsage]:
        # The LLM client blocks on HTTP; a worker thread keeps the batch's scrapers moving.
        return await asyncio.to_thread(run_pipeline, profile, llm, generated_at=self._now)


@asynccontextmanager
async def _sources(
    settings: Settings, mode: DataMode, fetcher: Fetcher | None, resolver: Resolver | None
) -> AsyncIterator[tuple[Fetcher | None, Resolver | None]]:
    """One HTTP client and one DNS resolver shared by the whole run (none when offline).

    Sharing the resolver means only the first target pays to discover blocked system DNS.
    """
    if mode is DataMode.OFFLINE:
        yield None, None
    elif fetcher is not None:
        yield fetcher, resolver or FallbackResolver(SystemResolver(), DohResolver(fetcher))
    else:
        async with Fetcher(settings) as owned:
            yield owned, resolver or FallbackResolver(SystemResolver(), DohResolver(owned))


def _failure(profile: StartupProfile, message: str) -> AnalysisResult:
    return AnalysisResult(
        company_name=profile.company_name, domain=profile.domain, errors=[message]
    )


def _describe(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__


def _elapsed_ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)


# --- checkpoints ------------------------------------------------------------------------


def load_checkpoint(path: Path) -> tuple[dict[str, AnalysisResult], int]:
    """The latest result per domain, and how many lines could not be read (an interrupted
    run can leave its last line cut short)."""
    latest: dict[str, AnalysisResult] = {}
    unreadable = 0
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return latest, 0
    for line in lines:
        if not line.strip():
            continue
        try:
            result = AnalysisResult.model_validate_json(line)
        except ValidationError:
            unreadable += 1
            continue
        latest[result.domain] = result
    return latest, unreadable


class _CheckpointWriter:
    """Appends one JSON line per finished account and flushes it, so a crash loses at
    most the account in flight."""

    def __init__(self, path: Path | None, *, append: bool) -> None:
        self._path = path
        self._append = append
        self._file: TextIO | None = None

    def __enter__(self) -> "_CheckpointWriter":
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._file = self._path.open("a" if self._append else "w", encoding="utf-8")
        return self

    def __exit__(self, *exc_info: object) -> None:
        if self._file is not None:
            self._file.close()

    def write(self, result: AnalysisResult) -> None:
        if self._file is not None:
            self._file.write(result.model_dump_json() + "\n")
            self._file.flush()


# --- ranking and outputs ----------------------------------------------------------------


def rank(results: Iterable[AnalysisResult]) -> list[AnalysisResult]:
    """Most worth working first: by recommendation, then wedge fit, then MEDDPICC total.
    Accounts that could not be analyzed sort last."""

    def key(result: AnalysisResult) -> tuple[int, int, int, int, str]:
        if result.brief is None:
            return (1, 0, 0, 0, result.company_name.lower())
        scorecard = result.brief.scorecard
        return (
            0,
            _RECOMMENDATION_ORDER[scorecard.recommendation],
            -result.brief.value_props.overall_fit,
            -scorecard.total_score,
            result.company_name.lower(),
        )

    return sorted(results, key=key)


def shortlist(
    ranked: Sequence[AnalysisResult], *, min_tier: Tier | None = None, top: int | None = None
) -> list[AnalysisResult]:
    """The analyzed accounts at `min_tier` or better, at most `top` of them."""
    picked = [
        result
        for result in ranked
        if result.brief is not None
        and (min_tier is None or _TIER_ORDER[result.brief.scorecard.tier] <= _TIER_ORDER[min_tier])
    ]
    return picked if top is None else picked[:top]


def batch_data_source(results: Iterable[AnalysisResult]) -> DataSource | None:
    """LIVE or MOCK when every analyzed account agrees, HYBRID when they mix."""
    sources = {result.brief.data_source for result in results if result.brief is not None}
    if not sources:
        return None
    return sources.pop() if len(sources) == 1 else DataSource.HYBRID


def brief_filename(domain: str, fmt: BriefFormat = "md") -> str:
    return f"{re.sub(r'[^a-z0-9]+', '-', domain.lower()).strip('-')}.{fmt}"


def render_brief(brief: SDROutboundBrief, fmt: BriefFormat = "md") -> str:
    return to_markdown(brief) if fmt == "md" else brief.model_dump_json(indent=2) + "\n"


def export_brief(
    brief: SDROutboundBrief,
    path: Path,
    *,
    fmt: BriefFormat | None = None,
    force: bool = False,
) -> Path:
    """Write the brief where brief_target() says and return the file written.

    Raises FileExistsError rather than overwrite unless `force`.
    """
    target, fmt = brief_target(path, brief.profile.domain, fmt)
    if target.exists() and not force:
        raise FileExistsError(f"{target} already exists; pass --force to overwrite it.")
    _write_atomic(target, render_brief(brief, fmt))
    return target


def brief_target(
    path: Path, domain: str, fmt: BriefFormat | None = None
) -> tuple[Path, BriefFormat]:
    """The file and format an export to `path` uses.

    A path ending in .md or .json is the file itself, and its suffix sets the format; any
    other path is a directory to write `<domain>.<fmt>` into (Markdown by default). Raises
    ValueError when `fmt` contradicts the suffix.
    """
    suffix_fmt = _SUFFIX_FORMATS.get(path.suffix.lower())
    if suffix_fmt is not None:
        if fmt is not None and fmt != suffix_fmt:
            raise ValueError(f"{path.name} is a .{suffix_fmt} file but the format is {fmt}.")
        return path, suffix_fmt
    resolved: BriefFormat = fmt or "md"
    return path / brief_filename(domain, resolved), resolved


def write_batch_outputs(
    ranked: Sequence[AnalysisResult],
    selected: Sequence[AnalysisResult],
    out_dir: Path,
    *,
    fmt: BriefFormat = "md",
) -> BatchOutputs:
    """`ranked.csv` with every account, and a brief for each selected one. A batch output
    directory is regenerated on every run, so existing files are replaced."""
    briefs_dir = out_dir / "briefs"
    briefs: dict[str, Path] = {}
    for result in selected:
        if result.brief is not None:
            target = briefs_dir / brief_filename(result.domain, fmt)
            _write_atomic(target, render_brief(result.brief, fmt))
            briefs[result.domain] = target
    ranked_csv = out_dir / RANKED_NAME
    _write_atomic(ranked_csv, _ranked_csv(ranked, briefs, out_dir))
    return BatchOutputs(ranked_csv, briefs)


def _ranked_csv(ranked: Sequence[AnalysisResult], briefs: Mapping[str, Path], out_dir: Path) -> str:
    rows: list[dict[str, object]] = []
    for position, result in enumerate(ranked, start=1):
        row: dict[str, object] = {
            "rank": position,
            "company_name": result.company_name,
            "domain": result.domain,
            "errors": " | ".join(result.errors),
        }
        if result.brief is not None:
            brief = result.brief
            scorecard = brief.scorecard
            brief_path = briefs.get(result.domain)
            row |= {
                "hq_state": brief.profile.hq_state,
                "in_territory": brief.profile.in_territory,
                "recommendation": scorecard.recommendation.value,
                "tier": scorecard.tier.value,
                "meddpicc_total": scorecard.total_score,
                "coverage_pct": scorecard.coverage_pct,
                "primary_wedge": (brief.value_props.primary_wedge or ""),
                "overall_fit": brief.value_props.overall_fit,
                "data_source": brief.data_source.value,
                "brief": brief_path.relative_to(out_dir).as_posix() if brief_path else "",
            }
        rows.append(row)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=RANKED_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as tmp:
        tmp.write(text)
    Path(tmp.name).replace(path)


# --- doctor -----------------------------------------------------------------------------


def diagnose(settings: Settings) -> list[Check]:
    """Configuration checks that need no network."""
    plan = plan_run(settings, DataMode.AUTO)
    model = settings.anthropic_model
    checks = [
        Check(
            "Anthropic API key",
            True if plan.live_llm else None,
            f"set: briefs are written by {model}"
            if plan.live_llm
            else "not set: the zero-cost mock LLM writes rules-based briefs",
        ),
        Check(
            "Model",
            True if model in PRICES else None,
            model if model in PRICES else f"{model} (no price on file: costs show as $0.00)",
        ),
        Check(
            "Data",
            None,
            "public sources, with illustrative data for targets nothing could be read for "
            "(--offline: illustrative only; --live: public only)",
        ),
        _cache_check(settings.cache_dir),
    ]
    return checks


def _cache_check(cache_dir: Path) -> Check:
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=cache_dir):
            pass
    except OSError as exc:
        return Check("Cache", False, f"{cache_dir} is not writable ({exc.strerror})")
    return Check("Cache", True, str(cache_dir))


async def diagnose_network(
    settings: Settings, *, fetcher: Fetcher | None = None, resolver: Resolver | None = None
) -> list[Check]:
    """Probe what live mode needs: system DNS, DNS over HTTPS, and a public job board."""
    checks: list[Check] = []
    async with _sources(settings, DataMode.LIVE, fetcher, None) as (live_fetcher, _):
        assert live_fetcher is not None
        system = resolver or SystemResolver()
        try:
            await system.resolve("boards-api.greenhouse.io", "A")
            checks.append(Check("System DNS", True, "resolves public names"))
        except DnsUnavailable:
            checks.append(
                Check("System DNS", False, "blocked or unreachable; DNS over HTTPS is used")
            )
        try:
            answer = await DohResolver(live_fetcher).resolve("boards-api.greenhouse.io", "A")
            checks.append(Check("DNS over HTTPS", bool(answer), "dns.google answers"))
        except DnsUnavailable:
            checks.append(Check("DNS over HTTPS", False, "dns.google is unreachable"))
        try:
            page = await live_fetcher.get("https://api.lever.co/v0/postings/leverdemo?mode=json")
            checks.append(
                Check("Public job boards", page.ok, f"api.lever.co answered HTTP {page.status}")
            )
        except FetchError as exc:
            checks.append(Check("Public job boards", False, f"unreachable ({exc})"))
    return checks
