import pytest
import json

@pytest.mark.asyncio
async def test_agent_exits_on_plain_text(monkeypatch):
    from modules.core.controller.agent import run_agent

    def fake_ollama(_):
        return "Just explaining, no tool needed."

    monkeypatch.setattr(
        "modules.core.controller.agent.ask_ollama",
        fake_ollama
    )

    await run_agent("Explain hello world")
