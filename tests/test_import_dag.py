"""Static architecture checks over src/anthropic_prospector.

* Import DAG: each layer imports only the layers the plan allows, so the package cannot
  grow a cycle and the pipeline cannot reach into scrapers or the CLI.
* Third-party boundaries: Typer, Rich and the Anthropic SDK each stay behind one module.
* Pydantic V2 hygiene: no V1-era APIs, including ones the type checker cannot see.
* The leaf modules import alone, warning-free, in a fresh interpreter (Phase 1 gate).
"""

import ast
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

PACKAGE = "anthropic_prospector"
SRC = Path(__file__).resolve().parents[1] / "src" / PACKAGE

# Layer of every module, matched on the module name or its dotted prefix. A new module
# fails test_every_module_has_a_layer until it is placed here deliberately.
LAYERS: dict[str, str] = {
    f"{PACKAGE}.models": "models",
    f"{PACKAGE}.config": "config",
    f"{PACKAGE}.mock": "mock",
    f"{PACKAGE}.scrapers": "scrapers",
    f"{PACKAGE}.pipeline": "pipeline",
    f"{PACKAGE}.service": "service",
    f"{PACKAGE}.render": "render",
    f"{PACKAGE}.cli": "cli",
    f"{PACKAGE}.__main__": "cli",
}

# Layers each layer may import besides its own. "root" is the package __init__: it only
# defines __version__ and imports nothing from the package, so anything may import it.
ALLOWED: dict[str, frozenset[str]] = {
    "root": frozenset(),
    "models": frozenset(),
    "config": frozenset({"root"}),
    "mock": frozenset({"models", "config"}),
    "scrapers": frozenset({"models", "config"}),
    "pipeline": frozenset({"models", "config"}),
    "render": frozenset({"models", "config"}),
    "service": frozenset({"models", "config", "mock", "scrapers", "pipeline"}),
    "cli": frozenset({"root", "models", "config", "service", "render"}),
}

# Siblings that must stay independent: the service passes one's output to the other.
FORBIDDEN_EDGES = {
    (f"{PACKAGE}.pipeline.displacement_matrix", f"{PACKAGE}.pipeline.meddpicc_generator"),
    (f"{PACKAGE}.pipeline.meddpicc_generator", f"{PACKAGE}.pipeline.displacement_matrix"),
}

# Third-party packages confined to the modules that own them (module or package prefix).
OWNERS: dict[str, tuple[str, ...]] = {
    "typer": (f"{PACKAGE}.cli",),
    "rich": (f"{PACKAGE}.render",),
    "anthropic": (f"{PACKAGE}.pipeline.llm",),
    "dns": (f"{PACKAGE}.scrapers",),
    "httpx": (f"{PACKAGE}.scrapers", f"{PACKAGE}.pipeline.llm"),
}

# The only third-party packages each leaf module may import.
LEAF_THIRD_PARTY: dict[str, set[str]] = {
    f"{PACKAGE}.models": {"pydantic"},
    f"{PACKAGE}.config": {"pydantic", "pydantic_settings"},
}

V1_METHODS = {
    "construct",
    "dict",
    "from_orm",
    "parse_file",
    "parse_obj",
    "parse_raw",
    "schema_json",
    "update_forward_refs",
}
V1_ATTRIBUTES = {"__fields__", "__validators__"}


def _module_name(path: Path) -> str:
    parts = path.relative_to(SRC.parent).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


MODULES: dict[str, Path] = {_module_name(p): p for p in sorted(SRC.rglob("*.py"))}


@dataclass(frozen=True)
class Import:
    target: str  # absolute module name; relative imports keep their leading dots
    line: int


def _tree(module: str) -> ast.Module:
    return ast.parse(MODULES[module].read_text(encoding="utf-8"), filename=str(MODULES[module]))


def _imports(module: str) -> list[Import]:
    found: list[Import] = []
    for node in ast.walk(_tree(module)):
        if isinstance(node, ast.Import):
            found += [Import(alias.name, node.lineno) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = "." * node.level + (node.module or "")
            for alias in node.names:
                # `from pkg import submodule` depends on the submodule, not just the package.
                candidate = f"{base}.{alias.name}"
                found.append(Import(candidate if candidate in MODULES else base, node.lineno))
    return found


def _layer(module: str) -> str:
    if module == PACKAGE:
        return "root"
    for prefix, layer in LAYERS.items():
        if module == prefix or module.startswith(f"{prefix}."):
            return layer
    raise AssertionError(f"{module} has no layer: add it to LAYERS in {Path(__file__).name}")


def _within(module: str, owners: tuple[str, ...]) -> bool:
    return any(module == owner or module.startswith(f"{owner}.") for owner in owners)


def test_package_is_discovered() -> None:
    assert {PACKAGE, f"{PACKAGE}.models", f"{PACKAGE}.config", f"{PACKAGE}.cli"} <= set(MODULES)


def test_every_module_has_a_layer() -> None:
    for module in MODULES:
        _layer(module)


@pytest.mark.parametrize("module", sorted(MODULES))
def test_imports_respect_layers(module: str) -> None:
    layer = _layer(module)
    allowed = ALLOWED[layer] | {layer}
    violations = []
    for imp in _imports(module):
        if imp.target.startswith("."):
            violations.append(f"line {imp.line}: relative import {imp.target!r}")
        elif imp.target.split(".")[0] == PACKAGE:
            target_layer = _layer(imp.target)
            if target_layer not in allowed or (module, imp.target) in FORBIDDEN_EDGES:
                violations.append(f"line {imp.line}: {layer} may not import {imp.target}")
    assert not violations, f"{module}:\n" + "\n".join(violations)


@pytest.mark.parametrize("module", sorted(MODULES))
def test_third_party_boundaries(module: str) -> None:
    violations = [
        f"line {imp.line}: {imp.target} belongs in {', '.join(OWNERS[top])}"
        for imp in _imports(module)
        if (top := imp.target.split(".")[0]) in OWNERS and not _within(module, OWNERS[top])
    ]
    assert not violations, f"{module}:\n" + "\n".join(violations)


@pytest.mark.parametrize(("module", "allowed"), sorted(LEAF_THIRD_PARTY.items()))
def test_leaf_modules_use_only_stdlib_and_pydantic(module: str, allowed: set[str]) -> None:
    top_level = {imp.target.split(".")[0] for imp in _imports(module)}
    third_party = top_level - set(sys.stdlib_module_names) - {PACKAGE}
    assert third_party <= allowed


@pytest.mark.parametrize("module", sorted(MODULES))
def test_no_pydantic_v1_apis(module: str) -> None:
    violations = []
    for node in ast.walk(_tree(module)):
        if isinstance(node, ast.ClassDef):
            violations += [
                f"line {inner.lineno}: nested `class Config` (use model_config = ConfigDict(...))"
                for inner in node.body
                if isinstance(inner, ast.ClassDef) and inner.name == "Config"
            ]
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in V1_METHODS
        ):
            violations.append(f"line {node.lineno}: .{node.func.attr}() is a Pydantic V1 API")
        elif isinstance(node, ast.Attribute) and node.attr in V1_ATTRIBUTES:
            violations.append(f"line {node.lineno}: {node.attr} is a Pydantic V1 API")
    assert not violations, f"{module}:\n" + "\n".join(violations)


@pytest.mark.parametrize("module", [f"{PACKAGE}.models", f"{PACKAGE}.config"])
def test_leaf_imports_alone_in_fresh_interpreter(module: str) -> None:
    probe = (
        f"import sys, {module}; print(*sorted(m for m in sys.modules if m.startswith({PACKAGE!r})))"
    )
    proc = subprocess.run(
        [sys.executable, "-W", "error", "-c", probe], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stderr
    assert set(proc.stdout.split()) == {PACKAGE, module}
