from copilot.core.categorisation import CategorizationRule
from copilot.core.pipeline import run_categorization_pipeline
from copilot.llm.client import FakeLLMClient
from tests.tools.test_categorisation_tools import ctx  # noqa: F401


def test_pipeline_overrides_win(ctx):
    # Insert an override
    ctx.conn.execute(
        "INSERT INTO merchant_overrides (id, user_id, merchant_normalized, category_id, created_by, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("o1", "u1", "swiggy", "travel", "user", "2024-01-01T00:00:00Z"),
    )

    rules = [CategorizationRule(match="swiggy", is_regex=False, category_id="food", confidence=0.9)]
    fake_llm = FakeLLMClient([])

    run_categorization_pipeline(ctx, fake_llm, rules, {}, "model-1", "v1")

    # t1 should be categorized as 'travel' because override beats rule
    row = ctx.conn.execute(
        "SELECT category_id, category_source FROM transactions WHERE id = 't1'"
    ).fetchone()
    assert tuple(row) == ("travel", "override")
    assert not fake_llm.prompts


def test_pipeline_rule_beats_llm(ctx):
    rules = [CategorizationRule(match="swiggy", is_regex=False, category_id="food", confidence=0.9)]
    fake_llm = FakeLLMClient([])

    run_categorization_pipeline(ctx, fake_llm, rules, {}, "model-1", "v1")

    row = ctx.conn.execute(
        "SELECT category_id, category_source FROM transactions WHERE id = 't1'"
    ).fetchone()
    assert tuple(row) == ("food", "rule")
    assert not fake_llm.prompts


def test_pipeline_falls_back_to_llm(ctx):
    rules = []
    fake_llm = FakeLLMClient(
        [
            '{"decisions": [{"merchant_normalized": "swiggy", "category_id": "food", "confidence": 0.86}]}'
        ]
    )

    run_categorization_pipeline(ctx, fake_llm, rules, {}, "model-1", "v1")

    row = ctx.conn.execute(
        "SELECT category_id, category_source FROM transactions WHERE id = 't1'"
    ).fetchone()
    assert tuple(row) == ("food", "llm")
    assert len(fake_llm.prompts) == 1

    # Next time it should hit cache
    ctx.conn.execute(
        "UPDATE transactions SET category_id = NULL, category_source = 'none' WHERE id = 't1'"
    )

    run_categorization_pipeline(ctx, fake_llm, rules, {}, "model-1", "v1")
    row2 = ctx.conn.execute(
        "SELECT category_id, category_source FROM transactions WHERE id = 't1'"
    ).fetchone()
    assert tuple(row2) == ("food", "cache")
    assert len(fake_llm.prompts) == 1  # still 1, no new call
