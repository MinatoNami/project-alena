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
