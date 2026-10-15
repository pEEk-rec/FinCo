"""
Defects found while building Stage 4.12, each pinned by a test that fails without the fix.

1. Essential categories were matched by id only, so this product's `housing` (Rent) and `bills`
   (Utilities), and any category the user creates, could be targeted for reduction.
2. Challenge templates named categories (`dining_out`) the product does not have, so the
   fallback path produced no offers for a real user.
3. The "weekend heavy" memory trigger and the "budget exceeded in 2 of 3 months" trigger queried
   tables and columns that do not exist, inside `except OperationalError: pass`, so they never fired.
4. Declared exceptions are recorded per month by the memory observers, but pauses, baselines and
   streak freezes only understood explicit day ranges.
"""

import json
from datetime import datetime

import pytest

from copilot.core.adaptive import detect_exception_overlap
from copilot.core.baseline import calculate_baseline, generate_candidate_windows
from copilot.core.category_resolution import resolve_categories, resolve_merchants
from copilot.core.challenges import (
    LLMChallengeSpec,
    evaluate_triggers,
    generate_challenge_offers,
    validate_llm_spec,
)
from copilot.core.essentials import essential_category_ids, is_essential
from copilot.core.exception_windows import active_exceptions, exception_range
from copilot.core.experiments import design_experiment, start_experiment
from copilot.core.self_competition import get_streak_freeze_dates
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_account, insert_budget, insert_category, insert_user
from copilot.models.domain import Account, Budget, Category, User

T0 = "2026-01-01T00:00:00Z"
CLOCK = datetime.fromisoformat("2026-09-01T00:00:00+05:30")
USER = "user_alice"

# The categories this product actually ships (ids differ from their display names).
PRODUCT_CATEGORIES = [
    ("food", "Dining"),
    ("groceries", "Groceries"),
    ("housing", "Rent"),
    ("bills", "Utilities"),
    ("travel", "Travel"),
    ("shopping", "Shopping"),
    ("entertainment", "Entertainment"),
    ("subscriptions", "Subscriptions"),
    ("education", "Education"),
    ("flat_rent", "Flat rent"),
    ("coffee_runs", "Coffee runs"),
]


@pytest.fixture
def conn():
    c = get_connection(":memory:", check_same_thread=False)
    init_db(c)
    insert_user(c, User(id=USER, created_at=T0))
    insert_account(
        c, Account(id="acc_main", user_id=USER, name="Main", opening_balance_paise=0, created_at=T0)
    )
    for cid, name in PRODUCT_CATEGORIES:
        insert_category(c, Category(id=cid, user_id=USER, name=name, created_at=T0))
    return c


def _txn(conn, tx_id, when, paise, cat="food", merchant="Merchant"):
    conn.execute(
        "INSERT INTO transactions (id, user_id, account_id, occurred_at, amount_paise, direction,"
        " merchant_raw, merchant_normalized, description, category_id, category_source, created_at)"
        " VALUES (?, ?, 'acc_main', ?, ?, 'debit', ?, ?, 'd', ?, 'rule', ?)",
        (tx_id, USER, when, paise, merchant, merchant.lower(), cat, when),
    )


def _baseline_history(conn, cat="food", paise=300000, duration=14, merchant="Merchant"):
    for i, (start, _end) in enumerate(generate_candidate_windows("2026-09-01", duration, k=6), 1):
        _txn(conn, f"h_{cat}_{i}", f"{start}T10:00:00Z", paise, cat, merchant)


# ------------------------------------------------------------------ 1. essentials


@pytest.mark.parametrize(
    "cid, name, essential",
    [
        ("housing", "Rent", True),
        ("bills", "Utilities", True),
        ("travel", "Travel", True),
        ("groceries", "Groceries", True),
        ("education", "Education", True),
        ("flat_rent", "Flat rent", True),
        ("home_emi", "Home EMI", True),
        ("fees", "Bank fees and charges", True),
        ("food", "Dining", False),
        ("shopping", "Shopping", False),
        ("entertainment", "Entertainment", False),
        ("subscriptions", "Subscriptions", False),
        ("coffee_runs", "Coffee runs", False),  # "coffee" must not read as "fee"
        ("emirates", "Emirates trip", False),  # "emi" must match a whole word only
    ],
)
def test_essential_classification_uses_ids_names_and_whole_words(cid, name, essential):
    assert is_essential(cid, name) is essential


def test_every_essential_product_category_is_found_for_the_user(conn):
    ids = essential_category_ids(conn, USER)
    assert {"housing", "bills", "groceries", "travel", "education", "flat_rent"} <= ids
    assert not ids & {"food", "shopping", "entertainment", "subscriptions", "coffee_runs"}


@pytest.mark.parametrize("cat", ["housing", "bills", "flat_rent", "travel"])
def test_design_refuses_essential_targets_whatever_the_id(conn, cat):
    with pytest.raises(ValueError, match="essential category"):
        design_experiment(
            conn, USER, params={"metric_code": "category_spend", "categories": [cat]}, clock=CLOCK
        )


def test_a_no_spend_challenge_on_an_essential_category_is_refused_too(conn):
    """Zero-spend days on groceries would push the user to skip food as much as a cap would."""
    with pytest.raises(ValueError, match="essential category"):
        design_experiment(
            conn,
            USER,
            params={"metric_code": "no_spend_days", "categories": ["groceries"]},
            clock=CLOCK,
        )


def test_llm_specs_naming_the_products_essential_ids_are_rejected(conn):
    essential = essential_category_ids(conn, USER)
    user_cats = {cid for cid, _ in PRODUCT_CATEGORIES}
    for cat in ("housing", "bills", "flat_rent"):
        spec = LLMChallengeSpec(
            metric_code="category_spend",
            categories=[cat],
            duration_days=14,
            difficulty="medium",
            title="t",
            rationale="r",
        )
        ok, why = validate_llm_spec(spec, user_cats, essential)
        assert not ok and "essential" in why


# ------------------------------------------------------------------ 2. template resolution


def test_template_hints_resolve_to_the_users_own_categories(conn):
    assert resolve_categories(conn, USER, ["dining_out", "food_delivery"]) == ["food"]
    assert resolve_categories(conn, USER, ["shopping"]) == ["shopping"]
    assert resolve_categories(conn, USER, ["entertainment"]) == ["entertainment"]


def test_resolution_never_returns_an_essential_category(conn):
    # "food" is a synonym of the dining hints; a category called "Food and groceries" is essential
    insert_category(
        conn,
        Category(id="food_and_groceries", user_id=USER, name="Food and groceries", created_at=T0),
    )
    assert "food_and_groceries" not in resolve_categories(conn, USER, ["dining_out"])


def test_merchant_group_comes_from_the_users_own_merchants(conn):
    _txn(conn, "m1", "2026-08-20T10:00:00Z", 40000, "food", "SWIGGY ORDER")
    _txn(conn, "m2", "2026-08-21T10:00:00Z", 30000, "food", "Local Dhaba")
    assert resolve_merchants(conn, USER, "food_delivery") == ["swiggy"]
    assert resolve_merchants(conn, USER, None) == []


def test_template_fallback_produces_offers_for_a_real_product_user(conn):
    """With product categories (food/Dining) and no model, offers still exist and use `food`."""
    _baseline_history(conn, "food", 300000, duration=7)
    offers = generate_challenge_offers(
        conn, USER, week_start="2026-09-01", llm_client=None, clock=CLOCK
    )
    assert offers, "no offers: the templates did not resolve to the user's categories"
    for offer in offers:
        assert set(offer.params_json.get("categories", [])) <= {
            "food",
            "shopping",
            "entertainment",
            "subscriptions",
        }
        assert not set(offer.params_json.get("categories", [])) & essential_category_ids(conn, USER)


# ------------------------------------------------------------------ 3. triggers


def test_weekend_heavy_memory_pattern_fires_the_trigger(conn):
    assert "weekend_heavy" not in evaluate_triggers(conn, USER, clock=CLOCK)
    conn.execute(
        "INSERT INTO memory_items (id, user_id, kind, subject_key, statement_json, source, status,"
        " prior_bp, user_confirmed, created_at) VALUES ('m1', ?, 'recurring_pattern',"
        " 'category:food', ?, 'observed', 'active', 3000, 0, ?)",
        (USER, json.dumps({"category": "food", "pattern": "weekend_heavy", "ratio_bp": 20000}), T0),
    )
    assert "weekend_heavy" in evaluate_triggers(conn, USER, clock=CLOCK)


def _budget(conn, cat, limit):
    insert_budget(
        conn,
        Budget(
            id=f"b_{cat}", user_id=USER, category_id=cat, limit_paise=limit, warn_threshold_pct=80
        ),
    )


def test_budget_exceeded_in_two_of_three_months_fires_but_one_does_not(conn):
    _budget(conn, "food", 100000)
    _txn(conn, "j", "2026-08-10T10:00:00Z", 150000)  # August over
    assert "budget_exceeded" not in evaluate_triggers(conn, USER, clock=CLOCK)  # one month only
    _txn(conn, "k", "2026-07-10T10:00:00Z", 150000)  # July over as well
    assert "budget_exceeded_2_of_3" in evaluate_triggers(conn, USER, clock=CLOCK)


def test_an_essential_budget_does_not_trigger_a_reduction_challenge(conn):
    _budget(conn, "housing", 100000)
    _txn(conn, "r1", "2026-08-02T10:00:00Z", 150000, "housing")
    _txn(conn, "r2", "2026-07-02T10:00:00Z", 150000, "housing")
    assert "budget_exceeded" not in evaluate_triggers(conn, USER, clock=CLOCK)


def test_a_goal_with_no_history_to_judge_by_is_not_called_at_risk(conn):
    from copilot.db.repo import insert_goal
    from copilot.models.agentic import Goal

    insert_goal(
        conn,
        Goal(
            id="g1",
            user_id=USER,
            name="Trip",
            kind="savings",
            target_paise=5000000,
            current_paise=1000000,
            deadline="2026-12-31",
            priority=1,
            created_at=T0,
            updated_at=T0,
        ),
    )
    assert "goal_at_risk" not in evaluate_triggers(conn, USER, clock=CLOCK)


# ------------------------------------------------------------------ 4. exceptions


@pytest.mark.parametrize(
    "meta, expected",
    [
        ({"period": "2026-09"}, ("2026-09-01", "2026-09-30")),
        ({"period": "2026-02"}, ("2026-02-01", "2026-02-28")),
        ({"period": "2026-09-12"}, ("2026-09-12", "2026-09-12")),
        ({"from_date": "2026-09-05", "to_date": "2026-09-08"}, ("2026-09-05", "2026-09-08")),
        ({"from_date": "2026-09-08", "to_date": "2026-09-05"}, None),
        ({"period": "not-a-date"}, None),
        ({}, None),
    ],
)
def test_exception_ranges_cover_months_days_and_explicit_ranges(meta, expected):
    got = exception_range(meta)
    assert (None if got is None else (got[0].isoformat(), got[1].isoformat())) == expected


def _exception(conn, mem_id, meta):
    conn.execute(
        "INSERT INTO memory_items (id, user_id, kind, subject_key, statement_json, source, status,"
        " prior_bp, user_confirmed, created_at) VALUES (?, ?, 'contextual_exception', ?, ?,"
        " 'user_stated', 'active', 6000, 1, ?)",
        (mem_id, USER, mem_id, json.dumps(meta), T0),
    )


def test_a_category_specific_exception_ignores_other_categories(conn):
    _exception(conn, "e1", {"category": "shopping", "period": "2026-09", "reason": "festival"})
    assert active_exceptions(conn, USER, ["food"]) == []
    assert len(active_exceptions(conn, USER, ["shopping"])) == 1
    assert len(active_exceptions(conn, USER, None)) == 1


def test_a_month_level_exception_excludes_baseline_windows(conn):
    _baseline_history(conn, "food", 300000, duration=14)
    base_before, _ = calculate_baseline(
        conn, USER, "category_spend", "2026-09-01", 14, {"categories": ["food"]}
    )
    _exception(conn, "e1", {"category": "food", "period": "2026-07", "reason": "festival"})
    base_after, exclusions = calculate_baseline(
        conn, USER, "category_spend", "2026-09-01", 14, {"categories": ["food"]}
    )
    assert any("contextual_exception_festival" in e["reason"] for e in exclusions)
    assert base_after is None or base_after.k < base_before.k


def test_a_month_level_exception_pauses_an_active_experiment(conn):
    """The observers record `period`; the pause logic used to look only for from/to dates."""
    _baseline_history(conn, "food", 300000, duration=14)
    exp = design_experiment(
        conn,
        USER,
        params={"metric_code": "category_spend", "categories": ["food"], "duration_days": 14},
        clock=CLOCK,
    )
    started = start_experiment(conn, USER, exp.id, clock=CLOCK)
    _exception(conn, "e1", {"category": "food", "period": "2026-09", "reason": "festival"})
    proposals = detect_exception_overlap(conn, USER, started.id, clock=CLOCK)
    kinds = {p.kind: p.status for p in proposals}
    assert kinds.get("pause") == "auto_applied_pause" and "extend" in kinds


def test_a_month_level_exception_freezes_streaks(conn):
    _exception(conn, "e1", {"period": "2026-09", "reason": "trip"})
    frozen = get_streak_freeze_dates(conn, USER)
    assert {d.isoformat() for d in frozen} == {f"2026-09-{day:02d}" for day in range(1, 31)}


# ------------------------------------------------------------------ 5. overlapping experiments


def test_a_window_used_by_another_experiment_on_the_same_metric_is_excluded(conn):
    """`design_experiment` stores `metric_code`; the baseline used to look for `metric`."""
    _baseline_history(conn, "food", 300000, duration=14)
    # an earlier experiment occupying the window just before the new one (18 to 31 August)
    august = datetime.fromisoformat("2026-08-18T10:00:00+05:30")
    earlier = design_experiment(
        conn,
        USER,
        params={"metric_code": "category_spend", "categories": ["food"], "duration_days": 14},
        clock=august,
    )
    start_experiment(conn, USER, earlier.id, clock=august)
    base, exclusions = calculate_baseline(
        conn, USER, "category_spend", "2026-09-01", 14, {"categories": ["food"]}
    )
    assert any(e["reason"] == "overlapping_experiment" for e in exclusions)
    assert base is not None and base.k == 5  # one of the six windows is set aside
