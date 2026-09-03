from __future__ import annotations

import os
import sys
from pathlib import Path


def _find_root() -> Path:
    """The directory holding `modules/` — the repo root, or /app in the image.

    Walked rather than counted: the app sits four levels below the repo root in
    a checkout but two below it in the container, and a fixed `parents[4]`
    crashed there with IndexError before the first import finished.
    """
    override = os.getenv("ALENA_ROOT")
    if override:
        return Path(override).resolve()

    here = Path(__file__).resolve()
    for candidate in here.parents:
        if (candidate / "modules").is_dir():
            return candidate
    # Nothing recognisable: the app's own parent still makes `app.*` importable.
    return here.parents[1]


ROOT_DIR = _find_root()
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
