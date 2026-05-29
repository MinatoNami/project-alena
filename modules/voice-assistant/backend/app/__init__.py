from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_ROOT_DIR = next(
    (parent for parent in _HERE.parents if (parent / ".env").exists()),
    _HERE.parents[1],
)
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))
