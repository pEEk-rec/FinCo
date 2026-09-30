-- SQLite schema for Phase 0

CREATE TABLE users (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL
);

CREATE TABLE accounts (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE categories (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE transactions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    amount_paise INTEGER NOT NULL,
    direction TEXT NOT NULL CHECK(direction IN ('debit', 'credit')),
    merchant_raw TEXT NOT NULL,
    description TEXT NOT NULL,
    category_id TEXT,
    category_confidence REAL CHECK(category_confidence IS NULL OR (category_confidence >= 0.0 AND category_confidence <= 1.0)),
    category_source TEXT NOT NULL CHECK(category_source IN ('rule', 'llm', 'user', 'none')),
    created_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id),
    FOREIGN KEY(account_id) REFERENCES accounts(id),
    FOREIGN KEY(category_id) REFERENCES categories(id)
);

CREATE INDEX idx_transactions_user_occurred ON transactions(user_id, occurred_at);

CREATE TABLE budgets (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    category_id TEXT NOT NULL,
    period TEXT NOT NULL CHECK(period = 'monthly'),
    limit_paise INTEGER NOT NULL CHECK(limit_paise >= 0),
    warn_threshold_pct INTEGER NOT NULL CHECK(warn_threshold_pct >= 0 AND warn_threshold_pct <= 100),
    FOREIGN KEY(user_id) REFERENCES users(id),
    FOREIGN KEY(category_id) REFERENCES categories(id)
);

-- audit_events created in Step 3
-- memory_entries schema (Step 8)
CREATE TABLE memory_entries (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('preference', 'pattern', 'feedback')),
    content TEXT NOT NULL,
    source TEXT NOT NULL CHECK(source IN ('user_stated', 'observed', 'inferred')),
    confidence REAL NOT NULL CHECK(confidence >= 0.0 AND confidence <= 1.0),
    created_at TEXT NOT NULL,
    last_confirmed_at TEXT NOT NULL,
    provenance TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id)
);

-- Reserved for later phase, no logic yet
CREATE TABLE goals (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id)
);

-- Reserved for later phase, no logic yet
CREATE TABLE buckets (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id)
);
