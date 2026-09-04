"""Stop a rejected idea coming back next week.

The specs lead with this: "avoid repeatedly suggesting previously rejected
ideas". It is also the easiest thing to get wrong, because a research agent
rewords rather than repeats -- "semantic library search" one week,
"embedding-based document retrieval" the next.

Three layers, checked in order and *before* an observation is sent for review
rather than after:

1. Normalized title. Punctuation and stopwords dropped, words sorted, so word
   order and phrasing do not matter.
2. Token overlap. Works with no model at all.
3. Embedding cosine, when an embedding model is actually loaded.

Layer 3 is the best of the three and the least available: LM Studio serves
embeddings only when an embedding model occupies its embedding slot, which is
separate from the chat slot. So it is an upgrade, never a dependency -- with
no embedding model the first two layers still run, and dedup degrades in
recall rather than failing.

A previously *rejected* recommendation is a harder block than an open one, and
its rejection reason travels with the verdict so it can reach the prompt that
generates the next round.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence

from modules.core.controller.logger import logger

from ..text import jaccard, normalize_title

# Tuned to be cautious: a false "duplicate" silently loses a real idea, which
# is worse than a duplicate reaching a human who can see it is one.
# How each status reads when something duplicates it. Phrased as what is
# outstanding, because that is what the reader has to act on.
_WHERE = {
    "awaiting review": "already proposed and awaiting review",
    "recommended": "already proposed and awaiting your decision",
    "accepted": "already accepted and awaiting implementation",
    "implemented": "already implemented",
    "rejected": "already rejected",
    "abandoned": "already proposed and then abandoned",
    "successful": "already implemented, and it worked",
    "unsuccessful": "already implemented, and it did not work",
}

TITLE_MATCH = 1.0
# Titles are short and on-topic, so their overlap is a sharper signal than the
# same measure over full text, where a long shared preamble drowns it. Hence a
# lower bar for titles than for bodies.
TITLE_TOKEN_THRESHOLD = 0.65
TOKEN_THRESHOLD = 0.72
EMBEDDING_THRESHOLD = 0.90


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    left = math.sqrt(sum(x * x for x in a))
    right = math.sqrt(sum(y * y for y in b))
    if left == 0 or right == 0:
        return 0.0
    return dot / (left * right)


def pack_embedding(vector: Sequence[float]) -> bytes:
    return struct.pack(f"<{len(vector)}f", *vector)


def unpack_embedding(blob: Optional[bytes]) -> List[float]:
    if not blob:
        return []
    return list(struct.unpack(f"<{len(blob) // 4}f", blob))


@dataclass(frozen=True)
class PriorRecommendation:
    """What dedup compares against."""

    id: int
    title: str
    normalized_title: str
    status: str
    reason: Optional[str] = None
    body: Optional[str] = None
    embedding: Optional[bytes] = None
    # "recommendation" or "observation". An observation already ingested and
    # waiting for review counts as something we have proposed: reviewing the
    # same idea twice is exactly the spend dedup exists to avoid.
    kind: str = "recommendation"

    def text(self) -> str:
        return f"{self.title}\n\n{self.body or ''}".strip()


@dataclass(frozen=True)
class DedupVerdict:
    duplicate: bool
    matched: Optional[PriorRecommendation] = None
    method: Optional[str] = None
    similarity: float = 0.0

    @property
    def reason(self) -> Optional[str]:
        """Why this was skipped, in terms of what is already in flight.

        The status matters more than the fact of duplication. "Already
        accepted and waiting to be built" is a different thing to hear than
        "you turned this down in March", and the point of not re-adding
        something is that the existing one gets dealt with -- which needs the
        reader to know which one, and where it has got to.
        """
        if not self.duplicate or self.matched is None:
            return None

        where = _WHERE.get(self.matched.status, f"already recorded as {self.matched.status}")
        detail = (
            f"{self.matched.kind} #{self.matched.id}, matched on "
            f"{self.method} ({self.similarity:.2f})"
        )
        if self.matched.status == "rejected" and self.matched.reason:
            return f"{where} — {self.matched.reason} [{detail}]"
        return f"{where} [{detail}]"


def check(
    title: str,
    text: str,
    priors: Iterable[PriorRecommendation],
    *,
    embedding: Optional[Sequence[float]] = None,
) -> DedupVerdict:
    """Is this observation something we have already proposed?

    Reports the closest prior whenever there is any overlap at all, even below
    threshold, so a near-miss is recorded rather than silently discarded. A
    candidate that resembles nothing gets no match and a similarity of zero,
    which is what makes its novelty score one.
    """
    priors = list(priors)
    if not priors:
        return DedupVerdict(duplicate=False)

    normalized = normalize_title(title)
    best: Optional[PriorRecommendation] = None
    best_score = 0.0
    best_method = None

    for prior in priors:
        if normalized and normalized == prior.normalized_title:
            return DedupVerdict(
                duplicate=True,
                matched=prior,
                method="normalized title",
                similarity=TITLE_MATCH,
            )

        score = jaccard(text, prior.text())
        method = "token overlap"

        # Title overlap is scored against its own, lower threshold, so a
        # reworded heading is caught even when the bodies share little.
        title_score = jaccard(title, prior.title)
        if title_score >= TITLE_TOKEN_THRESHOLD and title_score > score:
            score, method = title_score, "title overlap"

        if embedding is not None:
            prior_vector = unpack_embedding(prior.embedding)
            if prior_vector:
                similarity = cosine(embedding, prior_vector)
                if similarity > score:
                    score, method = similarity, "embedding"

        if score > best_score:
            best, best_score, best_method = prior, score, method

    if best is None:
        return DedupVerdict(duplicate=False)

    threshold = {
        "embedding": EMBEDDING_THRESHOLD,
        "title overlap": TITLE_TOKEN_THRESHOLD,
    }.get(best_method, TOKEN_THRESHOLD)
    return DedupVerdict(
        duplicate=best_score >= threshold,
        matched=best,
        method=best_method,
        similarity=best_score,
    )


def embed_text(text: str) -> Optional[List[float]]:
    """Embed one string, or None when no embedding model is loaded.

    Never raises: dedup must keep working on its first two layers when the
    embedding slot is empty, which is the usual state of a LM Studio install
    that was set up for chat.
    """
    from modules.improve.intelligence.summarize import _client

    try:
        vectors = _client().embed([text])
    except Exception as exc:  # noqa: BLE001 - an upgrade, never a dependency
        logger.debug(f"Embeddings unavailable, dedup falling back: {exc!r}")
        return None
    return vectors[0] if vectors and vectors[0] else None
