"""Load a targets CSV into StartupProfiles.

One bad row never sinks the file: a row that fails validation becomes a RowError with its
line number, and the remaining rows still load. Only a file that cannot be read as a
target list at all (unreadable, empty, or missing a required column) raises
TargetFileError.

Headers are matched loosely ("HQ State" == "hq_state"). Values are cleaned the way CRM
exports need: "Series C+" or "series_c_plus", "$1.2B" or "1200000000", "1,200" employees.
"""

import csv
import io
import re
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

from pydantic import ValidationError

from anthropic_prospector.models import FundingStage, RowError, StartupProfile, TargetBatch

REQUIRED_COLUMNS: Final = ("company_name", "domain", "hq_state")
PROFILE_COLUMNS: Final = (
    *REQUIRED_COLUMNS,
    "website_url",
    "hq_city",
    "description",
    "vertical",
    "employee_count",
    "funding_stage",
    "total_funding_usd",
    "last_round_date",
    "ats_hint",
    "ats_board_token",
)
CONTACT_COLUMNS: Final = {
    "contact_name": "name",
    "contact_title": "title",
    "contact_linkedin": "linkedin_url",
}
KNOWN_COLUMNS: Final = frozenset((*PROFILE_COLUMNS, *CONTACT_COLUMNS))

_AMOUNT = re.compile(r"^\$?(\d+(?:\.\d+)?)([kmb])?$")
_SCALE: Final = {"": 1, "k": 10**3, "m": 10**6, "b": 10**9}
_SERIES = re.compile(r"^series_([a-z])(?:_plus)?$")


class TargetFileError(Exception):
    """The file cannot be read as a target list at all."""


def load_targets(path: Path) -> TargetBatch:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise TargetFileError(f"cannot read {path}: {exc}") from exc
    return parse_targets(text, source=str(path))


def parse_targets(text: str, *, source: str = "<targets>") -> TargetBatch:
    reader = csv.DictReader(io.StringIO(text.removeprefix("﻿"), newline=""))
    if not reader.fieldnames:
        raise TargetFileError(f"{source} is empty")
    keys = {name: _column_key(name) for name in reader.fieldnames}
    if missing := [c for c in REQUIRED_COLUMNS if c not in keys.values()]:
        raise TargetFileError(f"{source} is missing required column(s): {', '.join(missing)}")
    warnings = []
    if unknown := sorted({k for k in keys.values() if k and k not in KNOWN_COLUMNS}):
        warnings.append(f"ignored unknown column(s): {', '.join(unknown)}")

    profiles: list[StartupProfile] = []
    errors: list[RowError] = []
    first_seen: dict[str, int] = {}
    try:
        for raw in reader:
            line = reader.line_num
            extra = raw.pop(None, None)  # cells beyond the header
            row = {keys[name]: (value or "").strip() for name, value in raw.items()}
            if not any(row.values()) and not extra:
                continue
            domain = row.get("domain") or None
            if extra:
                message = f"{len(extra)} more cell(s) than the header; check for unquoted commas"
                errors.append(RowError(line=line, domain=domain, message=message))
                continue
            try:
                profile = StartupProfile.model_validate(_profile_data(row))
            except ValueError as exc:  # includes ValidationError
                errors.append(RowError(line=line, domain=domain, message=_describe(exc)))
                continue
            if (first := first_seen.get(profile.domain)) is not None:
                message = f"duplicate of line {first} ({profile.domain}); skipped"
                errors.append(RowError(line=line, domain=domain, message=message))
                continue
            first_seen[profile.domain] = line
            profiles.append(profile)
    except csv.Error as exc:
        raise TargetFileError(f"{source}, line {reader.line_num}: {exc}") from exc
    return TargetBatch(source=source, profiles=profiles, errors=errors, warnings=warnings)


def parse_money(text: str) -> int:
    """'$1.2B', '45M', '45,000,000' or 'USD 750k' -> whole dollars."""
    cleaned = re.sub(r"[\s,_]", "", text.lower()).removeprefix("usd")
    if (match := _AMOUNT.match(cleaned)) is None:
        raise ValueError(f"total_funding_usd: not an amount: {text!r}")
    return int(Decimal(match[1]) * _SCALE[match[2] or ""])


def parse_funding_stage(text: str) -> FundingStage:
    """'Pre-seed', 'Seed', 'Series A', 'Series C+', 'Series D' (counts as C+), or enum values."""
    key = _column_key(text)
    if key in {stage.value for stage in FundingStage}:
        return FundingStage(key)
    if key == "preseed":
        return FundingStage.PRE_SEED
    if match := _SERIES.match(key):
        series = {"a": FundingStage.SERIES_A, "b": FundingStage.SERIES_B}
        return series.get(match[1], FundingStage.SERIES_C_PLUS)
    raise ValueError(f"funding_stage: expected Pre-seed, Seed or Series A/B/C+, got {text!r}")


def _column_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")


def _profile_data(row: dict[str, str]) -> dict[str, Any]:
    data: dict[str, Any] = {column: row[column] for column in PROFILE_COLUMNS if row.get(column)}
    if "employee_count" in data:
        data["employee_count"] = data["employee_count"].replace(",", "")
    if "total_funding_usd" in data:
        data["total_funding_usd"] = parse_money(data["total_funding_usd"])
    if "funding_stage" in data:
        data["funding_stage"] = parse_funding_stage(data["funding_stage"])
    if "ats_hint" in data:
        data["ats_hint"] = data["ats_hint"].lower()
    if contact := {field: row[col] for col, field in CONTACT_COLUMNS.items() if row.get(col)}:
        data["contacts"] = [contact]
    return data


def _describe(exc: ValueError) -> str:
    if not isinstance(exc, ValidationError):
        return str(exc)
    parts = []
    for error in exc.errors():
        message = error["msg"].removeprefix("Value error, ")
        column = _column_for(error["loc"])
        parts.append(f"{column}: {message}" if column else message)
    return "; ".join(parts)


def _column_for(loc: tuple[int | str, ...]) -> str:
    """Name the CSV column a validation error came from."""
    if not loc:
        return ""
    if loc[0] == "contacts":
        field = str(loc[-1])
        return next((col for col, f in CONTACT_COLUMNS.items() if f == field), "contact")
    return str(loc[0])
