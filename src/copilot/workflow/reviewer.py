"""
Reviewer (critic) and Reflexion-style revision loop (PLAN_PHASE3 Section 5.13).

Invariants:
1. Deterministic checks first: all sub-questions answered or in gaps,
   confidence labels present, causal rules pass.
2. Optional LLM critic from a closed set:
   {'missed_subquestion', 'unclear_answer', 'unsupported_claim', 'missing_caveat', 'ok'}.
3. Safety Rule 14: The LLM critic CANNOT introduce or change numbers.
   Any critique containing numbers is rejected.
4. Revision rounds are strictly bounded (default 1).
5. All reflections are recorded in the `reflections` table.
"""

import json
import logging
import re
import sqlite3
import uuid
from typing import Any

from copilot.audit.events import record_event
from copilot.context.builder import ContextBuilder
from copilot.core.timeutil import now_utc, to_utc_iso
from copilot.db.repo_phase3 import insert_reflection
from copilot.llm.client import LLMClient, extract_json
from copilot.models.phase3 import Reflection, SpecialistReport, SubQuestion
from copilot.tools.executor import ExecutionContext
from copilot.workflow.multi_agent import merge_specialist_reports
from copilot.workflow.specialists import DOMAIN_TO_ROLE, run_specialist

logger = logging.getLogger(__name__)

ALLOWED_CRITIQUE_CODES = {
    "missed_subquestion",
    "unclear_answer",
    "unsupported_claim",
    "missing_caveat",
    "ok",
}


def deterministic_review(
    subquestions: list[SubQuestion],
    reports: list[SpecialistReport],
    merge_result: dict[str, Any],
) -> list[str]:
    """
    Perform deterministic critique checks:
    1. Every sub-question answered or explicitly marked as a gap.
    2. Confidence labels present on all findings.
    3. Causal claim checks (evidence present).
    """
    critique_codes: set[str] = set()
    findings = merge_result.get("findings", [])
    gaps = merge_result.get("gaps", [])

    # 1. Check sub-question coverage
    for sq in subquestions:
        answered = False
        # Check if any finding addresses this subquestion
        for f in findings:
            metric = f.get("metric", "")
            evidence = str(f.get("evidence", ""))
            if sq.question_kind in metric or sq.question_kind in evidence:
                answered = True
                break

        # Check if explicitly mentioned in gaps
        in_gaps = any(sq.question_kind in g or sq.domain in g for g in gaps)

        if not answered and not in_gaps:
            critique_codes.add("missed_subquestion")

    # 2. Check confidence labels
    for f in findings:
        conf = f.get("confidence")
        if not conf or conf not in ("high", "medium", "low"):
            critique_codes.add("missing_caveat")

        # 3. Check evidence for causal claims
        if not f.get("evidence"):
            critique_codes.add("unsupported_claim")

    if not critique_codes:
        return ["ok"]
    return sorted(critique_codes)


def llm_critic_review(
    llm_client: LLMClient,
    subquestions: list[SubQuestion],
    merge_result: dict[str, Any],
    conn: sqlite3.Connection | None = None,
    user_id: str | None = None,
    task_id: str | None = None,
) -> list[str]:
    """
    Closed-set LLM critic.
    Enforces Safety Rule 14: Critic CANNOT introduce or change numbers.
    Any critique output containing digits is rejected and audited.
    """
    effective_task_id = task_id or "task_review"
    builder = ContextBuilder(conn=conn)
    instruction = (
        "Review the following findings against subquestions. Respond in JSON with:\n"
        "{\n"
        '  "critique_code": "missed_subquestion" | "unclear_answer" | '
        '"unsupported_claim" | "missing_caveat" | "ok",\n'
        '  "explanation": "brief text without any numbers"\n'
        "}\n"
        "SAFETY RULE: You CANNOT introduce or change numbers. "
        "Do not include any digits in your critique."
    )

    try:
        raw_reply, _ = builder.complete(
            client=llm_client,
            user_id=user_id or "user_unknown",
            task_id=effective_task_id,
            purpose="critique",
            instruction=instruction,
            sub_questions=subquestions,
            findings=merge_result.get("findings", []),
            conn=conn,
        )
        text = extract_json(raw_reply)

        # Safety Rule 14: The LLM critic CANNOT introduce or change numbers
        if re.search(r"\d", text):
            msg = (
                "LLM critic output contained numbers, violating Safety Rule 14. "
                "Critique rejected."
            )
            logger.warning(msg)
            if conn and user_id:
                record_event(
                    conn=conn,
                    user_id=user_id,
                    actor="agent",
                    event_type="critic_number_rejected",
                    reason=msg,
                    run_id=task_id,
                )
            raise ValueError(msg)


        data = json.loads(text)
        code = data.get("critique_code", "ok")
        if code not in ALLOWED_CRITIQUE_CODES:
            logger.warning("Critic returned unknown code '%s'; defaulting to 'ok'", code)
            return ["ok"]
        return [code]

    except ValueError:
        raise
    except Exception as exc:
        logger.warning("LLM critic failed: %s; falling back to deterministic review", exc)
        return ["ok"]


def run_review_and_revision(
    subquestions: list[SubQuestion],
    reports: list[SpecialistReport],
    merge_result: dict[str, Any],
    ctx: ExecutionContext,
    task_id: str,
    llm_client: LLMClient | None = None,
    max_revision_rounds: int = 1,
) -> tuple[dict[str, Any], list[SpecialistReport], list[Reflection]]:
    """
    Execute deterministic review + closed-set critic, with at most max_revision_rounds (default 1).
    Records every reflection in the database.
    """
    current_merge = dict(merge_result)
    current_reports = list(reports)
    reflections: list[Reflection] = []

    round_idx = 0
    while round_idx <= max_revision_rounds:
        # 1. Deterministic Review
        det_codes = deterministic_review(subquestions, current_reports, current_merge)
        critic_source = "deterministic"
        codes = det_codes

        # 2. Optional LLM Critic (if deterministic passed with ok)
        if codes == ["ok"] and llm_client is not None:
            try:
                llm_codes = llm_critic_review(
                    llm_client=llm_client,
                    subquestions=subquestions,
                    merge_result=current_merge,
                    conn=ctx.conn,
                    user_id=ctx.user_id,
                    task_id=task_id,
                )
                codes = llm_codes
                critic_source = "llm_critic"
            except ValueError as ve:
                # Number injection rejected; continue with deterministic facts unchanged
                logger.info("Critic rejected: %s", ve)
                codes = ["ok"]

        is_ok = (codes == ["ok"])

        if is_ok:
            # Review passed
            outcome = "fixed" if round_idx > 0 else "unchanged"
            refl = Reflection(
                id=f"ref_{uuid.uuid4().hex[:12]}",
                user_id=ctx.user_id,
                task_id=task_id,
                round=round_idx,
                critique_codes=codes,
                source=critic_source,  # type: ignore[arg-type]
                revised=(round_idx > 0),
                outcome=outcome,  # type: ignore[arg-type]
                created_at=to_utc_iso(now_utc(ctx.clock)),
            )
            reflections.append(refl)
            if ctx.conn:
                insert_reflection(ctx.conn, refl)
            break

        # Critique raised an issue
        if round_idx >= max_revision_rounds:
            # Reached max revision rounds; must give up rather than looping indefinitely
            refl = Reflection(
                id=f"ref_{uuid.uuid4().hex[:12]}",
                user_id=ctx.user_id,
                task_id=task_id,
                round=round_idx,
                critique_codes=codes,
                source=critic_source,  # type: ignore[arg-type]
                revised=False,
                outcome="gave_up",
                created_at=to_utc_iso(now_utc(ctx.clock)),
            )
            reflections.append(refl)
            if ctx.conn:
                insert_reflection(ctx.conn, refl)
            break

        # Perform Revision: find affected subquestion(s)
        refl = Reflection(
            id=f"ref_{uuid.uuid4().hex[:12]}",
            user_id=ctx.user_id,
            task_id=task_id,
            round=round_idx,
            critique_codes=codes,
            source=critic_source,  # type: ignore[arg-type]
            revised=True,
            outcome="unchanged",
            created_at=to_utc_iso(now_utc(ctx.clock)),
        )
        reflections.append(refl)
        if ctx.conn:
            insert_reflection(ctx.conn, refl)

        # Find which subquestions need re-running
        affected_subquestions = []
        if "missed_subquestion" in codes:
            for sq in subquestions:
                answered = any(
                    sq.question_kind in f.get("metric", "")
                    or sq.question_kind in str(f.get("evidence", ""))
                    for f in current_merge.get("findings", [])
                )
                if not answered:
                    affected_subquestions.append(sq)
        else:
            # Re-run all subquestions if unclear or unsupported
            affected_subquestions = list(subquestions)

        logger.info(
            "Revision round %d: re-running %d affected subquestion(s)",
            round_idx,
            len(affected_subquestions),
        )
        for sq in affected_subquestions:
            role = DOMAIN_TO_ROLE.get(sq.domain, "CashflowAgent")
            revised_report = run_specialist(role, sq, ctx, task_id)
            # Replace old report or append
            current_reports = [
                r
                for r in current_reports
                if (
                    r.agent_role != role
                    or r.sub_question_json.get("question_kind") != sq.question_kind
                )
            ]
            current_reports.append(revised_report)

        # Re-merge
        current_merge = merge_specialist_reports(
            current_reports, ctx.user_id, task_id, conn=ctx.conn
        )
        round_idx += 1


    return current_merge, current_reports, reflections
