#!/usr/bin/env python3
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))

from novelwiki.platform.architecture.checks import (
    frontend_boundary_violations, inbound_database_violations,
    module_dependency_cycles, table_boundary_violations,
)

violations = table_boundary_violations(root)
cycles = module_dependency_cycles(root)
frontend = frontend_boundary_violations(root)
inbound = inbound_database_violations(root)
if violations or cycles or frontend or inbound:
    for item in violations:
        print(item)
    for item in cycles:
        print(f"module dependency cycle: {item}")
    for item in frontend:
        print(item)
    for item in inbound:
        print(item)
    raise SystemExit(1)
print("architecture boundaries: ok")
