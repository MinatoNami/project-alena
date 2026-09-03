"""Ingest a research document and turn it into observations.

ALENA cannot trigger ChatGPT Work -- it is a provider-side scheduler. What it
can do is consume the output, so the integration is a file contract: the
scheduled task writes a markdown document, and this reads it.

Dedup runs here, at ingest, rather than after review. Checking afterwards
would mean spending a Codex review on a proposal we already turned down, which
is the expensive half of the mistake.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from modules.core.controller.logger import logger

from ..persistence import (
    priors_for_dedup,
    record_observation,
    record_research,
    upsert_repository,
)
from ..recommend.dedup import check, embed_text, pack_embedding
from ..registry import Repository
from .parse import parse_research

RESEARCH_SUFFIXES = (".md", ".markdown")


@dataclass
class IngestResult:
    repository_id: str
    research_id: Optional[int] = None
    created: bool = False
    accepted: List[str] = field(default_factory=list)
    duplicates: List[str] = field(default_factory=list)
    embeddings_used: bool = False
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None

    def describe(self) -> str:
        if self.error:
            return f"{self.repository_id}: {self.error}"
        if not self.created:
            return f"{self.repository_id}: already ingested, nothing new"
        parts = [f"{len(self.accepted)} observation(s)"]
        if self.duplicates:
            parts.append(f"{len(self.duplicates)} duplicate(s) skipped")
        return f"{self.repository_id}: {', '.join(parts)}"


def ingest_text(
    repository: Repository,
    text: str,
    *,
    source: str = "chatgpt-work",
    path: Optional[str] = None,
    use_embeddings: bool = True,
    conn=None,
) -> IngestResult:
    repository.require("research")
    # Research can arrive before the first scan. The registry is the authority
    # on what exists, so the row is created from it rather than making the
    # caller run a scan first to satisfy a foreign key.
    upsert_repository(repository, conn)
    parsed = parse_research(text)

    if parsed.repository and parsed.repository != repository.id:
        # The document names a different repository. Trusting the file over the
        # command would let a misfiled research report be attributed to a
        # repository nobody asked about.
        return IngestResult(
            repository.id,
            error=(
                f"document declares Repository: {parsed.repository!r}, "
                f"but was ingested for {repository.id!r}"
            ),
        )

    research_id, created = record_research(
        repository_id=repository.id,
        source=parsed.source or source,
        content=parsed.content,
        content_hash=parsed.content_hash,
        title=parsed.title,
        document_date=parsed.document_date,
        path=path,
        conn=conn,
    )

    result = IngestResult(repository.id, research_id=research_id, created=created)
    if not created:
        return result

    priors = priors_for_dedup(repository.id, conn)

    for observation in parsed.observations:
        embedding = embed_text(observation.text()) if use_embeddings else None
        if embedding:
            result.embeddings_used = True

        verdict = check(
            observation.title, observation.text(), priors, embedding=embedding
        )
        record_observation(
            research_id=research_id,
            repository_id=repository.id,
            title=observation.title,
            normalized_title=observation.normalized_title,
            body=observation.body,
            evidence=observation.evidence,
            duplicate_of=(
                verdict.matched.id
                if verdict.duplicate and verdict.matched.kind == "recommendation"
                else None
            ),
            duplicate_reason=verdict.reason,
            similarity=verdict.similarity,
            embedding=pack_embedding(embedding) if embedding else None,
            conn=conn,
        )
        if verdict.duplicate:
            logger.info(f"{repository.id}: skipping duplicate — {verdict.reason}")
            result.duplicates.append(observation.title)
        else:
            result.accepted.append(observation.title)

    if not result.embeddings_used and parsed.observations:
        logger.warning(
            f"{repository.id}: no embedding model loaded, so de-duplication ran "
            "on titles and token overlap only. A reworded duplicate can reach "
            "review; the rejected-recommendations context is what catches it."
        )
    return result


def ingest_file(
    repository: Repository, path: Path, *, source: str = "chatgpt-work", conn=None
) -> IngestResult:
    path = Path(path)
    if not path.exists():
        return IngestResult(repository.id, error=f"no such file: {path}")
    return ingest_text(
        repository,
        path.read_text(encoding="utf-8", errors="replace"),
        source=source,
        path=str(path),
        conn=conn,
    )


def research_files(directory: Path) -> List[Path]:
    """Markdown in a drop directory, oldest first."""
    directory = Path(directory)
    if not directory.is_dir():
        return []
    return sorted(
        (p for p in directory.iterdir() if p.suffix.lower() in RESEARCH_SUFFIXES),
        key=lambda p: (p.stat().st_mtime, p.name),
    )
