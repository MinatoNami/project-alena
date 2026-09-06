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


def test_the_prompt_section_lists_the_same_tools_as_the_array():
    """The two must agree.

    Native tool calling makes the prompt list redundant in principle, but local
    models lean on it, and naming a tool there that the array withholds teaches
    the model to ask for calls the policy will refuse.
    """
    c = catalog()
    c.register(
        [
            ToolContract(
                name="a",
                input_schema={
                    "type": "object",
                    "properties": {
                        "one": {"type": "string"},
                        "two": {"type": "integer"},
                    },
                    "required": ["one"],
                },
            ),
            ToolContract(name="gone"),
            ToolContract(name="b"),
        ]
    )

    assert c.system_prompt_section("assistant") == (
        "Available tools:\n- a(one: string, two?: integer)\n- gone()"
    )
    assert [t["function"]["name"] for t in c.openai_tools("assistant")] == ["a", "gone"]


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


def test_drift_is_reported_in_words_a_reader_can_act_on():
    """The two checks that had no caller. A check that runs nowhere catches
    nothing, so discovery logs these and `alena-improve tools` prints them."""
    from modules.gateway.catalog import report_drift
    from modules.gateway.contracts import SideEffect

    c = catalog()
    c.register(
        [
            ToolContract(name="surprise", source="mcp"),
            ToolContract(
                name="a", side_effect_hint=SideEffect.DESTRUCTIVE, source="mcp"
            ),
        ]
    )

    lines = report_drift(c)
    assert any("surprise" in line and "not declared" in line for line in lines)
    assert any("read_only" in line and "destructive" in line for line in lines)


def test_a_catalog_that_agrees_with_its_policy_reports_nothing():
    from modules.gateway.catalog import report_drift

    c = catalog()
    c.register([ToolContract(name="a", source="mcp")])

    assert report_drift(c) == []


# --- discovery of ALENA's own servers --------------------------------------


@pytest.mark.asyncio
async def test_every_tool_is_discovered_and_all_declared(tmp_path, monkeypatch):
    """MCP-first: the contract comes from the server, the policy from the file.

    Fails if a tool ships without a policy entry, or a policy entry outlives
    its tool. All three servers are discovered, so this now covers the whole
    catalog rather than just alena-core.
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

    assert discovered, "no server advertised any tools"
    assert catalog.discovered, "a successful discovery must not run again"
    assert catalog.undeclared() == []
    assert catalog.unimplemented() == []
    assert all(catalog.get(name).contract.source == "mcp" for name in discovered)


@pytest.mark.asyncio
async def test_the_static_shim_describes_the_same_tools_the_servers_do(
    tmp_path, monkeypatch
):
    """The shim's remaining job is to be a fallback, so it must not drift.

    `tool_definitions.py` is only reached when a server will not start. A name
    in one and not the other means the fallback would offer the planner a tool
    that does not exist, or withhold one that does -- and it is the deletion of
    that file that this test is really guarding the way to.
    """
    monkeypatch.setenv("ALENA_DB_PATH", str(tmp_path / "state.db"))
    from modules.gateway.catalog import discover_into
    from modules.gateway.policy import load_policy
    from modules.gateway.pool import MCPSessionPool

    static_only = ToolCatalog(load_policy())
    static_only.register(static_contracts())

    discovered_only = ToolCatalog(load_policy())
    pool = MCPSessionPool()
    try:
        await discover_into(discovered_only, pool)
    finally:
        await pool.aclose()

    # alena-core has no static counterpart -- it was born discovered.
    from_servers = {
        name
        for name in discovered_only.names()
        if discovered_only.get(name).contract.mcp_server != "alena-core"
    }
    assert from_servers == set(static_only.names())


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
    # Unmarked, so the next turn tries again: one unlucky start should not cost
    # the planner half its tools for the life of the process.
    assert not catalog.discovered


def test_an_underscored_name_resolves_to_the_tool_that_was_meant():
    """Local models rewrite `repo.search` as `repo_search`. The catalog knows
    which one that is; making the model spend a turn finding out is waste."""
    c = catalog()
    c.register([ToolContract(name="a")])
    c._contracts["repo.search"] = ToolContract(name="repo.search")

    assert c.canonical("repo_search") == "repo.search"
    assert c.canonical("repo.search") == "repo.search"


def test_a_name_that_matches_nothing_is_left_alone():
    """Canonicalising is a convenience, not a search. An unknown name stays
    unknown so the gateway refuses it by that name and says so."""
    assert catalog().canonical("not_a_tool") == "not_a_tool"
