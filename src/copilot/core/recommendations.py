"""
Core Explainable Recommendations Services (PLAN_PHASE2 Section 5.8 & Stage 2.6).

Every recommendation exposes:
- evidence: findings, investigation IDs, simulation IDs
- calculations: structured CalcStep items {label, formula_id, inputs, result}
- assumptions: explicit constraints and projection conditions
- tools_used: tool calls that produced the recommendation
- memories: past user decisions/overrides strictly isolated by user_id
- confidence_label: 'high', 'medium', or 'low'
- simulation_id: mandatory when the recommendation has a financial consequence
- explain rendering: human-readable full explanation
"""

import sqlite3
import uuid
from typing import Any, Literal

from copilot.config.phase2 import load_explanation_templates
from copilot.core.advice import format_inr, validate_advice
from copilot.core.timeutil import now_utc, to_utc_iso
from copilot.models.agentic import CalcStep, Recommendation, RecommendationOrigin
from copilot.models.findings import Finding


def find_relevant_memories(
    conn: sqlite3.Connection,
    user_id: str,
    *,
    category_id: str | None = None,
    origin: str | None = None,
) -> list[dict[str, Any]]:
    """
    Look up past user actions, overrides, and decisions strictly isolated by user_id.
    Never exposes another user's memories.
    """
    memories: list[dict[str, Any]] = []

    # 1. Past decided advice items for this user
    cur = conn.execute(
        """
        SELECT id, text, status, decided_at, created_at, origin
        FROM advice_items
        WHERE user_id = ? AND status IN ('approved', 'rejected')
        ORDER BY created_at DESC LIMIT 5
        """,
        (user_id,),
    )
    for row in cur.fetchall():
        memories.append(
            {
                "kind": "past_advice_decision",
                "id": row[0],
                "summary": f"User {row[2]} advice: {row[1][:60]}...",
                "status": row[2],
                "origin": row[5] if len(row) > 5 else "monthly_review",
                "decided_at": row[3],
                "created_at": row[4],
            }
        )

    # 2. Past decided alerts for this user
    try:
        cur_alerts = conn.execute(
            """
            SELECT id, kind, subject_key, status, decided_at, created_at
            FROM alerts
            WHERE user_id = ? AND status IN ('acknowledged', 'dismissed', 'snoozed')
            ORDER BY created_at DESC LIMIT 5
            """,
            (user_id,),
        )
        for r in cur_alerts.fetchall():
            if category_id is None or r[2] == category_id:
                memories.append(
                    {
                        "kind": "past_alert_decision",
                        "id": r[0],
                        "summary": f"Alert {r[1]} for {r[2]} was {r[3]}",
                        "status": r[3],
                        "decided_at": r[4],
                        "created_at": r[5],
                    }
                )
    except sqlite3.OperationalError:
        pass

    # 3. Active alert preferences for this user
    try:
        cur_prefs = conn.execute(
            """
            SELECT id, category_id, min_severity, muted, max_open_alerts
            FROM alert_preferences
            WHERE user_id = ?
            """,
            (user_id,),
        )
        for p in cur_prefs.fetchall():
            if category_id is None or p[1] == category_id:
                summary = (
                    f"Preference: category={p[1] or 'global'}, min_sev={p[2]}, muted={bool(p[3])}"
                )
                memories.append(
                    {
                        "kind": "alert_preference",
                        "id": p[0],
                        "summary": summary,
                        "muted": bool(p[3]),
                    }
                )
    except sqlite3.OperationalError:
        pass

    return memories


def build_recommendation(
    user_id: str,
    origin: RecommendationOrigin,
    text: str,
    *,
    task_id: str | None = None,
    run_id: str | None = None,
    evidence: list[str] | None = None,
    calculations: list[CalcStep] | None = None,
    assumptions: list[str] | None = None,
    tools_used: list[dict[str, Any]] | None = None,
    memories: list[dict[str, Any]] | None = None,
    confidence_label: Literal["high", "medium", "low"] | None = "medium",
    simulation_id: str | None = None,
    recommendation_kind: str | None = None,
    findings_by_id: dict[str, Finding] | None = None,
    investigations_by_id: dict[str, Any] | None = None,
    simulations_by_id: dict[str, Any] | None = None,
    goals_by_id: dict[str, Any] | None = None,
    clock: Any | None = None,
) -> Recommendation:
    """
    Construct, validate, and return an explainable Recommendation.
    If validation fails, falls back to a deterministic safe template.
    """
    rec_id = str(uuid.uuid4())
    ts = to_utc_iso(now_utc(clock))

    ev_list = evidence or []
    calc_list = calculations or []
    assump_list = list(assumptions or [])
    tools_list = tools_used or []
    mem_list = memories or []

    # Prepare validation draft object
    draft_obj = {
        "text": text,
        "finding_ids": [fid for fid in ev_list if fid in (findings_by_id or {})],
        "evidence": ev_list,
        "calculations": calc_list,
        "simulation_id": simulation_id,
        "kind": recommendation_kind,
    }

    # Validate narration
    verdict = validate_advice(
        draft_obj,
        findings_by_id=findings_by_id or {},
        investigations_by_id=investigations_by_id,
        simulations_by_id=simulations_by_id,
        goals_by_id=goals_by_id,
        calculations=calc_list,
        recommendation_kind=recommendation_kind,
        simulation_id=simulation_id,
    )

    final_text = text
    if not verdict.ok:
        # Fallback to deterministic safe template from explanation_templates.yaml
        cfg = load_explanation_templates()
        fallback_tmpl = cfg.fallback_templates.get("general")
        if recommendation_kind == "investigation_fallback":
            fallback_tmpl = cfg.hedged_sentences.get("inconclusive_investigation") or fallback_tmpl
        elif recommendation_kind in cfg.recommendation_templates:
            fallback_tmpl = cfg.recommendation_templates[recommendation_kind]

        # Grounding placeholders
        first_amount = "₹0"
        for c in calc_list:
            if isinstance(c.result, int):
                first_amount = format_inr(c.result)
                break

        safe_text = fallback_tmpl.format(
            amount_inr=first_amount,
            unexplained_inr=first_amount,
            spent_inr=first_amount,
            limit_inr=first_amount,
            category="general",
            percent="100",
            surplus_inr=first_amount,
            remaining_inr=first_amount,
            target_reduction_inr=first_amount,
            projected_surplus_inr=first_amount,
            goal_name="Goal",
            exceed_inr=first_amount,
        ) if fallback_tmpl else "Analysis completed. Review spending to maintain cashflow buffer."

        final_text = safe_text
        assump_list.append(
            f"Fallback template applied due to validation issues: {'; '.join(verdict.violations)}"
        )

    return Recommendation(
        id=rec_id,
        user_id=user_id,
        task_id=task_id,
        run_id=run_id,
        origin=origin,
        text=final_text,
        evidence=ev_list,
        calculations=calc_list,
        assumptions=assump_list,
        tools_used=tools_list,
        memories=mem_list,
        confidence_label=confidence_label,
        simulation_id=simulation_id,
        status="draft",
        created_at=ts,
    )


def format_recommendation_explanation(rec: Recommendation) -> str:
    """
    Render a comprehensive explanation for `copilot explain <recommendation_id>`
    (PLAN_PHASE2 Section 5.8).
    """
    lines = []
    lines.append("=" * 70)
    lines.append(f"RECOMMENDATION: {rec.id}")
    status_line = (
        f"Origin: {rec.origin} | Status: {rec.status} | "
        f"Confidence: {rec.confidence_label or 'unknown'}"
    )
    lines.append(status_line)
    lines.append("=" * 70)
    lines.append("")
    lines.append(f"Text:\n  {rec.text}")
    lines.append("")

    # Evidence
    lines.append("Evidence Cited:")
    if rec.evidence:
        for ev in rec.evidence:
            lines.append(f"  - {ev}")
    else:
        lines.append("  (None cited)")
    lines.append("")

    # Calculations
    lines.append("Calculations Performed:")
    if rec.calculations:
        for c in rec.calculations:
            inputs_str = ", ".join(f"{k}={v}" for k, v in c.inputs.items())
            lines.append(f"  • {c.label} [{c.formula_id}]: ({inputs_str}) -> {c.result}")
    else:
        lines.append("  (None performed)")
    lines.append("")

    # Assumptions
    lines.append("Assumptions:")
    if rec.assumptions:
        for a in rec.assumptions:
            lines.append(f"  * {a}")
    else:
        lines.append("  (No explicit assumptions)")
    lines.append("")

    # Tools Used
    lines.append("Tools Used in Generation:")
    if rec.tools_used:
        for t in rec.tools_used:
            t_name = t.get("tool", "unknown_tool")
            t_status = t.get("status", "done")
            lines.append(f"  - {t_name} ({t_status})")
    else:
        lines.append("  (Direct deterministic synthesis)")
    lines.append("")

    # Memories
    lines.append("User Memories / Past Decisions Relied On:")
    if rec.memories:
        for m in rec.memories:
            lines.append(f"  - [{m.get('kind', 'memory')}] {m.get('summary', str(m))}")
    else:
        lines.append("  (No past decisions consulted)")
    lines.append("")

    # Simulation Link
    if rec.simulation_id:
        lines.append(f"Linked Simulation Scenario: {rec.simulation_id}")
    else:
        lines.append("Linked Simulation Scenario: (None required)")

    lines.append("=" * 70)
    return "\n".join(lines)
