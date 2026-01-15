from modules.core.controller.normalize import normalize_codex_output

def test_normalize_extracts_message_and_reasoning(sample_codex_stream):
    result = normalize_codex_output(sample_codex_stream)

    assert result["message"] == "Hello world"
    assert result["reasoning"] == "Thinking"
