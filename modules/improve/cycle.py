"""One pass of the loop, stopping where a human is needed.

Scanning, ingesting research, reviewing and scoring are four commands that
are always run in that order and are useless out of it -- a review with
nothing ingested reviews nothing, and scoring before a review scores nothing.
Running them as one thing removes an ordering nobody should have to remember.

**It stops at the gate.** The cycle never implements. Everything it does is
reading, thinking and writing to ALENA's own state; the first thing that
touches a repository is behind a recorded human decision, and putting it at
the end of a command that also refreshes scans would be a way around that.

**It does not re-raise what is already outstanding.** De-duplication runs at
ingest against every recommendation in any state and every observation still
awaiting review, so an idea that is already accepted and waiting to be built
is skipped and named rather than added a second time.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from modules.core.controller.logger import logger

from .registry import Repository, RepositoryRegistry
from .research import ingest_file, research_files
from .review_run import recommend_repository, review_repository_async
from .scan_run import scan_repository

DEFAULT_RESEARCH_DIR = "~/alena-research"


def research_dir() -> Path:
    """Where research documents are dropped.

    One directory per repository underneath, named by repository id, so a
    single drop point serves the whole portfolio and a document cannot be
    ingested against the wrong repository by being in the wrong place.
    """
    raw = os.getenv("ALENA_RESEARCH_DIR") or DEFAULT_RESEARCH_DIR
    return Path(raw).expanduser()


@dataclass
class RepositoryCycle:
    repository_id: str
    scanned: bool = False
    unchanged: bool = False
    ingested: int = 0
    observations: int = 0
    duplicates: List[str] = field(default_factory=list)
    reviewed: int = 0
    review_failures: int = 0
    recommendations: int = 0
    awaiting_decision: int = 0
    errors: List[str] = field(default_factory=list)

    def describe(self) -> str:
        if self.errors:
            return f"{self.repository_id}: {self.errors[0]}"
        parts = []
        parts.append("unchanged" if self.unchanged else "scanned")
        if self.ingested:
            parts.append(f"{self.ingested} document(s), {self.observations} new")
        if self.duplicates:
            parts.append(f"{len(self.duplicates)} already outstanding")
        if self.reviewed:
            parts.append(f"{self.reviewed} reviewed")
        if self.review_failures:
            parts.append(f"{self.review_failures} review(s) failed")
        if self.awaiting_decision:
            parts.append(f"{self.awaiting_decision} awaiting your decision")
        return f"{self.repository_id}: " + ", ".join(parts)


@dataclass
class CycleRun:
    repositories: List[RepositoryCycle] = field(default_factory=list)

    @property
    def awaiting_decision(self) -> int:
        return sum(r.awaiting_decision for r in self.repositories)

    @property
    def duplicates(self) -> List[str]:
        return [d for r in self.repositories for d in r.duplicates]

    @property
    def failed(self) -> bool:
        return any(r.errors or r.review_failures for r in self.repositories)


async def cycle_repository_async(
    repository: Repository,
    *,
    drop: Optional[Path] = None,
    summarize: bool = True,
    note: Optional[str] = None,
    force: bool = False,
    executor=None,
    conn=None,
) -> RepositoryCycle:
    """Scan, ingest, review and score one repository. Never implement."""
    result = RepositoryCycle(repository.id)

    outcome = scan_repository(
        repository, force=force, summarize=summarize, note=note, conn=conn
    )
    if not outcome.ok:
        result.errors.append(outcome.error or "scan failed")
        return result
    result.scanned = True
    result.unchanged = outcome.skipped

    drop = drop or research_dir()
    for path in research_files(drop / repository.id):
        ingested = ingest_file(repository, path)
        if not ingested.ok:
            result.errors.append(f"{path.name}: {ingested.error}")
            continue
        if ingested.created:
            result.ingested += 1
        result.observations += len(ingested.accepted)
        result.duplicates.extend(ingested.duplicates)

    review = await review_repository_async(
        repository, note=note, executor=executor, conn=conn
    )
    result.reviewed = len(review.reviewed)
    result.review_failures = len(review.failed)

    recommended = recommend_repository(repository, conn=conn)
    result.recommendations = recommended.count
    result.awaiting_decision = recommended.count

    return result


def cycle(
    registry: RepositoryRegistry,
    repository_id: Optional[str] = None,
    **kwargs,
) -> CycleRun:
    """One pass over one repository, or all of them."""
    targets = (
        [registry.resolve(repository_id, "analyze")]
        if repository_id
        else registry.all()
    )

    async def run() -> CycleRun:
        result = CycleRun()
        for repository in targets:
            result.repositories.append(
                await cycle_repository_async(repository, **kwargs)
            )
        return result

    return asyncio.run(run())
