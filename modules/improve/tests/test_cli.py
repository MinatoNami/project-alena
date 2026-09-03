"""CLI tests. Every trigger in the spec is a subcommand, so these are the
entry points launchd will actually call."""

import json

import pytest
import yaml

from modules.improve.cli import main


@pytest.fixture
def registry_file(tmp_path, repo):
    path = tmp_path / "repositories.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "repositories": [
                    {
                        "id": "sample",
                        "name": "Sample",
                        "workspace": {"path": str(repo)},
                    },
                    {
                        "id": "off",
                        "workspace": {"path": str(repo)},
                        "enabled": False,
                    },
                ]
            }
        )
    )
    return str(path)


def run(*args):
    return main(list(args))


def test_repos_lists_declared_repositories(registry_file, capsys):
    assert run("repos", "--registry", registry_file) == 0

    out = capsys.readouterr().out
    assert "sample" in out
    assert "[disabled]" in out


def test_repos_json_is_machine_readable(registry_file, capsys):
    assert run("repos", "--registry", registry_file, "--json") == 0

    payload = json.loads(capsys.readouterr().out)
    assert {entry["id"] for entry in payload} == {"sample", "off"}


def test_scan_all_skips_disabled_repositories(registry_file, capsys):
    assert run("scan", "--all", "--no-llm", "--registry", registry_file) == 0

    out = capsys.readouterr().out
    assert "sample: scanned" in out
    assert "off:" not in out


def test_scan_names_one_repository(registry_file, capsys):
    assert run("scan", "sample", "--no-llm", "--registry", registry_file) == 0
    assert "sample: scanned" in capsys.readouterr().out


def test_scanning_a_disabled_repository_is_refused(registry_file, capsys):
    assert run("scan", "off", "--no-llm", "--registry", registry_file) == 2
    assert "disabled" in capsys.readouterr().err


def test_scanning_an_unknown_repository_is_refused(registry_file, capsys):
    assert run("scan", "nope", "--no-llm", "--registry", registry_file) == 2
    assert "Unknown repository" in capsys.readouterr().err


def test_scan_without_a_target_says_so(registry_file, capsys):
    assert run("scan", "--no-llm", "--registry", registry_file) == 2
    assert "--all" in capsys.readouterr().err


def test_a_second_scan_reports_the_repository_as_unchanged(registry_file, capsys):
    run("scan", "--all", "--no-llm", "--registry", registry_file)
    capsys.readouterr()

    run("scan", "--all", "--no-llm", "--registry", registry_file)
    assert "unchanged" in capsys.readouterr().out


def test_show_before_a_scan_explains_what_to_run(registry_file, capsys):
    assert run("show", "sample", "--registry", registry_file) == 1
    assert "has not been scanned" in capsys.readouterr().out


def test_show_reports_the_latest_scan(registry_file, capsys):
    run("scan", "sample", "--no-llm", "--registry", registry_file)
    capsys.readouterr()

    assert run("show", "sample", "--registry", registry_file) == 0
    out = capsys.readouterr().out
    assert "files      3" in out
    assert "Python" in out


def test_a_failing_repository_makes_the_run_exit_nonzero(tmp_path, capsys):
    path = tmp_path / "repositories.yaml"
    path.write_text(
        yaml.safe_dump(
            {"repositories": [{"id": "gone", "workspace": {"path": str(tmp_path / "x")}}]}
        )
    )
    assert run("scan", "--all", "--no-llm", "--registry", str(path)) == 1
    assert "failed" in capsys.readouterr().err


def test_where_reports_the_paths_in_use(registry_file, capsys):
    assert run("where", "--registry", registry_file) == 0

    out = capsys.readouterr().out
    assert "registry" in out and "tool policy" in out and "intelligence" in out


def test_audit_reads_the_gateway_log(registry_file, capsys):
    from modules.gateway.audit import AuditLog

    AuditLog().record(tool="codex_analyze", agent="assistant", outcome="success", arguments={})

    assert run("audit", "--registry", registry_file) == 0
    assert "codex_analyze" in capsys.readouterr().out


# --- Phase 2 commands ------------------------------------------------------


RESEARCH_DOC = """# Research: sample

Repository: sample
Date: 2026-09-03
Source: chatgpt-work

## Local OCR is practical

OCR runs on consumer hardware.

Evidence: https://a.example
"""


@pytest.fixture
def research_file(tmp_path):
    path = tmp_path / "drop" / "sample-2026-09-03.md"
    path.parent.mkdir()
    path.write_text(RESEARCH_DOC)
    return path


def test_context_writes_the_package(registry_file, capsys):
    assert run("context", "sample", "--registry", registry_file) == 0
    assert ".context" in capsys.readouterr().out


def test_ingest_research_reports_what_it_took(registry_file, research_file, capsys):
    assert run("ingest-research", "sample", str(research_file), "--registry", registry_file) == 0
    assert "1 observation" in capsys.readouterr().out


def test_ingest_research_from_a_drop_directory(registry_file, research_file, capsys):
    assert run(
        "ingest-research", "sample", "--from-dir", str(research_file.parent),
        "--registry", registry_file,
    ) == 0
    assert "1 observation" in capsys.readouterr().out


def test_ingest_research_reports_a_missing_file(registry_file, tmp_path, capsys):
    assert run("ingest-research", "sample", str(tmp_path / "nope.md"), "--registry", registry_file) == 1
    assert "no such file" in capsys.readouterr().out


def test_recommend_with_nothing_reviewed_writes_an_empty_report(registry_file, capsys):
    assert run("recommend", "sample", "--registry", registry_file) == 0
    out = capsys.readouterr().out
    assert "0 recommendation(s)" in out
    assert "latest.md" in out


def test_review_with_claude_and_no_routine_configured(registry_file, capsys, monkeypatch):
    """It should say what to set, not fail obscurely."""
    monkeypatch.delenv("CLAUDE_ROUTINE_URL", raising=False)
    run("ingest-research", "sample", "--registry", registry_file, "--from-dir", ".")
    capsys.readouterr()

    assert run("review", "sample", "--agent", "claude", "--registry", registry_file) == 0
    assert "claude:" in capsys.readouterr().out


def test_review_dry_run_reports_what_would_escalate(registry_file, capsys):
    assert run(
        "review", "sample", "--agent", "claude", "--dry-run", "--registry", registry_file
    ) == 0
    assert "claude:" in capsys.readouterr().out


def test_review_defaults_to_codex(registry_file, capsys):
    assert run("review", "sample", "--registry", registry_file) == 0
    assert "codex:" in capsys.readouterr().out


# --- Phase 4 commands ------------------------------------------------------


@pytest.fixture
def accepted_recommendation(repo, registry_file):
    from modules.improve.persistence import (
        record_observation,
        record_research,
        upsert_recommendation,
        upsert_repository,
    )
    from modules.improve.registry import load_registry

    repository = load_registry(registry_file).resolve("sample")
    upsert_repository(repository)
    research_id, _ = record_research(
        repository_id="sample", source="test", content="# R", content_hash="h"
    )
    observation_id = record_observation(
        research_id=research_id,
        repository_id="sample",
        title="A change",
        normalized_title="a change",
        body="...",
        evidence=None,
    )
    return upsert_recommendation(
        repository_id="sample",
        observation_id=observation_id,
        title="A change",
        normalized_title="a change",
        body="...",
        score=0.8,
    )


def test_pending_lists_undecided_recommendations(registry_file, accepted_recommendation, capsys):
    assert run("pending", "sample", "--registry", registry_file) == 0
    assert "A change" in capsys.readouterr().out


def test_decide_accepts(registry_file, accepted_recommendation, capsys):
    assert run("decide", "sample", str(accepted_recommendation), "--accept", "--registry", registry_file) == 0
    out = capsys.readouterr().out
    assert "recommended → accepted" in out
    assert "alena-improve implement sample" in out


def test_decide_refuses_a_rejection_without_a_reason(registry_file, accepted_recommendation, capsys):
    assert run("decide", "sample", str(accepted_recommendation), "--reject", "--registry", registry_file) == 2
    assert "requires a reason" in capsys.readouterr().err


def test_decide_refuses_two_outcomes_at_once(registry_file, accepted_recommendation, capsys):
    assert run(
        "decide", "sample", str(accepted_recommendation), "--accept", "--abandon",
        "--reason", "x", "--registry", registry_file,
    ) == 2
    assert "exactly one" in capsys.readouterr().err


def test_decide_refuses_an_illegal_transition(registry_file, accepted_recommendation, capsys):
    assert run(
        "decide", "sample", str(accepted_recommendation), "--successful", "--registry", registry_file
    ) == 2
    assert "Cannot go from" in capsys.readouterr().err


def test_implement_refuses_a_read_only_repository(registry_file, accepted_recommendation, capsys):
    run("decide", "sample", str(accepted_recommendation), "--accept", "--registry", registry_file)
    capsys.readouterr()

    assert run("implement", "sample", str(accepted_recommendation), "--registry", registry_file) == 2
    assert "modify" in capsys.readouterr().err


def test_trail_shows_the_decision_history(registry_file, accepted_recommendation, capsys):
    run("decide", "sample", str(accepted_recommendation), "--accept", "--registry", registry_file)
    capsys.readouterr()

    assert run("trail", "sample", str(accepted_recommendation), "--registry", registry_file) == 0
    assert "recommended -> accepted" in capsys.readouterr().out


# --- monitoring and the approval queue -------------------------------------


def test_status_on_a_fresh_system_says_nothing_needs_you(registry_file, capsys):
    assert run("status", "--registry", registry_file) == 0
    out = capsys.readouterr().out
    assert "Nothing needs you" in out
    assert "ingest-research" in out


def test_status_counts_work_waiting_at_each_stage(registry_file, repository, capsys):
    from modules.improve.research import ingest_text

    ingest_text(repository, RESEARCH_DOC, use_embeddings=False)

    assert run("status", "--registry", registry_file) == 0
    assert "Observations awaiting review: 1" in capsys.readouterr().out


def test_status_reports_a_stranded_observation(registry_file, repository, capsys):
    from modules.improve.persistence import observations_for, record_review
    from modules.improve.research import ingest_text

    ingest_text(repository, RESEARCH_DOC, use_embeddings=False)
    record_review(
        observation_id=observations_for("sample")[0]["id"],
        repository_id="sample",
        agent="codex",
        verdict="error",
        body="codex CLI not found",
    )

    run("status", "--registry", registry_file)
    out = capsys.readouterr().out
    assert "failed review" in out
    assert "--retry-failed" in out


def test_the_queue_is_empty_on_a_fresh_system(registry_file, capsys):
    assert run("queue", "--registry", registry_file) == 0
    assert "Nothing is awaiting a decision" in capsys.readouterr().out


def test_the_queue_shows_a_recommendation_and_how_to_answer(
    registry_file, accepted_recommendation, capsys
):
    assert run("queue", "sample", "--registry", registry_file) == 0

    out = capsys.readouterr().out
    assert "A change" in out
    assert f"decide sample {accepted_recommendation} --accept" in out
    assert "--reject --reason" in out


def test_the_queue_drops_a_recommendation_once_it_is_decided(
    registry_file, accepted_recommendation, capsys
):
    run("decide", "sample", str(accepted_recommendation), "--accept", "--registry", registry_file)
    capsys.readouterr()

    run("queue", "sample", "--registry", registry_file)
    assert "Nothing is awaiting a decision" in capsys.readouterr().out
