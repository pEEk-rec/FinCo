-- Migration 003: Phase 2 Agentic Intelligence Layer schema additions (PLAN_PHASE2 Section 4)

-- 1. Agent Tasks
CREATE TABLE IF NOT EXISTS agent_tasks (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    run_id TEXT,
    raw_text TEXT NOT NULL,
    intent_json TEXT,
    status TEXT NOT NULL CHECK (status IN ('understood', 'needs_clarification', 'refused', 'planned', 'running', 'awaiting_approval', 'done', 'failed', 'stopped')),
    stop_reason TEXT CHECK (stop_reason IS NULL OR stop_reason IN ('completed', 'step_budget', 'llm_budget', 'loop_detected', 'tool_failure', 'inconclusive')),
    planner_mode TEXT NOT NULL CHECK (planner_mode IN ('deterministic', 'llm')),
    model TEXT,
    prompt_version TEXT,
    created_at TEXT NOT NULL CHECK (created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    finished_at TEXT CHECK (finished_at IS NULL OR finished_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z')
) STRICT;

CREATE INDEX IF NOT EXISTS idx_agent_tasks_user_created ON agent_tasks(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_agent_tasks_user_status ON agent_tasks(user_id, status);

-- 2. Plan Steps
CREATE TABLE IF NOT EXISTS plan_steps (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES agent_tasks(id),
    user_id TEXT NOT NULL REFERENCES users(id),
    seq INTEGER NOT NULL CHECK (seq >= 0),
    tool_name TEXT NOT NULL,
    args_json TEXT NOT NULL,
    rationale TEXT NOT NULL,
    proposed_by TEXT NOT NULL CHECK (proposed_by IN ('deterministic', 'llm')),
    status TEXT NOT NULL CHECK (status IN ('proposed', 'rejected', 'running', 'done', 'failed', 'skipped_memoized')),
    reject_reason TEXT,
    started_at TEXT CHECK (started_at IS NULL OR started_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    finished_at TEXT CHECK (finished_at IS NULL OR finished_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    UNIQUE (task_id, seq)
) STRICT;

CREATE INDEX IF NOT EXISTS idx_plan_steps_task ON plan_steps(task_id, seq);

-- 3. Goals (Upgraded from Phase 0 stub schema)
CREATE TABLE new_goals (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('savings', 'purchase', 'emergency_fund', 'other')),
    target_paise INTEGER NOT NULL CHECK (target_paise > 0),
    current_paise INTEGER NOT NULL CHECK (current_paise >= 0),
    deadline TEXT CHECK (deadline IS NULL OR deadline GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    priority INTEGER NOT NULL CHECK (priority BETWEEN 1 AND 3),
    status TEXT NOT NULL CHECK (status IN ('active', 'paused', 'done')),
    created_at TEXT NOT NULL CHECK (created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    updated_at TEXT NOT NULL CHECK (updated_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z')
) STRICT;

INSERT INTO new_goals (id, user_id, name, kind, target_paise, current_paise, deadline, priority, status, created_at, updated_at)
SELECT id, user_id, name, 'other', 1, 0, NULL, 1, 'active',
       CASE WHEN created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z' THEN created_at ELSE strftime('%Y-%m-%dT%H:%M:%SZ', 'now') END,
       CASE WHEN created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z' THEN created_at ELSE strftime('%Y-%m-%dT%H:%M:%SZ', 'now') END
FROM goals;

DROP TABLE goals;
ALTER TABLE new_goals RENAME TO goals;

CREATE INDEX idx_goals_user_status ON goals(user_id, status);

-- 4. Investigations
CREATE TABLE IF NOT EXISTS investigations (
    id TEXT PRIMARY KEY,
    task_id TEXT REFERENCES agent_tasks(id),
    user_id TEXT NOT NULL REFERENCES users(id),
    run_id TEXT,
    subject_kind TEXT NOT NULL CHECK (subject_kind IN ('anomaly', 'category_change', 'merchant_change', 'period_change')),
    subject_ref_json TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('explained', 'partially_explained', 'inconclusive', 'needs_clarification')),
    confidence_label TEXT NOT NULL CHECK (confidence_label IN ('high', 'medium', 'low')),
    explained_share_bp INTEGER NOT NULL CHECK (explained_share_bp BETWEEN 0 AND 10000),
    unexplained_paise INTEGER NOT NULL CHECK (unexplained_paise >= 0),
    rounds INTEGER NOT NULL CHECK (rounds >= 1),
    created_at TEXT NOT NULL CHECK (created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z')
) STRICT;

CREATE INDEX IF NOT EXISTS idx_investigations_user_created ON investigations(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_investigations_task ON investigations(task_id);

-- 5. Hypotheses
CREATE TABLE IF NOT EXISTS hypotheses (
    id TEXT PRIMARY KEY,
    investigation_id TEXT NOT NULL REFERENCES investigations(id),
    user_id TEXT NOT NULL REFERENCES users(id),
    code TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('supported', 'contradicted', 'untested', 'neutral')),
    score_bp INTEGER NOT NULL CHECK (score_bp BETWEEN 0 AND 10000),
    contribution_paise INTEGER NOT NULL CHECK (contribution_paise >= 0),
    UNIQUE (investigation_id, code)
) STRICT;

CREATE INDEX IF NOT EXISTS idx_hypotheses_investigation ON hypotheses(investigation_id);

-- 6. Evidence Items
CREATE TABLE IF NOT EXISTS evidence_items (
    id TEXT PRIMARY KEY,
    investigation_id TEXT NOT NULL REFERENCES investigations(id),
    user_id TEXT NOT NULL REFERENCES users(id),
    hypothesis_code TEXT NOT NULL,
    test_code TEXT NOT NULL,
    result TEXT NOT NULL CHECK (result IN ('supports', 'contradicts', 'neutral')),
    strength_bp INTEGER NOT NULL CHECK (strength_bp BETWEEN 0 AND 10000),
    numbers_json TEXT NOT NULL,
    txn_ids_json TEXT NOT NULL
) STRICT;

CREATE INDEX IF NOT EXISTS idx_evidence_investigation ON evidence_items(investigation_id);

-- 7. Simulations
CREATE TABLE IF NOT EXISTS simulations (
    id TEXT PRIMARY KEY,
    task_id TEXT REFERENCES agent_tasks(id),
    user_id TEXT NOT NULL REFERENCES users(id),
    scenario_json TEXT NOT NULL,
    baseline_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    assumptions_json TEXT NOT NULL,
    created_at TEXT NOT NULL CHECK (created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z')
) STRICT;

CREATE INDEX IF NOT EXISTS idx_simulations_user_created ON simulations(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_simulations_task ON simulations(task_id);

-- 8. Alerts
CREATE TABLE IF NOT EXISTS alerts (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    kind TEXT NOT NULL,
    subject_key TEXT NOT NULL,
    period TEXT NOT NULL,
    score_bp INTEGER NOT NULL CHECK (score_bp BETWEEN 0 AND 10000),
    severity TEXT NOT NULL CHECK (severity IN ('info', 'notice', 'warning', 'critical')),
    components_json TEXT NOT NULL,
    why_text TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('open', 'acknowledged', 'dismissed', 'snoozed')),
    snoozed_until TEXT CHECK (snoozed_until IS NULL OR snoozed_until GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    dedup_key TEXT NOT NULL,
    run_id TEXT,
    created_at TEXT NOT NULL CHECK (created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    decided_at TEXT CHECK (decided_at IS NULL OR decided_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    dismiss_reason TEXT
) STRICT;

CREATE INDEX IF NOT EXISTS idx_alerts_user_status ON alerts(user_id, status);
CREATE INDEX IF NOT EXISTS idx_alerts_user_dedup ON alerts(user_id, dedup_key);

-- 9. Alert Preferences
CREATE TABLE IF NOT EXISTS alert_preferences (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    category_id TEXT,
    kind TEXT,
    min_severity TEXT NOT NULL CHECK (min_severity IN ('info', 'notice', 'warning', 'critical')),
    muted INTEGER NOT NULL CHECK (muted IN (0, 1)),
    max_open_alerts INTEGER CHECK (max_open_alerts IS NULL OR max_open_alerts > 0),
    FOREIGN KEY (user_id, category_id) REFERENCES categories(user_id, id)
) STRICT;

CREATE INDEX IF NOT EXISTS idx_alert_preferences_user ON alert_preferences(user_id);

-- 10. Extend advice_items with explanation fields
-- Note: SQLite does not support IF NOT EXISTS in ALTER TABLE ADD COLUMN,
-- so we execute column additions directly.
ALTER TABLE advice_items ADD COLUMN origin TEXT NOT NULL DEFAULT 'monthly_review' CHECK (origin IN ('monthly_review', 'investigation', 'whatif', 'alert', 'goal'));
ALTER TABLE advice_items ADD COLUMN calculations_json TEXT;
ALTER TABLE advice_items ADD COLUMN tools_used_json TEXT;
ALTER TABLE advice_items ADD COLUMN memories_json TEXT;
ALTER TABLE advice_items ADD COLUMN confidence_label TEXT CHECK (confidence_label IS NULL OR confidence_label IN ('high', 'medium', 'low'));
ALTER TABLE advice_items ADD COLUMN simulation_id TEXT REFERENCES simulations(id);
ALTER TABLE advice_items ADD COLUMN task_id TEXT REFERENCES agent_tasks(id);
