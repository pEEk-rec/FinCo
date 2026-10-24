"""
The Phase 4 demo journey through the real CLI on a seeded database, nothing pre-inserted
(docs/demo_script_phase4.md). Each test guards a defect the demo run found.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from copilot.cli.main import app

runner = CliRunner()
NOW = "2024-05-01T10:00:00+05:30"


def _run(*args: str) -> str:
    res = runner.invoke(app, list(args))
    assert res.exit_code == 0, res.output
    return res.output


def _scalar(db: str, sql: str):
    conn = sqlite3.connect(db)
    try:
        return conn.execute(sql).fetchone()[0]
    finally:
        conn.close()


@pytest.fixture
def journey_db(tmp_path: Path) -> str:
    db = str(tmp_path / "journey.db")
    _run("init-db", "--db", db)
    _run("seed", "--db", db, "--months", "4", "--seed", "42")
    _run("consent", "approve", "consent_seed_u1_42", "--db", db)
    _run("run", "--db", db, "--year", "2024", "--month", "2")
    conn = sqlite3.connect(db)
    conn.execute("UPDATE budgets SET limit_paise = 300000 WHERE category_id = 'food'")
    conn.commit()
    conn.close()
    return db


def test_run_keeps_what_the_graph_wrote(journey_db: str):
    """Categories chosen during `copilot run` are still there afterwards."""
    assert (
        _scalar(journey_db, "SELECT COUNT(*) FROM transactions WHERE category_id IS NOT NULL") > 100
    )


def test_offers_are_generated_from_the_cli_and_carry_a_reason(journey_db: str):
    out = _run("challenges", "offers", "--clock", NOW, "--db", journey_db, "--json")
    offers = json.loads(out)
    assert offers and offers[0]["template_code"] == "delivery_cap"
    table = _run("challenges", "offers", "--clock", NOW, "--db", journey_db)
    assert "usual" in table, "the reason column must show the observational statement"


def test_a_dated_exception_pauses_the_experiment_and_feedback_teaches_the_loop(journey_db: str):
    offer = json.loads(_run("challenges", "offers", "--clock", NOW, "--db", journey_db, "--json"))[
        0
    ]
    _run("challenges", "accept", offer["id"], "--clock", NOW, "--db", journey_db)
    exp = _scalar(journey_db, "SELECT id FROM experiments LIMIT 1")

    _run(
        "memory", "exception", "--category", "food", "--reason", "travel",
        "--from", "2024-05-03", "--to", "2024-05-05", "--db", journey_db,
    )  # fmt: skip
    _run("experiments", "tick", "--clock", "2024-05-04T12:00:00+05:30", "--db", journey_db)
    for code in ("exception_overlap_auto_pause", "exception_overlap_extend"):
        assert (
            _scalar(
                journey_db,
                f"SELECT COUNT(*) FROM adjustment_proposals WHERE reason_code = '{code}'",
            )
            == 1
        )

    _run("experiments", "tick", "--clock", "2024-05-12T12:00:00+05:30", "--db", journey_db)
    _run("experiments", "review", exp, "--db", journey_db)
    assert _scalar(journey_db, "SELECT COUNT(*) FROM feedback_stats") == 0

    for _ in range(2):  # a second submission must not teach the loop twice
        _run(
            "experiments", "feedback", exp, "--difficulty", "2", "--helpful", "--repeat",
            "--clock", "2024-05-12T13:00:00+05:30", "--db", journey_db,
        )  # fmt: skip
    assert (
        _scalar(
            journey_db, "SELECT alpha_milli FROM feedback_stats WHERE subject_key = 'delivery_cap'"
        )
        == 3000
    )
    assert (
        _scalar(journey_db, "SELECT COUNT(*) FROM memory_items WHERE kind = 'experiment_outcome'")
        == 1
    )


def test_a_bad_exception_range_is_refused(journey_db: str):
    res = runner.invoke(
        app,
        ["memory", "exception", "--category", "food", "--reason", "travel",
         "--from", "2024-05-05", "--to", "2024-05-03", "--db", journey_db],
    )  # fmt: skip
    assert res.exit_code == 1
