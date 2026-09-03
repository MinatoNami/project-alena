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

# ---------------------------------------------------------------------------
# Research, observations and reviews
# ---------------------------------------------------------------------------


def recommendations_by_status(
    repository_id: str, conn: Optional[sqlite3.Connection] = None
) -> Dict[str, List[Dict[str, Any]]]:
    """Prior recommendations, grouped for the context package."""
    conn = conn or get_connection()
    rows = [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM recommendations WHERE repository_id = ?"
            " ORDER BY updated_at DESC",
            (repository_id,),
        )
    ]
    return {
        "all": rows,
        "accepted": [r for r in rows if r["status"] == "accepted"],
        "rejected": [r for r in rows if r["status"] == "rejected"],
    }


def priors_for_dedup(
    repository_id: str, conn: Optional[sqlite3.Connection] = None
) -> List[Any]:
    """Everything already proposed, as dedup wants it.

    Both decided recommendations and observations still waiting for review.
    Leaving the pending ones out would let the same idea arrive in two research
    documents and be reviewed twice before anything had a chance to notice.
    """
    from .recommend.dedup import PriorRecommendation

    conn = conn or get_connection()
    priors = [
        PriorRecommendation(
            id=row["id"],
            title=row["title"],
            normalized_title=row["normalized_title"],
            status=row["status"],
            reason=row["reason"],
            body=row["body"],
            embedding=row["embedding"],
            kind="recommendation",
        )
        for row in conn.execute(
            "SELECT id, title, normalized_title, status, reason, body, embedding"
            " FROM recommendations WHERE repository_id = ?",
            (repository_id,),
        )
    ]
    priors += [
        PriorRecommendation(
            id=row["id"],
            title=row["title"],
            normalized_title=row["normalized_title"],
            status="awaiting review",
            reason=None,
            body=row["body"],
            embedding=row["embedding"],
            kind="observation",
        )
        for row in conn.execute(
            "SELECT o.id, o.title, o.normalized_title, o.body, o.embedding"
            " FROM observations o"
            " WHERE o.repository_id = ? AND o.duplicate_reason IS NULL"
            " AND NOT EXISTS (SELECT 1 FROM recommendations r"
            "                 WHERE r.observation_id = o.id)",
            (repository_id,),
        )
    ]
    return priors


def record_research(
    *,
    repository_id: str,
    source: str,
    content: str,
    content_hash: str,
    title: Optional[str] = None,
    document_date: Optional[str] = None,
    path: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> tuple[int, bool]:
    """Store a research document. Returns (id, created).

    Re-ingesting the same file is a no-op rather than an error: a watched drop
    directory will hand us the same document more than once.
    """
    conn = conn or get_connection()
    existing = conn.execute(
        "SELECT id FROM research_documents WHERE repository_id = ? AND content_hash = ?",
        (repository_id, content_hash),
    ).fetchone()
    if existing is not None:
        return int(existing["id"]), False

    cursor = conn.execute(
        """
        INSERT INTO research_documents
            (repository_id, created_at, source, title, document_date, path,
             content, content_hash)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            repository_id,
            utcnow(),
            source,
            title,
            document_date,
            path,
            content,
            content_hash,
        ),
    )
    conn.commit()
    return int(cursor.lastrowid), True


def record_observation(
    *,
    research_id: int,
    repository_id: str,
    title: str,
    normalized_title: str,
    body: Optional[str],
    evidence: Optional[str],
    duplicate_of: Optional[int] = None,
    duplicate_reason: Optional[str] = None,
    similarity: float = 0.0,
    embedding: Optional[bytes] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> int:
    conn = conn or get_connection()
    cursor = conn.execute(
        """
        INSERT INTO observations
            (research_id, repository_id, created_at, title, normalized_title,
             body, evidence, duplicate_of, duplicate_reason, similarity, embedding)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            research_id,
            repository_id,
            utcnow(),
            title,
            normalized_title,
            body,
            evidence,
            duplicate_of,
            duplicate_reason,
            similarity,
            embedding,
        ),
    )
    conn.commit()
    return int(cursor.lastrowid)


def observations_for(
    repository_id: str,
    *,
    include_duplicates: bool = False,
    unreviewed_only: bool = False,
    retry_failed: bool = False,
    conn: Optional[sqlite3.Connection] = None,
) -> List[Dict[str, Any]]:
    conn = conn or get_connection()
    sql = ["SELECT o.* FROM observations o WHERE o.repository_id = ?"]
    if not include_duplicates:
        sql.append("AND o.duplicate_of IS NULL AND o.duplicate_reason IS NULL")
    if unreviewed_only:
        # An errored review still counts as an attempt, so a permanently
        # broken agent is not retried every run. `retry_failed` is the way
        # back once the cause is fixed -- and `status` reports how many
        # observations are sitting in that state, because otherwise it is
        # silent.
        clause = (
            "AND NOT EXISTS (SELECT 1 FROM engineering_reviews r"
            " WHERE r.observation_id = o.id"
        )
        if retry_failed:
            clause += " AND r.verdict != 'error'"
        sql.append(clause + ")")
    sql.append("ORDER BY o.id")
    return [dict(row) for row in conn.execute(" ".join(sql), (repository_id,))]


def observations_with_failed_reviews(
    repository_id: str, conn: Optional[sqlite3.Connection] = None
) -> List[Dict[str, Any]]:
    """Observations whose only reviews errored.

    Stranded: they will not be picked up again without --retry-failed.
    """
    conn = conn or get_connection()
    return [
        dict(row)
        for row in conn.execute(
            "SELECT o.* FROM observations o WHERE o.repository_id = ?"
            " AND o.duplicate_reason IS NULL"
            " AND EXISTS (SELECT 1 FROM engineering_reviews r"
            "             WHERE r.observation_id = o.id AND r.verdict = 'error')"
            " AND NOT EXISTS (SELECT 1 FROM engineering_reviews r"
            "                 WHERE r.observation_id = o.id AND r.verdict != 'error')"
            " ORDER BY o.id",
            (repository_id,),
        )
    ]


def record_review(
    *,
    observation_id: int,
    repository_id: str,
    agent: str,
    verdict: str,
    confidence: Optional[float] = None,
    fit: Optional[float] = None,
    cost: Optional[float] = None,
    risk: Optional[float] = None,
    value: Optional[float] = None,
    body: Optional[str] = None,
    path: Optional[str] = None,
    requires_architecture_review: Optional[bool] = None,
    security_sensitive: Optional[bool] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> int:
    conn = conn or get_connection()
    cursor = conn.execute(
        """
        INSERT INTO engineering_reviews
            (observation_id, repository_id, created_at, agent, verdict,
             confidence, fit, cost, risk, value, body, path,
             requires_architecture_review, security_sensitive)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            observation_id,
            repository_id,
            utcnow(),
            agent,
            verdict,
            confidence,
            fit,
            cost,
            risk,
            value,
            body,
            path,
            # Stored as tri-state: NULL means the reviewer did not say.
            None if requires_architecture_review is None else int(bool(requires_architecture_review)),
            None if security_sensitive is None else int(bool(security_sensitive)),
        ),
    )
    conn.commit()
    return int(cursor.lastrowid)


def set_escalation_reason(
    observation_id: int, reason: Optional[str], conn: Optional[sqlite3.Connection] = None
) -> None:
    """Record why a candidate was sent for a second opinion.

    Kept so the thresholds can be tuned later against which escalations turned
    out to be worth their cost.
    """
    conn = conn or get_connection()
    conn.execute(
        "UPDATE observations SET escalation_reason = ? WHERE id = ?",
        (reason, observation_id),
    )
    conn.commit()


def observations_with_reviews(
    repository_id: str, conn: Optional[sqlite3.Connection] = None
) -> List[tuple]:
    """Every observation that has been reviewed, with its reviews."""
    conn = conn or get_connection()
    observations = observations_for(repository_id, conn=conn)
    return [(o, reviews_for(o["id"], conn)) for o in observations]


def reviews_for(
    observation_id: int, conn: Optional[sqlite3.Connection] = None
) -> List[Dict[str, Any]]:
    conn = conn or get_connection()
    return [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM engineering_reviews WHERE observation_id = ? ORDER BY id",
            (observation_id,),
        )
    ]


def upsert_recommendation(
    *,
    repository_id: str,
    observation_id: int,
    title: str,
    normalized_title: str,
    body: str,
    score: Optional[float] = None,
    confidence: Optional[float] = None,
    estimated_effort: Optional[str] = None,
    score_breakdown: Optional[dict] = None,
    embedding: Optional[bytes] = None,
    status: str = "recommended",
    reason: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> int:
    """Write the recommendation for an observation, replacing any earlier one.

    Keyed on the observation rather than the title: re-running synthesis after
    a better review should update the recommendation, not add a second one.
    A human decision already recorded against it is left alone.
    """
    conn = conn or get_connection()
    now = utcnow()
    existing = conn.execute(
        "SELECT id, status FROM recommendations WHERE observation_id = ?",
        (observation_id,),
    ).fetchone()

    if existing is not None:
        if existing["status"] != "recommended":
            # A human has decided on this one; synthesis does not overwrite it.
            return int(existing["id"])
        conn.execute(
            "UPDATE recommendations SET updated_at = ?, title = ?,"
            " normalized_title = ?, body = ?, score = ?, confidence = ?,"
            " estimated_effort = ?, score_breakdown = ?, embedding = ?,"
            " status = ?, reason = ? WHERE id = ?",
            (
                now,
                title,
                normalized_title,
                body,
                score,
                confidence,
                estimated_effort,
                _json(score_breakdown) if score_breakdown else None,
                embedding,
                status,
                reason,
                existing["id"],
            ),
        )
        conn.commit()
        return int(existing["id"])

    cursor = conn.execute(
        """
        INSERT INTO recommendations
            (repository_id, created_at, updated_at, title, normalized_title,
             body, status, reason, score, confidence, estimated_effort,
             score_breakdown, embedding, observation_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            repository_id,
            now,
            now,
            title,
            normalized_title,
            body,
            status,
            reason,
            score,
            confidence,
            estimated_effort,
            _json(score_breakdown) if score_breakdown else None,
            embedding,
            observation_id,
        ),
    )
    conn.commit()
    return int(cursor.lastrowid)


def recommendations_for(
    repository_id: str,
    status: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> List[Dict[str, Any]]:
    conn = conn or get_connection()
    if status:
        rows = conn.execute(
            "SELECT * FROM recommendations WHERE repository_id = ? AND status = ?"
            " ORDER BY score DESC, id",
            (repository_id, status),
        )
    else:
        rows = conn.execute(
            "SELECT * FROM recommendations WHERE repository_id = ?"
            " ORDER BY score DESC, id",
            (repository_id,),
        )
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# Implementations
# ---------------------------------------------------------------------------


def record_implementation(
    *,
    recommendation_id: int,
    repository_id: str,
    implemented_by: str,
    reviewed_by: Optional[str] = None,
    branch: Optional[str] = None,
    base_branch: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> int:
    """Open an implementation record before anything is written.

    Before, not after: a run that dies halfway leaves a branch on disk, and the
    row is how you find out which one.
    """
    conn = conn or get_connection()
    cursor = conn.execute(
        "INSERT INTO implementations (recommendation_id, repository_id,"
        " created_at, implemented_by, reviewed_by, branch, base_branch, status)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, 'started')",
        (
            recommendation_id,
            repository_id,
            utcnow(),
            implemented_by,
            reviewed_by,
            branch,
            base_branch,
        ),
    )
    conn.commit()
    return int(cursor.lastrowid)


def update_implementation(
    implementation_id: int,
    *,
    status: Optional[str] = None,
    commit_sha: Optional[str] = None,
    files_changed: Optional[List[str]] = None,
    tests_command: Optional[str] = None,
    tests_passed: Optional[bool] = None,
    tests_output: Optional[str] = None,
    review_verdict: Optional[str] = None,
    review_body: Optional[str] = None,
    pushed: Optional[bool] = None,
    pull_request_url: Optional[str] = None,
    error: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> None:
    conn = conn or get_connection()
    fields = {
        "status": status,
        "commit_sha": commit_sha,
        "files_changed": _json(files_changed) if files_changed is not None else None,
        "tests_command": tests_command,
        "tests_passed": None if tests_passed is None else int(tests_passed),
        "tests_output": tests_output,
        "review_verdict": review_verdict,
        "review_body": review_body,
        "pushed": None if pushed is None else int(pushed),
        "pull_request_url": pull_request_url,
        "error": error,
    }
    assignments = [f"{k} = ?" for k, v in fields.items() if v is not None]
    if not assignments:
        return
    conn.execute(
        f"UPDATE implementations SET {', '.join(assignments)} WHERE id = ?",
        [v for v in fields.values() if v is not None] + [implementation_id],
    )
    conn.commit()


def implementations_for(
    recommendation_id: int, conn: Optional[sqlite3.Connection] = None
) -> List[Dict[str, Any]]:
    conn = conn or get_connection()
    return [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM implementations WHERE recommendation_id = ?"
            " ORDER BY id DESC",
            (recommendation_id,),
        )
    ]
