"""Starting pipeline steps from the dashboard.

The interesting cases are refusals: a second run while one is going, and a
command that is not on the list.
"""

import time

import pytest
from fastapi.testclient import TestClient

from modules.improve.web import runs as runs_module
from modules.improve.web.api import create_app
from modules.improve.web.runs import COMMANDS, Busy, Runner

DASHBOARD = {"X-Alena-Dashboard": "1"}


@pytest.fixture(autouse=True)
def fresh_runner():
    runs_module.reset_runner()
    yield
    runs_module.reset_runner()


@pytest.fixture
def fake_wrapper(tmp_path):
    """A stand-in for the real wrapper: prints its arguments, then exits."""
    script = tmp_path / "wrapper.sh"
    script.write_text('#!/bin/sh\necho "ran: $*"\nexit ${ALENA_TEST_EXIT:-0}\n')
    script.chmod(0o755)
    return script


@pytest.fixture
def slow_wrapper(tmp_path):
    script = tmp_path / "slow.sh"
    script.write_text('#!/bin/sh\nsleep 5\n')
    script.chmod(0o755)
    return script


def wait_for(run, runner, state="finished", timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if run.state == state:
            return run
        time.sleep(0.05)
    raise AssertionError(f"run stayed {run.state}, expected {state}")


# -- what may be started ---------------------------------------------------


def test_implement_is_not_something_a_browser_can_start():
    """It writes to a repository, and it is the thing most worth watching."""
    assert "implement" not in COMMANDS
    assert not any("implement" in c.args for c in COMMANDS.values())


def test_ingest_research_is_not_offered():
    """It needs a file path, and a browser should not be choosing one."""
    assert not any("ingest-research" in c.args for c in COMMANDS.values())


def test_a_command_that_spends_something_says_so():
    """A button that quietly costs Codex quota is one people regret."""
    assert COMMANDS["review"].costs
    assert COMMANDS["scan"].costs is None


def test_the_claude_preview_is_a_dry_run():
    assert "--dry-run" in COMMANDS["escalate-dry-run"].args


# -- the runner ------------------------------------------------------------


def test_a_run_captures_its_output(fake_wrapper):
    runner = Runner(fake_wrapper)
    run = wait_for(runner.start("scan"), runner)

    assert run.exit_code == 0
    assert any("ran: scan --all" in line for line in run.output)


def test_a_failing_command_is_marked_failed(fake_wrapper, monkeypatch):
    monkeypatch.setenv("ALENA_TEST_EXIT", "1")
    runner = Runner(fake_wrapper)
    run = wait_for(runner.start("scan"), runner, state="failed")

    assert run.exit_code == 1


def test_a_missing_wrapper_fails_rather_than_hanging(tmp_path):
    runner = Runner(tmp_path / "does-not-exist.sh")
    run = wait_for(runner.start("scan"), runner, state="failed")

    assert "could not start" in run.output[0]


def test_only_one_runs_at_a_time(slow_wrapper):
    """They share a database and the same workspaces."""
    runner = Runner(slow_wrapper)
    runner.start("scan")

    with pytest.raises(Busy, match="already running"):
        runner.start("recommend")


def test_a_second_run_is_refused_rather_than_queued(slow_wrapper):
    """Queueing would let a stray double-click spend a second Codex review."""
    runner = Runner(slow_wrapper)
    runner.start("scan")

    with pytest.raises(Busy):
        runner.start("scan")
    assert len(runner.runs()) == 1


def test_the_slot_is_released_when_a_run_finishes(fake_wrapper):
    runner = Runner(fake_wrapper)
    wait_for(runner.start("scan"), runner)

    assert runner.current is None
    assert runner.start("recommend")


def test_the_slot_is_released_when_a_run_fails(fake_wrapper, monkeypatch):
    monkeypatch.setenv("ALENA_TEST_EXIT", "2")
    runner = Runner(fake_wrapper)
    wait_for(runner.start("scan"), runner, state="failed")

    assert runner.current is None


def test_an_unknown_command_is_rejected(fake_wrapper):
    with pytest.raises(KeyError):
        Runner(fake_wrapper).start("rm-rf")


def test_history_is_bounded(fake_wrapper):
    runner = Runner(fake_wrapper)
    for _ in range(runs_module.KEEP_RUNS + 5):
        wait_for(runner.start("scan"), runner)

    assert len(runner.runs()) == runs_module.KEEP_RUNS


# -- through the API -------------------------------------------------------


@pytest.fixture
def client(tmp_path, monkeypatch, fake_wrapper):
    import yaml

    registry = tmp_path / "repositories.yaml"
    registry.write_text(
        yaml.safe_dump(
            {"repositories": [{"id": "sample", "workspace": {"path": str(tmp_path)}}]}
        )
    )
    monkeypatch.setenv("ALENA_REPOSITORIES", str(registry))
    monkeypatch.setenv("ALENA_DB_PATH", str(tmp_path / "state.db"))
    runs_module._runner = Runner(fake_wrapper)
    return TestClient(create_app())


def test_the_api_lists_what_can_be_started(client):
    keys = {c["key"] for c in client.get("/api/commands").json()}
    assert keys == set(COMMANDS)


def test_starting_a_run_returns_its_id(client):
    response = client.post("/api/runs", json={"command": "scan"}, headers=DASHBOARD)

    assert response.status_code == 200
    assert response.json()["state"] in ("running", "finished")


def test_a_run_can_be_polled(client):
    run_id = client.post("/api/runs", json={"command": "scan"}, headers=DASHBOARD).json()["id"]
    for _ in range(100):
        body = client.get(f"/api/runs/{run_id}").json()
        if body["state"] != "running":
            break
        time.sleep(0.05)

    assert body["state"] == "finished"
    assert any("ran: scan" in line for line in body["output"])


def test_starting_a_run_needs_the_dashboard_header(client):
    """It is state-changing, so the same guard as approving applies."""
    assert client.post("/api/runs", json={"command": "scan"}).status_code == 403


def test_an_unknown_command_is_a_400(client):
    response = client.post("/api/runs", json={"command": "rm-rf"}, headers=DASHBOARD)

    assert response.status_code == 400
    assert "scan" in response.json()["detail"]


def test_a_second_run_is_a_409_not_a_500(client, slow_wrapper):
    """Nothing is broken; the caller has to wait."""
    runs_module._runner = Runner(slow_wrapper)
    client.post("/api/runs", json={"command": "scan"}, headers=DASHBOARD)

    response = client.post("/api/runs", json={"command": "recommend"}, headers=DASHBOARD)
    assert response.status_code == 409
    assert "already running" in response.json()["detail"]


def test_an_unknown_run_is_a_404(client):
    assert client.get("/api/runs/nope").status_code == 404
