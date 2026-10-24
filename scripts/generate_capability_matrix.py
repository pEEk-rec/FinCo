"""
Generate docs/capability_matrix.md from config/planner_capabilities.yaml.
PLAN_PHASE2 Section 5.1.
"""

import sys
from pathlib import Path

# Ensure src is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from copilot.config.phase2 import load_planner_capabilities  # noqa: E402


def generate_matrix() -> str:
    yaml_path = PROJECT_ROOT / "config" / "planner_capabilities.yaml"
    cfg = load_planner_capabilities(yaml_path)

    lines = [
        "# Tool Capability & Governance Matrix",
        "",
        "> **DRAFT: awaiting user review**",
        "",
        "This matrix declares the execution class, planner selectability, operational cost,",
        "and governance classification for all tools in the Personal Finance Copilot.",
        "",
        "## 1. Autonomous Analysis Tools (Planner Selectable)",
        "",
        "These tools are strictly deterministic `read` or `compute` operations.",
        "The autonomous planner may select and invoke them without prior human approval.",
        "",
        "| Tool Name | Class | Cost | Description | Relevant Intents |",
        "|---|---|---|---|---|",
    ]

    autonomous = [(name, cap) for name, cap in cfg.tools.items() if cap.planner_selectable]
    for name, cap in sorted(autonomous, key=lambda x: x[0]):
        intents_str = ", ".join(cap.intents) if cap.intents else "all"
        desc = cap.short_description
        lines.append(f"| `{name}` | `{cap.tool_class}` | `{cap.cost}` | {desc} | {intents_str} |")

    lines.extend(
        [
            "",
            "## 2. Protected State Mutation & Governance Tools (Approval Required / User Only)",
            "",
            "These tools write to financial/user state, or require explicit human decisions.",
            "They are **permanently barred** from autonomous selection by the planner.",
            "",
            "| Tool Name | Class | Cost | Description | Reason Barred from Planner |",
            "|---|---|---|---|---|",
        ]
    )

    protected = [(name, cap) for name, cap in cfg.tools.items() if not cap.planner_selectable]
    for name, cap in sorted(protected, key=lambda x: x[0]):
        reason = "State mutation requires user authorization or fixed pipeline node"
        lines.append(
            f"| `{name}` | `{cap.tool_class}` | `{cap.cost}` | {cap.short_description} | {reason} |"
        )

    lines.extend(
        [
            "",
            "## 3. Permanently Prohibited Tool Classes",
            "",
            "The following operations have no tool contracts and are permanently denied by policy:",
            "",
            "- **Money Movement:** Initiating payments, bank transfers, UPI transactions, charges.",
            "- **Trading / Execution:** Executing stock, mutual fund, crypto, or commodity orders.",
            "- **Credential Ingestion:** Requesting or caching OTPs, PINs, passwords, or card numbers.",
            "- **External Mutations:** Modifying third-party bank records or external APIs.",
            "",
            "---",
            "*Generated from `config/planner_capabilities.yaml`.*",
            "",
        ]
    )

    return "\n".join(lines)


def main() -> None:
    content = generate_matrix()
    out_path = PROJECT_ROOT / "docs" / "capability_matrix.md"
    out_path.write_text(content, encoding="utf-8")
    print(f"Generated {out_path} ({len(content)} bytes)")


if __name__ == "__main__":
    main()
