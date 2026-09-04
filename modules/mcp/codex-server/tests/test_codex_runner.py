import io
import json

import pytest

from app import codex_runner


class Stdin(io.StringIO):
    """Keeps what was written after close(), which StringIO does not."""

    written = ""

    def close(self):
        self.written = self.getvalue()
        super().close()


class FakeProcess:
    """A Codex run: JSONL on stdout, a message on stderr, an exit code.

    `on_line` fires as each stdout line is consumed, which is how the test
    for incremental progress observes what has been emitted so far.
    """

    def __init__(self, lines, returncode=0, stderr="", on_line=None):
        self.stdin = Stdin()
        self.stderr = io.StringIO(stderr)
        self._returncode = returncode
        self._lines = list(lines)
        self._on_line = on_line

    @property
    def stdout(self):
        def generate():
            for line in self._lines:
                yield line
                if self._on_line:
                    self._on_line()

        return generate()

    def wait(self):
        return self._returncode


@pytest.fixture
def spawn(monkeypatch):
    """Capture the command, and control what Codex 'emits'."""
    captured = {}

    def make(lines=(), returncode=0, stderr="", on_line=None):
        def fake_popen(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["cwd"] = kwargs.get("cwd")
            captured["process"] = FakeProcess(list(lines), returncode, stderr, on_line)
            return captured["process"]

        monkeypatch.setattr(codex_runner.subprocess, "Popen", fake_popen)
        return captured

    return make


def event(**payload) -> str:
    return json.dumps(payload) + "\n"


# -- the command ------------------------------------------------------------


def test_analysis_runs_in_a_read_only_sandbox(spawn):
    """Defence in depth: a read tool cannot write even if something above it
    went wrong."""
    captured = spawn()
    codex_runner.run_codex("analyse this")

    assert captured["cmd"][:3] == [codex_runner.CODEX_BIN, "exec", "--json"]
    assert captured["cmd"][-2:] == ["--sandbox", "read-only"]


def test_apply_mode_asks_for_workspace_write(spawn):
    captured = spawn()
    codex_runner.run_codex("edit", extra_args=["--apply", "--flag"])

    assert "--flag" in captured["cmd"]
    assert captured["cmd"][-2:] == ["--sandbox", "workspace-write"]


def test_full_auto_is_not_passed(spawn):
    """It was removed in codex-cli 0.153 and makes the whole call fail."""
    captured = spawn()
    codex_runner.run_codex("edit", extra_args=["--apply"])

    assert "--full-auto" not in captured["cmd"]


def test_the_prompt_is_written_to_stdin(spawn):
    captured = spawn()
    codex_runner.run_codex("do the thing", cwd="/repo")

    assert captured["process"].stdin.written == "do the thing"
    assert captured["cwd"] == "/repo"


# -- the returned output ----------------------------------------------------


def test_every_line_is_returned_for_the_caller_to_parse(spawn):
    lines = [
        event(type="item.completed", item={"type": "agent_message", "text": "Done."}),
        event(type="turn.completed", usage={}),
    ]
    spawn(lines)

    assert codex_runner.run_codex("x") == "".join(lines)


def test_a_failure_raises_with_the_message(spawn):
    spawn(returncode=1, stderr="boom")

    with pytest.raises(RuntimeError, match="boom"):
        codex_runner.run_codex("fail")


def test_a_silent_failure_still_says_something(spawn):
    spawn(returncode=2, stderr="")

    with pytest.raises(RuntimeError, match="non-zero"):
        codex_runner.run_codex("fail")


# -- progress, which is the point ------------------------------------------


def test_progress_goes_to_stderr_not_stdout(spawn, capsys):
    """stdout is the MCP protocol channel; progress there corrupts it."""
    spawn([event(type="item.started", item={"type": "command_execution", "command": "ls"})])
    codex_runner.run_codex("x")

    captured = capsys.readouterr()
    assert "ls" in captured.err
    assert captured.out == ""


def test_progress_is_written_as_each_event_arrives(spawn, capsys):
    """Not collected and dumped at the end -- that is the thing being fixed.

    Observed by reading stderr partway through the stream: the first event's
    line has to be there before the second is consumed.
    """
    seen = []

    def snapshot():
        seen.append(capsys.readouterr().err)

    spawn(
        [
            event(type="item.started", item={"type": "command_execution", "command": "one"}),
            event(type="item.started", item={"type": "command_execution", "command": "two"}),
        ],
        on_line=snapshot,
    )
    codex_runner.run_codex("x")

    assert "one" in seen[0], "the first line had not been written yet"
    assert "two" not in seen[0], "the second was written before its event arrived"
    assert "two" in seen[1]


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"type": "item.started", "item": {"type": "command_execution", "command": "ls -la"}}, "$ ls -la"),
        ({"type": "item.completed", "item": {"type": "command_execution", "exit_code": 1}}, "exit 1"),
        ({"type": "item.completed", "item": {"type": "file_change", "changes": [{"path": "/a/b/x.py"}]}}, "changed x.py"),
        ({"type": "item.completed", "item": {"type": "agent_message", "text": "First.\nSecond."}}, "First."),
        ({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 2}}, "done"),
    ],
)
def test_events_read_as_something_happening(payload, expected):
    assert expected in codex_runner.describe_event(json.dumps(payload))


def test_reasoning_is_not_reported():
    """It is the bulk of the output, and it is thinking rather than doing."""
    assert codex_runner.describe_event(
        json.dumps({"type": "item.completed", "item": {"type": "reasoning", "text": "hm"}})
    ) is None


def test_a_successful_command_is_not_reported():
    """Only the failures are worth a line; the command itself was announced."""
    assert codex_runner.describe_event(
        json.dumps({"type": "item.completed", "item": {"type": "command_execution", "exit_code": 0}})
    ) is None


def test_a_line_that_is_not_an_event_is_ignored():
    assert codex_runner.describe_event("not json") is None
    assert codex_runner.describe_event("[1, 2, 3]") is None
    assert codex_runner.describe_event("") is None


def test_a_long_command_is_truncated(spawn, capsys):
    spawn([event(type="item.started", item={"type": "command_execution", "command": "x" * 500})])
    codex_runner.run_codex("x")

    line = capsys.readouterr().err.strip()
    assert len(line) <= codex_runner.MAX_PROGRESS_CHARS
