-- Schema 006: human decisions and what they turned into.
--
-- The spec wants a recommendation's whole life recorded, not just its verdict:
-- what it was estimated to cost against what it cost, what value was expected
-- against what was observed. That is the material the weights get fitted to
-- later, and none of it can be recovered after the fact.

ALTER TABLE recommendations ADD COLUMN expected_value REAL;
ALTER TABLE recommendations ADD COLUMN observed_value REAL;
ALTER TABLE recommendations ADD COLUMN human_feedback TEXT;
ALTER TABLE recommendations ADD COLUMN decided_at TEXT;
ALTER TABLE recommendations ADD COLUMN decided_by TEXT;
ALTER TABLE recommendations ADD COLUMN implemented_by TEXT;
ALTER TABLE recommendations ADD COLUMN branch TEXT;

-- Every status change, kept rather than overwritten. "This was accepted, then
-- abandoned three weeks later" is a different fact from "this is abandoned",
-- and only one of them survives an UPDATE.
CREATE TABLE IF NOT EXISTS decisions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    recommendation_id INTEGER NOT NULL REFERENCES recommendations (id) ON DELETE CASCADE,
    repository_id     TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    from_status       TEXT NOT NULL,
    to_status         TEXT NOT NULL,
    reason            TEXT,
    actor             TEXT NOT NULL DEFAULT 'human'
);

CREATE INDEX IF NOT EXISTS idx_decisions_recommendation
    ON decisions (recommendation_id, id DESC);

-- One implementation attempt. The branch is recorded even when the run fails,
-- because a half-finished branch on disk is the thing you need to find.
CREATE TABLE IF NOT EXISTS implementations (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    recommendation_id INTEGER NOT NULL REFERENCES recommendations (id) ON DELETE CASCADE,
    repository_id     TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    implemented_by    TEXT NOT NULL,
    reviewed_by       TEXT,
    branch            TEXT,
    base_branch       TEXT,
    commit_sha        TEXT,
    files_changed     TEXT,
    tests_command     TEXT,
    tests_passed      INTEGER,
    tests_output      TEXT,
    review_verdict    TEXT,
    review_body       TEXT,
    pushed            INTEGER NOT NULL DEFAULT 0,
    pull_request_url  TEXT,
    status            TEXT NOT NULL DEFAULT 'started'
        CHECK (status IN ('started', 'implemented', 'reviewed', 'failed')),
    error             TEXT
);

CREATE INDEX IF NOT EXISTS idx_implementations_recommendation
    ON implementations (recommendation_id, id DESC);
