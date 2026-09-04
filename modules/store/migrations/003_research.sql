-- Schema 003: external research, engineering review, and the link from an
-- observation to the recommendation it became.

-- A research document produced outside ALENA -- today, by a ChatGPT Work
-- scheduled task. Its content is third-party text that will later be shown to
-- a coding agent, so it is stored as data and never as instructions.
CREATE TABLE IF NOT EXISTS research_documents (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    repository_id   TEXT NOT NULL REFERENCES repositories (id) ON DELETE CASCADE,
    created_at      TEXT NOT NULL,
    source          TEXT NOT NULL,
    title           TEXT,
    document_date   TEXT,
    path            TEXT,
    content         TEXT NOT NULL,
    -- Re-ingesting the same file must not duplicate its observations.
    content_hash    TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_research_repo_hash
    ON research_documents (repository_id, content_hash);

-- One claim from a research document. Observations are what dedup and review
-- operate on; an observation that survives both becomes a recommendation.
CREATE TABLE IF NOT EXISTS observations (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    research_id      INTEGER NOT NULL REFERENCES research_documents (id) ON DELETE CASCADE,
    repository_id    TEXT NOT NULL REFERENCES repositories (id) ON DELETE CASCADE,
    created_at       TEXT NOT NULL,
    title            TEXT NOT NULL,
    normalized_title TEXT NOT NULL,
    body             TEXT,
    evidence         TEXT,
    -- Set when dedup refuses it: why, and what it duplicated.
    duplicate_of     INTEGER REFERENCES recommendations (id) ON DELETE SET NULL,
    duplicate_reason TEXT,
    similarity       REAL,
    embedding        BLOB
);

CREATE INDEX IF NOT EXISTS idx_observations_repo
    ON observations (repository_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_observations_normalized
    ON observations (repository_id, normalized_title);

-- An engineering agent's verdict on one observation. Codex in Phase 2, Claude
-- in Phase 3. Both are recorded even when they disagree -- the disagreement is
-- the point of running two.
CREATE TABLE IF NOT EXISTS engineering_reviews (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    observation_id INTEGER NOT NULL REFERENCES observations (id) ON DELETE CASCADE,
    repository_id  TEXT NOT NULL REFERENCES repositories (id) ON DELETE CASCADE,
    created_at     TEXT NOT NULL,
    agent          TEXT NOT NULL,
    verdict        TEXT NOT NULL
        CHECK (verdict IN ('supported', 'rejected', 'unclear', 'error')),
    confidence     REAL,
    fit            REAL,
    cost           REAL,
    risk           REAL,
    body           TEXT,
    path           TEXT
);

CREATE INDEX IF NOT EXISTS idx_reviews_observation
    ON engineering_reviews (observation_id, agent);

ALTER TABLE recommendations ADD COLUMN observation_id INTEGER
    REFERENCES observations (id) ON DELETE SET NULL;
ALTER TABLE recommendations ADD COLUMN score_breakdown TEXT;
