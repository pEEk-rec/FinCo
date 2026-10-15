-- Migration 004: Phase 3 Advanced Financial Copilot Schema (PLAN_PHASE3 Section 4)

-- 1. Extend Goals (PLAN_PHASE3 Section 0.7, 4)
ALTER TABLE goals ADD COLUMN progress_source TEXT NOT NULL DEFAULT 'manual' CHECK (progress_source IN ('manual', 'bucket', 'account'));
ALTER TABLE goals ADD COLUMN linked_account_id TEXT REFERENCES accounts(id);
ALTER TABLE goals ADD COLUMN start_date TEXT CHECK (start_date IS NULL OR start_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]');
ALTER TABLE goals ADD COLUMN essential INTEGER NOT NULL DEFAULT 0 CHECK (essential IN (0, 1));
ALTER TABLE goals ADD COLUMN notes TEXT;

-- 2. Goal Contributions (for manual goals - bucket and account goals derive them)
CREATE TABLE IF NOT EXISTS goal_contributions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    goal_id TEXT NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
    amount_paise INTEGER NOT NULL,
    occurred_on TEXT NOT NULL CHECK (occurred_on GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    source TEXT NOT NULL CHECK (source IN ('manual', 'bucket_allocation', 'account_delta')),
    ref_id TEXT,
    created_at TEXT NOT NULL CHECK (created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z')
) STRICT;

CREATE INDEX IF NOT EXISTS idx_goal_contributions_user_goal ON goal_contributions(user_id, goal_id, occurred_on);

-- 3. Commitments
CREATE TABLE IF NOT EXISTS commitments (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('outflow', 'inflow')),
    kind TEXT NOT NULL CHECK (kind IN ('fee', 'bill', 'rent', 'travel', 'allowance', 'income', 'subscription', 'emi', 'investment_contribution', 'goal_contribution', 'other')),
    category_id TEXT REFERENCES categories(id),
    amount_paise INTEGER,
    amount_min_paise INTEGER,
    amount_max_paise INTEGER,
    certainty TEXT NOT NULL CHECK (certainty IN ('firm', 'estimated')),
    schedule_kind TEXT NOT NULL CHECK (schedule_kind IN ('once', 'weekly', 'monthly', 'yearly', 'every_n_days')),
    schedule_json TEXT NOT NULL,
    start_date TEXT NOT NULL CHECK (start_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    end_date TEXT CHECK (end_date IS NULL OR end_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    recurring_series_id TEXT REFERENCES recurring_series(id),
    goal_id TEXT REFERENCES goals(id),
    bucket_id TEXT,
    source TEXT NOT NULL CHECK (source IN ('user', 'suggested')),
    status TEXT NOT NULL CHECK (status IN ('draft', 'active', 'paused', 'ended', 'rejected')),
    created_at TEXT NOT NULL CHECK (created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    updated_at TEXT NOT NULL CHECK (updated_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z')
) STRICT;

CREATE INDEX IF NOT EXISTS idx_commitments_user_status ON commitments(user_id, status);
CREATE INDEX IF NOT EXISTS idx_commitments_user_kind ON commitments(user_id, kind);

-- 4. Commitment Matches
CREATE TABLE IF NOT EXISTS commitment_matches (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    commitment_id TEXT NOT NULL REFERENCES commitments(id) ON DELETE CASCADE,
    due_date TEXT NOT NULL CHECK (due_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    txn_id TEXT NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
    match_method TEXT NOT NULL CHECK (match_method IN ('series', 'amount_date', 'manual')),
    confidence_bp INTEGER NOT NULL CHECK (confidence_bp BETWEEN 0 AND 10000),
    created_at TEXT NOT NULL CHECK (created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    UNIQUE (user_id, txn_id)
) STRICT;

CREATE INDEX IF NOT EXISTS idx_commitment_matches_commitment ON commitment_matches(commitment_id, due_date);

-- 5. Virtual Buckets (Upgraded from Phase 0 stub schema)
CREATE TABLE new_buckets (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('spending', 'goal', 'commitment', 'flexible')),
    period_policy TEXT NOT NULL CHECK (period_policy IN ('reset_monthly', 'accumulate')),
    goal_id TEXT REFERENCES goals(id),
    commitment_id TEXT REFERENCES commitments(id),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL CHECK (created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z')
) STRICT;

INSERT INTO new_buckets (id, user_id, name, kind, period_policy, goal_id, commitment_id, status, sort_order, created_at)
SELECT id, user_id, name, 'flexible', 'reset_monthly', NULL, NULL, 'active', 0,
       CASE WHEN created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z' THEN created_at ELSE strftime('%Y-%m-%dT%H:%M:%SZ', 'now') END
FROM buckets;

DROP TABLE buckets;
ALTER TABLE new_buckets RENAME TO buckets;

CREATE INDEX IF NOT EXISTS idx_buckets_user_status ON buckets(user_id, status);

-- 6. Bucket Categories (unique user_id, category_id enforces 1 spending bucket per category)
CREATE TABLE IF NOT EXISTS bucket_categories (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    bucket_id TEXT NOT NULL REFERENCES buckets(id) ON DELETE CASCADE,
    category_id TEXT NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL CHECK (created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    UNIQUE (user_id, category_id)
) STRICT;

CREATE INDEX IF NOT EXISTS idx_bucket_categories_bucket ON bucket_categories(bucket_id);

-- 7. Bucket Allocations (Append-only ledger)
CREATE TABLE IF NOT EXISTS bucket_allocations (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    bucket_id TEXT NOT NULL REFERENCES buckets(id) ON DELETE CASCADE,
    amount_paise INTEGER NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('allocate', 'release', 'reassign_in', 'reassign_out', 'rollover', 'adjust')),
    period TEXT NOT NULL CHECK (period GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]'),
    pair_id TEXT,
    source TEXT NOT NULL CHECK (source IN ('user', 'approved_draft', 'system_rollover')),
    draft_id TEXT,
    created_at TEXT NOT NULL CHECK (created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z')
) STRICT;

CREATE INDEX IF NOT EXISTS idx_bucket_allocations_bucket_period ON bucket_allocations(user_id, bucket_id, period);

-- 8. Reallocation Drafts
CREATE TABLE IF NOT EXISTS reallocation_drafts (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    from_bucket_id TEXT NOT NULL REFERENCES buckets(id),
    to_bucket_id TEXT NOT NULL REFERENCES buckets(id),
    amount_paise INTEGER NOT NULL CHECK (amount_paise > 0),
    reason_json TEXT NOT NULL,
    simulation_id TEXT REFERENCES simulations(id),
    status TEXT NOT NULL CHECK (status IN ('draft', 'approved', 'rejected', 'applied', 'expired')),
    created_at TEXT NOT NULL CHECK (created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    decided_at TEXT CHECK (decided_at IS NULL OR decided_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    applied_at TEXT CHECK (applied_at IS NULL OR applied_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z')
) STRICT;

CREATE INDEX IF NOT EXISTS idx_reallocation_drafts_user_status ON reallocation_drafts(user_id, status);

-- 9. Readiness Assessments
CREATE TABLE IF NOT EXISTS readiness_assessments (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    run_id TEXT NOT NULL,
    assessed_on TEXT NOT NULL CHECK (assessed_on GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    level TEXT NOT NULL CHECK (level IN ('not_ready', 'building', 'ready_with_conditions', 'ready', 'insufficient_data')),
    criteria_json TEXT NOT NULL,
    numbers_json TEXT NOT NULL,
    config_version TEXT NOT NULL,
    created_at TEXT NOT NULL CHECK (created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z')
) STRICT;

CREATE INDEX IF NOT EXISTS idx_readiness_user ON readiness_assessments(user_id, assessed_on);

-- 10. Contribution Plans
CREATE TABLE IF NOT EXISTS contribution_plans (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    run_id TEXT NOT NULL,
    period_from TEXT NOT NULL CHECK (period_from GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]'),
    horizon_months INTEGER NOT NULL CHECK (horizon_months BETWEEN 1 AND 24),
    waterfall_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    assumptions_json TEXT NOT NULL,
    created_at TEXT NOT NULL CHECK (created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z')
) STRICT;

CREATE INDEX IF NOT EXISTS idx_contribution_plans_user ON contribution_plans(user_id, created_at);

-- 11. Tradeoff Analyses
CREATE TABLE IF NOT EXISTS tradeoff_analyses (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    run_id TEXT NOT NULL,
    alternatives_json TEXT NOT NULL,
    results_json TEXT NOT NULL,
    assumptions_json TEXT NOT NULL,
    created_at TEXT NOT NULL CHECK (created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z')
) STRICT;

CREATE INDEX IF NOT EXISTS idx_tradeoff_analyses_user ON tradeoff_analyses(user_id, created_at);

-- 12. Behavioural Memory Items
CREATE TABLE IF NOT EXISTS memory_items (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    kind TEXT NOT NULL CHECK (kind IN ('recurring_pattern', 'contextual_exception', 'advice_feedback', 'preference', 'merchant_habit')),
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

CREATE INDEX IF NOT EXISTS idx_memory_items_user_status ON memory_items(user_id, status);
CREATE INDEX IF NOT EXISTS idx_memory_items_user_subject ON memory_items(user_id, subject_key);

-- 13. Memory Evidence
CREATE TABLE IF NOT EXISTS memory_evidence (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    memory_id TEXT NOT NULL REFERENCES memory_items(id) ON DELETE CASCADE,
    polarity TEXT NOT NULL CHECK (polarity IN ('supports', 'contradicts')),
    ref_kind TEXT NOT NULL CHECK (ref_kind IN ('txn', 'advice', 'audit_event', 'anomaly', 'investigation', 'capture_label')),
    ref_id TEXT NOT NULL,
    observed_at TEXT NOT NULL CHECK (observed_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    weight_bp INTEGER NOT NULL CHECK (weight_bp BETWEEN 0 AND 10000),
    created_at TEXT NOT NULL CHECK (created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z')
) STRICT;

CREATE INDEX IF NOT EXISTS idx_memory_evidence_memory ON memory_evidence(memory_id, polarity);

-- 14. User Preferences
CREATE TABLE IF NOT EXISTS user_preferences (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    key TEXT NOT NULL,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL CHECK (updated_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    UNIQUE (user_id, key)
) STRICT;

-- 15. Skill Runs
CREATE TABLE IF NOT EXISTS skill_runs (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    task_id TEXT NOT NULL,
    skill_name TEXT NOT NULL,
    skill_version INTEGER NOT NULL CHECK (skill_version >= 1),
    inputs_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'ok', 'failed', 'cannot_run')),
    outputs_json TEXT NOT NULL,
    started_at TEXT NOT NULL CHECK (started_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    finished_at TEXT CHECK (finished_at IS NULL OR finished_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z')
) STRICT;

CREATE INDEX IF NOT EXISTS idx_skill_runs_user_task ON skill_runs(user_id, task_id);

-- 16. Specialist Reports
CREATE TABLE IF NOT EXISTS specialist_reports (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    task_id TEXT NOT NULL,
    agent_role TEXT NOT NULL,
    sub_question_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('ok', 'partial', 'failed', 'timeout')),
    findings_json TEXT NOT NULL,
    gaps_json TEXT NOT NULL,
    error_code TEXT,
    duration_ms INTEGER NOT NULL CHECK (duration_ms >= 0),
    created_at TEXT NOT NULL CHECK (created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z')
) STRICT;

CREATE INDEX IF NOT EXISTS idx_specialist_reports_task ON specialist_reports(task_id, agent_role);

-- 17. Reflections (Reflexion-style revision history)
CREATE TABLE IF NOT EXISTS reflections (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    task_id TEXT NOT NULL,
    round INTEGER NOT NULL CHECK (round >= 0),
    critique_codes_json TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('deterministic', 'llm_critic')),
    revised INTEGER NOT NULL CHECK (revised IN (0, 1)),
    outcome TEXT NOT NULL CHECK (outcome IN ('fixed', 'unchanged', 'gave_up')),
    created_at TEXT NOT NULL CHECK (created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z')
) STRICT;

CREATE INDEX IF NOT EXISTS idx_reflections_task ON reflections(task_id, round);

-- 18. Context Manifests (audit token budgets and context inclusion)
CREATE TABLE IF NOT EXISTS context_manifests (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    call_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    purpose TEXT NOT NULL,
    budget_tokens INTEGER NOT NULL CHECK (budget_tokens >= 0),
    estimated_tokens INTEGER NOT NULL CHECK (estimated_tokens >= 0),
    included_json TEXT NOT NULL,
    excluded_json TEXT NOT NULL,
    redactions_count INTEGER NOT NULL DEFAULT 0 CHECK (redactions_count >= 0),
    prompt_version TEXT NOT NULL,
    created_at TEXT NOT NULL CHECK (created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z')
) STRICT;

CREATE INDEX IF NOT EXISTS idx_context_manifests_task ON context_manifests(task_id, purpose);

-- 19. Trace Spans (for observability)
CREATE TABLE IF NOT EXISTS trace_spans (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    trace_id TEXT NOT NULL,
    span_id TEXT NOT NULL,
    parent_span_id TEXT,
    kind TEXT NOT NULL CHECK (kind IN ('node', 'tool', 'llm', 'job', 'skill', 'specialist', 'mcp')),
    name TEXT NOT NULL,
    started_at TEXT NOT NULL CHECK (started_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    duration_ms INTEGER NOT NULL CHECK (duration_ms >= 0),
    status TEXT NOT NULL CHECK (status IN ('ok', 'error')),
    error_code TEXT,
    attrs_json TEXT NOT NULL,
    created_at TEXT NOT NULL CHECK (created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z')
) STRICT;

CREATE INDEX IF NOT EXISTS idx_trace_spans_trace ON trace_spans(trace_id, started_at);

-- 20. Scheduled Jobs (agent runtime)
CREATE TABLE IF NOT EXISTS scheduled_jobs (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    job_kind TEXT NOT NULL,
    schedule TEXT NOT NULL,
    next_run_at TEXT NOT NULL CHECK (next_run_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    lease_owner TEXT,
    lease_until TEXT CHECK (lease_until IS NULL OR lease_until GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    last_status TEXT CHECK (last_status IS NULL OR last_status IN ('ok', 'failed', 'skipped', 'dead_letter')),
    consecutive_failures INTEGER NOT NULL DEFAULT 0 CHECK (consecutive_failures >= 0),
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    updated_at TEXT NOT NULL CHECK (updated_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    UNIQUE (user_id, job_kind)
) STRICT;

CREATE INDEX IF NOT EXISTS idx_scheduled_jobs_user ON scheduled_jobs(user_id, next_run_at);

-- 21. Job Runs
CREATE TABLE IF NOT EXISTS job_runs (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    job_id TEXT NOT NULL REFERENCES scheduled_jobs(id) ON DELETE CASCADE,
    started_at TEXT NOT NULL CHECK (started_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    finished_at TEXT CHECK (finished_at IS NULL OR finished_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    status TEXT NOT NULL CHECK (status IN ('ok', 'failed', 'skipped', 'dead_letter')),
    attempt INTEGER NOT NULL CHECK (attempt >= 1),
    error_code TEXT,
    summary_json TEXT NOT NULL,
    created_at TEXT NOT NULL CHECK (created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z')
) STRICT;

CREATE INDEX IF NOT EXISTS idx_job_runs_job ON job_runs(job_id, started_at);
CREATE INDEX IF NOT EXISTS idx_job_runs_user ON job_runs(user_id, started_at);

-- 22. Feedback Stats (bounded feedback learning state)
CREATE TABLE IF NOT EXISTS feedback_stats (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    subject_kind TEXT NOT NULL CHECK (subject_kind IN ('alert_kind', 'advice_kind')),
    subject_key TEXT NOT NULL,
    alpha_milli INTEGER NOT NULL DEFAULT 2000 CHECK (alpha_milli > 0),
    beta_milli INTEGER NOT NULL DEFAULT 2000 CHECK (beta_milli > 0),
    updated_at TEXT NOT NULL CHECK (updated_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    UNIQUE (user_id, subject_kind, subject_key)
) STRICT;

CREATE INDEX IF NOT EXISTS idx_feedback_stats_user ON feedback_stats(user_id, subject_kind);
