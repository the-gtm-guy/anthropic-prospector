"""Targets CSV loading: the shipped targets.csv, and row-level error isolation."""

from pathlib import Path

import pytest

from anthropic_prospector.mock import fixture_domains
from anthropic_prospector.models import TERRITORY_STATES, FundingStage
from anthropic_prospector.targets import (
    TargetFileError,
    load_targets,
    parse_funding_stage,
    parse_money,
    parse_targets,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_shipped_targets_load_cleanly() -> None:
    batch = load_targets(REPO_ROOT / "targets.csv")
    assert batch.errors == []
    assert batch.warnings == []
    assert len(batch.profiles) == 26
    domains = {p.domain for p in batch.profiles}
    assert all(domain.endswith(".example") for domain in domains), "targets are fictional"
    assert set(fixture_domains()) <= domains
    assert {p.hq_state for p in batch.profiles if p.in_territory} == TERRITORY_STATES
    assert sum(not p.in_territory for p in batch.profiles) == 2
    assert any(p.contacts for p in batch.profiles)


def test_bad_rows_fail_alone_with_line_numbers() -> None:
    batch = parse_targets(
        "company_name,domain,hq_state,employee_count\n"
        "Good Co,good.example,CA,10\n"
        "Bad Domain,not a domain,CA,10\n"
        "Bad State,badstate.example,Ontario,10\n"
        "Bad Size,badsize.example,WA,lots\n"
        'Also Good,https://www.alsogood.example/about,Washington,"1,200"\n'
    )
    assert [(p.domain, p.hq_state) for p in batch.profiles] == [
        ("good.example", "CA"),
        ("alsogood.example", "WA"),
    ]
    assert batch.profiles[1].employee_count == 1200
    assert [(e.line, e.message.split(":")[0]) for e in batch.errors] == [
        (3, "domain"),
        (4, "hq_state"),
        (5, "employee_count"),
    ]
    assert batch.errors[0].domain == "not a domain"


def test_duplicate_domains_keep_the_first_row() -> None:
    batch = parse_targets(
        "company_name,domain,hq_state\nAcme,acme.example,CA\nAcme Again,https://www.ACME.example,CA\n"
    )
    assert [p.company_name for p in batch.profiles] == ["Acme"]
    assert batch.errors[0].line == 3
    assert "duplicate of line 2" in batch.errors[0].message


def test_headers_and_values_are_normalized() -> None:
    batch = parse_targets(
        "﻿Company Name, Domain ,HQ State,Funding Stage,Total Funding (USD),ATS Hint\n"
        "\n"
        "Acme,acme.example,california,Series C+,$1.2B,Greenhouse\n"
        ",,,,,\n"
    )
    assert batch.errors == []
    (profile,) = batch.profiles
    assert profile.hq_state == "CA"
    assert profile.funding_stage is FundingStage.SERIES_C_PLUS
    assert profile.total_funding_usd == 1_200_000_000
    assert profile.ats_hint == "greenhouse"


def test_contacts_need_a_name_and_title() -> None:
    batch = parse_targets(
        "company_name,domain,hq_state,contact_name,contact_title\n"
        "Acme,acme.example,CA,Dana Cho,CTO\n"
        "Beta,beta.example,CA,Sam Lee,\n"
    )
    assert batch.profiles[0].contacts[0].title == "CTO"
    assert batch.errors[0].line == 3
    assert batch.errors[0].message.startswith("contact_title:")


def test_unquoted_commas_are_reported_not_misread() -> None:
    batch = parse_targets("company_name,domain,hq_state\nAcme, Inc.,acme.example,CA\n")
    assert batch.profiles == []
    assert "more cell(s) than the header" in batch.errors[0].message


def test_line_numbers_count_physical_lines() -> None:
    batch = parse_targets(
        'company_name,domain,hq_state,description\nAcme,acme.example,CA,"Two\nlines"\n'
        "Bad,bad domain,CA,x\n"
    )
    assert batch.errors[0].line == 4


def test_unknown_columns_are_ignored_with_a_warning() -> None:
    batch = parse_targets("company_name,domain,hq_state,arr\nAcme,acme.example,CA,5M\n")
    assert len(batch.profiles) == 1
    assert batch.warnings == ["ignored unknown column(s): arr"]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", "is empty"),
        ("company_name,domain\nAcme,acme.example\n", "missing required column"),
    ],
)
def test_unusable_files_raise(text: str, message: str) -> None:
    with pytest.raises(TargetFileError, match=message):
        parse_targets(text)


def test_unreadable_files_raise(tmp_path: Path) -> None:
    with pytest.raises(TargetFileError, match="cannot read"):
        load_targets(tmp_path / "missing.csv")
    with pytest.raises(TargetFileError, match="cannot read"):
        load_targets(tmp_path)  # a directory


@pytest.mark.parametrize(
    ("text", "dollars"),
    [
        ("48000000", 48_000_000),
        ("48,000,000", 48_000_000),
        ("$45M", 45_000_000),
        ("1.2B", 1_200_000_000),
        ("USD 750k", 750_000),
    ],
)
def test_parse_money(text: str, dollars: int) -> None:
    assert parse_money(text) == dollars


@pytest.mark.parametrize("text", ["lots", "$", "45 million", "1.2.3M"])
def test_parse_money_rejects(text: str) -> None:
    with pytest.raises(ValueError, match="not an amount"):
        parse_money(text)


@pytest.mark.parametrize(
    ("text", "stage"),
    [
        ("Pre-seed", FundingStage.PRE_SEED),
        ("preseed", FundingStage.PRE_SEED),
        ("Seed", FundingStage.SEED),
        ("Series A", FundingStage.SERIES_A),
        ("series_b", FundingStage.SERIES_B),
        ("Series C+", FundingStage.SERIES_C_PLUS),
        ("Series D", FundingStage.SERIES_C_PLUS),
        ("unknown", FundingStage.UNKNOWN),
    ],
)
def test_parse_funding_stage(text: str, stage: FundingStage) -> None:
    assert parse_funding_stage(text) is stage


def test_parse_funding_stage_rejects() -> None:
    with pytest.raises(ValueError, match="funding_stage"):
        parse_funding_stage("Bootstrapped")
