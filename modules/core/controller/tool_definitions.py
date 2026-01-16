"""
Centralized tool definitions for all MCP servers.
Single source of truth for tool metadata, capabilities, and documentation.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from enum import Enum


class ToolCapability(Enum):
    """Tool capability flags"""

    GENERATE_CODE = "generate_code"
    EDIT_FILES = "edit_files"
    EXECUTE_CODE = "execute_code"
    ACCESS_TIME = "access_time"
    ACCESS_NETWORK = "access_network"
    READ_FILES = "read_files"


@dataclass
class ToolArgument:
    """Tool argument definition"""

    name: str
    arg_type: str
    required: bool = True
    description: str = ""


@dataclass
class ToolDefinition:
    """Complete tool definition"""

    name: str
    description: str
    mcp_server: str
    required_args: List[ToolArgument] = field(default_factory=list)
    optional_args: List[ToolArgument] = field(default_factory=list)
    capabilities: List[ToolCapability] = field(default_factory=list)

    def get_all_args(self) -> List[ToolArgument]:
        """Get all arguments (required + optional)"""
        return self.required_args + self.optional_args

    def get_required_arg_names(self) -> List[str]:
        """Get list of required argument names"""
        return [arg.name for arg in self.required_args]

    def has_capability(self, capability: ToolCapability) -> bool:
        """Check if tool has a specific capability"""
        return capability in self.capabilities

    def to_system_prompt_format(self) -> str:
        """Generate system prompt format string"""
        args = []
        for arg in self.required_args:
            args.append(f"{arg.name}: {arg.arg_type}")
        for arg in self.optional_args:
            args.append(f"{arg.name}?: {arg.arg_type}")
        return f"- {self.name}({', '.join(args)})"


# ============================================================================
# TOOL DEFINITIONS
# ============================================================================

TOOL_DEFINITIONS = [
    # Codex MCP Server Tools
    # ToolDefinition(
    #     name="codex_generate",
    #     description="Generate code based on a prompt",
    #     mcp_server="codex",
    #     required_args=[
    #         ToolArgument("prompt", "string", description="Code generation prompt")
    #     ],
    #     capabilities=[ToolCapability.GENERATE_CODE],
    # ),
    # ToolDefinition(
    #     name="codex_plan",
    #     description="Create a development plan for a repository",
    #     mcp_server="codex",
    #     required_args=[
    #         ToolArgument("repo_path", "string", description="Path to repository"),
    #         ToolArgument("goal", "string", description="Development goal"),
    #     ],
    #     capabilities=[ToolCapability.READ_FILES],
    # ),
    # ToolDefinition(
    #     name="codex_analyze",
    #     description="Analyze code in a repository",
    #     mcp_server="codex",
    #     required_args=[
    #         ToolArgument("repo_path", "string", description="Path to repository"),
    #         ToolArgument("question", "string", description="Analysis question"),
    #     ],
    #     capabilities=[ToolCapability.READ_FILES],
    # ),
    # ToolDefinition(
    #     name="codex_summarize",
    #     description="Summarize code in a repository",
    #     mcp_server="codex",
    #     required_args=[
    #         ToolArgument("repo_path", "string", description="Path to repository")
    #     ],
    #     optional_args=[
    #         ToolArgument("focus", "string", required=False, description="Focus area")
    #     ],
    #     capabilities=[ToolCapability.READ_FILES],
    # ),
    # ToolDefinition(
    #     name="codex_doc_outline",
    #     description="Generate documentation outline for a repository",
    #     mcp_server="codex",
    #     required_args=[
    #         ToolArgument("repo_path", "string", description="Path to repository"),
    #         ToolArgument("topic", "string", description="Documentation topic"),
    #     ],
    #     optional_args=[
    #         ToolArgument(
    #             "audience", "string", required=False, description="Target audience"
    #         )
    #     ],
    #     capabilities=[ToolCapability.READ_FILES],
    # ),
    # ToolDefinition(
    #     name="codex_test_plan",
    #     description="Create a test plan for a repository",
    #     mcp_server="codex",
    #     required_args=[
    #         ToolArgument("repo_path", "string", description="Path to repository"),
    #         ToolArgument("goal", "string", description="Testing goal"),
    #     ],
    #     capabilities=[ToolCapability.READ_FILES],
    # ),
    # ToolDefinition(
    #     name="codex_edit",
    #     description="Edit files in a repository",
    #     mcp_server="codex",
    #     required_args=[
    #         ToolArgument("repo_path", "string", description="Path to repository"),
    #         ToolArgument("instruction", "string", description="Edit instruction"),
    #     ],
    #     capabilities=[ToolCapability.EDIT_FILES, ToolCapability.READ_FILES],
    # ),
    # ToolDefinition(
    #     name="codex_refactor",
    #     description="Refactor code in a repository",
    #     mcp_server="codex",
    #     required_args=[
    #         ToolArgument("repo_path", "string", description="Path to repository"),
    #         ToolArgument("goal", "string", description="Refactoring goal"),
    #     ],
    #     optional_args=[
    #         ToolArgument(
    #             "constraints",
    #             "string",
    #             required=False,
    #             description="Refactoring constraints",
    #         )
    #     ],
    #     capabilities=[ToolCapability.EDIT_FILES, ToolCapability.READ_FILES],
    # ),
    # Google Calendar MCP Server Tools
    ToolDefinition(
        name="google_list_events",
        description="List events from a Google Calendar within a date range",
        mcp_server="google-calendar",
        optional_args=[
            ToolArgument(
                "calendar_id",
                "string",
                required=False,
                description="Calendar ID (default: primary)",
            ),
            ToolArgument(
                "start_date",
                "string",
                required=False,
                description="Start date (YYYY-MM-DD)",
            ),
            ToolArgument(
                "end_date",
                "string",
                required=False,
                description="End date (YYYY-MM-DD)",
            ),
            ToolArgument(
                "max_results",
                "int",
                required=False,
                description="Maximum number of events",
            ),
        ],
        capabilities=[ToolCapability.ACCESS_NETWORK, ToolCapability.ACCESS_TIME],
    ),
    ToolDefinition(
        name="google_create_event",
        description="Create a new event in a Google Calendar",
        mcp_server="google-calendar",
        required_args=[
            ToolArgument("title", "string", description="Event title"),
            ToolArgument("start_time", "string", description="Start time (ISO format)"),
            ToolArgument("end_time", "string", description="End time (ISO format)"),
        ],
        optional_args=[
            ToolArgument(
                "calendar_id",
                "string",
                required=False,
                description="Calendar ID (default: primary)",
            ),
            ToolArgument(
                "description", "string", required=False, description="Event description"
            ),
            ToolArgument(
                "attendees",
                "List[string]",
                required=False,
                description="List of attendee emails",
            ),
        ],
        capabilities=[ToolCapability.ACCESS_NETWORK, ToolCapability.ACCESS_TIME],
    ),
    ToolDefinition(
        name="google_update_event",
        description="Update an existing event in a Google Calendar",
        mcp_server="google-calendar",
        required_args=[
            ToolArgument("event_id", "string", description="Event ID to update")
        ],
        optional_args=[
            ToolArgument(
                "calendar_id",
                "string",
                required=False,
                description="Calendar ID (default: primary)",
            ),
            ToolArgument(
                "title", "string", required=False, description="New event title"
            ),
            ToolArgument(
                "description",
                "string",
                required=False,
                description="New event description",
            ),
            ToolArgument(
                "start_time",
                "string",
                required=False,
                description="New start time (ISO format)",
            ),
            ToolArgument(
                "end_time",
                "string",
                required=False,
                description="New end time (ISO format)",
            ),
        ],
        capabilities=[ToolCapability.ACCESS_NETWORK, ToolCapability.ACCESS_TIME],
    ),
    ToolDefinition(
        name="google_delete_event",
        description="Delete an event from a Google Calendar",
        mcp_server="google-calendar",
        required_args=[
            ToolArgument("event_id", "string", description="Event ID to delete")
        ],
        optional_args=[
            ToolArgument(
                "calendar_id",
                "string",
                required=False,
                description="Calendar ID (default: primary)",
            )
        ],
        capabilities=[ToolCapability.ACCESS_NETWORK, ToolCapability.ACCESS_TIME],
    ),
]


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


def get_tool_by_name(name: str) -> Optional[ToolDefinition]:
    """Get tool definition by name"""
    for tool in TOOL_DEFINITIONS:
        if tool.name == name:
            return tool
    return None


def get_tools_by_server(server: str) -> List[ToolDefinition]:
    """Get all tools for a specific MCP server"""
    return [tool for tool in TOOL_DEFINITIONS if tool.mcp_server == server]


def get_all_tool_names() -> List[str]:
    """Get list of all tool names"""
    return [tool.name for tool in TOOL_DEFINITIONS]


def generate_system_prompt_tools_section() -> str:
    """Generate the tools section for system prompt"""
    lines = ["Available tools:"]
    for tool in TOOL_DEFINITIONS:
        lines.append(tool.to_system_prompt_format())
    return "\n".join(lines)


def get_tool_registry() -> Dict[str, Dict[str, Any]]:
    """Generate tool registry format"""
    registry = {}
    for tool in TOOL_DEFINITIONS:
        registry[tool.name] = {"required_args": tool.get_required_arg_names()}
    return registry


def get_tool_capabilities_dict() -> Dict[str, Dict[str, bool]]:
    """Generate tool capabilities format"""
    capabilities = {}
    for tool in TOOL_DEFINITIONS:
        capabilities[tool.name] = {
            "name": tool.name,
            "can_generate_code": tool.has_capability(ToolCapability.GENERATE_CODE),
            "can_edit_files": tool.has_capability(ToolCapability.EDIT_FILES),
            "can_execute_code": tool.has_capability(ToolCapability.EXECUTE_CODE),
            "can_access_time": tool.has_capability(ToolCapability.ACCESS_TIME),
            "can_access_network": tool.has_capability(ToolCapability.ACCESS_NETWORK),
            "can_read_files": tool.has_capability(ToolCapability.READ_FILES),
        }
    return capabilities
