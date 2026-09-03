"""Turn reviewed observations into scored recommendations.

The spec calls this the Thinking Agent. In Phase 2 it is deliberately not a
model: it combines the research observation, the derived evidence and novelty
scores, and whatever the engineering reviews concluded, using the weights in
scoring.py. Nothing here needs judgement that has not already been made
somewhere it can be attributed to.

Phase 3 adds Claude as a second reviewer, and this is where the two verdicts
get reconciled -- so disagreement is recorded rather than averaged away.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ..persistence import reviews_for, upsert_recommendation
from .scoring import Dimensions, Score, evidence_score, novelty_score, score


@dataclass
class Synthesis:
    observation: Dict[str, Any]
    reviews: List[Dict[str, Any]]
    score: Score
    body: str
    recommendation_id: Optional[int] = None
    disagreement: bool = False
    rejected: bool = False

    @property
    def title(self) -> str:
        return self.observation["title"]


def _mean(values: List[float]) -> Optional[float]:
    numbers = [v for v in values if v is not None]
    return sum(numbers) / len(numbers) if numbers else None


def reconcile(reviews: List[Dict[str, Any]]) -> tuple[Dict[str, Optional[float]], bool]:
    """Combine reviewer judgements, and say whether they disagreed.

    Disagreement is not averaged into the middle and forgotten. Two frontier
    models reaching opposite conclusions is the signal the spec wants two of
    them for, so it is reported and it lowers confidence.
    """
    usable = [r for r in reviews if r["verdict"] in ("supported", "rejected", "unclear")]
    verdicts = {r["verdict"] for r in usable if r["verdict"] != "unclear"}
    disagreement = len(verdicts) > 1

    combined: Dict[str, Optional[float]] = {
        key: _mean([r.get(key) for r in usable]) for key in ("fit", "cost", "risk")
    }
    confidence = _mean([r.get("confidence") for r in usable])
    if disagreement and confidence is not None:
        # Reviewers who contradict each other are not collectively confident.
        confidence = min(confidence, 0.5)
    combined["confidence"] = confidence
    return combined, disagreement


def build_body(
    repository_name: str,
    observation: Dict[str, Any],
    reviews: List[Dict[str, Any]],
    scan_summary: Optional[str],
    result: Score,
    disagreement: bool,
) -> str:
    by_agent = {r["agent"]: r for r in reviews}

    lines = [
        "### Research Evidence",
        "",
        (observation.get("body") or "_none recorded_").strip(),
        "",
        f"**Cited:** {observation.get('evidence') or 'nothing cited'}",
        "",
        "### Current Architecture",
        "",
        (scan_summary or "_No repository summary available._").strip(),
        "",
    ]

    for agent, heading in (("codex", "Codex Assessment"), ("claude", "Claude Assessment")):
        review = by_agent.get(agent)
        lines += [f"### {heading}", ""]
        if review is None:
            lines += [
                "_Not requested._"
                if agent == "claude"
                else "_No review recorded._",
                "",
            ]
            continue
        lines += [f"**Verdict:** {review['verdict']}", ""]
        lines += [(review.get("body") or "_no detail returned_").strip(), ""]

    if disagreement:
        lines += [
            "### Disagreement",
            "",
            "The reviewers reached opposite conclusions. Confidence is capped "
            "at 0.5 until a human resolves it.",
            "",
        ]

    dimensions = result.dimensions.to_dict()
    lines += [
        "### Scoring",
        "",
        "| Dimension | Value | Weight |",
        "|---|---|---|",
    ]
    for name, value in dimensions.items():
        lines.append(f"| {name} | {value:.2f} | {result.weights.get(name, 0):+.2f} |")
    lines += ["", f"**Score:** {result.normalized:.2f} ({result.priority})", ""]

    return "\n".join(lines).rstrip()


def synthesize_observation(
    repository,
    observation: Dict[str, Any],
    scan_summary: Optional[str] = None,
    conn=None,
) -> Optional[Synthesis]:
    """Score one reviewed observation and record the recommendation."""
    reviews = reviews_for(observation["id"], conn)
    if not reviews or all(r["verdict"] == "error" for r in reviews):
        return None

    combined, disagreement = reconcile(reviews)

    # An observation every reviewer judged unsound is not a recommendation
    # awaiting a human decision -- Codex's job is to reject what does not fit.
    # It is still recorded, with the reviewer's reasoning, because that is what
    # stops the same idea arriving again next week.
    usable = [r for r in reviews if r["verdict"] != "error"]
    rejected_by_all = bool(usable) and all(r["verdict"] == "rejected" for r in usable)

    dimensions = Dimensions.from_mapping(
        {
            "value": _mean([r.get("fit") for r in reviews]),
            "fit": combined["fit"],
            "cost": combined["cost"],
            "risk": combined["risk"],
            "confidence": combined["confidence"],
            "evidence": evidence_score(observation.get("evidence")),
            "novelty": novelty_score(observation.get("similarity") or 0.0),
        }
    )
    result = score(dimensions)

    body = build_body(
        repository.name, observation, reviews, scan_summary, result, disagreement
    )

    reason = None
    if rejected_by_all:
        summaries = [
            f"{r['agent']}: {(r.get('body') or '').strip().splitlines()[0][:160]}"
            for r in usable
            if (r.get("body") or "").strip()
        ]
        reason = "rejected by engineering review" + (
            "; " + "; ".join(summaries) if summaries else ""
        )

    recommendation_id = upsert_recommendation(
        repository_id=repository.id,
        observation_id=observation["id"],
        title=observation["title"],
        normalized_title=observation["normalized_title"],
        body=body,
        score=result.normalized,
        confidence=dimensions.confidence,
        estimated_effort=result.effort,
        score_breakdown=result.to_dict(),
        embedding=observation.get("embedding"),
        status="rejected" if rejected_by_all else "recommended",
        reason=reason,
        conn=conn,
    )

    return Synthesis(
        observation=observation,
        reviews=reviews,
        score=result,
        body=body,
        recommendation_id=recommendation_id,
        disagreement=disagreement,
        rejected=rejected_by_all,
    )
