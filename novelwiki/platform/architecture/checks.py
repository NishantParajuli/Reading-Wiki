from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Iterator

TABLE_OWNERS = {
    "app_migrations": "platform", "audit_events": "platform",
    "users": "identity", "oauth_accounts": "identity", "sessions": "identity",
    "email_tokens": "identity", "auth_rate_limits": "identity", "quota_usage": "identity",
    "user_ai_backend_policies": "ai_execution", "ai_request_locks": "ai_execution",
    "provider_budget": "ai_execution", "ai_execution_runs": "ai_execution",
    "ai_worker_heartbeats": "ai_execution", "novels": "catalog",
    "library_entries": "catalog", "tag_suggestions": "catalog", "sources": "acquisition",
    "import_jobs": "acquisition", "assets": "acquisition", "chapters": "reading",
    "reading_progress": "reading", "bookmarks": "reading", "chapter_overlays": "reading",
    "contributions": "reading", "translation_glossary": "translation", "chunks": "codex",
    "entities": "codex", "entity_descriptions": "codex", "entity_aliases": "codex",
    "identity_links": "codex", "entity_facts": "codex", "relationships": "codex",
    "events": "codex", "extraction_state": "codex", "wiki_cache": "codex",
    "query_cache": "codex", "tts_jobs": "narration", "chapter_audio": "narration",
    "jobs": "work",
}

_WRITE = re.compile(r"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+([a-z_]+)", re.I)
_READ = re.compile(r"\b(?:FROM|JOIN)\s+([a-z_]+)", re.I)

MODULE_PREFIX = "novelwiki.modules."

# Compatibility namespaces that still resolve to business-module implementations.
# Keeping this map here makes the dependency graph semantic rather than dependent
# on the spelling of an import during the strangler migration.
LEGACY_NAMESPACE_OWNERS = {
    "novelwiki.agent.llm_client": "ai_execution",
    "novelwiki.agy.codex": "codex",
    "novelwiki.agy.translation": "translation",
    "novelwiki.auth": "identity",
    "novelwiki.quota": "identity",
    "novelwiki.jobs": "work",
    "novelwiki.agy": "ai_execution",
    "novelwiki.ai_backend": "ai_execution",
    "novelwiki.importer": "acquisition",
    "novelwiki.scraper": "acquisition",
    "novelwiki.ingest": "codex",
    "novelwiki.retrieval": "codex",
    "novelwiki.agent": "codex",
    "novelwiki.translate": "translation",
    "novelwiki.tts": "narration",
    "novelwiki.ai_limits": "ai_execution",
    "novelwiki.audit": "platform",
    "novelwiki.config": "platform",
    "novelwiki.db": "platform",
}

_DATABASE_METHODS = {"execute", "executemany", "fetch", "fetchrow", "fetchval"}
_POOL_FUNCTIONS = {"close_db_pool", "get_db_pool", "init_db_pool"}


def _string_literals(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.value, node.lineno
        elif isinstance(node, ast.JoinedStr):
            yield "".join(
                value.value for value in node.values
                if isinstance(value, ast.Constant) and isinstance(value.value, str)
            ), node.lineno


def _python_imports(path: Path) -> Iterator[tuple[str, int]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node.lineno
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module, node.lineno
            if node.module == "novelwiki":
                for alias in node.names:
                    yield f"novelwiki.{alias.name}", node.lineno


def _resolved_python_imports(path: Path, module_root: Path) -> Iterator[tuple[str, int]]:
    """Yield absolute import targets, including imports relative to a module package."""
    relative = path.relative_to(module_root).with_suffix("")
    module_parts = ["novelwiki", "modules", *relative.parts]
    if module_parts[-1] == "__init__":
        package_parts = module_parts[:-1]
    else:
        package_parts = module_parts[:-1]
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node.lineno
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                keep = len(package_parts) - (node.level - 1)
                prefix = package_parts[:keep]
                target = ".".join([*prefix, *(node.module or "").split(".")]).rstrip(".")
            else:
                target = node.module or ""
            if target:
                yield target, node.lineno


def _module_owner(imported: str) -> str | None:
    if imported.startswith(MODULE_PREFIX):
        parts = imported.split(".")
        return parts[2] if len(parts) > 2 else None
    for prefix, owner in sorted(
        LEGACY_NAMESPACE_OWNERS.items(), key=lambda item: len(item[0]), reverse=True
    ):
        if imported == prefix or imported.startswith(f"{prefix}."):
            return owner
    return None


def _sql_location(path: Path, root: Path) -> tuple[str | None, bool, bool]:
    """Return (owner, SQL allowed here, read-only projection)."""
    relative = path.relative_to(root)
    parts = relative.parts
    if relative == Path("novelwiki/db/schema.py") or (
        parts[:2] == ("novelwiki", "db") and path.name.startswith("migrate")
    ):
        return "platform", True, False
    if len(parts) >= 3 and parts[:2] == ("novelwiki", "platform"):
        return "platform", True, False
    if len(parts) >= 6 and parts[:2] == ("novelwiki", "modules"):
        owner = parts[2]
        is_outbound = parts[3:5] == ("adapters", "outbound")
        read_only = owner == "experience" and is_outbound
        return owner, is_outbound, read_only
    return None, False, False


def table_boundary_violations(root: Path) -> list[str]:
    violations: list[str] = []
    production_root = root / "novelwiki"
    for path in sorted(production_root.rglob("*.py")):
        if "eval" in path.relative_to(production_root).parts:
            continue
        owner, sql_allowed, read_only = _sql_location(path, root)
        for text, line in _string_literals(path):
            if not re.search(r"\b(?:SELECT|INSERT|UPDATE|DELETE)\b", text, re.I):
                continue
            writes = [table for table in _WRITE.findall(text) if table.lower() in TABLE_OWNERS]
            reads = [table for table in _READ.findall(text) if table.lower() in TABLE_OWNERS]
            if (writes or reads) and not sql_allowed:
                violations.append(
                    f"{path.relative_to(root)}:{line}: raw SQL outside an approved adapter"
                )
                continue
            if writes and read_only:
                violations.append(
                    f"{path.relative_to(root)}:{line}: Experience projection writes data"
                )
            for table in writes:
                expected = TABLE_OWNERS.get(table.lower())
                if expected and expected != owner and owner != "platform":
                    violations.append(
                        f"{path.relative_to(root)}:{line}: {owner} writes {table} owned by {expected}"
                    )
            for table in reads:
                expected = TABLE_OWNERS.get(table.lower())
                if expected and expected != owner and owner not in {"experience", "platform"}:
                    violations.append(
                        f"{path.relative_to(root)}:{line}: {owner} reads {table} owned by {expected}"
                    )
    return violations


def module_dependency_cycles(root: Path) -> list[str]:
    module_root = root / "novelwiki" / "modules"
    graph: dict[str, set[str]] = {path.name: set() for path in module_root.iterdir() if path.is_dir()}
    for path in module_root.rglob("*.py"):
        owner = path.relative_to(module_root).parts[0]
        for imported, _line in _python_imports(path):
            target = _module_owner(imported)
            is_public_contract = (
                imported.startswith(MODULE_PREFIX)
                and len(imported.split(".")) >= 4
                and imported.split(".")[3] == "public"
            )
            if target and target != owner and not is_public_contract:
                graph.setdefault(owner, set()).add(target)
    cycles: set[str] = set()

    def visit(node: str, path: list[str]):
        if node in path:
            cycle = path[path.index(node):] + [node]
            rotations = [cycle[i:-1] + cycle[:i] + [cycle[i]] for i in range(len(cycle)-1)]
            cycles.add(" -> ".join(min(rotations)))
            return
        for child in graph.get(node, ()):
            visit(child, path + [node])

    for node in graph:
        visit(node, [])
    return sorted(cycles)


def legacy_facade_import_violations(root: Path) -> list[str]:
    """Report module code that reaches implementations through old namespaces."""
    module_root = root / "novelwiki" / "modules"
    violations: list[str] = []
    for path in sorted(module_root.rglob("*.py")):
        for imported, line in _python_imports(path):
            if any(
                imported == prefix or imported.startswith(f"{prefix}.")
                for prefix in LEGACY_NAMESPACE_OWNERS
            ):
                violations.append(
                    f"{path.relative_to(root)}:{line}: imports compatibility facade {imported}"
                )
    return violations


def cross_module_import_violations(root: Path) -> list[str]:
    """Require stable cross-owner types to enter through public.py."""
    module_root = root / "novelwiki" / "modules"
    violations: list[str] = []
    for path in sorted(module_root.rglob("*.py")):
        owner = path.relative_to(module_root).parts[0]
        for imported, line in _python_imports(path):
            if not imported.startswith(MODULE_PREFIX):
                continue
            target = _module_owner(imported)
            if not target or target == owner:
                continue
            parts = imported.split(".")
            if len(parts) < 4 or parts[3] != "public":
                violations.append(
                    f"{path.relative_to(root)}:{line}: imports {imported} instead of {MODULE_PREFIX}{target}.public"
                )
    return violations


def layer_dependency_violations(root: Path) -> list[str]:
    """Enforce the final Clean Architecture layer and composition directions."""
    module_root = root / "novelwiki" / "modules"
    violations: list[str] = []
    for path in sorted(module_root.rglob("*.py")):
        relative = path.relative_to(module_root)
        owner = relative.parts[0]
        layer = None
        if len(relative.parts) >= 4 and relative.parts[1:3] == ("adapters", "inbound"):
            layer = "inbound"
        elif len(relative.parts) >= 4 and relative.parts[1:3] == ("adapters", "outbound"):
            layer = "outbound"
        elif len(relative.parts) == 2 and relative.name == "public.py":
            layer = "public"
        own_adapters = f"novelwiki.modules.{owner}.adapters"
        for imported, line in _resolved_python_imports(path, module_root):
            if imported == "novelwiki.bootstrap" or imported.startswith("novelwiki.bootstrap."):
                violations.append(
                    f"{path.relative_to(root)}:{line}: module code imports composition root {imported}"
                )
            if layer == "inbound" and imported.startswith(f"{own_adapters}.outbound"):
                violations.append(
                    f"{path.relative_to(root)}:{line}: inbound adapter imports outbound adapter {imported}"
                )
            if layer == "outbound" and imported.startswith(f"{own_adapters}.inbound"):
                violations.append(
                    f"{path.relative_to(root)}:{line}: outbound adapter imports inbound adapter {imported}"
                )
            if layer == "public" and imported.startswith(own_adapters):
                violations.append(
                    f"{path.relative_to(root)}:{line}: public contract imports adapter {imported}"
                )
            if layer == "outbound" and (
                imported == "fastapi" or imported.startswith("fastapi.")
            ):
                violations.append(
                    f"{path.relative_to(root)}:{line}: outbound adapter imports FastAPI {imported}"
                )
    return violations


def public_surface_violations(root: Path) -> list[str]:
    """Keep public.py as DTO/protocol contracts, never executable implementation lookup."""
    module_root = root / "novelwiki" / "modules"
    violations: list[str] = []
    for path in sorted(module_root.glob("*/public.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                violations.append(
                    f"{path.relative_to(root)}:{node.lineno}: public contract defines executable function {node.name}"
                )
    return violations


def frontend_boundary_violations(root: Path) -> list[str]:
    frontend = root / "novelwiki" / "frontend" / "src"
    violations: list[str] = []
    for facade in ("api.js", "queries.js"):
        if (frontend / "lib" / facade).exists():
            violations.append(f"frontend compatibility facade still exists: lib/{facade}")
    import_pattern = re.compile(r"(?:from\s+|import\s*\()(['\"])([^'\"]+)\1")
    for path in sorted(frontend.rglob("*.js*")):
        source = path.read_text(encoding="utf-8")
        if re.search(r"\bAPI\.", source):
            violations.append(f"{path.relative_to(root)}: global API facade usage")
        relative = path.relative_to(frontend)
        owner = relative.parts[1] if len(relative.parts) > 1 and relative.parts[0] == "modules" else None
        for match in import_pattern.finditer(source):
            target = match.group(2)
            if "/modules/" not in target and not target.startswith("../"):
                continue
            resolved = (path.parent / target).resolve()
            try:
                target_relative = resolved.relative_to(frontend / "modules")
            except ValueError:
                continue
            target_owner = target_relative.parts[0]
            if owner and target_owner != owner:
                public_file = target_relative.parts[-1] in {"api.js", "queries.js", "index.js"}
                if not public_file:
                    violations.append(
                        f"{path.relative_to(root)} imports internal file from {target_owner}: {target}"
                    )
    screen_limits = {
        frontend / "screens" / "Reader.jsx": 400,
        frontend / "screens" / "ImportView.jsx": 300,
        frontend / "screens" / "Admin.jsx": 150,
        frontend / "screens" / "Account.jsx": 150,
        frontend / "screens" / "novel" / "Manage.jsx": 400,
    }
    for path, limit in screen_limits.items():
        count = len(path.read_text(encoding="utf-8").splitlines())
        if count > limit:
            violations.append(f"{path.relative_to(root)}: {count} lines exceeds reviewed limit {limit}")
    return violations


def inbound_database_violations(root: Path) -> list[str]:
    """Ban pool ownership and direct SQL from non-outbound business layers."""
    module_root = root / "novelwiki" / "modules"
    violations: list[str] = []
    paths = set(module_root.glob("*/adapters/inbound/**/*.py"))
    paths.update(module_root.glob("*/application/**/*.py"))
    paths.update(module_root.glob("*/domain/**/*.py"))
    paths.update((root / "novelwiki" / "workflows").glob("**/*.py"))
    for path in sorted(paths):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for name in sorted(_POOL_FUNCTIONS):
            if name in source:
                violations.append(f"{path.relative_to(root)} imports or calls {name}")
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in _DATABASE_METHODS
            ):
                violations.append(
                    f"{path.relative_to(root)}:{node.lineno}: non-outbound layer calls {node.func.attr}"
                )
    return violations
