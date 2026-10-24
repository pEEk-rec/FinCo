"""
Off-policy evaluation estimators (IPS, Self-Normalized IPS) for offer simulation.
(PLAN_PHASE4 Section 6 & Stage 4.9)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from eval.sim.simulator import LoggedInteraction


@dataclass
class OffPolicyEstimate:
    """Estimated value and uncertainty bounds for a target policy."""

    estimate: float
    standard_error: float
    error_bound: float  # 1.96 * standard_error (95% CI margin)
    ci_lower: float
    ci_upper: float
    sample_size: int
    effective_sample_size: float

    @property
    def is_valid(self) -> bool:
        return self.sample_size > 0 and not math.isnan(self.estimate)


def compute_importance_weights(
    behavior_propensities: list[float],
    target_propensities: list[float],
    clip_max: float | None = 20.0,
) -> list[float]:
    """
    Compute importance weights w_i = min(p_t / p_b, clip_max).
    Accepts probabilities in either basis points (<= 10000) or floats in [0, 1].
    """
    if len(behavior_propensities) != len(target_propensities):
        raise ValueError("Propensity vectors must have identical length")

    weights: list[float] = []
    for pb, pt in zip(behavior_propensities, target_propensities, strict=False):
        # Convert bp to float if needed
        p_b = pb / 10000.0 if pb > 1.0 else pb
        p_t = pt / 10000.0 if pt > 1.0 else pt

        if p_b <= 0.0:
            w = 0.0
        else:
            w = p_t / p_b

        if clip_max is not None and clip_max > 0.0:
            w = min(w, clip_max)

        weights.append(w)
    return weights


def estimate_ips(
    logged_rewards: list[float],
    behavior_propensities: list[float],
    target_propensities: list[float],
    clip_max: float | None = 20.0,
) -> OffPolicyEstimate:
    """
    Standard Inverse Propensity Scoring (Horvitz-Thompson estimator):
    V_hat = (1 / N) * sum(w_i * Y_i)
    """
    n = len(logged_rewards)
    if n == 0:
        return OffPolicyEstimate(0.0, 0.0, 0.0, 0.0, 0.0, 0, 0.0)

    weights = compute_importance_weights(
        behavior_propensities, target_propensities, clip_max=clip_max
    )
    terms = [w * y for w, y in zip(weights, logged_rewards, strict=False)]
    v_hat = sum(terms) / float(n)

    if n > 1:
        variance = sum((t - v_hat) ** 2 for t in terms) / float(n - 1)
        se = math.sqrt(max(0.0, variance) / float(n))
    else:
        se = 0.0

    sum_w = sum(weights)
    sum_w_sq = sum(w**2 for w in weights)
    ess = (sum_w**2 / sum_w_sq) if sum_w_sq > 0.0 else 0.0

    margin = 1.96 * se
    return OffPolicyEstimate(
        estimate=round(v_hat, 4),
        standard_error=round(se, 4),
        error_bound=round(margin, 4),
        ci_lower=round(v_hat - margin, 4),
        ci_upper=round(v_hat + margin, 4),
        sample_size=n,
        effective_sample_size=round(ess, 2),
    )


def estimate_snips(
    logged_rewards: list[float],
    behavior_propensities: list[float],
    target_propensities: list[float],
    clip_max: float | None = 20.0,
) -> OffPolicyEstimate:
    """
    Self-Normalized Inverse Propensity Scoring (Hajek estimator):
    V_hat = sum(w_i * Y_i) / sum(w_i)
    """
    n = len(logged_rewards)
    if n == 0:
        return OffPolicyEstimate(0.0, 0.0, 0.0, 0.0, 0.0, 0, 0.0)

    weights = compute_importance_weights(
        behavior_propensities, target_propensities, clip_max=clip_max
    )
    sum_w = sum(weights)

    if sum_w <= 0.0:
        return OffPolicyEstimate(0.0, 0.0, 0.0, 0.0, 0.0, n, 0.0)

    weighted_terms = [w * y for w, y in zip(weights, logged_rewards, strict=False)]
    v_hat = sum(weighted_terms) / sum_w

    # Asymptotic variance of ratio estimator: sum(w_i^2 * (y_i - v_hat)^2) / (sum(w_i))^2
    var_numerator = sum(
        (w**2) * ((y - v_hat) ** 2) for w, y in zip(weights, logged_rewards, strict=False)
    )
    variance = var_numerator / (sum_w**2)
    se = math.sqrt(max(0.0, variance))

    sum_w_sq = sum(w**2 for w in weights)
    ess = (sum_w**2 / sum_w_sq) if sum_w_sq > 0.0 else 0.0

    margin = 1.96 * se
    return OffPolicyEstimate(
        estimate=round(v_hat, 4),
        standard_error=round(se, 4),
        error_bound=round(margin, 4),
        ci_lower=round(v_hat - margin, 4),
        ci_upper=round(v_hat + margin, 4),
        sample_size=n,
        effective_sample_size=round(ess, 2),
    )


def evaluate_arm_off_policy(
    history: list[LoggedInteraction],
    target_template: str,
    target_probability: float = 1.0,
) -> tuple[OffPolicyEstimate, OffPolicyEstimate]:
    """
    Evaluate the expected reward of a target challenge arm using logged interaction history.
    Returns (IPS, SNIPS) estimates.
    """
    rewards: list[float] = []
    behavior_props: list[float] = []
    target_props: list[float] = []

    for item in history:
        rewards.append(item.reward)
        behavior_props.append(item.propensity_bp / 10000.0)
        if item.template_code == target_template:
            target_props.append(target_probability)
        else:
            target_props.append(0.0)

    ips = estimate_ips(rewards, behavior_props, target_props)
    snips = estimate_snips(rewards, behavior_props, target_props)
    return ips, snips
