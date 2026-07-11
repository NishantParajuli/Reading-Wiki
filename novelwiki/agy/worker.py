"""Stable dedicated-worker entrypoint for AI Execution."""

from __future__ import annotations

import asyncio
import sys

from novelwiki.modules.ai_execution.adapters.inbound import worker as _implementation

if __name__ == "__main__":
    asyncio.run(_implementation.main())
else:
    sys.modules[__name__] = _implementation
