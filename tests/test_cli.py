import subprocess
import sys
from importlib.metadata import entry_points

from typer.testing import CliRunner

from anthropic_prospector import __version__
from anthropic_prospector.cli import app

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
