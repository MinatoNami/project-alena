"""Scoped, revocable write permission for a single action run.

A grant is what turns a recorded human decision into the ability to write. It
is deliberately not a permission change: the policy still decides *who may call
what*, and a grant only satisfies the approval requirement that policy imposes,
for one repository, for one run, for a bounded window.

Two limits make it safe to hand out.

**It cannot exceed the policy.** A grant satisfies approval; it never adds a
tool the policy would refuse. An agent that is not in `allowed_agents` stays
refused with a grant in hand.

**It is capped at REPOSITORY_WRITE.** A grant can authorise a branch and a
commit in a declared workspace. It cannot authorise pushing, opening a pull
request, changing infrastructure, or anything destructive -- those leave the
machine or cannot be undone, and each needs its own explicit human act rather
than riding along with "yes, implement this".

The addendum's rule, stated as code: agents may improve capabilities, agents
may not independently expand permissions.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterator, List, Optional

from .contracts import SideEffect

# The hard ceiling. Nothing raises this; a grant that wanted more would be a
# different kind of object with a different approval behind it.
MAX_GRANTED_SIDE_EFFECT = SideEffect.REPOSITORY_WRITE

DEFAULT_TTL_MINUTES = 60


@dataclass(frozen=True)
class ActionGrant:
    """Permission to write to one repository, for one run.

    `authority` records what the grant rests on -- the recommendation a human
    accepted -- so the audit log answers "who said this could happen" rather
    than only "it happened".
    """

    repository_id: str
    agent: str
    authority: str
    granted_by: str = "human"
    max_side_effect: SideEffect = MAX_GRANTED_SIDE_EFFECT
    expires_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        if self.max_side_effect.rank > MAX_GRANTED_SIDE_EFFECT.rank:
            raise ValueError(
                f"A grant cannot authorise {self.max_side_effect.value}. "
                f"The ceiling is {MAX_GRANTED_SIDE_EFFECT.value}: pushing, pull "
                "requests and destructive operations need their own approval."
            )

    @classmethod
    def for_recommendation(
        cls,
        repository_id: str,
        agent: str,
        recommendation_id: int,
        *,
        granted_by: str = "human",
        ttl_minutes: int = DEFAULT_TTL_MINUTES,
    ) -> "ActionGrant":
        return cls(
            repository_id=repository_id,
            agent=agent,
            authority=f"recommendation:{recommendation_id}",
            granted_by=granted_by,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes),
        )

    def active(self) -> bool:
        if self.expires_at is None:
            return True
        return datetime.now(timezone.utc) < self.expires_at

    def covers(
        self, agent: str, repository_id: Optional[str], side_effect: Optional[SideEffect]
    ) -> bool:
        if not self.active():
            return False
        if agent != self.agent or repository_id != self.repository_id:
            return False
        if side_effect is None:
            # An unclassified tool is not something a standing grant should
            # wave through.
            return False
        return side_effect.rank <= self.max_side_effect.rank

    def describe(self) -> str:
        return (
            f"{self.agent} may write to {self.repository_id} "
            f"under {self.authority}, granted by {self.granted_by}"
        )


@dataclass
class GrantBook:
    """The grants currently in force. Empty is the normal state."""

    grants: List[ActionGrant] = field(default_factory=list)

    def add(self, grant: ActionGrant) -> ActionGrant:
        self.grants.append(grant)
        return grant

    def remove(self, grant: ActionGrant) -> None:
        try:
            self.grants.remove(grant)
        except ValueError:
            pass

    def find(
        self, agent: str, repository_id: Optional[str], side_effect: Optional[SideEffect]
    ) -> Optional[ActionGrant]:
        for grant in self.grants:
            if grant.covers(agent, repository_id, side_effect):
                return grant
        return None

    def clear(self) -> None:
        self.grants.clear()

    @contextmanager
    def granted(self, grant: ActionGrant) -> Iterator[ActionGrant]:
        """Hold a grant for the body, and drop it however the body ends.

        The `finally` is the point. A grant that outlives its run is a
        standing write permission nobody remembers issuing.
        """
        self.add(grant)
        try:
            yield grant
        finally:
            self.remove(grant)
