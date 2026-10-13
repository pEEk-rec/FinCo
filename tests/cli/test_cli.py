"""
Comprehensive CLI tests for Finance Copilot (Stage 1.11).
Tests every command, argument, flag, and error branch via Typer CliRunner.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from copilot.cli.main import app

runner = CliRunner()


@pytest.fixture
def test_db_path(tmp_path: Path) -> str:
    return str(tmp_path / "cli_test.db")


def seed_and_approve(test_db_path: str, months: int = 2, seed: int = 42) -> None:
    runner.invoke(app, ["init-db", "--db", test_db_path])
    runner.invoke(
        app,
        ["seed", "--db", test_db_path, "--months", str(months), "--seed", str(seed)],
    )
    # Approve pending consent
    res = runner.invoke(app, ["consent", "list", "--db", test_db_path, "--json"])
    consents = json.loads(res.output)
    for c in consents:
        if c.get("status") == "pending":
            runner.invoke(app, ["consent", "approve", c["id"], "--db", test_db_path])


def test_cli_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Personal Finance & Budgeting Copilot CLI" in result.output
    assert "init-db" in result.output
    assert "seed" in result.output
    assert "run" in result.output
    assert "review-month" in result.output
    assert "consent" in result.output


def test_init_db(test_db_path: str) -> None:
    result = runner.invoke(app, ["init-db", "--db", test_db_path])
    assert result.exit_code == 0
    assert "Database initialized" in result.output
    assert Path(test_db_path).exists()


def test_seed(test_db_path: str) -> None:
    init_res = runner.invoke(app, ["init-db", "--db", test_db_path])
    assert init_res.exit_code == 0

    seed_res = runner.invoke(
        app, ["seed", "--db", test_db_path, "--months", "2", "--seed", "123"]
    )
    assert seed_res.exit_code == 0
    assert "Seeded environment for user" in seed_res.output
    assert "Accounts:" in seed_res.output


def test_consent_lifecycle(test_db_path: str) -> None:
    runner.invoke(app, ["init-db", "--db", test_db_path])
    runner.invoke(app, ["seed", "--db", test_db_path])

    # List consents
    list_res = runner.invoke(app, ["consent", "list", "--db", test_db_path])
    assert list_res.exit_code == 0
    assert "Bank Consents" in list_res.output

    # List as JSON
    list_json_res = runner.invoke(app, ["consent", "list", "--db", test_db_path, "--json"])
    assert list_json_res.exit_code == 0
    consents = json.loads(list_json_res.output)
    assert len(consents) >= 1
    consent_id = consents[0]["id"]
    assert consents[0]["status"] == "pending"

    # Approve consent
    approve_res = runner.invoke(app, ["consent", "approve", consent_id, "--db", test_db_path])
    assert approve_res.exit_code == 0
    assert "approved" in approve_res.output

    # Revoke consent
    revoke_res = runner.invoke(
        app, ["consent", "revoke", consent_id, "--db", test_db_path, "--reason", "user request"]
    )
    assert revoke_res.exit_code == 0
    assert "revoked" in revoke_res.output

    # Create new consent
    create_res = runner.invoke(
        app, ["consent", "create", "acc_seed_1", "--db", test_db_path, "--institution", "HDFC"]
    )
    assert create_res.exit_code == 0
    assert "Created consent" in create_res.output

    # Approve invalid consent
    bad_approve = runner.invoke(app, ["consent", "approve", "nonexistent_c", "--db", test_db_path])
    assert bad_approve.exit_code != 0
    assert "not found" in bad_approve.output or "Error" in bad_approve.output


def test_run_workflow(test_db_path: str) -> None:
    seed_and_approve(test_db_path, months=2)

    # Run workflow with auto-approve
    run_res = runner.invoke(
        app, ["run", "--db", test_db_path, "--auto-approve", "--year", "2024", "--month", "2"]
    )
    assert run_res.exit_code == 0
    assert "Workflow execution completed" in run_res.output
    assert "WORKFLOW RUN TRACE" in run_res.output

    # Run when consent is revoked fails gracefully
    list_json_res = runner.invoke(app, ["consent", "list", "--db", test_db_path, "--json"])
    consents = json.loads(list_json_res.output)
    for c in consents:
        runner.invoke(app, ["consent", "revoke", c["id"], "--db", test_db_path])

    run_revoked = runner.invoke(app, ["run", "--db", test_db_path, "--auto-approve"])
    assert run_revoked.exit_code != 0
    assert "consent" in run_revoked.output.lower()


def test_transactions_and_correction_and_undo(test_db_path: str) -> None:
    seed_and_approve(test_db_path, months=2)
    runner.invoke(
        app, ["run", "--db", test_db_path, "--auto-approve", "--year", "2024", "--month", "2"]
    )

    # List txns table
    txns_res = runner.invoke(app, ["txns", "--db", test_db_path, "--limit", "10"])
    assert txns_res.exit_code == 0
    assert "Transactions" in txns_res.output

    # List txns as JSON
    txns_json_res = runner.invoke(app, ["txns", "--db", test_db_path, "--json", "--limit", "5"])
    assert txns_json_res.exit_code == 0
    txns = json.loads(txns_json_res.output)
    assert len(txns) > 0
    target_txn = txns[0]
    txn_id = target_txn["id"]

    # Filter needs-review
    nr_res = runner.invoke(app, ["txns", "--db", test_db_path, "--needs-review"])
    assert nr_res.exit_code == 0

    # User correction
    correct_res = runner.invoke(
        app, ["correct", txn_id, "cat_dining", "--db", test_db_path, "--remember"]
    )
    assert correct_res.exit_code == 0
    assert "updated to category" in correct_res.output

    # List audit trail to get the correction event id
    audit_json = runner.invoke(app, ["audit", "--db", test_db_path, "--json", "--limit", "10"])
    assert audit_json.exit_code == 0
    events = json.loads(audit_json.output)
    user_override_event = next(
        (e for e in events if e.get("event_type") == "transaction_recategorized"),
        None,
    )
    assert user_override_event is not None
    audit_id = user_override_event["id"]

    # Undo the correction
    undo_res = runner.invoke(app, ["undo", audit_id, "--db", test_db_path])
    assert undo_res.exit_code == 0
    assert "successfully" in undo_res.output

    # Test error cases
    bad_correct = runner.invoke(app, ["correct", "missing_txn", "food", "--db", test_db_path])
    assert bad_correct.exit_code != 0

    bad_undo = runner.invoke(app, ["undo", "missing_audit_evt", "--db", test_db_path])
    assert bad_undo.exit_code != 0


def test_undo_batch(test_db_path: str) -> None:
    seed_and_approve(test_db_path, months=2)
    runner.invoke(
        app, ["run", "--db", test_db_path, "--auto-approve", "--year", "2024", "--month", "2"]
    )

    # Audit list
    audit_json = runner.invoke(app, ["audit", "--db", test_db_path, "--json"])
    assert audit_json.exit_code == 0
    events = json.loads(audit_json.output)
    auto_cat_event = next(
        (e for e in events if e.get("event_type") == "auto_categorise"),
        None,
    )

    if auto_cat_event and auto_cat_event.get("batch_id"):
        batch_id = auto_cat_event["batch_id"]
        undo_batch_res = runner.invoke(app, ["undo-batch", batch_id, "--db", test_db_path])
        assert undo_batch_res.exit_code == 0
        assert "Batch undo successful" in undo_batch_res.output

    # Invalid batch id
    bad_batch = runner.invoke(app, ["undo-batch", "nonexistent_batch", "--db", test_db_path])
    assert bad_batch.exit_code != 0


def test_budgets_forecast_anomalies_recurring_state(test_db_path: str) -> None:
    seed_and_approve(test_db_path, months=2)
    runner.invoke(
        app, ["run", "--db", test_db_path, "--auto-approve", "--year", "2024", "--month", "2"]
    )

    # Budgets
    b_res = runner.invoke(app, ["budgets", "--db", test_db_path])
    assert b_res.exit_code == 0
    assert "Budget Performance" in b_res.output

    b_json = runner.invoke(app, ["budgets", "--db", test_db_path, "--json"])
    assert b_json.exit_code == 0
    assert isinstance(json.loads(b_json.output), list)

    # Forecast
    f_res = runner.invoke(app, ["forecast", "--db", test_db_path, "--month", "2024-02"])
    assert f_res.exit_code == 0
    assert "Forecast" in f_res.output

    f_json = runner.invoke(app, ["forecast", "--db", test_db_path, "--month", "2024-02", "--json"])
    assert f_json.exit_code == 0
    f_obj = json.loads(f_json.output)
    assert "projected_total" in f_obj

    # Forecast invalid month
    bad_f = runner.invoke(app, ["forecast", "--db", test_db_path, "--month", "bad-date"])
    assert bad_f.exit_code != 0
    assert "YYYY-MM" in bad_f.output

    # Anomalies
    a_res = runner.invoke(app, ["anomalies", "--db", test_db_path, "--month", "2024-02"])
    assert a_res.exit_code == 0
    assert "Detected Anomalies" in a_res.output

    a_json = runner.invoke(
        app, ["anomalies", "--db", test_db_path, "--month", "2024-02", "--json"]
    )
    assert a_json.exit_code == 0
    assert isinstance(json.loads(a_json.output), list)

    # Recurring
    r_res = runner.invoke(app, ["recurring", "--db", test_db_path])
    assert r_res.exit_code == 0
    assert "recurring" in r_res.output.lower()

    r_json = runner.invoke(app, ["recurring", "--db", test_db_path, "--json"])
    assert r_json.exit_code == 0
    assert isinstance(json.loads(r_json.output), list)

    # State
    s_res = runner.invoke(app, ["state", "--db", test_db_path, "--month", "2024-02"])
    assert s_res.exit_code == 0
    assert "Financial State Snapshot" in s_res.output

    s_json = runner.invoke(app, ["state", "--db", test_db_path, "--month", "2024-02", "--json"])
    assert s_json.exit_code == 0
    assert "balance_paise" in json.loads(s_json.output)


def test_review_month_cli(test_db_path: str, tmp_path: Path) -> None:
    seed_and_approve(test_db_path, months=2)
    runner.invoke(
        app, ["run", "--db", test_db_path, "--auto-approve", "--year", "2024", "--month", "2"]
    )

    reports_dir = tmp_path / "custom_reports"

    rev_res = runner.invoke(
        app,
        [
            "review-month",
            "2024-02",
            "--db",
            test_db_path,
            "--output-dir",
            str(reports_dir),
        ],
    )
    assert rev_res.exit_code == 0
    assert "Generated Monthly Review" in rev_res.output

    # Check files created
    assert (reports_dir / "2024-02.md").exists()
    assert (reports_dir / "2024-02.html").exists()

    # Invalid period
    bad_rev = runner.invoke(app, ["review-month", "2026", "--db", test_db_path])
    assert bad_rev.exit_code != 0
    assert "YYYY-MM" in bad_rev.output


def test_trace_cmd() -> None:
    # Nonexistent trace
    res = runner.invoke(app, ["trace", "nonexistent_run_99999"])
    assert res.exit_code != 0
    assert "No execution trace found" in res.output or "not found" in res.output


def test_eval_cmd(test_db_path: str) -> None:
    runner.invoke(app, ["init-db", "--db", test_db_path])
    res = runner.invoke(app, ["eval", "--db", test_db_path])
    assert res.exit_code == 0
    assert "Evaluation" in res.output
