import pytest
import os

@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "1",
    reason="Integration tests disabled"
)
async def test_real_codex_call():
    from modules.core.controller.agent import run_agent
    await run_agent("Write a Rust hello world program")
