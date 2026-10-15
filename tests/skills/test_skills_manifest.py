"""
Tests for Skill Manifest Schema and Safety Validation (Stage 3.10 & Section 5.12).
"""

import pytest

from copilot.models.phase3 import SkillManifest
from copilot.skills.manifest import load_all_skills, validate_skill_manifest
from copilot.workflow.nodes import ensure_tools_registered


@pytest.fixture(autouse=True)
def setup_tools():
    ensure_tools_registered()


def test_load_all_standard_skills():
    """Verify all 5 standard skills load and pass validation."""
    skills = load_all_skills()
    expected = {
        "affordability_check",
        "monthly_close",
        "trip_planning",
        "contribution_review",
        "explain_month_change",
    }
    assert expected.issubset(set(skills.keys()))
    for name, manifest in skills.items():
        assert manifest.name == name
        assert manifest.version >= 1
        assert len(manifest.steps) >= 1
        assert manifest.narration_template


def test_reject_unknown_tool():
    """Manifest specifying an unknown/unregistered tool raises ValueError."""
    manifest = SkillManifest(
        name="invalid_tool_skill",
        version=1,
        description="Skill with unknown tool",
        inputs={},
        preconditions=[],
        steps=[{"non_existent_tool_xyz": {}}],
        outputs=[],
        narration_template="tpl_v1",
        eval_cases="tests/skills/",
    )
    with pytest.raises(ValueError, match="Unknown tool 'non_existent_tool_xyz'"):
        validate_skill_manifest(manifest)


def test_reject_write_tool():
    """Manifest referencing a write-class tool (e.g. create_goal) raises ValueError."""
    manifest = SkillManifest(
        name="adversarial_write_skill",
        version=1,
        description="Skill trying to execute write tool",
        inputs={},
        preconditions=[],
        steps=[{"create_goal": {"name": "Test", "target_paise": 100000}}],
        outputs=[],
        narration_template="tpl_v1",
        eval_cases="tests/skills/",
    )
    with pytest.raises(ValueError, match="Write tool or non-selectable tool 'create_goal'"):
        validate_skill_manifest(manifest)


def test_reject_user_allocate_write_tool():
    """Manifest referencing allocate_to_bucket raises ValueError."""
    manifest = SkillManifest(
        name="adversarial_allocate_skill",
        version=1,
        description="Skill trying to allocate funds directly",
        inputs={},
        preconditions=[],
        steps=[{"allocate_to_bucket": {"bucket_id": "b1", "amount_paise": 100000}}],
        outputs=[],
        narration_template="tpl_v1",
        eval_cases="tests/skills/",
    )
    with pytest.raises(ValueError, match="Write tool or non-selectable tool 'allocate_to_bucket'"):
        validate_skill_manifest(manifest)


def test_reject_bad_argument_placeholder():
    """Step argument referencing undeclared $placeholder raises ValueError."""
    manifest = SkillManifest(
        name="bad_placeholder_skill",
        version=1,
        description="Skill referencing undeclared placeholder",
        inputs={"amount_paise": "required"},
        preconditions=[],
        steps=[
            {
                "run_whatif": {
                    "amount_paise": "$amount_paise",
                    "category_id": "$undeclared_category_id",
                }
            }
        ],
        outputs=[],
        narration_template="tpl_v1",
        eval_cases="tests/skills/",
    )
    with pytest.raises(ValueError, match="Bad placeholder '\\$undeclared_category_id'"):
        validate_skill_manifest(manifest)
