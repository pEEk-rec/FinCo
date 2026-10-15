"""
Tests for Stage 3.16 Orchestration Comparison (PLAN_PHASE3 Section 5.13 & Section 7).

Validates:
1. Benchmark runner executes across all 5 built paradigm variations.
2. Architectural invariants:
   - Phase 3 Multi-Agent coverage > Phase 2 Single Loop coverage > Phase 1 Fixed Graph coverage.
   - Phase 1 fixed pipeline has the lowest mean latency.
   - Deterministic / LLM-off modes make exactly 0 LLM calls.
   - All built configurations maintain 0% crash / failure rate.
   - docs/orchestration_paradigms.md is generated with empirical measurements.
"""

from pathlib import Path

from copilot.eval.orchestration_comparison import (
    generate_orchestration_paradigms_document,
    run_orchestration_benchmark,
)


def test_orchestration_benchmark_runs_and_satisfies_invariants():
    """Verify that the empirical benchmark runs and meets all structural invariants."""
    metrics = run_orchestration_benchmark()

    # 1. All paradigms present
    expected_paradigms = {
        "phase1_fixed",
        "phase2_single_loop_llm_off",
        "phase2_single_loop_llm_on",
        "phase3_multi_agent_llm_off",
        "phase3_multi_agent_llm_on",
    }
    assert set(metrics.keys()) == expected_paradigms

    p1 = metrics["phase1_fixed"]
    p2_off = metrics["phase2_single_loop_llm_off"]
    p2_on = metrics["phase2_single_loop_llm_on"]
    p3_off = metrics["phase3_multi_agent_llm_off"]
    p3_on = metrics["phase3_multi_agent_llm_on"]

    # 2. Coverage progression invariant: Phase 3 > Phase 2 > Phase 1
    assert p3_off.coverage_pct > p2_off.coverage_pct
    assert p2_off.coverage_pct > p1.coverage_pct
    assert p3_off.coverage_pct >= 95.0  # Phase 3 covers virtually all sub-questions

    # 3. Accuracy progression invariant: Phase 3 multi-agent attains highest accuracy
    assert p3_off.accuracy_pct >= p2_off.accuracy_pct
    assert p2_off.accuracy_pct >= p1.accuracy_pct

    # 4. Latency invariant: Phase 1 fixed compiled graph is the fastest
    assert p1.latency_mean_ms < p2_off.latency_mean_ms
    assert p1.latency_mean_ms < p3_off.latency_mean_ms

    # 5. LLM calls invariant
    assert p1.llm_calls_mean == 0.0
    assert p2_off.llm_calls_mean == 0.0
    assert p3_off.llm_calls_mean == 0.0
    assert p2_on.llm_calls_mean > 0.0
    assert p3_on.llm_calls_mean > 0.0

    # 6. Reliability invariant: 0% unhandled failures
    assert p1.failure_rate_pct == 0.0
    assert p2_off.failure_rate_pct == 0.0
    assert p3_off.failure_rate_pct == 0.0

    # 7. Fault tolerance: partial answer handling under gaps
    assert p3_off.partial_rate_pct > 0.0


def test_orchestration_paradigms_document_generated(tmp_path: Path):
    """Verify that generate_orchestration_paradigms_document generates valid markdown."""
    metrics = run_orchestration_benchmark()
    out_file = tmp_path / "orchestration_paradigms.md"
    doc_path = generate_orchestration_paradigms_document(metrics, output_path=out_file)

    assert Path(doc_path).exists()
    content = Path(doc_path).read_text(encoding="utf-8")

    # Invariants in generated document
    assert "# Orchestration Paradigms: Comparative Evaluation and Architectural Analysis" in content
    assert "Fixed Graph (Phase 1)" in content
    assert "Single Planner Loop (Phase 2)" in content
    assert "Supervisor + Specialists (Phase 3)" in content
    assert "Conversational Multi-Agent" in content
    assert "The Routing Rule" in content
    assert "Measured Empirical Results" in content
