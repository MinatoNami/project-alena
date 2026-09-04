from modules.gateway.audit import hash_arguments, redact


def test_argument_hash_ignores_key_order():
    assert hash_arguments({"a": 1, "b": 2}) == hash_arguments({"b": 2, "a": 1})


def test_argument_hash_changes_with_the_values():
    assert hash_arguments({"a": 1}) != hash_arguments({"a": 2})


def test_unserialisable_arguments_still_hash():
    assert hash_arguments({"f": object()})


def test_sensitive_keys_are_redacted():
    cleaned = redact({"token": "secret", "repo_path": "/tmp"})
    assert cleaned["token"] == "***"
    assert cleaned["repo_path"] == "/tmp"


def test_arguments_are_not_stored_by_default(memory_audit):
    """They carry file contents and can carry credentials."""
    memory_audit.record(
        tool="t", agent="a", outcome="success", arguments={"text": "sensitive"}
    )

    row = memory_audit.recent(1)[0]
    assert row["arguments"] is None
    assert row["arguments_hash"]


def test_arguments_are_stored_redacted_when_enabled(memory_audit, monkeypatch):
    monkeypatch.setenv("ALENA_AUDIT_ARGUMENTS", "1")
    memory_audit.record(
        tool="t", agent="a", outcome="success", arguments={"token": "hunter2"}
    )

    assert "hunter2" not in memory_audit.recent(1)[0]["arguments"]


def test_counts_are_broken_down_by_outcome(memory_audit):
    memory_audit.record(tool="t", agent="a", outcome="success", arguments={})
    memory_audit.record(
        tool="t", agent="a", outcome="denied", arguments={}, denial_reason="nope"
    )
    memory_audit.record(tool="t", agent="a", outcome="error", arguments={}, error="x")

    assert memory_audit.count() == 3
    assert memory_audit.count("denied") == 1
