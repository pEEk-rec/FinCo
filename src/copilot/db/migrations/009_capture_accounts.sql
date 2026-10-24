-- Migration 009: which ledger account carries which card or account number tail
-- (PLAN_CAPTURE Stage C4). Bank alerts show only the last four digits; this is how an alert is
-- tied to one of the user's accounts when reconciling by amount, account and time.
CREATE TABLE IF NOT EXISTS account_last4_map (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    last4 TEXT NOT NULL CHECK (last4 GLOB '[0-9][0-9][0-9][0-9]'),
    created_at TEXT NOT NULL,
    UNIQUE (user_id, last4)
) STRICT;
