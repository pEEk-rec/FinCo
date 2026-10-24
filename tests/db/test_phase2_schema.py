"""
Tests for Phase 2 database schema, migrations, models, and repo functions (PLAN_PHASE2 Stage 2.1).
"""

import sqlite3

import pytest

from copilot.db.connection import get_connection, init_db
from copilot.db.repo import (
    get_agent_task,
    get_alert,
    get_goal,
    get_investigation,
    get_simulation,
    insert_agent_task,
    insert_alert,
    insert_goal,
    insert_investigation,
    insert_plan_step,
    insert_simulation,
    insert_user,
    list_alert_preferences,
    list_alerts,
    list_goals,
    list_plan_steps,
    set_alert_preference,
    update_agent_task_status,
    update_alert_status,
    update_goal,
)
from copilot.models.agentic import (
    AgentTask,
    Alert,
    AlertPreference,
    EvidenceItem,
    Goal,
    Hypothesis,
    Intent,
    Investigation,
    PlanStep,
)
from copilot.models.domain import User

T0 = "2026-10-01T10:00:00Z"
T1 = "2026-10-01T12:00:00Z"


@pytest.fixture
def conn() -> sqlite3.Connection:
    c = get_connection(":memory:")
    init_db(c)
    insert_user(c, User(id="u1", created_at=T0))
    insert_user(c, User(id="u2", created_at=T0))
    c.commit()
    return c


def test_migrations_idempotency_fresh_and_repeat(conn):
    """Applying init_db multiple times is completely idempotent."""
    init_db(conn)
    init_db(conn)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "agent_tasks" in tables
    assert "plan_steps" in tables
    assert "goals" in tables
    assert "investigations" in tables
    assert "hypotheses" in tables
    assert "evidence_items" in tables
    assert "simulations" in tables
    assert "alerts" in tables
    assert "alert_preferences" in tables


def test_migration_preserves_phase1_advice_items_data():
    """Applying migration 003 to an existing Phase 1 database preserves advice_items rows."""
    c = get_connection(":memory:")
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        ) STRICT;
        """
    )
    for m in ["001_initial.sql", "002_phase1_schema.sql"]:
        script = (
            pytest.importorskip("pathlib").Path(__file__).resolve().parents[2]
            / "src"
            / "copilot"
            / "db"
            / "migrations"
            / m
        ).read_text(encoding="utf-8")
        c.executescript(script)
        c.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            (m, T0),
        )
    c.commit()

    insert_user(c, User(id="u1", created_at=T0))
    # Insert Phase 1 advice item before migration 003
    c.execute(
        """
        INSERT INTO advice_items (
            id, user_id, run_id, finding_ids_json, text,
            evidence_json, assumptions_json, status, created_at
        ) VALUES ('adv_1', 'u1', 'r1', '[]', 'Old advice', '[]', '[]', 'draft', ?)
        """,
        (T0,),
    )
    c.commit()

    # Now run init_db (which applies 003)
    init_db(c)

    # Check that adv_1 is preserved and has new column defaults
    row = c.execute("SELECT * FROM advice_items WHERE id = 'adv_1'").fetchone()
    assert row is not None
    assert row["id"] == "adv_1"
    assert row["text"] == "Old advice"
    assert row["origin"] == "monthly_review"  # default value populated
    assert row["calculations_json"] is None


def test_goal_repo_and_constraints(conn):
    """Goals CRUD, user isolation, and constraint enforcement."""
    goal1 = Goal(
        id="g1",
        user_id="u1",
        name="Emergency Fund",
        kind="emergency_fund",
        target_paise=10000000,
        current_paise=2500000,
        deadline="2027-03-31",
        priority=1,
        status="active",
        created_at=T0,
        updated_at=T0,
    )
    insert_goal(conn, goal1)

    fetched = get_goal(conn, "u1", "g1")
    assert fetched is not None
    assert fetched.name == "Emergency Fund"
    assert fetched.target_paise == 10000000

    # User isolation: u2 cannot see u1's goal
    assert get_goal(conn, "u2", "g1") is None
    assert len(list_goals(conn, "u2")) == 0
    assert len(list_goals(conn, "u1")) == 1

    # Update goal
    ok = update_goal(conn, "u1", "g1", current_paise=3000000, updated_at=T1)
    assert ok
    updated = get_goal(conn, "u1", "g1")
    assert updated.current_paise == 3000000

    # Constraint check: negative target_paise fails
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO goals (id, user_id, name, kind, target_paise, current_paise, priority, status, created_at, updated_at)
            VALUES ('g_bad', 'u1', 'Bad', 'savings', -500, 0, 1, 'active', ?, ?)
            """,
            (T0, T0),
        )


def test_agent_task_and_plan_steps_repo(conn):
    """Agent task & plan steps CRUD, user isolation, and relations."""
    intent = Intent(
        type="check_budget",
        period="2026-09",
        confidence_label="high",
        source="deterministic",
    )
    task = AgentTask(
        id="task_1",
        user_id="u1",
        run_id="run_1",
        raw_text="Check my dining budget for September",
        intent=intent,
        status="running",
        planner_mode="deterministic",
        created_at=T0,
    )
    insert_agent_task(conn, task)

    step1 = PlanStep(
        id="s1",
        task_id="task_1",
        user_id="u1",
        seq=0,
        tool_name="check_budgets",
        args={"month": "2026-09"},
        rationale="Inspect September budgets",
        proposed_by="deterministic",
        status="done",
        started_at=T0,
        finished_at=T1,
    )
    insert_plan_step(conn, step1)

    fetched_task = get_agent_task(conn, "u1", "task_1")
    assert fetched_task is not None
    assert fetched_task.intent.type == "check_budget"
    assert fetched_task.intent.period == "2026-09"

    # User isolation: u2 cannot get u1's task
    assert get_agent_task(conn, "u2", "task_1") is None

    steps = list_plan_steps(conn, "u1", "task_1")
    assert len(steps) == 1
    assert steps[0].tool_name == "check_budgets"
    assert steps[0].args == {"month": "2026-09"}

    # Update task status
    assert update_agent_task_status(conn, "u1", "task_1", "done", stop_reason="completed")
    assert get_agent_task(conn, "u1", "task_1").status == "done"


def test_investigation_repo_and_relations(conn):
    """Investigations, hypotheses, and evidence items insertion and round-trip."""
    h1 = Hypothesis(
        id="h1",
        investigation_id="inv_1",
        user_id="u1",
        code="one_off_large",
        status="supported",
        score_bp=8000,
        contribution_paise=500000,
    )
    e1 = EvidenceItem(
        id="e1",
        investigation_id="inv_1",
        user_id="u1",
        hypothesis_code="one_off_large",
        test_code="top_ticket_share",
        result="supports",
        strength_bp=8500,
        numbers={"share_pct": 78, "amount_paise": 500000},
        txn_ids=["tx_123"],
    )
    inv = Investigation(
        id="inv_1",
        task_id=None,
        user_id="u1",
        run_id="run_inv",
        subject_kind="category_change",
        subject_ref={"category_id": "dining", "period": "2026-09"},
        outcome="explained",
        confidence_label="high",
        explained_share_bp=8000,
        unexplained_paise=125000,
        rounds=1,
        hypotheses=[h1],
        evidence=[e1],
        created_at=T0,
    )
    insert_investigation(conn, inv)

    fetched = get_investigation(conn, "u1", "inv_1")
    assert fetched is not None
    assert fetched.outcome == "explained"
    assert len(fetched.hypotheses) == 1
    assert fetched.hypotheses[0].code == "one_off_large"
    assert len(fetched.evidence) == 1
    assert fetched.evidence[0].numbers["share_pct"] == 78
    assert fetched.evidence[0].txn_ids == ["tx_123"]

    # User isolation: u2 cannot get u1's investigation
    assert get_investigation(conn, "u2", "inv_1") is None


def test_simulation_repo(conn):
    """Simulation insertion and retrieval."""
    insert_simulation(
        conn,
        sim_id="sim_1",
        user_id="u1",
        scenario={"kind": "add_spend", "amount_paise": 3000000},
        baseline={"projected_spend": 2500000},
        result={"new_projected_spend": 5500000},
        assumptions=["Income remains unchanged"],
        created_at=T0,
    )

    sim = get_simulation(conn, "u1", "sim_1")
    assert sim is not None
    assert sim["scenario"]["amount_paise"] == 3000000
    assert sim["assumptions"] == ["Income remains unchanged"]

    # User isolation
    assert get_simulation(conn, "u2", "sim_1") is None


def test_alerts_and_preferences_repo(conn):
    """Alerts and AlertPreferences CRUD, isolation, and updates."""
    alert1 = Alert(
        id="alt_1",
        user_id="u1",
        kind="budget_velocity",
        subject_key="dining:2026-09",
        period="2026-09",
        score_bp=8200,
        severity="warning",
        components={"threshold": 91, "run_rate": 115},
        why_text="Dining is at 91% with 11 days left",
        status="open",
        dedup_key="dining:2026-09:budget_velocity",
        created_at=T0,
    )
    insert_alert(conn, alert1)

    fetched = get_alert(conn, "u1", "alt_1")
    assert fetched is not None
    assert fetched.severity == "warning"
    assert fetched.components["threshold"] == 91

    # User isolation
    assert get_alert(conn, "u2", "alt_1") is None
    assert len(list_alerts(conn, "u2")) == 0
    assert len(list_alerts(conn, "u1")) == 1

    # Update alert lifecycle
    assert update_alert_status(
        conn, "u1", "alt_1", "dismissed", decided_at=T1, dismiss_reason="expected_trip"
    )
    updated = get_alert(conn, "u1", "alt_1")
    assert updated.status == "dismissed"
    assert updated.dismiss_reason == "expected_trip"

    # Preferences
    pref = AlertPreference(
        id="pref_1",
        user_id="u1",
        kind="budget_velocity",
        min_severity="warning",
        muted=False,
        max_open_alerts=3,
    )
    set_alert_preference(conn, pref)
    user_prefs = list_alert_preferences(conn, "u1")
    assert len(user_prefs) == 1
    assert user_prefs[0].min_severity == "warning"
    assert user_prefs[0].max_open_alerts == 3
    assert len(list_alert_preferences(conn, "u2")) == 0
