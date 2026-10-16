"""Command-line interface.

Thin by design: commands parse input, call the service layer, and hand results to the
renderer. No business logic lives here.

Reports go to stdout; progress, notes and errors go to stderr, so stdout stays clean for
pipes. Exit codes: 0 success, 1 some accounts could not be analyzed (or a doctor check
failed), 2 usage or configuration error.
"""

import asyncio
import platform
import sys
from collections import Counter
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Final, NoReturn

import typer
from pydantic import ValidationError

from anthropic_prospector import __version__
from anthropic_prospector.config import Settings
from anthropic_prospector.models import AnalysisResult, StartupProfile, Tier, normalize_state
from anthropic_prospector.render import (
    BatchProgress,
    account_view,
    banner,
    batch_view,
    doctor_view,
    failures_view,
    make_console,
    scorecard_view,
    usage_view,
    working,
)
from anthropic_prospector.service import (
    CHECKPOINT_NAME,
    DEFAULT_CONCURRENCY,
    BriefFormat,
    DataMode,
    TargetNotFound,
    analyze,
    analyze_batch,
    batch_data_source,
    brief_target,
    diagnose,
    diagnose_network,
    export_brief,
    filter_states,
    make_llm,
    plan_run,
    rank,
    resolve_target,
    shortlist,
    write_batch_outputs,
)
from anthropic_prospector.targets import TargetFileError, load_targets

EXIT_PARTIAL: Final = 1
EXIT_USAGE: Final = 2

app = typer.Typer(
    name="prospector",
    help="Signal-based MEDDPICC qualification engine for West Coast B2B startups.",
    no_args_is_help=True,
    add_completion=False,
)


class BriefFormatChoice(StrEnum):
    MD = "md"
    JSON = "json"

    def as_format(self) -> BriefFormat:
        return "json" if self is BriefFormatChoice.JSON else "md"


Target = Annotated[
    str, typer.Argument(metavar="DOMAIN", help="Company domain or URL, e.g. lexiconlegal.example.")
]
Offline = Annotated[
    bool,
    typer.Option("--offline", help="Illustrative data and the mock LLM: no network, no cost."),
]
Live = Annotated[
    bool,
    typer.Option(
        "--live", help="Public sources only: fail an account rather than use illustrative data."
    ),
]
TargetsFile = Annotated[
    Path | None,
    typer.Option("--targets", metavar="CSV", help="Look the domain up in this targets file."),
]
Name = Annotated[str | None, typer.Option(help="Company name, for a domain not in any file.")]
State = Annotated[
    str | None, typer.Option(help="HQ state, e.g. CA; required for a domain not in any file.")
]
NoColor = Annotated[
    bool, typer.Option("--no-color", help="No colour in the output (NO_COLOR also works).")
]


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"anthropic-prospector {__version__}")
        raise typer.Exit


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show the version and exit.",
        ),
    ] = False,
) -> None:
    """Signal-based MEDDPICC qualification engine for West Coast B2B startups."""


@app.command()
def run(
    target: Target,
    offline: Offline = False,
    live: Live = False,
    targets: TargetsFile = None,
    name: Name = None,
    state: State = None,
    as_json: Annotated[
        bool, typer.Option("--json", help="Print the whole analysis as JSON instead.")
    ] = False,
    no_color: NoColor = False,
) -> None:
    """Analyze one account end to end: signals, wedges, MEDDPICC and the outbound brief."""
    settings, mode = _setup(offline, live)
    profile = _profile(target, targets, name, state)
    result = _analyze(profile, settings, mode, no_color)
    if as_json:
        typer.echo(result.model_dump_json(indent=2))
    else:
        out = make_console(no_color=no_color)
        out.print(_banner(settings, mode, [result]))
        out.print(account_view(result, out))
    if not result.ok:
        raise typer.Exit(EXIT_PARTIAL)


@app.command()
def qualify(
    target: Target,
    offline: Offline = False,
    live: Live = False,
    targets: TargetsFile = None,
    name: Name = None,
    state: State = None,
    export: Annotated[
        Path | None,
        typer.Option(
            "--export-brief",
            metavar="PATH",
            help="Write the outbound brief to a .md or .json file, or into a directory.",
        ),
    ] = None,
    fmt: Annotated[
        BriefFormatChoice | None,
        typer.Option("--format", help="Brief format for a directory export [default: md]."),
    ] = None,
    force: Annotated[bool, typer.Option("--force", help="Overwrite an existing brief.")] = False,
    no_color: NoColor = False,
) -> None:
    """Score one account on MEDDPICC and, optionally, export its outbound brief."""
    settings, mode = _setup(offline, live)
    profile = _profile(target, targets, name, state)
    brief_format = fmt.as_format() if fmt is not None else None
    if export is not None:  # fail before the analysis, which may cost money
        try:
            destination, _ = brief_target(export, profile.domain, brief_format)
        except ValueError as exc:
            _fail(str(exc))
        if destination.exists() and not force:
            _fail(f"{destination} already exists; pass --force to overwrite it.")
    result = _analyze(profile, settings, mode, no_color)
    out = make_console(no_color=no_color)
    out.print(_banner(settings, mode, [result]))
    out.print(scorecard_view(result, out))
    if export is not None and result.brief is not None:
        try:
            written = export_brief(result.brief, export, fmt=brief_format, force=force)
        except (OSError, ValueError) as exc:
            _fail(f"Could not write the brief: {exc}")
        out.print(f"Brief written to {written}", markup=False)
    if not result.ok:
        raise typer.Exit(EXIT_PARTIAL)


@app.command("territory-batch")
def territory_batch(
    csv_path: Annotated[
        Path, typer.Argument(metavar="CSV", help="Targets file; see targets.csv for the columns.")
    ],
    states: Annotated[
        str | None,
        typer.Option(help="Only these HQ states, comma-separated, e.g. CA,WA,OR,AZ."),
    ] = None,
    top: Annotated[
        int | None, typer.Option(min=1, help="Show and export only the N best accounts.")
    ] = None,
    min_tier: Annotated[
        Tier | None,
        typer.Option(
            "--min-tier",
            case_sensitive=False,
            help="Show and export only accounts at this MEDDPICC tier or better.",
        ),
    ] = None,
    out_dir: Annotated[
        Path, typer.Option("--out-dir", help="Where ranked.csv, briefs/ and the checkpoint go.")
    ] = Path("prospector-out"),
    concurrency: Annotated[
        int, typer.Option(min=1, max=16, help="Accounts analyzed at the same time.")
    ] = DEFAULT_CONCURRENCY,
    resume: Annotated[
        bool, typer.Option("--resume", help="Reuse accounts already finished in the checkpoint.")
    ] = False,
    max_cost: Annotated[
        float | None,
        typer.Option(
            "--max-cost",
            min=0,
            metavar="USD",
            help="Start no new account once estimated LLM spend reaches this.",
        ),
    ] = None,
    fmt: Annotated[
        BriefFormatChoice, typer.Option("--format", help="Format of the exported briefs.")
    ] = BriefFormatChoice.MD,
    offline: Offline = False,
    live: Live = False,
    no_color: NoColor = False,
) -> None:
    """Qualify a territory from a CSV: rank every account and export the best briefs."""
    settings, mode = _setup(offline, live)
    try:
        batch = load_targets(csv_path)
    except TargetFileError as exc:
        _fail(str(exc))
    profiles = batch.profiles
    if states is not None:
        profiles = filter_states(profiles, _parse_states(states))

    out = make_console(no_color=no_color)
    err = make_console(stderr=True, no_color=no_color)
    llm = make_llm(settings, mode)
    with BatchProgress(err, total=len(profiles)) as progress:
        report = asyncio.run(
            analyze_batch(
                profiles,
                settings,
                mode=mode,
                concurrency=concurrency,
                checkpoint=out_dir / CHECKPOINT_NAME,
                resume=resume,
                max_cost_usd=max_cost,
                on_result=progress.advance,
                llm=llm,
            )
        )
    ranked = rank(report.results)
    selected = shortlist(ranked, min_tier=min_tier, top=top)
    try:
        outputs = write_batch_outputs(ranked, selected, out_dir, fmt=fmt.as_format())
    except OSError as exc:
        _fail(f"Could not write to {out_dir}: {exc}")

    position = {result.domain: rank_ for rank_, result in enumerate(ranked, start=1)}
    out.print(_banner(settings, mode, report.results))
    out.print(batch_view([(position[r.domain], r) for r in selected], out, total=len(ranked)))
    failures = failures_view(batch.errors, report.failed)
    if failures is not None:
        out.print(failures)
    data_counts = Counter(r.brief.data_source for r in report.results if r.brief is not None)
    out.print(
        usage_view(
            report.usage,
            llm_model=plan_run(settings, mode).llm_model,
            data_counts=data_counts,
            resumed=len(report.resumed),
        )
    )
    out.print(
        f"Wrote {outputs.ranked_csv} and {len(outputs.briefs)} brief(s) to {out_dir / 'briefs'}",
        markup=False,
    )
    for note in (*batch.warnings, *report.notes):
        err.print(note, markup=False, style="yellow")
    if batch.errors or report.failed:
        raise typer.Exit(EXIT_PARTIAL)


@app.command()
def doctor(
    network: Annotated[
        bool,
        typer.Option("--network", help="Also probe DNS, DNS over HTTPS and a public job board."),
    ] = False,
    no_color: NoColor = False,
) -> None:
    """Show which keys are set, what each mode will use, and what is reachable."""
    settings = _settings()
    python = f"Python {platform.python_version()} ({sys.platform})"
    checks: list[tuple[str, bool | None, str]] = [
        ("Version", None, f"anthropic-prospector {__version__} on {python}")
    ]
    found = diagnose(settings)
    if network:
        found += asyncio.run(diagnose_network(settings))
    checks += [(check.name, check.ok, check.detail) for check in found]
    out = make_console(no_color=no_color)
    out.print(doctor_view(checks, out))
    if any(ok is False for _, ok, _ in checks):
        raise typer.Exit(EXIT_PARTIAL)


def _setup(offline: bool, live: bool) -> tuple[Settings, DataMode]:
    if offline and live:
        _fail("--offline and --live cannot be used together.")
    mode = DataMode.OFFLINE if offline else DataMode.LIVE if live else DataMode.AUTO
    return _settings(), mode


def _settings() -> Settings:
    try:
        return Settings()
    except ValidationError as exc:
        # Locations and messages only: an echoed input could be an API key.
        problems = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        )
        _fail(f"Invalid configuration: {problems}")


def _profile(
    target: str, targets: Path | None, name: str | None, state: str | None
) -> StartupProfile:
    batch = None
    if targets is not None:
        try:
            batch = load_targets(targets)
        except TargetFileError as exc:
            _fail(str(exc))
    try:
        return resolve_target(target, batch=batch, company_name=name, hq_state=state)
    except TargetNotFound as exc:
        _fail(str(exc))
    except ValidationError as exc:
        _fail(f"Invalid account details: {exc.errors()[0]['msg']}")
    except ValueError as exc:
        _fail(f"{target!r} is not a domain: {exc}")


def _parse_states(states: str) -> list[str]:
    try:
        return [normalize_state(state) for state in states.split(",") if state.strip()]
    except ValueError as exc:
        _fail(f"--states: {exc}")


def _analyze(
    profile: StartupProfile, settings: Settings, mode: DataMode, no_color: bool
) -> AnalysisResult:
    err = make_console(stderr=True, no_color=no_color)
    with working(err, f"Qualifying {profile.domain}"):
        return asyncio.run(analyze(profile, settings, mode=mode))


def _banner(settings: Settings, mode: DataMode, results: list[AnalysisResult]) -> object:
    return banner(
        data=batch_data_source(results),
        llm_model=plan_run(settings, mode).llm_model,
        mode=mode.value,
    )


def _fail(message: str) -> NoReturn:
    make_console(stderr=True).print(f"Error: {message}", markup=False, style="red")
    raise typer.Exit(EXIT_USAGE)
