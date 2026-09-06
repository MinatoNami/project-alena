"""The alena-core MCP contract.

These pin the contract itself. A tool's name and schema are what every client
depends on, so a change to either should show up as a failing test rather than
as a client that quietly stops working.
"""

import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import pytest

_SERVER = Path(__file__).resolve().parents[1]
_ROOT = Path(__file__).resolve().parents[4]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Loaded by path, under a unique name, rather than by putting the server's
# directory on sys.path. Every MCP server in this repo has a package called
# `app`, so the first one imported would shadow the rest for the whole test
# session -- which is exactly what happens when the full suite runs.
_spec = importlib.util.spec_from_file_location(
    "alena_core_server", _SERVER / "app" / "server.py"
)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
mcp = _module.mcp

from modules.gateway.contracts import SideEffect  # noqa: E402
from modules.gateway.policy import load_policy  # noqa: E402

EXPECTED_TOOLS = {
    "memory.search": ["query_text"],
    "portfolio.dependency_divergence": [],
    "portfolio.search_capability": ["term"],
    "recommendation.search": [],
    "repo.find_todos": ["repository_id"],
    "repo.get_dependencies": ["repository_id"],
    "repo.get_history": ["repository_id"],
    "repo.read_file": ["path", "repository_id"],
    "repo.search": ["pattern", "repository_id"],
    "resource.list": [],
    "resource.read": ["uri"],
}

EXPECTED_RESOURCES = {
    "alena://repositories",
    "alena://portfolio/capabilities",
}

EXPECTED_TEMPLATES = {
    "alena://repositories/{repository_id}/profile",
    "alena://repositories/{repository_id}/architecture",
    "alena://repositories/{repository_id}/recommendations",
}


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setenv("ALENA_DB_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("ALENA_INTELLIGENCE_DIR", str(tmp_path / "intel"))
    from modules.store import db

    db.reset_connection()
    yield
    db.reset_connection()


def tools():
    return asyncio.run(mcp.list_tools())


# -- the contract ----------------------------------------------------------


def test_the_tool_list_is_what_clients_expect():
    assert {t.name for t in tools()} == set(EXPECTED_TOOLS)


def test_each_tool_requires_what_it_says():
    for tool in tools():
        required = sorted(tool.inputSchema.get("required", []))
        assert required == sorted(EXPECTED_TOOLS[tool.name]), tool.name


def test_every_tool_is_described():
    """The description is how an agent decides whether the tool is the one."""
    for tool in tools():
        assert tool.description and len(tool.description.strip()) > 20, tool.name


def test_the_resources_are_what_clients_expect():
    resources = asyncio.run(mcp.list_resources())
    assert {str(r.uri) for r in resources} == EXPECTED_RESOURCES


def test_the_resource_templates_are_what_clients_expect():
    templates = asyncio.run(mcp.list_resource_templates())
    assert {t.uriTemplate for t in templates} == EXPECTED_TEMPLATES


def test_reads_are_resources_and_searches_are_tools():
    """The standard's split: pretending a read is an action makes clients
    treat it as one."""
    tool_names = {t.name for t in tools()}
    assert not any(name.endswith(".get_profile") for name in tool_names)
    assert any("search" in name for name in tool_names)


# -- the invariant that makes this safe to expose --------------------------


def test_every_tool_is_declared_read_only():
    """A client configured to reach alena-core talks to it directly, with no
    gateway in between. Read-only by construction is what makes that safe --
    so adding a tool that writes has to fail here."""
    policy = load_policy(str(_ROOT / "config" / "tool_policy.yaml"))

    for tool in tools():
        declared = policy.tool(tool.name)
        assert declared is not None, f"{tool.name} is not in the tool policy"
        assert declared.side_effect is SideEffect.READ_ONLY, tool.name


def test_no_tool_name_suggests_a_write():
    forbidden = ("create", "delete", "write", "edit", "push", "commit", "apply", "run")
    for tool in tools():
        action = tool.name.split(".", 1)[-1]
        assert not any(action.startswith(word) for word in forbidden), tool.name


# -- behaviour -------------------------------------------------------------


def call(name, arguments):
    result = asyncio.run(mcp.call_tool(name, arguments))
    return json.loads(result[0][0].text)


def test_an_unknown_repository_returns_a_structured_error():
    """A caller that gets prose cannot tell a bad id from a broken server."""
    payload = call("repo.search", {"repository_id": "nope", "pattern": "x"})

    assert payload["error"]
    assert "nope" in payload["message"]


def test_an_unscanned_repository_says_what_to_run():
    payload = json.loads(
        list(asyncio.run(mcp.read_resource("alena://repositories/nope/profile")))[0].content
    )
    assert "message" in payload


def test_the_doorway_lists_every_resource_and_template():
    """One tool that says "read a resource", not one tool per resource.

    It delegates to the server's own registry, so a resource added above shows
    up here without anyone remembering to add it twice.
    """
    listed = call("resource.list", {})

    assert {r["uri"] for r in listed["resources"]} == EXPECTED_RESOURCES
    assert {t["uri_template"] for t in listed["templates"]} == EXPECTED_TEMPLATES


def test_the_doorway_reads_a_templated_resource():
    result = asyncio.run(
        mcp.call_tool("resource.read", {"uri": "alena://repositories"})
    )
    payload = json.loads(result[0][0].text)

    assert isinstance(payload, list)


def test_the_doorway_returns_a_structured_error_for_an_unknown_uri():
    result = asyncio.run(mcp.call_tool("resource.read", {"uri": "alena://nope"}))
    payload = json.loads(result[0][0].text)

    assert payload["error"]


def test_registry_tags_are_known_before_anything_is_scanned():
    """Tags are declared, not discovered, so they answer even on a cold start."""
    matches = call("portfolio.search_capability", {"term": "django"})

    assert set(matches) == {"tag:django"}


def test_a_capability_nothing_declares_returns_nothing():
    assert call("portfolio.search_capability", {"term": "cobol"}) == {}


def test_the_repositories_resource_lists_the_registry():
    content = list(asyncio.run(mcp.read_resource("alena://repositories")))[0].content
    ids = {row["id"] for row in json.loads(content)}

    assert "project-alena" in ids
