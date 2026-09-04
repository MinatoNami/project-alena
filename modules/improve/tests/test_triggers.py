"""The predicate that stands between a research feed and a subscription.

Exhaustive on purpose: this is the only thing deciding how much the expensive
reviewer costs, and a quietly-inverted condition here is a bill, not a bug
report.
"""

import pytest

from modules.improve.agents.triggers import (
    CONFIDENCE_FLOOR,
    SCORE_THRESHOLD,
    Candidate,
    candidate_from_rows,
    should_escalate,
)


def reviewed(**overrides) -> Candidate:
    """A candidate that clears nothing: reviewed, confident, small, dull."""
    base = dict(
        observation_id=1,
        title="x",
        score=0.4,
        effort="SMALL",
        confidence=0.9,
        verdict="supported",
        security_sensitive=False,
    )
    base.update(overrides)
    return Candidate(**base)


# -- the negative cases, which are the ones that save money ----------------


def test_a_dull_candidate_is_not_escalated():
    decision = should_escalate(reviewed())
    assert not decision
    assert decision.reason == "below every escalation threshold"


def test_an_unreviewed_candidate_is_not_escalated():
    """There is nothing to second-guess yet; that would be triage, not review."""
    assert not should_escalate(reviewed(verdict=None))


def test_a_candidate_already_reviewed_by_the_agent_is_not_escalated_again():
    decision = should_escalate(reviewed(score=0.99, already_reviewed_by=("claude",)))
    assert not decision
    assert "already reviewed" in decision.reason


def test_another_agents_review_does_not_count_as_this_one():
    assert should_escalate(reviewed(score=0.99, already_reviewed_by=("codex",)))


def test_a_confidently_rejected_candidate_is_not_escalated_on_score_alone():
    """Codex's job is to reject what does not fit; that is a result."""
    assert not should_escalate(reviewed(score=0.99, verdict="rejected"))


def test_a_rejected_candidate_is_still_escalated_if_the_rejection_was_unsure():
    assert should_escalate(reviewed(verdict="rejected", confidence=0.2))


# -- each spec condition, on its own ---------------------------------------


def test_a_high_score_escalates():
    decision = should_escalate(reviewed(score=SCORE_THRESHOLD))
    assert decision
    assert "score" in decision.reason


def test_a_score_just_below_the_threshold_does_not():
    assert not should_escalate(reviewed(score=SCORE_THRESHOLD - 0.01))


def test_low_reviewer_confidence_escalates():
    decision = should_escalate(reviewed(confidence=CONFIDENCE_FLOOR - 0.01))
    assert decision
    assert "confidence" in decision.reason


def test_confidence_exactly_at_the_floor_does_not():
    assert not should_escalate(reviewed(confidence=CONFIDENCE_FLOOR))


def test_an_architecture_change_escalates():
    assert should_escalate(reviewed(requires_architecture_review=True))


def test_a_security_sensitive_change_escalates():
    assert should_escalate(reviewed(security_sensitive=True))


def test_large_effort_escalates():
    decision = should_escalate(reviewed(effort="LARGE"))
    assert decision
    assert "LARGE" in decision.reason


def test_medium_effort_does_not():
    assert not should_escalate(reviewed(effort="MEDIUM"))


def test_disagreement_escalates():
    assert should_escalate(reviewed(disagreement=True))


def test_every_reason_that_fired_is_reported():
    decision = should_escalate(
        reviewed(score=0.9, effort="LARGE", requires_architecture_review=True)
    )
    assert "score" in decision.reason
    assert "LARGE" in decision.reason
    assert "architecture" in decision.reason


# -- the repository domain fallback ----------------------------------------


def test_a_security_repository_escalates_when_the_reviewer_was_silent():
    assert should_escalate(
        reviewed(security_sensitive=None, repository_tags=("security", "agents"))
    )


def test_a_reviewer_saying_not_sensitive_beats_the_repository_tag():
    """Otherwise every candidate in a security product escalates, and the
    cost control this module exists for is gone for that repository."""
    assert not should_escalate(
        reviewed(security_sensitive=False, repository_tags=("security",))
    )


def test_an_unrelated_tag_does_not_escalate():
    assert not should_escalate(
        reviewed(security_sensitive=None, repository_tags=("django", "pdf"))
    )


# -- thresholds are arguments, so they can be tuned ------------------------


def test_the_score_threshold_can_be_raised():
    assert not should_escalate(reviewed(score=0.8), score_threshold=0.95)


def test_the_confidence_floor_can_be_raised():
    assert should_escalate(reviewed(confidence=0.8), confidence_floor=0.9)


# -- building a candidate from stored rows ---------------------------------


def test_the_lowest_confidence_wins_not_the_mean():
    """One reviewer being unsure is reason enough to ask someone else."""
    candidate = candidate_from_rows(
        {"id": 1, "title": "x"},
        [
            {"agent": "codex", "verdict": "supported", "confidence": 0.95},
            {"agent": "other", "verdict": "supported", "confidence": 0.2},
        ],
    )
    assert candidate.confidence == 0.2


def test_errored_reviews_are_left_out_of_the_judgement():
    candidate = candidate_from_rows(
        {"id": 1, "title": "x"},
        [
            {"agent": "codex", "verdict": "error", "confidence": None},
            {"agent": "other", "verdict": "supported", "confidence": 0.8},
        ],
    )
    assert candidate.confidence == 0.8
    assert candidate.verdict == "supported"


def test_an_errored_review_still_counts_as_having_been_attempted():
    """Otherwise a failing agent is retried on every run, forever."""
    candidate = candidate_from_rows(
        {"id": 1, "title": "x"}, [{"agent": "claude", "verdict": "error"}]
    )
    assert "claude" in candidate.already_reviewed_by


def test_opposite_verdicts_are_recorded_as_disagreement():
    candidate = candidate_from_rows(
        {"id": 1, "title": "x"},
        [
            {"agent": "codex", "verdict": "supported"},
            {"agent": "claude", "verdict": "rejected"},
        ],
    )
    assert candidate.disagreement


@pytest.mark.parametrize("stored,expected", [(1, True), (0, False), (None, None)])
def test_security_sensitive_is_read_as_a_tri_state(stored, expected):
    candidate = candidate_from_rows(
        {"id": 1, "title": "x"},
        [{"agent": "codex", "verdict": "supported", "security_sensitive": stored}],
    )
    assert candidate.security_sensitive is expected
