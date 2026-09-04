import json
import os
import sys

from typing import Callable, Optional, Set
from types import SimpleNamespace

from modules.core.controller.llm_client import ask_llm
from modules.core.controller.normalize import normalize_codex_output
from modules.core.controller.tool_executor import execute_tool
from modules.core.controller.tool_definitions import get_tool_by_name
from modules.core.tools.tool_capabilities import TOOL_CAPABILITIES, tool_can_handle
from modules.core.controller.normalize import normalize_codex_output
from modules.core.controller.logger import logger
from modules.core.controller.memory import get_default_memory, ConversationMemory
from modules.llm import LLMUnavailable
from modules.gateway import ensure_discovered, get_gateway
from modules.gateway.errors import GatewayDenied


def _build_server_config(mcp_server_key: str) -> SimpleNamespace:
    base_dir = os.path.join(os.path.dirname(__file__), "..", "..", "mcp")
    # Map logical server key to folder name
    if mcp_server_key == "codex":
        folder = "codex-server"
    else:
        folder = mcp_server_key

    return SimpleNamespace(
        # sys.executable, not "python": an MCP server needs the same
        # interpreter as its caller, because that is the one with `mcp`
        # installed. A bare "python" depends on PATH, which a launchd job does
        # not have -- and this failed for every scheduled review until a live
        # run with observations in the queue finally exercised it.
        command=sys.executable,
        args=["-m", "app.main"],
        cwd=os.path.abspath(os.path.join(base_dir, folder)),
        # Unbuffered, so the server's progress on stderr reaches whoever is
        # watching while the work happens rather than after it.
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
        encoding="utf-8",
        encoding_error_handler="replace",
        stderr_to_stdout=False,
    )


def _catalog_entry(tool_name: str):
    """The catalog's entry for a tool, or None if it has never heard of it."""
    try:
        return get_gateway().catalog.get(tool_name)
    except Exception as exc:  # noqa: BLE001 - a broken catalog is not fatal here
        logger.warning(f"Tool catalog unavailable for '{tool_name}': {exc!r}")
        return None


def _get_server_for_tool(tool_name: str) -> SimpleNamespace:
    """The MCP server that implements `tool_name`.

    The catalog answers first, because a discovered tool exists nowhere else.
    Sending `repo.search` to the codex server -- which is what the "default to
    codex" fallback below would do for anything the static table has not heard
    of -- turns a perfectly good tool call into a baffling failure.
    """
    entry = _catalog_entry(tool_name)
    if entry is not None and entry.contract.mcp_server:
        return _build_server_config(entry.contract.mcp_server)

    tool_def = get_tool_by_name(tool_name)
    # Default to codex if unknown (keeps backward-compatibility)
    server_key = tool_def.mcp_server if tool_def else "codex"
    return _build_server_config(server_key)


def _record_gate_refusal(tool_name: str, arguments: dict, intents: Set[str]) -> None:
    """Record the one refusal the audit trail never saw.

    Every gateway denial is recorded with a reason code, counted, and reported
    by `alena-improve tools`. This heuristic sits in front of the gateway and
    refused silently, so there has never been a way to ask the obvious
    question: does it prevent mistakes, or only cause them? Recorded as a
    denial with its own reason so that the existing metrics can answer it.
    """
    try:
        get_gateway().audit.record(
            tool=tool_name,
            agent="assistant",
            outcome="denied",
            arguments=arguments,
            denial_reason=f"capability_heuristic:{','.join(sorted(intents)) or 'none'}",
        )
    except Exception as exc:  # noqa: BLE001 - never fail a turn over bookkeeping
        logger.warning(f"Could not record a capability refusal: {exc!r}")


def _tool_can_handle(
    tool_name: str, intents: Set[str], arguments: Optional[dict] = None
) -> bool:
    """Whether `tool_name` could satisfy the turn's inferred intents.

    The capability table describes the static tools and only those. A
    discovered tool has no entry and never will -- MCP carries no capability
    vocabulary -- so a missing entry is not evidence against it, and treating
    it as such would refuse every alena-core tool before it was ever called.

    The gateway remains the authority on whether a call is permitted. This
    heuristic exists only to stop the planner answering a clock question with
    a code generator, and it can only judge the tools it actually describes.
    """
    if tool_name in TOOL_CAPABILITIES:
        allowed = tool_can_handle(tool_name, intents)
    else:
        allowed = _catalog_entry(tool_name) is not None

    if not allowed:
        _record_gate_refusal(tool_name, arguments or {}, intents)
    return allowed


async def _discover_tools() -> None:
    """Put the discovered MCP tools in the catalog before the planner runs.

    This is what the local model's `tools` array is built from, so it has to
    happen before the first `ask_llm` rather than before the first tool call.
    It costs one subprocess per process: `ensure_discovered` is a no-op once
    the catalog is filled.
    """
    try:
        discovered = await ensure_discovered()
    except Exception as exc:  # noqa: BLE001 - the assistant answers regardless
        logger.warning(f"Tool discovery failed: {exc!r}")
        return
    if discovered:
        logger.info(f"TOOLS_DISCOVERED: {', '.join(sorted(discovered))}")


def _parse_tool_call(response: str) -> Optional[dict]:
    """Return the tool-call payload in `response`, or None if it is prose.

    A reply is only a tool call if it is a JSON object naming a tool. Testing
    for "parses as JSON" instead would crash on a model that answers with a
    bare number or list, which json.loads accepts but has no .get().
    """
    try:
        parsed = json.loads(response)
    except json.JSONDecodeError:
        return None

    if isinstance(parsed, dict) and parsed.get("tool"):
        return parsed
    return None


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
    """Plan and act on one user turn.

    A gateway refusal is an answer, not a crash: the planner regularly asks for
    a tool the policy will not give it, and the CLI and the controller both
    need that to come back as text rather than a traceback.
    """
    await _discover_tools()
    try:
        return await _plan_and_act(
            user_input,
            memory,
            tool_executor,
            output_sink=output_sink,
            return_output=return_output,
        )
    except GatewayDenied as exc:
        message = (
            "❌ I cannot complete this request with the available tools.\n"
            f"Reason: {exc}"
        )
        logger.warning(f"GATEWAY_REFUSED_TURN: {exc.reason_code} - {exc}")
        (output_sink or print)(message)
        return message if return_output else None


async def _plan_and_act(
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

    # 1️⃣ Ask the planner
    history = memory.get_messages()
    try:
        llm_response = ask_llm(
            [
                *history,
                {"role": "user", "content": user_input},
            ]
        )
    except LLMUnavailable as exc:
        emit(f"❌ Inference server unavailable: {exc}")
        return done()

    memory.add_user(user_input)

    logger.info(f"LLM_RESPONSE: {llm_response}")

    if not llm_response.strip():
        logger.warning("LLM returned empty response")
        if "codex" in text:
            tool = "codex_generate"
            arguments = {"prompt": user_input}
            logger.info(f"TOOL_REQUEST (fallback): tool={tool} arguments={arguments}")

            intents = infer_intents(user_input)
            if not explicit_codex_request and not _tool_can_handle(
                tool, intents, arguments
            ):
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
            "❌ The model returned an empty response. "
            "Check LLM_BASE_URL/LLM_MODEL/LLM_TIMEOUT or enable LLM_DEBUG=1."
        )
        return done()

    # 2️⃣ Tool loop: allow multiple tool calls
    max_tool_steps = int(os.getenv("ALENA_MAX_TOOL_STEPS", "3"))
    tool_steps = 0
    current_response = llm_response

    while True:
        parsed = _parse_tool_call(current_response)
        if parsed is None:
            intents = infer_intents(user_input)
            if "access_filesystem" in intents:
                tool = "codex_analyze"
                arguments = {"repo_path": ".", "question": user_input}
                if not explicit_codex_request and not _tool_can_handle(
                    tool, intents, arguments
                ):
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

        if not explicit_codex_request and not _tool_can_handle(
            tool, intents, arguments
        ):
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
            # Ending the turn here used to throw away the result of the call
            # that tripped the limit, and answer an error. The budget is on
            # tool calls, not on the turn -- so spend the last step asking for
            # prose instead, and let the model say what it could not finish.
            try:
                final_message = ask_llm(
                    [
                        *memory.get_messages(),
                        {
                            "role": "user",
                            "content": (
                                "No more tool calls are available for this "
                                "turn. Answer now from the tool results above."
                            ),
                        },
                    ],
                    with_tools=False,
                )
            except LLMUnavailable as exc:
                emit(f"❌ Inference server unavailable: {exc}")
                return done()

            if not final_message.strip():
                # Emit-only, like the other failure paths: an empty string is
                # not an answer to hand back to a caller.
                final_message = None
                emit(
                    "❌ Reached tool step limit. "
                    "Please refine the request or try again."
                )
                return done()

            memory.add_assistant(final_message)
            emit("\n✅ Final answer:\n" + final_message)
            return done()

        # Asking for "a tool call JSON" here contradicts the system prompt,
        # which tells the model to use the tool-calling interface. Given both,
        # a model splits the difference and writes prose that *describes* a
        # call -- which parses as an answer, so the chain ends one step short
        # of the thing the user asked for.
        followup = (
            "Use the tool result above to continue. If you need another tool, "
            "call it through the tool interface. Otherwise give the final "
            "answer. Do not describe a tool call in your reply: either make "
            "the call or answer."
        )
        try:
            current_response = ask_llm(
                [
                    *memory.get_messages(),
                    {"role": "user", "content": followup},
                ]
            )
        except LLMUnavailable as exc:
            emit(f"❌ Inference server unavailable: {exc}")
            return done()

    return done()
