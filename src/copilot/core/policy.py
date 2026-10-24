"""
Stage 4.9: Offer policy engine (Thompson sampling, Greedy, Random) with logged propensities.
(PLAN_PHASE4 Section 5.9 & Stage 4.9)

Invariants:
1. Arms: challenge families passing the safety filter. Never include essential categories.
2. Thompson sampling: draws theta ~ Beta(alpha, beta) using an injected seeded random.Random.
   Score = int(round(theta * value_weight * 10000)).
3. Propensity logging: estimates selection probability via Monte Carlo re-draws
   (propensity_draws, default 1000).
   Propensities are integers in [1, 10000] basis points, and their sum is <= min(M, K) * 10000.
4. Rest weeks: if the user abandons or rates unhelpful two experiments in a row, policy returns
   zero offers for rest_weeks (default 2).
5. Off-policy reproducibility: same seed -> same offers and propensities.
"""

from __future__ import annotations

import random
import sqlite3
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Literal

from copilot.config.phase4 import OffersConfig, load_offers_config
from copilot.core.learning_loop import get_template_posterior
from copilot.core.timeutil import IST, from_utc_iso
from copilot.db.repo_phase4 import list_experiment_reviews, list_experiments, list_offers

if TYPE_CHECKING:
    from copilot.core.challenges import CandidateOffer


# ---------------------------------------------------------------------------------------------
# 1. Rest Weeks Detector
# ---------------------------------------------------------------------------------------------
def is_user_in_rest_weeks(
    conn: sqlite3.Connection,
    user_id: str,
    as_of: date | None = None,
    config: OffersConfig | None = None,
) -> bool:
    """
    Check if the user is in rest weeks:
    Rule (Section 5.8 & 5.9): If the user abandons or rates as unhelpful two experiments
    in a row, offers pause for `offers.rest_weeks` (default 2 weeks / 14 days).
    """
    cfg = config or load_offers_config()
    today = as_of or datetime.now(tz=IST).date()

    # Get all finished experiments (completed or abandoned)
    exps = list_experiments(conn, user_id)
    finished = [e for e in exps if e.status in ("completed", "abandoned", "reviewed")]
    if len(finished) < 2:
        return False

    # Sort descending by finish time
    def _finish_key(exp) -> str:
        return exp.ended_at or exp.created_at

    finished.sort(key=_finish_key, reverse=True)
    last_two = finished[:2]

    # Evaluate negative outcome for each
    reviews_map = {r.experiment_id: r for r in list_experiment_reviews(conn, user_id)}

    negative_count = 0
    for e in last_two:
        if e.status == "abandoned":
            negative_count += 1
        elif e.id in reviews_map:
            rev = reviews_map[e.id]
            if rev.user_helpful is False:
                negative_count += 1

    if negative_count < 2:
        return False

    # Check if within rest_weeks duration from the latest finish
    latest_finish_str = _finish_key(last_two[0])
    try:
        latest_finish_d = from_utc_iso(latest_finish_str).astimezone(IST).date()
    except Exception:
        latest_finish_d = today

    rest_days = cfg.rest_weeks * 7
    days_since = (today - latest_finish_d).days
    return 0 <= days_since < rest_days


def is_in_dismissal_quiet_period(
    conn: sqlite3.Connection,
    user_id: str,
    as_of: date | None = None,
    config: OffersConfig | None = None,
) -> bool:
    """
    True when recent offers have all been dismissed or ignored, and it is a quiet week.

    PLAN_PHASE4 section 1.3: offers thin out when they keep being dismissed. Count the offers
    in a row, newest first, that were dismissed or expired without being accepted. Once that run
    reaches `dismissed_in_a_row`, the `quiet_weeks` after the latest offered week show nothing;
    the week after that, offers may return. An accepted offer ends the run.
    """
    cfg = config or load_offers_config()
    today = as_of or datetime.now(tz=IST).date()
    decided = [o for o in list_offers(conn, user_id) if o.status != "shown"]
    decided.sort(key=lambda o: (o.week_start, o.created_at), reverse=True)
    run = 0
    for offer in decided:
        if offer.status == "accepted":
            break
        run += 1
    if run < cfg.dismissed_in_a_row:
        return False
    latest_week = date.fromisoformat(decided[0].week_start)
    quiet_from = latest_week + timedelta(days=7)
    quiet_until = latest_week + timedelta(days=7 * (1 + cfg.quiet_weeks))
    return quiet_from <= today < quiet_until


# ---------------------------------------------------------------------------------------------
# 2. Value Weighting
# ---------------------------------------------------------------------------------------------
def compute_value_weight(cand: CandidateOffer) -> float:
    """
    Compute normalised value weight for candidate challenge:
    Combines expected absolute financial effect and goal relevance.
    """
    # 1.0 base + goal relevance share (0.0 to 1.0) + expected effect normalized (up to ~₹2,000)
    goal_boost = cand.goal_relevance_bp / 10000.0
    effect_boost = (
        min(1.0, cand.expected_effect_paise / 200000.0) if cand.expected_effect_paise > 0 else 0.0
    )
    return 1.0 + goal_boost + effect_boost


# ---------------------------------------------------------------------------------------------
# 3. Policy Selection Engines
# ---------------------------------------------------------------------------------------------
def select_offers_thompson(
    conn: sqlite3.Connection,
    user_id: str,
    candidates: list[CandidateOffer],
    max_offers: int = 3,
    seed: int | None = None,
    config: OffersConfig | None = None,
) -> tuple[list[CandidateOffer], list[int]]:
    """
    Thompson Sampling policy:
    1. For each candidate arm, draw theta ~ Beta(alpha, beta) using seeded RNG.
    2. Score = int(round(theta * value_weight * 10000)).
    3. Pick top max_offers.
    4. Monte Carlo propensity estimation: re-draw `propensity_draws` times
       to log exact selection probabilities.
    """
    cfg = config or load_offers_config()
    if not candidates:
        return [], []

    rng = random.Random(seed)
    arm_posteriors: list[tuple[float, float, float]] = []
    for cand in candidates:
        alpha_m, beta_m, _ = get_template_posterior(conn, user_id, cand.template_code, cfg)
        a = max(0.1, alpha_m / 1000.0)
        b = max(0.1, beta_m / 1000.0)
        w = compute_value_weight(cand)
        arm_posteriors.append((a, b, w))

    # 1. Primary Draw
    scores: list[tuple[int, int]] = []
    for idx, (a, b, w) in enumerate(arm_posteriors):
        theta = rng.betavariate(a, b)
        score_bp = int(round(theta * w * 10000))
        scores.append((score_bp, idx))

    scores.sort(key=lambda s: s[0], reverse=True)
    k_slots = min(max_offers, len(candidates))
    selected_indices = [idx for _, idx in scores[:k_slots]]
    selected_candidates = [candidates[idx] for idx in selected_indices]

    # 2. Monte Carlo Propensity Estimation
    mc_draws = cfg.propensity_draws
    mc_rng = random.Random(seed + 1000007 if seed is not None else None)
    selection_counts = [0] * len(candidates)

    for _ in range(mc_draws):
        sim_scores: list[tuple[float, int]] = []
        for idx, (a, b, w) in enumerate(arm_posteriors):
            th = mc_rng.betavariate(a, b)
            sim_scores.append((th * w, idx))
        sim_scores.sort(key=lambda s: s[0], reverse=True)
        for _, idx in sim_scores[:k_slots]:
            selection_counts[idx] += 1

    propensities: list[int] = []
    for idx in selected_indices:
        prob = selection_counts[idx] / float(mc_draws)
        prob_bp = max(1, min(10000, int(round(prob * 10000))))
        propensities.append(prob_bp)

    return selected_candidates, propensities


def select_offers_greedy(
    conn: sqlite3.Connection,
    user_id: str,
    candidates: list[CandidateOffer],
    max_offers: int = 3,
    config: OffersConfig | None = None,
) -> tuple[list[CandidateOffer], list[int]]:
    """
    Greedy (posterior mean) policy:
    Score = posterior_mean * value_weight * 10000.
    Deterministic, zero exploration. Propensity is 10000 bp.
    """
    cfg = config or load_offers_config()
    if not candidates:
        return [], []

    scores: list[tuple[int, int]] = []
    for idx, cand in enumerate(candidates):
        _, _, mean = get_template_posterior(conn, user_id, cand.template_code, cfg)
        w = compute_value_weight(cand)
        score_bp = int(round(mean * w * 10000))
        scores.append((score_bp, idx))

    scores.sort(key=lambda s: s[0], reverse=True)
    k_slots = min(max_offers, len(candidates))
    selected = [candidates[idx] for _, idx in scores[:k_slots]]
    propensities = [10000] * len(selected)
    return selected, propensities


def select_offers_random(
    candidates: list[CandidateOffer],
    max_offers: int = 3,
    seed: int | None = None,
) -> tuple[list[CandidateOffer], list[int]]:
    """
    Uniform random exploration policy for baseline comparison.
    Propensity = min(max_offers, K) / K.
    """
    if not candidates:
        return [], []

    rng = random.Random(seed)
    k_slots = min(max_offers, len(candidates))
    shuffled_indices = list(range(len(candidates)))
    rng.shuffle(shuffled_indices)
    chosen_indices = shuffled_indices[:k_slots]

    prob = k_slots / float(len(candidates))
    prob_bp = max(1, min(10000, int(round(prob * 10000))))

    selected = [candidates[i] for i in chosen_indices]
    propensities = [prob_bp] * len(selected)
    return selected, propensities


# ---------------------------------------------------------------------------------------------
# 4. Master Offer Policy Dispatcher
# ---------------------------------------------------------------------------------------------
def select_challenge_offers(
    conn: sqlite3.Connection,
    user_id: str,
    candidates: list[CandidateOffer],
    policy: Literal["thompson", "greedy", "random"] | None = None,
    max_offers: int | None = None,
    seed: int | None = None,
    config: OffersConfig | None = None,
    as_of: date | None = None,
) -> tuple[list[CandidateOffer], list[int], str | None]:
    """
    Dispatch offer selection to configured policy:
    - Checks rest weeks first (returns [] if active rest week)
    - Runs Thompson, Greedy, or Random selection
    - Returns (selected_candidates, propensities_bp, status_reason)
    """
    cfg = config or load_offers_config()
    pol = policy or cfg.policy
    limit = max_offers if max_offers is not None else cfg.max_per_week

    # 1. Rest weeks check
    if is_user_in_rest_weeks(conn, user_id, as_of=as_of, config=cfg):
        return [], [], "rest_weeks"
    if is_in_dismissal_quiet_period(conn, user_id, as_of=as_of, config=cfg):
        return [], [], "quiet_weeks"

    if not candidates:
        return [], [], "no_candidates"

    # 2. Policy dispatch
    if pol == "thompson":
        selected, props = select_offers_thompson(
            conn, user_id, candidates, max_offers=limit, seed=seed, config=cfg
        )
    elif pol == "greedy":
        selected, props = select_offers_greedy(
            conn, user_id, candidates, max_offers=limit, config=cfg
        )
    elif pol == "random":
        selected, props = select_offers_random(candidates, max_offers=limit, seed=seed)
    else:
        raise ValueError(f"Unknown offer policy: {pol}")

    return selected, props, "selected"
