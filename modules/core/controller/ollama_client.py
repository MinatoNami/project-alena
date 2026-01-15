import os
import requests

SYSTEM_PROMPT = """You are ALENA, an AI planner.

Rules:
- You do NOT execute code.
- You do NOT modify files directly.
- You may request tools.

Available tools:
- codex_generate(prompt: string)
- codex_edit(repo_path: string, instruction: string)

Tool usage rules:
- If the user explicitly asks to use a tool (e.g. "use codex", "using only codex tool"),
  you MUST respond with a tool call.
- If you cannot confidently answer without code generation or editing, use a tool.
- If you can answer fully in text, answer directly.

When calling a tool, respond ONLY in valid JSON:

{
  "tool": "<tool_name>",
  "arguments": { ... }
}

Do NOT return empty responses.
"""




OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://10.8.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gpt-oss:20b")


def ask_ollama(messages):
    response = requests.post(
        f"{OLLAMA_HOST}/api/chat",
        json={
            "model": OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                *messages,
            ],
            "stream": False,
        },
        timeout=120,
    )

    response.raise_for_status()
    data = response.json()
    content = data.get("message", {}).get("content") or ""
    if not content.strip():
        fallback = data.get("response")
        if isinstance(fallback, str) and fallback.strip():
            return fallback
    return content
