"""The registry is what supersedes the hardcoded allowlist in safety.py."""

import pytest

from modules.gateway import set_gateway
from modules.gateway.errors import RepositoryPathDenied
from modules.improve.registry import parse_registry
from modules.improve.wiring import build_gateway, install_gateway


@pytest.fixture
def two_repos(tmp_path):
    for name in ("one", "two"):
        (tmp_path / name).mkdir()
    return parse_registry(
        {
            "repositories": [
                {"id": "one", "workspace": {"path": str(tmp_path / "one")}},
                {"id": "two", "workspace": {"path": str(tmp_path / "two")}},
            ]
        }
    )


def test_the_gateway_takes_its_allowed_roots_from_the_registry(two_repos, tmp_path):
    gateway = build_gateway(two_repos)

    assert sorted(gateway._repo_roots()) == sorted(
        [str(tmp_path / "one"), str(tmp_path / "two")]
    )


@pytest.mark.asyncio
async def test_a_path_outside_every_declared_workspace_is_refused(two_repos):
    gateway = build_gateway(two_repos)

    with pytest.raises(RepositoryPathDenied):
        await gateway.call(
            None, "codex_analyze", {"repo_path": "/etc", "question": "?"}
        )


@pytest.mark.asyncio
async def test_a_path_inside_a_declared_workspace_passes_the_guard(two_repos, tmp_path):
    """It reaches the tool, which is as far as this test cares."""
    calls = []

    class Pool:
        async def call_tool(self, server, tool, arguments):
            calls.append(tool)
            return "ok"

    gateway = build_gateway(two_repos)
    gateway._pool = Pool()

    await gateway.call(
        None,
        "codex_analyze",
        {"repo_path": str(tmp_path / "one"), "question": "?"},
        agent="assistant",
    )

    assert calls == ["codex_analyze"]


def test_install_replaces_the_process_gateway(two_repos):
    from modules.gateway import get_gateway

    try:
        installed = install_gateway(two_repos)
        assert get_gateway() is installed
    finally:
        set_gateway(None)
