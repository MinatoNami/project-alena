import pytest
from modules.core.controller.tool_registry import validate_tool_call

def test_valid_tool_call():
    validate_tool_call({
        "tool": "codex_generate",
        "arguments": {"prompt": "hello"}
    })

def test_missing_tool_key():
    with pytest.raises(ValueError):
        validate_tool_call({"arguments": {}})

def test_unknown_tool():
    with pytest.raises(ValueError):
        validate_tool_call({
            "tool": "rm_rf",
            "arguments": {}
        })

def test_missing_argument():
    with pytest.raises(ValueError):
        validate_tool_call({
            "tool": "codex_edit",
            "arguments": {"repo_path": "/tmp"}
        })
