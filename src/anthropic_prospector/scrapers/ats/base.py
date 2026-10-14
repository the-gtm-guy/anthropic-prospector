"""The contract every ATS adapter follows, and the HTML-to-text helper they share.

An adapter knows one job-board API: where a company's public board lives and how to turn
its JSON into JobPostings. parse() is pure, so it is tested against recorded payloads.
Boards drift: raw records are read leniently, and a posting that cannot be normalized is
skipped and counted, never allowed to fail the whole board.
"""

import html
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Final, Protocol

from anthropic_prospector.models import ATSPlatform, JobPosting

# Elements a browser lays out apart: their text must not run together ("ServicesOpenAI").
_BLOCK_TAGS: Final = frozenset(
    {
        "address", "article", "aside", "blockquote", "br", "dd", "div", "dl", "dt",
        "figcaption", "footer", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "li",
        "main", "nav", "ol", "p", "pre", "section", "table", "td", "th", "tr", "ul",
    }
)  # fmt: skip
_SKIP_TAGS: Final = frozenset({"script", "style", "noscript", "template", "svg"})


@dataclass(frozen=True)
class ParsedBoard:
    postings: list[JobPosting] = field(default_factory=list)
    skipped: int = 0  # records that could not be normalized


class ATSAdapter(Protocol):
    platform: ATSPlatform

    def board_url(self, token: str) -> str:
        """The public JSON endpoint for a board token."""
        ...

    def summary_url(self, token: str) -> str | None:
        """A lighter listing without descriptions, for boards too large to read in full;
        None when the API offers none."""
        ...

    def parse(self, payload: Any) -> ParsedBoard:
        """Normalize a board payload. Must not raise on malformed records."""
        ...


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)


def html_to_text(markup: str, *, escaped: bool = False) -> str:
    """Visible text of an HTML fragment, one block per line.

    `escaped=True` first unescapes entity-encoded HTML, as Greenhouse returns it.
    """
    if escaped:
        markup = html.unescape(markup)
    parser = _TextExtractor()
    parser.feed(markup)
    parser.close()
    lines = (
        re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in "".join(parser.parts).split("\n")
    )
    return "\n".join(line for line in lines if line)
