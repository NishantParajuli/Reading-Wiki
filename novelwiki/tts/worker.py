import sys
from novelwiki.bootstrap.narration_worker import build_narration_worker_runtime
from novelwiki.modules.narration.adapters.inbound import worker as _implementation

_implementation.configure_worker_runtime(build_narration_worker_runtime())
sys.modules[__name__] = _implementation
