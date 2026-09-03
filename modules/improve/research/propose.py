"""An idea the operator types, entering the pipeline as an observation.

Until now the only way in was a research document from an external agent, so
somebody with an idea of their own had nowhere to put it. This is that input.

It is deliberately *not* a shortcut. A proposal goes through everything a
research observation goes through -- de-duplication, engineering review,
scoring, and the same human decision at the end. Skipping review for ideas
that came from a person would mean the review only ever scrutinises the
suggestions nobody is attached to.

The one thing that differs is the reviewer's framing, and the reason is worth
stating. Research is quarantined because it is untrusted; a proposal is not
untrusted, it came through an interface only the operator can reach. The risk
runs the other way: a reviewer agreeing because of who asked. So the prompt
spends its words inviting refusal instead. See prompting.OPERATOR_PREAMBLE.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from modules.core.controller.logger import logger

from ..agents.prompting import OPERATOR_SOURCE
from ..persistence import (
    priors_for_dedup,
    record_observation,
    record_research,
    upsert_repository,
)
from ..recommend.dedup import check, embed_text, pack_embedding
from ..registry import Repository
from ..text import normalize_title
from .parse import content_hash

MAX_TITLE = 200
MAX_BODY = 20000


@dataclass
class ProposalResult:
    repository_id: str
    observation_id: Optional[int] = None
    title: str = ""
    duplicate_of: Optional[int] = None
    duplicate_reason: Optional[str] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def duplicate(self) -> bool:
        return self.duplicate_reason is not None

    def describe(self) -> str:
        if self.error:
            return f"{self.repository_id}: {self.error}"
        if self.duplicate:
            return f"{self.repository_id}: already proposed — {self.duplicate_reason}"
        return (
            f"{self.repository_id}: recorded as observation #{self.observation_id}. "
            "It will be reviewed on the next review run."
        )


def propose(
    repository: Repository,
    title: str,
    body: str,
    *,
    evidence: Optional[str] = None,
    use_embeddings: bool = True,
    conn=None,
) -> ProposalResult:
    """Record an operator's own idea as an observation."""
    repository.require("research")

    title = (title or "").strip()[:MAX_TITLE]
    body = (body or "").strip()[:MAX_BODY]
    if not title:
        return ProposalResult(repository.id, error="a proposal needs a title")

    upsert_repository(repository, conn)

    # A proposal gets its own research row so it has the same provenance
    # every other observation has: a source, a date, and something to point at
    # when asking where an idea came from.
    document = f"# Proposal: {title}\n\nRepository: {repository.id}\nSource: {OPERATOR_SOURCE}\n\n## {title}\n\n{body}\n"
    research_id, _ = record_research(
        repository_id=repository.id,
        source=OPERATOR_SOURCE,
        content=document,
        content_hash=content_hash(document),
        title=title,
        conn=conn,
    )

    text = f"{title}\n\n{body}".strip()
    embedding = embed_text(text) if use_embeddings else None
    verdict = check(title, text, priors_for_dedup(repository.id, conn), embedding=embedding)

    observation_id = record_observation(
        research_id=research_id,
        repository_id=repository.id,
        title=title,
        normalized_title=normalize_title(title),
        body=body,
        evidence=evidence,
        duplicate_of=(
            verdict.matched.id
            if verdict.duplicate and verdict.matched.kind == "recommendation"
            else None
        ),
        duplicate_reason=verdict.reason if verdict.duplicate else None,
        similarity=verdict.similarity,
        embedding=pack_embedding(embedding) if embedding else None,
        source=OPERATOR_SOURCE,
        conn=conn,
    )

    if verdict.duplicate:
        logger.info(f"{repository.id}: proposal duplicates something — {verdict.reason}")

    return ProposalResult(
        repository_id=repository.id,
        observation_id=observation_id,
        title=title,
        duplicate_of=verdict.matched.id if verdict.duplicate and verdict.matched else None,
        duplicate_reason=verdict.reason if verdict.duplicate else None,
    )
