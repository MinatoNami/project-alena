-- Schema 008: the near-duplicate band.
--
-- De-duplication skips a match silently, so its threshold is set high: a
-- false positive throws away a real idea with nobody seeing it. That caution
-- has a cost at the other end. Two proposals to move the same app off Nuxt 3
-- scored 0.83 against a 0.90 bar and both reached the queue, where a human
-- had to notice they were the same thing.
--
-- Between "certainly the same" and "probably unrelated" there is a band where
-- the right answer is not a decision at all -- it is a question, put to the
-- reviewer, which can read both and say. That is what these columns carry.
-- Unlike `duplicate_of`, an observation with them set is still reviewed.

ALTER TABLE observations ADD COLUMN near_duplicate_of INTEGER
    REFERENCES recommendations (id) ON DELETE SET NULL;
ALTER TABLE observations ADD COLUMN near_duplicate_reason TEXT;
ALTER TABLE observations ADD COLUMN near_similarity REAL;
