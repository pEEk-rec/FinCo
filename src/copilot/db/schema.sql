-- SQLite schema for Phase 0 (schema version 1).
--
-- Conventions:
--   * Tables are STRICT (SQLite >= 3.37): an INTEGER column rejects 499.5 instead of storing a REAL.
--   * Every timestamp is canonical UTC text 'YYYY-MM-DDTHH:MM:SSZ' (CHECKed with GLOB), so plain
--     string comparison in SQL orders them correctly.
--   * Tenant safety: parent tables expose UNIQUE(user_id, id) and children reference
--     (user_id, <parent>_id). A row can therefore only point at a parent owned by the same user.
--   * The whole script runs in one transaction and stamps PRAGMA user_version at the end.

BEGIN;

CREATE TABLE users (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL CHECK (created_at GLOB
        '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z')
) STRICT;

CREATE TABLE accounts (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,
    opening_balance_paise INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL CHECK (created_at GLOB
        '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    UNIQUE (user_id, id)
) STRICT;

CREATE TABLE categories (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,
    created_at TEXT NOT NULL CHECK (created_at GLOB
        '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    UNIQUE (user_id, id),
    UNIQUE (user_id, name)
) STRICT;

-- Sign convention: debit (spend) => amount_paise > 0, credit (refund/income) => amount_paise < 0.
-- Zero-amount rows are rejected.
CREATE TABLE transactions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    account_id TEXT NOT NULL,
    occurred_at TEXT NOT NULL CHECK (occurred_at GLOB
        '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    amount_paise INTEGER NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('debit', 'credit')),
    merchant_raw TEXT NOT NULL,
    description TEXT NOT NULL,
    category_id TEXT,
    category_confidence REAL CHECK (
        category_confidence IS NULL OR (category_confidence >= 0.0 AND category_confidence <= 1.0)
    ),
    category_source TEXT NOT NULL CHECK (category_source IN ('rule', 'llm', 'user', 'none')),
    created_at TEXT NOT NULL CHECK (created_at GLOB
        '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    CHECK (
        (direction = 'debit' AND amount_paise > 0) OR (direction = 'credit' AND amount_paise < 0)
    ),
    FOREIGN KEY (user_id, account_id) REFERENCES accounts(user_id, id),
    FOREIGN KEY (user_id, category_id) REFERENCES categories(user_id, id)
) STRICT;

CREATE INDEX idx_transactions_user_occurred ON transactions(user_id, occurred_at);

CREATE TABLE budgets (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    category_id TEXT NOT NULL,
    period TEXT NOT NULL CHECK (period = 'monthly'),
    limit_paise INTEGER NOT NULL CHECK (limit_paise >= 0),
    warn_threshold_pct INTEGER NOT NULL CHECK (warn_threshold_pct >= 0 AND warn_threshold_pct <= 100),
    UNIQUE (user_id, category_id, period),
    FOREIGN KEY (user_id, category_id) REFERENCES categories(user_id, id)
) STRICT;

CREATE TABLE audit_events (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    run_id TEXT,
    occurred_at TEXT NOT NULL CHECK (occurred_at GLOB
        '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    actor TEXT NOT NULL CHECK (actor IN ('user', 'agent', 'system')),
    event_type TEXT NOT NULL,
    entity_type TEXT,
    entity_id TEXT,
    before_json TEXT,
    after_json TEXT,
    reason TEXT NOT NULL,
    policy_decision TEXT CHECK (policy_decision IN ('allow', 'deny', 'needs_approval')),
    metadata_json TEXT
) STRICT;

CREATE INDEX idx_audit_user_occurred ON audit_events(user_id, occurred_at);
CREATE INDEX idx_audit_user_run ON audit_events(user_id, run_id);
CREATE INDEX idx_audit_user_entity ON audit_events(user_id, entity_id);

CREATE TRIGGER trg_audit_events_no_update
BEFORE UPDATE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit_events is append-only, UPDATE is not allowed');
END;

CREATE TRIGGER trg_audit_events_no_delete
BEFORE DELETE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit_events is append-only, DELETE is not allowed');
END;

-- memory_entries schema (Step 8)
CREATE TABLE memory_entries (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    kind TEXT NOT NULL CHECK (kind IN ('preference', 'pattern', 'feedback')),
    content TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('user_stated', 'observed', 'inferred')),
    confidence REAL NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    created_at TEXT NOT NULL CHECK (created_at GLOB
        '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    last_confirmed_at TEXT NOT NULL CHECK (last_confirmed_at GLOB
        '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    provenance TEXT NOT NULL
) STRICT;

-- Reserved for later phase, no logic yet
CREATE TABLE goals (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
) STRICT;

-- Reserved for later phase, no logic yet
CREATE TABLE buckets (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
) STRICT;

PRAGMA user_version = 1;

COMMIT;
