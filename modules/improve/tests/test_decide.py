"""The approval gate: a closed set of transitions, and a reason where it counts."""

import pytest

from modules.improve.decide import (
    ABANDONED,
    ACCEPTED,
    IMPLEMENTED,
    RECOMMENDED,
    REJECTED,
    SUCCESSFUL,
    UNSUCCESSFUL,
    DecisionError,
    check_transition,
    decide,
    get_recommendation,
    history,
)
from modules.improve.persistence import (
    record_observation,
    record_research,
    upsert_recommendation,
    upsert_repository,
)


@pytest.fixture
def recommendation(repository):
    upsert_repository(repository)
    research_id, _ = record_research(
        repository_id=repository.id,
        source="test",
        content="# Research",
        content_hash="hash",
    )
    observation_id = record_observation(
        research_id=research_id,
        repository_id=repository.id,
        title="Semantic search",
        normalized_title="search semantic",
        body="...",
        evidence=None,
    )
    return upsert_recommendation(
        repository_id=repository.id,
        observation_id=observation_id,
        title="Semantic search",
        normalized_title="search semantic",
        body="...",
        score=0.8,
    )


# -- the transition table --------------------------------------------------


@pytest.mark.parametrize(
    "source,target",
    [
        (RECOMMENDED, ACCEPTED),
        (ACCEPTED, IMPLEMENTED),
        (ACCEPTED, ABANDONED),
        (IMPLEMENTED, SUCCESSFUL),
        (IMPLEMENTED, UNSUCCESSFUL),
        (REJECTED, RECOMMENDED),
        (UNSUCCESSFUL, ACCEPTED),
        (UNSUCCESSFUL, ABANDONED),
    ],
)
def test_allowed_transitions(source, target):
    check_transition(source, target, reason="because")


@pytest.mark.parametrize(
    "source,target",
    [
        (RECOMMENDED, IMPLEMENTED),
        (RECOMMENDED, SUCCESSFUL),
        (ACCEPTED, SUCCESSFUL),
        (SUCCESSFUL, ACCEPTED),
        (ABANDONED, ACCEPTED),
        (UNSUCCESSFUL, IMPLEMENTED),
        (UNSUCCESSFUL, SUCCESSFUL),
    ],
)
def test_refused_transitions(source, target):
    with pytest.raises(DecisionError, match="Cannot go from"):
        check_transition(source, target, reason="because")


def test_the_refusal_says_what_is_possible_instead():
    with pytest.raises(DecisionError, match="accepted"):
        check_transition(RECOMMENDED, IMPLEMENTED, None)


def test_an_unknown_status_is_refused():
    with pytest.raises(DecisionError, match="Unknown status"):
        check_transition("invented", ACCEPTED, None)


# -- reasons ---------------------------------------------------------------


@pytest.mark.parametrize("target", [REJECTED, ABANDONED, UNSUCCESSFUL])
def test_a_negative_outcome_needs_a_reason(target):
    """It goes into the next reviewer's prompt; without it the idea returns."""
    source = {REJECTED: RECOMMENDED, ABANDONED: ACCEPTED, UNSUCCESSFUL: IMPLEMENTED}[target]
    with pytest.raises(DecisionError, match="requires a reason"):
        check_transition(source, target, None)


def test_whitespace_is_not_a_reason():
    with pytest.raises(DecisionError, match="requires a reason"):
        check_transition(RECOMMENDED, REJECTED, "   ")


def test_accepting_needs_no_reason():
    check_transition(RECOMMENDED, ACCEPTED, None)


# -- recording -------------------------------------------------------------


def test_a_decision_updates_the_recommendation(repository, recommendation):
    decide(repository.id, recommendation, ACCEPTED)

    assert get_recommendation(repository.id, recommendation)["status"] == ACCEPTED


def test_a_decision_records_who_made_it(repository, recommendation):
    decide(repository.id, recommendation, ACCEPTED, actor="lionel")

    assert get_recommendation(repository.id, recommendation)["decided_by"] == "lionel"


def test_history_is_appended_not_overwritten(repository, recommendation):
    """"Accepted, then abandoned" is a different fact from "abandoned"."""
    decide(repository.id, recommendation, ACCEPTED)
    decide(repository.id, recommendation, ABANDONED, reason="no longer needed")

    trail = [(row["from_status"], row["to_status"]) for row in history(recommendation)]
    assert trail == [(RECOMMENDED, ACCEPTED), (ACCEPTED, ABANDONED)]


def test_the_rejection_reason_is_stored_for_dedup(repository, recommendation):
    decide(repository.id, recommendation, REJECTED, reason="too complex for now")

    assert "too complex" in get_recommendation(repository.id, recommendation)["reason"]


def test_an_outcome_records_effort_and_value(repository, recommendation):
    decide(repository.id, recommendation, ACCEPTED)
    decide(repository.id, recommendation, IMPLEMENTED)
    decide(
        repository.id,
        recommendation,
        SUCCESSFUL,
        actual_effort="LARGE",
        observed_value=0.9,
        feedback="took longer than estimated",
    )

    row = get_recommendation(repository.id, recommendation)
    assert row["actual_effort"] == "LARGE"
    assert row["observed_value"] == 0.9
    assert row["human_feedback"] == "took longer than estimated"


def test_the_expected_value_is_captured_at_decision_time(repository, recommendation):
    """So estimate and outcome can be compared later."""
    decide(repository.id, recommendation, ACCEPTED)

    assert get_recommendation(repository.id, recommendation)["expected_value"] == 0.8


def test_a_refused_transition_changes_nothing(repository, recommendation):
    with pytest.raises(DecisionError):
        decide(repository.id, recommendation, IMPLEMENTED)

    assert get_recommendation(repository.id, recommendation)["status"] == RECOMMENDED
    assert history(recommendation) == []


def test_an_unknown_recommendation_is_refused(repository):
    with pytest.raises(DecisionError, match="No recommendation"):
        decide(repository.id, 999, ACCEPTED)


def test_a_recommendation_from_another_repository_is_not_found(repository, recommendation):
    with pytest.raises(DecisionError, match="No recommendation"):
        decide("someone-else", recommendation, ACCEPTED)


def test_a_rejection_can_be_revisited(repository, recommendation):
    decide(repository.id, recommendation, REJECTED, reason="too early")
    decide(repository.id, recommendation, RECOMMENDED)

    assert get_recommendation(repository.id, recommendation)["status"] == RECOMMENDED


def test_a_failed_attempt_can_be_attempted_again(repository, recommendation):
    """A bad implementation is a fact about the attempt, not the idea.

    Without this the first failed run buries a good recommendation for good:
    `unsuccessful` used to be terminal, which only went unnoticed while
    nothing ever moved a recommendation out of `accepted`.
    """
    decide(repository.id, recommendation, ACCEPTED)
    decide(repository.id, recommendation, IMPLEMENTED, actor="codex")
    decide(repository.id, recommendation, UNSUCCESSFUL, reason="tests failed")
    decide(repository.id, recommendation, ACCEPTED)

    assert get_recommendation(repository.id, recommendation)["status"] == ACCEPTED


def test_a_success_is_still_the_end_of_the_line(repository, recommendation):
    decide(repository.id, recommendation, ACCEPTED)
    decide(repository.id, recommendation, IMPLEMENTED, actor="codex")
    decide(repository.id, recommendation, SUCCESSFUL)

    with pytest.raises(DecisionError, match="Cannot go from"):
        decide(repository.id, recommendation, ACCEPTED)
