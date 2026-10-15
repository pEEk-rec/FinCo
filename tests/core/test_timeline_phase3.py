"""
Tests for Activity Timeline Phase 3 Additions and Forgotten Memory Privacy (Stage 3.10 & Section 5.10).
"""


import pytest

from copilot.core.timeline import build_timeline
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_account, insert_user
from copilot.db.repo_phase3 import (
    insert_bucket,
    insert_commitment,
    insert_contribution_plan,
    insert_memory_item,
    insert_readiness_assessment,
    insert_reallocation_draft,
    insert_tradeoff_analysis,
)
from copilot.models.domain import Account, User
from copilot.models.phase3 import (
    Bucket,
    Commitment,
    ContributionPlan,
    ContributionPlanStep,
    MemoryItem,
    Readiness,
    ReadinessCriterion,
    ReallocationDraft,
    TradeoffResult,
)


@pytest.fixture
def conn():
    c = get_connection(":memory:")
    init_db(c)
    yield c
    c.close()


def test_timeline_phase3_entries_and_forgotten_memory_privacy(conn):
    """Verify timeline renders Phase 3 entities and strictly hides forgotten memory content."""
    user_id = "u_timeline"
    insert_user(conn, User(id=user_id, created_at="2026-01-01T00:00:00Z"))
    insert_account(
        conn,
        Account(
            id="a1",
            user_id=user_id,
            name="Checking",
            opening_balance_paise=10_000_000,
            created_at="2026-01-01T00:00:00Z",
        ),
    )

    # 1. Commitment
    insert_commitment(
        conn,
        Commitment(
            id="c_rent",
            user_id=user_id,
            name="House Rent",
            direction="outflow",
            kind="rent",
            amount_paise=3_000_000,
            certainty="firm",
            schedule_kind="monthly",
            schedule_json={"day": 5},
            start_date="2026-01-01",
            status="active",
            created_at="2026-10-02T10:00:00Z",
            updated_at="2026-10-02T10:00:00Z",
        ),
    )

    # 2. Reallocation Draft (draft -> pending approval)
    insert_bucket(
        conn,
        Bucket(
            id="b_groceries",
            user_id=user_id,
            name="Groceries",
            kind="spending",
            period_policy="reset_monthly",
            status="active",
            sort_order=1,
            created_at="2026-10-01T00:00:00Z",
        ),
    )
    insert_bucket(
        conn,
        Bucket(
            id="b_dining",
            user_id=user_id,
            name="Dining",
            kind="spending",
            period_policy="reset_monthly",
            status="active",
            sort_order=2,
            created_at="2026-10-01T00:00:00Z",
        ),
    )
    insert_reallocation_draft(
        conn,
        ReallocationDraft(
            id="rd_01",
            user_id=user_id,
            from_bucket_id="b_dining",
            to_bucket_id="b_groceries",
            amount_paise=500_000,
            reason_json={"reason": "Cover grocery deficit"},
            status="draft",
            created_at="2026-10-03T11:00:00Z",
        ),
    )

    # 3. Readiness Assessment
    insert_readiness_assessment(
        conn,
        user_id,
        Readiness(
            run_id="run_rd_1",
            assessed_on="2026-10-04",
            level="ready_with_conditions",
            criteria=[
                ReadinessCriterion(
                    name="Enough History",
                    status="pass",
                    value_text="3 months",
                    threshold_text="3 months",
                    what_would_change_it="Needs 3 months of data",
                )
            ],
            numbers={"essential_monthly_spend_paise": 2_000_000},
            config_version="1.0",
        ),
    )

    # 4. Contribution Plan
    insert_contribution_plan(
        conn,
        user_id,
        ContributionPlan(
            run_id="run_cp_1",
            period_from="2026-10",
            horizon_months=6,
            waterfall_order=["firm_commitments"],
            steps=[
                ContributionPlanStep(
                    step_name="firm_commitments",
                    needed_paise=1000000,
                    funded_expected_paise=1000000,
                    funded_low_paise=1000000,
                    shortfall_paise=0,
                    verdict="fits",
                )
            ],
            assumptions={"notes": "Run-rate sustained"},
        ),
    )

    # 5. Tradeoff Analysis
    insert_tradeoff_analysis(
        conn,
        user_id,
        TradeoffResult(
            run_id="run_to_1",
            alternatives=[],
            best_alternative_name=None,
            assumptions={},
        ),
    )

    # 6. Active Memory Item
    insert_memory_item(
        conn,
        MemoryItem(
            id="mem_active",
            user_id=user_id,
            kind="recurring_pattern",
            subject_key="category:dining",
            statement_json={"pattern": "weekend_heavy"},
            source="observed",
            status="active",
            prior_bp=8000,
            created_at="2026-10-07T12:00:00Z",
        ),
    )

    # 7. Forgotten Memory Item (Critical check: content must NEVER appear)
    insert_memory_item(
        conn,
        MemoryItem(
            id="mem_forgotten",
            user_id=user_id,
            kind="contextual_exception",
            subject_key="category:dining",
            statement_json={},  # cleared statement per ADR and PLAN_PHASE3 Section 4
            source="observed",
            status="forgotten",
            prior_bp=0,
            created_at="2026-10-08T14:00:00Z",
        ),
    )

    # Build timeline
    timeline = build_timeline(conn, user_id)

    kinds = [e.kind for e in timeline.entries]
    assert "commitment" in kinds
    assert "approval_pending" in kinds
    assert "readiness" in kinds
    assert "contribution_plan" in kinds
    assert "tradeoff" in kinds
    assert "memory" in kinds

    # Pending approvals check
    assert len(timeline.pending_approvals) >= 1
    pending_draft = [e for e in timeline.pending_approvals if e.ref.get("draft_id") == "rd_01"]
    assert len(pending_draft) == 1
    assert pending_draft[0].title == "Pending Reallocation Draft"

    # Forgotten memory verification
    forgotten_entries = [e for e in timeline.entries if e.ref.get("memory_id") == "mem_forgotten"]
    assert len(forgotten_entries) == 1
    f_entry = forgotten_entries[0]
    assert f_entry.title == "Memory Item Forgotten"
    assert f_entry.detail == "Memory item was forgotten at user request."
    assert "statement_json" not in f_entry.detail
    assert "pattern" not in f_entry.detail
    assert f_entry.status == "forgotten"
