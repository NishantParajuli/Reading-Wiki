from __future__ import annotations

import ast
import re
from pathlib import Path

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


def table_boundary_violations(root: Path) -> list[str]:
    module_root = root / "novelwiki" / "modules"
    violations: list[str] = []
    for path in sorted(module_root.rglob("*.py")):
        owner = path.relative_to(module_root).parts[0]
        for text, line in _string_literals(path):
            if not re.search(r"\b(?:SELECT|INSERT|UPDATE|DELETE)\b", text, re.I):
                continue
            for table in _WRITE.findall(text):
                expected = TABLE_OWNERS.get(table.lower())
                if expected and expected != owner:
                    violations.append(
                        f"{path.relative_to(root)}:{line}: {owner} writes {table} owned by {expected}"
                    )
            for table in _READ.findall(text):
                expected = TABLE_OWNERS.get(table.lower())
                if expected and expected != owner and owner != "experience":
                    violations.append(
                        f"{path.relative_to(root)}:{line}: {owner} reads {table} owned by {expected}"
                    )
    return violations


def module_dependency_cycles(root: Path) -> list[str]:
    module_root = root / "novelwiki" / "modules"
    graph: dict[str, set[str]] = {path.name: set() for path in module_root.iterdir() if path.is_dir()}
    prefix = "novelwiki.modules."
    for path in module_root.rglob("*.py"):
        owner = path.relative_to(module_root).parts[0]
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            imported = None
            if isinstance(node, ast.ImportFrom):
                imported = node.module
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(prefix):
                        target = alias.name.split(".")[2]
                        if target != owner:
                            graph.setdefault(owner, set()).add(target)
            if imported and imported.startswith(prefix):
                target = imported.split(".")[2]
                if target != owner:
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
    module_root = root / "novelwiki" / "modules"
    violations: list[str] = []
    database_methods = {"execute", "executemany", "fetch", "fetchrow", "fetchval"}
    for path in sorted(module_root.glob("*/adapters/inbound/*.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        if "get_db_pool" in source:
            violations.append(f"{path.relative_to(root)} imports or calls get_db_pool")
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in database_methods
            ):
                violations.append(
                    f"{path.relative_to(root)}:{node.lineno}: inbound adapter calls {node.func.attr}"
                )
    return violations
