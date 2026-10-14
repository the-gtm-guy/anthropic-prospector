"""Phase 2 gate for the mock layer: fixtures validate and cover the scenario matrix,
mock data never links to a real site, and synthetic signals are deterministic."""

import os
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import pytest

from anthropic_prospector.mock import (
    SYNTHETIC_WARNING,
    fixture_domains,
    fixture_profile,
    fixture_profiles,
    mock_signals,
    synthesize_signals,
)
from anthropic_prospector.mock.synth import _KEYWORD_PHRASES
from anthropic_prospector.models import (
    TERRITORY_STATES,
    ATSPlatform,
    CloudProvider,
    CompetitorKind,
    DataSource,
    SignalKeyword,
    StartupProfile,
    TechStackSignals,
)

WHEN = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
FIXTURES = fixture_profiles()


def _signals(profile: StartupProfile) -> TechStackSignals:
    assert profile.tech_stack is not None, profile.domain
    return profile.tech_stack


def _profile(domain: str, **overrides: Any) -> StartupProfile:
    data: dict[str, Any] = {"company_name": "Sample Startup", "domain": domain, "hq_state": "CA"}
    return StartupProfile.model_validate(data | overrides)


def _hosts(signals: TechStackSignals) -> set[str]:
    urls = [e.source_url for e in signals.evidence if e.source_url]
    urls += [posting.url for posting in signals.ai_roles]
    return {urlsplit(url).hostname or "" for url in urls}


def _has(signals: TechStackSignals, kind: CompetitorKind) -> bool:
    return any(c.kind is kind for c in signals.competitors)


# --------------------------------------------------------------------------- fixtures


def test_fixtures_are_valid_fictional_mock_data() -> None:
    assert len(FIXTURES) == 12
    assert fixture_domains() == sorted(p.domain for p in FIXTURES)
    for profile in FIXTURES:
        assert profile.domain.endswith(".example"), "fixtures are fictional (RFC 2606)"
        assert _signals(profile).data_source is DataSource.MOCK
        assert profile.contacts == [], "contacts only ever come from the user's CSV"


def test_mock_data_never_links_to_real_sites() -> None:
    for profile in FIXTURES:
        hosts = _hosts(_signals(profile)) | {urlsplit(profile.website_url).hostname or ""}
        assert all(host.endswith(".example") for host in hosts), (profile.domain, hosts)
    synthetic = synthesize_signals(_profile("real-company.com"), collected_at=WHEN)
    assert all(host.endswith(".invalid") for host in _hosts(synthetic))


SCENARIOS: dict[str, Callable[[TechStackSignals], bool]] = {
    "OpenAI incumbent on AWS": lambda s: (
        _has(s, CompetitorKind.OPENAI) and s.primary_cloud is CloudProvider.AWS
    ),
    "LangChain on GCP": lambda s: (
        _has(s, CompetitorKind.LANGCHAIN) and s.primary_cloud is CloudProvider.GCP
    ),
    "self-hosted vLLM": lambda s: _has(s, CompetitorKind.VLLM),
    "Azure OpenAI on Azure": lambda s: (
        _has(s, CompetitorKind.AZURE_OPENAI) and s.primary_cloud is CloudProvider.AZURE
    ),
    "already a Claude user": lambda s: _has(s, CompetitorKind.ANTHROPIC_EXISTING),
    "no AI signal": lambda s: s.ai_role_count == 0 and not s.competitors and not s.keyword_hits,
    "multi-cloud": lambda s: s.primary_cloud is CloudProvider.MULTI,
    "hosting hidden behind a CDN": lambda s: s.primary_cloud is CloudProvider.UNKNOWN,
    "Greenhouse board": lambda s: s.ats is ATSPlatform.GREENHOUSE,
    "Lever board": lambda s: s.ats is ATSPlatform.LEVER,
    "Ashby board": lambda s: s.ats is ATSPlatform.ASHBY,
}


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_fixtures_cover_scenario(scenario: str) -> None:
    assert any(SCENARIOS[scenario](_signals(p)) for p in FIXTURES)


def test_fixtures_cover_the_territory_and_one_account_outside_it() -> None:
    assert {p.hq_state for p in FIXTURES if p.in_territory} == TERRITORY_STATES
    assert any(not p.in_territory for p in FIXTURES)


def test_fixture_lookups_return_independent_copies() -> None:
    first = fixture_profile("lexiconlegal.example")
    assert first is not None
    first.hq_city = "Mutated"
    again = fixture_profile("lexiconlegal.example")
    assert again is not None
    assert again.hq_city == "San Francisco"
    assert fixture_profile("not-a-fixture.example") is None


# --------------------------------------------------------------------------- synthetic


def test_synthetic_signals_are_deterministic_in_process() -> None:
    first = synthesize_signals(_profile("sample-startup.com"), collected_at=WHEN)
    second = synthesize_signals(_profile("sample-startup.com"), collected_at=WHEN)
    assert first == second


PROBE = """
from datetime import UTC, datetime
from anthropic_prospector.mock import synthesize_signals
from anthropic_prospector.models import StartupProfile
profile = StartupProfile.model_validate(
    {"company_name": "Sample Startup", "domain": "sample-startup.com", "hq_state": "CA"}
)
when = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
print(synthesize_signals(profile, collected_at=when).model_dump_json())
"""


@pytest.mark.parametrize("hash_seed", ["0", "4242"])
def test_synthetic_signals_are_deterministic_across_processes(hash_seed: str) -> None:
    # A different PYTHONHASHSEED per process would expose any use of hash() or set order.
    env = {**os.environ, "PYTHONHASHSEED": hash_seed}
    proc = subprocess.run(
        [sys.executable, "-c", PROBE], capture_output=True, text=True, check=True, env=env
    )
    expected = synthesize_signals(_profile("sample-startup.com"), collected_at=WHEN)
    assert proc.stdout.strip() == expected.model_dump_json()


def test_synthetic_signals_are_labelled_and_varied() -> None:
    outputs = [
        synthesize_signals(_profile(f"startup-{n}.com"), collected_at=WHEN) for n in range(100)
    ]
    for signals in outputs:
        assert signals.data_source is DataSource.MOCK
        assert signals.warnings == [SYNTHETIC_WARNING]
        assert all(e.kind == "mock" for e in signals.evidence)
        assert all(e.snippet.startswith("[synthetic] ") for e in signals.evidence)
    assert len({s.model_dump_json(exclude={"domain"}) for s in outputs}) > 90
    assert any(s.ai_role_count == 0 for s in outputs)
    assert any(s.primary_cloud is CloudProvider.MULTI for s in outputs)
    assert any(s.primary_cloud is CloudProvider.UNKNOWN for s in outputs)
    assert any(_has(s, CompetitorKind.AZURE_OPENAI) for s in outputs)


def test_synthetic_keywords_cite_synthetic_evidence() -> None:
    assert set(_KEYWORD_PHRASES) == set(SignalKeyword), "every keyword needs a phrase"
    signals = synthesize_signals(_profile("sample-startup.com"), collected_at=WHEN)
    assert set(signals.keyword_evidence) == set(signals.keyword_hits)
    by_id = {e.id: e for e in signals.evidence}
    for ids in signals.keyword_evidence.values():
        assert all(by_id[i].snippet.startswith("[synthetic] ") for i in ids)


def test_synthetic_signals_respect_the_profile() -> None:
    profile = _profile(
        "sample-startup.com", ats_hint="ashby", ats_board_token="sample", employee_count=10
    )
    signals = synthesize_signals(profile, collected_at=WHEN)
    assert signals.ats is ATSPlatform.ASHBY
    assert signals.ats_board_token == "sample"
    assert signals.total_open_roles <= 2  # at most 15% of a 10-person company


def test_mock_signals_prefer_fixtures() -> None:
    fixture = fixture_profile("quartzdev.example")
    assert fixture is not None
    assert mock_signals(_profile("quartzdev.example")) == fixture.tech_stack
    synthetic = mock_signals(_profile("sample-startup.com"), collected_at=WHEN)
    assert synthetic.warnings == [SYNTHETIC_WARNING]
