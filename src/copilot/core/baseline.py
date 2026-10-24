"""
Baseline, Outcome, Rank-P, Pace, and Integrity Engine (PLAN_PHASE4 Section 5.2).
Pure deterministic engine with integer paise, integer basis points, and no causal claims.
"""

import json
import sqlite3
from datetime import date, timedelta
from typing import Any, Literal

from copilot.core.exception_windows import active_exceptions
from copilot.core.metrics import METRIC_DIRECTIONS, _date_to_utc_bounds, calculate_metric
from copilot.core.timeutil import IST, from_utc_iso
from copilot.models.phase4 import Baseline, IntegrityNote

OutcomeType = Literal[
    "beyond_usual_range", "within_usual_range", "above_usual_range", "no_baseline"
]
PaceType = Literal["ahead", "on_pace", "behind", "insufficient"]


# ---------------------------------------------------------------------------------------------
# 1. Candidate Windows Generator
# ---------------------------------------------------------------------------------------------
def generate_candidate_windows(
    start_date: str,
    duration_days: int,
    k: int = 6,
    max_lookback_weeks: int = 26,
) -> list[tuple[str, str]]:
    """
    Generate candidate baseline windows of length `duration_days` aligned to the same weekday,
    ending before `start_date`, going back at most `max_lookback_weeks`.
    Oldest to newest.
    """
    s_date = date.fromisoformat(start_date)
    max_lookback_days = max_lookback_weeks * 7
    windows: list[tuple[str, str]] = []

    # Window 1 ends on s_date - 1 day, starts on s_date - duration_days
    # Window 2 ends on previous window start - 1 day, etc.
    cur_end = s_date - timedelta(days=1)
    earliest_allowed = s_date - timedelta(days=max_lookback_days)

    while len(windows) < k:
        cur_start = cur_end - timedelta(days=duration_days - 1)
        if cur_start < earliest_allowed:
            break
        # Both must start on the same weekday as s_date
        assert cur_start.weekday() == s_date.weekday()
        windows.append((cur_start.isoformat(), cur_end.isoformat()))
        cur_end = cur_start - timedelta(days=1)

    # Return most recent windows in chronological order (oldest first)
    return windows[::-1]


# ---------------------------------------------------------------------------------------------
# 2. Baseline Calculation
# ---------------------------------------------------------------------------------------------
def calculate_baseline(
    conn: sqlite3.Connection,
    user_id: str,
    metric_code: str,
    start_date: str,
    duration_days: int,
    params: dict[str, Any] | None = None,
    k: int = 6,
    min_windows: int = 3,
    max_lookback_weeks: int = 26,
) -> tuple[Baseline | None, list[dict[str, Any]]]:
    """
    Calculate baseline median, low, high from K comparable historical windows.
    Excludes windows overlapping contextual exceptions or other experiments on the same metric.
    Returns (Baseline, exclusions). If valid windows < min_windows, Baseline is None.
    """
    candidate_windows = generate_candidate_windows(
        start_date=start_date,
        duration_days=duration_days,
        k=k,
        max_lookback_weeks=max_lookback_weeks,
    )
    exclusions: list[dict[str, Any]] = []
    valid_windows: list[tuple[str, str]] = []

    # Declared exceptions that apply to this metric's categories, as day ranges
    categories = (params or {}).get("categories", [])
    exception_windows = active_exceptions(conn, user_id, categories)

    # Fetch existing active/completed experiments for same metric
    exp_query = """
        SELECT window_start, window_end, metric_def_json FROM experiments
        WHERE user_id = ? AND status IN ('active', 'completed', 'reviewed')
    """
    exp_rows = conn.execute(exp_query, (user_id,)).fetchall()

    # Check earliest account creation
    acc_row = conn.execute(
        "SELECT MIN(created_at) FROM accounts WHERE user_id = ?", (user_id,)
    ).fetchone()
    earliest_account_date: date | None = None
    if acc_row and acc_row[0]:
        earliest_account_date = from_utc_iso(acc_row[0]).astimezone(IST).date()

    # The first payment on record: earlier windows have no data, which is not the same as no spend
    first_row = conn.execute(
        "SELECT MIN(occurred_at) FROM transactions WHERE user_id = ?", (user_id,)
    ).fetchone()
    first_txn_date: date | None = (
        from_utc_iso(first_row[0]).astimezone(IST).date() if first_row and first_row[0] else None
    )

    for w_start_str, w_end_str in candidate_windows:
        w_start = date.fromisoformat(w_start_str)

        # 0. A window the user's data does not reach back to cannot say what was usual
        if first_txn_date is None or w_start < first_txn_date:
            exclusions.append(
                {
                    "window": f"{w_start_str}..{w_end_str}",
                    "reason": "before_first_transaction",
                }
            )
            continue

        # 1. Check account existence
        if earliest_account_date and w_start < earliest_account_date:
            exclusions.append(
                {
                    "window": f"{w_start_str}..{w_end_str}",
                    "reason": "account_not_yet_created",
                }
            )
            continue

        # 2. Check overlap with contextual exceptions
        overlap_exception = False
        w_end = date.fromisoformat(w_end_str)
        for _mem_id, ex_from, ex_to, ex_reason in exception_windows:
            if ex_from <= w_end and ex_to >= w_start:  # the ranges share at least one day
                overlap_exception = True
                exclusions.append(
                    {
                        "window": f"{w_start_str}..{w_end_str}",
                        "reason": f"contextual_exception_{ex_reason}",
                    }
                )
                break

        if overlap_exception:
            continue

        # 3. Check overlap with existing experiments on same metric
        overlap_exp = False
        for er in exp_rows:
            try:
                m_def = json.loads(er["metric_def_json"])
                if (m_def.get("metric_code") or m_def.get("metric")) == metric_code:
                    e_s = er["window_start"]
                    e_e = er["window_end"]
                    if not (w_end_str < e_s or w_start_str > e_e):
                        overlap_exp = True
                        exclusions.append(
                            {
                                "window": f"{w_start_str}..{w_end_str}",
                                "reason": "overlapping_experiment",
                            }
                        )
                        break
            except Exception:
                pass

        if overlap_exp:
            continue

        valid_windows.append((w_start_str, w_end_str))

    if len(valid_windows) < min_windows:
        return None, exclusions

    # Compute metric values for each valid window
    window_values: list[int] = []
    for w_start_str, w_end_str in valid_windows:
        val = calculate_metric(
            conn=conn,
            user_id=user_id,
            metric_code=metric_code,
            start_date=w_start_str,
            end_date=w_end_str,
            params=params,
        )
        window_values.append(val)

    sorted_vals = sorted(window_values)
    n = len(sorted_vals)
    # Lower middle rule for even count: sorted_vals[(n // 2) - 1]
    if n % 2 == 1:
        median_val = sorted_vals[n // 2]
    else:
        median_val = sorted_vals[(n // 2) - 1]

    low_val = sorted_vals[0]
    high_val = sorted_vals[-1]

    baseline = Baseline(
        k=len(window_values),
        window_values=window_values,
        median=median_val,
        low=low_val,
        high=high_val,
        excluded_windows=exclusions,
    )
    return baseline, exclusions


# ---------------------------------------------------------------------------------------------
# 3. Outcome & Rank-P Evaluation
# ---------------------------------------------------------------------------------------------
def evaluate_outcome(
    observed_value: int,
    baseline: Baseline | None,
    target_value: int,
    metric_code: str,
    min_effect_share_bp: int = 1000,
    min_effect_paise: int = 20000,
) -> tuple[OutcomeType, int, int, bool]:
    """
    Deterministic outcome and exact rank-p evaluation (PLAN_PHASE4 Section 5.2).
    Returns: (outcome, rank_p_bp, effect_value, target_met)
    """
    direction = METRIC_DIRECTIONS.get(metric_code, "lower")

    if baseline is None or baseline.k < 3:
        target_met = (
            observed_value <= target_value
            if direction == "lower"
            else observed_value >= target_value
        )
        effect = (
            target_value - observed_value if direction == "lower" else observed_value - target_value
        )
        # 10000 = no evidence of a difference; the column allows 1 to 10000
        return "no_baseline", 10000, effect, target_met

    k = baseline.k
    median = baseline.median
    low = baseline.low
    high = baseline.high
    vals = baseline.window_values

    if direction == "lower":
        target_met = observed_value <= target_value
        effect_value = median - observed_value

        # rank_p = (1 + count(b <= v)) / (k + 1) in basis points
        count_le = sum(1 for b in vals if b <= observed_value)
        rank_p_bp = ((1 + count_le) * 10000) // (k + 1)

        # Minimum effect threshold
        min_effect = max((min_effect_share_bp * median) // 10000, min_effect_paise)

        if observed_value < low and (median - observed_value) >= min_effect:
            outcome = "beyond_usual_range"
        elif observed_value > high:
            outcome = "above_usual_range"
        else:
            outcome = "within_usual_range"

    else:  # higher-is-better
        target_met = observed_value >= target_value
        effect_value = observed_value - median

        # rank_p = (1 + count(b >= v)) / (k + 1) in basis points
        count_ge = sum(1 for b in vals if b >= observed_value)
        rank_p_bp = ((1 + count_ge) * 10000) // (k + 1)

        min_effect = max((min_effect_share_bp * median) // 10000, min_effect_paise)

        if observed_value > high and (observed_value - median) >= min_effect:
            outcome = "beyond_usual_range"
        elif observed_value < low:
            outcome = "above_usual_range"
        else:
            outcome = "within_usual_range"

    return outcome, rank_p_bp, effect_value, target_met


# ---------------------------------------------------------------------------------------------
# 4. Pace Engine
# ---------------------------------------------------------------------------------------------
def calculate_pace(
    observed_value: int,
    target_value: int,
    start_date: str,
    end_date: str,
    as_of_date: str,
    metric_code: str,
    tolerance_bp: int = 1000,
) -> PaceType:
    """
    Calculate mid-experiment pace (PLAN_PHASE4 Section 5.2).
    expected = (target * elapsed_days) // total_days (integer arithmetic, round half up).
    """
    s_d = date.fromisoformat(start_date)
    e_d = date.fromisoformat(end_date)
    cur_d = date.fromisoformat(as_of_date)

    total_days = (e_d - s_d).days + 1
    elapsed_days = (cur_d - s_d).days + 1

    if elapsed_days <= 0:
        return "insufficient"
    elapsed_days = min(elapsed_days, total_days)

    direction = METRIC_DIRECTIONS.get(metric_code, "lower")

    # Linear expected progress: round half up integer arithmetic
    expected_value = (target_value * elapsed_days + (total_days // 2)) // total_days
    tolerance_delta = (expected_value * tolerance_bp) // 10000

    if direction == "lower":
        if observed_value < expected_value - tolerance_delta:
            return "ahead"
        if observed_value > expected_value + tolerance_delta:
            return "behind"
        return "on_pace"
    else:
        if observed_value > expected_value + tolerance_delta:
            return "ahead"
        if observed_value < expected_value - tolerance_delta:
            return "behind"
        return "on_pace"


# ---------------------------------------------------------------------------------------------
# 5. Integrity Notes Engine
# ---------------------------------------------------------------------------------------------
def calculate_integrity_notes(
    conn: sqlite3.Connection,
    user_id: str,
    start_date: str,
    end_date: str,
    target_value: int,
    observed_value: int,
    categories: list[str],
    metric_code: str,
    share_of_margin_bp: int = 5000,
) -> IntegrityNote:
    """
    Verify integrity of self-competition outcomes (PLAN_PHASE4 Section 5.2):
    Flags recategorisations out of target categories, late transactions, and exceptions.
    Requires user confirmation before target_met XP is awarded if recategorized amount
    is >= 50% of the winning margin.
    """
    start_utc, end_utc = _date_to_utc_bounds(start_date, end_date)
    cat_set = set(categories)

    # 1. Recategorisations out of category during the window
    # Audit events of type 'category_override_created' or 'transaction_categorised'
    recat_query = """
        SELECT metadata_json FROM audit_events
        WHERE user_id = ? AND event_type IN ('category_override_created', 'transaction_categorised')
          AND occurred_at >= ? AND occurred_at <= ?
    """
    rows = conn.execute(recat_query, (user_id, start_utc, end_utc)).fetchall()
    recat_count = 0
    recat_amount = 0

    for r in rows:
        try:
            meta = json.loads(r["metadata_json"] or "{}")
            prev_cat = meta.get("previous_category_id") or meta.get("old_category_id")
            new_cat = meta.get("category_id") or meta.get("new_category_id")
            amt = abs(int(meta.get("amount_paise", 0)))
            if prev_cat in cat_set and new_cat not in cat_set:
                recat_count += 1
                recat_amount += amt
        except Exception:
            pass

    # 1b. The product's own recategorisations: what `recategorize_transaction` actually records
    # (event type `transaction_recategorized`, category in before/after, amount on the
    # transaction). Only changes to payments dated inside the window count, and one that was
    # undone does not. There is no upper time bound: a correction made after the window ends but
    # before the review would otherwise be a way to improve the result unnoticed.
    real_rows = conn.execute(
        """
        SELECT e.before_json, e.after_json, t.amount_paise
        FROM audit_events e
        JOIN transactions t ON t.id = e.entity_id AND t.user_id = e.user_id
        WHERE e.user_id = ? AND e.event_type = 'transaction_recategorized'
          AND e.entity_type = 'transaction' AND e.occurred_at >= ?
          AND t.occurred_at >= ? AND t.occurred_at < ?
          AND NOT EXISTS (
              SELECT 1 FROM audit_events u
              WHERE u.user_id = e.user_id AND u.event_type = 'undo'
                AND json_extract(u.metadata_json, '$.undone_event_id') = e.id
          )
        """,
        (user_id, start_utc, start_utc, end_utc),
    ).fetchall()
    for r in real_rows:
        try:
            before_cat = json.loads(r["before_json"] or "{}").get("category_id")
            after_cat = json.loads(r["after_json"] or "{}").get("category_id")
        except (ValueError, AttributeError):
            continue
        if before_cat in cat_set and after_cat not in cat_set:
            recat_count += 1
            recat_amount += abs(int(r["amount_paise"]))

    # 2. Late transactions (occurred inside window but created after window end)
    late_query = """
        SELECT COUNT(*), COALESCE(SUM(amount_paise), 0)
        FROM transactions
        WHERE user_id = ? AND occurred_at >= ? AND occurred_at < ? AND created_at > ?
    """
    late_row = conn.execute(late_query, (user_id, start_utc, end_utc, end_utc)).fetchone()
    late_count = late_row[0] if late_row else 0
    late_amount = late_row[1] if late_row else 0

    # 3. Exceptions declared inside window
    ex_query = """
        SELECT COUNT(*) FROM memory_items
        WHERE user_id = ? AND kind = 'contextual_exception' AND created_at >= ? AND created_at <= ?
    """
    ex_row = conn.execute(ex_query, (user_id, start_utc, end_utc)).fetchone()
    ex_count = ex_row[0] if ex_row else 0

    # Confirmation required check
    direction = METRIC_DIRECTIONS.get(metric_code, "lower")
    confirmation_required = False
    if direction == "lower" and observed_value <= target_value:
        winning_margin = target_value - observed_value
        if winning_margin > 0:
            threshold = (winning_margin * share_of_margin_bp) // 10000
            if recat_amount >= threshold and recat_amount > 0:
                confirmation_required = True

    return IntegrityNote(
        recategorized_count=recat_count,
        recategorized_amount_paise=recat_amount,
        late_txns_count=late_count,
        late_txns_amount_paise=late_amount,
        exceptions_count=ex_count,
        confirmation_required=confirmation_required,
    )
