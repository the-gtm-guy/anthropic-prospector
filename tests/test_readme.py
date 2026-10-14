"""The README's examples are real, and so is the sample brief it links to.

Every `$ ...` line in a ```console block of README.md runs, in order, in one scratch
directory holding a copy of targets.csv, at a fixed terminal width, with no keys. Each must
exit 0. When the README shows output under a command, that output must match what the
command prints today. Leading VAR=value words set environment variables, as in a shell.

examples/lexiconlegal-example.md must equal the brief the same account produces now.

After an intended change, refresh both and review the diff:

    UPDATE_README=1 pytest tests/test_readme.py
"""

import asyncio
import difflib
import os
import re
import shlex
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from anthropic_prospector.cli import app
from anthropic_prospector.config import Settings
from anthropic_prospector.service import DataMode, analyze, render_brief, resolve_target

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
SAMPLE_BRIEF = ROOT / "examples" / "lexiconlegal-example.md"
SAMPLE_TIME = datetime(2026, 10, 1, 16, tzinfo=UTC)
DEFAULT_COLUMNS = "100"
UPDATE = os.environ.get("UPDATE_README") == "1"

_CONSOLE_BLOCK = re.compile(r"^```console\n(.*?)^```$", re.MULTILINE | re.DOTALL)
_ASSIGNMENT = re.compile(r"^[A-Z_][A-Z0-9_]*=")
_LINK = re.compile(r"\]\((?!https?://|#|mailto:)([^)\s]+)\)")


@dataclass
class Example:
    command: str
    output: list[str] = field(default_factory=list)


def _parse(block: str) -> list[Example]:
    examples: list[Example] = []
    for line in block.splitlines():
        if line.startswith("$ "):
            examples.append(Example(line[2:].strip()))
        elif examples:
            examples[-1].output.append(line.rstrip())
        elif line.strip():
            raise AssertionError(f"console block text before any command: {line!r}")
    for example in examples:
        while example.output and not example.output[-1]:
            example.output.pop()
    return examples


def _render(examples: list[Example]) -> str:
    lines: list[str] = []
    for example in examples:
        lines.append(f"$ {example.command}")
        lines += example.output
    return "\n".join(lines) + "\n"


def _run(runner: CliRunner, command: str) -> tuple[int, list[str], str]:
    words = shlex.split(command)
    env = {"COLUMNS": DEFAULT_COLUMNS}
    while words and _ASSIGNMENT.match(words[0]):
        name, _, value = words.pop(0).partition("=")
        env[name] = value
    assert words[:1] == ["prospector"], f"README console commands must run prospector: {command}"
    result = runner.invoke(app, words[1:], env=env)
    lines = [line.rstrip() for line in result.stdout.splitlines()]
    while lines and not lines[-1]:
        lines.pop()
    return result.exit_code, lines, result.stdout + result.stderr


def test_readme_examples_run_and_match(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    text = README.read_text(encoding="utf-8")
    blocks = list(_CONSOLE_BLOCK.finditer(text))
    assert blocks, "README.md has no console examples"
    shutil.copy(ROOT / "targets.csv", tmp_path / "targets.csv")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PROSPECTOR_CACHE_DIR", str(tmp_path / "cache"))
    runner = CliRunner()

    problems: list[str] = []
    rebuilt: list[str] = []
    position = 0
    for block in blocks:
        examples = _parse(block.group(1))
        for example in examples:
            code, actual, everything = _run(runner, example.command)
            if code != 0:
                problems.append(f"`{example.command}` exited {code}:\n{everything}")
            elif example.output and example.output != actual:
                if UPDATE:
                    example.output = actual
                else:
                    problems.append(
                        f"`{example.command}` output differs from the README:\n"
                        + "\n".join(_diff(example.output, actual))
                    )
        rebuilt += [text[position : block.start(1)], _render(examples)]
        position = block.end(1)
    rebuilt.append(text[position:])

    if UPDATE and not problems:
        README.write_text("".join(rebuilt), encoding="utf-8")
    assert not problems, "\n\n".join(problems) + "\n\nRefresh: UPDATE_README=1 pytest"


def test_sample_brief_is_current() -> None:
    profile = resolve_target("lexiconlegal.example")
    result = asyncio.run(analyze(profile, Settings(), mode=DataMode.OFFLINE, now=SAMPLE_TIME))
    assert result.brief is not None
    expected = render_brief(result.brief, "md")
    if UPDATE:
        SAMPLE_BRIEF.parent.mkdir(parents=True, exist_ok=True)
        SAMPLE_BRIEF.write_text(expected, encoding="utf-8")
    assert SAMPLE_BRIEF.read_text(encoding="utf-8") == expected


@pytest.mark.parametrize("doc", ["README.md", "CAROUSEL_DECK.md"])
def test_relative_links_resolve(doc: str) -> None:
    text = (ROOT / doc).read_text(encoding="utf-8")
    missing = [link for link in _LINK.findall(text) if not (ROOT / link.split("#")[0]).exists()]
    assert not missing, f"{doc} links to missing files: {missing}"


def _diff(expected: list[str], actual: list[str]) -> list[str]:
    return list(difflib.unified_diff(expected, actual, "README", "actual", lineterm=""))
