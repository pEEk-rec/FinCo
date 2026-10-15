"""
Decision-level user simulator for offer policy evaluation.
(PLAN_PHASE4 Section 6 & Stage 4.9)

Runs multi-week simulations of candidate offers, user decisions,
and posterior updates to compute cumulative reward, regret, and off-policy logs.
"""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from copilot.config.phase4 import OffersConfig, load_offers_config
from copilot.core.challenges import CandidateOffer
from copilot.core.learning_loop import update_template_posterior
from copilot.core.policy import select_challenge_offers
from copilot.core.timeutil import IST, to_utc_iso
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_account, insert_category, insert_user
from copilot.db.repo_phase4 import insert_experiment, insert_experiment_review, insert_offer
from copilot.models.domain import Account, Category, User
from copilot.models.phase4 import Experiment, ExperimentReview, Offer
from eval.sim.personas import Persona


@dataclass
class LoggedInteraction:
    week: int
    template_code: str
    propensity_bp: int
    accepted: bool
    completed: bool
    helpful: bool
    reward: float


@dataclass
class SimulationResult:
    policy_name: str
    persona_name: str
    weeks: int
    seed: int
    total_reward: float
    best_fixed_arm: str
    best_fixed_reward: float
    cumulative_regret: float
    offers_shown: int
    offers_accepted: int
    offers_completed: int
    rest_weeks_count: int
    history: list[LoggedInteraction] = field(default_factory=list)


def create_simulated_candidates() -> list[CandidateOffer]:
    """Return standard candidate pool for simulation across challenge templates."""
    templates = [
        ("tpl_dining_weekend", "dining_spend", 45000, 10000, 4000),
        ("tpl_delivery_cap", "delivery_spend", 30000, 8000, 3000),
        ("tpl_no_spend_day", "no_spend_days", 3, 5000, 2000),
        ("tpl_grocery_smart", "grocery_spend", 80000, 12000, 5000),
        ("tpl_commute_transit", "transport_spend", 25000, 6000, 2500),
        ("tpl_subscription_audit", "subscription_spend", 15000, 5000, 3500),
    ]

    candidates: list[CandidateOffer] = []
    for code, metric, target, effect, relevance in templates:
        candidates.append(
            CandidateOffer(
                template_code=code,
                title=code.replace("_", " ").title(),
                metric_code=metric,
                difficulty="medium",
                target_value=target,
                baseline_median=int(target * 1.25) if target > 10 else 4,
                expected_effect_paise=effect,
                goal_relevance_bp=relevance,
                duration_days=14,
                categories=[metric.replace("_spend", "")],
                rationale="Sized based on your historical baseline.",
            )
        )
    return candidates


def run_simulation(
    policy: str,
    persona: Persona,
    weeks: int = 52,
    seed: int = 42,
    max_offers: int = 3,
    config: OffersConfig | None = None,
) -> SimulationResult:
    """
    Run an offline multi-week decision-level simulation for a persona under a policy.
    """
    cfg = config or load_offers_config()
    rng = random.Random(seed)

    # Initialize isolated SQLite database
    conn = get_connection(":memory:")
    init_db(conn)

    user_id = "u_sim"
    t0 = "2026-01-01T00:00:00Z"
    insert_user(conn, User(id=user_id, created_at=t0))
    insert_account(conn, Account(id="acc_sim", user_id=user_id, name="Checking", created_at=t0))
    insert_category(conn, Category(id="dining", user_id=user_id, name="Dining", created_at=t0))

    candidate_pool = create_simulated_candidates()
    history: list[LoggedInteraction] = []

    total_reward = 0.0
    offers_shown = 0
    offers_accepted = 0
    offers_completed = 0
    rest_weeks_count = 0

    base_date = date(2026, 1, 5)  # Monday

    for w in range(1, weeks + 1):
        current_date = base_date + timedelta(days=(w - 1) * 7)
        clock_dt = datetime(
            current_date.year, current_date.month, current_date.day, 10, 0, tzinfo=IST
        )

        selected_offers, propensities, status = select_challenge_offers(
            conn=conn,
            user_id=user_id,
            candidates=candidate_pool,
            policy=policy,  # type: ignore
            max_offers=max_offers,
            seed=seed + (w * 10007),
            config=cfg,
            as_of=current_date,
        )

        if status == "rest_weeks":
            rest_weeks_count += 1
            continue

        for rank, (cand, prop_bp) in enumerate(
            zip(selected_offers, propensities, strict=False), 1
        ):
            offers_shown += 1
            pref = persona.get_preference(cand.template_code, w)

            # 1. Accept Decision
            accepted = rng.random() < pref.p_accept
            # The same offer rows the product writes, so the dismissal rule sees this history
            insert_offer(
                conn,
                Offer(
                    id=f"off_sim_{w}_{rank}",
                    user_id=user_id,
                    week_start=current_date.isoformat(),
                    template_code=cand.template_code,
                    difficulty=cand.difficulty,
                    params_json={"metric_code": cand.metric_code},
                    rank=rank,
                    propensity_bp=prop_bp,
                    policy_version=f"{policy}_sim",
                    rng_seed=seed,
                    reason_json={},
                    status="accepted" if accepted else "dismissed",
                    created_at=to_utc_iso(clock_dt),
                    decided_at=to_utc_iso(clock_dt),
                ),
            )
            if not accepted:
                # Dismissed offer
                update_template_posterior(
                    conn, user_id, cand.template_code, "dismissed_offer", config=cfg, clock=clock_dt
                )
                history.append(
                    LoggedInteraction(
                        week=w,
                        template_code=cand.template_code,
                        propensity_bp=prop_bp,
                        accepted=False,
                        completed=False,
                        helpful=False,
                        reward=0.0,
                    )
                )
                continue

            offers_accepted += 1
            exp_id = f"exp_sim_{w}_{uuid.uuid4().hex[:6]}"

            # 2. Complete Decision
            completed = rng.random() < pref.p_complete
            if not completed:
                # Abandoned
                exp = Experiment(
                    id=exp_id,
                    user_id=user_id,
                    title=cand.title,
                    template_code=cand.template_code,
                    hypothesis_json={
                        "metric": cand.metric_code,
                        "direction": "lower",
                        "target": cand.target_value,
                    },
                    metric_def_json={"metric": cand.metric_code, "categories": cand.categories},
                    params_json={},
                    difficulty=cand.difficulty,
                    window_start=current_date.isoformat(),
                    window_end=(current_date + timedelta(days=cand.duration_days)).isoformat(),
                    baseline_json={"median": 50000, "k": 4},
                    target_value=cand.target_value,
                    status="abandoned",
                    origin="offer",
                    created_at=to_utc_iso(clock_dt),
                    ended_at=to_utc_iso(clock_dt + timedelta(days=5)),
                )
                insert_experiment(conn, exp)
                update_template_posterior(
                    conn, user_id, cand.template_code, "abandoned", config=cfg, clock=clock_dt
                )
                history.append(
                    LoggedInteraction(
                        week=w,
                        template_code=cand.template_code,
                        propensity_bp=prop_bp,
                        accepted=True,
                        completed=False,
                        helpful=False,
                        reward=0.0,
                    )
                )
                continue

            offers_completed += 1

            # 3. Helpful Decision
            helpful = rng.random() < pref.p_helpful
            reward = 1.0 if helpful else 0.0
            total_reward += reward

            end_dt = clock_dt + timedelta(days=cand.duration_days)
            exp = Experiment(
                id=exp_id,
                user_id=user_id,
                title=cand.title,
                template_code=cand.template_code,
                hypothesis_json={
                    "metric": cand.metric_code,
                    "direction": "lower",
                    "target": cand.target_value,
                },
                metric_def_json={"metric": cand.metric_code, "categories": cand.categories},
                params_json={},
                difficulty=cand.difficulty,
                window_start=current_date.isoformat(),
                window_end=(current_date + timedelta(days=cand.duration_days)).isoformat(),
                baseline_json={"median": 50000, "k": 4},
                target_value=cand.target_value,
                status="completed",
                origin="offer",
                created_at=to_utc_iso(clock_dt),
                ended_at=to_utc_iso(end_dt),
            )
            insert_experiment(conn, exp)

            rev_id = f"rev_sim_{w}_{uuid.uuid4().hex[:6]}"
            rev = ExperimentReview(
                id=rev_id,
                user_id=user_id,
                experiment_id=exp_id,
                observed_value=cand.target_value - 2000,
                outcome="beyond_usual_range",
                rank_p_bp=9000,
                effect_value=-cand.expected_effect_paise,
                target_met=True,
                integrity_json={},
                data_quality_json={"coverage": 100},
                user_difficulty=2,
                user_helpful=helpful,
                created_at=to_utc_iso(end_dt),
            )
            insert_experiment_review(conn, rev)

            update_template_posterior(
                conn,
                user_id,
                cand.template_code,
                "completed_review",
                user_helpful=helpful,
                config=cfg,
                clock=end_dt,
            )

            history.append(
                LoggedInteraction(
                    week=w,
                    template_code=cand.template_code,
                    propensity_bp=prop_bp,
                    accepted=True,
                    completed=True,
                    helpful=helpful,
                    reward=reward,
                )
            )

    best_slate, best_fixed_total = persona.best_fixed_slate(weeks, slate_size=max_offers)
    best_arm = best_slate[0] if best_slate else ""
    regret = max(0.0, best_fixed_total - total_reward)

    return SimulationResult(
        policy_name=policy,
        persona_name=persona.name,
        weeks=weeks,
        seed=seed,
        total_reward=total_reward,
        best_fixed_arm=best_arm,
        best_fixed_reward=round(best_fixed_total, 2),
        cumulative_regret=round(regret, 2),
        offers_shown=offers_shown,
        offers_accepted=offers_accepted,
        offers_completed=offers_completed,
        rest_weeks_count=rest_weeks_count,
        history=history,
    )
