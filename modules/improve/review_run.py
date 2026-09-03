"""Run engineering review over a repository's unreviewed observations,
then synthesise and render what survives.

Two commands' worth of orchestration, kept together because they share the
same shape: resolve the repository, build the shared context once, iterate.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from modules.core.controller.logger import logger

from .agents.codex_review import review_observation
from .context_package import build_context_package
from .persistence import (
    latest_scan,
    observations_for,
    recommendations_by_status,
    recommendations_for,
    record_review,
    upsert_repository,
)
from .recommend.render import render_report, write_report
from .recommend.synthesize import synthesize_observation
from .registry import Repository

MAX_CONTEXT_CHARS = 6000


@dataclass
class ReviewRun:
    repository_id: str
    reviewed: List[str] = field(default_factory=list)
    failed: List[str] = field(default_factory=list)
    skipped: int = 0

    def describe(self) -> str:
        parts = [f"{len(self.reviewed)} reviewed"]
        if self.failed:
            parts.append(f"{len(self.failed)} failed")
        if self.skipped:
            parts.append(f"{self.skipped} already reviewed")
        return f"{self.repository_id}: {', '.join(parts)}"


def _context_text(repository: Repository, scan: Optional[Dict[str, Any]]) -> str:
    """A short brief for the reviewer, not the whole package.

    The full `.context/` directory is on disk for an agent that wants to read
    it; pasting all of it into every prompt would spend the context window on
    material the agent can see by looking at the repository itself.
    """
    scan = scan or {}
    parts = []
    if scan.get("summary"):
        parts.append(scan["summary"])
    languages = ", ".join((scan.get("languages") or {}).keys())
    if languages:
        parts.append(f"Languages: {languages}")
    dependencies = [d["name"] for d in (scan.get("dependencies") or [])][:40]
    if dependencies:
        parts.append(f"Declared dependencies: {', '.join(dependencies)}")
    return "\n\n".join(parts)[:MAX_CONTEXT_CHARS]


async def review_repository_async(
    repository: Repository,
    *,
    limit: Optional[int] = None,
    executor=None,
    conn=None,
) -> ReviewRun:
    repository.require("analyze")
    upsert_repository(repository, conn)
    run = ReviewRun(repository.id)

    observations = observations_for(
        repository.id, unreviewed_only=True, conn=conn
    )
    if limit:
        observations = observations[:limit]
    if not observations:
        return run

    scan = latest_scan(repository.id, conn)
    context = _context_text(repository, scan)
    rejected = recommendations_by_status(repository.id, conn)["rejected"]
    build_context_package(repository, conn=conn)

    for observation in observations:
        result = await review_observation(
            repository,
            observation,
            context=context,
            rejected=rejected,
            executor=executor,
        )
        record_review(
            observation_id=observation["id"],
            repository_id=repository.id,
            agent="codex",
            verdict=result.verdict,
            confidence=result.confidence,
            fit=result.fit,
            cost=result.cost,
            risk=result.risk,
            body=result.body or (result.error or ""),
            conn=conn,
        )
        if result.ok:
            run.reviewed.append(observation["title"])
        else:
            run.failed.append(observation["title"])
            logger.warning(f"{repository.id}: review failed — {result.error}")

    return run


def review_repository(repository: Repository, **kwargs) -> ReviewRun:
    return asyncio.run(review_repository_async(repository, **kwargs))


@dataclass
class RecommendRun:
    repository_id: str
    written: List[Path] = field(default_factory=list)
    count: int = 0
    duplicates: int = 0
    rejected: int = 0

    def describe(self) -> str:
        parts = [f"{self.count} recommendation(s)"]
        if self.rejected:
            parts.append(f"{self.rejected} rejected by review")
        if self.duplicates:
            parts.append(f"{self.duplicates} duplicate(s) skipped")
        return f"{self.repository_id}: {', '.join(parts)}"


def recommend_repository(
    repository: Repository, root: Optional[Path] = None, conn=None
) -> RecommendRun:
    """Score every reviewed observation and write the report."""
    upsert_repository(repository, conn)
    scan = latest_scan(repository.id, conn)
    summary = (scan or {}).get("summary")

    for observation in observations_for(repository.id, conn=conn):
        synthesize_observation(repository, observation, summary, conn=conn)

    rows = recommendations_for(repository.id, "recommended", conn=conn)
    for row in rows:
        if row.get("score_breakdown"):
            try:
                row["score_breakdown_parsed"] = json.loads(row["score_breakdown"])
            except json.JSONDecodeError:
                row["score_breakdown_parsed"] = {}

    duplicates = [
        o
        for o in observations_for(repository.id, include_duplicates=True, conn=conn)
        if o.get("duplicate_reason")
    ]
    rejected = recommendations_for(repository.id, "rejected", conn=conn)

    text = render_report(repository.name, repository.id, rows, duplicates, rejected)
    written = write_report(repository.id, text, root)

    return RecommendRun(
        repository.id,
        written=written,
        count=len(rows),
        duplicates=len(duplicates),
        rejected=len(rejected),
    )
