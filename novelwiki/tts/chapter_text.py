import sys
from novelwiki.modules.narration.adapters.outbound import chapter_text as _implementation
sys.modules[__name__] = _implementation
