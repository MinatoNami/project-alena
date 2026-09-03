-- Schema 005: keep the reviewer's value judgement.
--
-- The reviewer is asked for `value` and returns it, but there was nowhere to
-- put it, so synthesis substituted `fit`. That reads a change which slots
-- neatly into the architecture as a *valuable* change -- and a trivial
-- convenience that fits perfectly scored as highly as a capability the
-- product needs.

ALTER TABLE engineering_reviews ADD COLUMN value REAL;
