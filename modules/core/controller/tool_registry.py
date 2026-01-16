TOOLS = {
    "codex_generate": {
        "required_args": ["prompt"],
    },
    "codex_plan": {
        "required_args": ["repo_path", "goal"],
    },
    "codex_analyze": {
        "required_args": ["repo_path", "question"],
    },
    "codex_summarize": {
        "required_args": ["repo_path"],
    },
    "codex_doc_outline": {
        "required_args": ["repo_path", "topic"],
    },
    "codex_test_plan": {
        "required_args": ["repo_path", "goal"],
    },
    "codex_edit": {
        "required_args": ["repo_path", "instruction"],
    },
    "codex_refactor": {
        "required_args": ["repo_path", "goal"],
    },
}


def validate_tool_call(tool_call: dict):
    if "tool" not in tool_call or "arguments" not in tool_call:
        raise ValueError("Invalid tool call shape")

    tool = tool_call["tool"]
    args = tool_call["arguments"]

    if tool not in TOOLS:
        raise ValueError(f"Unknown tool: {tool}")

    for req in TOOLS[tool]["required_args"]:
        if req not in args:
            raise ValueError(f"Missing argument: {req}")
