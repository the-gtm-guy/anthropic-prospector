"""Infer which cloud hosts a company's apps from public DNS, conservatively.

* A CNAME into a cloud provider's own namespace (load balancer, Cloud Run, App Service)
  is a hint; the confidence reflects how specific the suffix is.
* A CDN or proxy in front (Cloudflare, Fastly, Vercel, ...) hides the real host, so it is
  reported as "fronted" and yields no provider: unknown, not a guess.
* Google Workspace (MX, SPF, google-site-verification) is email and identity, not GCP,
  and is ignored.
* An Amazon SES SPF include only shows that mail is sent through AWS, so it is a weak hint.
"""

import asyncio
from dataclasses import dataclass
from typing import Final, Protocol
from urllib.parse import quote

import dns.asyncresolver
import dns.exception
import dns.rdtypes.ANY.TXT
import dns.resolver

from anthropic_prospector.models import CloudProvider
from anthropic_prospector.scrapers.http import Fetcher, FetchError

MAX_HOPS: Final = 3
HOST_PREFIXES: Final = ("", "www.", "app.", "api.")
SES_CONFIDENCE: Final = 0.3

# Specific suffixes must precede the generic ".amazonaws.com".
PROVIDER_SUFFIXES: Final[tuple[tuple[str, CloudProvider, float, str], ...]] = (
    (".elb.amazonaws.com", CloudProvider.AWS, 0.85, "an AWS load balancer"),
    (".elasticbeanstalk.com", CloudProvider.AWS, 0.85, "AWS Elastic Beanstalk"),
    (".awsglobalaccelerator.com", CloudProvider.AWS, 0.8, "AWS Global Accelerator"),
    (".amplifyapp.com", CloudProvider.AWS, 0.75, "AWS Amplify"),
    (".amazonaws.com", CloudProvider.AWS, 0.8, "an AWS endpoint"),
    (".cloudfront.net", CloudProvider.AWS, 0.5, "Amazon CloudFront"),
    (".run.app", CloudProvider.GCP, 0.8, "Google Cloud Run"),
    (".appspot.com", CloudProvider.GCP, 0.8, "Google App Engine"),
    ("ghs.googlehosted.com", CloudProvider.GCP, 0.6, "Google-hosted content"),
    (".web.app", CloudProvider.GCP, 0.6, "Firebase Hosting"),
    (".firebaseapp.com", CloudProvider.GCP, 0.6, "Firebase Hosting"),
    (".azurewebsites.net", CloudProvider.AZURE, 0.85, "Azure App Service"),
    (".azurefd.net", CloudProvider.AZURE, 0.85, "Azure Front Door"),
    (".azurecontainerapps.io", CloudProvider.AZURE, 0.85, "Azure Container Apps"),
    (".cloudapp.azure.com", CloudProvider.AZURE, 0.8, "an Azure cloud service"),
    (".cloudapp.net", CloudProvider.AZURE, 0.8, "an Azure cloud service"),
    (".trafficmanager.net", CloudProvider.AZURE, 0.7, "Azure Traffic Manager"),
    (".azureedge.net", CloudProvider.AZURE, 0.6, "Azure CDN"),
)

FRONTING_SUFFIXES: Final[tuple[tuple[str, str], ...]] = (
    (".fastly.net", "Fastly"),
    (".vercel-dns.com", "Vercel"),
    (".vercel.app", "Vercel"),
    (".netlify.app", "Netlify"),
    (".netlify.com", "Netlify"),
    (".akamaiedge.net", "Akamai"),
    (".edgekey.net", "Akamai"),
)

_RDTYPE_CODES: Final = {"CNAME": 5, "A": 1, "AAAA": 28, "TXT": 16, "MX": 15}


class DnsUnavailable(Exception):
    """Resolution itself failed (blocked UDP, timeout, no nameservers), not "no such record"."""


@dataclass(frozen=True)
class CloudHint:
    provider: CloudProvider
    confidence: float
    snippet: str
    host: str


@dataclass(frozen=True)
class DnsReport:
    hints: list[CloudHint]
    fronted_by: list[str]
    warnings: list[str]
    reached: bool = True  # False when no lookup could be answered at all


class Resolver(Protocol):
    async def resolve(self, name: str, rdtype: str) -> list[str]:
        """Records as strings, trailing dots stripped; [] for NXDOMAIN or no answer.
        Raises DnsUnavailable when resolving itself fails."""
        ...


class SystemResolver:
    async def resolve(self, name: str, rdtype: str) -> list[str]:
        try:
            answer = await dns.asyncresolver.resolve(name, rdtype, lifetime=3.0)
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
            return []
        except (
            dns.resolver.NoNameservers,
            dns.exception.Timeout,
            dns.resolver.LifetimeTimeout,
            OSError,
        ) as exc:
            raise DnsUnavailable(f"{name} {rdtype}: {type(exc).__name__}") from exc
        records: list[str] = []
        for rdata in answer:
            if isinstance(rdata, dns.rdtypes.ANY.TXT.TXT):
                records.append(b"".join(rdata.strings).decode("utf-8", errors="replace"))
            else:
                records.append(rdata.to_text().rstrip("."))
        return records


class DohResolver:
    def __init__(self, fetcher: Fetcher) -> None:
        self._fetcher = fetcher

    async def resolve(self, name: str, rdtype: str) -> list[str]:
        url = f"https://dns.google/resolve?name={quote(name, safe='')}&type={rdtype}"
        try:
            status, data = await self._fetcher.get_json(url)
        except FetchError as exc:
            raise DnsUnavailable(str(exc)) from exc
        if status != 200 or not isinstance(data, dict):
            raise DnsUnavailable(f"{url}: HTTP {status}")
        dns_status = data.get("Status")
        if dns_status == 3:
            return []
        if dns_status != 0:
            raise DnsUnavailable(f"{url}: DNS status {dns_status}")
        code = _RDTYPE_CODES.get(rdtype)
        records: list[str] = []
        for answer in data.get("Answer") or []:
            if not isinstance(answer, dict) or answer.get("type") != code:
                continue
            value = str(answer.get("data", "")).rstrip(".")
            if rdtype == "TXT":
                value = value.strip('"')
            records.append(value)
        return records


class FallbackResolver:
    """Uses `primary` until it raises DnsUnavailable, then `secondary` for good."""

    def __init__(self, primary: Resolver, secondary: Resolver) -> None:
        self._primary = primary
        self._secondary = secondary
        self._use_secondary = False

    async def resolve(self, name: str, rdtype: str) -> list[str]:
        if not self._use_secondary:
            try:
                return await self._primary.resolve(name, rdtype)
            except DnsUnavailable:
                self._use_secondary = True
        return await self._secondary.resolve(name, rdtype)


def _classify(host: str, target: str) -> tuple[CloudHint | None, str | None]:
    lowered = target.lower()
    for suffix, provider, confidence, description in PROVIDER_SUFFIXES:
        if lowered.endswith(suffix):
            snippet = f"{host} is a CNAME for {description} ({target})."
            return CloudHint(provider, confidence, snippet, host), None
    if "cloudflare" in lowered:
        return None, "Cloudflare"
    for suffix, name in FRONTING_SUFFIXES:
        if lowered.endswith(suffix):
            return None, name
    return None, None


async def inspect_domain(domain: str, resolver: Resolver) -> DnsReport:
    hints: dict[tuple[str, CloudProvider], CloudHint] = {}
    fronted_by: list[str] = []
    warnings: list[str] = []

    def add(hint: CloudHint) -> None:
        key = (hint.host, hint.provider)
        if key not in hints or hints[key].confidence < hint.confidence:
            hints[key] = hint

    async def walk(host: str) -> None:
        current = host
        for _ in range(MAX_HOPS):
            targets = await resolver.resolve(current, "CNAME")
            if not targets:
                return
            current = targets[0]
            hint, front = _classify(host, current)
            if hint is not None:
                add(hint)
            if front is not None and front not in fronted_by:
                fronted_by.append(front)

    async def spf() -> None:
        for record in await resolver.resolve(domain, "TXT"):
            lowered = record.lower()
            if lowered.startswith("v=spf1") and "include:amazonses.com" in lowered:
                snippet = f"{domain} sends email through Amazon SES (SPF)."
                add(CloudHint(CloudProvider.AWS, SES_CONFIDENCE, snippet, domain))

    hosts = [f"{prefix}{domain}" for prefix in HOST_PREFIXES]
    results = await asyncio.gather(*(walk(host) for host in hosts), spf(), return_exceptions=True)
    failed = [r for r in results if isinstance(r, DnsUnavailable)]
    for result in results:
        if isinstance(result, BaseException) and not isinstance(result, DnsUnavailable):
            raise result
    if len(failed) == len(results):
        warning = f"DNS unavailable: could not resolve any record for {domain}."
        return DnsReport([], [], [warning], reached=False)
    for name, result in zip([*hosts, f"{domain} (TXT)"], results, strict=True):
        if isinstance(result, DnsUnavailable):
            warnings.append(f"DNS lookup failed for {name}.")
    return DnsReport(list(hints.values()), fronted_by, warnings)
