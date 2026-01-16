from types import SimpleNamespace
import importlib.util
from pathlib import Path


def _load_normalizer():
    module_path = Path(__file__).resolve().parents[1] / "test_mcp.py"
    spec = importlib.util.spec_from_file_location("codex_test_mcp", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.normalize_codex_output


normalize_codex_output = _load_normalizer()


def test_normalize_codex_output_extracts_message_and_reasoning():
    content = [
        SimpleNamespace(
            text="""
{"type":"item.completed","item":{"type":"agent_message","text":"Hello"}}
{"type":"item.completed","item":{"type":"reasoning","text":"Because."}}
{"type":"item.completed","item":{"type":"agent_message","text":"World"}}
"""
        )
    ]

    result = normalize_codex_output(content)

    assert result["message"] == "Hello\n\nWorld"
    assert result["reasoning"] == "Because."


def test_normalize_codex_output_ignores_non_matching_lines():
    content = [
        SimpleNamespace(
            text="""
not json
{"type":"item.started"}
{"type":"item.completed","item":{"type":"other","text":"skip"}}
"""
        ),
        SimpleNamespace(no_text=True),
    ]

    result = normalize_codex_output(content)

    assert result["message"] == ""
    assert result["reasoning"] is None
