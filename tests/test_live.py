"""Smoke tests against real public endpoints. Opt in with: pytest -m live

They catch drift that recorded fixtures cannot: an ATS changing its payload shows up here
as an empty board or a pile of skipped postings. They need network access, read only
public job-board APIs and pages, and never run in CI.
"""

from pathlib import Path

import pytest

from anthropic_prospector.config import Settings
from anthropic_prospector.models import ATSPlatform, DataSource, StartupProfile
from anthropic_prospector.scrapers.ats import find_board
from anthropic_prospector.scrapers.collect import collect
from anthropic_prospector.scrapers.http import DiskCache, Fetcher

pytestmark = pytest.mark.live

# Each ATS vendor's own public board, plus Anthropic's, which is large enough to exercise
# the titles-only fallback.
BOARDS = [
    ("Anthropic", "anthropic.com", ATSPlatform.GREENHOUSE, "anthropic"),
    ("Lever", "lever.co", ATSPlatform.LEVER, "leverdemo"),
    ("Ashby", "ashbyhq.com", ATSPlatform.ASHBY, "ashby"),
]


@pytest.mark.parametrize(
    ("company", "domain", "platform", "token"), BOARDS, ids=[b[2].value for b in BOARDS]
)
async def test_public_board_still_parses(
    company: str, domain: str, platform: ATSPlatform, token: str, tmp_path: Path
) -> None:
    profile = StartupProfile(
        company_name=company,
        domain=domain,
        hq_state="CA",
        ats_hint=platform,
        ats_board_token=token,
    )
    async with Fetcher(Settings(), cache=DiskCache(tmp_path, ttl_s=0)) as fetcher:
        lookup = await find_board(fetcher, profile)
    assert lookup.board is not None, lookup.warnings
    board = lookup.board
    assert board.ref.platform is platform
    assert board.postings, f"{board.ref.label} parsed to no postings"
    assert board.skipped <= len(board.postings) // 10, "many skips suggest payload drift"


async def test_collect_reads_a_real_company(tmp_path: Path) -> None:
    profile = StartupProfile(company_name="Anthropic", domain="anthropic.com", hq_state="CA")
    async with Fetcher(Settings(), cache=DiskCache(tmp_path, ttl_s=0)) as fetcher:
        signals = await collect(profile, fetcher=fetcher, strict=True)
    assert signals.data_source is DataSource.LIVE
    assert signals.ats is ATSPlatform.GREENHOUSE
    assert signals.total_open_roles > 0
