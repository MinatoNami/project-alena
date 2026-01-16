# Tool System Architecture

## Overview

The tool system has been refactored to use a **centralized, single-source-of-truth** approach for defining tools and their capabilities. This makes it easy to add new MCP servers and their tools without having to update multiple files.

## Architecture

### Core Components

1. **`tool_definitions.py`** - Single source of truth

   - Contains all tool definitions with metadata
   - Defines tool capabilities using enums
   - Provides helper functions to generate formats for other modules

2. **`tool_registry.py`** - Auto-generated registry

   - Imports and uses definitions from `tool_definitions.py`
   - Validates tool calls against required arguments

3. **`tool_capabilities.py`** - Auto-generated capabilities

   - Imports and uses definitions from `tool_definitions.py`
   - Used by safety checks to verify tool permissions

4. **`ollama_client.py`** - Auto-generated system prompt
   - Imports tool descriptions from `tool_definitions.py`
   - System prompt is dynamically generated with current tools

## Adding a New MCP Server

### Step 1: Add Tool Definitions

Edit `tool_definitions.py` and add your tools to the `TOOL_DEFINITIONS` list:

```python
ToolDefinition(
    name="your_tool_name",
    description="What the tool does",
    mcp_server="your-mcp-server-name",
    required_args=[
        ToolArgument("arg1", "string", description="Description of arg1"),
        ToolArgument("arg2", "int", description="Description of arg2")
    ],
    optional_args=[
        ToolArgument("opt_arg", "string", required=False, description="Optional arg")
    ],
    capabilities=[
        ToolCapability.ACCESS_NETWORK,  # Choose appropriate capabilities
        ToolCapability.ACCESS_TIME
    ]
)
```

### Step 2: Available Capabilities

Choose from these capability flags:

- `ToolCapability.GENERATE_CODE` - Can generate code
- `ToolCapability.EDIT_FILES` - Can modify files
- `ToolCapability.EXECUTE_CODE` - Can execute code
- `ToolCapability.ACCESS_TIME` - Can access time/dates
- `ToolCapability.ACCESS_NETWORK` - Can make network requests
- `ToolCapability.READ_FILES` - Can read files

### Step 3: That's It!

All other files will automatically pick up the new tools:

- ✅ Tool registry will validate new tool calls
- ✅ Capability checks will work with new tools
- ✅ System prompt will include new tools
- ✅ No manual updates needed elsewhere

## Example: Adding Slack MCP Server

```python
# In tool_definitions.py, add to TOOL_DEFINITIONS list:

ToolDefinition(
    name="slack_send_message",
    description="Send a message to a Slack channel",
    mcp_server="slack",
    required_args=[
        ToolArgument("channel", "string", description="Channel ID or name"),
        ToolArgument("message", "string", description="Message text to send")
    ],
    optional_args=[
        ToolArgument("thread_ts", "string", required=False,
                    description="Thread timestamp for replies")
    ],
    capabilities=[ToolCapability.ACCESS_NETWORK]
),

ToolDefinition(
    name="slack_list_channels",
    description="List all Slack channels",
    mcp_server="slack",
    capabilities=[ToolCapability.ACCESS_NETWORK]
),
```

## Benefits

### Before (Old System)

- ❌ Tools defined in 3+ different places
- ❌ Easy to create inconsistencies
- ❌ Required updating multiple files for each new tool
- ❌ No single view of all tools

### After (New System)

- ✅ Single source of truth
- ✅ Consistent definitions everywhere
- ✅ Add tools in one place only
- ✅ Type-safe with dataclasses
- ✅ Auto-generated documentation
- ✅ Easy to add new MCP servers

## Helper Functions

### Query Tools

```python
from modules.core.controller.tool_definitions import (
    get_tool_by_name,
    get_tools_by_server,
    get_all_tool_names
)

# Get specific tool
tool = get_tool_by_name("codex_generate")

# Get all tools for a server
codex_tools = get_tools_by_server("codex")
calendar_tools = get_tools_by_server("google-calendar")

# Get all tool names
all_tools = get_all_tool_names()
```

### Generate Formats

```python
from modules.core.controller.tool_definitions import (
    generate_system_prompt_tools_section,
    get_tool_registry,
    get_tool_capabilities_dict
)

# Generate system prompt section
prompt_text = generate_system_prompt_tools_section()

# Get registry format
registry = get_tool_registry()

# Get capabilities dict
capabilities = get_tool_capabilities_dict()
```

## Testing

When adding new tools, make sure to:

1. Test tool validation in `tool_registry.py`
2. Test capability checks in `tool_capabilities.py`
3. Verify system prompt includes new tools
4. Add unit tests for new MCP server tools

## Migration Notes

The old hardcoded definitions have been replaced with auto-generated ones from `tool_definitions.py`. If you need to modify tool behavior:

1. ✅ Edit `tool_definitions.py`
2. ❌ Don't edit the generated sections in other files
