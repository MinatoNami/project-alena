import subprocess
from pathlib import Path

import pytest

from modules.improve.registry import parse_registry


def git(workspace: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(workspace), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


@pytest.fixture
def repo(tmp_path) -> Path:
    """A real git repository.

    Real rather than mocked: the scanner's whole job is reading git, and a
    fake `git` would only prove the fake behaves as expected.
    """
    workspace = tmp_path / "sample"
    workspace.mkdir()
    git(workspace, "init", "-q", "-b", "main")
    git(workspace, "config", "user.email", "test@example.com")
    git(workspace, "config", "user.name", "Test")

    (workspace / "README.md").write_text("# Sample\n\nA sample project.\n")
    (workspace / "requirements.txt").write_text("httpx>=0.27\nfastapi\n# comment\n")
    (workspace / "app.py").write_text("# TODO: wire up the router\nprint('hi')\n")
    git(workspace, "add", "-A")
    git(workspace, "commit", "-q", "-m", "Initial commit")
    return workspace


@pytest.fixture
def registry(repo):
    return parse_registry(
        {
            "repositories": [
                {
                    "id": "sample",
                    "name": "Sample",
                    "workspace": {"path": str(repo)},
                    "capabilities": {"modify": False},
                }
            ]
        }
    )


@pytest.fixture
def repository(registry):
    return registry.resolve("sample")


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Keep every test out of ~/.alena."""
    monkeypatch.setenv("ALENA_DB_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("ALENA_INTELLIGENCE_DIR", str(tmp_path / "intelligence"))
    monkeypatch.delenv("ALENA_WORKSPACE_ROOT", raising=False)
    monkeypatch.delenv("ALENA_REPOSITORIES", raising=False)
    from modules.store import db

    db.reset_connection()
    yield
    db.reset_connection()
