"""Which agent implements, and which one reviews the result.

The spec wants the opposite model to review: if Claude implemented, Codex
reviews, and the reverse. The intent is that no model both proposes and blesses
its own work.

Reality constrains the rotation today. Writing to a repository means running a
tool on this machine through the gateway, and the only agent wired that way is
Codex. A Claude Code Routine runs on Anthropic's side; it can read a diff and
judge it, but it cannot commit to a workspace here. So the pairing is currently
fixed rather than alternating -- Codex implements, Claude reviews -- and the
independent-check property still holds, which is the part that matters.

The table is data so that when Claude gains a local write path, the rotation
starts working without touching the action agent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

# Agents that can write to a workspace on this machine.
LOCAL_IMPLEMENTERS = ("codex",)
# Agents that can review a diff, whether or not they can write one.
REVIEWERS = ("claude", "codex")


class RoutingError(ValueError):
    pass


@dataclass(frozen=True)
class Pairing:
    implementer: str
    reviewer: str

    def describe(self) -> str:
        return f"{self.implementer} implements, {self.reviewer} reviews"


def pair_for(
    preferred_implementer: Optional[str] = None,
    available_reviewers: Sequence[str] = REVIEWERS,
) -> Pairing:
    """Pick an implementer and a reviewer that are not the same agent."""
    implementer = preferred_implementer or LOCAL_IMPLEMENTERS[0]
    if implementer not in LOCAL_IMPLEMENTERS:
        raise RoutingError(
            f"{implementer} cannot write to a workspace on this machine. "
            f"Local implementers: {', '.join(LOCAL_IMPLEMENTERS)}"
        )

    for candidate in available_reviewers:
        if candidate != implementer:
            return Pairing(implementer=implementer, reviewer=candidate)

    raise RoutingError(
        f"No reviewer available other than {implementer}. A model reviewing its "
        "own implementation is not an independent check."
    )
