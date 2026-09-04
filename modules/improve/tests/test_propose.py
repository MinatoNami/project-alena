"""An idea the operator types, entering the pipeline as an observation."""

import json
from types import SimpleNamespace

import pytest

from modules.improve.agents.codex_review import build_prompt
from modules.improve.agents.prompting import OPERATOR_SOURCE, preamble_for
from modules.improve.persistence import observations_for, recommendations_for
from modules.improve.research import ingest_text, propose
from modules.improve.review_run import recommend_repository, review_repository_async


def codex_result(payload):
    text = f"Assessment.\n\n```json\n{json.dumps(payload)}\n```"
    line = json.dumps(
        {"type": "item.completed", "item": {"type": "agent_message", "text": text}}
    )
    return SimpleNamespace(content=[SimpleNamespace(text=line)])


SUPPORTED = {
    "verdict": "supported", "value": 0.8, "fit": 0.8, "cost": 0.3,
    "risk": 0.2, "confidence": 0.85,
}


# -- recording -------------------------------------------------------------


def test_a_proposal_becomes_an_observation(repository):
    result = propose(
        repository, "Cache page thumbnails", "Regenerated on every load.",
        use_embeddings=False,
    )

    assert result.ok and not result.duplicate
    rows = observations_for(repository.id)
    assert [r["title"] for r in rows] == ["Cache page thumbnails"]


def test_a_proposal_is_marked_as_coming_from_the_operator(repository):
    propose(repository, "An idea", "Detail.", use_embeddings=False)

    assert observations_for(repository.id)[0]["source"] == OPERATOR_SOURCE


def test_research_keeps_its_own_source(repository):
    ingest_text(
        repository,
        "# R\n\nRepository: sample\nSource: chatgpt-work\n\n## Found\n\nSomething.\n",
        use_embeddings=False,
    )

    assert observations_for(repository.id)[0]["source"] == "chatgpt-work"


def test_a_proposal_needs_a_title(repository):
    result = propose(repository, "   ", "Body.", use_embeddings=False)

    assert not result.ok
    assert "needs a title" in result.error


def test_a_proposal_gets_a_research_row_for_provenance(repository):
    """So there is something to point at when asking where an idea came from."""
    propose(repository, "An idea", "Detail.", use_embeddings=False)

    from modules.store import get_connection

    rows = list(get_connection().execute("SELECT source, title FROM research_documents"))
    assert rows[0]["source"] == OPERATOR_SOURCE
    assert rows[0]["title"] == "An idea"


def test_a_long_proposal_is_truncated(repository):
    result = propose(repository, "x" * 500, "y" * 50000, use_embeddings=False)

    assert len(result.title) == 200


# -- it goes through everything else ---------------------------------------


def test_a_proposal_is_de_duplicated_like_anything_else(repository):
    propose(repository, "Cache page thumbnails on disk", "Detail.", use_embeddings=False)
    again = propose(repository, "On disk, cache page thumbnails", "Same.", use_embeddings=False)

    assert again.duplicate
    assert "awaiting review" in again.duplicate_reason


def test_a_proposal_duplicating_a_rejected_recommendation_is_caught(repository):
    """The memory loop applies to your own ideas too."""
    from modules.improve.decide import REJECTED, decide

    propose(repository, "Add OCR", "Detail.", use_embeddings=False)
    import asyncio

    async def codex(server, tool, arguments, **kwargs):
        return codex_result(SUPPORTED)

    asyncio.run(review_repository_async(repository, executor=codex))
    recommend_repository(repository)
    recommendation = recommendations_for(repository.id)[0]
    decide(repository.id, recommendation["id"], REJECTED, reason="too early")

    again = propose(repository, "OCR, add", "Same idea.", use_embeddings=False)

    assert again.duplicate
    assert "too early" in again.duplicate_reason


@pytest.mark.asyncio
async def test_a_proposal_is_reviewed_and_scored_like_research(repository):
    """Not a shortcut. Skipping review for ideas that came from a person would
    mean the review only scrutinises suggestions nobody is attached to."""
    propose(repository, "Cache thumbnails", "Detail.", use_embeddings=False)

    async def codex(server, tool, arguments, **kwargs):
        return codex_result(SUPPORTED)

    await review_repository_async(repository, executor=codex)
    recommend_repository(repository)

    rows = recommendations_for(repository.id, "recommended")
    assert [r["title"] for r in rows] == ["Cache thumbnails"]


@pytest.mark.asyncio
async def test_a_rejected_proposal_does_not_become_a_recommendation(repository):
    """"No" stays available for the operator's own ideas."""
    propose(repository, "A bad idea", "Detail.", use_embeddings=False)

    async def codex(server, tool, arguments, **kwargs):
        return codex_result(dict(SUPPORTED, verdict="rejected", value=0.0, fit=0.0))

    await review_repository_async(repository, executor=codex)
    recommend_repository(repository)

    assert recommendations_for(repository.id, "recommended") == []
    assert recommendations_for(repository.id, "rejected")


# -- the framing, which is the whole difference ----------------------------


def test_research_is_framed_as_untrusted():
    assert "third-party text" in preamble_for("chatgpt-work")


def test_a_proposal_is_not_framed_as_untrusted():
    """Quarantining something that came through an interface only the operator
    can reach would be theatre."""
    preamble = preamble_for(OPERATOR_SOURCE)
    assert "third-party" not in preamble
    assert "carries no authority" not in preamble


def test_a_proposal_is_framed_to_invite_refusal():
    """The risk here is the opposite of injection: agreement because of who
    asked."""
    preamble = preamble_for(OPERATOR_SOURCE)
    assert "not for agreement" in preamble
    assert "rejected" in preamble


def test_the_reviewer_picks_its_framing_from_the_source():
    operator = build_prompt("Repo", {"title": "T", "body": "b", "source": OPERATOR_SOURCE})
    research = build_prompt("Repo", {"title": "T", "body": "b", "source": "chatgpt-work"})

    assert "came from your operator" in operator
    assert "third-party text" in research


def test_an_observation_with_no_source_is_treated_as_untrusted():
    """Fail safe: an unknown origin gets the cautious framing."""
    assert "third-party text" in build_prompt("Repo", {"title": "T", "body": "b"})


def test_both_reviewers_use_the_same_framing():
    """Two copies of a security-relevant decision drift."""
    from modules.improve.agents import claude_review

    observation = {"id": 1, "title": "T", "body": "b", "source": OPERATOR_SOURCE}
    assert "came from your operator" in claude_review.build_prompt("Repo", observation)
