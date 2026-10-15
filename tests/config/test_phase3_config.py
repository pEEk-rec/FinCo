"""
Unit tests for Phase 3 configuration loading and Pydantic validation (PLAN_PHASE3 Stage 3.0).
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from copilot.config.phase3 import (
    CalendarConfig,
    LearningConfig,
    MemoryThresholds,
    ReadinessConfig,
    load_buckets_config,
    load_calendar_config,
    load_commitments_config,
    load_context_config,
    load_contributions_config,
    load_decomposition_config,
    load_learning_config,
    load_mcp_config,
    load_memory_config,
    load_ops_config,
    load_phase3_goals_config,
    load_readiness_config,
    load_runtime_config,
    load_skill_manifest,
)

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


def test_all_phase3_configs_load_successfully():
    """Verify that all Phase 3 YAML configs load cleanly with exact types."""
    commitments = load_commitments_config(CONFIG_DIR / "commitments.yaml")
    assert commitments.amount_tolerance_bp == 500
    assert "rent" in commitments.allowed_kinds

    goals = load_phase3_goals_config(CONFIG_DIR / "goals.yaml")
    assert goals.projection_months == 3
    assert goals.default_progress_source == "manual"
    assert "bucket" in goals.allowed_progress_sources

    buckets = load_buckets_config(CONFIG_DIR / "buckets.yaml")
    assert buckets.low_threshold_bp == 2000
    assert buckets.draft_ttl_days == 7

    calendar = load_calendar_config(CONFIG_DIR / "calendar.yaml")
    assert calendar.default_horizon_days == 60
    assert calendar.max_horizon_days == 180
    assert calendar.min_buffer_paise == 100000

    readiness = load_readiness_config(CONFIG_DIR / "readiness.yaml")
    assert readiness.emergency_months_target == 3
    assert readiness.emergency_min_months == 1
    assert "rent" in readiness.essential_categories

    contributions = load_contributions_config(CONFIG_DIR / "contributions.yaml")
    assert contributions.default_horizon_months == 6
    assert contributions.max_tradeoff_alternatives == 3
    assert contributions.waterfall_order[0] == "firm_commitments"

    memory = load_memory_config(CONFIG_DIR / "memory.yaml")
    assert memory.advice_cooldown_days == 30
    assert memory.thresholds_bp.use == 6000
    assert memory.thresholds_bp.stale == 4000
    assert memory.thresholds_bp.retire == 2000
    assert "festival" in memory.allowed_exception_reasons

    decomp = load_decomposition_config(CONFIG_DIR / "decomposition.yaml")
    assert decomp.max_subquestions_per_task == 4
    assert "affordability" in decomp.decomposition_templates

    context = load_context_config(CONFIG_DIR / "context.yaml")
    assert context.token_budgets["intent_extraction"] == 1000
    assert context.top_k_memories == 5

    runtime = load_runtime_config(CONFIG_DIR / "runtime.yaml")
    assert runtime.loop_interval_seconds == 60
    assert "rollover_buckets" in runtime.jobs

    learning = load_learning_config(CONFIG_DIR / "learning.yaml")
    assert learning.prior_alpha == 2
    assert "not_covered" in learning.hard_floor_severities

    ops = load_ops_config(CONFIG_DIR / "ops.yaml")
    assert ops.currency == "USD"
    assert 50 in ops.latency_percentiles

    mcp = load_mcp_config(CONFIG_DIR / "mcp.yaml")
    assert mcp.server_name == "finco-mcp"
    assert "get_calendar" in mcp.exposed_tools


def test_all_skill_manifests_load_successfully():
    """Verify that all required skill manifests in config/skills/ load cleanly."""
    skills_dir = CONFIG_DIR / "skills"
    required_skills = [
        "affordability_check",
        "monthly_close",
        "trip_planning",
        "contribution_review",
        "explain_month_change",
    ]
    for skill_name in required_skills:
        manifest = load_skill_manifest(skills_dir / f"{skill_name}.yaml")
        assert manifest.name == skill_name
        assert manifest.version >= 1
        assert len(manifest.steps) >= 1
        assert len(manifest.outputs) >= 1


def test_calendar_horizon_boundaries():
    """Boundary test: calendar horizon 180 accepted, 181 rejected (PLAN_PHASE3 Stage 3.0)."""
    # 180 is accepted
    valid_cal = CalendarConfig(
        default_horizon_days=60,
        max_horizon_days=180,
        min_buffer_paise=100000,
    )
    assert valid_cal.max_horizon_days == 180

    # 181 is rejected
    with pytest.raises(ValidationError):
        CalendarConfig(
            default_horizon_days=60,
            max_horizon_days=181,
            min_buffer_paise=100000,
        )

    # default_horizon_days > max_horizon_days is rejected
    with pytest.raises(ValidationError):
        CalendarConfig(
            default_horizon_days=90,
            max_horizon_days=60,
            min_buffer_paise=100000,
        )


def test_readiness_emergency_months_boundaries():
    """Boundary test: emergency months target range allowed 1 to 12 (PLAN_PHASE3 1.3)."""
    valid = ReadinessConfig(
        min_history_months=3,
        positive_months_required=2,
        max_cv_bp=5000,
        emergency_months_target=12,
        emergency_min_months=1,
        obligation_window_days=90,
        essential_categories=["rent"],
    )
    assert valid.emergency_months_target == 12

    # 13 is rejected
    with pytest.raises(ValidationError):
        ReadinessConfig(
            min_history_months=3,
            positive_months_required=2,
            max_cv_bp=5000,
            emergency_months_target=13,
            emergency_min_months=1,
            obligation_window_days=90,
            essential_categories=["rent"],
        )

    # 0 is rejected
    with pytest.raises(ValidationError):
        ReadinessConfig(
            min_history_months=3,
            positive_months_required=2,
            max_cv_bp=5000,
            emergency_months_target=0,
            emergency_min_months=1,
            obligation_window_days=90,
            essential_categories=["rent"],
        )

    # min > target is rejected
    with pytest.raises(ValidationError):
        ReadinessConfig(
            min_history_months=3,
            positive_months_required=2,
            max_cv_bp=5000,
            emergency_months_target=3,
            emergency_min_months=4,
            obligation_window_days=90,
            essential_categories=["rent"],
        )


def test_memory_thresholds_ordering():
    """Verify that memory thresholds enforce use > stale >= retire."""
    valid = MemoryThresholds(use=6000, stale=4000, retire=2000)
    assert valid.use == 6000

    # Inverted order is rejected
    with pytest.raises(ValidationError):
        MemoryThresholds(use=4000, stale=6000, retire=2000)

    # retire > stale is rejected
    with pytest.raises(ValidationError):
        MemoryThresholds(use=6000, stale=2000, retire=4000)


def test_learning_config_multiplier_validation():
    """Verify learning config bounds: m_min must be strictly less than m_max."""
    with pytest.raises(ValidationError):
        LearningConfig(
            prior_alpha=2,
            prior_beta=2,
            eta=0.5,
            m_min=1.5,
            m_max=0.5,
            hard_floor_severities=["exceeded"],
        )


def test_config_extra_fields_forbidden():
    """Verify that unexpected configuration keys fail loudly (extra='forbid')."""
    with pytest.raises(ValidationError):
        CalendarConfig(
            default_horizon_days=60,
            max_horizon_days=180,
            min_buffer_paise=100000,
            unexpected_field="forbidden",  # type: ignore[call-arg]
        )
