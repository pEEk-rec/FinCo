-- Migration 008: SMS parse outcomes (PLAN_CAPTURE Stage C2).
-- One row per message from an allowlisted bank sender: only the outcome, never the text.
-- Senders that are not allowlisted are not recorded at all.
CREATE TABLE IF NOT EXISTS sms_parse_log (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    bank TEXT NOT NULL,
    sender TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('parsed', 'unparsed', 'dropped_otp')),
    kind TEXT,
    template TEXT,
    occurred_at TEXT NOT NULL CHECK (occurred_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z')
) STRICT;

CREATE INDEX IF NOT EXISTS idx_sms_parse_log_sender ON sms_parse_log(user_id, sender, occurred_at);
