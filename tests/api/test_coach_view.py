"""The Challenges and Progress screens read one typed, fully labelled model."""

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from copilot.api.app import create_app
from copilot.api.state import ApiState
from copilot.cli.main import app as cli
from copilot.core.labels import format_metric, metric_label, metric_unit
from copilot.tools.registry import clear_registry

runner = CliRunner()
NOW = "2024-05-01T10:00:00+05:30"
AUTH = {"Authorization": "Bearer t"}


def _cli(*args):
    res = runner.invoke(cli, list(args))
    assert res.exit_code == 0, res.output
    return res.output


@pytest.fixture
def journey(tmp_path):
    clear_registry()
    db = str(tmp_path / "c.db")
    _cli("init-db", "--db", db)
    _cli("seed", "--db", db, "--months", "4", "--seed", "42")
    _cli("consent", "approve", "consent_seed_u1_42", "--db", db)
    _cli("run", "--db", db, "--year", "2024", "--month", "2")
    conn = sqlite3.connect(db)
    conn.execute("UPDATE budgets SET limit_paise = 300000 WHERE category_id = 'food'")
    conn.commit()
    conn.close()
    return db


def _client(db, clock):
    from copilot.core.timeutil import from_utc_iso

    st = ApiState(db_path=__import__("pathlib").Path(db), clock=from_utc_iso(clock), token="t", llm=None)
    return TestClient(create_app(st))


def test_labels_and_units_never_show_raw_codes_or_wrong_units():
    assert metric_label("merchant_group_spend") == "spending on these merchants"
    assert metric_unit("txn_count") == "count" and format_metric("txn_count", 12) == "12"
    assert format_metric("no_spend_days", 1) == "1 day"
    assert format_metric("tagging_completeness", 8750) == "87%"
    assert format_metric("category_spend", 35000) == "₹350"


def test_the_view_follows_a_challenge_from_offer_to_review(journey):
    client = _client(journey, "2024-05-01T04:30:00Z")
    gen = json.loads(_cli("challenges", "offers", "--clock", NOW, "--db", journey, "--json"))
    view = client.get("/api/coach", headers=AUTH).json()
    o = view["offers"][0]
    assert o["id"] == gen[0]["id"] and o["unit"] == "money"
    assert "merchant_group_spend" not in o["reason"] and o["reason"].startswith("Your usual")

    _cli("challenges", "accept", o["id"], "--clock", NOW, "--db", journey)
    mid = _client(journey, "2024-05-04T04:30:00Z").get("/api/coach", headers=AUTH).json()
    assert mid["offers"] == [] and len(mid["active"]) == 1
    a = mid["active"][0]
    assert a["total_days"] == 7 and a["usual"] and a["history"] and a["pace"] in (
        "ahead", "on_pace", "behind"
    )
    assert "_" not in a["hypothesis"].split("then")[1][:40]

    _cli("experiments", "tick", "--clock", "2024-05-12T12:00:00+05:30", "--db", journey)
    done = _client(journey, "2024-05-12T07:00:00Z").get("/api/coach", headers=AUTH).json()
    rv = done["reviews"][0]
    assert rv["headline"].startswith("₹") and rv["feedback_given"] is False
    assert any(b["code"] == "first_experiment_reviewed" for b in done["progress"]["badges"])
    assert done["progress"]["locked_badges"], "unearned badges are listed so they can be aimed at"
    level = done["progress"]["level"]
    assert 0 <= level["progress_bp"] <= 10000 and level["number"] >= 1


def test_a_new_user_gets_an_empty_but_valid_view(tmp_path):
    clear_registry()
    db = tmp_path / "e.db"
    _cli("init-db", "--db", str(db))
    view = _client(str(db), "2024-05-01T04:30:00Z").get("/api/coach", headers=AUTH)
    assert view.status_code == 200
    body = view.json()
    assert body["offers"] == [] and body["active"] == [] and body["reviews"] == []
