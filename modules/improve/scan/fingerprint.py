"""Change detection between runs.

The nightly scan runs against every repository whether or not anything
happened. The fingerprint is what makes that cheap: if it matches the previous
scan, the repository has not moved and the model is never called.

It covers HEAD, the branch, and the working tree, because a repository sitting
on uncommitted work has changed even though its HEAD has not.
"""

from __future__ import annotations

import hashlib
from typing import Optional

from .git import GitState


def fingerprint(state: GitState) -> str:
    digest = hashlib.sha256()
    digest.update((state.head_sha or "no-head").encode())
    digest.update(b"\x1f")
    digest.update((state.branch or "no-branch").encode())
    digest.update(b"\x1f")
    for path in sorted(state.dirty_files):
        digest.update(path.encode())
        digest.update(b"\x1e")
    return digest.hexdigest()


def has_changed(current: str, previous: Optional[str]) -> bool:
    """A repository with no previous scan counts as changed."""
    return previous is None or current != previous
