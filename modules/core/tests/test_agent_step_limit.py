"""The tool budget limits tool calls, not the turn.

Reaching `ALENA_MAX_TOOL_STEPS` used to end the turn with an error, throwing
away the result of the call that tripped the limit. The user asked a question,
ALENA did the work, and then answered "reached tool step limit".
"""

import json

import pytest

from modules.core.controller import agent


class FakeResult:
    content = "the tool said something useful"


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("ALENA_DB_PATH", str(tmp_path / "test.db"))
    from modules.store import db

    db.reset_connection()
    yield
    db.reset_connection()


@pytest.fixture
def one_step(monkeypatch):
    """A planner that only ever asks for tools, on a one-call budget."""
    monkeypatch.setenv("ALENA_MAX_TOOL_STEPS", "1")

    asked = []

    def fake_ask(messages, *, agent="assistant", with_tools=True):
        asked.append(with_tools)
        if not with_tools:
            return "Here is what I found, though I could not check everything."
        return json.dumps(
            {"tool": "codex_generate", "arguments": {"prompt": "anything"}}
        )

    monkeypatch.setattr(agent, "ask_llm", fake_ask)
    monkeypatch.setattr(
        agent, "normalize_codex_output", lambda _: {"message": "tool output"}
    )
    return asked


async def fake_executor(server, tool, arguments):
    return FakeResult()


@pytest.mark.asyncio
async def test_the_last_step_is_spent_on_an_answer(one_step):
    answer = await agent.run_agent(
        "do the thing", tool_executor=fake_executor, return_output=True
    )

    assert answer == "Here is what I found, though I could not check everything."
    # Tools offered on the planning call, withheld on the one that has no
    # budget left to use them.
    assert one_step == [True, False]


@pytest.mark.asyncio
async def test_a_model_with_nothing_to_say_still_reports_the_limit(
    one_step, monkeypatch
):
    """The old message is the fallback, not the outcome."""
    monkeypatch.setattr(
        agent, "ask_llm", lambda messages, **kwargs: "" if not kwargs.get(
            "with_tools", True
        ) else json.dumps({"tool": "codex_generate", "arguments": {"prompt": "x"}})
    )

    said = []
    answer = await agent.run_agent(
        "do the thing",
        tool_executor=fake_executor,
        output_sink=said.append,
        return_output=True,
    )

    assert answer is None
    assert any("Reached tool step limit" in line for line in said)
