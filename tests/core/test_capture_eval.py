"""`copilot eval --capture`: deterministic, honest about what it does not measure."""

from copilot.eval.harness_capture import (
    aggregate,
    evaluate_corpus,
    evaluate_simulated,
    render_markdown,
    run_capture_evaluation,
    write_report,
)


def test_the_corpus_parses_and_every_otp_and_stranger_is_dropped():
    c = evaluate_corpus()
    assert all(acc == 1.0 for acc in c["accuracy_by_bank"].values())
    assert c["unparsed"] == 0 and c["dropped"] == c["must_drop"] > 0


def test_a_run_is_deterministic_for_a_seed():
    assert evaluate_simulated(7) == evaluate_simulated(7)


def test_pooling_adds_counts_rather_than_averaging_rates():
    a, b = evaluate_simulated(7), evaluate_simulated(42)
    pooled = aggregate([a, b])
    assert pooled["payments"] == a["payments"] + b["payments"]
    assert pooled["asked"] == a["asked"] + b["asked"]


def test_the_evaluation_passes_its_targets_and_never_double_counts(tmp_path):
    report = run_capture_evaluation()
    failed = [c.name for c in report.checks if not c.passed]
    assert not failed, failed
    assert report.sections["simulated"]["double_count_violations"] == 0
    out = write_report(report, tmp_path / "r.md")
    text = out.read_text(encoding="utf-8")
    assert "Not measured here" in text and "real, redacted SMS export" in text
    assert text == render_markdown(report)
