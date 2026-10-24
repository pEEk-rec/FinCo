-- Migration 007: Capture & Ledger track (PLAN_CAPTURE Stage C1, ADR-0001)
-- Payment events captured at the moment of payment, the labels users give them, what we
-- remember about each counterparty, the prompt log, and links to ledger transactions.
-- No raw message text is stored anywhere: only parsed structured fields.

CREATE TABLE IF NOT EXISTS payment_events (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source TEXT NOT NULL CHECK (source IN ('sms', 'notification', 'manual', 'simulator')),
    simulated INTEGER NOT NULL DEFAULT 0 CHECK (simulated IN (0, 1)),
    amount_paise INTEGER NOT NULL CHECK (amount_paise > 0),
    direction TEXT NOT NULL CHECK (direction IN ('debit', 'credit')),
    account_last4 TEXT CHECK (account_last4 IS NULL OR account_last4 GLOB '[0-9][0-9][0-9][0-9]'),
    utr TEXT,
    fingerprint TEXT NOT NULL,
    counterparty_key TEXT NOT NULL,
    counterparty_kind TEXT NOT NULL CHECK (counterparty_kind IN ('merchant', 'person', 'self', 'cash', 'unknown')),
    display_name TEXT NOT NULL,
    bank TEXT,
    channel TEXT NOT NULL DEFAULT 'other' CHECK (channel IN ('upi', 'card', 'atm', 'neft', 'imps', 'autopay', 'other')),
    occurred_at TEXT NOT NULL CHECK (occurred_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    state TEXT NOT NULL DEFAULT 'posted' CHECK (state IN ('detected', 'posted', 'reversed', 'reconciled', 'orphaned')),
    -- the current label (the full history is in capture_labels)
    category_id TEXT,
    credit_kind TEXT,
    category_source TEXT CHECK (category_source IS NULL OR category_source IN ('user', 'auto', 'guess')),
    needs_review INTEGER NOT NULL DEFAULT 0 CHECK (needs_review IN (0, 1)),
    reversed_event_id TEXT,
    created_at TEXT NOT NULL CHECK (created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    UNIQUE (user_id, fingerprint)
) STRICT;

-- A UTR/RRN identifies one payment. Partial index: many events legitimately have none.
CREATE UNIQUE INDEX IF NOT EXISTS idx_payment_events_utr ON payment_events(user_id, utr) WHERE utr IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_payment_events_user_time ON payment_events(user_id, occurred_at);
CREATE INDEX IF NOT EXISTS idx_payment_events_counterparty ON payment_events(user_id, counterparty_key);

CREATE TABLE IF NOT EXISTS capture_labels (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    event_id TEXT NOT NULL REFERENCES payment_events(id) ON DELETE CASCADE,
    category_id TEXT,
    credit_kind TEXT,
    split_json TEXT,
    note TEXT,
    source TEXT NOT NULL CHECK (source IN ('user', 'auto', 'guess')),
    -- which guess the user picked: 1..n, or 0 for "Other"; NULL when not asked
    rank_picked INTEGER CHECK (rank_picked IS NULL OR rank_picked >= 0),
    linked_event_id TEXT,
    created_at TEXT NOT NULL CHECK (created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z')
) STRICT;

CREATE INDEX IF NOT EXISTS idx_capture_labels_event ON capture_labels(user_id, event_id);

CREATE TABLE IF NOT EXISTS counterparty_profiles (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    counterparty_key TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('merchant', 'person', 'self', 'cash', 'unknown')),
    display_name TEXT NOT NULL,
    -- learn: k-of-n rule; always_ask: never auto-label; always_category: the user's explicit choice
    policy TEXT NOT NULL DEFAULT 'learn' CHECK (policy IN ('learn', 'always_ask', 'always_category')),
    policy_category_id TEXT,
    recent_categories_json TEXT NOT NULL DEFAULT '[]',
    seen_count INTEGER NOT NULL DEFAULT 0 CHECK (seen_count >= 0),
    last_seen_at TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE (user_id, counterparty_key)
) STRICT;

CREATE TABLE IF NOT EXISTS prompt_log (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    event_id TEXT NOT NULL REFERENCES payment_events(id) ON DELETE CASCADE,
    decision TEXT NOT NULL CHECK (decision IN ('ask', 'inbox', 'auto_label', 'guess_only', 'no_ask')),
    reason TEXT NOT NULL,
    guesses_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL CHECK (status IN ('pending', 'answered', 'expired', 'dismissed', 'not_needed')),
    created_at TEXT NOT NULL CHECK (created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    expires_at TEXT,
    answered_at TEXT,
    UNIQUE (user_id, event_id)
) STRICT;

CREATE INDEX IF NOT EXISTS idx_prompt_log_pending ON prompt_log(user_id, status, created_at);

CREATE TABLE IF NOT EXISTS event_links (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    event_id TEXT NOT NULL REFERENCES payment_events(id) ON DELETE CASCADE,
    txn_id TEXT NOT NULL,
    method TEXT NOT NULL CHECK (method IN ('utr', 'amount_account_time')),
    created_at TEXT NOT NULL,
    UNIQUE (user_id, event_id),
    UNIQUE (user_id, txn_id)
) STRICT;
