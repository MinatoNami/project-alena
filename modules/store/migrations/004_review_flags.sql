-- Schema 004: the flags that decide whether a second opinion is worth buying.
--
-- The spec triggers Claude on architecture-sensitive, security-sensitive or
-- large-effort candidates, and on ones where Codex was not confident. The
-- first three are judgements the reviewer is asked for directly; storing them
-- means the trigger predicate reads recorded facts rather than re-deriving
-- them from prose.

ALTER TABLE engineering_reviews ADD COLUMN requires_architecture_review INTEGER;
ALTER TABLE engineering_reviews ADD COLUMN security_sensitive INTEGER;

-- Why a candidate was escalated, kept so the decision can be audited and the
-- thresholds tuned against what actually turned out to be worth reviewing.
ALTER TABLE observations ADD COLUMN escalation_reason TEXT;
