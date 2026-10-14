"""Greenhouse job board: GET boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true.

Quirks: `content` is entity-escaped HTML (it must be unescaped before tags are parsed),
`location` may be null, `departments` may be empty, and timestamps carry a UTC offset.
"""

from datetime import datetime
from typing import Any

from anthropic_prospector.models import ATSPlatform, JobPosting
from anthropic_prospector.scrapers.ats.base import ParsedBoard, html_to_text


def _text(value: Any) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


class GreenhouseAdapter:
    platform = ATSPlatform.GREENHOUSE

    def board_url(self, token: str) -> str:
        return f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"

    def summary_url(self, token: str) -> str | None:
        return f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs"

    def parse(self, payload: Any) -> ParsedBoard:
        jobs = payload.get("jobs") if isinstance(payload, dict) else None
        if not isinstance(jobs, list):
            return ParsedBoard()
        postings: list[JobPosting] = []
        skipped = 0
        for raw in jobs:
            try:
                postings.append(self._posting(raw))
            except (ValueError, TypeError, KeyError, AttributeError):
                skipped += 1
        return ParsedBoard(postings, skipped)

    def _posting(self, raw: Any) -> JobPosting:
        location = raw.get("location")
        departments = raw.get("departments")
        department = None
        if isinstance(departments, list) and departments:
            department = _text(departments[0].get("name"))
        posted = _text(raw.get("first_published")) or _text(raw.get("updated_at"))
        content = raw.get("content")
        return JobPosting(
            ats=self.platform,
            external_id=str(raw["id"]),
            title=_text(raw.get("title")) or "",
            url=_text(raw.get("absolute_url")) or "",
            location=_text(location.get("name")) if isinstance(location, dict) else None,
            department=department,
            description_text=html_to_text(content, escaped=True)
            if isinstance(content, str)
            else "",
            posted_at=datetime.fromisoformat(posted) if posted else None,
        )
