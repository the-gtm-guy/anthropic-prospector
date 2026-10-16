"""Terminal output with Rich, the only module that imports it.

Every view adapts to the terminal: wide (110+ columns) puts panels side by side and shows
every column, medium (80+) drops the least important column, and narrow stacks everything.
Health reads without colour: each state has a glyph and a word as well, and the glyphs
fall back to ASCII on terminals that cannot print Unicode.

Scraped text is never parsed as markup. Dynamic values go into Text objects, so a job post
containing "[bold]" prints exactly that.
"""

from collections.abc import Mapping, Sequence
from types import TracebackType
from typing import Final, Self

from rich import box
from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.status import Status
from rich.table import Table
from rich.text import Text

from anthropic_prospector.models import (
    AnalysisResult,
    ATSPlatform,
    CloudProvider,
    CompetitorKind,
    DataSource,
    ElementScore,
    ElementStatus,
    Evidence,
    FundingStage,
    Health,
    LLMUsage,
    MEDDPICCScorecard,
    Recommendation,
    RowError,
    SDROutboundBrief,
    StartupProfile,
    TechStackSignals,
    Tier,
)

WIDE: Final = 110
MEDIUM: Final = 80

# glyph, ASCII glyph, word, colour
_HEALTH: Final = {
    Health.GREEN: ("✓", "+", "strong", "green"),
    Health.YELLOW: ("◐", "~", "partial", "yellow"),
    Health.RED: ("✗", "x", "weak", "red"),
    Health.GREY: ("○", "?", "unknown", "bright_black"),
}
_RECOMMENDATIONS: Final = {
    Recommendation.PURSUE: ("PURSUE", "bold green"),
    Recommendation.NURTURE: ("NURTURE", "yellow"),
    Recommendation.ROUTE_TO_AE: ("ROUTE TO AE", "cyan"),
    Recommendation.ROUTE_TO_OWNER: ("ROUTE TO OWNER", "blue"),
    Recommendation.DISQUALIFY: ("DISQUALIFY", "red"),
}
_TIER_STYLES: Final = {Tier.A: "bold green", Tier.B: "green", Tier.C: "yellow", Tier.D: "red"}
_DATA: Final = {
    DataSource.LIVE: ("LIVE", "bold green", "public sources"),
    DataSource.MOCK: ("MOCK", "bold yellow", "illustrative data"),
    DataSource.HYBRID: ("HYBRID", "bold yellow", "live + illustrative"),
}
_SEP: Final = " · "
# Compact names for cards and tables; the pipeline words its own for prose.
_CLOUDS: Final = {
    CloudProvider.AWS: "AWS",
    CloudProvider.GCP: "Google Cloud",
    CloudProvider.AZURE: "Azure",
    CloudProvider.MULTI: "multi-cloud",
    CloudProvider.UNKNOWN: "unknown",
}
_COMPETITORS: Final = {
    CompetitorKind.OPENAI: "OpenAI",
    CompetitorKind.AZURE_OPENAI: "Azure OpenAI",
    CompetitorKind.LANGCHAIN: "LangChain",
    CompetitorKind.VLLM: "vLLM",
    CompetitorKind.OTHER_LLM: "other LLMs",
    CompetitorKind.ANTHROPIC_EXISTING: "Claude (already)",
}
_ATS: Final = {
    ATSPlatform.GREENHOUSE: "Greenhouse",
    ATSPlatform.LEVER: "Lever",
    ATSPlatform.ASHBY: "Ashby",
    ATSPlatform.UNKNOWN: "no public board found",
}
_STAGES: Final = {
    FundingStage.PRE_SEED: "Pre-seed",
    FundingStage.SEED: "Seed",
    FundingStage.SERIES_A: "Series A",
    FundingStage.SERIES_B: "Series B",
    FundingStage.SERIES_C_PLUS: "Series C+",
    FundingStage.UNKNOWN: "Stage unknown",
}
_STATUS: Final = {
    ElementStatus.UNKNOWN: "unknown",
    ElementStatus.HYPOTHESIZED: "hypothesized",
    ElementStatus.VALIDATED: "validated",
}


def make_console(
    *, stderr: bool = False, no_color: bool = False, width: int | None = None
) -> Console:
    """A console that never reinterprets data: no highlighting, no emoji codes.
    NO_COLOR is honoured when `no_color` is False."""
    return Console(
        stderr=stderr,
        no_color=True if no_color else None,
        width=width,
        highlight=False,
        emoji=False,
    )


def ascii_only(console: Console) -> bool:
    return not console.encoding.lower().startswith("utf")


# --- shared pieces ----------------------------------------------------------------------


def banner(*, data: DataSource | None, llm_model: str | None, mode: str) -> Text:
    """One line that says what is real: where the data came from and who wrote the text."""
    text = Text()
    text.append("DATA ", style="bold")
    if data is None:
        text.append("none analyzed", style="bright_black")
    else:
        label, style, meaning = _DATA[data]
        text.append(label, style=style)
        text.append(f" ({meaning})", style="bright_black")
    text.append(_SEP, style="bright_black")
    text.append("LLM ", style="bold")
    if llm_model is None:
        text.append("mock", style="bold yellow")
        text.append(" ($0, rules-based)", style="bright_black")
    else:
        text.append(llm_model, style="bold green")
    text.append(_SEP, style="bright_black")
    text.append("mode ", style="bold")
    text.append(mode)
    return text


def recommendation_text(recommendation: Recommendation) -> Text:
    label, style = _RECOMMENDATIONS[recommendation]
    return Text(label, style=style)


def health_text(element: ElementScore, *, ascii_mode: bool) -> Text:
    glyph, ascii_glyph, word, colour = _HEALTH[element.health]
    return Text(f"{ascii_glyph if ascii_mode else glyph} {word}", style=colour)


def verdict(brief: SDROutboundBrief) -> Text:
    """PURSUE · Tier C · MEDDPICC 52/100 · 50% known · fit 82"""
    scorecard = brief.scorecard
    text = recommendation_text(scorecard.recommendation)
    text.append(_SEP, style="bright_black")
    text.append(f"Tier {scorecard.tier.value}", style=_TIER_STYLES[scorecard.tier])
    text.append(_SEP, style="bright_black")
    text.append(f"MEDDPICC {scorecard.total_score}/100")
    text.append(_SEP, style="bright_black")
    text.append(f"{scorecard.coverage_pct:.0f}% known")
    text.append(_SEP, style="bright_black")
    text.append(f"fit {brief.value_props.overall_fit}")
    return text


def _label(value: str) -> str:
    return value.replace("_", " ").capitalize()


def _money(dollars: int) -> str:
    for scale, suffix in ((10**9, "B"), (10**6, "M"), (10**3, "K")):
        if dollars >= scale:
            return f"${dollars / scale:.1f}".removesuffix(".0") + suffix
    return f"${dollars}"


def _pct(confidence: float) -> str:
    return f"{confidence * 100:.0f}%"


def _bar(score: int, *, ascii_mode: bool, cells: int = 10) -> Text:
    filled = round(score / 100 * cells)
    full, empty = ("#", "-") if ascii_mode else ("█", "░")
    text = Text(full * filled, style="green" if score >= 60 else "yellow")
    text.append(empty * (cells - filled), style="bright_black")
    return text


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _notes(result: AnalysisResult) -> RenderableType | None:
    """Errors, collection warnings and the disclaimer, quietly, under a view."""
    lines: list[Text] = [Text(error, style="yellow") for error in result.errors]
    if result.brief is not None:
        signals = result.brief.profile.tech_stack
        if signals is not None:
            lines += [Text(warning, style="bright_black") for warning in signals.warnings]
        lines.append(Text(result.brief.disclaimer, style="bright_black italic"))
    return Group(*lines) if lines else None


def _failure_view(result: AnalysisResult) -> Panel:
    body = Group(*(Text(error, style="red") for error in result.errors))
    title = Text(f"{result.company_name} ({result.domain}): not analyzed", style="bold red")
    return Panel(body, title=title, title_align="left", border_style="red", box=box.ROUNDED)


# --- run: the account card --------------------------------------------------------------


def account_view(result: AnalysisResult, console: Console) -> RenderableType:
    """Profile and signals side by side (stacked when narrow), wedges, verdict and brief."""
    if result.brief is None:
        return _failure_view(result)
    brief = result.brief
    width = console.width
    ascii_mode = ascii_only(console)
    profile_panel = _panel("Account", _profile_grid(brief.profile))
    signals_panel = _panel("Signals", _signals_grid(brief, ascii_mode))
    cards: RenderableType = Group(profile_panel, signals_panel)
    if width >= WIDE:
        side_by_side = Table.grid(expand=True, padding=(0, 1))
        side_by_side.add_column(ratio=1)
        side_by_side.add_column(ratio=1)
        side_by_side.add_row(profile_panel, signals_panel)
        cards = side_by_side
    parts: list[RenderableType] = [
        cards,
        _wedges_table(brief, width, ascii_mode),
        verdict(brief),
        _brief_panel(brief, width, ascii_mode),
    ]
    if (notes := _notes(result)) is not None:
        parts.append(notes)
    return Group(*parts)


def _panel(title: str, body: RenderableType) -> Panel:
    return Panel(
        body, title=Text(title, style="bold"), title_align="left", box=box.ROUNDED, expand=True
    )


def _facts() -> Table:
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="bright_black", no_wrap=True)
    grid.add_column(overflow="fold")
    return grid


def _profile_grid(profile: StartupProfile) -> Table:
    grid = _facts()
    grid.add_row("Company", Text(profile.company_name, style="bold"))
    grid.add_row("Domain", Text(profile.domain))
    place = Text(", ".join(p for p in (profile.hq_city, profile.hq_state) if p))
    if profile.in_territory:
        place.append("  in territory", style="green")
    else:
        place.append("  outside territory", style="yellow")
    grid.add_row("HQ", place)
    grid.add_row("Vertical", Text(profile.vertical or "not given"))
    stage = [_STAGES[profile.funding_stage]]
    if profile.total_funding_usd:
        stage.append(f"{_money(profile.total_funding_usd)} raised")
    if profile.last_round_date:
        stage.append(f"last round {profile.last_round_date.isoformat()}")
    grid.add_row("Funding", Text(" · ".join(stage)))
    if profile.employee_count:
        grid.add_row("Employees", Text(str(profile.employee_count)))
    contacts = Text("\n").join(
        Text(f"{contact.name}, {contact.title}") for contact in profile.contacts
    )
    grid.add_row("Contacts", contacts if profile.contacts else Text("none supplied"))
    return grid


def _signals_grid(brief: SDROutboundBrief, ascii_mode: bool) -> Table:
    grid = _facts()
    signals = brief.profile.tech_stack
    if signals is None:
        grid.add_row("Signals", Text("not collected"))
        return grid
    grid.add_row("Hiring", _hiring(signals))
    grid.add_row("Cloud", _clouds(signals))
    competitors = " · ".join(
        f"{_COMPETITORS[c.kind]} {_pct(c.confidence)}" for c in signals.competitors
    )
    grid.add_row("Models", Text(competitors or "none seen"))
    times = "x" if ascii_mode else "×"  # noqa: RUF001 - a deliberate multiplication sign
    top = sorted(signals.keyword_hits.items(), key=lambda item: (-item[1], item[0].value))[:5]
    keywords = " · ".join(f"{_label(k.value).lower()} {times}{n}" for k, n in top)
    grid.add_row("Keywords", Text(keywords or "none seen"))
    label, style, _ = _DATA[signals.data_source]
    data = Text(label, style=style)
    data.append(f" · {len(signals.evidence)} evidence items")
    data.append(f" · {signals.collected_at.date().isoformat()}")
    grid.add_row("Data", data)
    return grid


def _hiring(signals: TechStackSignals) -> Text:
    if not signals.total_open_roles:
        return Text("no open roles found")
    text = Text(f"{signals.ai_role_count} AI/ML of {signals.total_open_roles} open roles")
    board = _ATS[signals.ats]
    if signals.ats_board_token:
        board += f" '{signals.ats_board_token}'"
    text.append(f" ({board})", style="bright_black")
    return text


def _clouds(signals: TechStackSignals) -> Text:
    if not signals.cloud:
        return Text("unknown")
    text = Text(" · ".join(f"{_CLOUDS[s.provider]} {_pct(s.confidence)}" for s in signals.cloud))
    if signals.primary_cloud is CloudProvider.MULTI:
        text.append(" (multi-cloud)", style="bright_black")
    return text


def _wedges_table(brief: SDROutboundBrief, width: int, ascii_mode: bool) -> Table:
    table = Table(
        title=Text("Anthropic wedges", style="bold"),
        title_justify="left",
        box=box.ROUNDED,
        expand=True,
    )
    table.add_column("Wedge", no_wrap=True)
    table.add_column("Fit", no_wrap=True)
    if width >= MEDIUM:
        table.add_column("Conf.", justify="right", no_wrap=True)
        table.add_column("Hypothesis", overflow="fold", ratio=1)
    primary = brief.value_props.primary_wedge
    for wedge in brief.value_props.wedges:
        name = Text(wedge.title, style="bold" if wedge.wedge_id is primary else "")
        if wedge.wedge_id is primary:
            name.append(" *" if ascii_mode else " ★", style="yellow")
        fit = Text(f"{wedge.fit_score:>3} ")
        if width >= MEDIUM:
            fit.append_text(_bar(wedge.fit_score, ascii_mode=ascii_mode))
            table.add_row(name, fit, _pct(wedge.confidence), Text(wedge.hypothesis))
        else:
            table.add_row(name, fit)
    if not brief.value_props.wedges:
        table.add_row(Text("none", style="bright_black"), *[""] * (len(table.columns) - 1))
    return table


def _brief_panel(brief: SDROutboundBrief, width: int, ascii_mode: bool) -> Panel:
    narrative = brief.narrative
    parts: list[RenderableType] = [Text(narrative.headline, style="bold")]
    if narrative.why_now:
        parts.append(Text("Why now", style="bright_black"))
        parts += [Text(f"- {reason}") for reason in narrative.why_now[:3]]
    parts.append(Text("Call opener", style="bright_black"))
    parts.append(Text(narrative.call_opener))
    plan = Text("Sequence  ", style="bright_black")
    plan.append(
        (" -> " if ascii_mode else " → ").join(
            f"day {t.day_offset} {t.channel.value}" for t in narrative.touches
        )
        if width >= MEDIUM
        else f"{len(narrative.touches)} touches over {narrative.touches[-1].day_offset} days"
    )
    parts.append(plan)
    return _panel("Outbound brief", Group(*parts))


# --- qualify: the MEDDPICC scorecard ----------------------------------------------------


def scorecard_view(result: AnalysisResult, console: Console) -> RenderableType:
    """The MEDDPICC table: a column per detail when wide, stacked elements when narrow."""
    if result.brief is None:
        return _failure_view(result)
    brief = result.brief
    ascii_mode = ascii_only(console)
    header = Text(brief.profile.company_name, style="bold")
    header.append(f"  {brief.profile.domain}", style="bright_black")
    header.append(f"  {brief.profile.hq_state}", style="bright_black")
    if console.width >= MEDIUM:
        body: RenderableType = _scorecard_table(brief, console.width, ascii_mode)
    else:
        body = _scorecard_stack(brief, ascii_mode)
    parts: list[RenderableType] = [header, body, verdict(brief)]
    if (notes := _notes(result)) is not None:
        parts.append(notes)
    return Group(*parts)


def _scorecard_table(brief: SDROutboundBrief, width: int, ascii_mode: bool) -> Table:
    scorecard = brief.scorecard
    evidence = {item.id: item for item in brief.evidence}
    wide = width >= WIDE
    table = Table(
        title=Text("MEDDPICC scorecard", style="bold"),
        title_justify="left",
        box=box.ROUNDED,
        show_footer=True,
        expand=True,
    )
    table.add_column("Element", footer=Text("Total", style="bold"), no_wrap=True)
    table.add_column(
        "Score", footer=Text(f"{scorecard.total_score}/100", style="bold"), no_wrap=True
    )
    table.add_column("Status", footer=f"{scorecard.coverage_pct:.0f}% known", no_wrap=True)
    table.add_column("Health", footer=_tier_text(scorecard), no_wrap=True)
    if wide:
        table.add_column("Key evidence", overflow="ellipsis", no_wrap=True, ratio=2)
    table.add_column(
        "Next action",
        footer=recommendation_text(scorecard.recommendation),
        overflow="fold",
        ratio=3,
    )
    for element in scorecard.elements:
        cells: list[RenderableType] = [
            Text(_label(element.element.value)),
            _score_text(element),
            Text(_STATUS[element.status], style="bright_black"),
            health_text(element, ascii_mode=ascii_mode),
        ]
        if wide:
            cells.append(_evidence_text(element, evidence))
        cells.append(Text(element.next_action))
        table.add_row(*cells)
    return table


def _scorecard_stack(brief: SDROutboundBrief, ascii_mode: bool) -> Group:
    rows: list[RenderableType] = [Text("MEDDPICC scorecard", style="bold")]
    arrow = "->" if ascii_mode else "→"
    for element in brief.scorecard.elements:
        line = health_text(element, ascii_mode=ascii_mode)
        line.append(f"  {_label(element.element.value)}  ", style="bold")
        line.append_text(_score_text(element))
        line.append(f"  {_STATUS[element.status]}", style="bright_black")
        rows.append(line)
        action = Table.grid(padding=(0, 1))  # a hanging indent for wrapped lines
        action.add_column(no_wrap=True)
        action.add_column(overflow="fold")
        action.add_row(f"  {arrow}", Text(element.next_action))
        rows.append(action)
    return Group(*rows)


def _score_text(element: ElementScore) -> Text:
    if element.score is None:
        return Text("–", style="bright_black")  # noqa: RUF001 - en dash: no score yet
    return Text(f"{element.score}/10")


def _tier_text(scorecard: MEDDPICCScorecard) -> Text:
    return Text(f"Tier {scorecard.tier.value}", style=_TIER_STYLES[scorecard.tier])


def _evidence_text(element: ElementScore, evidence: Mapping[str, Evidence]) -> Text:
    if not element.evidence_ids:
        return Text("none yet", style="bright_black")
    first = element.evidence_ids[0]
    item = evidence.get(first)
    more = len(element.evidence_ids) - 1
    text = Text(f"{first} ", style="bold")
    text.append(item.snippet if item is not None else "")
    if more:
        text.append(f" (+{more})", style="bright_black")
    return text


# --- territory-batch --------------------------------------------------------------------


def batch_view(
    rows: Sequence[tuple[int, AnalysisResult]], console: Console, *, total: int
) -> Table:
    """The ranked shortlist. `rows` are (rank, result) pairs; `total` counts every account."""
    width = console.width
    table = Table(
        title=Text(f"Ranked accounts: {len(rows)} shown of {total}", style="bold"),
        title_justify="left",
        box=box.ROUNDED,
        expand=True,
    )
    table.add_column("#", justify="right", no_wrap=True)
    table.add_column("Company", overflow="fold", ratio=2)
    if width >= MEDIUM:
        table.add_column("ST", no_wrap=True)
    table.add_column("Recommendation" if width >= WIDE else "Rec.", no_wrap=True)
    if width >= MEDIUM:
        table.add_column("Tier", no_wrap=True)
        table.add_column("MEDDPICC", justify="right", no_wrap=True)
    table.add_column("Fit", justify="right", no_wrap=True)
    if width >= WIDE:
        table.add_column("Primary wedge", overflow="fold", ratio=1)
        table.add_column("Data", no_wrap=True)
    for position, result in rows:
        if result.brief is None:
            continue
        brief = result.brief
        scorecard = brief.scorecard
        cells: list[RenderableType] = [str(position), Text(result.company_name)]
        if width >= MEDIUM:
            cells.append(brief.profile.hq_state)
        cells.append(recommendation_text(scorecard.recommendation))
        if width >= MEDIUM:
            cells.append(_tier_text(scorecard))
            cells.append(str(scorecard.total_score))
        cells.append(str(brief.value_props.overall_fit))
        if width >= WIDE:
            primary = next(
                (
                    w.title
                    for w in brief.value_props.wedges
                    if w.wedge_id is brief.value_props.primary_wedge
                ),
                "none",
            )
            label, style, _ = _DATA[brief.data_source]
            cells += [Text(primary), Text(label, style=style)]
        table.add_row(*cells)
    return table


def failures_view(row_errors: Sequence[RowError], failed: Sequence[AnalysisResult]) -> Table | None:
    """Rows the targets file could not load and accounts that could not be analyzed."""
    if not row_errors and not failed:
        return None
    table = Table(
        title=Text("Not analyzed", style="bold red"),
        title_justify="left",
        box=box.ROUNDED,
        expand=True,
    )
    table.add_column("Where", no_wrap=True)
    table.add_column("Domain", overflow="fold")
    table.add_column("Problem", overflow="fold", ratio=1)
    for error in row_errors:
        table.add_row(f"line {error.line}", Text(error.domain or ""), Text(error.message))
    for result in failed:
        table.add_row(Text(result.company_name), Text(result.domain), Text(" ".join(result.errors)))
    return table


def usage_view(
    usage: LLMUsage,
    *,
    llm_model: str | None,
    data_counts: Mapping[DataSource, int],
    resumed: int = 0,
) -> Text:
    """What the run cost and what its data was."""
    text = Text("LLM ", style="bold")
    if llm_model is None:
        text.append("mock: no tokens, $0.00")
    else:
        prompt = usage.input_tokens + usage.cache_read_tokens + usage.cache_write_tokens
        hit_rate = usage.cache_read_tokens / prompt if prompt else 0.0
        text.append(
            f"{llm_model}: {usage.input_tokens:,} input, {usage.output_tokens:,} output, "
            f"{usage.cache_read_tokens:,} cache-read tokens ({hit_rate:.0%} of prompt), "
            f"est. ${usage.est_cost_usd:.2f}"
        )
    text.append("\nData ", style="bold")
    parts = [
        f"{count} {_DATA[source][0].lower()}"
        for source, count in sorted(data_counts.items())
        if count
    ]
    text.append(", ".join(parts) or "nothing analyzed")
    if resumed:
        text.append(f"\nResumed {resumed} account(s) from the checkpoint", style="bright_black")
    return text


# --- doctor -----------------------------------------------------------------------------


def doctor_view(checks: Sequence[tuple[str, bool | None, str]], console: Console) -> Table:
    ascii_mode = ascii_only(console)
    table = Table(
        title=Text("prospector doctor", style="bold"),
        title_justify="left",
        box=box.ROUNDED,
        expand=True,
    )
    table.add_column("Check", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Detail", overflow="fold", ratio=1)
    for name, ok, detail in checks:
        if ok is None:
            status = Text("- info" if ascii_mode else "· info", style="bright_black")
        elif ok:
            status = Text("+ ok" if ascii_mode else "✓ ok", style="green")
        else:
            status = Text("x problem" if ascii_mode else "✗ problem", style="red")
        table.add_row(Text(name), status, Text(detail))
    return table


# --- progress ---------------------------------------------------------------------------


class BatchProgress:
    """Live progress for territory-batch: a bar on a terminal, one line per account
    otherwise (CI logs, pipes). Writes to the console it is given, normally stderr."""

    def __init__(self, console: Console, total: int) -> None:
        self._console = console
        self._total = total
        self._done = 0
        self._live = console.is_terminal
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("{task.description}", markup=False),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=console,
            transient=True,
            disable=not self._live,
        )
        self._task = self._progress.add_task("Qualifying accounts", total=total)

    def __enter__(self) -> Self:
        self._progress.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._progress.stop()

    def advance(self, result: AnalysisResult) -> None:
        self._done += 1
        outcome = (
            _RECOMMENDATIONS[result.brief.scorecard.recommendation][0]
            if result.brief is not None
            else "FAILED"
        )
        description = f"{result.company_name}: {outcome}"
        if self._live:
            self._progress.update(self._task, advance=1, description=description)
        else:
            self._console.print(Text(f"[{self._done}/{self._total}] {description}"))


def working(console: Console, message: str) -> Status:
    """A spinner for one slow step; shows nothing when the console is not a terminal."""
    return console.status(Text(message), spinner="dots")
