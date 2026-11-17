-- Migration 014: the personal model, check-ins, shared expenses (PLAN_AGENTIC_V2, A8 to A12).
-- Every table carries user_id; money is integer paise.

-- What the user values and how their money arrives. `stated` is what they said and confirmed;
-- `inferred` is a suggestion from their own money and is not used until they confirm it.
CREATE TABLE user_profile (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    field TEXT NOT NULL,
    value_json TEXT NOT NULL,
    provenance TEXT NOT NULL CHECK (provenance IN ('stated', 'inferred')),
    confirmed INTEGER NOT NULL CHECK (confirmed IN (0, 1)),
    evidence_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (user_id, field)
) STRICT;

-- A proposed or applied budget for a month. The plan is a JSON of exact paise lines.
CREATE TABLE budget_plans (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    period TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('proposed', 'applied', 'dismissed')),
    plan_json TEXT NOT NULL,
    before_json TEXT,
    created_at TEXT NOT NULL,
    decided_at TEXT
) STRICT;

-- Which kind of nudge, sent when, in what tone, works for this user (a bounded Beta posterior).
CREATE TABLE nudge_arms (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    timing TEXT NOT NULL,
    tone TEXT NOT NULL,
    alpha_milli INTEGER NOT NULL CHECK (alpha_milli > 0),
    beta_milli INTEGER NOT NULL CHECK (beta_milli > 0),
    trials INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    UNIQUE (user_id, timing, tone)
) STRICT;

-- The check-in agent's messages. figures_json holds every number the text may use; verified_json
-- holds what the verification step recomputed.
CREATE TABLE checkins (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    signal TEXT NOT NULL,
    headline TEXT NOT NULL,
    body TEXT NOT NULL,
    figures_json TEXT NOT NULL,
    options_json TEXT NOT NULL,
    verified_json TEXT NOT NULL,
    arm_timing TEXT,
    arm_tone TEXT,
    status TEXT NOT NULL CHECK (status IN ('sent', 'acted', 'dismissed', 'not_useful')),
    created_at TEXT NOT NULL,
    responded_at TEXT
) STRICT;
CREATE INDEX idx_checkins_user ON checkins (user_id, created_at);

-- Hypotheses the check-in agent dropped because they did not survive their own check.
CREATE TABLE checkin_drops (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    signal TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
) STRICT;

-- Shared expenses: roommates and trips. Balances are derived; nothing here moves money.
CREATE TABLE split_groups (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
) STRICT;

CREATE TABLE split_members (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    group_id TEXT NOT NULL REFERENCES split_groups(id),
    name TEXT NOT NULL,
    is_me INTEGER NOT NULL CHECK (is_me IN (0, 1))
) STRICT;

CREATE TABLE split_expenses (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    group_id TEXT NOT NULL REFERENCES split_groups(id),
    paid_by TEXT NOT NULL REFERENCES split_members(id),
    amount_paise INTEGER NOT NULL CHECK (amount_paise > 0),
    note TEXT NOT NULL,
    shares_json TEXT NOT NULL,
    txn_id TEXT,
    created_at TEXT NOT NULL
) STRICT;

-- "A paid B": a record that two people settled between themselves, never a payment made here.
CREATE TABLE split_settlements (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    group_id TEXT NOT NULL REFERENCES split_groups(id),
    from_member TEXT NOT NULL REFERENCES split_members(id),
    to_member TEXT NOT NULL REFERENCES split_members(id),
    amount_paise INTEGER NOT NULL CHECK (amount_paise > 0),
    txn_id TEXT,
    created_at TEXT NOT NULL
) STRICT;

-- What the user said about a subscription (for example "I no longer use this").
CREATE TABLE subscription_notes (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    series_id TEXT NOT NULL,
    note TEXT NOT NULL CHECK (note IN ('unused', 'keep')),
    created_at TEXT NOT NULL,
    UNIQUE (user_id, series_id)
) STRICT;
