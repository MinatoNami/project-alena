"""The escalation pass: who gets a second opinion, and what it costs."""

import json
from types import SimpleNamespace

import pytest

from modules.improve.persistence import (
    observations_for,
    recommendations_for,
    reviews_for,
)
from modules.improve.recommend.synthesize import synthesize_observation
from modules.improve.research import ingest_text
from modules.improve.review_run import (
    escalate_repository,
    recommend_repository,
    review_repository_async,
)

RESEARCH = """# Research: sample

Repository: sample
Source: chatgpt-work

## Local OCR for scanned PDFs is practical

OCR models run on consumer hardware.

Evidence: https://a https://b https://c

## Add a keyboard shortcut for the next page

A small reader convenience.

Evidence: https://d
"""

HIGH_VALUE = {
    "verdict": "supported", "value": 0.85, "fit": 0.85, "cost": 0.4, "risk": 0.2,
    "confidence": 0.85, "requires_architecture_review": False, "security_sensitive": False,
}
TRIVIAL = {
    "verdict": "supported", "value": 0.3, "fit": 0.9, "cost": 0.1, "risk": 0.05,
    "confidence": 0.9, "requires_architecture_review": False, "security_sensitive": False,
}


def codex(verdicts):
    async def executor(server, tool, arguments, **kwargs):
        title = arguments["question"].split("Title: ")[1].splitlines()[0]
        payload = next(v for k, v in verdicts.items() if title.startswith(k))
        text = f"Assessment.\n\n```json\n{json.dumps(payload)}\n```"
        line = json.dumps(
            {"type": "item.completed", "item": {"type": "agent_message", "text": text}}
        )
        return SimpleNamespace(content=[SimpleNamespace(text=line)])

    return executor


async def prepare(repository):
    ingest_text(repository, RESEARCH, use_embeddings=False)
    await review_repository_async(
        repository, executor=codex({"Local OCR": HIGH_VALUE, "Add a keyboard": TRIVIAL})
    )
    recommend_repository(repository)


@pytest.mark.asyncio
async def test_only_candidates_clearing_a_threshold_are_escalated(repository):
    await prepare(repository)

    run = escalate_repository(repository, dry_run=True)

    assert run.considered == 2
    assert len(run.reviewed) == 1
    assert run.skipped == 1
    assert "Local OCR" in run.reviewed[0]


@pytest.mark.asyncio
async def test_a_dry_run_calls_no_routine(repository):
    await prepare(repository)

    def explode(*args, **kwargs):
        raise AssertionError("the routine was called during a dry run")

    escalate_repository(repository, dry_run=True, caller=explode)


@pytest.mark.asyncio
async def test_the_escalation_rate_is_reported(repository):
    """So the cost is visible here rather than on a bill."""
    await prepare(repository)

    assert "50% of 2 escalated" in escalate_repository(repository, dry_run=True).describe()


@pytest.mark.asyncio
async def test_the_reason_is_recorded_against_the_observation(repository):
    await prepare(repository)
    escalate_repository(repository, dry_run=True)

    reasons = {o["title"][:9]: o["escalation_reason"] for o in observations_for(repository.id)}
    assert "score" in reasons["Local OCR"]
    assert "below every escalation threshold" in reasons["Add a key"]


@pytest.mark.asyncio
async def test_an_unreviewed_observation_is_not_considered(repository):
    """Escalating before the first reviewer has looked would be triage."""
    ingest_text(repository, RESEARCH, use_embeddings=False)

    run = escalate_repository(repository, dry_run=True)

    assert run.considered == 0


@pytest.mark.asyncio
async def test_a_successful_escalation_records_a_claude_review(repository):
    await prepare(repository)

    def caller(prompt, **kwargs):
        return '```json\n{"verdict": "rejected", "fit": 0.2, "confidence": 0.9}\n```'

    run = escalate_repository(repository, caller=caller)

    assert len(run.reviewed) == 1
    observation = next(o for o in observations_for(repository.id) if o["title"].startswith("Local OCR"))
    agents = {r["agent"] for r in reviews_for(observation["id"])}
    assert agents == {"codex", "claude"}


@pytest.mark.asyncio
async def test_the_same_candidate_is_not_escalated_twice(repository):
    await prepare(repository)

    def caller(prompt, **kwargs):
        return '```json\n{"verdict": "supported", "confidence": 0.9}\n```'

    escalate_repository(repository, caller=caller)
    second = escalate_repository(repository, caller=caller)

    assert second.reviewed == []


@pytest.mark.asyncio
async def test_a_failing_routine_does_not_stop_the_run(repository):
    await prepare(repository)

    def caller(prompt, **kwargs):
        raise RuntimeError("routine unreachable")

    run = escalate_repository(repository, caller=caller)

    assert len(run.failed) == 1
    assert run.reviewed == []


@pytest.mark.asyncio
async def test_a_failed_escalation_is_not_retried_forever(repository):
    """An errored review still counts as attempted."""
    await prepare(repository)

    def caller(prompt, **kwargs):
        raise RuntimeError("routine unreachable")

    escalate_repository(repository, caller=caller)
    second = escalate_repository(repository, caller=caller)

    assert second.failed == []
    assert second.skipped >= 1


@pytest.mark.asyncio
async def test_codex_is_shown_to_claude_for_it_to_challenge(repository):
    await prepare(repository)
    seen = {}

    def caller(prompt, **kwargs):
        seen["prompt"] = prompt
        return '{"verdict": "supported"}'

    escalate_repository(repository, caller=caller)

    assert "Codex verdict: supported" in seen["prompt"]
    assert "Do not defer to it" in seen["prompt"]


# -- what a disagreement does to the score ---------------------------------


@pytest.mark.asyncio
async def test_a_disagreement_survives_into_the_recommendation(repository):
    await prepare(repository)

    def caller(prompt, **kwargs):
        return '```json\n{"verdict": "rejected", "value": 0.1, "fit": 0.1, "confidence": 0.9}\n```'

    escalate_repository(repository, caller=caller)

    observation = next(o for o in observations_for(repository.id) if o["title"].startswith("Local OCR"))
    result = synthesize_observation(repository, observation)

    assert result.disagreement
    assert "Disagreement" in result.body
    assert result.score.dimensions.confidence == 0.5


@pytest.mark.asyncio
async def test_a_split_verdict_does_not_count_as_rejected_by_all(repository):
    """One reviewer saying no is a disagreement for a human, not a dismissal."""
    await prepare(repository)

    def caller(prompt, **kwargs):
        return '```json\n{"verdict": "rejected", "confidence": 0.9}\n```'

    escalate_repository(repository, caller=caller)
    recommend_repository(repository)

    open_titles = [r["title"] for r in recommendations_for(repository.id, "recommended")]
    assert any(t.startswith("Local OCR") for t in open_titles)


@pytest.mark.asyncio
async def test_both_reviewers_rejecting_does_dismiss_it(repository):
    ingest_text(repository, RESEARCH, use_embeddings=False)
    rejected = dict(HIGH_VALUE, verdict="rejected", value=0.0, fit=0.0)
    await review_repository_async(
        repository, executor=codex({"Local OCR": rejected, "Add a keyboard": TRIVIAL})
    )
    recommend_repository(repository)

    def caller(prompt, **kwargs):
        return '```json\n{"verdict": "rejected", "confidence": 0.9}\n```'

    escalate_repository(repository, caller=caller)
    recommend_repository(repository)

    dismissed = [r["title"] for r in recommendations_for(repository.id, "rejected")]
    assert any(t.startswith("Local OCR") for t in dismissed)


@pytest.mark.asyncio
async def test_retry_failed_re_attempts_a_broken_escalation(repository):
    """The way back once a bad CLAUDE_ROUTINE_URL is fixed."""
    await prepare(repository)

    def failing(prompt, **kwargs):
        raise RuntimeError("routine unreachable")

    escalate_repository(repository, caller=failing)

    def working(prompt, **kwargs):
        return '{"verdict": "supported", "confidence": 0.9}'

    retried = escalate_repository(repository, caller=working, retry_failed=True)

    assert len(retried.reviewed) == 1
