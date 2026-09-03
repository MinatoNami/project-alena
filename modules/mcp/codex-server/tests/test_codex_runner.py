from types import SimpleNamespace

import pytest

from app import codex_runner


def test_run_codex_builds_command_without_apply(monkeypatch):
    captured = {}

    def fake_run(cmd, input, capture_output, text, cwd, check):
        captured["cmd"] = cmd
        captured["input"] = input
        captured["capture_output"] = capture_output
        captured["text"] = text
        captured["cwd"] = cwd
        captured["check"] = check
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(codex_runner.subprocess, "run", fake_run)

    result = codex_runner.run_codex("hello", cwd="/repo", extra_args=["--foo", "bar"])

    assert result == "ok"
    assert captured["cmd"] == [
        codex_runner.CODEX_BIN,
        "exec",
        "--json",
        "--foo",
        "bar",
        "--sandbox",
        "read-only",
    ]
    assert captured["input"] == "hello"
    assert captured["cwd"] == "/repo"
    assert captured["capture_output"] is True
    assert captured["text"] is True
    assert captured["check"] is False


def test_run_codex_builds_command_with_apply(monkeypatch):
    captured = {}

    def fake_run(cmd, input, capture_output, text, cwd, check):
        captured["cmd"] = cmd
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(codex_runner.subprocess, "run", fake_run)

    codex_runner.run_codex("apply", extra_args=["--apply", "--flag"])

    assert captured["cmd"] == [
        codex_runner.CODEX_BIN,
        "exec",
        "--json",
        "--flag",
        "--sandbox",
        "workspace-write",
    ]


def test_run_codex_raises_on_error(monkeypatch):
    def fake_run(cmd, input, capture_output, text, cwd, check):
        return SimpleNamespace(returncode=1, stdout="", stderr="boom")

    monkeypatch.setattr(codex_runner.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="boom"):
        codex_runner.run_codex("fail")


def test_analysis_runs_in_a_read_only_sandbox(monkeypatch):
    """Defence in depth: a read tool cannot write even if something above it
    went wrong."""
    captured = {}

    def fake_run(cmd, input, capture_output, text, cwd, check):
        captured["cmd"] = cmd
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(codex_runner.subprocess, "run", fake_run)
    codex_runner.run_codex("analyse this")

    assert captured["cmd"][-2:] == ["--sandbox", "read-only"]


def test_full_auto_is_not_passed(monkeypatch):
    """It was removed in codex-cli 0.153 and makes the whole call fail."""
    captured = {}

    def fake_run(cmd, input, capture_output, text, cwd, check):
        captured["cmd"] = cmd
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(codex_runner.subprocess, "run", fake_run)
    codex_runner.run_codex("edit", extra_args=["--apply"])

    assert "--full-auto" not in captured["cmd"]
