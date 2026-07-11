#!/usr/bin/env python3
import argparse
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))

from novelwiki.platform.architecture.checks import (
    cross_module_import_violations, frontend_boundary_violations,
    inbound_database_violations, legacy_facade_import_violations,
    layer_dependency_violations, module_dependency_cycles,
    public_surface_violations, table_boundary_violations,
)

parser = argparse.ArgumentParser()
parser.add_argument(
    "--strict",
    action="store_true",
    help="also audit final Clean Architecture layer and public-surface rules",
)
args = parser.parse_args()

violations = table_boundary_violations(root)
cycles = module_dependency_cycles(root)
frontend = frontend_boundary_violations(root)
inbound = inbound_database_violations(root)
legacy = legacy_facade_import_violations(root)
cross_module = cross_module_import_violations(root)
strict = (
    layer_dependency_violations(root) + public_surface_violations(root)
    if args.strict else []
)
if violations or cycles or frontend or inbound or legacy or cross_module or strict:
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
    for item in strict:
        print(item)
    raise SystemExit(1)
print("architecture boundaries: ok")
