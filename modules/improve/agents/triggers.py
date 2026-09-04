"""When is a second opinion worth buying?

Claude is the expensive reviewer, and the spec is explicit about why it is not
run on everything: forty research observations become ten candidates locally,
then four after Codex, and only those four are worth a second frontier model.
This module is that filter.

It is a pure function over recorded facts, with no I/O and no model call, for
two reasons. It is the thing standing between a research feed and a
subscription, so it has to be exhaustively testable. And every escalation
records *which* condition fired, so the thresholds can later be tuned against
which escalations turned out to be worth it.

The conditions are the spec's, and they are a disjunction -- any one is enough:

* the candidate scored high enough to be worth getting right
* Codex was not confident
* Codex says it changes architecture
* Codex says it touches security
* the effort is large
* Codex and a previous reviewer already disagree
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

SCORE_THRESHOLD = 0.70
CONFIDENCE_FLOOR = 0.60
LARGE_EFFORTS = ("LARGE",)

# Repositories whose domain makes everything security-sensitive. Athena is
# vulnerability management; a change there is security-relevant by default.
SECURITY_TAGS = frozenset({"security", "vulnerability-management", "auth", "crypto"})


@dataclass(frozen=True)
class Candidate:
    """Everything the predicate is allowed to look at."""

    observation_id: int
    title: str
    score: Optional[float] = None
    effort: Optional[str] = None
    confidence: Optional[float] = None
    verdict: Optional[str] = None
    requires_architecture_review: bool = False
    # Tri-state. None means no reviewer expressed an opinion, which is the
    # only case where the repository's domain tags get to decide.
    security_sensitive: Optional[bool] = None
    disagreement: bool = False
    repository_tags: Sequence[str] = field(default_factory=tuple)
    already_reviewed_by: Sequence[str] = field(default_factory=tuple)


@dataclass(frozen=True)
class Decision:
    escalate: bool
    reasons: List[str] = field(default_factory=list)

    @property
    def reason(self) -> Optional[str]:
        return "; ".join(self.reasons) if self.reasons else None

    def __bool__(self) -> bool:
        return self.escalate


def should_escalate(
    candidate: Candidate,
    *,
    agent: str = "claude",
    score_threshold: float = SCORE_THRESHOLD,
    confidence_floor: float = CONFIDENCE_FLOOR,
) -> Decision:
    """Decide whether `candidate` is worth a review from `agent`."""
    if agent in candidate.already_reviewed_by:
        return Decision(False, [f"already reviewed by {agent}"])

    # A candidate no reviewer has looked at yet has nothing to second-guess.
    # Escalating it would spend the expensive reviewer on triage.
    if candidate.verdict is None:
        return Decision(False, ["no engineering review yet"])

    # An idea the first reviewer rejected is not escalated on score alone --
    # but it is escalated if the rejection was unconfident or the subject is
    # one where being wrong is expensive.
    reasons: List[str] = []

    if candidate.disagreement:
        reasons.append("reviewers disagree")

    if candidate.confidence is not None and candidate.confidence < confidence_floor:
        reasons.append(f"low reviewer confidence ({candidate.confidence:.2f})")

    if candidate.requires_architecture_review:
        reasons.append("changes architecture")

    if candidate.security_sensitive:
        reasons.append("security-sensitive")
    elif candidate.security_sensitive is None and (
        SECURITY_TAGS & {t.lower() for t in candidate.repository_tags}
    ):
        # A reviewer that looked and said "not security-sensitive" is a better
        # signal than the repository's domain. The tag only fills a silence --
        # otherwise every candidate in a security product escalates, and the
        # cost control this module exists for is gone for that repository.
        reasons.append("security-sensitive by repository domain")

    if candidate.effort and candidate.effort.upper() in LARGE_EFFORTS:
        reasons.append(f"effort {candidate.effort}")

    if (
        candidate.verdict != "rejected"
        and candidate.score is not None
        and candidate.score >= score_threshold
    ):
        reasons.append(f"score {candidate.score:.2f} >= {score_threshold:.2f}")

    if not reasons:
        return Decision(False, ["below every escalation threshold"])
    return Decision(True, reasons)


def _flag(value: Any) -> bool:
    return bool(value) and value not in (0, "0", "false", "False")


def _tri_state(values) -> Optional[bool]:
    """True if any reviewer said so, False if one said not, None if silent."""
    seen = [v for v in values if v is not None]
    if not seen:
        return None
    return any(_flag(v) for v in seen)


def candidate_from_rows(
    observation: Dict[str, Any],
    reviews: List[Dict[str, Any]],
    repository_tags: Sequence[str] = (),
    score: Optional[float] = None,
    effort: Optional[str] = None,
    retry_failed: bool = False,
) -> Candidate:
    """Build a Candidate from what is stored, without judging anything.

    A review that errored still counts as an attempt, so a permanently broken
    endpoint is not retried on every run. `retry_failed` is the way back once
    the cause is fixed.
    """
    usable = [r for r in reviews if r.get("verdict") != "error"]
    attempted = [
        r["agent"]
        for r in reviews
        if not (retry_failed and r.get("verdict") == "error")
    ]
    verdicts = {r["verdict"] for r in usable if r["verdict"] != "unclear"}
    confidences = [r["confidence"] for r in usable if r.get("confidence") is not None]

    return Candidate(
        observation_id=observation["id"],
        title=observation["title"],
        score=score,
        effort=effort,
        # The *lowest* confidence, not the mean: one reviewer being unsure is
        # reason enough to ask someone else, and averaging hides it.
        confidence=min(confidences) if confidences else None,
        verdict=(next(iter(verdicts)) if len(verdicts) == 1 else "mixed")
        if usable
        else None,
        requires_architecture_review=any(
            _flag(r.get("requires_architecture_review")) for r in usable
        ),
        security_sensitive=_tri_state(
            r.get("security_sensitive") for r in usable
        ),
        disagreement=len(verdicts) > 1,
        repository_tags=tuple(repository_tags),
        already_reviewed_by=tuple(attempted),
    )
