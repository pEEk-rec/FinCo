"""
Script to execute the evaluation harness and generate docs/eval_report.md.
"""

import sys
from pathlib import Path

# Ensure implementation root is on sys.path
root = Path(__file__).resolve().parents[1]
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from copilot.eval.harness import run_evaluation  # noqa: E402


def main() -> None:
    print("Running Finance Copilot Evaluation Harness across seeds [42, 123, 999]...")
    report = run_evaluation()
    print("\nEvaluation Completed Successfully!")
    print("Report written to: docs/eval_report.md")
    print(f"Categorization Accuracy: {report['summary']['categorization_accuracy_mean']}%")
    print(f"Categorization Coverage: {report['summary']['categorization_coverage_mean']}%")
    print(f"High-Confidence Precision: {report['summary']['high_confidence_precision_mean']}%")
    print(f"Transfer F1: {report['summary']['transfer_f1_mean']}")
    print(f"Recurring F1: {report['summary']['recurring_f1_mean']}")
    print(f"Anomaly F1: {report['summary']['anomaly_f1_mean']}")
    print(f"Idempotency Check: {'PASS' if report['summary']['idempotency_pass'] else 'FAIL'}")


if __name__ == "__main__":
    main()
