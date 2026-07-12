"""Compatibility entrypoint for the Acquisition import-worker application service."""

import sys

# Claimed-job dispatch is owned by
# novelwiki.modules.acquisition.application.worker.ImportWorkerService.
from novelwiki.modules.acquisition.application import import_worker as _implementation

sys.modules[__name__] = _implementation
