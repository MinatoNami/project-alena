import json
import os

from typing import Callable, Optional, Set
from types import SimpleNamespace

from modules.core.controller.ollama_client import ask_ollama
from modules.core.controller.normalize import normalize_codex_output
from modules.core.controller.tool_executor import execute_tool
from modules.core.tools.tool_capabilities import tool_can_handle
from modules.core.controller.normalize import normalize_codex_output
from modules.core.controller.logger import logger

SERVER = SimpleNamespace(
    command="python",
    args=["-m", "app.main"],

    # Process settings
    cwd=os.path.join(os.path.dirname(__file__), "..", "..", "mcp", "codex-server"),
    env=None,

    # Text decoding settings expected by mcp.client.stdio
    encoding="utf-8",
    encoding_error_handler="replace",  # ✅ required

    # Optional but safe (prevents future attr errors across versions)
    stderr_to_stdout=False,
)

def infer_intents(user_input: str) -> Set[str]:
    text = user_input.lower()
    intents = set()

    if any(k in text for k in ["time", "date", "now", "current"]):
        intents.add("access_time")

    if any(k in text for k in ["fetch", "download", "http", "api"]):
        intents.add("access_network")

    if any(k in text for k in ["write code", "generate", "program"]):
        intents.add("generate_code")

    if any(k in text for k in ["edit", "modify", "change file"]):
        intents.add("edit_files")

    return intents


async def run_agent(user_input: str):
    text = user_input.lower()
    explicit_codex_request = "codex" in text and ("use" in text or "using" in text or "tool" in text)

    # 1️⃣ Ask Ollama
    ollama_response = ask_ollama([
        {"role": "user", "content": user_input}
    ])

    logger.info(f"OLLAMA_RESPONSE: {ollama_response}")

    if not ollama_response.strip():
        logger.warning("OLLAMA returned empty response")
        if "codex" in text:
            tool = "codex_generate"
            arguments = {"prompt": user_input}
            logger.info(f"TOOL_REQUEST (fallback): tool={tool} arguments={arguments}")

            intents = infer_intents(user_input)
            if not explicit_codex_request and not tool_can_handle(tool, intents):
                logger.warning(
                    f"Tool '{tool}' cannot satisfy intents {intents}"
                )
                print(
                    "❌ I cannot complete this request with the available tools.\n"
                    "Reason: required capability is missing."
                )
                return

            result = await execute_tool(SERVER, tool, arguments)
            normalized = normalize_codex_output(result.content)
            print("\n✅ Final answer:\n", normalized["message"])
            return

        print("❌ Ollama returned an empty response.")
        return

    # 2️⃣ If Ollama answered normally → exit early
    try:
        parsed = json.loads(ollama_response)
    except json.JSONDecodeError:
        print("✅ Final answer:\n", ollama_response)
        return

    # 3️⃣ Tool request detected
    tool = parsed.get("tool")
    arguments = parsed.get("arguments", {})

    logger.info(f"TOOL_REQUEST: tool={tool} arguments={arguments}")

    # 🔴 INSERT CAPABILITY CHECK HERE 🔴
    intents = infer_intents(user_input)

    if not explicit_codex_request and not tool_can_handle(tool, intents):
        logger.warning(
            f"Tool '{tool}' cannot satisfy intents {intents}"
        )
        print(
            "❌ I cannot complete this request with the available tools.\n"
            "Reason: required capability is missing."
        )
        return

    # 4️⃣ Execute tool ONLY if allowed
    result = await execute_tool(SERVER, tool, arguments)

    # 5️⃣ Normalize + output
    normalized = normalize_codex_output(result.content)
    print("\n✅ Final answer:\n", normalized["message"])
