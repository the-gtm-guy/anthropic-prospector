"""Hand-curated fixture companies (mock/data/*.json), one file per company.

Every company is fictional and lives on the reserved `.example` TLD (RFC 2606), so mock
data can never describe, or link to, a real organization. Each file is a StartupProfile
with its tech_stack filled in, validated by the same contract as live data.
"""

from collections.abc import Mapping
from functools import cache
from importlib.resources import files
from types import MappingProxyType

from anthropic_prospector.models import StartupProfile

_DATA = files("anthropic_prospector.mock") / "data"


@cache
def _load() -> Mapping[str, StartupProfile]:
    profiles: dict[str, StartupProfile] = {}
    for resource in sorted(_DATA.iterdir(), key=lambda r: r.name):
        if not resource.name.endswith(".json"):
            continue
        profile = StartupProfile.model_validate_json(resource.read_text(encoding="utf-8"))
        if profile.domain in profiles:
            raise ValueError(f"two fixtures for {profile.domain} (second: {resource.name})")
        profiles[profile.domain] = profile
    return MappingProxyType(profiles)


def fixture_domains() -> list[str]:
    return sorted(_load())


def fixture_profile(domain: str) -> StartupProfile | None:
    """The fixture for a normalized `domain`, or None. Returns a copy that is safe to mutate."""
    profile = _load().get(domain)
    return None if profile is None else profile.model_copy(deep=True)


def fixture_profiles() -> list[StartupProfile]:
    return [profile.model_copy(deep=True) for _, profile in sorted(_load().items())]
