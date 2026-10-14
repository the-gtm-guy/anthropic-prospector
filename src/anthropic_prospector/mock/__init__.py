"""Offline data for runs without network access or API keys.

Mock output is always labelled: data_source=mock on every record, fictional companies on
the reserved `.example` TLD, and synthetic evidence marked "[synthetic]".
"""

from datetime import datetime

from anthropic_prospector.mock.fixtures import fixture_domains, fixture_profile, fixture_profiles
from anthropic_prospector.mock.synth import SYNTHETIC_WARNING, synthesize_signals
from anthropic_prospector.models import StartupProfile, TechStackSignals

__all__ = [
    "SYNTHETIC_WARNING",
    "fixture_domains",
    "fixture_profile",
    "fixture_profiles",
    "mock_signals",
    "synthesize_signals",
]


def mock_signals(
    profile: StartupProfile, *, collected_at: datetime | None = None
) -> TechStackSignals:
    """The fixture's signals when `profile` has a fixture, else deterministic synthetic ones."""
    fixture = fixture_profile(profile.domain)
    if fixture is not None and fixture.tech_stack is not None:
        return fixture.tech_stack
    return synthesize_signals(profile, collected_at=collected_at)
