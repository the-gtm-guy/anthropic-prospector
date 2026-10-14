"""Public ATS job boards: Greenhouse, Lever and Ashby.

find_board() locates a company's public board and parses it. Candidates are tried in a
fixed order:

1. the board token from the targets file, on its `ats_hint` platform or else on each;
2. boards linked from the company's own pages (board_links() finds them);
3. slugs guessed from the company name and domain.

The first two are trusted, so the first of them that answers wins. A guessed board is
accepted only when its postings mention the company: a slug such as "atlas" can belong to
anyone. A board that does not exist (404), cannot be reached or does not parse never fails
the lookup; it becomes a warning and the next candidate is tried.
"""

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final, TypeVar
from urllib.parse import urlsplit

from anthropic_prospector.models import ATSPlatform, JobPosting, StartupProfile
from anthropic_prospector.scrapers.ats.ashby import AshbyAdapter
from anthropic_prospector.scrapers.ats.base import ATSAdapter
from anthropic_prospector.scrapers.ats.greenhouse import GreenhouseAdapter
from anthropic_prospector.scrapers.ats.lever import LeverAdapter
from anthropic_prospector.scrapers.http import Fetcher, FetchError, ResponseTooLarge

_T = TypeVar("_T")

PLATFORMS: Final = (ATSPlatform.GREENHOUSE, ATSPlatform.LEVER, ATSPlatform.ASHBY)
PLATFORM_NAMES: Final[Mapping[ATSPlatform, str]] = {
    ATSPlatform.GREENHOUSE: "Greenhouse",
    ATSPlatform.LEVER: "Lever",
    ATSPlatform.ASHBY: "Ashby",
}
BOARD_MAX_BYTES: Final = 8_000_000  # boards with full descriptions run to megabytes
MAX_GUESSED_SLUGS: Final = 3
VERIFY_POSTINGS: Final = 25  # postings read when checking that a guessed board fits

_ADAPTERS: Final[Mapping[ATSPlatform, ATSAdapter]] = {
    ATSPlatform.GREENHOUSE: GreenhouseAdapter(),
    ATSPlatform.ASHBY: AshbyAdapter(),
}
_LEVER_US: Final = LeverAdapter()
_LEVER_EU: Final = LeverAdapter(eu=True)

# Board links as they appear in page markup: links, embed scripts and API calls.
_GREENHOUSE_LINKS: Final = (
    re.compile(
        r"greenhouse\.io/embed/job_board(?:/js)?\?(?:[^\"'\s<>]*?&(?:amp;)?)?for=([\w-]+)",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:job-)?boards\.greenhouse\.io/(?!embed\b)([\w-]+)", re.IGNORECASE),
    re.compile(r"\bboards-api\.greenhouse\.io/v1/boards/([\w-]+)", re.IGNORECASE),
)
_LEVER_LINKS: Final = (
    re.compile(r"\bjobs\.(eu\.)?lever\.co/([\w-]+)", re.IGNORECASE),
    re.compile(r"\bapi\.(eu\.)?lever\.co/v0/postings/([\w-]+)", re.IGNORECASE),
)
_ASHBY_LINKS: Final = (
    re.compile(r"\bjobs\.ashbyhq\.com/([\w.-]+)", re.IGNORECASE),
    re.compile(r"\bapi\.ashbyhq\.com/posting-api/job-board/([\w.-]+)", re.IGNORECASE),
)
_NOT_TOKENS: Final = frozenset({"api", "assets", "embed", "js", "jobs", "static", "v0", "v1"})
# Trailing words dropped from a company name when guessing slugs and matching names.
_NAME_SUFFIXES: Final = frozenset(
    {"ai", "co", "company", "corp", "hq", "inc", "io", "labs", "llc", "ltd", "technologies"}
)


@dataclass(frozen=True)
class BoardRef:
    platform: ATSPlatform
    token: str
    eu: bool = False  # Lever boards hosted in the EU are served from a separate API host

    @property
    def label(self) -> str:
        return f"{PLATFORM_NAMES[self.platform]} board '{self.token}'"


@dataclass(frozen=True)
class Board:
    ref: BoardRef
    api_url: str
    postings: list[JobPosting]
    skipped: int  # listed postings that could not be normalized

    @property
    def total_roles(self) -> int:
        return len(self.postings) + self.skipped


@dataclass(frozen=True)
class BoardLookup:
    board: Board | None
    warnings: list[str] = field(default_factory=list)
    reached: bool = False  # some ATS API answered, even if only with "no such board"


def adapter_for(ref: BoardRef) -> ATSAdapter:
    if ref.platform is ATSPlatform.LEVER:
        return _LEVER_EU if ref.eu else _LEVER_US
    return _ADAPTERS[ref.platform]


def board_links(markup: str) -> list[BoardRef]:
    """Boards referenced anywhere in `markup` (or a URL), in order of first appearance."""
    found: list[tuple[int, BoardRef]] = []
    for pattern in _GREENHOUSE_LINKS:
        found += [
            (m.start(), BoardRef(ATSPlatform.GREENHOUSE, m[1])) for m in pattern.finditer(markup)
        ]
    for pattern in _LEVER_LINKS:
        found += [
            (m.start(), BoardRef(ATSPlatform.LEVER, m[2], eu=bool(m[1])))
            for m in pattern.finditer(markup)
        ]
    for pattern in _ASHBY_LINKS:
        found += [
            (m.start(), BoardRef(ATSPlatform.ASHBY, m[1].rstrip(".")))
            for m in pattern.finditer(markup)
        ]
    found.sort(key=lambda item: item[0])
    return _unique(ref for _, ref in found if ref.token and ref.token.lower() not in _NOT_TOKENS)


async def find_board(
    fetcher: Fetcher, profile: StartupProfile, linked: Sequence[BoardRef] = ()
) -> BoardLookup:
    warnings: list[str] = []
    reached = False

    async def read(ref: BoardRef) -> Board | None:
        nonlocal reached
        adapter = adapter_for(ref)
        url = adapter.board_url(ref.token)
        try:
            try:
                status, payload = await fetcher.get_json(url, max_bytes=BOARD_MAX_BYTES)
            except ResponseTooLarge:
                if (summary := adapter.summary_url(ref.token)) is None:
                    raise
                url = summary
                status, payload = await fetcher.get_json(url, max_bytes=BOARD_MAX_BYTES)
                warnings.append(
                    f"The {ref.label} is too large to read in full, so only job titles were read."
                )
        except FetchError as exc:
            # A 200 that is not JSON still means the API answered.
            reached = reached or exc.status is not None
            warnings.append(f"Could not read the {ref.label}: {exc}")
            return None
        reached = True
        if status != 200:
            if status != 404:
                warnings.append(f"The {ref.label} answered HTTP {status}.")
            return None
        parsed = adapter.parse(payload)
        if parsed.skipped:
            warnings.append(
                f"The {ref.label} listed {parsed.skipped} posting(s) that could not be read."
            )
        return Board(ref, url, parsed.postings, parsed.skipped)

    trusted = _unique([*_from_targets(profile), *linked])
    for ref in trusted:
        if (board := await read(ref)) is not None:
            return BoardLookup(board, warnings, reached)

    for ref in _guesses(profile):
        if ref in trusted or (board := await read(ref)) is None:
            continue
        if mentions_company(board.postings, profile):
            return BoardLookup(board, warnings, reached)
        if board.postings:
            warnings.append(
                f"Ignored the {ref.label}: its postings do not mention {profile.company_name}."
            )

    warnings.append(
        f"No public Greenhouse, Lever or Ashby job board found for {profile.company_name}; "
        "set ats_board_token in the targets file if it has one."
    )
    return BoardLookup(None, warnings, reached)


def guess_slugs(profile: StartupProfile) -> list[str]:
    """Likely board tokens: the joined name, the domain label, the hyphenated name, the
    name without suffixes such as "AI" or "Labs"."""
    words = re.findall(r"[a-z0-9]+", profile.company_name.lower())
    core = _core_words(words)
    label = profile.domain.split(".")[0]
    candidates = ["".join(words), label, "-".join(words), "".join(core)]
    return _unique(slug for slug in candidates if len(slug) >= 3)[:MAX_GUESSED_SLUGS]


def mentions_company(postings: Sequence[JobPosting], profile: StartupProfile) -> bool:
    """True when a posting links to the company's domain or names the company."""
    words = re.findall(r"[a-z0-9]+", profile.company_name.lower())
    names = [
        r"\s+".join(map(re.escape, variant))
        for variant in _unique((tuple(words), tuple(_core_words(words))))
        if len("".join(variant)) >= 4
    ]
    name = re.compile(rf"\b(?:{'|'.join(names)})\b", re.IGNORECASE) if names else None
    domain = profile.domain
    for posting in postings[:VERIFY_POSTINGS]:
        host = urlsplit(posting.url).hostname or ""
        if host == domain or host.endswith(f".{domain}"):
            return True
        text = f"{posting.title}\n{posting.description_text}"
        if domain in text.lower() or (name is not None and name.search(text)):
            return True
    return False


def _from_targets(profile: StartupProfile) -> list[BoardRef]:
    token = (profile.ats_board_token or "").strip()
    if not token:
        return []
    hint = profile.ats_hint
    if hint is ATSPlatform.LEVER:
        return [BoardRef(hint, token), BoardRef(hint, token, eu=True)]
    if hint is not None and hint in PLATFORMS:
        return [BoardRef(hint, token)]
    return [BoardRef(platform, token) for platform in PLATFORMS]


def _guesses(profile: StartupProfile) -> list[BoardRef]:
    """Every slug on the hinted platform first, then each slug on the other platforms."""
    slugs = guess_slugs(profile)
    hinted = [p for p in PLATFORMS if p is profile.ats_hint]
    others = [p for p in PLATFORMS if p is not profile.ats_hint]
    return [BoardRef(p, slug) for p in hinted for slug in slugs] + [
        BoardRef(p, slug) for slug in slugs for p in others
    ]


def _core_words(words: list[str]) -> list[str]:
    core = list(words)
    while len(core) > 1 and core[-1] in _NAME_SUFFIXES:
        core.pop()
    return core


def _unique(items: Iterable[_T]) -> list[_T]:
    return list(dict.fromkeys(items))
