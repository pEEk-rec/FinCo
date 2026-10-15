"""
Script to execute the Phase 3 evaluation harness and generate docs/eval_report_phase3.md.
"""

import sys
from pathlib import Path

# Ensure implementation root is on sys.path
root = Path(__file__).resolve().parents[1]
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from copilot.eval.harness_phase3 import run_phase3_evaluation  # noqa: E402


def main() -> None:
    print("Running Finance Copilot Phase 3 Evaluation Harness (seeds: [777, 888, 999])...")
    report = run_phase3_evaluation()
    print("\nPhase 3 Evaluation Completed Successfully!")
    print(f"Report written to: docs/eval_report_phase3.md (duration: {report['duration_seconds']}s)")
    print(f"Commitments Expansion Accuracy: {report['commitments']['expansion_accuracy_pct']}%")
    print(f"Calendar Balance Conservation: {report['calendar']['balance_conservation_pass']}")
    print(f"Calendar Shortfall Precision: {report['calendar']['shortfall_detection_accuracy_pct']}%")
    print(f"Buckets 1-to-1 Uniqueness: {report['buckets']['uniqueness_invariant_pass']}")
    print(f"Buckets 2-Step Governance: {report['buckets']['governance_two_step_pass']}")
    print(f"Readiness Classification Accuracy: {report['readiness']['accuracy_pct']}%")
    print(f"Memory Forgetting Verifiability: {report['memory']['forgetting_verifiability_pct']}%")
    print(f"Multi-Agent Parallel Speedup: {report['agent']['parallel_speedup']}x")
    print(f"Multi-Agent Reviewer Catch Rate: {report['orchestration']['reviewer_catch_rate_pct']}%")
    print(f"Learning Safety Floors Protected: {report['learning']['safety_floors_protected_pct']}%")
    print(f"Safety Lease Atomicity: {report['safety_and_runtime']['lease_atomicity_pass']}")
    print(f"Zero Float Currency Violations: {report['safety_and_runtime']['zero_float_violations']}")


if __name__ == "__main__":
    main()
