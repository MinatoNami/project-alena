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
        "--full-auto",
        "--sandbox",
        "workspace-write",
    ]


def test_run_codex_raises_on_error(monkeypatch):
    def fake_run(cmd, input, capture_output, text, cwd, check):
        return SimpleNamespace(returncode=1, stdout="", stderr="boom")

    monkeypatch.setattr(codex_runner.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="boom"):
        codex_runner.run_codex("fail")
