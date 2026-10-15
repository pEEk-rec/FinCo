"""
Tests for Stage 4.0: Configuration validation and boundary tests (PLAN_PHASE4 Stage 4.0, Section 1.3).
"""

import pytest
from pydantic import ValidationError

from copilot.config.phase4 import (
    BaselineConfig,
    ChallengeTemplate,
    DifficultyConfig,
    ExperimentCheckinsConfig,
    ExperimentLimitsConfig,
    ExperimentReviewConfig,
    ExperimentsConfig,
    RewardsConfig,
    load_badges_config,
    load_baseline_config,
    load_challenge_templates,
    load_experiments_config,
    load_integrity_config,
    load_offers_config,
    load_pace_config,
    load_phase4_safety_config,
    load_rewards_config,
    load_streaks_config,
)


def test_load_all_real_phase4_configs():
    """All Phase 4 YAML configurations load without errors."""
    exp = load_experiments_config()
    assert exp.default_duration_days == 14
    assert exp.limits.max_active == 2

    base = load_baseline_config()
    assert base.default_k == 6
    assert base.min_windows == 3

    tmpls = load_challenge_templates()
    assert len(tmpls) >= 8
    assert "weekday_home_cooking" in tmpls
    assert "delivery_cap" in tmpls

    offers = load_offers_config()
    assert offers.ttl_days == 7
    assert offers.policy == "thompson"

    rewards = load_rewards_config()
    assert rewards.xp.daily_cap == 100
    assert "checkin_answered" in rewards.rules

    badges = load_badges_config()
    assert "first_experiment_reviewed" in badges.badges

    streaks = load_streaks_config()
    assert streaks.grace_days_per_7_days == 1

    pace = load_pace_config()
    assert pace.tolerance_bp == 1000

    integrity = load_integrity_config()
    assert integrity.share_of_margin_bp == 5000

    safety = load_phase4_safety_config()
    assert "last chance" in safety.pressure_phrases
    assert "rent" in safety.essential_categories


def test_experiments_duration_boundaries():
    """Durations 7 and 56 are accepted; 6 and 57 are rejected."""
    base_kwargs = {
        "duration_days_min": 7,
        "duration_days_max": 56,
        "default_duration_days": 14,
        "default_start_weekday": 0,
        "limits": ExperimentLimitsConfig(max_active=2, max_per_category=1),
        "checkins": ExperimentCheckinsConfig(every_days=7),
        "review": ExperimentReviewConfig(delay_days=2),
        "difficulties": {"easy": DifficultyConfig(reduction_share_bp=1000)},
        "min_target_share_bp": 5000,
        "target_round_paise": 5000,
    }

    # 7 is accepted
    cfg7 = ExperimentsConfig(**{**base_kwargs, "duration_days_min": 7})
    assert cfg7.duration_days_min == 7

    # 56 is accepted
    cfg56 = ExperimentsConfig(**{**base_kwargs, "duration_days_max": 56})
    assert cfg56.duration_days_max == 56

    # 6 is rejected
    with pytest.raises(ValidationError):
        ExperimentsConfig(**{**base_kwargs, "duration_days_min": 6})

    # 57 is rejected
    with pytest.raises(ValidationError):
        ExperimentsConfig(**{**base_kwargs, "duration_days_max": 57})

    # min > max is rejected
    with pytest.raises(ValidationError):
        ExperimentsConfig(**{**base_kwargs, "duration_days_min": 28, "duration_days_max": 14})


def test_baseline_k_and_min_windows_boundaries():
    """Baseline default_k must be >= min_windows; min_windows >= 3."""
    base_kwargs = {
        "default_k": 6,
        "min_windows": 3,
        "max_lookback_weeks": 26,
        "max_missing_days": 0,
        "min_effect_share_bp": 1000,
        "min_effect_paise": 20000,
    }

    cfg = BaselineConfig(**base_kwargs)
    assert cfg.default_k == 6

    # min_windows < 3 rejected
    with pytest.raises(ValidationError):
        BaselineConfig(**{**base_kwargs, "min_windows": 2})

    # min_windows > default_k rejected
    with pytest.raises(ValidationError):
        BaselineConfig(**{**base_kwargs, "default_k": 3, "min_windows": 4})


def test_challenge_template_validation():
    """Challenge template rejects invalid durations and difficulties."""
    valid_data = {
        "code": "test_challenge",
        "family": "test_fam",
        "metric": "category_spend",
        "eligible_categories": ["dining_out"],
        "allowed_durations": [7, 14],
        "allowed_difficulties": ["easy", "medium"],
        "trigger_class": "test_trig",
        "weekdays_only": False,
        "title": "Test Challenge",
        "rationale_template": "Test rationale",
        "safety_tags": ["non_essential_only"],
    }
    tmpl = ChallengeTemplate(**valid_data)
    assert tmpl.code == "test_challenge"

    # Duration < 7 rejected
    with pytest.raises(ValidationError):
        ChallengeTemplate(**{**valid_data, "allowed_durations": [5, 14]})

    # Duration > 56 rejected
    with pytest.raises(ValidationError):
        ChallengeTemplate(**{**valid_data, "allowed_durations": [14, 60]})

    # Invalid difficulty rejected
    with pytest.raises(ValidationError):
        ChallengeTemplate(**{**valid_data, "allowed_difficulties": ["extreme"]})


def test_rewards_rule_rejects_forbidden_metrics_and_categories():
    """Rewards config validator fails if any rule references forbidden categories or metrics."""
    rewards = load_rewards_config()
    raw = rewards.model_dump()

    # Inject forbidden metric rule
    raw["rules"]["reduce_rent_xp"] = {
        "points": 50,
        "max_daily_share": 50,
        "description": "Rewards for cutting rent",
    }
    with pytest.raises(ValidationError, match="contains forbidden term"):
        RewardsConfig.model_validate(raw)

    # Inject forbidden commitment skip encouragement
    raw["rules"].pop("reduce_rent_xp")
    raw["rules"]["commitment_hack"] = {
        "points": 50,
        "max_daily_share": 50,
        "description": "Earn points when you skip emi payment",
    }
    with pytest.raises(ValidationError, match="encourages skipping"):
        RewardsConfig.model_validate(raw)
