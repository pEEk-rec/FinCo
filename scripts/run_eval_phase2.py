"""
Script to execute the Phase 2 evaluation harness and generate docs/eval_report_phase2.md.
"""

import sys
from pathlib import Path

# Ensure implementation root is on sys.path
root = Path(__file__).resolve().parents[1]
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from copilot.eval.harness_phase2 import run_phase2_evaluation  # noqa: E402


def main() -> None:
    print("Running Finance Copilot Phase 2 Evaluation Harness (seeds: [777, 888, 999])...")
    report = run_phase2_evaluation()
    print("\nPhase 2 Evaluation Completed Successfully!")
    print("Report written to: docs/eval_report_phase2.md")
    print(f"Intent Type Accuracy: {report['intent']['type_accuracy_pct']}%")
    prec = report["intent"]["refusal_precision_pct"]
    rec = report["intent"]["refusal_recall_pct"]
    print(f"Refusal Precision / Recall: {prec}% / {rec}%")
    match_pct = report["planner"]["exact_set_match_pct"]
    extra_tools = report["planner"]["extra_tools_per_task"]
    print(f"Planner Canonical Match: {match_pct}% (Extra tools: {extra_tools})")
    print(f"Adversarial Plan Rejection: {report['planner']['adversarial_rejection_pct']}%")
    decomp = report["investigation_standard"]["decomposition_invariant_pass_pct"]
    print(f"Decomposition Exactness: {decomp}%")
    false_exp = report["investigation_standard"]["false_explanation_rate_pct"]
    print(f"False Explanation Rate: {false_exp}%")
    sim_ok = (
        report["simulation"]["identity_pass"]
        and report["simulation"]["conservation_of_paise_pass"]
    )
    print(f"Simulation Invariants: {'PASS' if sim_ok else 'FAIL'}")
    print(f"Alerts Ordinary Month Silence: {report['alerts']['ordinary_month_silence_pct']}%")
    print(f"Narration Grounding Accuracy: {report['recommendations']['grounding_accuracy_pct']}%")
    print(f"Causal Claim Violations: {report['recommendations']['causal_claim_violations']}")
    missing_sim = report["recommendations"]["consequence_missing_simulation_violations"]
    print(f"Missing Simulation Violations: {missing_sim}")
    print(f"Mean Latency: {report['mean_query_latency_ms']}ms")


if __name__ == "__main__":
    main()
