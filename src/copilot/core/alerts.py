"""
Core Adaptive Alerts Engine (PLAN_PHASE2 Section 5.7 & Stage 2.5).

Deterministic multi-signal alert scoring, confidence damping, honest uncertainty,
and explainable template generation.
"""

import statistics
from dataclasses import dataclass
from typing import Any

from copilot.config.phase2 import AlertsConfig
from copilot.models.agentic import AlertSeverity


@dataclass(frozen=True)
class AlertSignalBreakdown:
    threshold: float
    forecast: float
    history_deviation: float
    anomaly: float
    goal_impact: float
    confidence_damping: float
    raw_score_bp: int
    score_bp: int
    severity: AlertSeverity | None
    components: dict[str, Any]


def compute_threshold_signal(budget_status: str, spent_paise: int, limit_paise: int) -> float:
    """
    Threshold signal in [0.0, 1.0].
    Exceeded budget = 1.0, warning = 0.5..1.0, normal < 80% = 0.0.
    """
    if limit_paise <= 0:
        return 0.0
    if budget_status == "exceeded" or spent_paise >= limit_paise:
        return 1.0
    if budget_status == "warning" or spent_paise >= int(0.80 * limit_paise):
        ratio = spent_paise / limit_paise
        return min(1.0, max(0.5, 0.5 + 0.5 * ((ratio - 0.8) / 0.2)))
    return 0.0


def compute_forecast_signal(
    limit_paise: int,
    fc_low: int,
    fc_expected: int,
    fc_high: int,
    projected_exceed: bool = False,
) -> float:
    """
    Forecast signal in [0.0, 1.0].
    Reflects whether and how far the forecast range exceeds the budget limit.
    """
    if limit_paise <= 0:
        return 0.0
    if fc_low > limit_paise:
        # Entire forecast range exceeds limit
        return 1.0
    if fc_expected > limit_paise:
        # Expected value exceeds limit
        overflow_ratio = (fc_expected - limit_paise) / max(1, int(0.25 * limit_paise))
        return min(0.95, max(0.70, 0.70 + 0.25 * overflow_ratio))
    if fc_high > limit_paise or projected_exceed:
        # Upper confidence bound breaches limit
        return 0.45
    return 0.0


def compute_history_deviation_signal(
    current_spend_to_date: int, historical_spends_to_date: list[int]
) -> float:
    """
    History deviation signal in [0.0, 1.0].
    Robust z-score of current spend-to-date vs same point in prior months.
    """
    if not historical_spends_to_date:
        return 0.0

    med = statistics.median(historical_spends_to_date)
    devs = [abs(x - med) for x in historical_spends_to_date]
    mad = statistics.median(devs) if devs else 0.0

    if mad > 0:
        z = (current_spend_to_date - med) / (1.4826 * mad)
    else:
        if current_spend_to_date > med:
            z = (current_spend_to_date - med) / max(1.0, float(med) * 0.2)
        else:
            z = 0.0

    if z <= 0.0:
        return 0.0
    # Map z = 3.0+ to 1.0
    return min(1.0, z / 3.0)


def compute_anomaly_signal(anomalies: list[dict[str, Any]]) -> float:
    """
    Anomaly signal in [0.0, 1.0] from open anomalies for this category/merchant.
    """
    if not anomalies:
        return 0.0
    max_sig = 0.0
    for a in anomalies:
        sev = str(a.get("severity", "")).lower()
        if sev == "high":
            max_sig = max(max_sig, 1.0)
        elif sev == "medium":
            max_sig = max(max_sig, 0.6)
        elif sev == "low":
            max_sig = max(max_sig, 0.3)
        else:
            score = a.get("score")
            if score is not None:
                max_sig = max(max_sig, min(1.0, float(score) / 100.0))
    return max_sig


def compute_goal_impact_signal(goals_affected: list[str]) -> float:
    """
    Goal impact signal in [0.0, 1.0].
    High when spend causes an active goal to become at_risk or off_track.
    """
    if not goals_affected:
        return 0.0
    if "off_track" in goals_affected:
        return 1.0
    if "at_risk" in goals_affected:
        return 0.6
    return 0.0


def compute_confidence_damping(history_months: int, txn_count: int) -> float:
    """
    Data confidence damping factor in [0.0, 1.0].
    Low data sufficiency damps the score (never raises it).
    """
    if history_months >= 3 and txn_count >= 5:
        return 1.0
    if history_months >= 2 and txn_count >= 3:
        return 0.85
    if history_months >= 1 or txn_count >= 2:
        return 0.60
    return 0.35


def evaluate_category_alert_signals(
    category_id: str,
    spent_paise: int,
    limit_paise: int,
    budget_status: str,
    fc_low: int,
    fc_expected: int,
    fc_high: int,
    projected_exceed: bool,
    historical_spends_to_date: list[int],
    anomalies: list[dict[str, Any]],
    goals_affected: list[str],
    history_months: int,
    txn_count: int,
    config: AlertsConfig,
    *,
    current_day: int = 15,
    days_in_month: int = 30,
    active_exception: dict[str, Any] | None = None,
    exception_damping_bp: int = 5000,
) -> AlertSignalBreakdown:
    """
    Compute multi-signal score, damping, and severity for a budget/category candidate.
    """
    s_thresh = compute_threshold_signal(budget_status, spent_paise, limit_paise)
    s_fc = compute_forecast_signal(limit_paise, fc_low, fc_expected, fc_high, projected_exceed)
    s_hist = compute_history_deviation_signal(spent_paise, historical_spends_to_date)
    s_anom = compute_anomaly_signal(anomalies)
    s_goal = compute_goal_impact_signal(goals_affected)

    damping = compute_confidence_damping(history_months, txn_count)

    w = config.signal_weights_bp
    raw_score_bp = int(
        w.get("threshold", 2500) * s_thresh
        + w.get("forecast", 2500) * s_fc
        + w.get("history_deviation", 2000) * s_hist
        + w.get("anomaly", 1500) * s_anom
        + w.get("goal_impact", 1500) * s_goal
    )

    base_score_bp = min(10000, max(0, int(raw_score_bp * damping)))

    # Apply exception damping if active contextual exception is present
    # (PLAN_PHASE3 Section 5.8 & 5.9)
    if active_exception:
        damped_factor = max(0.0, min(1.0, (10000 - exception_damping_bp) / 10000.0))
        score_bp = min(10000, max(0, int(base_score_bp * damped_factor)))
    else:
        score_bp = base_score_bp

    # Determine severity
    thresholds = config.tier_thresholds_bp
    severity: AlertSeverity | None = None
    if score_bp >= thresholds.get("critical", 9000):
        severity = "critical"
    elif score_bp >= thresholds.get("warning", 7500):
        severity = "warning"
    elif score_bp >= thresholds.get("notice", 5000):
        severity = "notice"
    elif score_bp >= thresholds.get("info", 2500):
        severity = "info"

    days_left = max(0, days_in_month - current_day)
    usual_paise = (
        int(statistics.median(historical_spends_to_date))
        if historical_spends_to_date
        else spent_paise
    )
    spent_pct = int((spent_paise / max(1, limit_paise)) * 100) if limit_paise > 0 else 0

    exc_reason = active_exception.get("reason", "exception") if active_exception else None
    components = {
        "category_id": category_id,
        "spent_paise": spent_paise,
        "spent_rupees": spent_paise // 100,
        "limit_paise": limit_paise,
        "limit_rupees": limit_paise // 100,
        "spent_pct": spent_pct,
        "current_day": current_day,
        "days_left": days_left,
        "days_in_month": days_in_month,
        "usual_paise": usual_paise,
        "usual_rupees": usual_paise // 100,
        "forecast_expected_paise": fc_expected,
        "forecast_expected_rupees": fc_expected // 100,
        "exceed_rupees": max(0, (fc_expected - limit_paise) // 100) if limit_paise > 0 else 0,
        "signals": {
            "threshold": round(s_thresh, 4),
            "forecast": round(s_fc, 4),
            "history_deviation": round(s_hist, 4),
            "anomaly": round(s_anom, 4),
            "goal_impact": round(s_goal, 4),
        },
        "damping": round(damping, 4),
        "raw_score_bp": raw_score_bp,
        "score_bp": score_bp,
        "history_months": history_months,
        "txn_count": txn_count,
        "damped_by_exception": active_exception is not None,
        "exception_reason": exc_reason,
        "memories": [active_exception] if active_exception else [],
    }

    return AlertSignalBreakdown(
        threshold=s_thresh,
        forecast=s_fc,
        history_deviation=s_hist,
        anomaly=s_anom,
        goal_impact=s_goal,
        confidence_damping=damping,
        raw_score_bp=raw_score_bp,
        score_bp=score_bp,
        severity=severity,
        components=components,
    )


def build_why_text(components: dict[str, Any]) -> str:
    """
    Build explainable alert why_text where EVERY number comes strictly from components.
    """
    cat = str(components.get("category_id", "Budget")).capitalize()
    spent_pct = components.get("spent_pct", 0)
    spent_rupees = components.get("spent_rupees", 0)
    limit_rupees = components.get("limit_rupees", 0)
    days_left = components.get("days_left", 0)
    exceed_rupees = components.get("exceed_rupees", 0)
    current_day = components.get("current_day", 15)
    usual_rupees = components.get("usual_rupees", 0)

    if limit_rupees > 0:
        if exceed_rupees > 0:
            base_text = (
                f"{cat} is {spent_pct}% of budget (₹{spent_rupees} of ₹{limit_rupees}) "
                f"with {days_left} days left; forecast exceeds limit by ₹{exceed_rupees}; "
                f"usual spend by day {current_day} is ₹{usual_rupees}."
            )
        else:
            base_text = (
                f"{cat} is {spent_pct}% of budget (₹{spent_rupees} of ₹{limit_rupees}) "
                f"with {days_left} days left; usual spend by day {current_day} is ₹{usual_rupees}."
            )
    else:
        base_text = (
            f"{cat} spend is ₹{spent_rupees} on day {current_day}; "
            f"usual spend by this day is ₹{usual_rupees}."
        )

    if components.get("damped_by_exception"):
        reason = components.get("exception_reason", "contextual")
        return f"{base_text} Damped by active {reason} exception."
    return base_text
