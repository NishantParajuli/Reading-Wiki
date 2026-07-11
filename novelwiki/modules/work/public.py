"""Stable Work Management contracts and data-transfer objects."""

from .application.contracts import (
    JobQuotaSettlement,
    ScheduledJob,
    WorkApi,
    WorkQuotaFinalizationTransactionApi,
    WorkTransactionApi,
)


__all__ = [
    "JobQuotaSettlement",
    "ScheduledJob",
    "WorkApi",
    "WorkQuotaFinalizationTransactionApi",
    "WorkTransactionApi",
]

# Stable executable compatibility surface. New application code receives these
# operations through Bootstrap; legacy workers and tests retain their import path.
from .adapters.outbound import postgres as service  # noqa: E402
from .adapters.outbound.claims import claim_next  # noqa: E402
from .adapters.inbound.worker import (  # noqa: E402
    _heartbeat,
    _recover_stale_leases,
    _release_due_provider_waits,
)
