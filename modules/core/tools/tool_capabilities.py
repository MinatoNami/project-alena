# modules/core/tools/tool_capabilities.py

from dataclasses import dataclass
from typing import Set


@dataclass(frozen=True)
class ToolCapabilities:
    name: str
    can_generate_code: bool = False
    can_edit_files: bool = False
    can_execute_code: bool = False
    can_access_time: bool = False
    can_access_network: bool = False
    can_read_files: bool = False


TOOL_CAPABILITIES = {
    "codex_generate": ToolCapabilities(
        name="codex_generate",
        can_generate_code=True,
        can_execute_code=False,
        can_access_time=False,
        can_access_network=False,
    ),
    "codex_plan": ToolCapabilities(
        name="codex_plan",
        can_execute_code=False,
        can_access_time=False,
        can_access_network=False,
        can_read_files=True,
    ),
    "codex_analyze": ToolCapabilities(
        name="codex_analyze",
        can_execute_code=False,
        can_access_time=False,
        can_access_network=False,
        can_read_files=True,
    ),
    "codex_summarize": ToolCapabilities(
        name="codex_summarize",
        can_execute_code=False,
        can_access_time=False,
        can_access_network=False,
        can_read_files=True,
    ),
    "codex_doc_outline": ToolCapabilities(
        name="codex_doc_outline",
        can_execute_code=False,
        can_access_time=False,
        can_access_network=False,
        can_read_files=True,
    ),
    "codex_test_plan": ToolCapabilities(
        name="codex_test_plan",
        can_execute_code=False,
        can_access_time=False,
        can_access_network=False,
        can_read_files=True,
    ),
    "codex_edit": ToolCapabilities(
        name="codex_edit",
        can_edit_files=True,
        can_execute_code=False,
        can_access_time=False,
        can_access_network=False,
        can_read_files=True,
    ),
    "codex_refactor": ToolCapabilities(
        name="codex_refactor",
        can_edit_files=True,
        can_execute_code=False,
        can_access_time=False,
        can_access_network=False,
        can_read_files=True,
    ),
}


def tool_can_handle(tool_name: str, intents: set) -> bool:
    caps = TOOL_CAPABILITIES.get(tool_name)

    if not caps:
        return False

    intent_to_capability = {
        "access_time": caps.can_access_time,
        "access_network": caps.can_access_network,
        "generate_code": caps.can_generate_code,
        "edit_files": caps.can_edit_files,
        "access_filesystem": caps.can_read_files or caps.can_execute_code,
    }

    for intent in intents:
        if not intent_to_capability.get(intent, True):
            return False

    return True
