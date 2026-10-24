"""
Database schema, constraint, user isolation, and migration tests for Phase 3 (PLAN_PHASE3 Stage 3.1).
"""

import sqlite3
from pathlib import Path

import pytest

from copilot.db.connection import get_connection, init_db
from copilot.db.repo_phase3 import (
    forget_memory_item,
    get_bucket_for_category,
    get_commitment,
    get_feedback_stat,
    get_memory_item,
    get_reallocation_draft,
    get_user_preference,
    insert_bucket,
    insert_bucket_allocation,
    insert_commitment,
    insert_memory_evidence,
    insert_memory_item,
    insert_reallocation_draft,
    insert_trace_span,
    list_bucket_allocations,
    list_commitments,
    list_memory_evidence,
    list_memory_items,
    list_scheduled_jobs,
    list_trace_spans,
    map_bucket_category,
    set_user_preference,
    update_commitment_status,
    update_reallocation_draft_status,
    upsert_feedback_stat,
    upsert_scheduled_job,
)
from copilot.models.phase3 import (
    Bucket,
    BucketAllocation,
    Commitment,
    MemoryEvidence,
    MemoryItem,
    ReallocationDraft,
    ScheduledJob,
    Span,
)

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "src" / "copilot" / "db" / "migrations"


@pytest.fixture
def conn():
    c = get_connection(":memory:")
    init_db(c)
    # Seed users
    c.execute("INSERT INTO users (id, created_at) VALUES ('u1', '2024-01-01T00:00:00Z')")
    c.execute("INSERT INTO users (id, created_at) VALUES ('u2', '2024-01-01T00:00:00Z')")
    # Seed accounts
    c.execute(
        "INSERT INTO accounts (id, user_id, name, opening_balance_paise, created_at) VALUES ('acc1', 'u1', 'Checking', 10000000, '2024-01-01T00:00:00Z')"
    )
    c.execute(
        "INSERT INTO accounts (id, user_id, name, opening_balance_paise, created_at) VALUES ('acc2', 'u2', 'Checking', 5000000, '2024-01-01T00:00:00Z')"
    )
    # Seed categories
    c.execute(
        "INSERT INTO categories (id, user_id, name, created_at) VALUES ('dining', 'u1', 'Dining', '2024-01-01T00:00:00Z')"
    )
    c.execute(
        "INSERT INTO categories (id, user_id, name, created_at) VALUES ('groceries', 'u1', 'Groceries', '2024-01-01T00:00:00Z')"
    )
    c.execute(
        "INSERT INTO categories (id, user_id, name, created_at) VALUES ('rent', 'u1', 'Rent', '2024-01-01T00:00:00Z')"
    )
    c.execute(
        "INSERT INTO categories (id, user_id, name, created_at) VALUES ('dining_u2', 'u2', 'Dining', '2024-01-01T00:00:00Z')"
    )
    yield c
    c.close()


def test_migration_004_preserves_phase2_data():
    """Verify that migration 004 applies to an existing Phase 2 database preserving all data."""
    c = get_connection(":memory:")
    # Run only migrations 001, 002, 003
    for m in ["001_initial.sql", "002_phase1_schema.sql", "003_phase2_schema.sql"]:
        script = (MIGRATIONS_DIR / m).read_text(encoding="utf-8")
        c.executescript(script)

    c.execute("INSERT INTO users (id, created_at) VALUES ('u1', '2024-01-01T00:00:00Z')")
    c.execute(
        """
        INSERT INTO goals (id, user_id, name, kind, target_paise, current_paise, deadline, priority, status, created_at, updated_at)
        VALUES ('g1', 'u1', 'Emergency Fund', 'emergency_fund', 50000000, 10000000, '2024-12-31', 1, 'active', '2024-01-01T00:00:00Z', '2024-01-01T00:00:00Z')
        """
    )
    c.execute(
        "INSERT INTO buckets (id, user_id, name, created_at) VALUES ('b1', 'u1', 'Old Bucket', '2024-01-01T00:00:00Z')"
    )

    # Now apply migration 004
    script_004 = (MIGRATIONS_DIR / "004_phase3_schema.sql").read_text(encoding="utf-8")
    c.executescript(script_004)

    # Goal data preserved with safe defaults
    goal_row = c.execute("SELECT * FROM goals WHERE id = 'g1'").fetchone()
    assert goal_row["name"] == "Emergency Fund"
    assert goal_row["target_paise"] == 50000000
    assert goal_row["progress_source"] == "manual"
    assert goal_row["essential"] == 0
    assert goal_row["linked_account_id"] is None

    # Bucket upgraded from stub schema with data preserved
    bucket_row = c.execute("SELECT * FROM buckets WHERE id = 'b1'").fetchone()
    assert bucket_row["name"] == "Old Bucket"
    assert bucket_row["kind"] == "flexible"
    assert bucket_row["period_policy"] == "reset_monthly"
    assert bucket_row["status"] == "active"
    c.close()


def test_commitments_crud_and_user_isolation(conn):
    """Verify commitments CRUD, constraints, and strict user isolation."""
    c1 = Commitment(
        id="c1",
        user_id="u1",
        name="Flat Rent",
        direction="outflow",
        kind="rent",
        category_id="rent",
        amount_paise=2500000,
        certainty="firm",
        schedule_kind="monthly",
        schedule_json={"day": 5},
        start_date="2024-01-01",
        source="user",
        status="active",
        created_at="2024-01-01T00:00:00Z",
        updated_at="2024-01-01T00:00:00Z",
    )
    insert_commitment(conn, c1)

    fetched = get_commitment(conn, "u1", "c1")
    assert fetched is not None
    assert fetched.name == "Flat Rent"
    assert fetched.schedule_json == {"day": 5}

    # u2 cannot see u1's commitment
    assert get_commitment(conn, "u2", "c1") is None
    assert len(list_commitments(conn, "u2")) == 0

    # Update status
    assert update_commitment_status(conn, "u1", "c1", "paused", "2024-02-01T00:00:00Z") is True
    paused = get_commitment(conn, "u1", "c1")
    assert paused.status == "paused"

    # Constraint check: invalid kind fails
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO commitments (id, user_id, name, direction, kind, certainty, schedule_kind, schedule_json, start_date, source, status, created_at, updated_at)
            VALUES ('c_bad', 'u1', 'Bad', 'outflow', 'invalid_kind', 'firm', 'monthly', '{}', '2024-01-01', 'user', 'active', '2024-01-01T00:00:00Z', '2024-01-01T00:00:00Z')
            """
        )


def test_bucket_category_uniqueness_and_ledger(conn):
    """Verify virtual buckets, 1-to-1 category mapping per user, and allocation ledger."""
    b1 = Bucket(
        id="b1",
        user_id="u1",
        name="Dining Out",
        kind="spending",
        period_policy="reset_monthly",
        status="active",
        sort_order=1,
        created_at="2024-01-01T00:00:00Z",
    )
    insert_bucket(conn, b1)

    # Map dining -> b1
    map_bucket_category(conn, "u1", "b1", "dining", "2024-01-01T00:00:00Z")
    assert get_bucket_for_category(conn, "u1", "dining") == "b1"

    # Map dining -> b2 for u1 updates the mapping (at most 1 bucket per category)
    b2 = Bucket(
        id="b2",
        user_id="u1",
        name="Food Total",
        kind="spending",
        period_policy="reset_monthly",
        status="active",
        sort_order=2,
        created_at="2024-01-01T00:00:00Z",
    )
    insert_bucket(conn, b2)
    map_bucket_category(conn, "u1", "b2", "dining", "2024-01-02T00:00:00Z")
    assert get_bucket_for_category(conn, "u1", "dining") == "b2"

    # Category mapping for u1 does not affect u2
    assert get_bucket_for_category(conn, "u2", "dining") is None

    # Ledger allocations
    alloc = BucketAllocation(
        id="ba1",
        user_id="u1",
        bucket_id="b1",
        amount_paise=1500000,
        kind="allocate",
        period="2024-03",
        source="user",
        created_at="2024-03-01T00:00:00Z",
    )
    insert_bucket_allocation(conn, alloc)
    allocs = list_bucket_allocations(conn, "u1", bucket_id="b1")
    assert len(allocs) == 1
    assert allocs[0].amount_paise == 1500000
    assert len(list_bucket_allocations(conn, "u2")) == 0


def test_reallocation_draft_lifecycle(conn):
    """Verify reallocation drafts creation, decide, apply, and user isolation."""
    b1 = Bucket(
        id="b1",
        user_id="u1",
        name="B1",
        kind="spending",
        period_policy="reset_monthly",
        status="active",
        created_at="2024-01-01T00:00:00Z",
    )
    b2 = Bucket(
        id="b2",
        user_id="u1",
        name="B2",
        kind="spending",
        period_policy="reset_monthly",
        status="active",
        created_at="2024-01-01T00:00:00Z",
    )
    insert_bucket(conn, b1)
    insert_bucket(conn, b2)

    draft = ReallocationDraft(
        id="rd1",
        user_id="u1",
        from_bucket_id="b1",
        to_bucket_id="b2",
        amount_paise=500000,
        reason_json={"reason": "Cover overspend in B2"},
        status="draft",
        created_at="2024-03-15T10:00:00Z",
    )
    insert_reallocation_draft(conn, draft)

    fetched = get_reallocation_draft(conn, "u1", "rd1")
    assert fetched is not None
    assert fetched.status == "draft"
    assert get_reallocation_draft(conn, "u2", "rd1") is None

    # Decide
    update_reallocation_draft_status(
        conn, "u1", "rd1", status="approved", decided_at="2024-03-15T10:05:00Z"
    )
    assert get_reallocation_draft(conn, "u1", "rd1").status == "approved"

    # Apply
    update_reallocation_draft_status(
        conn, "u1", "rd1", status="applied", applied_at="2024-03-15T10:06:00Z"
    )
    assert get_reallocation_draft(conn, "u1", "rd1").status == "applied"


def test_behavioural_memory_and_forgetting(conn):
    """Verify memory items, evidence rows, confidence updates, and forgetting."""
    item = MemoryItem(
        id="mem1",
        user_id="u1",
        kind="contextual_exception",
        subject_key="category:dining",
        statement_json={"category": "dining", "period": "2024-03", "reason": "festival"},
        source="observed",
        status="candidate",
        prior_bp=5000,
        created_at="2024-03-15T00:00:00Z",
    )
    insert_memory_item(conn, item)

    evidence = MemoryEvidence(
        id="ev1",
        user_id="u1",
        memory_id="mem1",
        polarity="supports",
        ref_kind="advice",
        ref_id="adv_123",
        observed_at="2024-03-15T12:00:00Z",
        weight_bp=2000,
        created_at="2024-03-15T12:00:00Z",
    )
    insert_memory_evidence(conn, evidence)

    fetched = get_memory_item(conn, "u1", "mem1")
    assert fetched is not None
    assert fetched.statement_json["reason"] == "festival"
    assert fetched.last_evidence_at == "2024-03-15T12:00:00Z"

    ev_list = list_memory_evidence(conn, "u1", "mem1")
    assert len(ev_list) == 1
    assert ev_list[0].weight_bp == 2000

    # User isolation
    assert get_memory_item(conn, "u2", "mem1") is None
    assert len(list_memory_items(conn, "u2")) == 0

    # Forgetting rule (PLAN_PHASE3 5.8): statement_json cleared to empty dict, evidence deleted, status = 'forgotten'
    assert forget_memory_item(conn, "u1", "mem1") is True
    forgotten = get_memory_item(conn, "u1", "mem1")
    assert forgotten.status == "forgotten"
    assert forgotten.statement_json == {}
    assert len(list_memory_evidence(conn, "u1", "mem1")) == 0


def test_user_preferences_and_feedback_stats(conn):
    """Verify user preferences upsert and feedback stats."""
    set_user_preference(
        conn,
        "u1",
        "waterfall_order",
        ["firm_commitments", "emergency_fund", "goals"],
        "2024-03-15T00:00:00Z",
    )
    pref = get_user_preference(conn, "u1", "waterfall_order")
    assert pref == ["firm_commitments", "emergency_fund", "goals"]
    assert get_user_preference(conn, "u2", "waterfall_order") is None

    # Feedback stat upsert
    upsert_feedback_stat(
        conn,
        "u1",
        "alert_kind",
        "dining_warning",
        alpha_milli=2500,
        beta_milli=1800,
        updated_at="2024-03-15T00:00:00Z",
    )
    stat = get_feedback_stat(conn, "u1", "alert_kind", "dining_warning")
    assert stat is not None
    assert stat.alpha_milli == 2500
    assert stat.beta_milli == 1800


def test_observability_spans_and_scheduled_jobs(conn):
    """Verify trace spans, scheduled jobs and job runs."""
    span = Span(
        id="sp1",
        user_id="u1",
        trace_id="tr_101",
        span_id="sp_1",
        kind="tool",
        name="get_calendar",
        started_at="2024-03-15T00:00:00Z",
        duration_ms=42,
        status="ok",
        attrs={"horizon_days": 60},
        created_at="2024-03-15T00:00:00Z",
    )
    insert_trace_span(conn, span)
    spans = list_trace_spans(conn, "u1", "tr_101")
    assert len(spans) == 1
    assert spans[0].attrs["horizon_days"] == 60

    # Scheduled job upsert
    job = ScheduledJob(
        id="job1",
        user_id="u1",
        job_kind="rollover_buckets",
        schedule="daily@00:05",
        next_run_at="2024-03-16T00:05:00Z",
        enabled=True,
        updated_at="2024-03-15T00:00:00Z",
    )
    upsert_scheduled_job(conn, job)
    jobs = list_scheduled_jobs(conn, "u1")
    assert len(jobs) >= 1
    assert any(j.job_kind == "rollover_buckets" for j in jobs)
    assert len(list_scheduled_jobs(conn, "u2")) == 0
