"""Lever postings: GET api.lever.co/v0/postings/{token}?mode=json (api.eu.lever.co for EU).

Quirks: the payload is a bare list, `createdAt` is epoch milliseconds and may be missing,
and a posting may carry only HTML (`description`, `additional`) without the plain variants.
"""

from datetime import UTC, datetime
from typing import Any

from anthropic_prospector.models import ATSPlatform, JobPosting
from anthropic_prospector.scrapers.ats.base import ParsedBoard, html_to_text


def _text(value: Any) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def _plain_or_html(raw: dict[str, Any], plain: str, markup: str) -> str:
    if text := _text(raw.get(plain)):
        return text
    html = raw.get(markup)
    return html_to_text(html) if isinstance(html, str) else ""


class LeverAdapter:
    platform = ATSPlatform.LEVER

    def __init__(self, *, eu: bool = False) -> None:
        self._host = "api.eu.lever.co" if eu else "api.lever.co"

    def board_url(self, token: str) -> str:
        return f"https://{self._host}/v0/postings/{token}?mode=json"

    def summary_url(self, token: str) -> str | None:
        return None

    def parse(self, payload: Any) -> ParsedBoard:
        if not isinstance(payload, list):
            return ParsedBoard()
        postings: list[JobPosting] = []
        skipped = 0
        for raw in payload:
            if not isinstance(raw, dict):
                continue  # not a record at all, so not a skipped posting
            try:
                postings.append(self._posting(raw))
            except (ValueError, TypeError, KeyError, AttributeError, OverflowError, OSError):
                skipped += 1
        return ParsedBoard(postings, skipped)

    def _posting(self, raw: Any) -> JobPosting:
        categories = raw.get("categories")
        if not isinstance(categories, dict):
            categories = {}
        parts = [_plain_or_html(raw, "descriptionPlain", "description")]
        lists = raw.get("lists")
        for item in lists if isinstance(lists, list) else []:
            parts.append(_text(item.get("text")) or "")
            content = item.get("content")
            parts.append(html_to_text(content) if isinstance(content, str) else "")
        parts.append(_plain_or_html(raw, "additionalPlain", "additional"))
        created = raw.get("createdAt")
        return JobPosting(
            ats=self.platform,
            external_id=str(raw["id"]),
            title=_text(raw.get("text")) or "",
            url=_text(raw.get("hostedUrl")) or "",
            location=_text(categories.get("location")),
            department=_text(categories.get("department")) or _text(categories.get("team")),
            description_text="\n".join(p for p in parts if p),
            posted_at=(
                datetime.fromtimestamp(created / 1000, UTC)
                if isinstance(created, int | float) and not isinstance(created, bool)
                else None
            ),
        )
