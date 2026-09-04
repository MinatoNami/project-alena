"""The human approval gate.

No recommendation becomes production code without passing through here, and
the transitions are a closed set rather than an UPDATE anyone can make. Two
things this is strict about.

**A rejection needs a reason.** The spec says so, and the reason is not
paperwork: it goes into the context package, into the next reviewer's prompt,
and into de-duplication. A rejection without a reason means the same idea
arrives again next month with nothing to recognise it by.

**A decision is appended, not overwritten.** "Accepted, then abandoned three
weeks later" is a different fact from "abandoned", and only one of them
survives an UPDATE.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Dict, Optional, Set

from modules.store import get_connection

from .artifacts import utcnow

RECOMMENDED = "recommended"
ACCEPTED = "accepted"
REJECTED = "rejected"
IMPLEMENTED = "implemented"
ABANDONED = "abandoned"
SUCCESSFUL = "successful"
UNSUCCESSFUL = "unsuccessful"

# Terminal except for the two that can be revisited. A rejection made when
# the product was less mature is exactly the kind that gets reconsidered --
# the spec's report offers Accept, Reject and Revisit. And a failed attempt
# is a fact about the attempt, not about the idea: "that did not work" has to
# be able to lead to "try it again", or the first bad implementation buries a
# good recommendation for good.
TRANSITIONS: Dict[str, Set[str]] = {
    RECOMMENDED: {ACCEPTED, REJECTED},
    ACCEPTED: {IMPLEMENTED, ABANDONED, REJECTED},
    REJECTED: {RECOMMENDED},
    IMPLEMENTED: {SUCCESSFUL, UNSUCCESSFUL, ABANDONED},
    SUCCESSFUL: set(),
    UNSUCCESSFUL: {ACCEPTED, ABANDONED},
    ABANDONED: set(),
}

REASON_REQUIRED = {REJECTED, ABANDONED, UNSUCCESSFUL}


class DecisionError(ValueError):
    """The transition is not allowed, or is missing something it needs."""


@dataclass(frozen=True)
class Decision:
    recommendation_id: int
    repository_id: str
    from_status: str
    to_status: str
    reason: Optional[str] = None
    actor: str = "human"

    def describe(self) -> str:
        detail = f" — {self.reason}" if self.reason else ""
        return (
            f"#{self.recommendation_id} {self.from_status} → {self.to_status}"
            f"{detail}"
        )


def get_recommendation(
    repository_id: str, recommendation_id: int, conn: Optional[sqlite3.Connection] = None
) -> Dict[str, Any]:
    conn = conn or get_connection()
    row = conn.execute(
        "SELECT * FROM recommendations WHERE id = ? AND repository_id = ?",
        (recommendation_id, repository_id),
    ).fetchone()
    if row is None:
        raise DecisionError(
            f"No recommendation #{recommendation_id} for {repository_id}"
        )
    return dict(row)


def check_transition(from_status: str, to_status: str, reason: Optional[str]) -> None:
    allowed = TRANSITIONS.get(from_status)
    if allowed is None:
        raise DecisionError(f"Unknown status: {from_status!r}")
    if to_status not in allowed:
        options = ", ".join(sorted(allowed)) or "nothing; it is terminal"
        raise DecisionError(
            f"Cannot go from {from_status} to {to_status}. From {from_status} "
            f"the options are: {options}"
        )
    if to_status in REASON_REQUIRED and not (reason or "").strip():
        raise DecisionError(
            f"Moving to {to_status} requires a reason. It goes into the context "
            "package and the next reviewer's prompt -- without it the same idea "
            "comes back with nothing to recognise it by."
        )


def decide(
    repository_id: str,
    recommendation_id: int,
    to_status: str,
    *,
    reason: Optional[str] = None,
    actor: str = "human",
    actual_effort: Optional[str] = None,
    observed_value: Optional[float] = None,
    feedback: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> Decision:
    """Record a decision, refusing anything the state machine does not allow."""
    conn = conn or get_connection()
    recommendation = get_recommendation(repository_id, recommendation_id, conn)
    from_status = recommendation["status"]

    check_transition(from_status, to_status, reason)

    now = utcnow()
    conn.execute(
        "UPDATE recommendations SET status = ?, reason = COALESCE(?, reason),"
        " updated_at = ?, decided_at = ?, decided_by = ?,"
        " actual_effort = COALESCE(?, actual_effort),"
        " observed_value = COALESCE(?, observed_value),"
        " expected_value = COALESCE(expected_value, score),"
        " human_feedback = COALESCE(?, human_feedback)"
        " WHERE id = ?",
        (
            to_status,
            reason,
            now,
            now,
            actor,
            actual_effort,
            observed_value,
            feedback,
            recommendation_id,
        ),
    )
    conn.execute(
        "INSERT INTO decisions (recommendation_id, repository_id, created_at,"
        " from_status, to_status, reason, actor) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (recommendation_id, repository_id, now, from_status, to_status, reason, actor),
    )
    conn.commit()

    return Decision(
        recommendation_id=recommendation_id,
        repository_id=repository_id,
        from_status=from_status,
        to_status=to_status,
        reason=reason,
        actor=actor,
    )


def history(
    recommendation_id: int, conn: Optional[sqlite3.Connection] = None
) -> list:
    conn = conn or get_connection()
    return [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM decisions WHERE recommendation_id = ? ORDER BY id",
            (recommendation_id,),
        )
    ]
