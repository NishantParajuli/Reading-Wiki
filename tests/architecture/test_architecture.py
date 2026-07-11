from __future__ import annotations

import ast
from pathlib import Path

import pytest

from novelwiki.modules import MODULE_NAMES

ROOT = Path(__file__).resolve().parents[2]
MODULE_ROOT = ROOT / "novelwiki" / "modules"


def _python_files(root: Path):
    yield from sorted(root.rglob("*.py"))


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append(node.module)
    return found


def test_all_canonical_modules_have_public_contracts():
    for name in MODULE_NAMES:
        assert (MODULE_ROOT / name / "public.py").is_file(), name


@pytest.mark.parametrize("path", list(_python_files(MODULE_ROOT)))
def test_domain_and_application_are_framework_independent(path: Path):
    relative = path.relative_to(MODULE_ROOT)
    if "domain" not in relative.parts and "application" not in relative.parts:
        return
    forbidden = ("fastapi", "asyncpg", "novelwiki.config.settings", "novelwiki.db.connection")
    violations = [name for name in _imports(path) if name.startswith(forbidden)]
    assert not violations, f"{relative}: forbidden imports {violations}"


def test_cross_module_imports_target_public_contracts_only():
    violations: list[str] = []
    prefix = "novelwiki.modules."
    for path in _python_files(MODULE_ROOT):
        owner = path.relative_to(MODULE_ROOT).parts[0]
        for imported in _imports(path):
            if not imported.startswith(prefix):
                continue
            parts = imported.split(".")
            if len(parts) < 3 or parts[2] == owner:
                continue
            if len(parts) < 4 or parts[3] != "public":
                violations.append(f"{path.relative_to(ROOT)} -> {imported}")
    assert not violations, "\n".join(violations)


def test_legacy_router_does_not_regain_migrated_reading_routes():
    source = (ROOT / "novelwiki/api/routes.py").read_text(encoding="utf-8")
    for path in (
        '"/novels/{novel_id}/progress"',
        '"/novels/{novel_id}/bookmarks"',
        '"/novels/{novel_id}/bookmarks/{bookmark_id}"',
    ):
        assert path not in source


def test_every_legacy_http_bridge_has_exactly_one_module_owner():
    from novelwiki.bootstrap.legacy_http import OWNERS
    from novelwiki.legacy.routes import router

    assigned = [name for names in OWNERS.values() for name in names]
    available = [route.endpoint.__name__ for route in router.routes]
    assert len(assigned) == len(set(assigned))
    assert sorted(assigned) == sorted(available)


def test_stable_api_routes_module_is_only_a_compatibility_alias():
    source = (ROOT / "novelwiki/api/routes.py").read_text(encoding="utf-8")
    assert "@router." not in source
    assert "novelwiki.legacy.routes" in source
