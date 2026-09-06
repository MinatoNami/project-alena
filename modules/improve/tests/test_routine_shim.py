"""The local endpoint that makes the second reviewer real.

`claude_review` was written against an assumed hosted trigger and, by its own
docstring, had never been run against a live one. What is tested here is not
that it answers -- that needs the CLI -- but the containment around it, since
a reviewer reached over HTTP is outside the Tool Gateway entirely.
"""

import json
import threading
import urllib.error
import urllib.request
from http.server import HTTPServer

import pytest

from modules.improve.agents import routine_shim


@pytest.fixture
def endpoint(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_ROUTINE_WORKSPACE", str(tmp_path / "empty"))
    monkeypatch.delenv("CLAUDE_ROUTINE_TOKEN", raising=False)

    server = HTTPServer(("127.0.0.1", 0), routine_shim.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()


def post(url, payload, token=None):
    request = urllib.request.Request(
        f"{url}/review",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.status, json.loads(response.read())


def test_it_speaks_the_contract_the_client_expects(endpoint, monkeypatch):
    monkeypatch.setattr(routine_shim, "run_claude", lambda prompt, **kw: (True, "a verdict"))

    status, body = post(endpoint, {"prompt": "judge this", "metadata": {"kind": "x"}})

    assert status == 200
    assert body == {"status": "completed", "result": "a verdict"}


def test_a_failure_is_not_dressed_up_as_an_answer(endpoint, monkeypatch):
    """An error returned as `result` would be parsed as a review."""
    monkeypatch.setattr(routine_shim, "run_claude", lambda prompt, **kw: (False, "no CLI"))

    with pytest.raises(urllib.error.HTTPError) as exc:
        post(endpoint, {"prompt": "judge this"})

    assert exc.value.code == 502


def test_a_prompt_is_required(endpoint):
    with pytest.raises(urllib.error.HTTPError) as exc:
        post(endpoint, {"metadata": {}})

    assert exc.value.code == 400


def test_a_token_is_enforced_when_one_is_set(endpoint, monkeypatch):
    monkeypatch.setenv("CLAUDE_ROUTINE_TOKEN", "secret")
    monkeypatch.setattr(routine_shim, "run_claude", lambda prompt, **kw: (True, "ok"))

    with pytest.raises(urllib.error.HTTPError) as exc:
        post(endpoint, {"prompt": "hello"})
    assert exc.value.code == 401

    status, _ = post(endpoint, {"prompt": "hello"}, token="secret")
    assert status == 200


def test_health_says_where_it_runs(endpoint, tmp_path):
    with urllib.request.urlopen(f"{endpoint}/health", timeout=10) as response:
        body = json.loads(response.read())

    assert body["status"] == "ok"
    assert body["workspace"] == str(tmp_path / "empty")


# -- containment -----------------------------------------------------------


def test_the_reviewer_runs_with_tools_denied(monkeypatch, tmp_path):
    """The prompt asks a model to judge a diff. Nothing it is sent should be
    actionable, and a request is not a boundary -- the flags are."""
    monkeypatch.setenv("CLAUDE_ROUTINE_WORKSPACE", str(tmp_path / "empty"))
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        seen["cwd"] = kwargs.get("cwd")

        class Result:
            returncode = 0
            stdout = "fine"
            stderr = ""

        return Result()

    monkeypatch.setattr(routine_shim.subprocess, "run", fake_run)

    ok, text = routine_shim.run_claude("judge this")

    assert ok and text == "fine"
    assert "--permission-prompts" in seen["command"]
    assert seen["command"][seen["command"].index("--permission-prompts") + 1] == "none"
    for tool in ("Bash", "Edit", "Write", "WebFetch"):
        assert tool in seen["command"], f"{tool} is not denied"


def test_it_runs_in_an_empty_directory_not_a_repository(monkeypatch, tmp_path):
    """A model handed untrusted research text should not also be handed a
    working tree."""
    monkeypatch.setenv("CLAUDE_ROUTINE_WORKSPACE", str(tmp_path / "somewhere"))

    directory = routine_shim.workspace()

    assert directory.is_dir()
    assert list(directory.iterdir()) == []
    assert not (directory / ".git").exists()


def test_it_refuses_to_bind_beyond_loopback():
    """This endpoint runs a model on request. Exposing it should not be
    something that happens by leaving a variable set."""
    with pytest.raises(SystemExit, match="loopback"):
        routine_shim.serve(host="0.0.0.0", port=9201)
