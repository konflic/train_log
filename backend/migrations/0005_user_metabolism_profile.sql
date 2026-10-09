-- 0005: optional profile inputs for future metabolism estimates.
--
-- Existing accounts predate these inputs, so their values remain NULL. New
-- registrations collect them in the UI and persist them with the account.

ALTER TABLE users ADD COLUMN sex TEXT
    CHECK (sex IS NULL OR sex IN ('male', 'female'));

ALTER TABLE users ADD COLUMN age INTEGER
    CHECK (age IS NULL OR (age >= 1 AND age <= 120));
