-- Schema 007: where an observation came from.
--
-- Until now every observation arrived in a research document from an external
-- agent, and the reviewer's framing assumed that: quarantined text, to be
-- judged, whose instructions are ignored. An idea the operator typed needs a
-- different framing, so the reviewer has to be able to tell them apart.

ALTER TABLE observations ADD COLUMN source TEXT;

-- Everything already stored came from research.
UPDATE observations SET source = (
    SELECT r.source FROM research_documents r WHERE r.id = observations.research_id
) WHERE source IS NULL;
