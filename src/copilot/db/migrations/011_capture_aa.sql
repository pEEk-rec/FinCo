-- Migration 011: Account Aggregator consent and fetched raw data (PLAN_CAPTURE Stage C7).
-- A consent is the user's permission, mirrored from the AA artefact. Raw fetched data lives in
-- aa_raw only until its data life ends; the ledger rows made from it belong to the user.

CREATE TABLE aa_consents (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    status TEXT NOT NULL CHECK (status IN ('pending', 'active', 'paused', 'revoked', 'expired')),
    connector TEXT NOT NULL,
    external_ref TEXT,
    purpose_code TEXT NOT NULL,
    fi_types TEXT NOT NULL,
    consent_types TEXT NOT NULL,
    fetch_type TEXT NOT NULL,
    frequency_json TEXT NOT NULL,
    consent_mode TEXT NOT NULL,
    range_from TEXT NOT NULL,
    range_to TEXT NOT NULL,
    data_life_days INTEGER NOT NULL CHECK (data_life_days > 0),
    created_at TEXT NOT NULL,
    approved_at TEXT,
    paused_at TEXT,
    revoked_at TEXT,
    expires_at TEXT,
    last_fetch_at TEXT
) STRICT;

CREATE INDEX idx_aa_consents_user ON aa_consents (user_id, status);

CREATE TABLE aa_raw (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    consent_id TEXT NOT NULL REFERENCES aa_consents(id),
    fetched_at TEXT NOT NULL,
    delete_after TEXT NOT NULL,
    txn_count INTEGER NOT NULL,
    payload TEXT NOT NULL
) STRICT;

CREATE INDEX idx_aa_raw_due ON aa_raw (delete_after);
