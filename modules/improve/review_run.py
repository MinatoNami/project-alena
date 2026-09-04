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

from .agents import claude_review
from .agents.codex_review import review_observation
from .agents.triggers import candidate_from_rows, should_escalate
from .context_package import build_context_package
from .persistence import (
    latest_scan,
    observations_for,
    recommendations_by_status,
    recommendations_for,
    record_review,
    reviews_for,
    set_escalation_reason,
    upsert_repository,
)
from .recommend.render import render_report, write_report
from .recommend.synthesize import synthesize_observation
from .registry import Repository

MAX_CONTEXT_CHARS = 6000


@dataclass
class ReviewRun:
    repository_id: str
    agent: str = "codex"
    reviewed: List[str] = field(default_factory=list)
    failed: List[str] = field(default_factory=list)
    skipped: int = 0
    considered: int = 0
    note: Optional[str] = None

    def describe(self) -> str:
        if self.note:
            return f"{self.repository_id}: {self.agent}: {self.note}"
        parts = [f"{self.agent}: {len(self.reviewed)} reviewed"]
        if self.failed:
            parts.append(f"{len(self.failed)} failed")
        if self.skipped:
            parts.append(f"{self.skipped} below the escalation threshold")
        if self.considered and self.agent != "codex":
            rate = len(self.reviewed) / self.considered
            parts.append(f"{rate:.0%} of {self.considered} escalated")
        return f"{self.repository_id}: {', '.join(parts)}"


def priors_besides(
    priors: List[Dict[str, Any]], observation_id: int
) -> List[Dict[str, Any]]:
    """Prior recommendations other than this observation's own.

    An observation that has already been scored has a recommendation of its
    own in the table. Handing that back to the reviewer as prior art would
    have it reject the idea as a restatement of itself -- so the one thing
    that is not a duplicate is the only one filtered out.
    """
    return [p for p in priors if p.get("observation_id") != observation_id]


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
    retry_failed: bool = False,
    note: Optional[str] = None,
    executor=None,
    conn=None,
) -> ReviewRun:
    repository.require("analyze")
    upsert_repository(repository, conn)
    run = ReviewRun(repository.id, agent="codex")

    observations = observations_for(
        repository.id, unreviewed_only=True, retry_failed=retry_failed, conn=conn
    )
    if limit:
        observations = observations[:limit]
    if not observations:
        return run

    scan = latest_scan(repository.id, conn)
    context = _context_text(repository, scan)
    # Everything already proposed, not just the rejections: an idea
    # already accepted and waiting to be built is as much a duplicate as
    # one that was turned down.
    priors = recommendations_by_status(repository.id, conn)["all"]
    build_context_package(repository, conn=conn)

    for observation in observations:
        result = await review_observation(
            repository,
            observation,
            context=context,
            priors=priors_besides(priors, observation["id"]),
            note=note,
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
            value=result.value,
            body=result.body or (result.error or ""),
            requires_architecture_review=result.requires_architecture_review,
            security_sensitive=result.security_sensitive,
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


def escalate_repository(
    repository: Repository,
    *,
    limit: Optional[int] = None,
    dry_run: bool = False,
    retry_failed: bool = False,
    caller=None,
    conn=None,
) -> ReviewRun:
    """Send the candidates that justify it to Claude for a second opinion.

    Everything expensive is behind the predicate in agents/triggers.py. A
    candidate that clears no threshold is skipped and the reason recorded, so
    the escalation rate is visible rather than something to find out from a
    bill.
    """
    repository.require("analyze")
    run = ReviewRun(repository.id, agent="claude")

    # Checked once, before anything is recorded. Without this, an unconfigured
    # routine produces one errored `claude` review per candidate -- and because
    # an errored review counts as attempted, every one of those candidates is
    # then silently never escalated again, including after a routine is set up.
    # A missing URL is an operator problem, not a per-candidate failure.
    if not dry_run and caller is None:
        try:
            claude_review.RoutineConfig.from_env()
        except claude_review.RoutineNotConfigured as exc:
            run.note = (
                "no routine configured, so nothing was escalated and nothing "
                f"was recorded. {exc}"
            )
            logger.info(f"{repository.id}: {run.note}")
            return run

    upsert_repository(repository, conn)
    scan = latest_scan(repository.id, conn)
    context = _context_text(repository, scan)
    # Everything already proposed, not just the rejections: an idea
    # already accepted and waiting to be built is as much a duplicate as
    # one that was turned down.
    priors = recommendations_by_status(repository.id, conn)["all"]
    scored = {
        row["observation_id"]: row
        for row in recommendations_for(repository.id, conn=conn)
        if row.get("observation_id")
    }

    for observation in observations_for(repository.id, conn=conn):
        reviews = reviews_for(observation["id"], conn)
        if not reviews:
            continue

        run.considered += 1
        recommendation = scored.get(observation["id"], {})
        candidate = candidate_from_rows(
            observation,
            reviews,
            repository_tags=repository.tags,
            score=recommendation.get("score"),
            effort=recommendation.get("estimated_effort"),
            retry_failed=retry_failed,
        )
        decision = should_escalate(candidate)
        set_escalation_reason(observation["id"], decision.reason, conn)

        if not decision.escalate:
            run.skipped += 1
            continue
        if dry_run:
            run.reviewed.append(f"{observation['title']} — {decision.reason}")
            continue

        codex = next((r for r in reviews if r["agent"] == "codex"), None)
        result = claude_review.review_observation(
            repository,
            observation,
            codex_review=codex,
            context=context,
            priors=priors_besides(priors, observation["id"]),
            caller=caller,
        )
        record_review(
            observation_id=observation["id"],
            repository_id=repository.id,
            agent="claude",
            verdict=result.verdict,
            confidence=result.confidence,
            fit=result.fit,
            cost=result.cost,
            risk=result.risk,
            value=result.value,
            body=result.body or (result.error or ""),
            requires_architecture_review=result.requires_architecture_review,
            security_sensitive=result.security_sensitive,
            conn=conn,
        )
        if result.ok:
            run.reviewed.append(observation["title"])
        else:
            run.failed.append(observation["title"])
            logger.warning(f"{repository.id}: Claude review failed — {result.error}")

    return run


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
