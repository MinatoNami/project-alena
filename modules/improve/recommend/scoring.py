"""Scoring a candidate improvement.

The weights come from the spec. They live here as data, not as arithmetic
spread through the code, because the spec is explicit that they should
eventually be fitted to acceptance history -- which means something has to be
able to replace them without touching the calculation.

Where each dimension comes from matters:

* **evidence** and **novelty** are derived, not judged. Evidence counts what
  the research document actually cited; novelty is one minus how similar this
  is to something already proposed. Both are deterministic and testable.
* **value**, **fit**, **cost**, **risk** and **confidence** are the reviewing
  agent's judgement, and arrive from the engineering review.

A missing dimension defaults to 0.5 rather than 0. A review that failed should
leave a candidate mid-table for a human to look at, not silently at the bottom
where nobody will.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Dict, Optional

# spec §6. Cost and risk subtract.
DEFAULT_WEIGHTS: Dict[str, float] = {
    "value": 0.30,
    "fit": 0.20,
    "evidence": 0.15,
    "novelty": 0.15,
    "confidence": 0.10,
    "cost": -0.05,
    "risk": -0.05,
}

DIMENSIONS = tuple(DEFAULT_WEIGHTS)
NEUTRAL = 0.5

# The raw score runs from -0.10 (nothing good, maximum cost and risk) to +0.90.
WORST_RAW = sum(w for w in DEFAULT_WEIGHTS.values() if w < 0)
BEST_RAW = sum(w for w in DEFAULT_WEIGHTS.values() if w > 0)

HIGH = 0.70
MEDIUM = 0.45


def clamp(value: Optional[float]) -> float:
    if value is None:
        return NEUTRAL
    try:
        number = float(value)
    except (TypeError, ValueError):
        return NEUTRAL
    return max(0.0, min(1.0, number))


@dataclass(frozen=True)
class Dimensions:
    value: float = NEUTRAL
    fit: float = NEUTRAL
    evidence: float = NEUTRAL
    novelty: float = NEUTRAL
    confidence: float = NEUTRAL
    cost: float = NEUTRAL
    risk: float = NEUTRAL

    @classmethod
    def from_mapping(cls, raw: Optional[dict]) -> "Dimensions":
        raw = raw or {}
        return cls(**{name: clamp(raw.get(name)) for name in DIMENSIONS})

    def to_dict(self) -> Dict[str, float]:
        return asdict(self)


@dataclass(frozen=True)
class Score:
    raw: float
    normalized: float
    priority: str
    effort: str
    dimensions: Dimensions
    weights: Dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))

    def to_dict(self) -> dict:
        return {
            "raw": round(self.raw, 4),
            "normalized": round(self.normalized, 4),
            "priority": self.priority,
            "effort": self.effort,
            "dimensions": {k: round(v, 4) for k, v in self.dimensions.to_dict().items()},
            "weights": self.weights,
        }


def priority_for(normalized: float) -> str:
    if normalized >= HIGH:
        return "HIGH"
    if normalized >= MEDIUM:
        return "MEDIUM"
    return "LOW"


def effort_for(cost: float) -> str:
    """Cost is a 0-1 judgement; the spec reports effort in buckets."""
    if cost < 0.34:
        return "SMALL"
    if cost < 0.67:
        return "MEDIUM"
    return "LARGE"


def score(
    dimensions: Dimensions, weights: Optional[Dict[str, float]] = None
) -> Score:
    weights = dict(weights or DEFAULT_WEIGHTS)
    values = dimensions.to_dict()
    raw = sum(weights.get(name, 0.0) * values[name] for name in values)

    worst = sum(w for w in weights.values() if w < 0)
    best = sum(w for w in weights.values() if w > 0)
    span = best - worst
    normalized = (raw - worst) / span if span else 0.0

    return Score(
        raw=raw,
        normalized=normalized,
        priority=priority_for(normalized),
        effort=effort_for(values["cost"]),
        dimensions=dimensions,
        weights=weights,
    )


def evidence_score(evidence: Optional[str]) -> float:
    """How well cited an observation is.

    Counting citations is crude, but it is at least a fact about the document
    rather than a model's opinion of its own output. No evidence is a real
    signal: the research prompt asks for evidence-backed observations.
    """
    if not evidence or not evidence.strip():
        return 0.0
    citations = sum(evidence.count(token) for token in ("http://", "https://"))
    if citations >= 3:
        return 1.0
    if citations == 2:
        return 0.8
    if citations == 1:
        return 0.6
    # Prose with no link is weaker than a citation but stronger than silence.
    return 0.3


def novelty_score(similarity: float) -> float:
    """One minus how close this is to something already proposed."""
    return clamp(1.0 - max(0.0, min(1.0, similarity)))
