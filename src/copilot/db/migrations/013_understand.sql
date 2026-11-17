-- Migration 013: merchant entities and the categorisation cascade (PLAN_AGENTIC_V2, A2 to A6).
-- Every table carries user_id. Confidence is in basis points (0 to 10000), like money it is an integer.

CREATE TABLE merchant_entities (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    kind TEXT NOT NULL CHECK (kind IN ('merchant', 'person', 'unknown')),
    display_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    merged_into TEXT
) STRICT;
CREATE INDEX idx_entities_user ON merchant_entities (user_id, kind);

CREATE TABLE entity_aliases (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    entity_id TEXT NOT NULL REFERENCES merchant_entities(id),
    alias_type TEXT NOT NULL CHECK (alias_type IN ('vpa', 'name', 'squash', 'card')),
    alias_value TEXT NOT NULL,
    evidence_bp INTEGER NOT NULL CHECK (evidence_bp BETWEEN 0 AND 10000),
    created_at TEXT NOT NULL,
    UNIQUE (user_id, alias_type, alias_value)
) STRICT;
CREATE INDEX idx_aliases_entity ON entity_aliases (user_id, entity_id);

-- What the user said about an entity. recent_json keeps the last three answers, newest last,
-- so a single odd answer can be told from a real change of mind.
CREATE TABLE entity_labels (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    entity_id TEXT NOT NULL REFERENCES merchant_entities(id),
    category_id TEXT NOT NULL REFERENCES categories(id),
    recent_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (user_id, entity_id)
) STRICT;

-- Merges, splits and "are these the same shop?" questions. snapshot_json lets an undo restore exactly.
CREATE TABLE entity_merge_log (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    kind TEXT NOT NULL CHECK (kind IN ('merge', 'split', 'question')),
    entity_a TEXT NOT NULL,
    entity_b TEXT NOT NULL,
    evidence_bp INTEGER NOT NULL DEFAULT 0,
    actor TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('open', 'applied', 'dismissed', 'undone')),
    snapshot_json TEXT,
    created_at TEXT NOT NULL
) STRICT;

-- Why each automatic label was given: which stage, how sure, on what evidence.
CREATE TABLE category_decisions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    transaction_id TEXT NOT NULL,
    entity_id TEXT,
    stage TEXT NOT NULL CHECK (stage IN ('S0', 'S1', 'S2', 'S3', 'S4', 'S5')),
    category_id TEXT,
    raw_bp INTEGER NOT NULL,
    confidence_bp INTEGER NOT NULL,
    evidence_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    superseded_by TEXT
) STRICT;
CREATE INDEX idx_decisions_tx ON category_decisions (user_id, transaction_id);

-- Reliability bins: how often each stage was right when it said a given raw score.
CREATE TABLE calibration_bins (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    stage TEXT NOT NULL,
    bin INTEGER NOT NULL CHECK (bin BETWEEN 0 AND 9),
    n INTEGER NOT NULL DEFAULT 0,
    correct INTEGER NOT NULL DEFAULT 0,
    UNIQUE (user_id, stage, bin)
) STRICT;

-- The model's answer for an entity, kept so it is asked once, not once per payment.
CREATE TABLE entity_enrichment (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    entity_id TEXT NOT NULL REFERENCES merchant_entities(id),
    category_id TEXT,
    raw_bp INTEGER NOT NULL,
    model TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (user_id, entity_id)
) STRICT;

-- A rule the agent noticed and proposes. Applied only when the user accepts it.
CREATE TABLE rule_proposals (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    pattern TEXT NOT NULL,
    category_id TEXT NOT NULL REFERENCES categories(id),
    evidence_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'accepted', 'dismissed')),
    created_at TEXT NOT NULL,
    decided_at TEXT,
    UNIQUE (user_id, pattern, category_id)
) STRICT;
