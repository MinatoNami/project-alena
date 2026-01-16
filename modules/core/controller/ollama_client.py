import os
import time
import json
import requests

from modules.core.controller.logger import logger

SYSTEM_PROMPT = """You are ALENA, an AI planner.

Rules:
- You do NOT execute code.
- You do NOT modify files directly.
- You may request tools.

Available tools:
- codex_generate(prompt: string)
- codex_plan(repo_path: string, goal: string)
- codex_analyze(repo_path: string, question: string)
- codex_summarize(repo_path: string, focus?: string)
- codex_doc_outline(repo_path: string, topic: string, audience?: string)
- codex_test_plan(repo_path: string, goal: string)
- codex_edit(repo_path: string, instruction: string)
- codex_refactor(repo_path: string, goal: string, constraints?: string)

Tool usage rules:
- If the user explicitly asks to use a tool (e.g. "use codex", "using only codex tool"),
  you MUST respond with a tool call.
- If you cannot confidently answer without code generation or editing, use a tool.
- If the user asks for the current working directory, current path, or repo location,
  use codex_analyze with repo_path "." and restate the question as the tool input.
- If the user asks to create, write, save, or add a file, use codex_edit.
- If you can answer fully in text, answer directly.

When calling a tool, respond ONLY in valid JSON:

{
  "tool": "<tool_name>",
  "arguments": { ... }
}

Do NOT return empty responses.
"""


OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://192.168.0.10:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gpt-oss:20b")
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "120"))
OLLAMA_DEBUG = os.getenv("OLLAMA_DEBUG", "0") == "1"


def ask_ollama(messages):
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            *messages,
        ],
        "stream": False,
    }

    for attempt in range(2):
        response = requests.post(
            f"{OLLAMA_HOST}/api/chat",
            json=payload,
            timeout=OLLAMA_TIMEOUT,
        )

        response.raise_for_status()
        data = response.json()
        if OLLAMA_DEBUG:
            logger.info("OLLAMA_RAW_RESPONSE: %s", data)
        message = data.get("message", {}) if isinstance(data, dict) else {}
        content = message.get("content") or ""
        if content.strip():
            return content

        tool_calls = message.get("tool_calls")
        if isinstance(tool_calls, list) and tool_calls:
            first = tool_calls[0] or {}
            function = first.get("function") or {}
            name = function.get("name")
            arguments = function.get("arguments", {})
            if name:
                tool_payload = {
                    "tool": name,
                    "arguments": arguments,
                }
                return json.dumps(tool_payload)

        logger.warning("OLLAMA_EMPTY_RESPONSE: %s", data)
        fallback = data.get("response")
        if isinstance(fallback, str) and fallback.strip():
            return fallback

        if attempt == 0:
            time.sleep(0.5)

    return ""
