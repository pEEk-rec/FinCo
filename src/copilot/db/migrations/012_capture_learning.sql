-- Migration 012: let the learner keep a posterior per capture ranking signal (Stage C8).
CREATE TABLE new_feedback_stats (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    subject_kind TEXT NOT NULL CHECK (subject_kind IN ('alert_kind', 'advice_kind', 'challenge_template', 'capture_signal')),
    subject_key TEXT NOT NULL,
    alpha_milli INTEGER NOT NULL DEFAULT 2000 CHECK (alpha_milli > 0),
    beta_milli INTEGER NOT NULL DEFAULT 2000 CHECK (beta_milli > 0),
    updated_at TEXT NOT NULL CHECK (updated_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    UNIQUE (user_id, subject_kind, subject_key)
) STRICT;

INSERT INTO new_feedback_stats (id, user_id, subject_kind, subject_key, alpha_milli, beta_milli, updated_at)
SELECT id, user_id, subject_kind, subject_key, alpha_milli, beta_milli, updated_at FROM feedback_stats;

DROP TABLE feedback_stats;
ALTER TABLE new_feedback_stats RENAME TO feedback_stats;
CREATE INDEX IF NOT EXISTS idx_feedback_stats_user ON feedback_stats(user_id, subject_kind);
