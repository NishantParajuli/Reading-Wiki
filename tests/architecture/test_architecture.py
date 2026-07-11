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


def test_stable_api_routes_module_is_sql_free_direct_call_wrapper():
    source = (ROOT / "novelwiki/api/routes.py").read_text(encoding="utf-8")
    assert "@router." not in source
    assert "get_db_pool" not in source
    assert not re.search(r"\b(?:SELECT|INSERT|UPDATE|DELETE)\b", source, re.IGNORECASE)


def test_legacy_http_implementation_is_deleted():
    assert not (ROOT / "novelwiki/legacy/routes.py").exists()
    assert not (ROOT / "novelwiki/bootstrap/legacy_http.py").exists()
    assert not list(MODULE_ROOT.glob("*/adapters/inbound/legacy_http.py"))


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
        "home": frozenset({
            "users", "novels", "library_entries", "reading_progress", "chapters",
            "sources", "chapter_audio",
        }),
        "activity": frozenset({
            "import_jobs", "tts_jobs", "jobs", "ai_execution_runs",
        }),
        "job_view": frozenset({"jobs", "ai_execution_runs"}),
        "novel_health": frozenset({
            "novels", "chapters", "entities", "chunks", "sources", "jobs",
            "import_jobs", "tts_jobs",
        }),
        "cost_estimate": frozenset({"chapters", "chapter_audio", "quota_usage"}),
        "admin_users": frozenset({
            "users", "quota_usage", "novels", "user_ai_backend_policies", "jobs",
        }),
        "admin_agy_health": frozenset({
            "ai_worker_heartbeats", "jobs", "ai_execution_runs",
        }),
        "admin_usage": frozenset({"quota_usage", "users", "novels"}),
        "admin_novels": frozenset({"novels", "users", "chapters"}),
        "admin_global_novels": frozenset({"novels", "chapters", "sources"}),
    }
    path = MODULE_ROOT / "experience/adapters/outbound/projections.py"
    source = path.read_text(encoding="utf-8")
    writes = re.findall(r"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\b", source, re.IGNORECASE)
    assert not writes, f"Experience projection registry contains write SQL: {writes}"


def test_bootstrap_web_lifespan_delegates_to_lifecycle_registry():
    source = (ROOT / "novelwiki/bootstrap/web.py").read_text(encoding="utf-8")
    lifespan_source = source[
        source.index("async def lifespan"):source.index("app = create_web_app")
    ]
    assert "build_application_lifecycle" in lifespan_source
    assert ".execute(" not in lifespan_source
    assert "start_worker" not in lifespan_source


def test_platform_web_is_a_passive_stable_entrypoint():
    source = (ROOT / "novelwiki/platform/web/app.py").read_text(encoding="utf-8")
    assert "from novelwiki.bootstrap.web import app" in source
    assert "novelwiki.modules" not in source


def test_bootstrap_uses_platform_web_infrastructure_factory():
    source = (ROOT / "novelwiki/bootstrap/web.py").read_text(encoding="utf-8")
    assert "from novelwiki.platform.web.factory import create_web_app" in source
    assert "from novelwiki.platform.web.static import mount_platform_surfaces" in source
    assert "@app.middleware" not in source
    assert "class SpaStaticFiles" not in source


def test_worker_adapters_delegate_claimed_job_orchestration_to_application():
    for owner, service in {
        "work": "WorkWorkerService",
        "ai_execution": "AgyWorkerService",
        "narration": "NarrationWorkerService",
        "acquisition": "ImportWorkerService",
    }.items():
        source = (MODULE_ROOT / owner / "adapters/inbound/worker.py").read_text(
            encoding="utf-8"
        )
        assert f"novelwiki.modules.{owner}.application.worker" in source
        assert service in source


def test_feature_cli_adapters_delegate_to_application_commands():
    for owner in ("acquisition", "codex", "translation"):
        source = (MODULE_ROOT / owner / "adapters/inbound/cli.py").read_text(
            encoding="utf-8"
        )
        assert "novelwiki.bootstrap" in source
        assert "parse_epub(" not in source
        assert "commit_job(" not in source
        assert "translate_range(" not in source


def test_experience_admin_commands_are_injected():
    source = (MODULE_ROOT / "experience/adapters/inbound/admin_http.py").read_text(
        encoding="utf-8"
    )
    assert "experience_admin_commands_dependency" in source
    assert "novelwiki.modules.ai_execution" not in source
    assert "novelwiki.modules.work" not in source
    assert "platform.observability" not in source


def test_experience_admin_adapter_contains_no_write_sql():
    path = MODULE_ROOT / "experience/adapters/inbound/admin_http.py"
    source = path.read_text(encoding="utf-8")
    writes = re.findall(
        r"\b(?:INSERT\s+INTO|UPDATE\s+[a-z_]|DELETE\s+FROM)\b",
        source,
        re.IGNORECASE,
    )
    assert not writes, f"Experience admin adapter contains write SQL: {writes}"


@pytest.mark.parametrize(
    "relative",
    [
        Path("experience/adapters/inbound/http.py"),
        Path("experience/adapters/inbound/admin_http.py"),
        Path("acquisition/adapters/inbound/worker.py"),
    ],
)
def test_all_remaining_inbound_adapters_are_database_free(relative: Path):
    source = (MODULE_ROOT / relative).read_text(encoding="utf-8")
    assert "get_db_pool" not in source
    tree = ast.parse(source)
    calls = [
        node.func.attr for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"execute", "executemany", "fetch", "fetchrow", "fetchval"}
    ]
    assert not calls, f"{relative}: database calls in inbound adapter: {calls}"


def test_table_reads_and_writes_respect_owner_boundaries():
    from novelwiki.platform.architecture.checks import table_boundary_violations
    assert table_boundary_violations(ROOT) == []


def test_executable_module_dependency_graph_is_acyclic():
    from novelwiki.platform.architecture.checks import module_dependency_cycles
    assert module_dependency_cycles(ROOT) == []


def test_frontend_feature_boundaries_and_screen_limits():
    from novelwiki.platform.architecture.checks import frontend_boundary_violations
    assert frontend_boundary_violations(ROOT) == []


def test_every_module_inbound_adapter_is_database_free():
    from novelwiki.platform.architecture.checks import inbound_database_violations
    assert inbound_database_violations(ROOT) == []


def test_no_module_uses_a_legacy_facade_as_an_internal_api():
    from novelwiki.platform.architecture.checks import legacy_facade_import_violations
    assert legacy_facade_import_violations(ROOT) == []


def test_cross_module_imports_use_public_contracts():
    from novelwiki.platform.architecture.checks import cross_module_import_violations
    assert cross_module_import_violations(ROOT) == []
