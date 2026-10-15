"""
Skills library package (PLAN_PHASE3 Section 5.12).
"""

from copilot.skills.manifest import load_all_skills, load_skill_manifest, validate_skill_manifest
from copilot.skills.runner import SkillRunResult, check_preconditions, run_skill
from copilot.skills.tools import register_skill_tools

__all__ = [
    "load_all_skills",
    "load_skill_manifest",
    "validate_skill_manifest",
    "check_preconditions",
    "run_skill",
    "SkillRunResult",
    "register_skill_tools",
]
