"""Tool effectiveness, computed from the audit log.

Most of these are about not giving confident bad advice: a young log looks
exactly like a catalog full of dead tools.
"""

from datetime import datetime, timedelta, timezone

import pytest

from modules.gateway.catalog import ToolCatalog
from modules.gateway.contracts import ToolContract
from modules.gateway.metrics import (
    CONTESTED,
    FAILING,
    HEALTHY,
    UNPROVEN,
    UNUSED,
    audit_basis,
    needing_attention,
    tool_metrics,
)
from modules.gateway.policy import parse_policy

START = datetime.now(timezone.utc) - timedelta(days=30)


@pytest.fixture
def log(memory_audit):
    """Write invocations directly, with control over their timestamps."""

    def write(tool, outcome, day=0, seconds=0, agent="assistant",
              repository_id="luma-index", duration_ms=100, arguments_hash="h"):
        memory_audit.conn.execute(
            "INSERT INTO tool_invocations (created_at, tool, agent,"
            " repository_id, arguments_hash, outcome, duration_ms)"
            " VALUES (?,?,?,?,?,?,?)",
            (
                (START + timedelta(days=day, seconds=seconds)).isoformat(),
                tool, agent, repository_id, arguments_hash, outcome, duration_ms,
            ),
        )
        memory_audit.conn.commit()

    write.conn = memory_audit.conn
    return write


def catalog(*names):
    policy = parse_policy(
        {
            "version": 1,
            "tools": {n: {"side_effect": "read_only", "allowed_agents": ["*"]} for n in names},
        }
    )
    built = ToolCatalog(policy)
    built.register([ToolContract(name=n) for n in names])
    return built


def busy(log, tool="filler"):
    """Enough history, spread over enough days, to judge an absence."""
    for day in range(0, 25):
        log(tool, "success", day=day)


# -- not concluding things from a young log --------------------------------


def test_an_empty_log_judges_nothing(log):
    metrics = tool_metrics(catalog("codex_analyze"), log.conn)

    assert metrics[0].health == UNPROVEN
    assert metrics[0].advice() is None


def test_a_busy_afternoon_is_not_evidence_a_tool_is_dead(log):
    """Enough calls, but all on one day."""
    for index in range(30):
        log("codex_edit", "success", day=0, seconds=index)

    metrics = {m.tool: m for m in tool_metrics(catalog("codex_edit", "codex_plan"), log.conn)}

    assert metrics["codex_plan"].health == UNPROVEN


def test_a_long_but_quiet_log_is_not_evidence_either(log):
    """Enough days, but barely any calls."""
    log("codex_edit", "success", day=0)
    log("codex_edit", "success", day=20)

    metrics = {m.tool: m for m in tool_metrics(catalog("codex_edit", "codex_plan"), log.conn)}

    assert metrics["codex_plan"].health == UNPROVEN


def test_enough_history_makes_an_absence_meaningful(log):
    busy(log)

    metrics = {m.tool: m for m in tool_metrics(catalog("filler", "codex_plan"), log.conn)}

    assert metrics["codex_plan"].health == UNUSED
    assert "Retire it" in metrics["codex_plan"].advice()


def test_the_basis_reports_what_it_is_working_from(log):
    busy(log)

    basis = audit_basis(log.conn)
    assert basis["invocations"] == 25
    assert basis["days"] >= 7
    assert basis["judgeable"]


# -- the signals -----------------------------------------------------------


def test_a_tool_that_mostly_works_is_healthy(log):
    busy(log, "codex_analyze")

    metrics = {m.tool: m for m in tool_metrics(catalog("codex_analyze"), log.conn)}
    assert metrics["codex_analyze"].health == HEALTHY
    assert metrics["codex_analyze"].reliability == 1.0


def test_a_tool_that_keeps_failing_is_flagged_for_repair(log):
    busy(log)
    for day in range(0, 8):
        log("codex_edit", "error" if day < 6 else "success", day=day)

    metrics = {m.tool: m for m in tool_metrics(catalog("filler", "codex_edit"), log.conn)}

    assert metrics["codex_edit"].health == FAILING
    assert "flag it for repair" in metrics["codex_edit"].advice().lower()


def test_repeated_refusals_are_the_tool_proposal_signal(log):
    """An agent reaching for something the policy will not give it means the
    catalog is missing a capability, or the policy is wrong about who has it."""
    busy(log)
    for day in range(0, 12):
        log("git.push", "denied", day=day, agent="action-agent")

    metrics = {m.tool: m for m in tool_metrics(catalog("filler"), log.conn)}

    assert metrics["git.push"].health == CONTESTED
    assert metrics["git.push"].refusal_rate == 1.0
    assert "catalog does not offer" in metrics["git.push"].advice()


def test_a_refused_call_is_not_counted_as_a_failure(log):
    """Refusing is the gateway working, not the tool breaking."""
    log("codex_edit", "denied")

    metrics = {m.tool: m for m in tool_metrics(catalog("codex_edit"), log.conn)}
    assert metrics["codex_edit"].failures == 0
    assert metrics["codex_edit"].reliability is None


# -- retries ---------------------------------------------------------------


def test_the_same_call_repeated_quickly_is_a_retry(log):
    """The agent did not want two answers; the first one did not work."""
    log("codex_analyze", "error", day=1, arguments_hash="same")
    log("codex_analyze", "success", day=1, seconds=60, arguments_hash="same")

    metrics = {m.tool: m for m in tool_metrics(catalog("codex_analyze"), log.conn)}
    assert metrics["codex_analyze"].retries == 1


def test_the_same_call_days_apart_is_not_a_retry(log):
    log("codex_analyze", "success", day=1, arguments_hash="same")
    log("codex_analyze", "success", day=5, arguments_hash="same")

    metrics = {m.tool: m for m in tool_metrics(catalog("codex_analyze"), log.conn)}
    assert metrics["codex_analyze"].retries == 0


def test_different_arguments_are_not_a_retry(log):
    log("codex_analyze", "success", day=1, arguments_hash="a")
    log("codex_analyze", "success", day=1, seconds=10, arguments_hash="b")

    metrics = {m.tool: m for m in tool_metrics(catalog("codex_analyze"), log.conn)}
    assert metrics["codex_analyze"].retries == 0


# -- the score -------------------------------------------------------------


def test_an_unused_tool_scores_zero(log):
    assert tool_metrics(catalog("codex_plan"), log.conn)[0].utility == 0.0


def test_reach_across_repositories_counts(log):
    for day, repo in enumerate(["a", "b", "c", "a", "b"]):
        log("wide", "success", day=day, repository_id=repo)
    for day in range(5):
        log("narrow", "success", day=day, repository_id="a")

    metrics = {m.tool: m for m in tool_metrics(None, log.conn)}
    assert metrics["wide"].utility > metrics["narrow"].utility
    assert metrics["wide"].repositories == 3


def test_failures_lower_the_score(log):
    for day in range(10):
        log("solid", "success", day=day)
    for day in range(10):
        log("shaky", "success" if day % 2 else "error", day=day)

    metrics = {m.tool: m for m in tool_metrics(None, log.conn)}
    assert metrics["solid"].utility > metrics["shaky"].utility


def test_timings_are_summarised(log):
    for day, ms in enumerate([100, 200, 900]):
        log("codex_analyze", "success", day=day, duration_ms=ms)

    metrics = {m.tool: m for m in tool_metrics(None, log.conn)}
    assert metrics["codex_analyze"].median_ms == 200
    assert metrics["codex_analyze"].slowest_ms == 900


# -- the attention list ----------------------------------------------------


def test_attention_lists_only_what_needs_looking_at(log):
    busy(log)
    for day in range(0, 12):
        log("git.push", "denied", day=day)

    attention = {m.tool for m in needing_attention(tool_metrics(catalog("filler"), log.conn))}

    assert "git.push" in attention
    assert "filler" not in attention


def test_a_tool_the_catalog_does_not_know_is_marked_undeclared(log):
    log("mystery.tool", "success")

    metrics = {m.tool: m for m in tool_metrics(catalog("codex_analyze"), log.conn)}
    assert not metrics["mystery.tool"].declared
