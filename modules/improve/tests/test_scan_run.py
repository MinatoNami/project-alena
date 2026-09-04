"""End-to-end scan behaviour against a real repository."""

import pytest

from modules.improve.artifacts import render_profile
from modules.improve.persistence import latest_scan, scan_history
from modules.improve.registry import RegistryError, parse_registry
from modules.improve.scan_run import scan_repository

from .conftest import git


def scan(repository, **kwargs):
    kwargs.setdefault("summarize", False)
    return scan_repository(repository, **kwargs)


def test_a_scan_collects_structure_and_writes_a_profile(repository):
    outcome = scan(repository)

    assert outcome.ok and outcome.changed
    assert outcome.scan["file_count"] == 3
    assert outcome.scan["languages"]["Python"] == 1
    assert {d["name"] for d in outcome.scan["dependencies"]} == {"httpx", "fastapi"}
    assert outcome.profile_path.exists()
    assert "# Sample" in outcome.profile_path.read_text()


def test_a_scan_is_persisted(repository):
    scan(repository)

    stored = latest_scan("sample")
    assert stored["file_count"] == 3
    assert stored["branch"] == "main"


def test_an_unchanged_repository_is_skipped(repository):
    scan(repository)
    second = scan(repository)

    assert second.skipped
    assert not second.changed
    assert len(scan_history("sample")) == 1


def test_force_rescans_without_duplicating_the_row(repository):
    """The same fingerprint is the same scan, refreshed -- not a new one."""
    scan(repository)
    forced = scan(repository, force=True)

    assert not forced.skipped
    assert len(scan_history("sample")) == 1


def test_a_commit_produces_a_new_scan(repo, repository):
    scan(repository)
    (repo / "extra.py").write_text("# FIXME: later\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "Add extra")

    second = scan(repository)

    assert second.changed and not second.skipped
    assert len(scan_history("sample")) == 2


def test_new_todos_are_reported_against_the_previous_scan(repo, repository):
    scan(repository)
    (repo / "extra.py").write_text("# FIXME: handle the empty case\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "Add extra")

    second = scan(repository)

    added = [t["text"] for t in second.scan["todo_delta"]["added"]]
    assert "handle the empty case" in added


def test_a_missing_workspace_fails_that_repository_only(tmp_path):
    registry = parse_registry(
        {
            "repositories": [
                {"id": "gone", "workspace": {"path": str(tmp_path / "nowhere")}}
            ]
        }
    )
    outcome = scan(registry.resolve("gone"))

    assert not outcome.ok
    assert "does not exist" in outcome.error


def test_a_directory_that_is_not_a_repository_fails_cleanly(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    registry = parse_registry(
        {"repositories": [{"id": "plain", "workspace": {"path": str(plain)}}]}
    )
    outcome = scan(registry.resolve("plain"))

    assert not outcome.ok
    assert "not a git repository" in outcome.error


def test_a_repository_that_forbids_analysis_is_refused(repo):
    registry = parse_registry(
        {
            "repositories": [
                {
                    "id": "sample",
                    "workspace": {"path": str(repo)},
                    "capabilities": {"analyze": False},
                }
            ]
        }
    )
    with pytest.raises(RegistryError, match="analyze"):
        scan(registry.resolve("sample"))


def test_a_scan_never_writes_to_the_repository(repo, repository):
    before = sorted(p.name for p in repo.iterdir())
    scan(repository)

    assert sorted(p.name for p in repo.iterdir()) == before
    assert not scan_repository(repository, summarize=False, force=True).scan.get("dirty")


def test_the_model_is_never_called_for_an_unchanged_repository(repository, monkeypatch):
    """The whole point of the fingerprint: a quiet night costs nothing."""
    scan(repository)

    def explode(*args, **kwargs):
        raise AssertionError("the model was called for an unchanged repository")

    monkeypatch.setattr("modules.improve.scan_run.summarize_repository", explode)
    outcome = scan_repository(repository, summarize=True)

    assert outcome.skipped


def test_a_summary_failure_does_not_fail_the_scan(repository, monkeypatch):
    """An unattended nightly run must survive LM Studio being asleep."""
    from modules.llm import LLMUnavailable

    def unavailable(*args, **kwargs):
        raise LLMUnavailable("no model loaded")

    monkeypatch.setattr("modules.llm.LLMChatClient.chat", unavailable)

    outcome = scan_repository(repository, summarize=True)

    assert outcome.ok
    assert outcome.scan["summary"] is None
    assert outcome.scan["file_count"] == 3


def test_a_broken_llm_config_does_not_fail_the_scan(repository, monkeypatch):
    def explode():
        raise RuntimeError("LLM_BASE_URL is nonsense")

    monkeypatch.setattr("modules.improve.intelligence.summarize._client", explode)

    outcome = scan_repository(repository, summarize=True)

    assert outcome.ok
    assert outcome.scan["summary"] is None


def test_the_profile_renders_without_a_summary(repository):
    outcome = scan(repository)
    rendered = render_profile(outcome.scan)

    assert "## Languages" in rendered
    assert "## Dependencies" in rendered
    assert "## TODO / FIXME" in rendered
    assert "Summary" not in rendered


def test_the_profile_renders_the_summary_when_there_is_one(repository):
    outcome = scan(repository)
    outcome.scan["summary"] = "A sample project."

    assert "## Summary\n\nA sample project." in render_profile(outcome.scan)
