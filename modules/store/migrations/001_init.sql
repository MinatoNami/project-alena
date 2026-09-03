-- Schema 001: audit log.
--
-- The audit log is the gateway's record of every tool invocation, allowed or
-- refused. It is also the raw material for the tool-utility metrics described
-- in the architecture addendum, so it records outcome and duration even for
-- calls that never reached a tool.

CREATE TABLE IF NOT EXISTS tool_invocations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TEXT    NOT NULL,
    tool            TEXT    NOT NULL,
    tool_version    TEXT,
    mcp_server      TEXT,
    agent           TEXT    NOT NULL,
    repository_id   TEXT,
    side_effect     TEXT,
    -- Arguments are hashed, not stored. They routinely carry file contents and
    -- can carry credentials; a durable log of them is a liability. Set
    -- ALENA_AUDIT_ARGUMENTS=1 to also keep a redacted copy in `arguments`.
    arguments_hash  TEXT    NOT NULL,
    arguments       TEXT,
    outcome         TEXT    NOT NULL CHECK (outcome IN ('success', 'denied', 'error')),
    denial_reason   TEXT,
    duration_ms     INTEGER,
    error           TEXT
);

CREATE INDEX IF NOT EXISTS idx_tool_invocations_tool ON tool_invocations (tool);
CREATE INDEX IF NOT EXISTS idx_tool_invocations_created ON tool_invocations (created_at);
CREATE INDEX IF NOT EXISTS idx_tool_invocations_repo ON tool_invocations (repository_id);
