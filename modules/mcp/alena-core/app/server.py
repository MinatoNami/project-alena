"""The alena-core MCP server.

One implementation, one MCP contract, many consumers -- Claude, ChatGPT, a
local model, or ALENA's own CLI all reach the same functions in
`modules.improve.query`. Nothing here contains logic; if a body grows past
"call the function and shape the result", it belongs in the query layer.

Tools and resources are split the way the interoperability standard asks.
Stable readable context is a **resource**: a repository profile, its
architecture, its recommendations, the portfolio's capabilities. Anything that
searches or computes is a **tool**. Pretending a read is an executable action
makes every client treat it as one.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP

from modules.improve import query
from modules.improve.registry import RegistryError

mcp = FastMCP("alena-core")


def _dump(payload: Any) -> str:
    return json.dumps(payload, indent=2, default=str)


def _error(exc: Exception) -> str:
    """Structured errors, per the tool development rules.

    A caller that gets prose back cannot tell a missing repository from a
    broken server.
    """
    return _dump({"error": type(exc).__name__, "message": str(exc)})


# ---------------------------------------------------------------------------
# Tools: search and computation
# ---------------------------------------------------------------------------


@mcp.tool(name="repo.search")
def repo_search(repository_id: str, pattern: str, max_results: int = 50) -> str:
    """Search a declared repository's tracked files for a regular expression."""
    try:
        return _dump(query.search_repository(repository_id, pattern, max_results))
    except (RegistryError, Exception) as exc:  # noqa: B014 - RegistryError is a ValueError
        return _error(exc)


@mcp.tool(name="repo.find_todos")
def repo_find_todos(repository_id: str) -> str:
    """List the TODO and FIXME markers found in a repository's last scan."""
    try:
        return _dump(query.repository_todos(repository_id))
    except Exception as exc:  # noqa: BLE001
        return _error(exc)


@mcp.tool(name="repo.get_dependencies")
def repo_get_dependencies(repository_id: str) -> str:
    """List the dependencies a repository declares, across every manifest."""
    try:
        return _dump(query.repository_dependencies(repository_id))
    except Exception as exc:  # noqa: BLE001
        return _error(exc)


@mcp.tool(name="repo.get_history")
def repo_get_history(repository_id: str, limit: int = 10) -> str:
    """List recent scans of a repository, newest first."""
    try:
        return _dump(query.repository_history(repository_id, limit))
    except Exception as exc:  # noqa: BLE001
        return _error(exc)


@mcp.tool(name="memory.search")
def memory_search(query_text: str, repository_id: str = "", limit: int = 20) -> str:
    """Search what ALENA has proposed before, decided and undecided.

    Ask this before proposing something: it is how you find out an idea was
    already rejected, and why.
    """
    try:
        return _dump(
            query.search_memory(query_text, repository_id or None, limit)
        )
    except Exception as exc:  # noqa: BLE001
        return _error(exc)


@mcp.tool(name="recommendation.search")
def recommendation_search(
    query_text: str = "",
    repository_id: str = "",
    status: str = "",
    limit: int = 20,
) -> str:
    """Search recommendations, optionally filtered by repository and status."""
    try:
        return _dump(
            query.search_recommendations(
                query_text, repository_id or None, status or None, limit
            )
        )
    except Exception as exc:  # noqa: BLE001
        return _error(exc)


@mcp.tool(name="portfolio.search_capability")
def portfolio_search_capability(term: str) -> str:
    """Find which repositories already use a technology.

    The question behind the portfolio idea: before building a capability, find
    out whether the portfolio already has one.
    """
    try:
        return _dump(query.search_capability(term))
    except Exception as exc:  # noqa: BLE001
        return _error(exc)


@mcp.tool(name="portfolio.dependency_divergence")
def portfolio_dependency_divergence() -> str:
    """List dependencies pinned differently across repositories."""
    try:
        return _dump(query.portfolio_snapshot()["divergence"])
    except Exception as exc:  # noqa: BLE001
        return _error(exc)


# ---------------------------------------------------------------------------
# Resources: stable context
# ---------------------------------------------------------------------------


@mcp.resource("alena://repositories")
def repositories_resource() -> str:
    """Every repository ALENA is allowed to look at."""
    return _dump(query.list_repositories())


@mcp.resource("alena://repositories/{repository_id}/profile")
def profile_resource(repository_id: str) -> str:
    """A repository's latest scan: languages, dependencies, TODOs, summary."""
    try:
        return _dump(query.repository_profile(repository_id))
    except Exception as exc:  # noqa: BLE001
        return _error(exc)


@mcp.resource("alena://repositories/{repository_id}/architecture")
def architecture_resource(repository_id: str) -> str:
    """The local model's description of how a repository is built."""
    try:
        profile = query.repository_profile(repository_id)
    except Exception as exc:  # noqa: BLE001
        return _error(exc)
    return _dump(
        {
            "repository_id": repository_id,
            "summary": profile.get("summary"),
            "diff_summary": profile.get("diff_summary"),
            "languages": profile.get("languages"),
        }
    )


@mcp.resource("alena://repositories/{repository_id}/recommendations")
def recommendations_resource(repository_id: str) -> str:
    """Everything proposed for a repository, whatever was decided."""
    try:
        return _dump(
            query.search_recommendations("", repository_id, limit=200)
        )
    except Exception as exc:  # noqa: BLE001
        return _error(exc)


@mcp.resource("alena://portfolio/capabilities")
def portfolio_resource() -> str:
    """What the repositories share: technologies, divergences, findings."""
    return _dump(query.portfolio_snapshot())
