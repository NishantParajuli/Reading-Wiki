#!/usr/bin/env python3
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))

from novelwiki.platform.architecture.checks import (
    cross_module_import_violations, frontend_boundary_violations,
    inbound_database_violations, legacy_facade_import_violations,
    module_dependency_cycles, table_boundary_violations,
)

violations = table_boundary_violations(root)
cycles = module_dependency_cycles(root)
frontend = frontend_boundary_violations(root)
inbound = inbound_database_violations(root)
legacy = legacy_facade_import_violations(root)
cross_module = cross_module_import_violations(root)
if violations or cycles or frontend or inbound or legacy or cross_module:
    for item in violations:
        print(item)
    for item in cycles:
        print(f"module dependency cycle: {item}")
    for item in frontend:
        print(item)
    for item in inbound:
        print(item)
    for item in legacy:
        print(item)
    for item in cross_module:
        print(item)
    raise SystemExit(1)
print("architecture boundaries: ok")
