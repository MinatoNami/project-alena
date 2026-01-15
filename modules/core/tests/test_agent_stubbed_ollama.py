import pytest
import json

@pytest.mark.asyncio
async def test_agent_parses_json_tool_call(monkeypatch):
    from modules.core.controller.agent import run_agent
    import json

    fake_response = json.dumps({
        "tool": "codex_generate",
        "arguments": {
            "prompt": "Write hello world"
        }
    })

    monkeypatch.setattr(
        "modules.core.controller.agent.ask_ollama",
        lambda _: fake_response
    )

    monkeypatch.setattr(
        "modules.core.controller.agent.normalize_codex_output",
        lambda _: {"message": "Hello world", "reasoning": None}
    )

    # ✅ FAKE EXECUTOR (this is the key change)
    async def fake_tool_executor(server, tool, arguments):
        class FakeResult:
            content = []
        return FakeResult()

    await run_agent(
        "Write hello world",
        tool_executor=fake_tool_executor
    )
