"""Compatibility alias for the Work Management worker adapter."""
import sys
from types import SimpleNamespace

from novelwiki.bootstrap.work_worker import build_worker_state_service
from novelwiki.bootstrap.workers import build_api_worker_registry
from novelwiki.modules.work.adapters.inbound import worker as _implementation
from novelwiki.modules.work.adapters.outbound import postgres
from novelwiki.modules.work.adapters.outbound.claims import claim_next

_implementation.configure_worker_runtime(SimpleNamespace(
    claim_next=claim_next,
    registry_factory=build_api_worker_registry,
    service=postgres,
    worker_state_factory=build_worker_state_service,
))
sys.modules[__name__] = _implementation
