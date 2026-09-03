"""Pool tests run a real MCP server subprocess.

Mocking `stdio_client` would test the mock. The thing worth proving here --
that two tool calls reach the *same* process -- only means something against a
real subprocess, so `fake_pid` reports its own pid and the test compares them.
"""

import asyncio

import pytest

from modules.gateway.pool import MCPSessionPool, server_key


def text_of(result):
    return result.content[0].text


@pytest.mark.asyncio
async def test_two_calls_share_one_server_process(fake_server):
    pool = MCPSessionPool()
    try:
        first = text_of(await pool.call_tool(fake_server, "fake_pid", {}))
        second = text_of(await pool.call_tool(fake_server, "fake_pid", {}))
    finally:
        await pool.aclose()

    assert first == second, "each call spawned its own server process"


@pytest.mark.asyncio
async def test_tool_results_come_back(fake_server):
    pool = MCPSessionPool()
    try:
        result = await pool.call_tool(fake_server, "fake_echo", {"text": "hi"})
    finally:
        await pool.aclose()

    assert text_of(result) == "echo:hi"


@pytest.mark.asyncio
async def test_a_failing_tool_does_not_kill_the_session(fake_server):
    """One bad call must not cost the process every later call."""
    pool = MCPSessionPool()
    try:
        before = text_of(await pool.call_tool(fake_server, "fake_pid", {}))

        result = await pool.call_tool(fake_server, "fake_boom", {})
        assert result.isError

        after = text_of(await pool.call_tool(fake_server, "fake_pid", {}))
    finally:
        await pool.aclose()

    assert before == after


@pytest.mark.asyncio
async def test_concurrent_calls_are_serialised_onto_one_session(fake_server):
    pool = MCPSessionPool()
    try:
        results = await asyncio.gather(
            *(pool.call_tool(fake_server, "fake_pid", {}) for _ in range(5))
        )
    finally:
        await pool.aclose()

    assert len({text_of(r) for r in results}) == 1


@pytest.mark.asyncio
async def test_closing_the_pool_stops_the_server(fake_server):
    pool = MCPSessionPool()
    await pool.call_tool(fake_server, "fake_pid", {})
    await pool.aclose()

    assert pool._workers == {}


def test_sessions_from_a_previous_event_loop_are_discarded(fake_server):
    """alena.py runs asyncio.run() per turn, so a stale loop is the norm."""
    pool = MCPSessionPool()

    async def one_turn():
        await pool.call_tool(fake_server, "fake_pid", {})
        return len(pool._workers)

    assert asyncio.run(one_turn()) == 1

    async def next_turn():
        # A different loop: the previous worker is unusable and must be dropped
        # rather than reused, or the call would hang on a dead transport.
        pool._check_loop()
        return len(pool._workers)

    assert asyncio.run(next_turn()) == 0


def test_server_key_distinguishes_servers():
    from types import SimpleNamespace

    a = SimpleNamespace(command="python", args=["-m", "app.main"], cwd="/a")
    b = SimpleNamespace(command="python", args=["-m", "app.main"], cwd="/b")

    assert server_key(a) != server_key(b)
    assert server_key(a) == server_key(
        SimpleNamespace(command="python", args=["-m", "app.main"], cwd="/a")
    )
