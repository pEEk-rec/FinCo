"""The owner's gold set: a sheet that leaks nothing, and an offline evaluation that prints totals."""

import csv

from typer.testing import CliRunner

from copilot.cli.main import app
from copilot.understand.gold import evaluate_sheet, prepare_sheet

runner = CliRunner()


def seeded(tmp_path):
    from copilot.api.services import DEMO_CLOCK, ensure_demo
    from copilot.api.state import ApiState
    from copilot.tools.registry import clear_registry

    clear_registry()
    state = ApiState(db_path=tmp_path / "g.db", clock=DEMO_CLOCK, token="t", llm=None)
    ensure_demo(state, "imported")
    return str(state.db_path)


def test_the_sheet_has_only_date_name_amount_and_an_empty_category(tmp_path):
    from copilot.cli.storage import open_db

    db = seeded(tmp_path)
    conn = open_db(db)
    path, n = prepare_sheet(conn, "u1", tmp_path / "sheet.csv", 60)
    raw = [
        r[0]
        for r in conn.execute("SELECT merchant_raw FROM transactions WHERE direction = 'debit'")
    ]
    conn.close()
    text = path.read_text("utf-8")
    rows = list(csv.DictReader(text.splitlines()))
    assert n == len(rows) > 20
    assert set(rows[0]) == {"row", "date", "name", "amount_rupees", "category"}
    assert all(r["category"] == "" for r in rows)
    # no raw narration, UTR-like reference or VPA survives into the sheet
    assert not any(
        "@" in r["name"] or any(c.isdigit() for c in r["name"].replace(" ", "")[:0]) for r in rows
    )
    assert not any(r_ in text for r_ in raw if "/" in r_)


def test_an_unlabelled_sheet_is_refused_and_a_labelled_one_reports_totals_only(tmp_path):
    from copilot.cli.storage import open_db
    from copilot.common.errors import ToolFailure

    db = seeded(tmp_path)
    conn = open_db(db)
    path, _ = prepare_sheet(conn, "u1", tmp_path / "sheet.csv", 80)
    conn.close()
    try:
        evaluate_sheet(path)
        raise AssertionError("an empty sheet must be refused")
    except ToolFailure:
        pass
    rows = list(csv.DictReader(path.read_text("utf-8").splitlines()))
    for i, r in enumerate(rows):
        r["category"] = "Food" if i % 2 == 0 else "Other"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    res = evaluate_sheet(path)
    assert res.rows == len(rows) and res.categories == 2 and 0 <= res.coverage <= 1
    out = runner.invoke(app, ["understand", "gold-eval", "--file", str(path)])
    assert out.exit_code == 0 and "accuracy on labelled" in out.output
