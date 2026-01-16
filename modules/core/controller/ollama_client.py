import os

from modules.core.controller.logger import logger
from modules.ollama import OllamaChatClient, OllamaConfig
from modules.core.controller.tool_definitions import (
    generate_system_prompt_tools_section,
)

SYSTEM_PROMPT = f"""You are ALENA, an AI planner.

Rules:
- You do NOT execute code.
- You do NOT modify files directly.
- You may request tools.

{generate_system_prompt_tools_section()}

Tool usage rules:
- If the user explicitly asks to use a tool (e.g. "use codex", "using only codex tool"),
  you MUST respond with a tool call.
- If you cannot confidently answer without code generation or editing, use a tool.
- If the user asks for the current working directory, current path, or repo location,
  use codex_analyze with repo_path "." and restate the question as the tool input.
- If the user asks to create, write, save, or add a file, use codex_edit.
- If you can answer fully in text, answer directly.

When calling a tool, respond ONLY in valid JSON:

{{
  "tool": "<tool_name>",
  "arguments": {{ ... }}
}}

Do NOT return empty responses.
"""


OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL") or os.getenv(
    "OLLAMA_HOST", "http://localhost:11434"
)
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gpt-oss:20b")
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "120"))
OLLAMA_DEBUG = os.getenv("OLLAMA_DEBUG", "0") == "1"


def ask_ollama(messages):
    config = OllamaConfig(
        base_url=OLLAMA_BASE_URL,
        model=OLLAMA_MODEL,
        timeout_s=OLLAMA_TIMEOUT,
        debug=OLLAMA_DEBUG,
    )
    client = OllamaChatClient(config)
    response = client.chat(messages, system_prompt=SYSTEM_PROMPT)
    if OLLAMA_DEBUG:
        logger.info("OLLAMA_RAW_RESPONSE: %s", response)
    return response
