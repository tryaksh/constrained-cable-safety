"""Every import of this repository's own code must point at something real.

Why this test exists
--------------------
A previous session deleted a helper module that two live entry points still
imported. Every unit test passed, because no unit test imports an entry point,
and every simulator entry point failed the moment it was started. Nothing caught
it until someone tried to run the project.

Importing each script for real would not work here: most of them import MuJoCo,
FreeCAD or Isaac Sim, which live in separate virtual environments and are not
installed alongside the test suite. So this test reads the code instead of
running it. It parses every Python file in the repository, finds every import
that refers to this repository's own packages, and checks that the module exists
and that the name being imported out of it is actually defined there.

That is enough to catch the failure above, and it runs in milliseconds on any
machine with no simulator installed.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]

# Directories whose Python files are checked.
SOURCE_DIRECTORIES = ("src", "scripts", "tests")

# Top-level names that belong to this repository rather than to a package
# installed from elsewhere. Anything else in an import statement is treated as a
# third-party dependency and left alone.
FIRST_PARTY_ROOTS = ("assembly_recovery", "scripts", "tests")

# Where each first-party root's files live, relative to the repository root.
ROOT_DIRECTORIES = {
    "assembly_recovery": ROOT / "src",
    "scripts": ROOT,
    "tests": ROOT,
}


def python_files() -> list[pathlib.Path]:
    """Every Python file in the repository worth checking, sorted."""
    found: list[pathlib.Path] = []
    for directory in SOURCE_DIRECTORIES:
        for path in sorted((ROOT / directory).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            found.append(path)
    return found


ALL_FILES = python_files()


def module_path(dotted: str) -> pathlib.Path | None:
    """Turn ``assembly_recovery.cable_run`` into the file it lives in.

    Returns ``None`` if the name does not belong to this repository. Raises
    nothing: a first-party name that has no file on disk comes back as a path
    that does not exist, which is exactly the failure we are looking for.
    """
    root = dotted.split(".", 1)[0]
    if root not in FIRST_PARTY_ROOTS:
        return None
    base = ROOT_DIRECTORIES[root]
    parts = dotted.split(".")
    as_module = base.joinpath(*parts).with_suffix(".py")
    as_package = base.joinpath(*parts, "__init__.py")
    return as_package if as_package.exists() and not as_module.exists() else as_module


def names_defined_in(path: pathlib.Path) -> set[str]:
    """Every name a module binds at its top level.

    Covers ``def``, ``class``, plain and annotated assignment, ``import`` and
    ``from ... import``, and star imports are reported by returning a set
    containing ``"*"`` so the caller can decline to judge.
    """
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    defined: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                defined.update(_assigned_names(target))
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            defined.update(_assigned_names(node.target))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                defined.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*":
                    defined.add("*")
                else:
                    defined.add(alias.asname or alias.name)
        elif isinstance(node, (ast.If, ast.Try)):
            # Names bound inside a ``try``/``except ImportError`` or a
            # ``if TYPE_CHECKING`` block still count as defined.
            for inner in ast.walk(node):
                if isinstance(inner, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    defined.add(inner.name)
                elif isinstance(inner, ast.Assign):
                    for target in inner.targets:
                        defined.update(_assigned_names(target))
                elif isinstance(inner, ast.Import):
                    for alias in inner.names:
                        defined.add(alias.asname or alias.name.split(".")[0])
                elif isinstance(inner, ast.ImportFrom):
                    for alias in inner.names:
                        defined.add(alias.asname or alias.name)
    return defined


def _assigned_names(target: ast.expr) -> set[str]:
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.Tuple, ast.List)):
        names: set[str] = set()
        for element in target.elts:
            names.update(_assigned_names(element))
        return names
    return set()


def first_party_imports(path: pathlib.Path) -> list[tuple[int, str, str | None]]:
    """Every first-party import in one file.

    Each entry is ``(line number, dotted module name, name imported out of it)``
    where the third item is ``None`` for a plain ``import x.y``.
    """
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    found: list[tuple[int, str, str | None]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in FIRST_PARTY_ROOTS:
                    found.append((node.lineno, alias.name, None))
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # a relative import; none are used here
                continue
            if node.module and node.module.split(".")[0] in FIRST_PARTY_ROOTS:
                for alias in node.names:
                    found.append((node.lineno, node.module, alias.name))
    return found


@pytest.mark.parametrize("path", ALL_FILES, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_every_first_party_import_resolves(path: pathlib.Path) -> None:
    """Every module this file imports from the repository exists on disk."""
    for lineno, dotted, _name in first_party_imports(path):
        target = module_path(dotted)
        assert target is not None, "first-party filter let a third-party name through"
        where = f"{path.relative_to(ROOT).as_posix()}:{lineno}"
        assert target.exists(), f"{where} imports {dotted}, which has no file at {target}"


@pytest.mark.parametrize("path", ALL_FILES, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_every_imported_name_is_defined(path: pathlib.Path) -> None:
    """Every name pulled out of one of this repository's modules is defined there."""
    for lineno, dotted, name in first_party_imports(path):
        if name is None:
            continue
        target = module_path(dotted)
        if target is None or not target.exists():
            continue  # the test above already reports this
        # ``from assembly_recovery import cable_run`` imports a submodule, not a
        # name inside ``__init__.py``.
        submodule = module_path(f"{dotted}.{name}")
        if submodule is not None and submodule.exists():
            continue
        defined = names_defined_in(target)
        if "*" in defined:
            continue  # a star import; we cannot tell without running it
        where = f"{path.relative_to(ROOT).as_posix()}:{lineno}"
        assert name in defined, f"{where} imports {name} from {dotted}, which does not define it"


def test_the_check_covers_the_scripts() -> None:
    """Guard against the walk silently finding nothing."""
    scripts = [p for p in ALL_FILES if p.parts[len(ROOT.parts)] == "scripts"]
    assert len(scripts) > 10, f"only {len(scripts)} scripts found; the walk is wrong"
