# modules/core/tools/tool_capabilities.py

from dataclasses import dataclass
from typing import Set
from modules.core.controller.tool_definitions import get_tool_capabilities_dict


@dataclass(frozen=True)
class ToolCapabilities:
    name: str
    can_generate_code: bool = False
    can_edit_files: bool = False
    can_execute_code: bool = False
    can_access_time: bool = False
    can_access_network: bool = False
    can_read_files: bool = False


# Auto-generated from centralized tool definitions
_caps_dict = get_tool_capabilities_dict()
TOOL_CAPABILITIES = {
    name: ToolCapabilities(**caps) for name, caps in _caps_dict.items()
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
