import pytest

from modules.gateway.catalog import ToolCatalog, static_contracts
from modules.gateway.contracts import ToolContract
from modules.gateway.policy import parse_policy


def catalog():
    return ToolCatalog(
        parse_policy(
            {
                "version": 1,
                "tools": {
                    "a": {"side_effect": "read_only", "allowed_agents": ["assistant"]},
                    "b": {"side_effect": "read_only", "allowed_agents": ["codex"]},
                    "gone": {"side_effect": "read_only", "allowed_agents": ["*"]},
                },
            }
        )
    )


def test_discovered_contract_replaces_a_static_one():
    c = catalog()
    c.register([ToolContract(name="a", description="old", source="static")])
    c.register([ToolContract(name="a", description="new", source="mcp")])

    assert c.get("a").contract.description == "new"


def test_static_does_not_clobber_a_discovered_contract():
    """Registration order must not decide which source of truth wins."""
    c = catalog()
    c.register([ToolContract(name="a", description="new", source="mcp")])
    c.register([ToolContract(name="a", description="old", source="static")])

    assert c.get("a").contract.description == "new"


def test_undeclared_lists_tools_policy_has_not_seen():
    c = catalog()
    c.register([ToolContract(name="a"), ToolContract(name="surprise")])

    assert c.undeclared() == ["surprise"]


def test_unimplemented_lists_stale_policy_entries():
    c = catalog()
    c.register([ToolContract(name="a"), ToolContract(name="b")])

    assert c.unimplemented() == ["gone"]


def test_openai_tools_are_filtered_to_what_the_agent_may_call():
    c = catalog()
    c.register([ToolContract(name="a"), ToolContract(name="b")])

    names = [t["function"]["name"] for t in c.openai_tools("assistant")]
    assert names == ["a"]


def test_undeclared_tools_are_never_offered_to_a_planner():
    c = catalog()
    c.register([ToolContract(name="surprise")])

    assert c.openai_tools("assistant") == []


def test_missing_tool_returns_none():
    assert catalog().get("nope") is None


def test_every_legacy_tool_is_declared_in_the_shipped_policy():
    """The legacy definitions and config/tool_policy.yaml must not drift.

    Only one direction is checkable here: the policy also declares the
    alena-core tools, which arrive by discovery rather than from the static
    provider. Both directions are checked once both providers have run --
    see test_alena_core_tools_are_discovered_and_all_declared.
    """
    from modules.gateway.policy import load_policy

    c = ToolCatalog(load_policy())
    c.register(static_contracts())

    assert c.undeclared() == [], "tools exist that the policy does not declare"


def test_a_server_claiming_worse_than_policy_is_flagged():
    """A tool that starts reporting destructiveHint has changed under us."""
    from modules.gateway.contracts import SideEffect

    c = catalog()
    c.register(
        [ToolContract(name="a", side_effect_hint=SideEffect.DESTRUCTIVE, source="mcp")]
    )

    assert c.disagreements() == [("a", SideEffect.READ_ONLY, SideEffect.DESTRUCTIVE)]


def test_a_server_claiming_safer_than_policy_is_not_flagged():
    """The hint never lowers a classification, so it is not a disagreement."""
    from modules.gateway.contracts import SideEffect

    c = ToolCatalog(
        parse_policy(
            {"version": 1, "tools": {"a": {"side_effect": "destructive"}}}
        )
    )
    c.register(
        [ToolContract(name="a", side_effect_hint=SideEffect.READ_ONLY, source="mcp")]
    )

    assert c.disagreements() == []


# --- discovery of ALENA's own servers --------------------------------------


@pytest.mark.asyncio
async def test_alena_core_tools_are_discovered_and_all_declared(tmp_path, monkeypatch):
    """MCP-first: the contract comes from the server, the policy from the file.

    Fails if a tool ships without a policy entry, or a policy entry outlives
    its tool.
    """
    monkeypatch.setenv("ALENA_DB_PATH", str(tmp_path / "state.db"))
    from modules.gateway.catalog import discover_into
    from modules.gateway.policy import load_policy
    from modules.gateway.pool import MCPSessionPool

    catalog = ToolCatalog(load_policy())
    catalog.register(static_contracts())

    pool = MCPSessionPool()
    try:
        discovered = await discover_into(catalog, pool)
    finally:
        await pool.aclose()

    assert discovered, "alena-core advertised no tools"
    assert catalog.undeclared() == []
    assert catalog.unimplemented() == []
    assert all(catalog.get(name).contract.source == "mcp" for name in discovered)


@pytest.mark.asyncio
async def test_a_server_that_will_not_start_does_not_take_the_catalog_with_it(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("ALENA_DB_PATH", str(tmp_path / "state.db"))
    from modules.gateway import catalog as catalog_module
    from modules.gateway.policy import load_policy

    monkeypatch.setattr(
        catalog_module, "DISCOVERABLE_SERVERS", (("broken", "does-not-exist"),)
    )

    catalog = ToolCatalog(load_policy())
    catalog.register(static_contracts())

    assert await catalog_module.discover_into(catalog) == []
    assert catalog.names()  # the static tools are still there
