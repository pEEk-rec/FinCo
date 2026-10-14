"""
Streamlit UI Blueprint for Finance Copilot (PLAN_PHASE1 Section 5.11 / Stage 1.13).

Provides a thin, modular view layer over core financial tools and the execution engine.
All actions flow strictly through `execute_tool(ctx, ...)` or high-level services to preserve
policy enforcement, audit trail immutability, and accounting invariants.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import streamlit as st

from copilot.core.advice import format_inr
from copilot.core.config import PROJECT_ROOT, load_settings
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import (
    get_monthly_review,
    list_accounts,
    list_categories,
    list_transactions,
)
from copilot.governance.policy import load_policy
from copilot.review.builder import build_monthly_review
from copilot.review.renderers import render_markdown
from copilot.tools.executor import ExecutionContext, execute_tool
from copilot.workflow.nodes import ensure_tools_registered


def get_default_db_path() -> Path:
    """Return default SQLite database path from settings."""
    try:
        settings = load_settings()
        return settings.db_path
    except Exception:
        return PROJECT_ROOT / "data" / "copilot.db"


def get_db_connection(db_path: str | Path) -> sqlite3.Connection:
    """Obtain or cache SQLite connection."""
    p = Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = get_connection(p)
    init_db(conn)
    return conn


def create_ui_context(conn: sqlite3.Connection, user_id: str = "u1") -> ExecutionContext:
    """Construct an ExecutionContext with actor='user' for audited UI operations."""
    policy_path = PROJECT_ROOT / "config" / "policy.yaml"
    policy = load_policy(policy_path)
    run_id = f"ui_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    return ExecutionContext(
        conn=conn,
        user_id=user_id,
        run_id=run_id,
        policy=policy,
        actor="user",
    )


# -------------------------------------------------------------------------------------------------
# Tab Renderers
# -------------------------------------------------------------------------------------------------


def render_dashboard(conn: sqlite3.Connection, user_id: str) -> None:
    """Render financial state overview, KPI metrics, and budget statuses."""
    st.header("Financial Overview")

    ctx = create_ui_context(conn, user_id)
    ensure_tools_registered()

    # 1. KPI Metrics
    bal_res = execute_tool(ctx, "get_balance", {})
    balance_paise = bal_res.data.balance_paise if bal_res.ok else 0

    now = datetime.now()
    txs = list_transactions(conn, user_id, "1970-01-01T00:00:00Z", "2030-01-01T00:00:00Z")
    pending_review = [t for t in txs if t.needs_review or t.category_id is None]

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Balance", format_inr(balance_paise))
    with col2:
        st.metric("Total Transactions", str(len(txs)))
    with col3:
        st.metric(
            "Needs Review",
            str(len(pending_review)),
            delta=f"{len(pending_review)} pending",
            delta_color="inverse",
        )
    with col4:
        accounts = list_accounts(conn, user_id)
        st.metric("Connected Accounts", str(len(accounts)))

    st.divider()

    # 2. Budget Performance
    st.subheader("Monthly Budget Performance")
    b_res = execute_tool(ctx, "check_budgets", {"year": now.year, "month": now.month})
    if b_res.ok and b_res.data.statuses:
        for b in b_res.data.statuses:
            col_b1, col_b2, col_b3 = st.columns([3, 1, 1])
            with col_b1:
                pct = min(b.pct_used or 0, 100)
                spent_s = format_inr(b.spent_paise)
                limit_s = format_inr(b.limit_paise)
                st.write(f"**{b.category_id.title()}**: {spent_s} / {limit_s} ({pct}%)")
                st.progress(pct / 100.0)
            with col_b2:
                if b.status == "ok":
                    st.success("OK")
                elif b.status == "warning":
                    st.warning("Warning")
                elif b.status == "projected_exceed":
                    st.warning("Run-rate Alert")
                else:
                    st.error("Exceeded")
            with col_b3:
                st.caption(f"Warn threshold: {b.warn_threshold_pct}%")
    else:
        st.info("No active budgets found. Seed data or configure limits to track performance.")

    st.divider()

    # 3. Recent Transactions
    st.subheader("Recent Transactions")
    recent = txs[:10]
    if recent:
        data = []
        for t in recent:
            amt = (
                format_inr(t.amount_paise)
                if t.direction == "debit"
                else format_inr(abs(t.amount_paise))
            )
            sign = "-" if t.direction == "debit" else "+"
            data.append(
                {
                    "Date": t.occurred_at[:10],
                    "Merchant": t.merchant_normalized or t.merchant_raw,
                    "Category": t.category_id or "uncategorised",
                    "Amount": f"{sign}{amt}",
                    "Review Required": "Yes" if t.needs_review else "No",
                }
            )
        st.dataframe(data, use_container_width=True)
    else:
        st.info("No transactions recorded yet.")


def render_review_queue(conn: sqlite3.Connection, user_id: str) -> None:
    """Render human review queue for unclassified or low-confidence transactions."""
    st.header("Human Review Queue (Human-in-the-Loop)")
    st.write(
        "Transactions flagged with `needs_review=1` require user confirmation. "
        "Approving updates the category with audited user attribution (`category_source='user'`)."
    )

    ctx = create_ui_context(conn, user_id)
    categories = list_categories(conn, user_id)
    category_options = {c.id: f"{c.name} ({c.id})" for c in categories}
    cat_keys = list(category_options.keys())

    all_txs = list_transactions(conn, user_id, "1970-01-01T00:00:00Z", "2030-01-01T00:00:00Z")
    queue_txs = [t for t in all_txs if t.needs_review or t.category_id is None]

    if not queue_txs:
        st.success("Review queue is completely clear! All transactions have verified categories.")
        return

    st.write(f"**{len(queue_txs)} transactions awaiting review:**")

    for tx in queue_txs:
        with st.container(border=True):
            col_info, col_action = st.columns([3, 2])
            with col_info:
                st.write(f"**Merchant:** `{tx.merchant_raw}`")
                amt_str = format_inr(abs(tx.amount_paise))
                st.write(f"**Date:** {tx.occurred_at[:19]} | **Amount:** {amt_str}")
                conf_val = tx.category_confidence or 0.0
                st.caption(f"Proposed: `{tx.category_id or 'none'}` (confidence: {conf_val})")

            with col_action:
                default_idx = cat_keys.index(tx.category_id) if tx.category_id in cat_keys else 0
                chosen_cat = st.selectbox(
                    "Select Category",
                    options=cat_keys,
                    format_func=lambda k: category_options[k],
                    index=default_idx,
                    key=f"cat_select_{tx.id}",
                )
                remember = st.checkbox(
                    "Remember rule for merchant",
                    value=False,
                    key=f"rem_{tx.id}",
                )

                if st.button("Confirm / Recategorize", key=f"btn_recat_{tx.id}", type="primary"):
                    res = execute_tool(
                        ctx,
                        "recategorize_transaction",
                        {
                            "transaction_id": tx.id,
                            "new_category_id": chosen_cat,
                            "remember": remember,
                        },
                    )
                    if res.ok:
                        conn.execute(
                            "UPDATE transactions SET needs_review = 0 WHERE id = ? AND user_id = ?",
                            (tx.id, user_id),
                        )
                        conn.commit()
                        st.success(f"Recategorized to '{chosen_cat}'!")
                        st.rerun()
                    else:
                        st.error(f"Failed to recategorize: {res.error.message}")


def render_advice_drafts(conn: sqlite3.Connection, user_id: str) -> None:
    """Render pending financial advice items awaiting user approval/rejection."""
    st.header("Financial Advice Approvals")
    st.write(
        "Advice generated by the agent is held in `draft` status until approved or rejected. "
        "All decisions are audited in compliance with the governance firewall."
    )

    ctx = create_ui_context(conn, user_id)
    rows = conn.execute(
        """
        SELECT id, text, status, created_at
        FROM advice_items
        WHERE user_id = ?
        ORDER BY created_at DESC
        """,
        (user_id,),
    ).fetchall()

    if not rows:
        st.info("No advice items recorded yet. Run the workflow or generate recommendations.")
        return

    for adv_id, text, status, created_at in rows:
        with st.container(border=True):
            col_t, col_s = st.columns([4, 1])
            with col_t:
                st.write(f"**Advice ID:** `{adv_id}`")
                st.write(f"> {text}")
                st.caption(f"Created: {created_at}")
            with col_s:
                if status == "approved":
                    st.success("APPROVED")
                elif status == "rejected":
                    st.error("REJECTED")
                else:
                    st.warning("DRAFT")
                    col_b1, col_b2 = st.columns(2)
                    with col_b1:
                        if st.button("Approve", key=f"app_{adv_id}", type="primary"):
                            res = execute_tool(
                                ctx,
                                "decide_advice",
                                {"advice_id": adv_id, "decision": "approved"},
                            )
                            if res.ok:
                                st.rerun()
                            else:
                                st.error(res.error.message)
                    with col_b2:
                        if st.button("Reject", key=f"rej_{adv_id}"):
                            res = execute_tool(
                                ctx,
                                "decide_advice",
                                {"advice_id": adv_id, "decision": "rejected"},
                            )
                            if res.ok:
                                st.rerun()
                            else:
                                st.error(res.error.message)


def render_monthly_review(conn: sqlite3.Connection, user_id: str) -> None:
    """Render versioned monthly reviews and markdown reports."""
    st.header("Monthly Review & Report Viewer")
    st.write(
        "Generate and view immutable, versioned financial review summaries "
        "with verified numerical grounding."
    )

    now = datetime.now()
    col_yr, col_mo, col_btn = st.columns([1, 1, 2])
    with col_yr:
        year = st.number_input("Year", min_value=2020, max_value=2030, value=now.year)
    with col_mo:
        month = st.number_input("Month", min_value=1, max_value=12, value=now.month)
    with col_btn:
        st.write("")
        st.write("")
        generate = st.button("Generate / Rebuild Monthly Review", type="primary")

    if generate:
        run_id = f"review_ui_{year}_{month:02d}_{datetime.now().strftime('%H%M%S')}"
        review_data = build_monthly_review(conn, user_id, int(year), int(month), run_id)
        st.session_state["active_review"] = review_data
        st.success(f"Generated Monthly Review (Version {review_data.version})!")

    review = st.session_state.get("active_review")
    if not review:
        review = get_monthly_review(conn, user_id, int(year), int(month))

    if review:
        st.info(
            f"Viewing Review for **{review.period}** | "
            f"Version: **v{review.version}** | Run ID: `{review.run_id}`"
        )
        rendered_md = render_markdown(review)
        st.markdown(rendered_md)
    else:
        st.info("Click 'Generate / Rebuild Monthly Review' to assemble the review document.")


def render_audit_trail(conn: sqlite3.Connection, user_id: str) -> None:
    """Render immutable audit log and reversible event undo controls."""
    st.header("Audit Trail & Reversibility")
    st.write(
        "Complete, append-only log of all system actions, human overrides, and automated changes."
    )

    ctx = create_ui_context(conn, user_id)
    events = conn.execute(
        """
        SELECT id, event_type, actor, reason, entity_type, entity_id,
               occurred_at, before_json, after_json
        FROM audit_events
        WHERE user_id = ?
        ORDER BY occurred_at DESC
        LIMIT 30
        """,
        (user_id,),
    ).fetchall()

    if not events:
        st.info("Audit log is currently empty.")
        return

    for ev in events:
        eid, etype, actor, reason, ent_type, ent_id, occurred_at, b_data, a_data = ev
        is_rev = bool(b_data)
        with st.container(border=True):
            col_e1, col_e2 = st.columns([4, 1])
            with col_e1:
                st.write(
                    f"**Event:** `{etype}` | **Actor:** `{actor}` | "
                    f"**Entity:** `{ent_type}:{ent_id}`"
                )
                st.caption(f"ID: `{eid}` | Time: {occurred_at} | Reason: {reason}")
                if b_data or a_data:
                    with st.expander("State Diff (Before / After)"):
                        st.json(
                            {
                                "before": json.loads(b_data) if b_data else None,
                                "after": json.loads(a_data) if a_data else None,
                            }
                        )
            with col_e2:
                if is_rev:
                    st.success("Reversible")
                    if st.button("Undo", key=f"undo_{eid}"):
                        u_res = execute_tool(ctx, "undo", {"audit_event_id": eid})
                        if u_res.ok:
                            st.success("Undone successfully!")
                            st.rerun()
                        else:
                            st.error(f"Undo failed: {u_res.error.message}")
                else:
                    st.caption("Immutable")


# -------------------------------------------------------------------------------------------------
# Main Streamlit App Entrypoint
# -------------------------------------------------------------------------------------------------


def main() -> None:
    """Streamlit application layout and navigation."""
    st.set_page_config(
        page_title="Finance Copilot Blueprint",
        page_icon="💳",
        layout="wide",
    )

    st.sidebar.title("💳 Finance Copilot")
    st.sidebar.caption("Minimal UI Blueprint (Stage 1.13)")

    db_default = str(get_default_db_path())
    db_path = st.sidebar.text_input("Database Path", value=db_default)
    user_id = st.sidebar.text_input("User ID", value="u1")

    try:
        conn = get_db_connection(db_path)
    except Exception as exc:
        st.sidebar.error(f"Failed to connect to database: {exc}")
        return

    st.sidebar.divider()
    nav = st.sidebar.radio(
        "Navigation",
        [
            "📊 Financial Dashboard",
            "📋 Review Queue (HITL)",
            "💡 Advice Approvals",
            "📑 Monthly Review Viewer",
            "📜 Audit Trail & Undo",
        ],
    )

    if nav == "📊 Financial Dashboard":
        render_dashboard(conn, user_id)
    elif nav == "📋 Review Queue (HITL)":
        render_review_queue(conn, user_id)
    elif nav == "💡 Advice Approvals":
        render_advice_drafts(conn, user_id)
    elif nav == "📑 Monthly Review Viewer":
        render_monthly_review(conn, user_id)
    elif nav == "📜 Audit Trail & Undo":
        render_audit_trail(conn, user_id)


if __name__ == "__main__":
    main()
