import json
import os

from typing import Callable, Optional, Set
from types import SimpleNamespace

from modules.core.controller.ollama_client import ask_ollama
from modules.core.controller.normalize import normalize_codex_output
from modules.core.controller.tool_executor import execute_tool
from modules.core.controller.tool_definitions import get_tool_by_name
from modules.core.tools.tool_capabilities import tool_can_handle
from modules.core.controller.normalize import normalize_codex_output
from modules.core.controller.logger import logger
from modules.core.controller.memory import get_default_memory, ConversationMemory


def _build_server_config(mcp_server_key: str) -> SimpleNamespace:
    base_dir = os.path.join(os.path.dirname(__file__), "..", "..", "mcp")
    # Map logical server key to folder name
    if mcp_server_key == "codex":
        folder = "codex-server"
    else:
        folder = mcp_server_key

    return SimpleNamespace(
        command="python",
        args=["-m", "app.main"],
        cwd=os.path.abspath(os.path.join(base_dir, folder)),
        env=None,
        encoding="utf-8",
        encoding_error_handler="replace",
        stderr_to_stdout=False,
    )


def _get_server_for_tool(tool_name: str) -> SimpleNamespace:
    tool_def = get_tool_by_name(tool_name)
    # Default to codex if unknown (keeps backward-compatibility)
    server_key = tool_def.mcp_server if tool_def else "codex"
    return _build_server_config(server_key)


def infer_intents(user_input: str) -> Set[str]:
    text = user_input.lower()
    intents = set()

    if any(k in text for k in ["time", "date", "now", "current time", "current date"]):
        intents.add("access_time")

    if any(k in text for k in ["fetch", "download", "http", "api"]):
        intents.add("access_network")

    if any(k in text for k in ["write code", "generate", "program"]):
        intents.add("generate_code")

    if any(
        k in text
        for k in [
            "edit",
            "modify",
            "change file",
            "create file",
            "write file",
            "save file",
            "add file",
        ]
    ):
        intents.add("edit_files")

    if any(
        k in text
        for k in [
            "current working directory",
            "working directory",
            "current directory",
            "cwd",
            "show path",
            "current path",
            "pwd",
        ]
    ):
        intents.add("access_filesystem")

    return intents


_memory = get_default_memory()


async def run_agent(
    user_input: str,
    memory: Optional[ConversationMemory] = None,
    tool_executor: Optional[Callable] = None,
    *,
    output_sink: Optional[Callable[[str], None]] = None,
    return_output: bool = False,
):
    memory = memory or _memory
    tool_executor = tool_executor or execute_tool
    text = user_input.lower()
    explicit_codex_request = "codex" in text and (
        "use" in text or "using" in text or "tool" in text
    )

    final_message: Optional[str] = None
    outputs: list[str] = []

    def emit(message: str) -> None:
        nonlocal outputs
        if output_sink is not None:
            output_sink(message)
        else:
            print(message)
        outputs.append(message)

    def done() -> Optional[str]:
        return final_message if return_output else None

    # 1️⃣ Ask Ollama
    history = memory.get_messages()
    ollama_response = ask_ollama(
        [
            *history,
            {"role": "user", "content": user_input},
        ]
    )
    memory.add_user(user_input)

    logger.info(f"OLLAMA_RESPONSE: {ollama_response}")

    if not ollama_response.strip():
        logger.warning("OLLAMA returned empty response")
        if "codex" in text:
            tool = "codex_generate"
            arguments = {"prompt": user_input}
            logger.info(f"TOOL_REQUEST (fallback): tool={tool} arguments={arguments}")

            intents = infer_intents(user_input)
            if not explicit_codex_request and not tool_can_handle(tool, intents):
                logger.warning(f"Tool '{tool}' cannot satisfy intents {intents}")
                emit(
                    "❌ I cannot complete this request with the available tools.\n"
                    "Reason: required capability is missing."
                )
                return done()

            result = await tool_executor(_get_server_for_tool(tool), tool, arguments)
            normalized = normalize_codex_output(result.content)
            final_message = normalized["message"]
            emit("\n✅ Final answer:\n" + final_message)
            return done()

        emit(
            "❌ Ollama returned an empty response. "
            "Check OLLAMA_BASE_URL/OLLAMA_MODEL/OLLAMA_TIMEOUT or enable OLLAMA_DEBUG=1."
        )
        return done()

    # 2️⃣ Tool loop: allow multiple tool calls
    max_tool_steps = int(os.getenv("ALENA_MAX_TOOL_STEPS", "3"))
    tool_steps = 0
    current_response = ollama_response

    while True:
        try:
            parsed = json.loads(current_response)
        except json.JSONDecodeError:
            intents = infer_intents(user_input)
            if "access_filesystem" in intents:
                tool = "codex_analyze"
                arguments = {"repo_path": ".", "question": user_input}
                if not explicit_codex_request and not tool_can_handle(tool, intents):
                    logger.warning(f"Tool '{tool}' cannot satisfy intents {intents}")
                    emit(
                        "❌ I cannot complete this request with the available tools.\n"
                        "Reason: required capability is missing."
                    )
                    return done()
                result = await tool_executor(
                    _get_server_for_tool(tool), tool, arguments
                )
                normalized = normalize_codex_output(result.content)
                final_message = normalized["message"]
                emit("\n✅ Final answer:\n" + final_message)
                return done()

            memory.add_assistant(current_response)
            final_message = current_response
            emit("✅ Final answer:\n" + final_message)
            return done()

        intents = infer_intents(user_input)
        if "access_filesystem" in intents and not explicit_codex_request:
            cwd = os.getcwd()
            tool = "codex_analyze"
            arguments = {
                "repo_path": cwd,
                "question": (f"Current working directory is: {cwd}. " f"{user_input}"),
            }
            memory.add_tool_call(tool, arguments)
            result = await tool_executor(_get_server_for_tool(tool), tool, arguments)
            normalized = normalize_codex_output(result.content)
            memory.add_tool_result(tool, normalized["message"])
            final_message = normalized["message"]
            emit("\n✅ Final answer:\n" + final_message)
            return done()

        # Tool request detected
        tool = parsed.get("tool")
        arguments = parsed.get("arguments", {})
        if (
            isinstance(arguments, dict)
            and "tool" in arguments
            and "arguments" in arguments
            and not parsed.get("_normalized")
        ):
            nested_tool = arguments.get("tool")
            nested_args = arguments.get("arguments", {})
            if nested_tool:
                tool = nested_tool
                arguments = nested_args

        if tool == "codex_generate" and isinstance(arguments, dict):
            prompt = arguments.get("prompt")
            if prompt and (
                "repo_path" in arguments
                or any(
                    k in str(prompt).lower()
                    for k in [
                        "create a file",
                        "create file",
                        "write a file",
                        "write file",
                        "save file",
                        "add a file",
                    ]
                )
            ):
                tool = "codex_edit"
                arguments = {
                    "repo_path": arguments.get("repo_path", "."),
                    "instruction": prompt,
                }

        # Normalize mis-scoped tool names like "codex_create_event" -> "create_event"
        if (
            not get_tool_by_name(tool)
            and isinstance(tool, str)
            and tool.startswith("codex_")
        ):
            candidate = tool[len("codex_") :]
            if get_tool_by_name(candidate):
                logger.info(f"Normalizing tool name '{tool}' -> '{candidate}'")
                tool = candidate

        logger.info(f"TOOL_REQUEST: tool={tool} arguments={arguments}")

        # Preprocess datetime arguments for Google Calendar tools
        if tool and tool.startswith("google_") and isinstance(arguments, dict):
            timezone_offset = os.getenv("CALENDAR_TIMEZONE_OFFSET", "+08:00")
            for key in ["start_time", "end_time"]:
                if key in arguments and isinstance(arguments[key], str):
                    # Strip 'Z' (UTC indicator) and add configured timezone offset
                    if arguments[key].endswith("Z"):
                        arguments[key] = arguments[key][:-1] + timezone_offset
                        logger.info(
                            f"Preprocessed {key}: replaced 'Z' with {timezone_offset}"
                        )

        if not explicit_codex_request and not tool_can_handle(tool, intents):
            logger.warning(f"Tool '{tool}' cannot satisfy intents {intents}")
            emit(
                "❌ I cannot complete this request with the available tools.\n"
                "Reason: required capability is missing."
            )
            return done()

        if tool == "codex_edit" and isinstance(arguments, dict):
            if "repo_path" not in arguments or not arguments.get("repo_path"):
                arguments["repo_path"] = os.getcwd()
            if "path" in arguments:
                path_value = arguments.pop("path")
                if path_value:
                    instruction = arguments.get("instruction", "")
                    if (
                        "file" not in instruction.lower()
                        or str(path_value) not in instruction
                    ):
                        arguments["instruction"] = (
                            f"{instruction}\n\nTarget path: {path_value}"
                        ).strip()

        tools_with_repo_path = {
            "codex_edit",
            "codex_refactor",
            "codex_plan",
            "codex_analyze",
            "codex_summarize",
            "codex_doc_outline",
            "codex_test_plan",
        }
        if isinstance(arguments, dict) and tool in tools_with_repo_path:
            repo_path = arguments.get("repo_path")
            if not repo_path:
                arguments["repo_path"] = os.getcwd()
            elif isinstance(repo_path, str) and repo_path:
                if not os.path.isabs(repo_path):
                    arguments["repo_path"] = os.path.abspath(
                        os.path.join(os.getcwd(), repo_path)
                    )

        memory.add_tool_call(tool, arguments)
        result = await tool_executor(_get_server_for_tool(tool), tool, arguments)

        # Don't normalize non-Codex tools - use their output directly
        if tool.startswith("codex_"):
            normalized = normalize_codex_output(result.content)
            tool_result = normalized["message"]
        else:
            tool_result = result.content

        memory.add_tool_result(tool, tool_result)

        tool_steps += 1
        if tool_steps >= max_tool_steps:
            emit("❌ Reached tool step limit. Please refine the request or try again.")
            return done()

        followup = (
            "Use the tool result above to continue. "
            "If another tool call is required, respond with a tool call JSON. "
            "Otherwise, provide the final answer."
        )
        current_response = ask_ollama(
            [
                *memory.get_messages(),
                {"role": "user", "content": followup},
            ]
        )

    return done()
