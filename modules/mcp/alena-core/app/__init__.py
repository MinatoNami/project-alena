"""ALENA's own capabilities, exposed over MCP.

The repo root goes on sys.path here because an MCP server is launched from its
own directory (`cd modules/mcp/alena-core && python -m app.main`), and unlike
the other servers this one is a thin adapter over `modules.improve`. Requiring
PYTHONPATH instead would make the server work or not depending on how it was
started, which is the kind of thing that only fails in the scheduled run.
"""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
