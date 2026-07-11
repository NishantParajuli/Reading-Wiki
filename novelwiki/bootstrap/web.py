"""Web composition-root compatibility bridge.

Router ownership moves here slice by slice. Importing this module never constructs a
second FastAPI application.
"""

from novelwiki.platform.web.app import app

__all__ = ["app"]
