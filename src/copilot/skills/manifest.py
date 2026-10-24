"""
Skill Manifest loading, schema validation, and catalogue (PLAN_PHASE3 Section 5.12).

Enforces:
- Manifest schema validation (Pydantic model)
- Unknown tool rejection: every step tool must exist in the global registry
- Write tool rejection: skills may NEVER reference write-class tools
- Bad placeholder rejection: every $arg must be declared in inputs
"""

import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from copilot.config.phase2 import load_planner_capabilities
from copilot.core.config import PROJECT_ROOT
from copilot.models.phase3 import SkillManifest
from copilot.planner.capabilities import is_planner_selectable
from copilot.tools.registry import get as get_tool


def _find_placeholders(obj: Any) -> list[str]:
    """Recursively find all $param placeholders in an argument structure."""
    placeholders: list[str] = []
    if isinstance(obj, str):
        if obj.startswith("$"):
            placeholders.append(obj[1:])
        else:
            for match in re.findall(r"\$([a-zA-Z_][a-zA-Z0-9_]*)", obj):
                placeholders.append(match)
    elif isinstance(obj, dict):
        for v in obj.values():
            placeholders.extend(_find_placeholders(v))
    elif isinstance(obj, list):
        for item in obj:
            placeholders.extend(_find_placeholders(item))
    return placeholders


def validate_skill_manifest(manifest: SkillManifest) -> None:
    """
    Validate a SkillManifest against strict safety and registry rules:
    1. Every tool in steps must be registered in the tool registry.
    2. Every tool in steps must be planner-selectable (read or compute; never write).
    3. Every $placeholder used in step args must be declared in inputs.
    """
    declared_inputs = set(manifest.inputs.keys())
    capabilities_cfg = load_planner_capabilities()

    for idx, step in enumerate(manifest.steps):
        if not isinstance(step, dict) or len(step) != 1:
            raise ValueError(f"Skill '{manifest.name}' step {idx} must be a single-key mapping")
        tool_name, step_args = next(iter(step.items()))

        # 1. Existence check
        spec = get_tool(tool_name)
        if spec is None:
            raise ValueError(f"Unknown tool '{tool_name}' in step {idx} of skill '{manifest.name}'")

        # 2. Safety / Write tool check
        # Skills may only reference planner-selectable read/compute tools,
        # or certified agent evaluation tools (evaluate_alerts).
        allowed_skill_extra_tools = {"evaluate_alerts"}
        is_selectable = is_planner_selectable(tool_name, capabilities_cfg)
        if not is_selectable and tool_name not in allowed_skill_extra_tools:
            raise ValueError(
                f"Write tool or non-selectable tool '{tool_name}' in step {idx} "
                f"is forbidden in skill '{manifest.name}'"
            )

        # 3. Placeholder binding check
        placeholders = _find_placeholders(step_args)
        for ph in placeholders:
            if ph not in declared_inputs:
                raise ValueError(
                    f"Bad placeholder '${ph}' in step {idx} of skill '{manifest.name}': "
                    "not declared in inputs"
                )


def load_skill_manifest(path: str | Path) -> SkillManifest:
    """Load, parse, and validate a YAML skill manifest file."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Skill manifest not found: {p}")

    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Skill manifest at {p} must be a YAML mapping")

    try:
        manifest = SkillManifest.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"Invalid skill manifest structure in {p}: {exc}") from exc

    validate_skill_manifest(manifest)
    return manifest


def load_all_skills(skills_dir: str | Path | None = None) -> dict[str, SkillManifest]:
    """Load and validate all skill manifests from the skills directory."""
    dir_path = Path(skills_dir) if skills_dir else (PROJECT_ROOT / "config" / "skills")
    if not dir_path.is_dir():
        return {}

    skills: dict[str, SkillManifest] = {}
    for yaml_file in sorted(dir_path.glob("*.yaml")):
        manifest = load_skill_manifest(yaml_file)
        skills[manifest.name] = manifest
    return skills
