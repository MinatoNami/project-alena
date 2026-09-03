"""Where everything is in the pipeline, and what is stuck.

The system moves work through six stages, and each hand-off is somewhere it
can quietly stop: research that is never ingested, observations nobody
reviews, recommendations nobody decides on, acceptances nobody implements.
None of those announce themselves -- a stalled stage looks exactly like a
quiet week.

So this counts what is sitting at each stage, and how long it has been
sitting. The ages are the useful part: "3 awaiting decision" is a working
system, "3 awaiting decision, oldest 24 days" is a queue nobody is reading.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from modules.store import get_connection

# How long something may sit at a stage before it is worth mentioning.
STALE_DAYS = {
    "unreviewed": 10,      # research ingested weekly; two missed cycles
    "unscored": 3,
    "undecided": 14,
    "unimplemented": 21,
    "unresolved": 30,      # implemented, but no outcome recorded
}

LAUNCHD_JOBS = ("local.alena.scan", "local.alena.review", "local.alena.recommend")


def _age_days(timestamp: Optional[str]) -> Optional[int]:
    if not timestamp:
        return None
    try:
        when = datetime.fromisoformat(timestamp)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - when).days


@dataclass
class Stage:
    name: str
    label: str
    count: int = 0
    oldest: Optional[str] = None
    examples: List[str] = field(default_factory=list)

    @property
    def oldest_days(self) -> Optional[int]:
        return _age_days(self.oldest)

    @property
    def stale(self) -> bool:
        limit = STALE_DAYS.get(self.name)
        age = self.oldest_days
        return bool(self.count and limit is not None and age is not None and age >= limit)

    def describe(self) -> str:
        if not self.count:
            return f"{self.label}: none"
        age = self.oldest_days
        suffix = f", oldest {age}d" if age else ""
        return f"{self.label}: {self.count}{suffix}"


def _stage(conn, name, label, sql, params=()) -> Stage:
    rows = list(conn.execute(sql, params))
    return Stage(
        name=name,
        label=label,
        count=len(rows),
        oldest=min((r["created_at"] for r in rows), default=None),
        examples=[f"{r['repository_id']} — {r['title']}" for r in rows[:3]],
    )


def pipeline(conn: Optional[sqlite3.Connection] = None) -> List[Stage]:
    """What is waiting at each hand-off."""
    conn = conn or get_connection()
    return [
        _stage(
            conn,
            "unreviewed",
            "Observations awaiting review",
            "SELECT o.repository_id, o.title, o.created_at FROM observations o"
            " WHERE o.duplicate_reason IS NULL AND NOT EXISTS"
            " (SELECT 1 FROM engineering_reviews r WHERE r.observation_id = o.id)"
            " ORDER BY o.created_at",
        ),
        _stage(
            conn,
            "unscored",
            "Reviewed, awaiting scoring",
            "SELECT o.repository_id, o.title, o.created_at FROM observations o"
            " WHERE EXISTS (SELECT 1 FROM engineering_reviews r"
            "               WHERE r.observation_id = o.id AND r.verdict != 'error')"
            " AND NOT EXISTS (SELECT 1 FROM recommendations c"
            "                 WHERE c.observation_id = o.id)"
            " ORDER BY o.created_at",
        ),
        _stage(
            conn,
            "undecided",
            "Recommendations awaiting your decision",
            "SELECT repository_id, title, created_at FROM recommendations"
            " WHERE status = 'recommended' ORDER BY created_at",
        ),
        _stage(
            conn,
            "unimplemented",
            "Accepted, awaiting implementation",
            "SELECT repository_id, title, decided_at AS created_at FROM recommendations"
            " WHERE status = 'accepted' ORDER BY decided_at",
        ),
        _stage(
            conn,
            "unresolved",
            "Implemented, awaiting an outcome",
            "SELECT repository_id, title, decided_at AS created_at FROM recommendations"
            " WHERE status = 'implemented' ORDER BY decided_at",
        ),
    ]


@dataclass
class Coverage:
    repositories: int = 0
    scanned: int = 0
    last_scan: Optional[str] = None
    research_documents: int = 0
    last_research: Optional[str] = None

    @property
    def last_scan_days(self) -> Optional[int]:
        return _age_days(self.last_scan)


def coverage(registry, conn: Optional[sqlite3.Connection] = None) -> Coverage:
    conn = conn or get_connection()
    repositories = registry.all()
    ids = [r.id for r in repositories]
    if not ids:
        return Coverage()

    placeholders = ",".join("?" for _ in ids)
    scanned = conn.execute(
        f"SELECT COUNT(DISTINCT repository_id), MAX(created_at) FROM scans"
        f" WHERE repository_id IN ({placeholders})",
        ids,
    ).fetchone()
    research = conn.execute(
        f"SELECT COUNT(*), MAX(created_at) FROM research_documents"
        f" WHERE repository_id IN ({placeholders})",
        ids,
    ).fetchone()

    return Coverage(
        repositories=len(repositories),
        scanned=scanned[0] or 0,
        last_scan=scanned[1],
        research_documents=research[0] or 0,
        last_research=research[1],
    )


@dataclass
class Job:
    label: str
    loaded: bool
    last_exit: Optional[int] = None
    running: bool = False
    log: Optional[Path] = None

    def describe(self) -> str:
        if not self.loaded:
            return f"{self.label}: not installed"
        if self.running:
            return f"{self.label}: running now"
        if self.last_exit is None:
            return f"{self.label}: loaded, has not run yet"
        if self.last_exit == 0:
            return f"{self.label}: last run ok"
        return f"{self.label}: last run FAILED (exit {self.last_exit})"

    @property
    def failing(self) -> bool:
        return bool(self.loaded and self.last_exit not in (None, 0))


def jobs() -> List[Job]:
    """What launchd thinks of the scheduled jobs.

    Empty when launchctl is not available, because nothing here should depend
    on the machine being a Mac with a schedule installed.
    """
    if not shutil.which("launchctl"):
        return []

    found: List[Job] = []
    logs = Path.home() / ".alena" / "logs"
    for label in LAUNCHD_JOBS:
        try:
            result = subprocess.run(
                ["launchctl", "print", f"gui/{os.getuid()}/{label}"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue

        if result.returncode != 0:
            found.append(Job(label, loaded=False))
            continue

        exit_code: Optional[int] = None
        for line in result.stdout.splitlines():
            if "last exit code" in line:
                value = line.split("=", 1)[-1].strip()
                exit_code = int(value) if value.isdigit() else None
        found.append(
            Job(
                label,
                loaded=True,
                last_exit=exit_code,
                running="state = running" in result.stdout,
                log=logs / f"{label.split('.')[-1]}.log",
            )
        )
    return found


def stranded(registry, conn: Optional[sqlite3.Connection] = None) -> List[Dict[str, Any]]:
    """Observations whose only review errored.

    They will not be picked up again without --retry-failed, and nothing else
    in the system mentions them -- which is how a broken agent turns into a
    silently shrinking queue.
    """
    from .persistence import observations_with_failed_reviews

    found: List[Dict[str, Any]] = []
    for repository in registry.all():
        found.extend(observations_with_failed_reviews(repository.id, conn))
    return found


def summary(registry, conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    stages = pipeline(conn)
    return {
        "coverage": coverage(registry, conn),
        "stages": stages,
        "jobs": jobs(),
        "stranded": stranded(registry, conn),
        "waiting_on_you": next(s for s in stages if s.name == "undecided").count,
        "stalled": [s for s in stages if s.stale],
    }
