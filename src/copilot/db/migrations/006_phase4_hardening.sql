-- Phase 4 hardening (PLAN_PHASE4 stage 4.13).
-- One set of weekly offers per user and week, whichever runner gets there first. Two runners
-- of the weekly job used to each insert a full set; this makes the second one fail cleanly.
CREATE UNIQUE INDEX IF NOT EXISTS idx_offers_user_week_rank ON offers(user_id, week_start, rank);
