from __future__ import annotations

import ast
import re
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


def test_completed_modules_have_no_legacy_http_handlers():
    from novelwiki.bootstrap.legacy_http import OWNERS

    assert OWNERS["catalog"] == frozenset()
    assert OWNERS["reading"] == frozenset()
    assert OWNERS["acquisition"] == frozenset()
    assert OWNERS["translation"] == frozenset()
    assert OWNERS["codex"] == frozenset()
    assert OWNERS["experience"] == frozenset()
    # This ratchet makes handler extraction monotonic. Lower it as each slice lands.
    assert sum(len(names) for names in OWNERS.values()) == 0


@pytest.mark.parametrize(
    "relative",
    [
        Path("catalog/adapters/inbound/http.py"),
        Path("translation/adapters/inbound/http.py"),
        Path("acquisition/adapters/inbound/http.py"),
        Path("experience/adapters/inbound/projections_http.py"),
        Path("reading/adapters/inbound/http.py"),
        Path("codex/adapters/inbound/http.py"),
        Path("identity/adapters/inbound/http.py"),
        Path("narration/adapters/inbound/http.py"),
    ],
)
def test_migrated_http_adapters_contain_no_sql_or_pool_access(relative: Path):
    source = (MODULE_ROOT / relative).read_text(encoding="utf-8")
    assert "get_db_pool" not in source
    tree = ast.parse(source)
    forbidden_methods = {"execute", "executemany", "fetch", "fetchrow", "fetchval"}
    calls = [
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and node.func.attr in forbidden_methods
    ]
    assert not calls, f"{relative}: database calls in inbound adapter: {calls}"


@pytest.mark.parametrize(
    "relative",
    [
        Path("work/adapters/inbound/worker.py"),
        Path("ai_execution/adapters/inbound/worker.py"),
        Path("narration/adapters/inbound/worker.py"),
    ],
)
def test_migrated_workers_contain_no_sql_or_pool_access(relative: Path):
    source = (MODULE_ROOT / relative).read_text(encoding="utf-8")
    assert "get_db_pool" not in source
    tree = ast.parse(source)
    forbidden_methods = {"execute", "executemany", "fetch", "fetchrow", "fetchval"}
    calls = [
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in forbidden_methods
    ]
    assert not calls, f"database calls in inbound worker {relative}: {calls}"


def test_named_workflow_coordinators_are_infrastructure_free():
    workflow_root = ROOT / "novelwiki" / "workflows"
    forbidden_imports = (
        "fastapi", "typer", "asyncpg", "novelwiki.platform",
        "novelwiki.db", "novelwiki.config",
    )
    violations: list[str] = []
    for path in _python_files(workflow_root):
        source = path.read_text(encoding="utf-8")
        for imported in _imports(path):
            if imported.startswith(forbidden_imports):
                violations.append(f"{path.name} imports {imported}")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in {"execute", "fetch", "fetchrow", "fetchval"}:
                    violations.append(f"{path.name} calls {node.func.attr}")
    assert not violations, "\n".join(violations)


def test_experience_projection_registry_is_explicit_and_read_only():
    from novelwiki.modules.experience.adapters.outbound.projections import (
        PROJECTION_TABLES,
    )

    assert PROJECTION_TABLES == {
        "library_cards": frozenset({
            "novels", "library_entries", "reading_progress", "chapters", "sources",
        }),
        "novel_detail": frozenset({
            "novels", "chapters", "sources", "reading_progress", "library_entries",
            "chapter_overlays", "import_jobs", "contributions",
        }),
        "discover": frozenset({
            "novels", "users", "library_entries", "chapters", "sources", "chapter_audio",
        }),
        "public_profile": frozenset({
            "users", "library_entries", "novels", "reading_progress", "chapters",
        }),
    }
    path = MODULE_ROOT / "experience/adapters/outbound/projections.py"
    source = path.read_text(encoding="utf-8")
    writes = re.findall(r"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\b", source, re.IGNORECASE)
    assert not writes, f"Experience projection registry contains write SQL: {writes}"


def test_platform_web_lifespan_delegates_to_lifecycle_registry():
    source = (ROOT / "novelwiki/platform/web/app.py").read_text(encoding="utf-8")
    lifespan_source = source[source.index("async def lifespan"):source.index("app = FastAPI")]
    assert "build_application_lifecycle" in lifespan_source
    assert ".execute(" not in lifespan_source
    assert "start_worker" not in lifespan_source


def test_experience_admin_adapter_contains_no_write_sql():
    path = MODULE_ROOT / "experience/adapters/inbound/admin_http.py"
    source = path.read_text(encoding="utf-8")
    writes = re.findall(
        r"\b(?:INSERT\s+INTO|UPDATE\s+[a-z_]|DELETE\s+FROM)\b",
        source,
        re.IGNORECASE,
    )
    assert not writes, f"Experience admin adapter contains write SQL: {writes}"
