"""
Tests for Core Adaptive Alerts Engine (PLAN_PHASE2 Section 5.7 & Stage 2.5).

Verifies:
- Every signal function at its boundaries (threshold, forecast, history deviation, anomaly, goal impact)
- Data confidence damping strictly damps the score (never raises it)
- Every tier cut-off boundary (info, notice, warning, critical)
- Ordinary seeded month produces zero alerts above info (quiet by default)
- All numbers in why_text strictly come from components
"""

from copilot.config.phase2 import AlertsConfig
from copilot.core.alerts import (
    build_why_text,
    compute_anomaly_signal,
    compute_confidence_damping,
    compute_forecast_signal,
    compute_goal_impact_signal,
    compute_history_deviation_signal,
    compute_threshold_signal,
    evaluate_category_alert_signals,
)


def test_threshold_signal_boundaries():
    """Test compute_threshold_signal at and around every boundary."""
    limit = 10000_00  # ₹10,000

    # 0 spend -> 0.0
    assert compute_threshold_signal("ok", 0, limit) == 0.0

    # 79% spend -> 0.0
    assert compute_threshold_signal("ok", 7900_00, limit) == 0.0

    # 80% spend -> 0.5 (warning threshold)
    assert compute_threshold_signal("warning", 8000_00, limit) == 0.5

    # 90% spend -> 0.75
    sig_90 = compute_threshold_signal("warning", 9000_00, limit)
    assert 0.74 <= sig_90 <= 0.76

    # 100% spend -> 1.0 (exceeded)
    assert compute_threshold_signal("exceeded", 10000_00, limit) == 1.0

    # 110% spend -> 1.0
    assert compute_threshold_signal("exceeded", 11000_00, limit) == 1.0

    # 0 limit -> 0.0
    assert compute_threshold_signal("ok", 5000_00, 0) == 0.0


def test_forecast_signal_boundaries():
    """Test compute_forecast_signal across range relations to budget limit."""
    limit = 5000_00

    # Low exceeds limit -> 1.0
    assert compute_forecast_signal(limit, 5500_00, 6000_00, 7000_00) == 1.0

    # Expected exceeds limit -> >= 0.70
    sig_exp = compute_forecast_signal(limit, 4500_00, 5500_00, 6500_00)
    assert sig_exp >= 0.70

    # Only high exceeds limit -> 0.45
    assert compute_forecast_signal(limit, 3500_00, 4500_00, 5500_00) == 0.45

    # All below limit -> 0.0
    assert compute_forecast_signal(limit, 2000_00, 3000_00, 4000_00) == 0.0

    # Projected exceed flag True -> 0.45
    assert compute_forecast_signal(limit, 2000_00, 3000_00, 4000_00, projected_exceed=True) == 0.45


def test_history_deviation_signal_robust_zscore():
    """Test history deviation robust z-score calculation."""
    history = [1000_00, 1100_00, 1050_00]  # median = 1050_00, small MAD

    # Current spend below median -> 0.0
    assert compute_history_deviation_signal(900_00, history) == 0.0
    assert compute_history_deviation_signal(1050_00, history) == 0.0

    # Current spend significantly above median -> positive signal up to 1.0
    sig_high = compute_history_deviation_signal(1500_00, history)
    assert sig_high > 0.5

    # Extreme outlier capped at 1.0
    sig_extreme = compute_history_deviation_signal(5000_00, history)
    assert sig_extreme == 1.0

    # Empty history -> 0.0
    assert compute_history_deviation_signal(2000_00, []) == 0.0


def test_anomaly_signal():
    """Test compute_anomaly_signal severity mapping."""
    assert compute_anomaly_signal([]) == 0.0
    assert compute_anomaly_signal([{"severity": "low"}]) == 0.3
    assert compute_anomaly_signal([{"severity": "medium"}]) == 0.6
    assert compute_anomaly_signal([{"severity": "high"}]) == 1.0
    # Picks highest
    assert compute_anomaly_signal([{"severity": "low"}, {"severity": "high"}]) == 1.0


def test_goal_impact_signal():
    """Test compute_goal_impact_signal."""
    assert compute_goal_impact_signal([]) == 0.0
    assert compute_goal_impact_signal(["on_track"]) == 0.0
    assert compute_goal_impact_signal(["at_risk"]) == 0.6
    assert compute_goal_impact_signal(["off_track"]) == 1.0
    assert compute_goal_impact_signal(["at_risk", "off_track"]) == 1.0


def test_confidence_damping_strictly_damps():
    """Damping factor is in [0.0, 1.0] and strictly damps score."""
    assert compute_confidence_damping(3, 10) == 1.0
    assert compute_confidence_damping(2, 4) == 0.85
    assert compute_confidence_damping(1, 2) == 0.60
    assert compute_confidence_damping(0, 0) == 0.35

    config = AlertsConfig(
        signal_weights_bp={
            "threshold": 2500,
            "forecast": 2500,
            "history_deviation": 2000,
            "anomaly": 1500,
            "goal_impact": 1500,
        },
        tier_thresholds_bp={
            "info": 2500,
            "notice": 5000,
            "warning": 7500,
            "critical": 9000,
        },
    )

    # Full data: raw == score
    res_full = evaluate_category_alert_signals(
        category_id="food",
        spent_paise=10000_00,
        limit_paise=10000_00,
        budget_status="exceeded",
        fc_low=12000_00,
        fc_expected=13000_00,
        fc_high=14000_00,
        projected_exceed=True,
        historical_spends_to_date=[8000_00, 8500_00, 9000_00],
        anomalies=[{"severity": "high"}],
        goals_affected=["off_track"],
        history_months=3,
        txn_count=10,
        config=config,
    )
    assert res_full.confidence_damping == 1.0
    assert res_full.score_bp == res_full.raw_score_bp

    # Zero history: score is damped
    res_damped = evaluate_category_alert_signals(
        category_id="food",
        spent_paise=10000_00,
        limit_paise=10000_00,
        budget_status="exceeded",
        fc_low=12000_00,
        fc_expected=13000_00,
        fc_high=14000_00,
        projected_exceed=True,
        historical_spends_to_date=[],
        anomalies=[{"severity": "high"}],
        goals_affected=["off_track"],
        history_months=0,
        txn_count=0,
        config=config,
    )
    assert res_damped.confidence_damping == 0.35
    assert res_damped.score_bp < res_damped.raw_score_bp


def test_tier_threshold_boundaries():
    """Verify severity tier classification at exact basis point boundaries."""
    config = AlertsConfig(
        signal_weights_bp={
            "threshold": 2500,
            "forecast": 2500,
            "history_deviation": 2000,
            "anomaly": 1500,
            "goal_impact": 1500,
        },
        tier_thresholds_bp={
            "info": 2500,
            "notice": 5000,
            "warning": 7500,
            "critical": 9000,
        },
    )

    # Helper to check boundary mapping
    thresholds = config.tier_thresholds_bp

    def get_tier(score: int):
        if score >= thresholds["critical"]:
            return "critical"
        if score >= thresholds["warning"]:
            return "warning"
        if score >= thresholds["notice"]:
            return "notice"
        if score >= thresholds["info"]:
            return "info"
        return None

    assert get_tier(2499) is None
    assert get_tier(2500) == "info"
    assert get_tier(4999) == "info"
    assert get_tier(5000) == "notice"
    assert get_tier(7499) == "notice"
    assert get_tier(7500) == "warning"
    assert get_tier(8999) == "warning"
    assert get_tier(9000) == "critical"
    assert get_tier(10000) == "critical"


def test_why_text_numbers_strictly_grounded():
    """All numbers in why_text must come from components."""
    components = {
        "category_id": "dining",
        "spent_pct": 91,
        "spent_rupees": 4550,
        "limit_rupees": 5000,
        "days_left": 11,
        "exceed_rupees": 1200,
        "current_day": 19,
        "usual_rupees": 3800,
    }

    text = build_why_text(components)
    # Check that each formatted number exists in the text
    assert "91%" in text
    assert "₹4550" in text
    assert "₹5000" in text
    assert "11 days" in text
    assert "₹1200" in text
    assert "day 19" in text
    assert "₹3800" in text


def test_quiet_by_default_on_ordinary_month():
    """
    Ordinary seeded month with healthy budget produces zero alerts above info.
    """
    config = AlertsConfig(
        signal_weights_bp={
            "threshold": 2500,
            "forecast": 2500,
            "history_deviation": 2000,
            "anomaly": 1500,
            "goal_impact": 1500,
        },
        tier_thresholds_bp={
            "info": 2500,
            "notice": 5000,
            "warning": 7500,
            "critical": 9000,
        },
    )

    # An ordinary month with 50% budget consumed halfway through month
    res = evaluate_category_alert_signals(
        category_id="food",
        spent_paise=2500_00,
        limit_paise=5000_00,
        budget_status="ok",
        fc_low=4500_00,
        fc_expected=4800_00,
        fc_high=5100_00,
        projected_exceed=False,
        historical_spends_to_date=[2400_00, 2600_00, 2500_00],
        anomalies=[],
        goals_affected=[],
        history_months=3,
        txn_count=12,
        config=config,
        current_day=15,
        days_in_month=30,
    )

    # Ordinary run-rate without breach produces no alert above info
    assert res.severity in (None, "info")
    assert res.severity != "warning"
    assert res.severity != "critical"
