"""collect(): live sources merged into TechStackSignals, and the fallback rules."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx

from anthropic_prospector.config import Settings
from anthropic_prospector.mock import mock_signals
from anthropic_prospector.models import (
    ATSPlatform,
    CloudProvider,
    CompetitorKind,
    DataSource,
    SignalKeyword,
    StartupProfile,
)
from anthropic_prospector.pipeline import MockLLMClient, run_pipeline, to_markdown
from anthropic_prospector.scrapers.collect import (
    CollectionError,
    Fallback,
    collect,
    is_reserved,
)
from anthropic_prospector.scrapers.dns_intel import DnsUnavailable
from anthropic_prospector.scrapers.http import DiskCache, Fetcher

NOW = datetime(2026, 10, 1, 16, 0, tzinfo=UTC)
SITE = "https://northwind-ai.com"
LEVER_API = "https://api.lever.co/v0/postings/northwind?mode=json"

HOMEPAGE = """<html><body>
<h1>Northwind AI</h1>
<p>AI agents for customer support teams.</p>
<a href="https://jobs.lever.co/northwind">Careers</a>
</body></html>"""

SUBPROCESSORS = """<html><body><table>
<tr><td>Amazon Web Services</td><td>Cloud hosting</td></tr>
<tr><td>OpenAI</td><td>Language model provider</td></tr>
</table></body></html>"""

POSTINGS = [
    {
        "id": "a1",
        "text": "Senior LLM Engineer",
        "hostedUrl": "https://jobs.lever.co/northwind/a1",
        "categories": {"location": "Seattle, WA", "team": "Engineering"},
        "descriptionPlain": (
            "We use LangChain and the OpenAI API for RAG over help-center articles.\n"
            "You will own our evals and cut the inference cost per ticket."
        ),
    },
    {
        "id": "a2",
        "text": "Account Executive",
        "hostedUrl": "https://jobs.lever.co/northwind/a2",
        "categories": {"team": "Sales"},
        "descriptionPlain": "Familiarity with OpenAI and SOC 2 reviews is a plus.",
    },
    {
        "id": "a3",
        "text": "Backend Engineer",
        "hostedUrl": "https://jobs.lever.co/northwind/a3",
        "categories": {"team": "Engineering"},
        "descriptionPlain": "Build APIs on AWS with ECS and S3. We are SOC 2 Type II.",
    },
]


class FakeResolver:
    def __init__(self, records: dict[tuple[str, str], list[str]], *, down: bool = False):
        self.records = records
        self.down = down

    async def resolve(self, name: str, rdtype: str) -> list[str]:
        if self.down:
            raise DnsUnavailable(name)
        return self.records.get((name, rdtype), [])


AWS_DNS = FakeResolver(
    {("app.northwind-ai.com", "CNAME"): ["k8s-prod-1234.us-west-2.elb.amazonaws.com"]}
)


async def _no_sleep(_: float) -> None:
    return None


@pytest.fixture
async def fetcher(tmp_path: Path) -> AsyncIterator[Fetcher]:
    async with httpx.AsyncClient(follow_redirects=True) as client:
        yield Fetcher(
            Settings(), client=client, cache=DiskCache(tmp_path, ttl_s=0), sleep=_no_sleep
        )


def _profile(domain: str = "northwind-ai.com") -> StartupProfile:
    return StartupProfile(company_name="Northwind AI", domain=domain, hq_state="WA")


def _mock_site(router: respx.MockRouter) -> None:
    router.get(f"{SITE}/robots.txt").respond(404)
    router.get(f"{SITE}/").respond(200, html=HOMEPAGE)
    router.get(f"{SITE}/subprocessors").respond(200, html=SUBPROCESSORS)
    router.get(url__startswith=SITE).respond(404)
    router.get(LEVER_API).respond(200, json=POSTINGS)


@pytest.mark.parametrize(
    ("domain", "reserved"),
    [
        ("acme.example", True),
        ("acme.invalid", True),
        ("acme.test", True),
        ("example.com", True),
        ("www.example.org", True),
        ("northwind-ai.com", False),
        ("notexample.com", False),
    ],
)
def test_is_reserved(domain: str, reserved: bool) -> None:
    assert is_reserved(domain) is reserved


async def test_live_signals_merge_every_source(
    fetcher: Fetcher, respx_mock: respx.MockRouter
) -> None:
    _mock_site(respx_mock)
    signals = await collect(_profile(), fetcher=fetcher, resolver=AWS_DNS, now=NOW)

    assert signals.data_source is DataSource.LIVE
    assert signals.collected_at == NOW
    assert (signals.ats, signals.ats_board_token) == (ATSPlatform.LEVER, "northwind")
    assert signals.total_open_roles == 3
    assert signals.ai_role_count == 1
    assert [role.title for role in signals.ai_roles] == ["Senior LLM Engineer"]

    competitors = {c.kind: c.confidence for c in signals.competitors}
    # The LLM role (0.6) and the subprocessor page (0.8): 1 - 0.4 * 0.2. The sales role's
    # mention of OpenAI is not read.
    assert competitors == {CompetitorKind.OPENAI: 0.92, CompetitorKind.LANGCHAIN: 0.6}
    assert next(c.kind for c in signals.competitors) is CompetitorKind.OPENAI

    (aws,) = signals.cloud
    assert aws.provider is CloudProvider.AWS
    assert aws.confidence == 0.95  # DNS, a posting and the subprocessor page, capped
    assert signals.primary_cloud is CloudProvider.AWS

    hits = signals.keyword_hits
    assert hits[SignalKeyword.RAG] == 1
    assert hits[SignalKeyword.EVALS] == 1
    assert hits[SignalKeyword.INFERENCE_COST] == 1
    assert hits[SignalKeyword.AGENTS] == 1  # the homepage
    assert hits[SignalKeyword.COMPLIANCE] == 1  # the backend role, not the sales role

    kinds = {e.kind for e in signals.evidence}
    assert kinds == {"job_posting", "web", "dns"}
    assert [e.id for e in signals.evidence] == [
        f"E{i}" for i in range(1, len(signals.evidence) + 1)
    ]
    by_id = {e.id: e for e in signals.evidence}
    langchain = next(c for c in signals.competitors if c.kind is CompetitorKind.LANGCHAIN)
    (cited,) = langchain.evidence_ids
    assert "LangChain" in by_id[cited].snippet
    assert by_id[cited].source_url == "https://jobs.lever.co/northwind/a1"
    assert all(e.observed_at == NOW for e in signals.evidence)


async def test_live_signals_run_through_the_pipeline(
    fetcher: Fetcher, respx_mock: respx.MockRouter
) -> None:
    _mock_site(respx_mock)
    profile = _profile()
    signals = await collect(profile, fetcher=fetcher, resolver=AWS_DNS, now=NOW)
    enriched = StartupProfile.model_validate(
        {**profile.model_dump(), "tech_stack": signals.model_dump()}
    )
    brief, usage = run_pipeline(enriched, MockLLMClient(), generated_at=NOW)
    assert brief.data_source is DataSource.LIVE
    assert usage.est_cost_usd == 0
    assert "ILLUSTRATIVE" not in to_markdown(brief)


async def test_boilerplate_repeated_across_postings_counts_once(
    fetcher: Fetcher, respx_mock: respx.MockRouter
) -> None:
    boilerplate = "Our assistant is built on the OpenAI API."
    postings = [
        {
            "id": f"b{i}",
            "text": f"Software Engineer {i}",
            "hostedUrl": f"https://jobs.lever.co/northwind/b{i}",
            "descriptionPlain": f"{boilerplate}\nRole {i} details.",
        }
        for i in range(3)
    ]
    respx_mock.get(f"{SITE}/robots.txt").respond(404)
    respx_mock.get(url__startswith=SITE).respond(404)
    respx_mock.get(LEVER_API).respond(200, json=postings)
    profile = _profile().model_copy(
        update={"ats_hint": ATSPlatform.LEVER, "ats_board_token": "northwind"}
    )
    signals = await collect(profile, fetcher=fetcher, resolver=FakeResolver({}), now=NOW)
    (openai,) = signals.competitors
    assert openai.confidence == 0.6
    assert signals.total_open_roles == 3


async def test_cdn_fronting_is_reported(fetcher: Fetcher, respx_mock: respx.MockRouter) -> None:
    respx_mock.route().respond(404)
    resolver = FakeResolver({("northwind-ai.com", "CNAME"): ["northwind.cdn.cloudflare.net"]})
    signals = await collect(_profile(), fetcher=fetcher, resolver=resolver, now=NOW)
    assert signals.data_source is DataSource.LIVE  # answers, even empty ones, are live
    assert signals.cloud == []
    assert signals.primary_cloud is CloudProvider.UNKNOWN
    assert any("Cloudflare" in w and "hides the hosting cloud" in w for w in signals.warnings)


async def test_reserved_domain_falls_back_without_network(fetcher: Fetcher) -> None:
    with respx.mock(assert_all_called=False) as router:  # no routes: any request errors
        signals = await collect(
            _profile("lexiconlegal.example"),
            fetcher=fetcher,
            resolver=FakeResolver({}, down=True),
            fallback=mock_signals,
            now=NOW,
        )
    assert not router.calls
    assert signals.data_source is DataSource.MOCK
    assert any("reserved example domain" in w for w in signals.warnings)


@pytest.mark.parametrize(
    ("strict", "fallback"), [(True, mock_signals), (False, None)], ids=["strict", "no-fallback"]
)
async def test_reserved_domain_raises_when_strict_or_without_fallback(
    fetcher: Fetcher, strict: bool, fallback: Fallback | None
) -> None:
    with pytest.raises(CollectionError, match="reserved example domain"):
        await collect(
            _profile("lexiconlegal.example"), fetcher=fetcher, fallback=fallback, strict=strict
        )


async def test_unreachable_target_falls_back_with_reasons(
    fetcher: Fetcher, respx_mock: respx.MockRouter
) -> None:
    respx_mock.route().mock(side_effect=httpx.ConnectError("blocked"))
    signals = await collect(
        _profile(),
        fetcher=fetcher,
        resolver=FakeResolver({}, down=True),
        fallback=mock_signals,
        now=NOW,
    )
    assert signals.data_source is DataSource.MOCK
    assert signals.domain == "northwind-ai.com"
    warnings = " | ".join(signals.warnings)
    assert "No live source could be reached for northwind-ai.com" in warnings
    assert "Website unreachable" in warnings
    assert "DNS unavailable" in warnings


async def test_unreachable_target_raises_when_strict(
    fetcher: Fetcher, respx_mock: respx.MockRouter
) -> None:
    respx_mock.route().mock(side_effect=httpx.ConnectError("blocked"))
    with pytest.raises(CollectionError) as excinfo:
        await collect(
            _profile(),
            fetcher=fetcher,
            resolver=FakeResolver({}, down=True),
            fallback=mock_signals,
            strict=True,
        )
    assert excinfo.value.domain == "northwind-ai.com"
    assert any("Website unreachable" in reason for reason in excinfo.value.reasons)
