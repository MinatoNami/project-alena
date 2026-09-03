"""The pipeline view.

Every hand-off in the system is somewhere work can quietly stop, and a
stalled stage looks exactly like a quiet week. These check that each one is
counted, and that a failed review is reported rather than left silent.
"""

import json
from types import SimpleNamespace

import pytest

from modules.improve.decide import ACCEPTED, IMPLEMENTED, decide
from modules.improve.persistence import (
    observations_for,
    observations_with_failed_reviews,
    record_review,
    recommendations_for,
)
from modules.improve.registry import parse_registry
from modules.improve.research import ingest_text
from modules.improve.review_run import recommend_repository, review_repository_async
from modules.improve.status import STALE_DAYS, coverage, pipeline, summary

RESEARCH = """# Research: sample

Repository: sample
Source: chatgpt-work

## A worthwhile change

Something substantial.

Evidence: https://a https://b
"""

SUPPORTED = {
    "verdict": "supported", "value": 0.8, "fit": 0.8, "cost": 0.4,
    "risk": 0.2, "confidence": 0.85,
}


def codex(payload=SUPPORTED):
    async def executor(server, tool, arguments, **kwargs):
        text = f"Assessment.\n\n```json\n{json.dumps(payload)}\n```"
        line = json.dumps(
            {"type": "item.completed", "item": {"type": "agent_message", "text": text}}
        )
        return SimpleNamespace(content=[SimpleNamespace(text=line)])

    return executor


def stage(name):
    return next(s for s in pipeline() if s.name == name)


# -- counting each hand-off ------------------------------------------------


def test_a_fresh_system_has_nothing_waiting(registry):
    assert all(s.count == 0 for s in pipeline())
    assert summary(registry)["waiting_on_you"] == 0


def test_ingested_research_shows_as_awaiting_review(repository):
    ingest_text(repository, RESEARCH, use_embeddings=False)

    assert stage("unreviewed").count == 1


@pytest.mark.asyncio
async def test_a_reviewed_observation_shows_as_awaiting_scoring(repository):
    ingest_text(repository, RESEARCH, use_embeddings=False)
    await review_repository_async(repository, executor=codex())

    assert stage("unreviewed").count == 0
    assert stage("unscored").count == 1


@pytest.mark.asyncio
async def test_a_scored_recommendation_shows_as_awaiting_a_decision(repository):
    ingest_text(repository, RESEARCH, use_embeddings=False)
    await review_repository_async(repository, executor=codex())
    recommend_repository(repository)

    assert stage("unscored").count == 0
    assert stage("undecided").count == 1


@pytest.mark.asyncio
async def test_an_acceptance_shows_as_awaiting_implementation(repository):
    ingest_text(repository, RESEARCH, use_embeddings=False)
    await review_repository_async(repository, executor=codex())
    recommend_repository(repository)
    recommendation = recommendations_for(repository.id)[0]
    decide(repository.id, recommendation["id"], ACCEPTED)

    assert stage("undecided").count == 0
    assert stage("unimplemented").count == 1


@pytest.mark.asyncio
async def test_an_implementation_shows_as_awaiting_an_outcome(repository):
    ingest_text(repository, RESEARCH, use_embeddings=False)
    await review_repository_async(repository, executor=codex())
    recommend_repository(repository)
    recommendation = recommendations_for(repository.id)[0]
    decide(repository.id, recommendation["id"], ACCEPTED)
    decide(repository.id, recommendation["id"], IMPLEMENTED)

    assert stage("unimplemented").count == 0
    assert stage("unresolved").count == 1


@pytest.mark.asyncio
async def test_a_rejection_leaves_nothing_waiting(repository):
    from modules.improve.decide import REJECTED

    ingest_text(repository, RESEARCH, use_embeddings=False)
    await review_repository_async(repository, executor=codex())
    recommend_repository(repository)
    recommendation = recommendations_for(repository.id)[0]
    decide(repository.id, recommendation["id"], REJECTED, reason="not now")

    assert all(s.count == 0 for s in pipeline())


def test_a_duplicate_is_not_counted_as_waiting(repository):
    """It was never going to be reviewed."""
    ingest_text(repository, RESEARCH, use_embeddings=False)
    ingest_text(
        repository,
        RESEARCH.replace("## A worthwhile change", "## A change worthwhile"),
        use_embeddings=False,
    )

    assert stage("unreviewed").count == 1


# -- ages ------------------------------------------------------------------


def test_a_fresh_queue_is_not_stale(repository):
    ingest_text(repository, RESEARCH, use_embeddings=False)

    assert not stage("unreviewed").stale


def test_an_old_queue_is_reported_as_stalled(repository):
    """"3 awaiting decision" is a working system; "oldest 24 days" is not."""
    from datetime import datetime, timedelta, timezone

    from modules.store import get_connection

    ingest_text(repository, RESEARCH, use_embeddings=False)
    old = (
        datetime.now(timezone.utc)
        - timedelta(days=STALE_DAYS["unreviewed"] + 5)
    ).isoformat()
    get_connection().execute("UPDATE observations SET created_at = ?", (old,))
    get_connection().commit()

    found = stage("unreviewed")
    assert found.stale
    assert found.oldest_days >= STALE_DAYS["unreviewed"]
    assert found.examples


# -- stranded work ---------------------------------------------------------


def test_an_observation_whose_review_errored_is_findable(repository):
    """Otherwise it sits forever and nothing says so."""
    ingest_text(repository, RESEARCH, use_embeddings=False)
    observation = observations_for(repository.id)[0]
    record_review(
        observation_id=observation["id"],
        repository_id=repository.id,
        agent="codex",
        verdict="error",
        body="codex CLI not found",
    )

    stranded = observations_with_failed_reviews(repository.id)
    assert len(stranded) == 1
    assert stage("unreviewed").count == 0, "an attempt was made, so not unreviewed"


def test_retry_failed_picks_a_stranded_observation_back_up(repository):
    ingest_text(repository, RESEARCH, use_embeddings=False)
    observation = observations_for(repository.id)[0]
    record_review(
        observation_id=observation["id"],
        repository_id=repository.id,
        agent="codex",
        verdict="error",
        body="transient",
    )

    assert observations_for(repository.id, unreviewed_only=True) == []
    assert len(observations_for(repository.id, unreviewed_only=True, retry_failed=True)) == 1


def test_a_successful_review_is_not_stranded(repository):
    ingest_text(repository, RESEARCH, use_embeddings=False)
    observation = observations_for(repository.id)[0]
    record_review(
        observation_id=observation["id"],
        repository_id=repository.id,
        agent="codex",
        verdict="error",
        body="first attempt",
    )
    record_review(
        observation_id=observation["id"],
        repository_id=repository.id,
        agent="codex",
        verdict="supported",
        body="second attempt",
    )

    assert observations_with_failed_reviews(repository.id) == []


# -- coverage --------------------------------------------------------------


def test_coverage_counts_scanned_repositories(registry, repository):
    from modules.improve.scan_run import scan_repository

    assert coverage(registry).scanned == 0
    scan_repository(repository, summarize=False)
    assert coverage(registry).scanned == 1


def test_coverage_counts_research(registry, repository):
    ingest_text(repository, RESEARCH, use_embeddings=False)

    assert coverage(registry).research_documents == 1


def test_coverage_of_an_empty_registry_is_empty():
    assert coverage(parse_registry({"repositories": []})).repositories == 0
