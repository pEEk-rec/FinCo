"""
Challenge templates, personalisation, trigger evaluation, and goal decomposition engine.
(PLAN_PHASE4 Section 5.4 & Stage 4.4)

Rules:
1. Integer paise for money throughout; integer basis points for rates.
2. Non-essential categories only: essential categories are strictly forbidden
   from reduction targets.
3. LLM-composed challenges are validated; numbers inside LLM specs are ignored and replaced
   by computed deterministic targets.
4. Templates act as fallback and seed pool.
5. Selection uses a greedy policy until Stage 4.9. Offers created are drafts only (status="shown").
6. Goal decomposition suggests candidate experiments covering the monthly gap without ever
   promising completion or reaching the goal.
"""

import hashlib
import sqlite3
import uuid
from datetime import date, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from copilot.audit.events import record_event
from copilot.config.phase4 import (
    ChallengeTemplate,
    load_challenge_templates,
    load_experiments_config,
    load_offers_config,
    load_phase4_safety_config,
)
from copilot.core.advice import format_inr
from copilot.core.baseline import calculate_baseline
from copilot.core.calendar import build_calendar, load_calendar_config
from copilot.core.category_resolution import resolve_categories, resolve_merchants
from copilot.core.essentials import essential_category_ids, is_essential
from copilot.core.goals import goal_progress, required_monthly_paise
from copilot.core.labels import format_metric, metric_label
from copilot.core.metrics import METRIC_CATALOGUE, calculate_tagging_completeness
from copilot.core.policy import (  # noqa: E402
    is_in_dismissal_quiet_period,
    is_user_in_rest_weeks,
    select_challenge_offers,
)
from copilot.core.timeutil import IST, from_utc_iso, month_bounds, to_utc_iso
from copilot.db.connection import savepoint
from copilot.db.repo import list_categories, list_goals, list_transactions
from copilot.db.repo_phase4 import insert_offer, list_experiments, list_offers
from copilot.llm.client import LLMClient, structured_call
from copilot.models.agentic import Goal
from copilot.models.phase4 import (
    DecomposedExperiment,
    GoalDecomposition,
    Offer,
)


# -------------------------------------------------------------------------------------------------
# 1. Models & LLM Specs
# -------------------------------------------------------------------------------------------------
class LLMChallengeSpec(BaseModel):
    """
    LLM-proposed challenge specification.
    Note: proposed_target is deliberately ignored by the sizing engine to prevent
    hallucinated numbers.
    """

    model_config = ConfigDict(extra="ignore")

    metric_code: str
    categories: list[str] = Field(default_factory=list)
    merchants: list[str] = Field(default_factory=list)
    duration_days: int = 14
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    title: str = "Custom Challenge"
    rationale: str = "Focus on mindful spending."
    proposed_target: int | None = None  # Hallucinated or suggested numbers; ALWAYS IGNORED


class LLMChallengeProposalBatch(BaseModel):
    """Batch of candidate challenge specs proposed by the LLM."""

    model_config = ConfigDict(extra="ignore")

    specs: list[LLMChallengeSpec] = Field(default_factory=list)


class CandidateOffer(BaseModel):
    """Internal candidate representation before offer creation."""

    model_config = ConfigDict(extra="forbid")

    template_code: str
    metric_code: str
    categories: list[str]
    merchants: list[str] = Field(default_factory=list)
    duration_days: int
    difficulty: Literal["easy", "medium", "hard"]
    title: str
    rationale: str
    weekdays_only: bool = False
    target_value: int
    baseline_median: int
    expected_effect_paise: int
    goal_relevance_bp: int = 0
    goal_id: str | None = None
    propensity_bp: int = 5000


def _round_paise(val: int, round_to: int = 5000) -> int:
    """Round paise to nearest boundary (e.g. ₹50 = 5000 paise)."""
    rem = val % round_to
    if rem >= round_to // 2:
        return val + (round_to - rem)
    return val - rem


# -------------------------------------------------------------------------------------------------
# 2. LLM Spec Validation
# -------------------------------------------------------------------------------------------------
def validate_llm_spec(
    spec: LLMChallengeSpec,
    user_categories: set[str],
    essential_categories: set[str],
    allowed_durations: set[int] | None = None,
) -> tuple[bool, str | None]:
    """
    Validate an LLM-proposed challenge spec.
    Rejects unknown metrics, essential category targets, cross-tenant/missing categories,
    and out-of-range durations.
    """
    if spec.metric_code not in METRIC_CATALOGUE:
        return False, f"unknown_metric: {spec.metric_code}"

    # Essential category check
    for cat in spec.categories:
        if cat in essential_categories:
            return False, f"essential_category_targeted: {cat}"

    # Existing category check (must belong to this user's registered categories)
    if spec.categories:
        for cat in spec.categories:
            if cat not in user_categories:
                return False, f"unknown_or_cross_user_category: {cat}"

    # Duration boundary: 7 to 56 days
    if spec.duration_days < 7 or spec.duration_days > 56:
        return False, f"duration_out_of_range: {spec.duration_days}"

    if allowed_durations is not None and spec.duration_days not in allowed_durations:
        return False, f"duration_not_in_allowed_set: {spec.duration_days}"

    if spec.difficulty not in ("easy", "medium", "hard"):
        return False, f"invalid_difficulty: {spec.difficulty}"

    return True, None


# -------------------------------------------------------------------------------------------------
# 3. Deterministic Triggers
# -------------------------------------------------------------------------------------------------
def _budget_exceeded_in_two_of_last_three_months(
    conn: sqlite3.Connection, user_id: str, now_dt: datetime
) -> bool:
    """True when a non-essential budgeted category went over its limit in 2 of the last 3 months."""
    budgets = conn.execute(
        "SELECT b.category_id, b.limit_paise, c.name FROM budgets b "
        "JOIN categories c ON c.user_id = b.user_id AND c.id = b.category_id "
        "WHERE b.user_id = ? AND b.limit_paise > 0",
        (user_id,),
    ).fetchall()
    budgets = [b for b in budgets if not is_essential(b["category_id"], b["name"])]
    if not budgets:
        return False
    ist = now_dt.astimezone(IST)
    year, month = ist.year, ist.month
    over: dict[str, int] = {}
    for _ in range(3):  # the three closed months before the current one
        year, month = (year - 1, 12) if month == 1 else (year, month - 1)
        start, end = month_bounds(year, month)
        for b in budgets:
            spent = conn.execute(
                "SELECT COALESCE(SUM(amount_paise), 0) FROM transactions WHERE user_id = ? "
                "AND category_id = ? AND occurred_at >= ? AND occurred_at < ? "
                "AND excluded_from_spend = 0 AND is_duplicate_of IS NULL",
                (user_id, b["category_id"], start, end),
            ).fetchone()[0]
            if spent > b["limit_paise"]:
                over[b["category_id"]] = over.get(b["category_id"], 0) + 1
    return any(count >= 2 for count in over.values())


def evaluate_triggers(
    conn: sqlite3.Connection,
    user_id: str,
    clock: datetime | None = None,
) -> set[str]:
    """
    Evaluate deterministic trigger conditions from existing user state.
    Returns set of active trigger codes:
    - 'weekend_heavy': heavy weekend discretionary spend or active pattern memory
    - 'budget_exceeded' / 'budget_exceeded_2_of_3': non-essential budget exceeded in 2 of 3 months
    - 'goal_at_risk' / 'goal_off_track': active goal with deficit & pace shortfall
    - 'calendar_shortfall': calendar projection shows shortfall or low balance < buffer
    - 'low_tagging_completeness': tagging completeness in past 30 days < 80% (8000 bp)
    - 'many_open_reviews': transaction review queue has >= 5 items
    - 'bucket_low': discretionary virtual bucket <= 0
    - 'checkin_prompt': check-in compliance habit needed
    """
    now_dt = clock or datetime.now(tz=IST)
    today_str = now_dt.strftime("%Y-%m-%d")
    fired: set[str] = set()

    # 1. Weekend heavy pattern: memory or transaction spend
    # Check memories for active weekend pattern
    # The Phase 3 observers store it as a recurring_pattern memory item.
    pattern = conn.execute(
        "SELECT 1 FROM memory_items WHERE user_id = ? AND kind = 'recurring_pattern' "
        "AND status = 'active' AND statement_json LIKE '%\"weekend_heavy\"%' LIMIT 1",
        (user_id,),
    ).fetchone()
    if pattern:
        fired.add("weekend_heavy")

    # If not fired via memory, check recent transactions (last 60 days)
    if "weekend_heavy" not in fired:
        t_start = (now_dt - timedelta(days=60)).strftime("%Y-%m-%d")
        txs = list_transactions(
            conn, user_id, start=f"{t_start}T00:00:00Z", end=f"{today_str}T23:59:59Z"
        )
        weekend_debits: list[int] = []
        weekday_debits: list[int] = []
        for t in txs:
            if t.direction == "debit" and not t.excluded_from_spend and not t.is_duplicate_of:
                dt = from_utc_iso(t.occurred_at).astimezone(IST)
                # Saturday (5) and Sunday (6)
                if dt.weekday() in (5, 6):
                    weekend_debits.append(t.amount_paise)
                else:
                    weekday_debits.append(t.amount_paise)
        if weekend_debits and weekday_debits:
            avg_wknd = sum(weekend_debits) / len(weekend_debits)
            avg_wkdy = sum(weekday_debits) / len(weekday_debits)
            if avg_wknd >= 1.5 * avg_wkdy and len(weekend_debits) >= 4:
                fired.add("weekend_heavy")

    # 2. Budget exceeded in 2 of last 3 months
    if _budget_exceeded_in_two_of_last_three_months(conn, user_id, now_dt):
        fired.add("budget_exceeded")
        fired.add("budget_exceeded_2_of_3")

    # 3. Goal at risk / off track
    for g in list_goals(conn, user_id, status="active"):
        track = goal_progress(conn, user_id, g, today_str).status
        if track in ("at_risk", "off_track"):
            fired.add("goal_at_risk")
            if track == "off_track":
                fired.add("goal_off_track")
            break

    # 4. Calendar shortfall
    try:
        cal = build_calendar(conn, user_id, today_str, horizon_days=30)
        has_real_shortfall = any(
            (len(r.get("commitments_due", [])) > 0 or r.get("lowest_balance_paise", 0) < 0)
            for r in cal.shortfall_ranges
        )
        if has_real_shortfall:
            fired.add("calendar_shortfall")
    except Exception:
        pass

    # 5. Low tagging completeness (< 8000 bp / 80% in last 30 days)
    t30_start = (now_dt - timedelta(days=30)).strftime("%Y-%m-%d")
    tag_comp = calculate_tagging_completeness(conn, user_id, t30_start, today_str)
    if tag_comp < 8000:
        fired.add("low_tagging_completeness")

    # 6. Many open reviews (>= 5 unreviewed transactions)
    rev_q = "SELECT COUNT(*) as unrev FROM transactions WHERE user_id = ? AND needs_review = 1"
    try:
        r_row = conn.execute(rev_q, (user_id,)).fetchone()
        if r_row and r_row["unrev"] >= 5:
            fired.add("many_open_reviews")
            fired.add("many_review_items")
    except sqlite3.OperationalError:
        pass

    # 7. Discretionary bucket low – uses the real Phase-3 bucket tables
    bucket_q = """
        SELECT COUNT(DISTINCT b.id) as low_count
        FROM buckets b
        LEFT JOIN bucket_allocations ba ON ba.bucket_id = b.id AND ba.user_id = b.user_id
        WHERE b.user_id = ? AND b.status = 'active' AND b.kind = 'spending'
        GROUP BY b.id
        HAVING COALESCE(SUM(
            CASE ba.kind
                WHEN 'allocate'     THEN  ba.amount_paise
                WHEN 'reassign_in'  THEN  ba.amount_paise
                WHEN 'release'      THEN -ba.amount_paise
                WHEN 'reassign_out' THEN -ba.amount_paise
                ELSE 0
            END
        ), 0) <= 0
    """
    try:
        b_rows = conn.execute(bucket_q, (user_id,)).fetchall()
        if b_rows and len(b_rows) > 0:
            fired.add("bucket_low")
    except sqlite3.OperationalError:
        pass

    return fired


# -------------------------------------------------------------------------------------------------
# 4. Candidate Fitting & Sizing
# -------------------------------------------------------------------------------------------------
def fit_candidate_challenge(
    conn: sqlite3.Connection,
    user_id: str,
    template: ChallengeTemplate | None = None,
    spec: LLMChallengeSpec | None = None,
    week_start: str | None = None,
    clock: datetime | None = None,
) -> CandidateOffer | None:
    """
    Fit challenge parameters and compute targets deterministically from historical baseline.
    Any proposed_target in spec is strictly ignored and replaced by baseline calculations.
    """
    if template is None and spec is None:
        raise ValueError("Either template or spec must be provided.")

    now_dt = clock or datetime.now(tz=IST)
    start_date = week_start or now_dt.strftime("%Y-%m-%d")

    metric_code = spec.metric_code if spec else template.metric
    if spec and spec.categories:
        categories = spec.categories
    else:
        # Template categories are hints; use this user's own matching categories
        categories = (
            resolve_categories(conn, user_id, template.eligible_categories) if template else []
        )
    merchants = (
        spec.merchants if spec else resolve_merchants(conn, user_id, template.merchant_group)
    )
    if template and not categories and not merchants and template.eligible_categories:
        return None  # nothing in this user's data matches the template
    duration_days = spec.duration_days if spec else template.allowed_durations[0]
    difficulty = spec.difficulty if spec else "medium"
    title = spec.title if spec else template.title
    rationale = spec.rationale if spec else template.rationale_template
    weekdays_only = template.weekdays_only if template else False
    template_code = template.code if template else f"custom_{metric_code}"

    cfg = load_experiments_config()

    # 1. Baseline calculation
    p_baseline = {
        "categories": categories,
        "merchants": merchants,
        "weekdays_only": weekdays_only,
    }
    base, _exclusions = calculate_baseline(
        conn=conn,
        user_id=user_id,
        metric_code=metric_code,
        start_date=start_date,
        duration_days=duration_days,
        params=p_baseline,
    )

    baseline_median = base.median if base else 0
    expected_effect_paise = 0

    if metric_code in ("category_spend", "merchant_group_spend", "txn_count"):
        if base is None:
            # Sizing from baseline requires at least 3 historical windows
            return None

        share_bp = cfg.difficulties[difficulty].reduction_share_bp
        reduction = (base.median * share_bp) // 10000
        raw_target = base.median - reduction
        target_val = _round_paise(raw_target, cfg.target_round_paise)
        target_floor = (base.median * cfg.min_target_share_bp) // 10000
        target_val = max(target_val, target_floor)
        expected_effect_paise = max(0, base.median - target_val)

    elif metric_code == "no_spend_days":
        # Target: count of days
        base_days = base.median if base else 0
        bump = 2 if difficulty == "hard" else (1 if difficulty == "medium" else 0)
        target_val = min(duration_days, base_days + bump + 1)
        expected_effect_paise = 0

    elif metric_code in ("tagging_completeness", "checkin_rate"):
        # 100% adherence (10000 basis points)
        target_val = 10000
        expected_effect_paise = 0

    elif metric_code == "bucket_adherence_days":
        target_val = duration_days
        expected_effect_paise = 0

    elif metric_code == "goal_allocation":
        # Target: allocation towards a goal
        goals = list_goals(conn, user_id, status="active")
        if goals:
            p_goal = min(goals, key=lambda g: g.priority)
            req_m = required_monthly_paise(p_goal, start_date)
            raw_target = (req_m // 2) if req_m and req_m > 0 else 500000
            target_val = _round_paise(raw_target, cfg.target_round_paise)
            expected_effect_paise = target_val
        else:
            return None  # a goal challenge needs a goal; no amount is invented without one
    else:
        target_val = 1
        expected_effect_paise = 0

    # 2. Goal relevance
    goal_id: str | None = None
    goal_relevance_bp = 0
    goals = list_goals(conn, user_id, status="active")
    if goals:
        p_goal = min(goals, key=lambda g: g.priority)
        goal_id = p_goal.id
        req_m = required_monthly_paise(p_goal, start_date)
        if req_m and req_m > 0 and expected_effect_paise > 0:
            goal_relevance_bp = min(10000, (expected_effect_paise * 10000) // req_m)

    return CandidateOffer(
        template_code=template_code,
        metric_code=metric_code,
        categories=categories,
        merchants=merchants,
        duration_days=duration_days,
        difficulty=difficulty,
        title=title,
        rationale=rationale,
        weekdays_only=weekdays_only,
        target_value=target_val,
        baseline_median=baseline_median,
        expected_effect_paise=expected_effect_paise,
        goal_relevance_bp=goal_relevance_bp,
        goal_id=goal_id,
        propensity_bp=5000,
    )


# -------------------------------------------------------------------------------------------------
# 5. Safety Filter
# -------------------------------------------------------------------------------------------------
def filter_safe_candidates(
    conn: sqlite3.Connection,
    user_id: str,
    candidates: list[CandidateOffer],
    week_start: str | None = None,
    clock: datetime | None = None,
) -> list[CandidateOffer]:
    """
    Filter candidate offers against safety constraints:
    1. Essential categories blocked from reduction metrics.
    2. Category conflicts with currently active experiments dropped.
    3. Cooldown boundary: templates used/shown within cooldown_days dropped.
    4. Calendar liquidity: allocation templates dropped if low balance < min_buffer_paise.
    """
    now_dt = clock or datetime.now(tz=IST)
    today_d = now_dt.date()
    safety_cfg = load_phase4_safety_config()
    offers_cfg = load_offers_config()
    cal_cfg = load_calendar_config()

    essential_cats = set(safety_cfg.essential_categories) | essential_category_ids(conn, user_id)

    # 1. Active experiments for category conflicts
    active_exps = list_experiments(conn, user_id, status="active")
    active_categories: set[str] = set()
    for exp in active_exps:
        cats = exp.metric_def_json.get("categories", [])
        active_categories.update(cats)

    # 2. Recent history for cooldown check
    past_exps = list_experiments(conn, user_id)
    past_offers = list_offers(conn, user_id)

    safe: list[CandidateOffer] = []
    for cand in candidates:
        # Rule 1: essential categories are never a target, whatever the metric
        # ("no-spend days" on groceries would push the user to skip food as much as a cap).
        if any(cat in essential_cats for cat in cand.categories):
            continue

        # Rule 2: Category conflict check
        if any(cat in active_categories for cat in cand.categories):
            continue

        # Rule 3: Cooldown boundary
        in_cooldown = False
        # Check completed/abandoned experiments
        for exp in past_exps:
            if exp.template_code == cand.template_code and exp.status in ("completed", "abandoned"):
                end_str = exp.ended_at or exp.created_at
                end_date = from_utc_iso(end_str).astimezone(IST).date()
                if (today_d - end_date).days < offers_cfg.cooldown_days:
                    in_cooldown = True
                    break

        if in_cooldown:
            continue

        # Check past offers
        for off in past_offers:
            if off.template_code == cand.template_code and off.status in ("accepted", "dismissed"):
                off_date = from_utc_iso(off.created_at).astimezone(IST).date()
                if (today_d - off_date).days < offers_cfg.cooldown_days:
                    in_cooldown = True
                    break

        if in_cooldown:
            continue

        # Rule 4: Calendar liquidity check for allocation templates
        if cand.metric_code == "goal_allocation" or cand.template_code == "goal_boost":
            try:
                cal = build_calendar(conn, user_id, today_d.isoformat(), horizon_days=60)
                min_low = min((d.running_balance_low for d in cal.days), default=0)
                if min_low - cand.target_value < cal_cfg.min_buffer_paise:
                    continue
            except Exception:
                pass

        safe.append(cand)

    return safe


# -------------------------------------------------------------------------------------------------
# 6. Offer Selection & Generation
# -------------------------------------------------------------------------------------------------
def select_offers_greedy(
    candidates: list[CandidateOffer],
    max_offers: int = 3,
) -> list[CandidateOffer]:
    """
    Greedy offer selection: rank candidates by (goal_relevance_bp, expected_effect_paise).
    """
    sorted_cands = sorted(
        candidates,
        key=lambda c: (c.goal_relevance_bp, c.expected_effect_paise),
        reverse=True,
    )
    return sorted_cands[:max_offers]


def _week_seed(user_id: str, week_start: str) -> int:
    """A reproducible seed per user and week: the same week always gives the same offers."""
    digest = hashlib.sha256(f"{user_id}|{week_start}".encode()).hexdigest()
    return int(digest[:8], 16)


def _offers_are_returning(conn: sqlite3.Connection, user_id: str) -> bool:
    """True when offers were last withheld more recently than the last offer was made."""
    withheld = conn.execute(
        "SELECT MAX(occurred_at) FROM audit_events WHERE user_id = ? "
        "AND event_type = 'offers_withheld'",
        (user_id,),
    ).fetchone()[0]
    if not withheld:
        return False
    last_offer = conn.execute(
        "SELECT MAX(created_at) FROM offers WHERE user_id = ?", (user_id,)
    ).fetchone()[0]
    return last_offer is None or withheld > last_offer


def generate_challenge_offers(
    conn: sqlite3.Connection,
    user_id: str,
    week_start: str | None = None,
    llm_client: LLMClient | None = None,
    clock: datetime | None = None,
    run_id: str | None = None,
    actor: str = "agent",
    max_offers: int | None = None,
    seed: int | None = None,
) -> list[Offer]:
    """
    Generate weekly challenge offers for user.

    Primary path: LLM proposes candidate specs, validated and fitted from data.
    Fallback & seed path: configured templates whose triggers fire.
    The offer policy (Thompson sampling by default) then picks the offers with a seeded
    generator and logs each one's selection probability. Created offers have status='shown'
    (drafts only, user opt-in required).

    Idempotent per week: a second call for the same week returns that week's offers instead of
    creating more. During rest weeks or a quiet week nothing is offered, and no model call is
    spent finding out.
    """
    now_dt = clock or datetime.now(tz=IST)
    today_str = week_start or now_dt.strftime("%Y-%m-%d")
    today_d = date.fromisoformat(today_str)

    existing = list_offers(conn, user_id, week_start=today_str)
    if existing:
        return [o for o in existing if o.status in ("shown", "accepted")]

    if not conn.execute(
        "SELECT 1 FROM transactions WHERE user_id = ? LIMIT 1", (user_id,)
    ).fetchone():
        return []  # nothing to base a challenge on yet; no model call, no placeholder offers

    offers_cfg = load_offers_config()
    withheld = (
        "rest_weeks"
        if is_user_in_rest_weeks(conn, user_id, as_of=today_d, config=offers_cfg)
        else "quiet_weeks"
        if is_in_dismissal_quiet_period(conn, user_id, as_of=today_d, config=offers_cfg)
        else None
    )
    if withheld:
        record_event(
            conn=conn,
            user_id=user_id,
            actor=actor,
            event_type="offers_withheld",
            reason=(
                "No offers this week after two challenges that did not work out."
                if withheld == "rest_weeks"
                else "No offers this week because recent ones were passed over."
            ),
            run_id=run_id,
            metadata={"reason": withheld, "week_start": today_str},
            clock=now_dt,
        )
        return []

    safety_cfg = load_phase4_safety_config()
    essential_cats = set(safety_cfg.essential_categories) | essential_category_ids(conn, user_id)

    user_cats = {c.id for c in list_categories(conn, user_id)}
    non_essential_user_cats = user_cats - essential_cats

    candidate_pool: list[CandidateOffer] = []

    # 1. Primary path: LLM proposal
    if llm_client is not None:
        cats_str = ", ".join(sorted(non_essential_user_cats))
        prompt = (
            f"Propose financial challenges for user with categories: [{cats_str}]. "
            f"Allowed metrics: category_spend, merchant_group_spend, txn_count, no_spend_days. "
            f"Durations: 7, 14, 28 days. Difficulties: easy, medium, hard."
        )
        try:
            batch = structured_call(
                client=llm_client,
                prompt=prompt,
                output_model=LLMChallengeProposalBatch,
                purpose="planning",
            )
            for spec in batch.specs:
                ok, err = validate_llm_spec(spec, user_cats, essential_cats)
                if not ok:
                    record_event(
                        conn=conn,
                        user_id=user_id,
                        actor=actor,
                        event_type="challenge_spec_rejected",
                        reason=f"LLM challenge spec rejected: {err}",
                        run_id=run_id,
                        entity_type="challenge_spec",
                        entity_id=spec.metric_code,
                        metadata={"error": err, "spec": spec.model_dump()},
                    )
                    continue

                fitted = fit_candidate_challenge(
                    conn=conn,
                    user_id=user_id,
                    spec=spec,
                    week_start=today_str,
                    clock=clock,
                )
                if fitted is not None:
                    candidate_pool.append(fitted)
        except Exception as exc:
            record_event(
                conn=conn,
                user_id=user_id,
                actor=actor,
                event_type="challenge_generation_fallback",
                reason=f"LLM challenge generation failed: {exc}; using template fallback",
                run_id=run_id,
                metadata={"error": str(exc)},
            )

    # 2. Template fallback and seed pool
    templates = list(load_challenge_templates().values())
    active_triggers = evaluate_triggers(conn, user_id, clock=clock)
    no_matching_triggers = not any(t.trigger_class in active_triggers for t in templates)

    for tmpl in templates:
        # Template eligible if trigger fires or no triggers matched (fallback)
        if tmpl.trigger_class in active_triggers or no_matching_triggers:
            fitted_tmpl = fit_candidate_challenge(
                conn=conn,
                user_id=user_id,
                template=tmpl,
                week_start=today_str,
                clock=clock,
            )
            if fitted_tmpl is not None:
                candidate_pool.append(fitted_tmpl)

    # 3. Safety filtering
    safe_candidates = filter_safe_candidates(
        conn=conn,
        user_id=user_id,
        candidates=candidate_pool,
        week_start=today_str,
        clock=clock,
    )

    # 4. Offer policy: seeded selection, with each offer's selection probability logged
    limit = max_offers if max_offers is not None else offers_cfg.max_per_week
    rng_seed = seed if seed is not None else _week_seed(user_id, today_str)
    selected, propensities, _status = select_challenge_offers(
        conn,
        user_id,
        safe_candidates,
        policy=offers_cfg.policy,
        max_offers=limit,
        seed=rng_seed,
        config=offers_cfg,
        as_of=today_d,
    )
    returning = _offers_are_returning(conn, user_id)

    # 5. Insert offers into database as drafts (status='shown'). Another runner may have made
    # this week's offers in the meantime; the unique index makes that fail here, and the whole
    # block is undone so only one complete set exists.
    created_offers: list[Offer] = []
    try:
        with savepoint(conn):
            created_offers = _insert_offers(
                conn,
                user_id,
                today_str,
                selected,
                propensities,
                offers_cfg,
                rng_seed,
                returning,
                now_dt,
            )
    except sqlite3.IntegrityError:
        return [
            o
            for o in list_offers(conn, user_id, week_start=today_str)
            if o.status in ("shown", "accepted")
        ]
    return created_offers


def _insert_offers(
    conn: sqlite3.Connection,
    user_id: str,
    today_str: str,
    selected: list[CandidateOffer],
    propensities: list[int],
    offers_cfg,
    rng_seed: int,
    returning: bool,
    now_dt: datetime,
) -> list[Offer]:
    """Write the chosen candidates as offers. Raises IntegrityError if the week already has them."""
    created_offers: list[Offer] = []
    for rank, (cand, propensity_bp) in enumerate(zip(selected, propensities, strict=True), 1):
        offer_id = f"off_{uuid.uuid4().hex[:12]}"
        if cand.expected_effect_paise > 0:
            reason_stmt = (
                f"Your usual {metric_label(cand.metric_code)} is "
                f"{format_metric(cand.metric_code, cand.baseline_median)}; "
                f"a {cand.difficulty} target of "
                f"{format_metric(cand.metric_code, cand.target_value)} "
                f"could save {format_inr(cand.expected_effect_paise)}."
            )
        else:
            reason_stmt = cand.rationale

        off = Offer(
            id=offer_id,
            user_id=user_id,
            week_start=today_str,
            template_code=cand.template_code,
            difficulty=cand.difficulty,
            params_json={
                "metric_code": cand.metric_code,
                "categories": cand.categories,
                "merchants": cand.merchants,
                "duration_days": cand.duration_days,
                "target_value": cand.target_value,
                "title": cand.title,
                "goal_id": cand.goal_id,
            },
            rank=rank,
            propensity_bp=propensity_bp,
            policy_version=f"{offers_cfg.policy}_v1",
            rng_seed=rng_seed,
            reason_json={
                "statement": reason_stmt,
                **(
                    {
                        "returning_note": "Offers were paused for a while. This is a fresh "
                        "suggestion, and you can say Not now at any time."
                    }
                    if returning
                    else {}
                ),
                "baseline_median": cand.baseline_median,
                "target_value": cand.target_value,
                "expected_effect_paise": cand.expected_effect_paise,
                "goal_relevance_bp": cand.goal_relevance_bp,
            },
            status="shown",
            created_at=to_utc_iso(now_dt),
            decided_at=None,
        )
        insert_offer(conn, off)
        created_offers.append(off)

    return created_offers


# -------------------------------------------------------------------------------------------------
# 7. Goal Gap Decomposition
# -------------------------------------------------------------------------------------------------
def decompose_goal_gap(
    conn: sqlite3.Connection,
    user_id: str,
    goal_id: str,
    clock: datetime | None = None,
) -> GoalDecomposition:
    """
    Decompose a goal's remaining deficit and monthly gap into up to 3 candidate experiments.
    Never promises completion or reaching the goal; all candidates are strictly opt-in.
    """
    now_dt = clock or datetime.now(tz=IST)
    today_str = now_dt.strftime("%Y-%m-%d")

    # Fetch goal
    goals = list_goals(conn, user_id)
    target_goal: Goal | None = next((g for g in goals if g.id == goal_id), None)
    if target_goal is None:
        raise ValueError(f"Goal not found: {goal_id}")

    req_monthly = required_monthly_paise(target_goal, today_str)
    deficit = max(0, target_goal.target_paise - target_goal.current_paise)

    decomposed_candidates: list[DecomposedExperiment] = []

    if deficit > 0 and req_monthly and req_monthly > 0:
        # Load non-essential candidate templates
        templates = list(load_challenge_templates().values())
        eligible_tmpls = [
            t
            for t in templates
            if t.metric in ("category_spend", "merchant_group_spend")
            and "non_essential_only" in t.safety_tags
        ]

        # Fit up to 3 candidate experiments
        for tmpl in eligible_tmpls[:3]:
            cand = fit_candidate_challenge(
                conn=conn,
                user_id=user_id,
                template=tmpl,
                week_start=today_str,
                clock=clock,
            )
            if cand is not None and cand.expected_effect_paise > 0:
                gap_share = min(100, (cand.expected_effect_paise * 100) // req_monthly)
                # Observational wording without causal promises
                cats_display = ", ".join(cand.categories)
                eff_rs = cand.expected_effect_paise // 100
                statement = (
                    f"A {cand.difficulty} reduction in {cats_display} of "
                    f"₹{eff_rs} over {cand.duration_days} days would cover "
                    f"{gap_share}% of the monthly savings needed for '{target_goal.name}'."
                )
                decomposed_candidates.append(
                    DecomposedExperiment(
                        template_code=cand.template_code,
                        title=cand.title,
                        metric_code=cand.metric_code,
                        categories=cand.categories,
                        duration_days=cand.duration_days,
                        difficulty=cand.difficulty,
                        target_value=cand.target_value,
                        expected_effect_paise=cand.expected_effect_paise,
                        gap_share_pct=gap_share,
                        statement=statement,
                    )
                )

    return GoalDecomposition(
        goal_id=target_goal.id,
        goal_name=target_goal.name,
        target_paise=target_goal.target_paise,
        current_paise=target_goal.current_paise,
        deficit_paise=deficit,
        required_monthly_paise=req_monthly,
        candidate_experiments=decomposed_candidates,
    )
