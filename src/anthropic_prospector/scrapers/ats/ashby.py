"""Ashby job board: GET api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=false.

Quirks: field drift between API versions (`jobUrl` or `applyUrl`, `publishedAt` or
`publishedDate`, `descriptionPlain` or only `descriptionHtml`), and unlisted jobs
(`isListed: false`) that must not be treated as open roles.
"""

from datetime import datetime
from typing import Any

from anthropic_prospector.models import ATSPlatform, JobPosting
from anthropic_prospector.scrapers.ats.base import ParsedBoard, html_to_text


def _text(value: Any) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


class AshbyAdapter:
    platform = ATSPlatform.ASHBY

    def board_url(self, token: str) -> str:
        return f"https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=false"

    def summary_url(self, token: str) -> str | None:
        return None

    def parse(self, payload: Any) -> ParsedBoard:
        jobs = payload.get("jobs") if isinstance(payload, dict) else None
        if not isinstance(jobs, list):
            return ParsedBoard()
        postings: list[JobPosting] = []
        skipped = 0
        for raw in jobs:
            try:
                if raw.get("isListed") is False:
                    continue
                postings.append(self._posting(raw))
            except (ValueError, TypeError, KeyError, AttributeError):
                skipped += 1
        return ParsedBoard(postings, skipped)

    def _posting(self, raw: Any) -> JobPosting:
        html = raw.get("descriptionHtml")
        description = _text(raw.get("descriptionPlain")) or (
            html_to_text(html) if isinstance(html, str) else ""
        )
        posted = _text(raw.get("publishedAt")) or _text(raw.get("publishedDate"))
        return JobPosting(
            ats=self.platform,
            external_id=str(raw["id"]),
            title=_text(raw.get("title")) or "",
            url=_text(raw.get("jobUrl")) or _text(raw.get("applyUrl")) or "",
            location=_text(raw.get("location")),
            department=_text(raw.get("department")) or _text(raw.get("team")),
            description_text=description,
            posted_at=datetime.fromisoformat(posted) if posted else None,
        )
