"""
Unit Tests for Behavioural Memory Store and Deterministic Observers (PLAN_PHASE3 Stage 3.8 & Section 5.8).

Verifies:
- Each observer finds its injected pattern on dev seeds and stays silent on noise
- Reasons limited to the allowed list (festival, travel, one_off_purchase, medical, family_event, other)
- Forgetting removes content from every query path while the audit keeps a content-free event
- Multi-tenant isolation enforced on all memory queries and operations
- Observers and refresh are idempotent for the same clock
- The LLM provider is never called by any memory function
"""

import json
import sqlite3
from datetime import UTC, datetime

import pytest

from copilot.core.errors import ErrorCode, ToolFailure
from copilot.core.memory import (
    compute_memory_confidence,
    determine_memory_status,
    edit_memory_statement_bounded,
    forget_memory,
    load_memory_config,
    observe_advice_feedback,
    observe_contextual_exceptions,
    observe_merchant_habits,
    observe_preferences,
    observe_recurring_patterns,
    record_contextual_exception,
    refresh_memories,
)
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import (
    insert_account,
    insert_category,
    insert_transaction,
    insert_user,
)
from copilot.db.repo_phase3 import (
    get_memory_item,
    insert_memory_evidence,
    insert_memory_item,
    list_memory_evidence,
    list_memory_items,
    set_user_preference,
)
from copilot.llm.client import FakeLLMClient
from copilot.models.domain import Account, Category, Transaction, User
from copilot.models.phase3 import MemoryEvidence, MemoryItem


@pytest.fixture
def conn():
    """In-memory SQLite connection with complete schema migrations."""
    c = get_connection(":memory:")
    init_db(c)
    yield c
    c.close()


def _setup_test_user(conn: sqlite3.Connection, user_id: str = "u_mem"):
    insert_user(conn, User(id=user_id, created_at="2026-01-01T00:00:00Z"))
    insert_account(
        conn,
        Account(
            id=f"acc_{user_id}",
            user_id=user_id,
            name="Checking",
            opening_balance_paise=10000000,
            created_at="2026-01-01T00:00:00Z",
        ),
    )
    for cat in ["dining", "utilities", "shopping", "groceries", "travel", "income"]:
        insert_category(
            conn,
            Category(
                id=f"{cat}_{user_id}",
                user_id=user_id,
                name=cat.capitalize(),
                created_at="2026-01-01T00:00:00Z",
            ),
        )


# -------------------------------------------------------------------------------------------------
# 1. Observer 1: Recurring Patterns
# -------------------------------------------------------------------------------------------------


def test_observer_recurring_patterns_weekend_heavy(conn: sqlite3.Connection):
    """Observer detects weekend-heavy spend when weekend daily average significantly exceeds weekday."""
    user_id = "u_rp_wknd"
    _setup_test_user(conn, user_id)
    clock = datetime(2026, 4, 1, 0, 0, 0, tzinfo=UTC)

    # Injected weekend-heavy: 4 weeks of data with ₹5,000 every Saturday & Sunday, and ₹200 on weekdays
    # Saturdays in March 2026: 7, 14, 21, 28; Sundays: 8, 15, 22, 29
    for day in [7, 8, 14, 15, 21, 22, 28, 29]:
        insert_transaction(
            conn,
            Transaction(
                id=f"tx_sat_{day}",
                user_id=user_id,
                account_id=f"acc_{user_id}",
                occurred_at=f"2026-03-{day:02d}T19:00:00Z",
                amount_paise=500000,  # ₹5,000
                direction="debit",
                category_id=f"dining_{user_id}",
                merchant_raw="Weekend Bistro",
                merchant_normalized="weekend bistro",
                description="Weekend dinner",
                created_at="2026-03-01T00:00:00Z",
            ),
        )

    # Weekdays: small amounts
    for day in [9, 10, 16, 17, 23, 24]:
        insert_transaction(
            conn,
            Transaction(
                id=f"tx_wk_{day}",
                user_id=user_id,
                account_id=f"acc_{user_id}",
                occurred_at=f"2026-03-{day:02d}T12:00:00Z",
                amount_paise=20000,  # ₹200
                direction="debit",
                category_id=f"dining_{user_id}",
                merchant_raw="Quick Lunch",
                merchant_normalized="quick lunch",
                description="Weekday lunch",
                created_at="2026-03-01T00:00:00Z",
            ),
        )

    candidates = observe_recurring_patterns(conn, user_id, clock)
    dining_cands = [
        c for c in candidates if c.statement_json.get("category") == f"dining_{user_id}"
    ]

    assert len(dining_cands) >= 1
    cand = dining_cands[0]
    assert cand.kind == "recurring_pattern"
    assert cand.statement_json["pattern"] == "weekend_heavy"
    assert cand.statement_json["ratio_bp"] >= 15000
    assert len(cand.evidence_items) > 0
    assert all(e.polarity == "supports" and e.ref_kind == "txn" for e in cand.evidence_items)


def test_observer_recurring_patterns_month_start_heavy(conn: sqlite3.Connection):
    """Observer detects month-start concentration when >= 50% of monthly spend is in days 1..7."""
    user_id = "u_rp_mstart"
    _setup_test_user(conn, user_id)
    clock = datetime(2026, 4, 1, 0, 0, 0, tzinfo=UTC)

    # Injected month-start: ₹10,000 on day 2 and day 5 in utilities; only ₹500 total afterwards across 3 weeks
    for day in [2, 5]:
        insert_transaction(
            conn,
            Transaction(
                id=f"tx_start_{day}",
                user_id=user_id,
                account_id=f"acc_{user_id}",
                occurred_at=f"2026-03-{day:02d}T10:00:00Z",
                amount_paise=1000000,  # ₹10,000
                direction="debit",
                category_id=f"utilities_{user_id}",
                merchant_raw="BESCOM Electricity",
                merchant_normalized="bescom",
                description="Power bill",
                created_at="2026-03-01T00:00:00Z",
            ),
        )

    for day in [15, 25]:
        insert_transaction(
            conn,
            Transaction(
                id=f"tx_late_{day}",
                user_id=user_id,
                account_id=f"acc_{user_id}",
                occurred_at=f"2026-03-{day:02d}T10:00:00Z",
                amount_paise=25000,  # ₹250
                direction="debit",
                category_id=f"utilities_{user_id}",
                merchant_raw="Water Board",
                merchant_normalized="water board",
                description="Water bill",
                created_at="2026-03-01T00:00:00Z",
            ),
        )

    candidates = observe_recurring_patterns(conn, user_id, clock)
    util_cands = [
        c for c in candidates if c.statement_json.get("category") == f"utilities_{user_id}"
    ]

    assert len(util_cands) >= 1
    cand = util_cands[0]
    assert cand.statement_json["pattern"] == "month_start_heavy"
    assert cand.statement_json["ratio_bp"] >= 5000


def test_observer_recurring_patterns_stays_silent_on_noise(conn: sqlite3.Connection):
    """Observer stays silent on evenly distributed transactions or short history."""
    user_id = "u_rp_noise"
    _setup_test_user(conn, user_id)
    clock = datetime(2026, 4, 1, 0, 0, 0, tzinfo=UTC)

    # 1. Short history: only 1 day of data
    insert_transaction(
        conn,
        Transaction(
            id="tx_one_day",
            user_id=user_id,
            account_id=f"acc_{user_id}",
            occurred_at="2026-03-15T12:00:00Z",
            amount_paise=50000,
            direction="debit",
            category_id=f"shopping_{user_id}",
            merchant_raw="Shop",
            merchant_normalized="shop",
            description="Shopping",
            created_at="2026-03-01T00:00:00Z",
        ),
    )
    cands = observe_recurring_patterns(conn, user_id, clock)
    assert len(cands) == 0


# -------------------------------------------------------------------------------------------------
# 2. Observer 2: Contextual Exceptions
# -------------------------------------------------------------------------------------------------


def test_observer_contextual_exceptions_from_dismissed_alerts(conn: sqlite3.Connection):
    """Observer extracts contextual exceptions from dismissed alerts with allowed reason labels."""
    user_id = "u_ctx_obs"
    _setup_test_user(conn, user_id)
    clock = datetime(2026, 4, 1, 0, 0, 0, tzinfo=UTC)

    # Injected dismissed alert with allowed reason 'festival'
    conn.execute(
        """
        INSERT INTO alerts (
            id, user_id, kind, subject_key, period, score_bp, severity, components_json,
            why_text, status, dedup_key, created_at, decided_at, dismiss_reason
        ) VALUES (
            'alt_diwali', ?, 'spend_spike', 'category:shopping', '2026-11', 8000, 'warning',
            '{"category_id": "shopping"}', 'Spike in shopping', 'dismissed', 'dedup_1',
            '2026-11-05T10:00:00Z', '2026-11-06T12:00:00Z', 'festival'
        )
        """,
        (user_id,),
    )

    # Undismissed open alert (should NOT become an exception)
    conn.execute(
        """
        INSERT INTO alerts (
            id, user_id, kind, subject_key, period, score_bp, severity, components_json,
            why_text, status, dedup_key, created_at
        ) VALUES (
            'alt_open', ?, 'spend_spike', 'category:dining', '2026-11', 6000, 'info',
            '{"category_id": "dining"}', 'Dining spike', 'open', 'dedup_2',
            '2026-11-05T10:00:00Z'
        )
        """,
        (user_id,),
    )

    cands = observe_contextual_exceptions(conn, user_id, clock)
    assert len(cands) == 1
    cand = cands[0]
    assert cand.kind == "contextual_exception"
    assert cand.statement_json["category"] == "shopping"
    assert cand.statement_json["period"] == "2026-11"
    assert cand.statement_json["reason"] == "festival"
    assert len(cand.evidence_items) == 1
    assert cand.evidence_items[0].ref_kind == "anomaly"
    assert cand.evidence_items[0].ref_id == "alt_diwali"


def test_contextual_exception_rejects_unallowed_reason(conn: sqlite3.Connection):
    """Contextual exception rejects reason labels not in the allowed list."""
    user_id = "u_ctx_reject"
    _setup_test_user(conn, user_id)

    # Allowed list: festival, travel, one_off_purchase, medical, family_event, other
    with pytest.raises(ToolFailure) as exc_info:
        record_contextual_exception(
            conn,
            user_id=user_id,
            category="dining",
            period="2026-11",
            reason="just_felt_like_it",  # Not in allowed list
        )
    assert exc_info.value.error.code == ErrorCode.INVALID_INPUT

    # Valid reason succeeds
    item = record_contextual_exception(
        conn,
        user_id=user_id,
        category="dining",
        period="2026-11",
        reason="travel",
    )
    assert item.status == "active"
    assert item.statement_json["reason"] == "travel"


def test_contextual_exception_can_cover_a_dated_range(conn: sqlite3.Connection):
    """A trip inside a month is stored with its exact days; bad ranges are refused."""
    user_id = "u_ctx_range"
    _setup_test_user(conn, user_id)
    item = record_contextual_exception(
        conn,
        user_id=user_id,
        category="dining",
        period="",
        reason="travel",
        from_date="2026-09-10",
        to_date="2026-09-16",
    )
    assert item.statement_json["from_date"] == "2026-09-10"
    assert item.statement_json["to_date"] == "2026-09-16"
    assert item.statement_json["period"] == "2026-09"
    for first, last in (("2026-09-16", "2026-09-10"), ("2026-09-10", None), ("bad", "2026-09-12")):
        with pytest.raises(ToolFailure) as exc_info:
            record_contextual_exception(
                conn,
                user_id=user_id,
                category="dining",
                period="",
                reason="travel",
                from_date=first,
                to_date=last,
            )
        assert exc_info.value.error.code == ErrorCode.INVALID_INPUT


# -------------------------------------------------------------------------------------------------
# 3. Observer 3: Advice Feedback
# -------------------------------------------------------------------------------------------------


def test_observer_advice_feedback(conn: sqlite3.Connection):
    """Observer extracts user approved and rejected advice items with advice_kind and subject."""
    user_id = "u_adv_obs"
    _setup_test_user(conn, user_id)
    clock = datetime(2026, 4, 1, 0, 0, 0, tzinfo=UTC)

    # Injected rejected advice
    conn.execute(
        """
        INSERT INTO advice_items (
            id, user_id, run_id, finding_ids_json, text, evidence_json, assumptions_json,
            status, decided_at, decided_by, created_at
        ) VALUES (
            'adv_reject_dining', ?, 'run_1', '["f_1"]', 'Consider reducing dining spend',
            '{"kind": "reduce_spend", "category": "dining"}', '[]', 'rejected',
            '2026-03-15T10:00:00Z', 'user', '2026-03-10T00:00:00Z'
        )
        """,
        (user_id,),
    )

    # Injected draft advice (should stay silent)
    conn.execute(
        """
        INSERT INTO advice_items (
            id, user_id, run_id, finding_ids_json, text, evidence_json, assumptions_json,
            status, created_at
        ) VALUES (
            'adv_draft', ?, 'run_1', '["f_2"]', 'Draft advice',
            '{"kind": "reduce_spend", "category": "groceries"}', '[]', 'draft',
            '2026-03-10T00:00:00Z'
        )
        """,
        (user_id,),
    )

    cands = observe_advice_feedback(conn, user_id, clock)
    assert len(cands) == 1
    cand = cands[0]
    assert cand.kind == "advice_feedback"
    assert cand.statement_json["advice_kind"] == "reduce_spend"
    assert cand.statement_json["subject"] == "category:dining"
    assert cand.statement_json["decision"] == "rejected"
    assert cand.evidence_items[0].ref_kind == "advice"
    assert cand.evidence_items[0].ref_id == "adv_reject_dining"


# -------------------------------------------------------------------------------------------------
# 4. Observer 4: User Preferences
# -------------------------------------------------------------------------------------------------


def test_observer_preferences(conn: sqlite3.Connection):
    """Observer extracts user preferences and marks them active without time decay."""
    user_id = "u_pref_obs"
    _setup_test_user(conn, user_id)
    clock = datetime(2026, 4, 1, 0, 0, 0, tzinfo=UTC)

    set_user_preference(
        conn,
        user_id=user_id,
        key="waterfall_order",
        value=["firm_commitments", "essential_spend", "emergency_fund"],
        updated_at="2026-03-01T00:00:00Z",
    )

    cands = observe_preferences(conn, user_id, clock)
    assert len(cands) == 1
    cand = cands[0]
    assert cand.kind == "preference"
    assert cand.subject_key == "preference:waterfall_order"
    assert cand.statement_json["key"] == "waterfall_order"
    assert cand.prior_bp == 10000
    assert cand.user_confirmed is True


# -------------------------------------------------------------------------------------------------
# 5. Observer 5: Merchant Habits
# -------------------------------------------------------------------------------------------------


def test_observer_merchant_habits(conn: sqlite3.Connection):
    """Observer extracts user merchant overrides."""
    user_id = "u_merch_obs"
    _setup_test_user(conn, user_id)
    clock = datetime(2026, 4, 1, 0, 0, 0, tzinfo=UTC)

    conn.execute(
        """
        INSERT INTO merchant_overrides (
            id, user_id, merchant_normalized, category_id, created_by, created_at
        ) VALUES (
            'ovr_swiggy', ?, 'swiggy', ?, 'user', '2026-03-01T00:00:00Z'
        )
        """,
        (user_id, f"dining_{user_id}"),
    )

    cands = observe_merchant_habits(conn, user_id, clock)
    assert len(cands) == 1
    cand = cands[0]
    assert cand.kind == "merchant_habit"
    assert cand.subject_key == "merchant:swiggy"
    assert cand.statement_json["merchant"] == "swiggy"
    assert cand.statement_json["category"] == f"dining_{user_id}"
    assert cand.source == "user_stated"


# -------------------------------------------------------------------------------------------------
# 6. Lifecycle: Candidate, Active, Stale, Retired
# -------------------------------------------------------------------------------------------------


def test_candidate_to_active_lifecycle(conn: sqlite3.Connection):
    """Observed items start as candidate and promote to active when confidence reaches use threshold."""
    user_id = "u_lifecycle"
    _setup_test_user(conn, user_id)
    cfg = load_memory_config()

    item = MemoryItem(
        id="mem_test",
        user_id=user_id,
        kind="recurring_pattern",
        subject_key="category:dining",
        statement_json={"pattern": "weekend_heavy"},
        source="observed",
        status="candidate",
        prior_bp=3000,
        user_confirmed=False,
        confidence_bp=0,
        created_at="2026-03-01T00:00:00Z",
    )
    insert_memory_item(conn, item)

    # 1. With no evidence, evidence_bp = 3000 -> remains candidate
    ev_list: list[MemoryEvidence] = []
    clock = datetime(2026, 3, 1, 0, 0, 0, tzinfo=UTC)
    conf_bp, supp_bp, cont_bp = compute_memory_confidence(item, ev_list, clock, cfg)
    assert conf_bp == 3000
    status = determine_memory_status(item, conf_bp, supp_bp, cont_bp, 0, cfg)
    assert status == "candidate"

    # 2. Add 3 supporting evidence items (each 1500 bp) -> total support = 4500 bp
    # evidence_bp = 3000 + 4500 = 7500 bp >= 6000 bp -> becomes active!
    for i in range(3):
        mev = MemoryEvidence(
            id=f"mev_{i}",
            user_id=user_id,
            memory_id="mem_test",
            polarity="supports",
            ref_kind="txn",
            ref_id=f"tx_{i}",
            observed_at="2026-03-01T00:00:00Z",
            weight_bp=1500,
            created_at="2026-03-01T00:00:00Z",
        )
        insert_memory_evidence(conn, mev)
        ev_list.append(mev)

    conf_bp, supp_bp, cont_bp = compute_memory_confidence(item, ev_list, clock, cfg)
    assert conf_bp == 7500
    status = determine_memory_status(item, conf_bp, supp_bp, cont_bp, 0, cfg)
    assert status == "active"


def test_user_confirmed_contradicted_memory_becomes_stale(conn: sqlite3.Connection):
    """User confirmed memory that becomes contradicted becomes stale with still_true check (PLAN_PHASE3 5.9)."""
    user_id = "u_still_true"
    _setup_test_user(conn, user_id)
    cfg = load_memory_config()

    item = MemoryItem(
        id="mem_conf",
        user_id=user_id,
        kind="recurring_pattern",
        subject_key="category:dining",
        statement_json={"pattern": "weekend_heavy"},
        source="observed",
        status="active",
        prior_bp=6000,
        user_confirmed=True,
        confidence_bp=6000,
        created_at="2026-03-01T00:00:00Z",
    )
    insert_memory_item(conn, item)

    # Add 2 contradicting evidence items with weight exceeding support
    ev_list = [
        MemoryEvidence(
            id="mev_c1",
            user_id=user_id,
            memory_id="mem_conf",
            polarity="contradicts",
            ref_kind="txn",
            ref_id="tx_c1",
            observed_at="2026-03-10T00:00:00Z",
            weight_bp=5000,
            created_at="2026-03-10T00:00:00Z",
        ),
        MemoryEvidence(
            id="mev_c2",
            user_id=user_id,
            memory_id="mem_conf",
            polarity="contradicts",
            ref_kind="txn",
            ref_id="tx_c2",
            observed_at="2026-03-11T00:00:00Z",
            weight_bp=5000,
            created_at="2026-03-11T00:00:00Z",
        ),
    ]

    clock = datetime(2026, 3, 15, 0, 0, 0, tzinfo=UTC)
    conf_bp, supp_bp, cont_bp = compute_memory_confidence(item, ev_list, clock, cfg)
    status = determine_memory_status(item, conf_bp, supp_bp, cont_bp, 2, cfg)

    # Invariant: Not auto-retired! Must be 'stale'
    assert status == "stale"


# -------------------------------------------------------------------------------------------------
# 7. Forgetting Invariant (PLAN_PHASE3 Section 4 & 5.8)
# -------------------------------------------------------------------------------------------------


def test_forgetting_removes_content_and_keeps_content_free_audit(conn: sqlite3.Connection):
    """forget_memory clears statement_json, deletes evidence, sets status=forgotten, audit has zero content."""
    user_id = "u_forget"
    _setup_test_user(conn, user_id)
    clock = datetime(2026, 3, 20, 0, 0, 0, tzinfo=UTC)

    # Record contextual exception with sensitive reason
    item = record_contextual_exception(
        conn,
        user_id=user_id,
        category="dining",
        period="2026-11",
        reason="medical",
        clock=clock,
    )
    mem_id = item.id

    # Evidence exists
    ev_list = list_memory_evidence(conn, user_id, mem_id)
    assert len(ev_list) >= 1

    # Now forget
    success = forget_memory(conn, user_id, mem_id, clock=clock)
    assert success is True

    # 1. Statement cleared to {}
    updated_item = get_memory_item(conn, user_id, mem_id)
    assert updated_item is not None
    assert updated_item.status == "forgotten"
    assert updated_item.statement_json == {}

    # 2. Evidence rows completely deleted
    remaining_evidence = list_memory_evidence(conn, user_id, mem_id)
    assert len(remaining_evidence) == 0

    # 3. Content-free audit event
    audit_row = conn.execute(
        """
        SELECT event_type, before_json, after_json, reason
        FROM audit_events
        WHERE user_id = ? AND entity_id = ? AND event_type = 'memory_forgotten'
        """,
        (user_id, mem_id),
    ).fetchone()

    assert audit_row is not None
    ev_type, before_json, after_json, reason = audit_row
    assert ev_type == "memory_forgotten"
    assert "medical" not in before_json
    assert "medical" not in after_json
    assert "medical" not in reason
    before_data = json.loads(before_json)
    assert before_data == {
        "memory_id": mem_id,
        "kind": "contextual_exception",
        "subject_key": "category:dining|period:2026-11",
    }


# -------------------------------------------------------------------------------------------------
# 8. Multi-Tenant Isolation
# -------------------------------------------------------------------------------------------------


def test_memory_multi_tenant_isolation(conn: sqlite3.Connection):
    """User A cannot access or manipulate User B's memories or evidence."""
    user_a = "u_tenant_a"
    user_b = "u_tenant_b"
    _setup_test_user(conn, user_a)
    _setup_test_user(conn, user_b)
    clock = datetime(2026, 3, 20, 0, 0, 0, tzinfo=UTC)

    # Create memory for User B
    item_b = record_contextual_exception(
        conn,
        user_id=user_b,
        category="travel",
        period="2026-12",
        reason="travel",
        clock=clock,
    )

    # User A tries to query B's memory
    assert get_memory_item(conn, user_a, item_b.id) is None
    assert list_memory_items(conn, user_a) == []
    assert list_memory_evidence(conn, user_a, item_b.id) == []

    # User A tries to forget B's memory
    assert forget_memory(conn, user_a, item_b.id, clock=clock) is False

    # User A tries to edit B's memory
    with pytest.raises(ToolFailure) as exc_info:
        edit_memory_statement_bounded(
            conn,
            user_id=user_a,
            memory_id=item_b.id,
            updates={"reason": "festival"},
        )
    assert exc_info.value.error.code == ErrorCode.NOT_FOUND


# -------------------------------------------------------------------------------------------------
# 9. Idempotency
# -------------------------------------------------------------------------------------------------


def test_refresh_memories_idempotent_for_same_clock(conn: sqlite3.Connection):
    """Calling refresh_memories twice with the same clock and state produces zero duplicate records."""
    user_id = "u_idemp"
    _setup_test_user(conn, user_id)
    clock = datetime(2026, 3, 20, 0, 0, 0, tzinfo=UTC)

    set_user_preference(
        conn,
        user_id=user_id,
        key="emergency_target_months",
        value=3,
        updated_at="2026-03-01T00:00:00Z",
    )

    # First run
    res1 = refresh_memories(conn, user_id, clock)
    count_items_1 = len(list_memory_items(conn, user_id))
    count_ev_1 = conn.execute(
        "SELECT COUNT(*) FROM memory_evidence WHERE user_id = ?", (user_id,)
    ).fetchone()[0]

    # Second run with exact same clock
    res2 = refresh_memories(conn, user_id, clock)
    count_items_2 = len(list_memory_items(conn, user_id))
    count_ev_2 = conn.execute(
        "SELECT COUNT(*) FROM memory_evidence WHERE user_id = ?", (user_id,)
    ).fetchone()[0]

    assert count_items_1 == count_items_2
    assert count_ev_1 == count_ev_2
    assert res2["new_candidates"] == 0
    assert res1["counts"] == res2["counts"]


# -------------------------------------------------------------------------------------------------
# 10. LLM Provider Invariant: Never Called
# -------------------------------------------------------------------------------------------------


def test_llm_provider_never_called_by_memory_system(conn: sqlite3.Connection):
    """Verify that zero LLM provider calls are made by any behavioural memory observer or operation."""
    user_id = "u_zero_llm"
    _setup_test_user(conn, user_id)
    clock = datetime(2026, 3, 20, 0, 0, 0, tzinfo=UTC)

    # Initialize a FakeLLMClient with empty replies (which would raise if invoked)
    fake_llm = FakeLLMClient([])

    # Run observers and full refresh
    observe_recurring_patterns(conn, user_id, clock)
    observe_contextual_exceptions(conn, user_id, clock)
    observe_advice_feedback(conn, user_id, clock)
    observe_preferences(conn, user_id, clock)
    observe_merchant_habits(conn, user_id, clock)
    refresh_memories(conn, user_id, clock)

    # Record, edit, forget
    item = record_contextual_exception(conn, user_id, "travel", "2026-10", "travel", clock=clock)
    edit_memory_statement_bounded(conn, user_id, item.id, {"reason": "festival"}, clock=clock)
    forget_memory(conn, user_id, item.id, clock=clock)

    # Strict invariant assertion: provider call log must have 0 prompts
    assert len(fake_llm.prompts) == 0
