import pytest

from modules.gateway.contracts import SideEffect
from modules.gateway.policy import (
    REASON_AGENT_NOT_PERMITTED,
    REASON_DENIED_FOR_REPOSITORY,
    REASON_NOT_ALLOWLISTED_FOR_REPOSITORY,
    REASON_REPOSITORY_NOT_PERMITTED,
    REASON_REPOSITORY_REQUIRED,
    REASON_TOOL_NOT_DECLARED,
    PolicyError,
    parse_policy,
)


def policy(**overrides):
    data = {
        "version": 1,
        "defaults": {"allowed_agents": ["assistant"]},
        "tools": {"t": {"side_effect": "read_only"}},
    }
    data.update(overrides)
    return parse_policy(data)


def test_undeclared_tool_is_denied():
    decision = policy().evaluate("not_declared", "assistant")
    assert not decision
    assert decision.reason_code == REASON_TOOL_NOT_DECLARED


def test_empty_policy_denies_everything():
    """The gateway fails closed: no policy means no tools, not all tools."""
    assert not parse_policy(None).evaluate("anything", "assistant")


def test_declared_tool_is_allowed_for_its_agent():
    assert policy().evaluate("t", "assistant").allowed


def test_agent_outside_the_list_is_denied():
    decision = policy().evaluate("t", "action-agent")
    assert decision.reason_code == REASON_AGENT_NOT_PERMITTED


def test_defaults_supply_allowed_agents():
    """A tool that names no agents inherits the defaults block."""
    assert policy().tools["t"].allowed_agents == ["assistant"]


def test_per_tool_agents_override_defaults():
    p = policy(
        tools={"t": {"side_effect": "read_only", "allowed_agents": ["codex"]}}
    )
    assert p.evaluate("t", "codex").allowed
    assert not p.evaluate("t", "assistant").allowed


def test_wildcard_agent_permits_anyone():
    p = policy(tools={"t": {"side_effect": "read_only", "allowed_agents": ["*"]}})
    assert p.evaluate("t", "whoever").allowed


def test_side_effect_is_required():
    with pytest.raises(PolicyError, match="side_effect"):
        parse_policy({"version": 1, "tools": {"t": {"allowed_agents": ["a"]}}})


def test_unknown_side_effect_is_rejected():
    with pytest.raises(ValueError, match="Unknown side effect"):
        parse_policy({"version": 1, "tools": {"t": {"side_effect": "mostly_fine"}}})


def test_unsupported_version_is_rejected():
    with pytest.raises(PolicyError, match="version"):
        parse_policy({"version": 99, "tools": {}})


def test_side_effect_is_parsed_onto_the_tool():
    p = policy(tools={"t": {"side_effect": "destructive"}})
    assert p.tools["t"].side_effect is SideEffect.DESTRUCTIVE


def test_tool_scoped_to_named_repositories():
    p = policy(
        tools={"t": {"side_effect": "read_only", "repositories": ["luma-index"]}}
    )
    assert p.evaluate("t", "assistant", "luma-index").allowed
    assert p.evaluate("t", "assistant", "athena").reason_code == (
        REASON_REPOSITORY_NOT_PERMITTED
    )


def test_scoped_tool_called_without_a_repository_says_so():
    """A missing repository is a missing argument, not a policy violation."""
    p = policy(
        tools={"t": {"side_effect": "read_only", "repositories": ["luma-index"]}}
    )
    assert p.evaluate("t", "assistant", None).reason_code == REASON_REPOSITORY_REQUIRED


def test_repository_deny_beats_allow():
    p = policy(
        tools={"git.push": {"side_effect": "remote_write"}},
        repositories={
            "control-plane": {"allow": ["git.*"], "deny": ["git.push"]},
        },
    )
    decision = p.evaluate("git.push", "assistant", "control-plane")
    assert decision.reason_code == REASON_DENIED_FOR_REPOSITORY


def test_repository_allowlist_excludes_unmatched_tools():
    p = policy(
        tools={"infra.apply": {"side_effect": "infrastructure_change"}},
        repositories={"control-plane": {"allow": ["repo.*"]}},
    )
    decision = p.evaluate("infra.apply", "assistant", "control-plane")
    assert decision.reason_code == REASON_NOT_ALLOWLISTED_FOR_REPOSITORY


def test_repository_with_no_entry_inherits_the_tool_policy():
    p = policy(repositories={"other": {"deny": ["t"]}})
    assert p.evaluate("t", "assistant", "unlisted").allowed


def test_wildcard_repository_policy_allows_everything():
    p = policy(repositories={"sandbox": {"allow": ["*"]}})
    assert p.evaluate("t", "assistant", "sandbox").allowed


def test_requires_approval_is_carried_on_the_decision():
    p = policy(
        tools={"t": {"side_effect": "repository_write", "requires_approval": True}}
    )
    assert p.evaluate("t", "assistant").requires_approval
