-- Migration 010: Web Push subscriptions and deliveries (PLAN_CAPTURE Stage C6b).
-- A subscription is one device (a laptop browser, a phone). A delivery is one prompt sent to one
-- device, with the hash of the single-use token that lets the notification's buttons answer it.
-- Payload text is never stored: only who it went to and whether the token has been used.
CREATE TABLE IF NOT EXISTS push_subscriptions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    endpoint TEXT NOT NULL,
    p256dh TEXT NOT NULL,
    auth TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT 'This device',
    created_at TEXT NOT NULL,
    last_ok_at TEXT,
    failures INTEGER NOT NULL DEFAULT 0 CHECK (failures >= 0),
    UNIQUE (user_id, endpoint)
) STRICT;

CREATE TABLE IF NOT EXISTS push_deliveries (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    subscription_id TEXT NOT NULL REFERENCES push_subscriptions(id) ON DELETE CASCADE,
    prompt_id TEXT NOT NULL REFERENCES prompt_log(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    used_at TEXT,
    UNIQUE (subscription_id, prompt_id)
) STRICT;

CREATE INDEX IF NOT EXISTS idx_push_deliveries_token ON push_deliveries(token_hash);
