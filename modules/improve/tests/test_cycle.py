"""One pass of the loop, stopping where a human is needed."""

import json
from types import SimpleNamespace

import pytest

from modules.improve.cycle import cycle, research_dir
from modules.improve.decide import ACCEPTED, REJECTED, decide
from modules.improve.persistence import recommendations_for
from modules.improve.registry import parse_registry
from modules.improve.research import propose

RESEARCH = """# Research: sample

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


@pytest.fixture
def drop(tmp_path):
    directory = tmp_path / "research"
    (directory / "sample").mkdir(parents=True)
    (directory / "sample" / "2026-09-04.md").write_text(RESEARCH)
    return directory


# -- the bundle ------------------------------------------------------------


def test_a_cycle_scans_ingests_reviews_and_scores(registry, drop):
    run = cycle(registry, "sample", drop=drop, summarize=False, executor=codex())

    entry = run.repositories[0]
    assert entry.scanned
    assert entry.ingested == 1
    assert entry.observations == 1
    assert entry.reviewed == 1
    assert entry.awaiting_decision == 1


def test_a_cycle_never_implements(registry, drop):
    """The first thing that touches a repository stays behind a decision."""
    from modules.improve.persistence import implementations_for

    cycle(registry, "sample", drop=drop, summarize=False, executor=codex())
    recommendation = recommendations_for("sample")[0]

    assert implementations_for(recommendation["id"]) == []
    assert recommendation["status"] == "recommended"


def test_a_cycle_with_nothing_dropped_still_scans(registry, tmp_path):
    run = cycle(registry, "sample", drop=tmp_path / "empty", summarize=False, executor=codex())

    assert run.repositories[0].scanned
    assert run.repositories[0].ingested == 0
    assert run.awaiting_decision == 0


def test_a_cycle_covers_every_repository(repo, drop, tmp_path):
    registry = parse_registry(
        {
            "repositories": [
                {"id": "sample", "workspace": {"path": str(repo)}},
                {"id": "second", "workspace": {"path": str(repo)}},
            ]
        }
    )
    run = cycle(registry, drop=drop, summarize=False, executor=codex())

    assert {r.repository_id for r in run.repositories} == {"sample", "second"}


def test_a_failed_scan_does_not_stop_the_other_repositories(repo, drop, tmp_path):
    registry = parse_registry(
        {
            "repositories": [
                {"id": "gone", "workspace": {"path": str(tmp_path / "nowhere")}},
                {"id": "sample", "workspace": {"path": str(repo)}},
            ]
        }
    )
    run = cycle(registry, drop=drop, summarize=False, executor=codex())

    by_id = {r.repository_id: r for r in run.repositories}
    assert by_id["gone"].errors
    assert by_id["sample"].scanned
    assert run.failed


def test_the_drop_directory_is_configurable(monkeypatch, tmp_path):
    monkeypatch.setenv("ALENA_RESEARCH_DIR", str(tmp_path / "elsewhere"))
    assert research_dir() == tmp_path / "elsewhere"


def test_research_for_another_repository_is_not_ingested(registry, tmp_path):
    """One directory per repository, so a document cannot be attributed to the
    wrong one by being in the wrong place."""
    drop = tmp_path / "research"
    (drop / "someone-else").mkdir(parents=True)
    (drop / "someone-else" / "r.md").write_text(RESEARCH)

    run = cycle(registry, "sample", drop=drop, summarize=False, executor=codex())

    assert run.repositories[0].ingested == 0


# -- nothing outstanding gets raised twice ---------------------------------


def test_something_awaiting_a_decision_is_not_added_again(registry, drop):
    cycle(registry, "sample", drop=drop, summarize=False, executor=codex())
    run = cycle(registry, "sample", drop=drop, summarize=False, executor=codex())

    # Same document: not re-ingested at all, and no second recommendation.
    assert run.repositories[0].ingested == 0
    assert len(recommendations_for("sample")) == 1


def test_a_reworded_repeat_of_something_accepted_is_skipped(registry, drop):
    """An idea already accepted and waiting to be built must not be raised
    again as new work."""
    cycle(registry, "sample", drop=drop, summarize=False, executor=codex())
    recommendation = recommendations_for("sample")[0]
    decide("sample", recommendation["id"], ACCEPTED)

    again = propose(
        registry.resolve("sample"), "Change worthwhile a", "Same thing.",
        use_embeddings=False,
    )

    assert again.duplicate
    assert "awaiting implementation" in again.duplicate_reason


def test_the_skip_says_what_is_outstanding(registry, drop):
    cycle(registry, "sample", drop=drop, summarize=False, executor=codex())

    again = propose(
        registry.resolve("sample"), "Change worthwhile a", "Same.",
        use_embeddings=False,
    )
    assert "awaiting your decision" in again.duplicate_reason


def test_a_rejected_idea_says_why_when_it_comes_back(registry, drop):
    cycle(registry, "sample", drop=drop, summarize=False, executor=codex())
    recommendation = recommendations_for("sample")[0]
    decide("sample", recommendation["id"], REJECTED, reason="not this quarter")

    again = propose(
        registry.resolve("sample"), "Change worthwhile a", "Same.",
        use_embeddings=False,
    )

    assert "already rejected" in again.duplicate_reason
    assert "not this quarter" in again.duplicate_reason
