import csv
import json
import subprocess
import sys
from importlib.metadata import entry_points
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from anthropic_prospector import __version__
from anthropic_prospector.cli import app
from anthropic_prospector.service import CHECKPOINT_NAME, RANKED_COLUMNS, RANKED_NAME

runner = CliRunner()


def test_help_runs() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "MEDDPICC" in result.output


def test_version_flag() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == f"anthropic-prospector {__version__}"


def test_console_script_is_registered() -> None:
    (script,) = entry_points(group="console_scripts", name="prospector")
    assert script.value == "anthropic_prospector.cli:app"


def test_module_entry_point() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "anthropic_prospector", "--version"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert __version__ in proc.stdout


TARGETS = Path(__file__).resolve().parents[1] / "targets.csv"
ENV = {"COLUMNS": "120"}
HEADER = TARGETS.read_text().splitlines()[0]


def invoke(*args: object, env: dict[str, str] | None = None) -> Result:
    return runner.invoke(app, [str(a) for a in args], env={**ENV, **(env or {})})


def write_csv(path: Path, *rows: str) -> Path:
    path.write_text("\n".join([HEADER, *rows]) + "\n")
    return path


def read_ranked(out_dir: Path) -> list[dict[str, str]]:
    with (out_dir / RANKED_NAME).open(newline="") as handle:
        return list(csv.DictReader(handle))


def test_qualify_scorecard() -> None:
    result = invoke("qualify", "lexiconlegal.example", "--offline")
    assert result.exit_code == 0
    for text in ("MEDDPICC scorecard", "Lexicon Legal AI", "PURSUE", "DATA MOCK"):
        assert text in result.stdout


def test_qualify_export_brief_overwrite_rules(tmp_path: Path) -> None:
    briefs = tmp_path / "briefs"
    args = ("qualify", "lexiconlegal.example", "--offline", "--export-brief", briefs)
    assert invoke(*args).exit_code == 0
    brief = briefs / "lexiconlegal-example.md"
    assert "ILLUSTRATIVE" in brief.read_text()
    before = brief.stat().st_mtime_ns
    again = invoke(*args)
    assert again.exit_code == 2
    assert "already exists" in again.stderr
    assert brief.stat().st_mtime_ns == before
    assert invoke(*args, "--force").exit_code == 0


def test_qualify_export_brief_json_file(tmp_path: Path) -> None:
    target = tmp_path / "b.json"
    result = invoke("qualify", "lexiconlegal.example", "--offline", "--export-brief", target)
    assert result.exit_code == 0
    assert "scorecard" in json.loads(target.read_text())


def test_qualify_export_format_conflict(tmp_path: Path) -> None:
    result = invoke(
        "qualify",
        "lexiconlegal.example",
        "--offline",
        "--export-brief",
        tmp_path / "b.md",
        "--format",
        "json",
    )
    assert result.exit_code == 2


def test_run_report() -> None:
    result = invoke("run", "quartzdev.example", "--offline")
    assert result.exit_code == 0
    for text in ("Anthropic wedges", "Outbound brief", "Quartz DevTools"):
        assert text in result.stdout


def test_run_json() -> None:
    result = invoke("run", "quartzdev.example", "--offline", "--json")
    assert result.exit_code == 0
    assert {"brief", "company_name", "domain", "errors"} <= json.loads(result.stdout).keys()


def test_unknown_domain_needs_state() -> None:
    result = invoke("run", "unknown-co.com", "--offline")
    assert result.exit_code == 2
    assert "--state" in result.stderr


def test_unknown_domain_with_name_and_state() -> None:
    result = invoke("run", "unknown-co.com", "--offline", "--state", "WA", "--name", "Unknown Co")
    assert result.exit_code == 0
    assert "Unknown Co" in result.stdout


def test_targets_file_markup_is_literal(tmp_path: Path) -> None:
    csv_path = write_csv(tmp_path / "t.csv", "Evil [bold]Corp[/bold],evilcorp.com,,CA" + "," * 10)
    result = invoke("qualify", "evilcorp.com", "--offline", "--targets", csv_path)
    assert result.exit_code == 0
    assert "Evil [bold]Corp[/bold]" in result.stdout


def test_batch_full(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = invoke("territory-batch", TARGETS, "--offline", "--out-dir", out)
    assert result.exit_code == 0
    with (out / RANKED_NAME).open(newline="") as handle:
        assert next(csv.reader(handle)) == list(RANKED_COLUMNS)
    rows = read_ranked(out)
    assert [int(r["rank"]) for r in rows] == list(range(1, 27))
    assert len((out / CHECKPOINT_NAME).read_text().splitlines()) == 26
    assert "Ranked accounts" in result.stdout
    assert "26 shown of 26" in result.stdout


def test_batch_states_and_top(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = invoke(
        "territory-batch", TARGETS, "--offline", "--out-dir", out, "--states", "CA,wa", "--top", 3
    )
    assert result.exit_code == 0
    assert {r["hq_state"] for r in read_ranked(out)} <= {"CA", "WA"}
    assert len(list((out / "briefs").iterdir())) == 3
    assert "3 shown of" in result.stdout


def test_batch_resume(tmp_path: Path) -> None:
    args = ("territory-batch", TARGETS, "--offline", "--out-dir", tmp_path / "out")
    assert invoke(*args).exit_code == 0
    second = invoke(*args, "--resume")
    assert second.exit_code == 0
    assert "Resumed 26" in second.stdout


def test_batch_min_tier(tmp_path: Path) -> None:
    result = invoke(
        "territory-batch", TARGETS, "--offline", "--out-dir", tmp_path / "out", "--min-tier", "A"
    )
    assert result.exit_code == 0
    assert invoke("territory-batch", TARGETS, "--offline", "--min-tier", "Z").exit_code == 2


def test_batch_bad_states(tmp_path: Path) -> None:
    result = invoke(
        "territory-batch", TARGETS, "--offline", "--out-dir", tmp_path / "out", "--states", "XX"
    )
    assert result.exit_code == 2
    assert "--states" in result.stderr


def test_batch_missing_csv(tmp_path: Path) -> None:
    result = invoke("territory-batch", tmp_path / "nope.csv", "--offline", "--out-dir", tmp_path)
    assert result.exit_code == 2


def test_batch_csv_without_domain_column(tmp_path: Path) -> None:
    bad = tmp_path / "bad.csv"
    bad.write_text("company_name,hq_state\nAcme,CA\n")
    result = invoke("territory-batch", bad, "--offline", "--out-dir", tmp_path / "out")
    assert result.exit_code == 2


def test_batch_partial_failure(tmp_path: Path) -> None:
    rows = [
        "Good Co,goodco.example,,CA" + "," * 10,
        "Bad Co,badco.example,,ZZ" + "," * 10,
    ]
    csv_path = write_csv(tmp_path / "t.csv", *rows)
    result = invoke("territory-batch", csv_path, "--offline", "--out-dir", tmp_path / "out")
    assert result.exit_code == 1
    assert "Not analyzed" in result.stdout
    assert "line 3" in result.stdout


def test_doctor_without_key() -> None:
    result = invoke("doctor")
    assert result.exit_code == 0
    assert "Anthropic API key" in result.stdout
    assert "not set" in result.stdout


def test_doctor_with_key_never_prints_it() -> None:
    result = invoke("doctor", env={"ANTHROPIC_API_KEY": "sk-ant-test-SECRET123"})
    assert result.exit_code == 0
    assert "set" in result.stdout
    assert "claude-sonnet-5-5" in result.stdout
    assert "SECRET123" not in result.stdout + result.stderr
    assert "not set" not in result.stdout


def test_offline_and_live_conflict() -> None:
    result = invoke("run", "lexiconlegal.example", "--offline", "--live")
    assert result.exit_code == 2
    assert "cannot be used together" in result.stderr


def test_invalid_configuration() -> None:
    result = invoke(
        "qualify", "lexiconlegal.example", "--offline", env={"PROSPECTOR_HTTP_CONCURRENCY": "999"}
    )
    assert result.exit_code == 2
    assert "Invalid configuration" in result.stderr
    assert "http_concurrency" in result.stderr


@pytest.mark.parametrize("command", ["run", "qualify", "territory-batch", "doctor"])
def test_command_help(command: str) -> None:
    assert invoke(command, "--help").exit_code == 0
