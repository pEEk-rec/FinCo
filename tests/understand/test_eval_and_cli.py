"""`copilot eval --categorise` and the `copilot understand` commands."""

import json

from typer.testing import CliRunner

from copilot.cli.main import app
from copilot.eval.categorise import (
    build_weeks,
    render_markdown,
    run_after,
    run_before,
    run_categorise_evaluation,
    write_report,
)

runner = CliRunner()


def test_the_same_seed_gives_the_same_world_and_the_same_answers():
    a, shops, _ = build_weeks(11)
    b, _, _ = build_weeks(11)
    assert [t.raw for t in a] == [t.raw for t in b]
    r1, _ = run_after(a, shops, 11)
    r2, _ = run_after(b, shops, 11)
    assert [x.correct for x in r1.rows] == [x.correct for x in r2.rows]


def test_both_engines_see_exactly_the_same_payments():
    txns, shops, _ = build_weeks(23)
    before = run_before(txns, shops, 23)
    after, _ = run_after(txns, shops, 23)
    assert [r.tx.id for r in before.rows] == [r.tx.id for r in after.rows]


def test_the_evaluation_meets_its_pre_declared_targets_and_never_labels_a_person(tmp_path):
    report = run_categorise_evaluation()
    failed = [c.name for c in report.checks if not c.passed]
    assert not failed, failed
    assert report.after["person_applied"] == 0
    out = write_report(report, tmp_path / "r.md")
    text = out.read_text(encoding="utf-8")
    assert text == render_markdown(report) and "simulated" in text and "Not measured here" in text


def test_fewer_questions_buys_coverage_with_accuracy_and_more_questions_does_the_reverse():
    report = run_categorise_evaluation()
    more, fewer = report.curve["more_questions"], report.curve["fewer_questions"]
    assert fewer["coverage_all"] > more["coverage_all"]
    assert fewer["accuracy"] <= more["accuracy"]


def test_the_understand_commands_run_end_to_end(tmp_path):
    db = str(tmp_path / "u.db")
    assert runner.invoke(app, ["init-db", "--db", db]).exit_code == 0
    assert runner.invoke(app, ["seed", "--db", db, "--months", "1", "--seed", "42"]).exit_code == 0
    run = runner.invoke(app, ["understand", "run", "--db", db])
    assert run.exit_code == 0, run.output
    qs = runner.invoke(app, ["understand", "questions", "--db", db, "--json"])
    assert qs.exit_code == 0, qs.output
    questions = json.loads(qs.output)["questions"]
    if questions:  # answer the first, then ask why for one of its payments
        q = questions[0]
        cat = "food"
        ans = runner.invoke(
            app, ["understand", "answer", "--shop", q["entity_id"], "--category", cat, "--db", db]
        )
        assert ans.exit_code == 0, ans.output
    assert runner.invoke(app, ["understand", "rules", "--db", db]).exit_code == 0


def test_swapping_the_model_changes_the_first_guess_not_the_labels():
    report = run_categorise_evaluation()
    strong, wrong = report.swap["strong model"], report.swap["always-wrong model"]
    assert wrong["accuracy"] >= 0.95, "a bad model must not cause wrong labels"
    assert abs(wrong["accuracy"] - strong["accuracy"]) <= 0.02
    assert wrong["guess_hit_rate"] < strong["guess_hit_rate"], (
        "the model only improves the first suggestion"
    )
