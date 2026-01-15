import pytest

@pytest.fixture
def sample_codex_stream():
    return [
        type("Chunk", (), {
            "text": (
                '{"type":"item.completed","item":{"type":"reasoning","text":"Thinking"}}\n'
                '{"type":"item.completed","item":{"type":"agent_message","text":"Hello world"}}'
            )
        })()
    ]
