"""CAROUSEL_DECK.md keeps the shape the LinkedIn carousel needs and the promises its copy
makes: six slides with short headlines and bodies, every colour from the brand palette,
and contrast ratios that are what the table says they are."""

import re
from pathlib import Path

import pytest

DECK = Path(__file__).resolve().parents[1] / "CAROUSEL_DECK.md"
PALETTE = {
    "Dark": "#141413",
    "Light": "#faf9f5",
    "Mid Gray": "#b0aea5",
    "Light Gray": "#e8e6dc",
    "Orange": "#d97757",
    "Blue": "#6a9bcc",
    "Green": "#788c5d",
}
FIELDS = ("Headline", "Body", "Background", "Visual", "Design prompt", "Alt text")
MAX_HEADLINE_WORDS = 8
MAX_BODY_WORDS = 25

_SLIDE = re.compile(r"^### Slide (\d+): (.+)$", re.MULTILINE)
_FIELD = re.compile(r"^- \*\*(.+?):\*\* (.+)$", re.MULTILINE)
_CONTRAST_ROW = re.compile(
    r"^\| ([A-Z][a-z]+(?: [A-Z][a-z]+)?) \| ([A-Z][a-z]+(?: [A-Z][a-z]+)?) \| "
    r"(\d+\.\d\d):1 \| (.+) \|$",
    re.MULTILINE,
)
_HASHTAG = re.compile(r"(?<!\S)#([A-Za-z][A-Za-z0-9]*)")


def _text() -> str:
    return DECK.read_text(encoding="utf-8")


def _section(title: str) -> str:
    text = _text()
    start = text.index(f"\n{title}\n")
    end = text.find("\n#", start + len(title) + 2)
    return text[start : end if end != -1 else len(text)]


def _slides() -> list[dict[str, str]]:
    text = _text()
    marks = list(_SLIDE.finditer(text))
    slides = []
    for index, mark in enumerate(marks):
        end = (
            marks[index + 1].start() if index + 1 < len(marks) else text.index("\n## ", mark.end())
        )
        fields = dict(_FIELD.findall(text[mark.end() : end]))
        slides.append({"number": mark.group(1), "title": mark.group(2), **fields})
    return slides


def _luminance(colour: str) -> float:
    channels = [int(colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(foreground: str, background: str) -> float:
    high, low = sorted((_luminance(foreground), _luminance(background)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def test_six_slides_in_order() -> None:
    assert [slide["number"] for slide in _slides()] == ["1", "2", "3", "4", "5", "6"]


@pytest.mark.parametrize("slide", _slides(), ids=lambda slide: f"slide-{slide['number']}")
def test_slide_copy_fits_the_limits(slide: dict[str, str]) -> None:
    missing = [name for name in FIELDS if not slide.get(name)]
    assert not missing, f"slide {slide['number']} lacks {missing}"
    assert len(slide["Headline"].split()) <= MAX_HEADLINE_WORDS
    assert len(slide["Body"].split()) <= MAX_BODY_WORDS
    assert slide["Background"] in {"Dark", "Light"}


def test_every_colour_is_from_the_palette() -> None:
    used = {colour.lower() for colour in re.findall(r"#[0-9a-fA-F]{6}\b", _text())}
    assert used <= set(PALETTE.values()), used - set(PALETTE.values())


def test_contrast_table_is_accurate() -> None:
    rows = _CONTRAST_ROW.findall(_text())
    assert len(rows) >= 10
    for foreground, background, ratio, _ in rows:
        assert f"{_contrast(PALETTE[foreground], PALETTE[background]):.2f}" == ratio, (
            f"{foreground} on {background}"
        )


def test_post_fits_linkedin() -> None:
    post = _section("### Post copy")
    body = "\n".join(line.removeprefix(">").strip() for line in post.splitlines()[2:])
    assert len(body) <= 3000  # LinkedIn's post limit
    assert 3 <= len(_HASHTAG.findall(body)) <= 5
