"""
Unit tests for the minimal Streamlit UI blueprint (Stage 1.13).
"""

from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock, patch

from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_account, insert_user
from copilot.models.domain import Account, User
from copilot.ui.app import (
    create_ui_context,
    get_db_connection,
    get_default_db_path,
    render_advice_drafts,
    render_audit_trail,
    render_dashboard,
    render_monthly_review,
    render_review_queue,
)


def test_ui_context_creation():
    conn = get_connection(":memory:")
    init_db(conn)
    ctx = create_ui_context(conn, user_id="u1")
    assert ctx.user_id == "u1"
    assert ctx.actor == "user"
    assert ctx.run_id.startswith("ui_")
    conn.close()


def test_get_default_db_path():
    path = get_default_db_path()
    assert path.name.endswith(".db")


def test_get_db_connection_in_memory():
    conn = get_db_connection(":memory:")
    assert isinstance(conn, sqlite3.Connection)
    # verify tables exist
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='transactions'"
    ).fetchone()
    assert row is not None
    conn.close()


@patch("streamlit.header")
@patch("streamlit.metric")
@patch("streamlit.columns")
@patch("streamlit.divider")
@patch("streamlit.subheader")
@patch("streamlit.info")
def test_render_dashboard_headless(
    mock_info,
    mock_subheader,
    mock_divider,
    mock_columns,
    mock_metric,
    mock_header,
):
    conn = get_connection(":memory:")
    init_db(conn)
    insert_user(conn, User(id="u1", created_at="2024-01-01T00:00:00Z"))
    insert_account(
        conn,
        Account(
            id="a1",
            user_id="u1",
            name="Checking",
            opening_balance_paise=100000,
            created_at="2024-01-01T00:00:00Z",
        ),
    )

    mock_col = MagicMock()
    mock_columns.return_value = (mock_col, mock_col, mock_col, mock_col)

    render_dashboard(conn, "u1")
    mock_header.assert_called_with("Financial Overview")
    conn.close()


@patch("streamlit.header")
@patch("streamlit.write")
@patch("streamlit.success")
def test_render_review_queue_empty_queue(mock_success, mock_write, mock_header):
    conn = get_connection(":memory:")
    init_db(conn)
    insert_user(conn, User(id="u1", created_at="2024-01-01T00:00:00Z"))

    render_review_queue(conn, "u1")
    mock_header.assert_called_with("Human Review Queue (Human-in-the-Loop)")
    mock_success.assert_called()
    conn.close()


@patch("streamlit.header")
@patch("streamlit.write")
@patch("streamlit.info")
def test_render_advice_drafts_empty(mock_info, mock_write, mock_header):
    conn = get_connection(":memory:")
    init_db(conn)
    insert_user(conn, User(id="u1", created_at="2024-01-01T00:00:00Z"))

    render_advice_drafts(conn, "u1")
    mock_header.assert_called_with("Financial Advice Approvals")
    mock_info.assert_called()
    conn.close()


@patch("streamlit.header")
@patch("streamlit.write")
@patch("streamlit.info")
def test_render_audit_trail_empty(mock_info, mock_write, mock_header):
    conn = get_connection(":memory:")
    init_db(conn)
    insert_user(conn, User(id="u1", created_at="2024-01-01T00:00:00Z"))

    render_audit_trail(conn, "u1")
    mock_header.assert_called_with("Audit Trail & Reversibility")
    mock_info.assert_called()
    conn.close()


@patch("streamlit.header")
@patch("streamlit.write")
@patch("streamlit.columns")
@patch("streamlit.number_input")
@patch("streamlit.button")
@patch("streamlit.info")
def test_render_monthly_review_empty(
    mock_info,
    mock_btn,
    mock_num,
    mock_cols,
    mock_write,
    mock_header,
):
    conn = get_connection(":memory:")
    init_db(conn)
    insert_user(conn, User(id="u1", created_at="2024-01-01T00:00:00Z"))

    mock_c = MagicMock()
    mock_cols.return_value = (mock_c, mock_c, mock_c)
    mock_btn.return_value = False
    mock_num.return_value = 2024

    render_monthly_review(conn, "u1")
    mock_header.assert_called_with("Monthly Review & Report Viewer")
    mock_info.assert_called()
    conn.close()
