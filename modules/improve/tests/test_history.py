"""One timeline across five tables.

The record already existed, spread out. These check it assembles in order,
filters correctly, and marks the events that went the unhappy way.
"""

import json
from types import SimpleNamespace

import pytest

from modules.improve.decide import ACCEPTED, IMPLEMENTED, REJECTED, decide
from modules.improve.history import (
    DECISION,
    IMPLEMENTATION,
    KINDS,
    RESEARCH,
    REVIEW,
    SCAN,
    counts,
    timeline,
)
from modules.improve.persistence import (
    recommendations_for,
    record_implementation,
    update_implementation,
)
from modules.improve.research import ingest_text, propose
from modules.improve.review_run import recommend_repository, review_repository_async
from modules.improve.scan_run import scan_repository

RESEARCH_DOC = """# Research: sample

Repository: sample
Source: chatgpt-work

## A worthwhile change

Something substantial.

Evidence: https://a https://b
"""

SUPPORTED = {
    "verdict": "supported", "value": 0.8, "fit": 0.8, "cost": 0.3,
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


def kinds_in(events):
    return {e.kind for e in events}


# -- what appears ----------------------------------------------------------


def test_an_empty_system_has_no_history(repository):
    assert timeline() == []
    assert all(v == 0 for v in counts().values())


def test_a_scan_appears(repository):
    scan_repository(repository, summarize=False)

    events = timeline()
    assert kinds_in(events) == {SCAN}
    assert "3 files" in events[0].summary


def test_research_appears_with_its_source(repository):
    ingest_text(repository, RESEARCH_DOC, use_embeddings=False)

    assert "chatgpt-work" in timeline()[0].summary


def test_a_proposal_reads_as_a_proposal_not_as_research(repository):
    propose(repository, "My idea", "Detail.", use_embeddings=False)

    assert "Proposed by operator: My idea" in timeline()[0].summary


@pytest.mark.asyncio
async def test_a_review_appears_with_its_verdict(repository):
    ingest_text(repository, RESEARCH_DOC, use_embeddings=False)
    await review_repository_async(repository, executor=codex())

    review = next(e for e in timeline() if e.kind == REVIEW)
    assert "codex said supported" in review.summary
    assert "85% confident" in review.summary
    assert review.detail == "A worthwhile change"


@pytest.mark.asyncio
async def test_a_decision_appears_with_its_reason(repository):
    ingest_text(repository, RESEARCH_DOC, use_embeddings=False)
    await review_repository_async(repository, executor=codex())
    recommend_repository(repository)
    recommendation = recommendations_for(repository.id)[0]
    decide(repository.id, recommendation["id"], REJECTED, reason="too early for us")

    decision = next(e for e in timeline() if e.kind == DECISION)
    assert "recommended → rejected" in decision.summary
    assert "too early for us" in decision.summary


def test_an_implementation_appears_with_its_branch(repository):
    from modules.improve.persistence import (
        record_observation,
        record_research,
        upsert_recommendation,
        upsert_repository,
    )

    upsert_repository(repository)
    research_id, _ = record_research(
        repository_id=repository.id, source="test", content="# R", content_hash="h"
    )
    observation_id = record_observation(
        research_id=research_id, repository_id=repository.id, title="T",
        normalized_title="t", body="", evidence=None,
    )
    recommendation_id = upsert_recommendation(
        repository_id=repository.id, observation_id=observation_id,
        title="T", normalized_title="t", body="",
    )
    implementation_id = record_implementation(
        recommendation_id=recommendation_id, repository_id=repository.id,
        implemented_by="codex", branch="alena/1-t",
    )
    update_implementation(implementation_id, status="reviewed", tests_passed=True)

    event = next(e for e in timeline() if e.kind == IMPLEMENTATION)
    assert "alena/1-t" in event.summary
    assert "tests passed" in event.summary


# -- ordering and filtering ------------------------------------------------


@pytest.mark.asyncio
async def test_everything_is_newest_first(repository):
    scan_repository(repository, summarize=False)
    ingest_text(repository, RESEARCH_DOC, use_embeddings=False)
    await review_repository_async(repository, executor=codex())

    events = timeline()
    assert [e.at for e in events] == sorted((e.at for e in events), reverse=True)
    assert kinds_in(events) == {SCAN, RESEARCH, REVIEW}


@pytest.mark.asyncio
async def test_a_kind_filter_narrows_it(repository):
    scan_repository(repository, summarize=False)
    ingest_text(repository, RESEARCH_DOC, use_embeddings=False)
    await review_repository_async(repository, executor=codex())

    assert kinds_in(timeline(kinds=[REVIEW])) == {REVIEW}
    assert kinds_in(timeline(kinds=[SCAN, REVIEW])) == {SCAN, REVIEW}


def test_an_unknown_kind_is_ignored_rather_than_emptying_the_list(repository):
    scan_repository(repository, summarize=False)

    assert timeline(kinds=["scan", "invented"]) != []


def test_a_repository_filter_narrows_it(repository, registry):
    scan_repository(repository, summarize=False)

    assert timeline(repository_id="sample") != []
    assert timeline(repository_id="someone-else") == []


def test_the_limit_is_respected(repository):
    scan_repository(repository, summarize=False)
    ingest_text(repository, RESEARCH_DOC, use_embeddings=False)

    assert len(timeline(limit=1)) == 1


def test_counts_cover_every_kind(repository):
    scan_repository(repository, summarize=False)

    assert set(counts()) == set(KINDS)
    assert counts()["scan"] == 1


# -- what is marked as having gone badly -----------------------------------


@pytest.mark.asyncio
async def test_a_rejection_is_marked_adverse(repository):
    ingest_text(repository, RESEARCH_DOC, use_embeddings=False)
    await review_repository_async(
        repository, executor=codex(dict(SUPPORTED, verdict="rejected"))
    )

    assert next(e for e in timeline() if e.kind == REVIEW).adverse


@pytest.mark.asyncio
async def test_a_supported_review_is_not_marked_adverse(repository):
    ingest_text(repository, RESEARCH_DOC, use_embeddings=False)
    await review_repository_async(repository, executor=codex())

    assert not next(e for e in timeline() if e.kind == REVIEW).adverse


@pytest.mark.asyncio
async def test_an_abandonment_is_marked_adverse(repository):
    ingest_text(repository, RESEARCH_DOC, use_embeddings=False)
    await review_repository_async(repository, executor=codex())
    recommend_repository(repository)
    recommendation = recommendations_for(repository.id)[0]
    decide(repository.id, recommendation["id"], ACCEPTED)
    decide(repository.id, recommendation["id"], "abandoned", reason="no longer needed")

    adverse = [e for e in timeline() if e.kind == DECISION and e.adverse]
    assert len(adverse) == 1


def test_a_scan_is_never_adverse(repository):
    scan_repository(repository, summarize=False)

    assert not timeline()[0].adverse
