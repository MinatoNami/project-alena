"""One timeline of everything the system has done.

The record already exists, spread across five tables that each answer a
different question. This assembles them into the one question nobody could ask
before: *what has actually happened here, in order.*

Scans and reviews are the bulk of it. Research, decisions and implementations
are included because a review with no visible outcome is half a story -- the
useful reading is "this was reviewed, then rejected, then proposed again",
which needs all five to be legible.

Read-only, and derived entirely from what is already stored. Nothing here is
a second source of truth.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from modules.store import get_connection

SCAN = "scan"
RESEARCH = "research"
REVIEW = "review"
DECISION = "decision"
IMPLEMENTATION = "implementation"

KINDS = (SCAN, RESEARCH, REVIEW, DECISION, IMPLEMENTATION)

DEFAULT_LIMIT = 100


@dataclass
class Event:
    kind: str
    at: str
    repository_id: str
    summary: str
    detail: Optional[str] = None
    # Whether this went the unhappy way. Drawn once here so every consumer
    # agrees on what counts as bad news.
    adverse: bool = False
    reference: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "at": self.at,
            "repository_id": self.repository_id,
            "summary": self.summary,
            "detail": self.detail,
            "adverse": self.adverse,
            "reference": self.reference,
        }


def _scans(conn, repository_id: Optional[str]) -> List[Event]:
    sql = "SELECT * FROM scans"
    params: tuple = ()
    if repository_id:
        sql += " WHERE repository_id = ?"
        params = (repository_id,)

    events = []
    for row in conn.execute(sql, params):
        head = (row["head_sha"] or "")[:8]
        events.append(
            Event(
                kind=SCAN,
                at=row["created_at"],
                repository_id=row["repository_id"],
                summary=f"Scanned {row['file_count'] or 0} files on {row['branch'] or '?'}",
                detail=(row["summary"] or "").strip()[:400] or None,
                reference={"head_sha": head, "dirty": bool(row["dirty"])},
            )
        )
    return events


def _research(conn, repository_id: Optional[str]) -> List[Event]:
    sql = "SELECT * FROM research_documents"
    params: tuple = ()
    if repository_id:
        sql += " WHERE repository_id = ?"
        params = (repository_id,)

    events = []
    for row in conn.execute(sql, params):
        origin = row["source"] or "unknown"
        events.append(
            Event(
                kind=RESEARCH,
                at=row["created_at"],
                repository_id=row["repository_id"],
                summary=(
                    f"Proposed by {origin}: {row['title']}"
                    if origin == "operator"
                    else f"Research ingested from {origin}"
                ),
                detail=row["title"] if origin != "operator" else None,
                reference={"source": origin},
            )
        )
    return events


def _reviews(conn, repository_id: Optional[str]) -> List[Event]:
    sql = (
        "SELECT r.*, o.title AS observation_title FROM engineering_reviews r"
        " LEFT JOIN observations o ON o.id = r.observation_id"
    )
    params: tuple = ()
    if repository_id:
        sql += " WHERE r.repository_id = ?"
        params = (repository_id,)

    events = []
    for row in conn.execute(sql, params):
        confidence = (
            f", {row['confidence'] * 100:.0f}% confident"
            if row["confidence"] is not None
            else ""
        )
        events.append(
            Event(
                kind=REVIEW,
                at=row["created_at"],
                repository_id=row["repository_id"],
                summary=f"{row['agent']} said {row['verdict']}{confidence}",
                detail=row["observation_title"],
                adverse=row["verdict"] in ("rejected", "error"),
                reference={
                    "agent": row["agent"],
                    "verdict": row["verdict"],
                    "observation_id": row["observation_id"],
                },
            )
        )
    return events


def _decisions(conn, repository_id: Optional[str]) -> List[Event]:
    sql = (
        "SELECT d.*, c.title FROM decisions d"
        " LEFT JOIN recommendations c ON c.id = d.recommendation_id"
    )
    params: tuple = ()
    if repository_id:
        sql += " WHERE d.repository_id = ?"
        params = (repository_id,)

    events = []
    for row in conn.execute(sql, params):
        reason = f" — {row['reason']}" if row["reason"] else ""
        events.append(
            Event(
                kind=DECISION,
                at=row["created_at"],
                repository_id=row["repository_id"],
                summary=f"{row['actor']}: {row['from_status']} → {row['to_status']}{reason}",
                detail=row["title"],
                adverse=row["to_status"] in ("rejected", "abandoned", "unsuccessful"),
                reference={
                    "recommendation_id": row["recommendation_id"],
                    "to_status": row["to_status"],
                },
            )
        )
    return events


def _implementations(conn, repository_id: Optional[str]) -> List[Event]:
    sql = (
        "SELECT i.*, c.title FROM implementations i"
        " LEFT JOIN recommendations c ON c.id = i.recommendation_id"
    )
    params: tuple = ()
    if repository_id:
        sql += " WHERE i.repository_id = ?"
        params = (repository_id,)

    events = []
    for row in conn.execute(sql, params):
        tests = (
            "tests passed"
            if row["tests_passed"]
            else "tests failed" if row["tests_passed"] == 0 else "tests not run"
        )
        events.append(
            Event(
                kind=IMPLEMENTATION,
                at=row["created_at"],
                repository_id=row["repository_id"],
                summary=f"{row['implemented_by']} wrote {row['branch']} — {row['status']}, {tests}",
                detail=row["title"],
                adverse=row["status"] == "failed" or row["tests_passed"] == 0,
                reference={
                    "branch": row["branch"],
                    "review_verdict": row["review_verdict"],
                    "pushed": bool(row["pushed"]),
                },
            )
        )
    return events


_SOURCES = {
    SCAN: _scans,
    RESEARCH: _research,
    REVIEW: _reviews,
    DECISION: _decisions,
    IMPLEMENTATION: _implementations,
}


def timeline(
    repository_id: Optional[str] = None,
    kinds: Optional[Sequence[str]] = None,
    limit: int = DEFAULT_LIMIT,
    conn: Optional[sqlite3.Connection] = None,
) -> List[Event]:
    """Everything that happened, newest first."""
    conn = conn or get_connection()
    wanted = [k for k in (kinds or KINDS) if k in _SOURCES]

    events: List[Event] = []
    for kind in wanted:
        events.extend(_SOURCES[kind](conn, repository_id))

    # Timestamps are ISO-8601 UTC throughout, so sorting the strings sorts the
    # instants -- no parsing, and no failure on a row written by an older
    # version with a slightly different format.
    events.sort(key=lambda e: e.at or "", reverse=True)
    return events[:limit]


def counts(
    repository_id: Optional[str] = None, conn: Optional[sqlite3.Connection] = None
) -> Dict[str, int]:
    conn = conn or get_connection()
    return {
        kind: len(source(conn, repository_id)) for kind, source in _SOURCES.items()
    }
