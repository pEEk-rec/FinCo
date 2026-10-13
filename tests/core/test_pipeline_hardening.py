"""Hardening tests for the categorization pipeline, batch tool and undo."""

from copilot.core.categorisation import CategorizationRule, load_aliases, load_rules
from copilot.core.config import PROJECT_ROOT
from copilot.core.pipeline import run_categorization_pipeline
from copilot.db.repo import get_transaction
from copilot.llm.client import FakeLLMClient
from copilot.tools.categorisation import CategorizeUpdate
from copilot.tools.executor import execute_tool
from tests.tools.test_categorisation_tools import T0, ctx  # noqa: F401


def _insert(ctx, tx_id: str, merchant: str, source: str = "none") -> None:
    ctx.conn.execute(
        "INSERT INTO transactions (id, user_id, account_id, occurred_at, amount_paise, "
        "direction, merchant_raw, description, created_at, category_source) "
        "VALUES (?, 'u1', 'a1', ?, 1000, 'debit', ?, 'd', ?, ?)",
        (tx_id, T0, merchant, T0, source),
    )


def _apply(ctx, **kw):
    return execute_tool(ctx, "categorize_batch", {"updates": [CategorizeUpdate(**kw).model_dump()]})


def test_llm_failure_degrades_to_review_queue(ctx):
    # Exhausted script makes the fake raise; the run must still finish.
    report = run_categorization_pipeline(ctx, FakeLLMClient([]), [], {}, "m", "v1")
    row = get_transaction(ctx.conn, "u1", "t1")
    assert row.category_id is None and row.needs_review is True
    assert report.llm_failures == 1


def test_llm_unknown_category_and_unasked_merchant_are_dropped(ctx):
    reply = (
        '{"decisions": ['
        '{"merchant_normalized": "swiggy", "category_id": "nonexistent", "confidence": 0.9},'
        '{"merchant_normalized": "other", "category_id": "food", "confidence": 0.9}]}'
    )
    run_categorization_pipeline(ctx, FakeLLMClient([reply]), [], {}, "m", "v1")
    row = get_transaction(ctx.conn, "u1", "t1")
    assert row.category_id is None and row.needs_review is True


def test_llm_confidence_is_capped_and_low_goes_to_review(ctx):
    reply = (
        '{"decisions": [{"merchant_normalized": "swiggy", "category_id": "food", '
        '"confidence": 0.99}]}'
    )
    run_categorization_pipeline(ctx, FakeLLMClient([reply]), [], {}, "m", "v1")
    row = get_transaction(ctx.conn, "u1", "t1")
    assert row.category_confidence == 0.85


def test_each_distinct_merchant_is_sent_once(ctx):
    _insert(ctx, "t2", "swiggy")
    _insert(ctx, "t3", "uber")
    llm = FakeLLMClient(
        [
            '{"decisions": [{"merchant_normalized": "swiggy", "category_id": "food", '
            '"confidence": 0.8},{"merchant_normalized": "uber", "category_id": "travel", '
            '"confidence": 0.8}]}'
        ]
    )
    report = run_categorization_pipeline(ctx, llm, [], {}, "m", "v1")
    assert report.llm_calls == 1 and len(llm.prompts) == 1
    assert llm.prompts[0].count("swiggy") == 1


def test_prompt_contains_no_account_numbers_or_upi_ids(ctx):
    _insert(ctx, "t2", "upi ravi@okhdfc 123456789012 cafe")
    llm = FakeLLMClient(['{"decisions": []}'])
    run_categorization_pipeline(ctx, llm, [], {}, "m", "v1")
    assert "@" not in llm.prompts[0] and "123456789012" not in llm.prompts[0]


def test_pipeline_never_overwrites_user_choice(ctx):
    ctx.conn.execute("UPDATE transactions SET category_source='user', category_id='rent'")
    rules = [
        CategorizationRule(match="swiggy", is_regex=False, category_id="food", confidence=0.95)
    ]
    run_categorization_pipeline(ctx, FakeLLMClient([]), rules, {}, "m", "v1")
    assert get_transaction(ctx.conn, "u1", "t1").category_id == "rent"


def test_batch_unknown_category_goes_to_review(ctx):
    out = _apply(ctx, transaction_id="t1", category_id="bogus", confidence=0.99, source="rule")
    assert out.ok and out.data.review_queue_count == 1
    assert get_transaction(ctx.conn, "u1", "t1").category_id is None


def test_undo_is_idempotent_and_does_not_clobber_later_user_change(ctx):
    _insert(ctx, "t2", "uber")
    for tx in ("t1", "t2"):
        assert _apply(ctx, transaction_id=tx, category_id="food", confidence=0.9, source="rule").ok
    # user fixes t2 afterwards
    ctx.conn.execute(
        "UPDATE transactions SET category_source='user', category_id='travel' WHERE id='t2'"
    )
    first = execute_tool(ctx, "undo_categorize_batch", {"target_run_id": ctx.run_id})
    assert first.data.restored_count == 1 and first.data.skipped_count == 1
    assert get_transaction(ctx.conn, "u1", "t2").category_id == "travel"
    second = execute_tool(ctx, "undo_categorize_batch", {"target_run_id": ctx.run_id})
    assert second.data.restored_count == 0


def test_shipped_config_loads():
    rules = load_rules(PROJECT_ROOT / "config" / "categorization_rules.yaml")
    aliases = load_aliases(PROJECT_ROOT / "config" / "merchant_aliases.yaml")
    assert rules and aliases


def test_bad_rule_regex_fails_loudly(tmp_path):
    import pytest

    p = tmp_path / "r.yaml"
    p.write_text("- {match: '([', is_regex: true, category_id: x, confidence: 0.5}\n")
    with pytest.raises(ValueError, match="invalid regex"):
        load_rules(p)
