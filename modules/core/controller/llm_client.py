import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from modules.core.controller.logger import logger
from modules.llm import LLMChatClient, LLMConfig, LLMUnavailable
from modules.core.controller.tool_definitions import (
    generate_openai_tools,
    generate_system_prompt_tools_section,
)
from modules.gateway import get_gateway


def planner_tools(agent: str = "assistant") -> Tuple[List[Dict[str, Any]], str]:
    """What `agent` may call, as (tools array, prompt section).

    The catalog is the source of both. It holds every tool discovery has found
    as well as the legacy static ones, filtered by the same policy that will
    judge the call — so the planner is never shown a tool it would be refused
    for asking about, and never hidden one it may have.

    The static definitions survive as a fallback for a catalog that cannot be
    built at all. A broken policy file should degrade the assistant to the
    tools it had before the gateway existed, not silence it.
    """
    try:
        catalog = get_gateway().catalog
        tools = catalog.openai_tools(agent)
        if tools:
            return tools, catalog.system_prompt_section(agent)
        logger.warning(
            "Tool catalog offers %r nothing; falling back to the static tools", agent
        )
    except Exception as exc:  # noqa: BLE001 - the planner must still answer
        logger.warning(
            "Tool catalog unavailable (%r); falling back to the static tools", exc
        )
    return generate_openai_tools(), generate_system_prompt_tools_section()


def build_system_prompt(tools_section: Optional[str] = None) -> str:
    """The planner prompt, built fresh so the clock is not frozen at import.

    The controller stays up for days; a datetime captured at import time would
    have the agent confidently reporting the day it was started.
    """
    if tools_section is None:
        tools_section = planner_tools()[1]
    return f"""You are ALENA, an AI planner.

Current Date and Time: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

Rules:
- You do NOT execute code.
- You do NOT modify files directly.
- You may request tools.

{tools_section}

Tool usage rules:
- If the user explicitly asks to use a tool (e.g. "use codex", "using only codex tool"),
  you MUST call that tool.
- If you cannot confidently answer without code generation or editing, call a tool.
- If the user asks for the current working directory, current path, or repo location,
  call codex_analyze with repo_path "." and restate the question as the tool input.
- If the user asks to create, write, save, or add a file, call codex_edit.
- If you can answer fully in text, answer directly.

Call tools through the tool-calling interface. Do NOT return empty responses.
"""


LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:1234")
# Blank means "whatever LM Studio has loaded", which is the usual setup: the
# model is chosen in the LM Studio UI rather than pinned here.
LLM_MODEL = os.getenv("LLM_MODEL", "")
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "120"))
LLM_DEBUG = os.getenv("LLM_DEBUG", "0") == "1"


def _config() -> LLMConfig:
    return LLMConfig(
        base_url=LLM_BASE_URL,
        model=LLM_MODEL,
        timeout_s=LLM_TIMEOUT,
        debug=LLM_DEBUG,
    )


# One client for the process: it caches which model LM Studio has loaded, so a
# fresh instance per turn would re-fetch /v1/models on every single message.
_client = LLMChatClient(_config())


def ask_llm(messages: List[Dict[str, Any]], *, agent: str = "assistant") -> str:
    """Ask the planner. Returns prose, or tool-call JSON for the agent loop.

    Tool calls now go through the server's native tool-calling interface, so
    the reply is a `{"tool": ..., "arguments": {...}}` string only because
    LLMChatClient renders them that way — the model is no longer asked to
    hand-write JSON into its answer.

    `agent` is the identity the policy filters by, and it has to be the same
    one the call is later made under. Offering the planner a tool the gateway
    then refuses is worse than not offering it: the model spends a turn on it
    and reads the refusal as a failure to retry.
    """
    tools, tools_section = planner_tools(agent)
    try:
        response = _client.chat(
            messages,
            system_prompt=build_system_prompt(tools_section),
            tools=tools,
        )
    except LLMUnavailable as exc:
        logger.error("LLM unavailable: %s", exc)
        raise

    if LLM_DEBUG:
        logger.info("LLM_RAW_RESPONSE: %s", response)
    return response
