from app import tools


def test_format_repo_prompt_includes_expected_sections():
    prompt = tools._format_repo_prompt(
        "/repo",
        "Do the thing",
        mode="analysis",
        constraints="Be safe",
        include_plan=True,
    )

    assert "repository at: /repo" in prompt
    assert "Mode: analysis" in prompt
    assert "Provide a concise, step-by-step plan" in prompt
    assert "Constraints:\nBe safe" in prompt
    assert "Instruction:" in prompt
    assert "Do the thing" in prompt


def test_codex_generate_calls_runner(monkeypatch):
    captured = {}

    def fake_run_codex(prompt, cwd=None, extra_args=None):
        captured["prompt"] = prompt
        captured["cwd"] = cwd
        captured["extra_args"] = extra_args
        return "ok"

    monkeypatch.setattr(tools, "run_codex", fake_run_codex)

    result = tools.codex_generate("hello")

    assert result == "ok"
    assert captured["prompt"] == "hello"
    assert captured["cwd"] is None
    assert captured["extra_args"] is None


def test_codex_plan_builds_prompt_and_cwd(monkeypatch):
    captured = {}

    def fake_run_codex(prompt, cwd=None, extra_args=None):
        captured["prompt"] = prompt
        captured["cwd"] = cwd
        captured["extra_args"] = extra_args
        return "ok"

    monkeypatch.setattr(tools, "run_codex", fake_run_codex)

    tools.codex_plan("/repo", "Add rate limiting")

    assert "Mode: planning" in captured["prompt"]
    assert "Add rate limiting" in captured["prompt"]
    assert "Provide a concise, step-by-step plan" in captured["prompt"]
    assert "Do not modify files" in captured["prompt"]
    assert captured["cwd"] == "/repo"
    assert captured["extra_args"] is None


def test_codex_analyze_builds_prompt_and_cwd(monkeypatch):
    captured = {}

    def fake_run_codex(prompt, cwd=None, extra_args=None):
        captured["prompt"] = prompt
        captured["cwd"] = cwd
        captured["extra_args"] = extra_args
        return "ok"

    monkeypatch.setattr(tools, "run_codex", fake_run_codex)

    tools.codex_analyze("/repo", "Where is auth?")

    assert "Mode: analysis" in captured["prompt"]
    assert "Where is auth?" in captured["prompt"]
    assert "Do not modify files" in captured["prompt"]
    assert captured["cwd"] == "/repo"
    assert captured["extra_args"] is None


def test_codex_summarize_without_focus(monkeypatch):
    captured = {}

    def fake_run_codex(prompt, cwd=None, extra_args=None):
        captured["prompt"] = prompt
        captured["cwd"] = cwd
        captured["extra_args"] = extra_args
        return "ok"

    monkeypatch.setattr(tools, "run_codex", fake_run_codex)

    tools.codex_summarize("/repo")

    assert "Mode: summarize" in captured["prompt"]
    assert "Provide a concise summary of the repository" in captured["prompt"]
    assert "Focus:" not in captured["prompt"]
    assert captured["cwd"] == "/repo"
    assert captured["extra_args"] is None


def test_codex_summarize_with_focus(monkeypatch):
    captured = {}

    def fake_run_codex(prompt, cwd=None, extra_args=None):
        captured["prompt"] = prompt
        captured["cwd"] = cwd
        captured["extra_args"] = extra_args
        return "ok"

    monkeypatch.setattr(tools, "run_codex", fake_run_codex)

    tools.codex_summarize("/repo", focus="architecture")

    assert "Focus: architecture" in captured["prompt"]
    assert captured["cwd"] == "/repo"


def test_codex_doc_outline(monkeypatch):
    captured = {}

    def fake_run_codex(prompt, cwd=None, extra_args=None):
        captured["prompt"] = prompt
        captured["cwd"] = cwd
        captured["extra_args"] = extra_args
        return "ok"

    monkeypatch.setattr(tools, "run_codex", fake_run_codex)

    tools.codex_doc_outline("/repo", topic="Auth", audience="backend engineers")

    assert "Mode: docs" in captured["prompt"]
    assert "Create a documentation outline for: Auth" in captured["prompt"]
    assert "Target audience: backend engineers" in captured["prompt"]
    assert captured["cwd"] == "/repo"


def test_codex_test_plan(monkeypatch):
    captured = {}

    def fake_run_codex(prompt, cwd=None, extra_args=None):
        captured["prompt"] = prompt
        captured["cwd"] = cwd
        captured["extra_args"] = extra_args
        return "ok"

    monkeypatch.setattr(tools, "run_codex", fake_run_codex)

    tools.codex_test_plan("/repo", goal="password reset")

    assert "Mode: test-plan" in captured["prompt"]
    assert "Create a test plan for: password reset" in captured["prompt"]
    assert captured["cwd"] == "/repo"


def test_codex_edit_passes_apply(monkeypatch):
    captured = {}

    def fake_run_codex(prompt, cwd=None, extra_args=None):
        captured["prompt"] = prompt
        captured["cwd"] = cwd
        captured["extra_args"] = extra_args
        return "ok"

    monkeypatch.setattr(tools, "run_codex", fake_run_codex)

    tools.codex_edit("/repo", "Refactor logging")

    assert "Mode: apply" in captured["prompt"]
    assert "Refactor logging" in captured["prompt"]
    assert captured["cwd"] == "/repo"
    assert captured["extra_args"] == ["--apply"]


def test_codex_refactor_passes_apply_and_constraints(monkeypatch):
    captured = {}

    def fake_run_codex(prompt, cwd=None, extra_args=None):
        captured["prompt"] = prompt
        captured["cwd"] = cwd
        captured["extra_args"] = extra_args
        return "ok"

    monkeypatch.setattr(tools, "run_codex", fake_run_codex)

    tools.codex_refactor("/repo", "Split service", constraints="Keep APIs stable")

    assert "Mode: refactor" in captured["prompt"]
    assert "Split service" in captured["prompt"]
    assert "Keep APIs stable" in captured["prompt"]
    assert "Provide a brief summary of changes" in captured["prompt"]
    assert captured["cwd"] == "/repo"
    assert captured["extra_args"] == ["--apply"]
