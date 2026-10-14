"""
Data access layer for persistent state.

Every function takes `user_id` and filters by it. No function commits: callers wrap their
unit of work in `copilot.db.connection.savepoint`.
"""

import json
import sqlite3
from typing import Any

from copilot.models.agentic import (
    AgentTask,
    Alert,
    AlertPreference,
    CalcStep,
    EvidenceItem,
    Goal,
    Hypothesis,
    Intent,
    Investigation,
    PlanStep,
    Recommendation,
)
from copilot.models.domain import Account, Budget, Category, MonthlyReview, Transaction, User
from copilot.models.memory import MemoryEntry


def insert_user(conn: sqlite3.Connection, user: User) -> None:
    """Insert a new user."""
    conn.execute("INSERT INTO users (id, created_at) VALUES (?, ?)", (user.id, user.created_at))


def get_user(conn: sqlite3.Connection, user_id: str) -> User | None:
    """Get a user by ID, or None."""
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return User(**dict(row)) if row else None


def insert_account(conn: sqlite3.Connection, account: Account) -> None:
    """Insert a new account."""
    conn.execute(
        """
        INSERT INTO accounts (id, user_id, name, opening_balance_paise, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            account.id,
            account.user_id,
            account.name,
            account.opening_balance_paise,
            account.created_at,
        ),
    )


def get_account(conn: sqlite3.Connection, user_id: str, account_id: str) -> Account | None:
    """Get an account by ID, or None if it does not exist for this user."""
    row = conn.execute(
        "SELECT * FROM accounts WHERE id = ? AND user_id = ?", (account_id, user_id)
    ).fetchone()
    return Account(**dict(row)) if row else None


def list_accounts(conn: sqlite3.Connection, user_id: str) -> list[Account]:
    """List all accounts for a user, ordered by id."""
    rows = conn.execute(
        "SELECT * FROM accounts WHERE user_id = ? ORDER BY id", (user_id,)
    ).fetchall()
    return [Account(**dict(row)) for row in rows]


def insert_category(conn: sqlite3.Connection, category: Category) -> None:
    """Insert a new category."""
    conn.execute(
        "INSERT INTO categories (id, user_id, name, created_at) VALUES (?, ?, ?, ?)",
        (category.id, category.user_id, category.name, category.created_at),
    )


def get_category(conn: sqlite3.Connection, user_id: str, category_id: str) -> Category | None:
    """Get a category by ID, or None if it does not exist for this user."""
    row = conn.execute(
        "SELECT * FROM categories WHERE id = ? AND user_id = ?", (category_id, user_id)
    ).fetchone()
    return Category(**dict(row)) if row else None


def list_categories(conn: sqlite3.Connection, user_id: str) -> list[Category]:
    """List all categories for a user, ordered by name."""
    rows = conn.execute(
        "SELECT * FROM categories WHERE user_id = ? ORDER BY name, id", (user_id,)
    ).fetchall()
    return [Category(**dict(row)) for row in rows]


def insert_transaction(conn: sqlite3.Connection, tx: Transaction) -> None:
    """Insert a new transaction."""
    conn.execute(
        """
        INSERT INTO transactions (
            id, user_id, account_id, occurred_at, amount_paise, direction,
            merchant_raw, description, category_id, category_confidence,
            category_source, created_at, fingerprint, batch_id,
            merchant_normalized, mode, is_duplicate_of, needs_review,
            excluded_from_spend
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            tx.id,
            tx.user_id,
            tx.account_id,
            tx.occurred_at,
            tx.amount_paise,
            tx.direction,
            tx.merchant_raw,
            tx.description,
            tx.category_id,
            tx.category_confidence,
            tx.category_source,
            tx.created_at,
            tx.fingerprint,
            tx.batch_id,
            tx.merchant_normalized,
            tx.mode,
            tx.is_duplicate_of,
            1 if tx.needs_review else 0,
            1 if tx.excluded_from_spend else 0,
        ),
    )


def get_transaction(conn: sqlite3.Connection, user_id: str, tx_id: str) -> Transaction | None:
    """Get a transaction by ID, or None if it does not exist for this user."""
    row = conn.execute(
        "SELECT * FROM transactions WHERE id = ? AND user_id = ?", (tx_id, user_id)
    ).fetchone()
    return Transaction(**dict(row)) if row else None


def list_transactions(
    conn: sqlite3.Connection,
    user_id: str,
    start: str,
    end: str,
    category_id: str | None = None,
    account_id: str | None = None,
    limit: int | None = None,
) -> list[Transaction]:
    """
    List a user's transactions with start <= occurred_at < end, oldest first.

    Optional filters: category, account, and a maximum row count.
    """
    query = """
        SELECT * FROM transactions
        WHERE user_id = ? AND occurred_at >= ? AND occurred_at < ?
    """
    params: list[str | int] = [user_id, start, end]
    if category_id is not None:
        query += " AND category_id = ?"
        params.append(category_id)
    if account_id is not None:
        query += " AND account_id = ?"
        params.append(account_id)
    query += " ORDER BY occurred_at ASC, id ASC"
    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)
    rows = conn.execute(query, params).fetchall()
    return [Transaction(**dict(row)) for row in rows]


def insert_budget(conn: sqlite3.Connection, budget: Budget) -> None:
    """Insert a new budget."""
    conn.execute(
        """
        INSERT INTO budgets (
            id, user_id, category_id, period, limit_paise, warn_threshold_pct, forecast_warn
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            budget.id,
            budget.user_id,
            budget.category_id,
            budget.period,
            budget.limit_paise,
            budget.warn_threshold_pct,
            1 if budget.forecast_warn else 0,
        ),
    )


def list_budgets(conn: sqlite3.Connection, user_id: str) -> list[Budget]:
    """List all budgets for a user, ordered by category."""
    rows = conn.execute(
        "SELECT * FROM budgets WHERE user_id = ? ORDER BY category_id, id", (user_id,)
    ).fetchall()
    return [Budget(**dict(row)) for row in rows]


def update_transaction_category(
    conn: sqlite3.Connection,
    user_id: str,
    tx_id: str,
    category_id: str | None,
    category_source: str,
    category_confidence: float | None = None,
    needs_review: bool | None = None,
) -> bool:
    """
    Update a transaction's category. Returns False if no such transaction for this user.

    `needs_review` None leaves the review flag alone; True/False sets it.
    """
    cursor = conn.execute(
        """
        UPDATE transactions
        SET category_id = ?, category_source = ?, category_confidence = ?,
            needs_review = COALESCE(?, needs_review)
        WHERE id = ? AND user_id = ?
        """,
        (
            category_id,
            category_source,
            category_confidence,
            None if needs_review is None else int(needs_review),
            tx_id,
            user_id,
        ),
    )
    return cursor.rowcount == 1


def insert_memory_entry(conn: sqlite3.Connection, entry: MemoryEntry) -> None:
    """Insert a memory entry."""
    conn.execute(
        """
        INSERT INTO memory_entries (
            id, user_id, kind, content, source, confidence,
            created_at, last_confirmed_at, provenance
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            entry.id,
            entry.user_id,
            entry.kind,
            entry.content,
            entry.source,
            entry.confidence,
            entry.created_at,
            entry.last_confirmed_at,
            entry.provenance,
        ),
    )


def list_memory_entries(
    conn: sqlite3.Connection, user_id: str, kind: str | None = None
) -> list[MemoryEntry]:
    """List a user's memory entries (optionally one kind), oldest first. No ranking."""
    query = "SELECT * FROM memory_entries WHERE user_id = ?"
    params: list[str] = [user_id]
    if kind is not None:
        query += " AND kind = ?"
        params.append(kind)
    query += " ORDER BY created_at ASC, id ASC"
    return [MemoryEntry(**dict(row)) for row in conn.execute(query, params).fetchall()]


def insert_monthly_review(conn: sqlite3.Connection, review: MonthlyReview) -> None:
    """Insert a new monthly review version."""
    conn.execute(
        """
        INSERT INTO monthly_reviews (
            id, user_id, year, month, version, run_id, review_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            review.id,
            review.user_id,
            review.year,
            review.month,
            review.version,
            review.run_id,
            review.review_json,
            review.created_at,
        ),
    )


def get_monthly_review(
    conn: sqlite3.Connection,
    user_id: str,
    year: int,
    month: int,
    version: int | None = None,
) -> MonthlyReview | None:
    """Get the latest (or specific version) monthly review."""
    if version is not None:
        row = conn.execute(
            """
            SELECT * FROM monthly_reviews
            WHERE user_id = ? AND year = ? AND month = ? AND version = ?
            """,
            (user_id, year, month, version),
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT * FROM monthly_reviews
            WHERE user_id = ? AND year = ? AND month = ?
            ORDER BY version DESC LIMIT 1
            """,
            (user_id, year, month),
        ).fetchone()
    return MonthlyReview(**dict(row)) if row else None


def list_monthly_reviews(
    conn: sqlite3.Connection,
    user_id: str,
    year: int | None = None,
    month: int | None = None,
) -> list[MonthlyReview]:
    """List monthly reviews for a user, sorted newest version first."""
    query = "SELECT * FROM monthly_reviews WHERE user_id = ?"
    params: list[object] = [user_id]
    if year is not None:
        query += " AND year = ?"
        params.append(year)
    if month is not None:
        query += " AND month = ?"
        params.append(month)
    query += " ORDER BY year DESC, month DESC, version DESC"
    return [MonthlyReview(**dict(row)) for row in conn.execute(query, params).fetchall()]


# ---------------------------------------------------------------------------------------------
# Phase 2: Goals
# ---------------------------------------------------------------------------------------------
def insert_goal(conn: sqlite3.Connection, goal: Goal) -> None:
    """Insert a new financial goal."""
    conn.execute(
        """
        INSERT INTO goals (
            id, user_id, name, kind, target_paise, current_paise,
            deadline, priority, status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            goal.id,
            goal.user_id,
            goal.name,
            goal.kind,
            goal.target_paise,
            goal.current_paise,
            goal.deadline,
            goal.priority,
            goal.status,
            goal.created_at,
            goal.updated_at,
        ),
    )


def get_goal(conn: sqlite3.Connection, user_id: str, goal_id: str) -> Goal | None:
    """Get a goal by ID, or None if not found for user."""
    row = conn.execute(
        "SELECT * FROM goals WHERE id = ? AND user_id = ?",
        (goal_id, user_id),
    ).fetchone()
    return Goal(**dict(row)) if row else None


def list_goals(
    conn: sqlite3.Connection,
    user_id: str,
    status: str | None = None,
) -> list[Goal]:
    """List goals for a user, ordered by priority ascending."""
    query = "SELECT * FROM goals WHERE user_id = ?"
    params: list[object] = [user_id]
    if status is not None:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY priority ASC, created_at ASC"
    return [Goal(**dict(row)) for row in conn.execute(query, params).fetchall()]


def update_goal(
    conn: sqlite3.Connection,
    user_id: str,
    goal_id: str,
    name: str | None = None,
    target_paise: int | None = None,
    current_paise: int | None = None,
    deadline: str | None = None,
    priority: int | None = None,
    status: str | None = None,
    updated_at: str | None = None,
) -> bool:
    """Update goal fields; returns True if a row was updated."""
    updates: list[str] = []
    params: list[object] = []
    if name is not None:
        updates.append("name = ?")
        params.append(name)
    if target_paise is not None:
        updates.append("target_paise = ?")
        params.append(target_paise)
    if current_paise is not None:
        updates.append("current_paise = ?")
        params.append(current_paise)
    if deadline is not None:
        updates.append("deadline = ?")
        params.append(deadline)
    if priority is not None:
        updates.append("priority = ?")
        params.append(priority)
    if status is not None:
        updates.append("status = ?")
        params.append(status)
    if updated_at is not None:
        updates.append("updated_at = ?")
        params.append(updated_at)

    if not updates:
        return False

    query = f"UPDATE goals SET {', '.join(updates)} WHERE id = ? AND user_id = ?"
    params.extend([goal_id, user_id])
    cur = conn.execute(query, params)
    return cur.rowcount > 0


# ---------------------------------------------------------------------------------------------
# Phase 2: Agent Tasks & Plan Steps
# ---------------------------------------------------------------------------------------------
def insert_agent_task(conn: sqlite3.Connection, task: AgentTask) -> None:
    """Insert a new agent task."""
    conn.execute(
        """
        INSERT INTO agent_tasks (
            id, user_id, run_id, raw_text, intent_json, status,
            stop_reason, planner_mode, model, prompt_version,
            created_at, finished_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            task.id,
            task.user_id,
            task.run_id,
            task.raw_text,
            task.intent.model_dump_json() if task.intent else None,
            task.status,
            task.stop_reason,
            task.planner_mode,
            task.model,
            task.prompt_version,
            task.created_at,
            task.finished_at,
        ),
    )


def get_agent_task(conn: sqlite3.Connection, user_id: str, task_id: str) -> AgentTask | None:
    """Get an agent task by ID."""
    row = conn.execute(
        "SELECT * FROM agent_tasks WHERE id = ? AND user_id = ?",
        (task_id, user_id),
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    if d.get("intent_json"):
        d["intent"] = Intent.model_validate_json(d.pop("intent_json"))
    else:
        d["intent"] = None
        d.pop("intent_json", None)
    return AgentTask(**d)


def update_agent_task_status(
    conn: sqlite3.Connection,
    user_id: str,
    task_id: str,
    status: str,
    stop_reason: str | None = None,
    finished_at: str | None = None,
) -> bool:
    """Update an agent task status and stop reason."""
    cur = conn.execute(
        """
        UPDATE agent_tasks
        SET status = ?,
            stop_reason = COALESCE(?, stop_reason),
            finished_at = COALESCE(?, finished_at)
        WHERE id = ? AND user_id = ?
        """,
        (status, stop_reason, finished_at, task_id, user_id),
    )
    return cur.rowcount > 0


def insert_plan_step(conn: sqlite3.Connection, step: PlanStep) -> None:
    """Insert a plan step."""
    conn.execute(
        """
        INSERT INTO plan_steps (
            id, task_id, user_id, seq, tool_name, args_json, rationale,
            proposed_by, status, reject_reason, started_at, finished_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            step.id,
            step.task_id,
            step.user_id,
            step.seq,
            step.tool_name,
            json.dumps(step.args, sort_keys=True),
            step.rationale,
            step.proposed_by,
            step.status,
            step.reject_reason,
            step.started_at,
            step.finished_at,
        ),
    )


def list_plan_steps(conn: sqlite3.Connection, user_id: str, task_id: str) -> list[PlanStep]:
    """List plan steps for a task in execution sequence order."""
    rows = conn.execute(
        "SELECT * FROM plan_steps WHERE user_id = ? AND task_id = ? ORDER BY seq ASC",
        (user_id, task_id),
    ).fetchall()
    steps = []
    for r in rows:
        d = dict(r)
        d["args"] = json.loads(d.pop("args_json", "{}"))
        steps.append(PlanStep(**d))
    return steps


def update_plan_step_status(
    conn: sqlite3.Connection,
    user_id: str,
    step_id: str,
    status: str,
    reject_reason: str | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
) -> bool:
    """Update status of a plan step."""
    cur = conn.execute(
        """
        UPDATE plan_steps
        SET status = ?,
            reject_reason = COALESCE(?, reject_reason),
            started_at = COALESCE(?, started_at),
            finished_at = COALESCE(?, finished_at)
        WHERE id = ? AND user_id = ?
        """,
        (status, reject_reason, started_at, finished_at, step_id, user_id),
    )
    return cur.rowcount > 0


# ---------------------------------------------------------------------------------------------
# Phase 2: Investigations
# ---------------------------------------------------------------------------------------------
def insert_investigation(conn: sqlite3.Connection, inv: Investigation) -> None:
    """Insert an investigation record with its hypotheses and evidence items."""
    conn.execute(
        """
        INSERT INTO investigations (
            id, task_id, user_id, run_id, subject_kind, subject_ref_json,
            outcome, confidence_label, explained_share_bp, unexplained_paise,
            rounds, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            inv.id,
            inv.task_id,
            inv.user_id,
            inv.run_id,
            inv.subject_kind,
            json.dumps(inv.subject_ref, sort_keys=True),
            inv.outcome,
            inv.confidence_label,
            inv.explained_share_bp,
            inv.unexplained_paise,
            inv.rounds,
            inv.created_at,
        ),
    )
    for h in inv.hypotheses:
        conn.execute(
            """
            INSERT INTO hypotheses (
                id, investigation_id, user_id, code, status, score_bp, contribution_paise
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (h.id, inv.id, inv.user_id, h.code, h.status, h.score_bp, h.contribution_paise),
        )
    for e in inv.evidence:
        conn.execute(
            """
            INSERT INTO evidence_items (
                id, investigation_id, user_id, hypothesis_code, test_code,
                result, strength_bp, numbers_json, txn_ids_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                e.id,
                inv.id,
                inv.user_id,
                e.hypothesis_code,
                e.test_code,
                e.result,
                e.strength_bp,
                json.dumps(e.numbers, sort_keys=True),
                json.dumps(e.txn_ids),
            ),
        )


def get_investigation(
    conn: sqlite3.Connection, user_id: str, inv_id: str
) -> Investigation | None:
    """Get an investigation with its hypotheses and evidence items."""
    row = conn.execute(
        "SELECT * FROM investigations WHERE id = ? AND user_id = ?",
        (inv_id, user_id),
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["subject_ref"] = json.loads(d.pop("subject_ref_json", "{}"))

    h_rows = conn.execute(
        "SELECT * FROM hypotheses WHERE investigation_id = ? AND user_id = ?",
        (inv_id, user_id),
    ).fetchall()
    d["hypotheses"] = [Hypothesis(**dict(hr)) for hr in h_rows]

    e_rows = conn.execute(
        "SELECT * FROM evidence_items WHERE investigation_id = ? AND user_id = ?",
        (inv_id, user_id),
    ).fetchall()
    evidence_items = []
    for er in e_rows:
        ed = dict(er)
        ed["numbers"] = json.loads(ed.pop("numbers_json", "{}"))
        ed["txn_ids"] = json.loads(ed.pop("txn_ids_json", "[]"))
        evidence_items.append(EvidenceItem(**ed))
    d["evidence"] = evidence_items
    return Investigation(**d)


def list_investigations(
    conn: sqlite3.Connection, user_id: str, limit: int = 50
) -> list[Investigation]:
    """List recent investigations for a user."""
    rows = conn.execute(
        "SELECT id FROM investigations WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    return [get_investigation(conn, user_id, r["id"]) for r in rows if r["id"]]  # type: ignore


# ---------------------------------------------------------------------------------------------
# Phase 2: Simulations
# ---------------------------------------------------------------------------------------------
def insert_simulation(
    conn: sqlite3.Connection,
    sim_id: str,
    user_id: str,
    scenario: dict[str, Any],
    baseline: dict[str, Any],
    result: dict[str, Any],
    assumptions: list[str],
    created_at: str,
    task_id: str | None = None,
) -> None:
    """Insert a simulation record."""
    conn.execute(
        """
        INSERT INTO simulations (
            id, task_id, user_id, scenario_json, baseline_json,
            result_json, assumptions_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            sim_id,
            task_id,
            user_id,
            json.dumps(scenario, sort_keys=True),
            json.dumps(baseline, sort_keys=True),
            json.dumps(result, sort_keys=True),
            json.dumps(assumptions, sort_keys=True),
            created_at,
        ),
    )


def get_simulation(
    conn: sqlite3.Connection, user_id: str, sim_id: str
) -> dict[str, Any] | None:
    """Get a simulation by ID."""
    row = conn.execute(
        "SELECT * FROM simulations WHERE id = ? AND user_id = ?",
        (sim_id, user_id),
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    return {
        "id": d["id"],
        "task_id": d["task_id"],
        "user_id": d["user_id"],
        "scenario": json.loads(d["scenario_json"]),
        "baseline": json.loads(d["baseline_json"]),
        "result": json.loads(d["result_json"]),
        "assumptions": json.loads(d["assumptions_json"]),
        "created_at": d["created_at"],
    }


# ---------------------------------------------------------------------------------------------
# Phase 2: Alerts & Preferences
# ---------------------------------------------------------------------------------------------
def insert_alert(conn: sqlite3.Connection, alert: Alert) -> None:
    """Insert an adaptive alert."""
    conn.execute(
        """
        INSERT INTO alerts (
            id, user_id, kind, subject_key, period, score_bp,
            severity, components_json, why_text, status,
            snoozed_until, dedup_key, run_id, created_at,
            decided_at, dismiss_reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            alert.id,
            alert.user_id,
            alert.kind,
            alert.subject_key,
            alert.period,
            alert.score_bp,
            alert.severity,
            json.dumps(alert.components, sort_keys=True),
            alert.why_text,
            alert.status,
            alert.snoozed_until,
            alert.dedup_key,
            alert.run_id,
            alert.created_at,
            alert.decided_at,
            alert.dismiss_reason,
        ),
    )


def get_alert(conn: sqlite3.Connection, user_id: str, alert_id: str) -> Alert | None:
    """Get an alert by ID."""
    row = conn.execute(
        "SELECT * FROM alerts WHERE id = ? AND user_id = ?",
        (alert_id, user_id),
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["components"] = json.loads(d.pop("components_json", "{}"))
    return Alert(**d)


def list_alerts(
    conn: sqlite3.Connection,
    user_id: str,
    status: str | None = None,
    limit: int = 50,
) -> list[Alert]:
    """List alerts for a user."""
    query = "SELECT * FROM alerts WHERE user_id = ?"
    params: list[object] = [user_id]
    if status is not None:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(query, params).fetchall()
    alerts = []
    for r in rows:
        d = dict(r)
        d["components"] = json.loads(d.pop("components_json", "{}"))
        alerts.append(Alert(**d))
    return alerts


def update_alert_status(
    conn: sqlite3.Connection,
    user_id: str,
    alert_id: str,
    status: str,
    decided_at: str | None = None,
    dismiss_reason: str | None = None,
    snoozed_until: str | None = None,
) -> bool:
    """Update alert lifecycle status."""
    cur = conn.execute(
        """
        UPDATE alerts
        SET status = ?,
            decided_at = COALESCE(?, decided_at),
            dismiss_reason = COALESCE(?, dismiss_reason),
            snoozed_until = COALESCE(?, snoozed_until)
        WHERE id = ? AND user_id = ?
        """,
        (status, decided_at, dismiss_reason, snoozed_until, alert_id, user_id),
    )
    return cur.rowcount > 0


def get_alert_by_dedup_key(
    conn: sqlite3.Connection, user_id: str, dedup_key: str
) -> Alert | None:
    """Get the most recent alert matching user_id and dedup_key."""
    row = conn.execute(
        "SELECT * FROM alerts WHERE user_id = ? AND dedup_key = ? ORDER BY created_at DESC LIMIT 1",
        (user_id, dedup_key),
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["components"] = json.loads(d.pop("components_json", "{}"))
    return Alert(**d)


def update_alert_in_place(
    conn: sqlite3.Connection,
    user_id: str,
    alert_id: str,
    score_bp: int,
    severity: str,
    components: dict[str, Any],
    why_text: str,
) -> bool:
    """Escalate an open alert in-place."""
    cur = conn.execute(
        """
        UPDATE alerts
        SET score_bp = ?,
            severity = ?,
            components_json = ?,
            why_text = ?
        WHERE id = ? AND user_id = ?
        """,
        (score_bp, severity, json.dumps(components, sort_keys=True), why_text, alert_id, user_id),
    )
    return cur.rowcount > 0


def set_alert_preference(conn: sqlite3.Connection, pref: AlertPreference) -> None:
    """Insert or update an alert preference."""
    conn.execute(
        """
        INSERT OR REPLACE INTO alert_preferences (
            id, user_id, category_id, kind, min_severity, muted, max_open_alerts
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            pref.id,
            pref.user_id,
            pref.category_id,
            pref.kind,
            pref.min_severity,
            1 if pref.muted else 0,
            pref.max_open_alerts,
        ),
    )


def list_alert_preferences(conn: sqlite3.Connection, user_id: str) -> list[AlertPreference]:
    """List alert preferences for a user."""
    rows = conn.execute(
        "SELECT * FROM alert_preferences WHERE user_id = ?",
        (user_id,),
    ).fetchall()
    prefs = []
    for r in rows:
        d = dict(r)
        d["muted"] = bool(d["muted"])
        prefs.append(AlertPreference(**d))
    return prefs


# -------------------------------------------------------------------------------------------------
# Explainable Recommendations (PLAN_PHASE2 Section 5.8)
# -------------------------------------------------------------------------------------------------


def insert_recommendation(conn: sqlite3.Connection, rec: Recommendation) -> None:
    """Insert an explainable recommendation into advice_items."""
    conn.execute(
        """
        INSERT INTO advice_items (
            id, user_id, run_id, finding_ids_json, text,
            evidence_json, assumptions_json, status, created_at,
            origin, calculations_json, tools_used_json, memories_json,
            confidence_label, simulation_id, task_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            rec.id,
            rec.user_id,
            rec.run_id or "run_0",
            json.dumps(rec.evidence),
            rec.text,
            json.dumps(rec.evidence),
            json.dumps(rec.assumptions),
            rec.status,
            rec.created_at,
            rec.origin,
            json.dumps([c.model_dump() for c in rec.calculations]),
            json.dumps(rec.tools_used),
            json.dumps(rec.memories),
            rec.confidence_label,
            rec.simulation_id,
            rec.task_id,
        ),
    )


def _row_to_recommendation(row: Any) -> Recommendation:
    d = dict(row)
    evidence = json.loads(d.get("evidence_json") or "[]")
    if not isinstance(evidence, list):
        evidence = []
    assumptions = json.loads(d.get("assumptions_json") or "[]")
    if not isinstance(assumptions, list):
        assumptions = []
    calcs_raw = json.loads(d.get("calculations_json") or "[]")
    calculations = [CalcStep(**c) for c in calcs_raw] if isinstance(calcs_raw, list) else []
    tools_used = json.loads(d.get("tools_used_json") or "[]")
    if not isinstance(tools_used, list):
        tools_used = []
    memories = json.loads(d.get("memories_json") or "[]")
    if not isinstance(memories, list):
        memories = []

    return Recommendation(
        id=d["id"],
        user_id=d["user_id"],
        task_id=d.get("task_id"),
        run_id=d.get("run_id"),
        origin=d.get("origin") or "monthly_review",
        text=d["text"],
        evidence=evidence,
        calculations=calculations,
        assumptions=assumptions,
        tools_used=tools_used,
        memories=memories,
        confidence_label=d.get("confidence_label"),
        simulation_id=d.get("simulation_id"),
        status=d.get("status") or "draft",
        created_at=d["created_at"],
    )


def get_recommendation(
    conn: sqlite3.Connection, user_id: str, rec_id: str
) -> Recommendation | None:
    """Get recommendation by ID strictly filtered by user_id."""
    row = conn.execute(
        "SELECT * FROM advice_items WHERE id = ? AND user_id = ?",
        (rec_id, user_id),
    ).fetchone()
    return _row_to_recommendation(row) if row else None


def list_recommendations(
    conn: sqlite3.Connection,
    user_id: str,
    *,
    origin: str | None = None,
    status: str | None = None,
    task_id: str | None = None,
) -> list[Recommendation]:
    """List recommendations for a user with optional filters."""
    query = "SELECT * FROM advice_items WHERE user_id = ?"
    params: list[Any] = [user_id]
    if origin:
        query += " AND origin = ?"
        params.append(origin)
    if status:
        query += " AND status = ?"
        params.append(status)
    if task_id:
        query += " AND task_id = ?"
        params.append(task_id)
    query += " ORDER BY created_at DESC"
    rows = conn.execute(query, tuple(params)).fetchall()
    return [_row_to_recommendation(r) for r in rows]


def update_recommendation_status(
    conn: sqlite3.Connection,
    user_id: str,
    rec_id: str,
    status: str,
    *,
    decided_at: str | None = None,
    decided_by: str = "user",
) -> bool:
    """Update recommendation status strictly filtered by user_id."""
    cur = conn.execute(
        """
        UPDATE advice_items
        SET status = ?, decided_at = ?, decided_by = ?
        WHERE id = ? AND user_id = ?
        """,
        (status, decided_at, decided_by, rec_id, user_id),
    )
    return cur.rowcount > 0

