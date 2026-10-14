from pathlib import Path

import httpx
import pytest
import respx

from anthropic_prospector.config import Settings
from anthropic_prospector.models import CloudProvider
from anthropic_prospector.scrapers.dns_intel import (
    DnsUnavailable,
    DohResolver,
    FallbackResolver,
    Resolver,
    inspect_domain,
)
from anthropic_prospector.scrapers.http import DiskCache, Fetcher


class FakeResolver:
    def __init__(self, records: dict[tuple[str, str], list[str]], *, down: bool = False) -> None:
        self.records = records
        self.down = down
        self.calls = 0

    async def resolve(self, name: str, rdtype: str) -> list[str]:
        self.calls += 1
        if self.down:
            raise DnsUnavailable(name)
        return self.records.get((name, rdtype), [])


async def no_sleep(_: float) -> None:
    return None


@pytest.mark.parametrize(
    ("target", "provider", "confidence", "description"),
    [
        ("x.us-east-1.elb.amazonaws.com", CloudProvider.AWS, 0.85, "an AWS load balancer"),
        ("a.s3.amazonaws.com", CloudProvider.AWS, 0.8, "an AWS endpoint"),
        ("x.cloudfront.net", CloudProvider.AWS, 0.5, "Amazon CloudFront"),
        ("svc-abc.a.run.app", CloudProvider.GCP, 0.8, "Google Cloud Run"),
        ("ghs.googlehosted.com", CloudProvider.GCP, 0.6, "Google-hosted content"),
        ("acme.web.app", CloudProvider.GCP, 0.6, "Firebase Hosting"),
        ("acme.AzureWebsites.net", CloudProvider.AZURE, 0.85, "Azure App Service"),
        ("acme.trafficmanager.net", CloudProvider.AZURE, 0.7, "Azure Traffic Manager"),
        ("acme.azureedge.net", CloudProvider.AZURE, 0.6, "Azure CDN"),
    ],
)
async def test_provider_classification(
    target: str, provider: CloudProvider, confidence: float, description: str
) -> None:
    resolver = FakeResolver({("app.acme.com", "CNAME"): [target]})
    report = await inspect_domain("acme.com", resolver)
    assert len(report.hints) == 1
    hint = report.hints[0]
    assert hint.provider is provider
    assert hint.confidence == confidence
    assert hint.host == "app.acme.com"
    assert hint.snippet == f"app.acme.com is a CNAME for {description} ({target})."
    assert report.warnings == []


async def test_follows_two_hop_chain() -> None:
    resolver = FakeResolver(
        {
            ("www.acme.com", "CNAME"): ["x.cloudfront.net"],
            ("x.cloudfront.net", "CNAME"): ["lb.eu-west-1.elb.amazonaws.com"],
        }
    )
    report = await inspect_domain("acme.com", resolver)
    # CloudFront (0.5) and the ELB behind it (0.85) collapse to the best AWS hint.
    assert [(h.host, h.confidence) for h in report.hints] == [("www.acme.com", 0.85)]


async def test_cloudflare_fronting_gives_no_hints() -> None:
    resolver = FakeResolver({("acme.com", "CNAME"): ["acme.com.cdn.cloudflare.net"]})
    report = await inspect_domain("acme.com", resolver)
    assert report.hints == []
    assert report.fronted_by == ["Cloudflare"]


async def test_ses_spf_is_weak_aws_hint() -> None:
    resolver = FakeResolver({("acme.com", "TXT"): ["v=spf1 include:amazonses.com ~all"]})
    report = await inspect_domain("acme.com", resolver)
    assert len(report.hints) == 1
    hint = report.hints[0]
    assert hint.provider is CloudProvider.AWS
    assert hint.confidence == 0.3
    assert hint.snippet == "acme.com sends email through Amazon SES (SPF)."


async def test_google_workspace_is_not_gcp() -> None:
    resolver = FakeResolver(
        {
            ("acme.com", "TXT"): [
                "v=spf1 include:_spf.google.com ~all",
                "google-site-verification=abc",
            ],
            ("acme.com", "MX"): ["1 aspmx.l.google.com"],
        }
    )
    report = await inspect_domain("acme.com", resolver)
    assert report.hints == []


async def test_hints_are_deduplicated() -> None:
    resolver = FakeResolver(
        {
            ("app.acme.com", "CNAME"): ["x.cloudfront.net"],
            ("x.cloudfront.net", "CNAME"): ["y.cloudfront.net"],
        }
    )
    report = await inspect_domain("acme.com", resolver)
    assert len(report.hints) == 1


async def test_all_unavailable_warns() -> None:
    report = await inspect_domain("acme.com", FakeResolver({}, down=True))
    assert report.hints == []
    assert len(report.warnings) == 1
    assert report.warnings[0].startswith("DNS unavailable")


@pytest.fixture
def fetcher(tmp_path: Path) -> Fetcher:
    return Fetcher(Settings(), cache=DiskCache(tmp_path, ttl_s=0), sleep=no_sleep)


@respx.mock
async def test_doh_parses_and_filters(fetcher: Fetcher) -> None:
    respx.get("https://dns.google/resolve").mock(
        return_value=httpx.Response(
            200,
            json={
                "Status": 0,
                "Answer": [
                    {"name": "app.acme.com.", "type": 5, "data": "x.elb.amazonaws.com."},
                    {"name": "x.elb.amazonaws.com.", "type": 1, "data": "1.2.3.4"},
                ],
            },
        )
    )
    assert await DohResolver(fetcher).resolve("app.acme.com", "CNAME") == ["x.elb.amazonaws.com"]


@respx.mock
async def test_doh_nxdomain(fetcher: Fetcher) -> None:
    respx.get("https://dns.google/resolve").mock(
        return_value=httpx.Response(200, json={"Status": 3})
    )
    assert await DohResolver(fetcher).resolve("nope.acme.com", "CNAME") == []


@respx.mock
async def test_doh_http_error_is_unavailable(fetcher: Fetcher) -> None:
    respx.get("https://dns.google/resolve").mock(return_value=httpx.Response(500))
    with pytest.raises(DnsUnavailable):
        await DohResolver(fetcher).resolve("acme.com", "CNAME")


async def test_fallback_is_sticky() -> None:
    primary = FakeResolver({}, down=True)
    secondary = FakeResolver({("a.com", "A"): ["1.1.1.1"]})
    resolver: Resolver = FallbackResolver(primary, secondary)
    assert await resolver.resolve("a.com", "A") == ["1.1.1.1"]
    assert await resolver.resolve("a.com", "A") == ["1.1.1.1"]
    assert primary.calls == 1
    assert secondary.calls == 2
