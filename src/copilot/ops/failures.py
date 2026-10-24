"""
Failure candidate exporter for agentic SDLC (PLAN_PHASE3 Section 5.13).

Exports tasks with `gave_up`, `merge_conflict`, budget stops, or validator fallbacks
into `eval/candidates/` as draft golden cases.
"""

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

import yaml

from copilot.core.config import PROJECT_ROOT

logger = logging.getLogger(__name__)


def export_failures(
    conn: sqlite3.Connection,
    output_dir: str | Path | None = None,
) -> list[Path]:
    """
    Query database for failure tasks (gave_up reflections, merge conflicts, validator fallbacks,
    or budget stops) and export them as draft golden test candidates.
    """
    if output_dir is None:
        target_dir = PROJECT_ROOT / "eval" / "candidates"
    else:
        target_dir = Path(output_dir)

    target_dir.mkdir(parents=True, exist_ok=True)
    exported_files: list[Path] = []

    # 1. Query reflections with gave_up
    gave_up_rows = conn.execute(
        "SELECT task_id, user_id, round, critique_codes_json, source, outcome, created_at "
        "FROM reflections WHERE outcome = 'gave_up'"
    ).fetchall()

    candidate_tasks: dict[str, dict[str, Any]] = {}

    for r in gave_up_rows:
        tid = r[0]
        candidate_tasks[tid] = {
            "task_id": tid,
            "user_id": r[1],
            "failure_type": "gave_up",
            "reason": f"Reflection revision failed after round {r[2]}",
            "critique_codes": json.loads(r[3]),
            "source": r[4],
            "created_at": r[6],
        }

    # 2. Query audit events for merge_conflict, validator_fallback, budget_stop
    audit_rows = conn.execute(
        """
        SELECT run_id, user_id, event_type, reason, metadata_json, occurred_at
        FROM audit_events
        WHERE event_type IN ('merge_conflict', 'validator_fallback', 'budget_stop')
        """
    ).fetchall()

    for r in audit_rows:
        tid = r[0]
        if not tid:
            continue
        if tid not in candidate_tasks:
            meta = json.loads(r[4]) if r[4] else {}
            candidate_tasks[tid] = {
                "task_id": tid,
                "user_id": r[1],
                "failure_type": r[2],
                "reason": r[3],
                "metadata": meta,
                "created_at": r[5],
            }

    # 3. Query agent tasks with failure stop reasons
    task_rows = conn.execute(
        """
        SELECT id, user_id, raw_text, status, stop_reason, created_at
        FROM agent_tasks
        WHERE stop_reason IN ('gave_up', 'merge_conflict', 'budget_stop', 'loop_limit')
        """
    ).fetchall()

    for r in task_rows:
        tid = r[0]
        if tid not in candidate_tasks:
            candidate_tasks[tid] = {
                "task_id": tid,
                "user_id": r[1],
                "failure_type": r[4],
                "reason": f"Agent task stopped with reason: {r[4]}",
                "raw_text": r[2],
                "created_at": r[5],
            }
        else:
            candidate_tasks[tid]["raw_text"] = r[2]

    # Write candidates to YAML files
    for tid, data in candidate_tasks.items():
        data["expected_behavior"] = "# TODO: Define expected behavior for regression test"
        file_path = target_dir / f"{tid}.yaml"
        with open(file_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, sort_keys=False)
        exported_files.append(file_path)
        logger.info("Exported failure candidate: %s", file_path)

    return exported_files
