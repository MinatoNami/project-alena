"""Reading and writing repository intelligence in SQLite.

Structured state lives here; the markdown under alena-intelligence/ is the
rendered view of it. Keeping both means a human can read a profile and the
orchestrator can still ask "what changed since the last scan" without parsing
prose.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List, Optional

from modules.store import get_connection

from .artifacts import utcnow
from .registry import Repository


def _json(value: Any) -> str:
    return json.dumps(value, default=str)


def _loads(raw: Optional[str], fallback: Any) -> Any:
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return fallback


def upsert_repository(
    repository: Repository, conn: Optional[sqlite3.Connection] = None
) -> None:
    conn = conn or get_connection()
    now = utcnow()
    conn.execute(
        """
        INSERT INTO repositories
            (id, name, workspace, default_branch, tags, first_seen_at, last_seen_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (id) DO UPDATE SET
            name = excluded.name,
            workspace = excluded.workspace,
            default_branch = excluded.default_branch,
            tags = excluded.tags,
            last_seen_at = excluded.last_seen_at
        """,
        (
            repository.id,
            repository.name,
            str(repository.workspace),
            repository.default_branch,
            _json(repository.tags),
            now,
            now,
        ),
    )
    conn.commit()


def latest_scan(
    repository_id: str, conn: Optional[sqlite3.Connection] = None
) -> Optional[Dict[str, Any]]:
    conn = conn or get_connection()
    row = conn.execute(
        "SELECT * FROM scans WHERE repository_id = ? ORDER BY id DESC LIMIT 1",
        (repository_id,),
    ).fetchone()
    return _row_to_scan(row) if row is not None else None


def _row_to_scan(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "repository_id": row["repository_id"],
        "scanned_at": row["created_at"],
        "fingerprint": row["fingerprint"],
        "head_sha": row["head_sha"],
        "branch": row["branch"],
        "dirty": bool(row["dirty"]),
        "changed": bool(row["changed"]),
        "file_count": row["file_count"],
        "languages": _loads(row["languages"], {}),
        "dependencies": _loads(row["dependencies"], []),
        "todos": _loads(row["todos"], []),
        "recent_commits": _loads(row["recent_commits"], []),
        "summary": row["summary"],
        "diff_summary": row["diff_summary"],
    }


def record_scan(
    scan: Dict[str, Any], conn: Optional[sqlite3.Connection] = None
) -> int:
    """Insert a scan, or refresh the existing row for that fingerprint.

    A forced re-scan of an unchanged repository produces the same fingerprint,
    and the unique index is what stops that filling the table with identical
    rows -- the newer summary replaces the older one instead.
    """
    conn = conn or get_connection()
    cursor = conn.execute(
        """
        INSERT INTO scans (
            repository_id, created_at, fingerprint, head_sha, branch, dirty,
            changed, file_count, languages, dependencies, todos,
            recent_commits, summary, diff_summary
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (repository_id, fingerprint) DO UPDATE SET
            created_at = excluded.created_at,
            dirty = excluded.dirty,
            file_count = excluded.file_count,
            languages = excluded.languages,
            dependencies = excluded.dependencies,
            todos = excluded.todos,
            recent_commits = excluded.recent_commits,
            summary = COALESCE(excluded.summary, scans.summary),
            diff_summary = COALESCE(excluded.diff_summary, scans.diff_summary)
        """,
        (
            scan["repository_id"],
            scan["scanned_at"],
            scan["fingerprint"],
            scan.get("head_sha"),
            scan.get("branch"),
            int(bool(scan.get("dirty"))),
            int(bool(scan.get("changed", True))),
            scan.get("file_count"),
            _json(scan.get("languages") or {}),
            _json(scan.get("dependencies") or []),
            _json(scan.get("todos") or []),
            _json(scan.get("recent_commits") or []),
            scan.get("summary"),
            scan.get("diff_summary"),
        ),
    )
    conn.commit()
    if cursor.lastrowid:
        return int(cursor.lastrowid)
    row = conn.execute(
        "SELECT id FROM scans WHERE repository_id = ? AND fingerprint = ?",
        (scan["repository_id"], scan["fingerprint"]),
    ).fetchone()
    return int(row["id"]) if row else 0


def scan_history(
    repository_id: str, limit: int = 10, conn: Optional[sqlite3.Connection] = None
) -> List[Dict[str, Any]]:
    conn = conn or get_connection()
    rows = conn.execute(
        "SELECT * FROM scans WHERE repository_id = ? ORDER BY id DESC LIMIT ?",
        (repository_id, limit),
    )
    return [_row_to_scan(row) for row in rows]


def rejected_recommendations(
    repository_id: str, conn: Optional[sqlite3.Connection] = None
) -> List[Dict[str, Any]]:
    """Ideas already turned down, with the reason.

    Nothing writes these until Phase 2. The reader exists now because the
    reason a recommendation was rejected has to reach the prompt that generates
    the next one -- re-suggesting rejected work is the failure mode the specs
    lead with.
    """
    conn = conn or get_connection()
    rows = conn.execute(
        "SELECT title, normalized_title, reason, updated_at FROM recommendations"
        " WHERE repository_id = ? AND status = 'rejected' ORDER BY updated_at DESC",
        (repository_id,),
    )
    return [dict(row) for row in rows]
