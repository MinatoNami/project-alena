-- Schema 002: repository intelligence and recommendation memory.
--
-- The registry YAML is the authority on which repositories exist and what may
-- be done to them. These tables hold what ALENA has *learned* about them --
-- scans, and the recommendation history that stops rejected ideas coming back.

CREATE TABLE IF NOT EXISTS repositories (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    workspace       TEXT NOT NULL,
    default_branch  TEXT,
    tags            TEXT,
    first_seen_at   TEXT NOT NULL,
    last_seen_at    TEXT NOT NULL
);

-- One row per scan. `fingerprint` is what makes "nothing changed" cheap: a
-- repeat scan that matches the previous fingerprint skips the model entirely.
CREATE TABLE IF NOT EXISTS scans (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    repository_id   TEXT NOT NULL REFERENCES repositories (id) ON DELETE CASCADE,
    created_at      TEXT NOT NULL,
    fingerprint     TEXT NOT NULL,
    head_sha        TEXT,
    branch          TEXT,
    dirty           INTEGER NOT NULL DEFAULT 0,
    changed         INTEGER NOT NULL DEFAULT 1,
    file_count      INTEGER,
    languages       TEXT,
    dependencies    TEXT,
    todos           TEXT,
    recent_commits  TEXT,
    summary         TEXT,
    diff_summary    TEXT
);

CREATE INDEX IF NOT EXISTS idx_scans_repo ON scans (repository_id, id DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_scans_repo_fingerprint
    ON scans (repository_id, fingerprint);

-- Recommendation memory. Nothing writes here until Phase 2, but the schema
-- lands now because the scanner already needs somewhere to look when it asks
-- "have we suggested this before".
CREATE TABLE IF NOT EXISTS recommendations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    repository_id   TEXT NOT NULL REFERENCES repositories (id) ON DELETE CASCADE,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    title           TEXT NOT NULL,
    normalized_title TEXT NOT NULL,
    body            TEXT,
    status          TEXT NOT NULL DEFAULT 'recommended'
        CHECK (status IN ('recommended', 'accepted', 'rejected', 'implemented',
                          'abandoned', 'successful', 'unsuccessful')),
    -- Rejections carry a reason, and the reason goes back into the prompt.
    -- Re-suggesting a rejected idea is the failure mode the specs lead with.
    reason          TEXT,
    score           REAL,
    confidence      REAL,
    estimated_effort TEXT,
    actual_effort   TEXT,
    embedding       BLOB
);

CREATE INDEX IF NOT EXISTS idx_recommendations_repo
    ON recommendations (repository_id, status);
CREATE INDEX IF NOT EXISTS idx_recommendations_normalized
    ON recommendations (repository_id, normalized_title);
