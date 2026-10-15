-- Migration 005: Phase 4 Behavioural Engagement & Gamification Schema (PLAN_PHASE4 Section 4)

-- 1. Experiments
CREATE TABLE IF NOT EXISTS experiments (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    template_code TEXT,
    hypothesis_json TEXT NOT NULL,
    metric_def_json TEXT NOT NULL,
    params_json TEXT NOT NULL,
    difficulty TEXT NOT NULL,
    window_start TEXT NOT NULL CHECK (window_start GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    window_end TEXT NOT NULL CHECK (window_end GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    baseline_json TEXT NOT NULL,
    target_value INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('offered', 'active', 'paused', 'completed', 'abandoned', 'expired', 'reviewed')),
    origin TEXT NOT NULL CHECK (origin IN ('user', 'offer', 'goal_decomposition')),
    offer_id TEXT,
    goal_id TEXT REFERENCES goals(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL CHECK (created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    started_at TEXT CHECK (started_at IS NULL OR started_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    ended_at TEXT CHECK (ended_at IS NULL OR ended_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z')
) STRICT;

CREATE INDEX IF NOT EXISTS idx_experiments_user_status ON experiments(user_id, status);
CREATE INDEX IF NOT EXISTS idx_experiments_user_window ON experiments(user_id, window_start, window_end);

-- 2. Experiment Check-ins
CREATE TABLE IF NOT EXISTS experiment_checkins (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    experiment_id TEXT NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    checkin_date TEXT NOT NULL CHECK (checkin_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    observed_value INTEGER NOT NULL,
    pace_status TEXT NOT NULL CHECK (pace_status IN ('ahead', 'on_pace', 'behind', 'insufficient')),
    user_response TEXT CHECK (user_response IS NULL OR user_response IN ('going_well', 'hard', 'want_to_pause', 'skip')),
    created_at TEXT NOT NULL CHECK (created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z')
) STRICT;

CREATE INDEX IF NOT EXISTS idx_checkins_user_exp ON experiment_checkins(user_id, experiment_id, checkin_date);

-- 3. Experiment Reviews
CREATE TABLE IF NOT EXISTS experiment_reviews (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    experiment_id TEXT NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    observed_value INTEGER NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('beyond_usual_range', 'within_usual_range', 'above_usual_range', 'no_baseline')),
    rank_p_bp INTEGER NOT NULL CHECK (rank_p_bp BETWEEN 1 AND 10000),
    effect_value INTEGER NOT NULL,
    target_met INTEGER NOT NULL CHECK (target_met IN (0, 1)),
    integrity_json TEXT NOT NULL,
    data_quality_json TEXT NOT NULL,
    user_difficulty INTEGER CHECK (user_difficulty IS NULL OR (user_difficulty BETWEEN 1 AND 5)),
    user_helpful INTEGER CHECK (user_helpful IS NULL OR user_helpful IN (0, 1)),
    user_would_repeat INTEGER CHECK (user_would_repeat IS NULL OR user_would_repeat IN (0, 1)),
    created_at TEXT NOT NULL CHECK (created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z')
) STRICT;

CREATE INDEX IF NOT EXISTS idx_reviews_user_exp ON experiment_reviews(user_id, experiment_id);

-- 4. Adjustment Proposals
CREATE TABLE IF NOT EXISTS adjustment_proposals (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    experiment_id TEXT NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('ease_target', 'extend', 'pause', 'resume', 'raise_target_optional', 'end_early')),
    reason_code TEXT NOT NULL,
    params_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('proposed', 'accepted', 'rejected', 'expired', 'auto_applied_pause')),
    created_at TEXT NOT NULL CHECK (created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    decided_at TEXT CHECK (decided_at IS NULL OR decided_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z')
) STRICT;

CREATE INDEX IF NOT EXISTS idx_adj_user_exp ON adjustment_proposals(user_id, experiment_id, status);

-- 5. Offers
CREATE TABLE IF NOT EXISTS offers (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    week_start TEXT NOT NULL CHECK (week_start GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    template_code TEXT NOT NULL,
    difficulty TEXT NOT NULL CHECK (difficulty IN ('easy', 'medium', 'hard')),
    params_json TEXT NOT NULL,
    rank INTEGER NOT NULL,
    propensity_bp INTEGER NOT NULL CHECK (propensity_bp BETWEEN 1 AND 10000),
    policy_version TEXT NOT NULL,
    rng_seed INTEGER NOT NULL,
    reason_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('shown', 'accepted', 'dismissed', 'expired')),
    created_at TEXT NOT NULL CHECK (created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    decided_at TEXT CHECK (decided_at IS NULL OR decided_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z')
) STRICT;

CREATE INDEX IF NOT EXISTS idx_offers_user_week ON offers(user_id, week_start, status);

-- 6. XP Events (append-only, unique per event award)
CREATE TABLE IF NOT EXISTS xp_events (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    rule_code TEXT NOT NULL,
    points INTEGER NOT NULL CHECK (points > 0),
    ref_kind TEXT NOT NULL,
    ref_id TEXT NOT NULL,
    period_day TEXT NOT NULL CHECK (period_day GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    created_at TEXT NOT NULL CHECK (created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    UNIQUE(user_id, rule_code, ref_kind, ref_id)
) STRICT;

CREATE INDEX IF NOT EXISTS idx_xp_events_user_day ON xp_events(user_id, period_day);

-- Append-only triggers for xp_events
CREATE TRIGGER IF NOT EXISTS trg_xp_events_no_update
BEFORE UPDATE ON xp_events
BEGIN
    SELECT RAISE(ABORT, 'xp_events is append-only, UPDATE is not allowed');
END;

CREATE TRIGGER IF NOT EXISTS trg_xp_events_no_delete
BEFORE DELETE ON xp_events
BEGIN
    SELECT RAISE(ABORT, 'xp_events is append-only, DELETE is not allowed');
END;

-- 7. Badge Awards (unique per badge per user)
CREATE TABLE IF NOT EXISTS badge_awards (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    badge_code TEXT NOT NULL,
    awarded_at TEXT NOT NULL CHECK (awarded_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    evidence_json TEXT NOT NULL,
    UNIQUE(user_id, badge_code)
) STRICT;

CREATE INDEX IF NOT EXISTS idx_badge_awards_user ON badge_awards(user_id, badge_code);

-- 8. Streak Freezes
CREATE TABLE IF NOT EXISTS streak_freezes (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    streak_code TEXT NOT NULL,
    from_date TEXT NOT NULL CHECK (from_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    to_date TEXT NOT NULL CHECK (to_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    reason TEXT NOT NULL CHECK (reason IN ('grace', 'exception')),
    created_at TEXT NOT NULL CHECK (created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z')
) STRICT;

CREATE INDEX IF NOT EXISTS idx_streak_freezes_user ON streak_freezes(user_id, streak_code, from_date, to_date);

-- 9. Upgrade feedback_stats to support 'challenge_template'
CREATE TABLE new_feedback_stats (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    subject_kind TEXT NOT NULL CHECK (subject_kind IN ('alert_kind', 'advice_kind', 'challenge_template')),
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

PRAGMA foreign_keys = OFF;

-- 10. Upgrade memory_items to support 'experiment_outcome'
CREATE TABLE new_memory_items (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    kind TEXT NOT NULL CHECK (kind IN ('recurring_pattern', 'contextual_exception', 'advice_feedback', 'preference', 'merchant_habit', 'experiment_outcome')),
    subject_key TEXT NOT NULL,
    statement_json TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('observed', 'user_stated', 'feedback', 'capture_label')),
    status TEXT NOT NULL CHECK (status IN ('candidate', 'active', 'stale', 'retired', 'rejected', 'forgotten')),
    prior_bp INTEGER NOT NULL CHECK (prior_bp BETWEEN 0 AND 10000),
    user_confirmed INTEGER NOT NULL DEFAULT 0 CHECK (user_confirmed IN (0, 1)),
    created_at TEXT NOT NULL CHECK (created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    last_evidence_at TEXT CHECK (last_evidence_at IS NULL OR last_evidence_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    last_confirmed_at TEXT CHECK (last_confirmed_at IS NULL OR last_confirmed_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z')
) STRICT;

INSERT INTO new_memory_items SELECT * FROM memory_items;
DROP TABLE memory_items;
ALTER TABLE new_memory_items RENAME TO memory_items;
CREATE INDEX IF NOT EXISTS idx_memory_items_user_status ON memory_items(user_id, status);
CREATE INDEX IF NOT EXISTS idx_memory_items_user_subject ON memory_items(user_id, subject_key);

-- 11. Upgrade memory_evidence to support 'review' and 'experiment'
CREATE TABLE new_memory_evidence (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    memory_id TEXT NOT NULL REFERENCES memory_items(id) ON DELETE CASCADE,
    polarity TEXT NOT NULL CHECK (polarity IN ('supports', 'contradicts')),
    ref_kind TEXT NOT NULL CHECK (ref_kind IN ('txn', 'advice', 'audit_event', 'anomaly', 'investigation', 'capture_label', 'review', 'experiment')),
    ref_id TEXT NOT NULL,
    observed_at TEXT NOT NULL CHECK (observed_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    weight_bp INTEGER NOT NULL CHECK (weight_bp BETWEEN 0 AND 10000),
    created_at TEXT NOT NULL CHECK (created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z')
) STRICT;

INSERT INTO new_memory_evidence SELECT * FROM memory_evidence;
DROP TABLE memory_evidence;
ALTER TABLE new_memory_evidence RENAME TO memory_evidence;
CREATE INDEX IF NOT EXISTS idx_memory_evidence_memory ON memory_evidence(memory_id, polarity);

PRAGMA foreign_keys = ON;
