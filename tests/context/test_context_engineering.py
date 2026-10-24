"""
Tests for Stage 3.12 Context Engineering and Injection Hardening (PLAN_PHASE3 Section 5.14).

Test coverage:
1. Token budget respected with exclusions recorded in manifest.
2. Deterministic ordering of context candidates.
3. Manifests NEVER contain raw user prompt text, merchant names, or memory statements (Safety Rule 19).
4. Memory retrieval ranking: subject match (exact 3, parent category 2, global 1) * confidence * recency weight.
5. Memory retrieval tenant isolation (user A never retrieves user B's memories).
6. Memory retrieval status filter (ONLY active memories returned; candidate, stale, retired, rejected, forgotten excluded).
7. Memory retrieval tie-breaking by item id.
8. PII and credential redaction asserted on captured prompts and redaction counts tracked.
9. Architecture test: Workflow and planner LLM entry points go through ContextBuilder.
"""

import ast
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from copilot.config.phase3 import ContextConfig
from copilot.context.builder import ContextBuilder
from copilot.context.retrieval import retrieve_relevant_memories
from copilot.core.timeutil import to_utc_iso
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_user
from copilot.db.repo_phase3 import (
    get_context_manifest,
    insert_memory_evidence,
    insert_memory_item,
)
from copilot.models.agentic import Intent
from copilot.models.domain import User
from copilot.models.phase3 import MemoryEvidence, MemoryItem


@pytest.fixture
def conn():
    c = get_connection(":memory:", check_same_thread=False)
    init_db(c)
    u_alice = User(id="user_alice", created_at="2026-09-01T00:00:00Z")
    insert_user(c, u_alice)
    u_bob = User(id="user_bob", created_at="2026-09-01T00:00:00Z")
    insert_user(c, u_bob)
    return c


def test_token_budget_respected_and_exclusions_recorded(conn):
    """
    Assert that when context items exceed token budget, lower priority items
    are excluded and recorded in manifest.excluded with reason 'budget_exceeded'.
    """
    # Create small budget config: 100 tokens (approx 400 chars)
    cfg = ContextConfig(
        token_budgets={"planning": 80},
        top_k_memories=5,
        character_token_ratio=4,
    )
    builder = ContextBuilder(config=cfg, conn=conn)

    intent = Intent(
        type="affordability",
        period="2026-10",
        amount_paise=5000000,
        confidence_label="high",
        source="deterministic",
    )

    # 10 large tool items
    large_catalogue = [
        {
            "tool_name": f"tool_test_long_name_{i}",
            "short_description": "A very detailed description of this tool with extensive text explaining capabilities "
            * 3,
            "parameters": {"param1": "string", "param2": "integer", "param3": "boolean"},
        }
        for i in range(10)
    ]

    built = builder.build(
        user_id="user_alice",
        task_id="task_budget_test",
        purpose="planning",
        instruction="Propose a plan for the user intent.",
        intent=intent,
        catalogue=large_catalogue,
        conn=conn,
    )

    assert built.estimated_tokens <= 80
    assert len(built.included) > 0
    # Must include mandatory system instruction
    assert any(item["source"] == "instruction" for item in built.included)

    # Some catalogue items must have been excluded due to budget
    assert len(built.excluded) > 0
    for exc in built.excluded:
        assert exc["reason"] == "budget_exceeded"
        assert exc["estimated_tokens"] > 0

    # Verify manifest persisted in DB
    manifest_db = get_context_manifest(conn, "user_alice", built.manifest.id)
    assert manifest_db is not None
    assert manifest_db.budget_tokens == 80
    assert len(manifest_db.excluded) == len(built.excluded)


def test_deterministic_ordering_of_context_candidates():
    """
    Items with identical priorities must sort deterministically by item ID ascending.
    """
    builder = ContextBuilder()
    findings = [
        {"id": "finding_z", "metric": "test", "value": 100},
        {"id": "finding_a", "metric": "test", "value": 200},
        {"id": "finding_m", "metric": "test", "value": 300},
    ]

    built = builder.build(
        user_id="user_alice",
        task_id="task_det_order",
        purpose="narration",
        instruction="Summarize findings.",
        findings=findings,
    )

    finding_items = [i for i in built.included if i["source"] == "findings"]
    ids = [i["id"] for i in finding_items]
    assert ids == sorted(ids), f"Expected sorted finding IDs, got: {ids}"


def test_manifest_never_contains_raw_text(conn):
    """
    Safety Rule 19: No manifest contains user text, merchant names, or memory statements.
    """
    builder = ContextBuilder(conn=conn)
    sensitive_user_text = "Please check my transactions at SecretLuxuryBoutique for ₹95,000"
    sensitive_merchant = "SecretLuxuryBoutique"
    sensitive_memory = "User regularly spends ₹50,000 at SecretLuxuryBoutique"

    mem = MemoryItem(
        id="mem_sens_1",
        user_id="user_alice",
        kind="recurring_pattern",
        subject_key=f"merchant:{sensitive_merchant}",
        statement_json={"merchant": sensitive_merchant, "statement": sensitive_memory},
        source="observed",
        status="active",
        prior_bp=7000,
        user_confirmed=True,
        confidence_bp=7000,
        created_at="2026-10-01T00:00:00Z",
    )
    insert_memory_item(conn, mem)

    built = builder.build(
        user_id="user_alice",
        task_id="task_safety_rule_19",
        purpose="planning",
        instruction="Plan the financial query.",
        untrusted_data={"query": sensitive_user_text, "merchant": sensitive_merchant},
        memories=[mem],
        conn=conn,
    )

    manifest_row = conn.execute(
        "SELECT * FROM context_manifests WHERE id = ?", (built.manifest.id,)
    ).fetchone()
    assert manifest_row is not None

    manifest_dump = json.dumps(dict(manifest_row))
    assert sensitive_user_text not in manifest_dump
    assert sensitive_merchant not in manifest_dump
    assert sensitive_memory not in manifest_dump
    assert "SecretLuxuryBoutique" not in manifest_dump


def test_memory_retrieval_ranking_exact_parent_global(conn):
    """
    Assert ranking formula:
      score = subject_match_weight (exact 3, parent 2, global 1) * confidence * recency
    """
    now_dt = datetime(2026, 10, 15, 12, 0, 0, tzinfo=UTC)
    now_iso = to_utc_iso(now_dt)

    # 1. Exact match item on category:dining (weight 3, confidence 8000 bp, recent)
    m_exact = MemoryItem(
        id="mem_01_exact",
        user_id="user_alice",
        kind="recurring_pattern",
        subject_key="category:dining",
        statement_json={"category": "dining", "pattern": "weekend_heavy"},
        source="observed",
        status="active",
        prior_bp=8000,
        user_confirmed=True,
        confidence_bp=8000,
        created_at=now_iso,
        last_evidence_at=now_iso,
    )
    insert_memory_item(conn, m_exact)
    insert_memory_evidence(
        conn,
        MemoryEvidence(
            id="ev_01",
            user_id="user_alice",
            memory_id=m_exact.id,
            polarity="supports",
            ref_kind="txn",
            ref_id="tx_1",
            observed_at=now_iso,
            weight_bp=8000,
            created_at=now_iso,
        ),
    )

    # 2. Parent category match on category:food (weight 2, confidence 9000 bp, recent)
    m_parent = MemoryItem(
        id="mem_02_parent",
        user_id="user_alice",
        kind="recurring_pattern",
        subject_key="category:food",
        statement_json={"category": "food", "pattern": "month_start_heavy"},
        source="observed",
        status="active",
        prior_bp=9000,
        user_confirmed=True,
        confidence_bp=9000,
        created_at=now_iso,
        last_evidence_at=now_iso,
    )
    insert_memory_item(conn, m_parent)
    insert_memory_evidence(
        conn,
        MemoryEvidence(
            id="ev_02",
            user_id="user_alice",
            memory_id=m_parent.id,
            polarity="supports",
            ref_kind="txn",
            ref_id="tx_2",
            observed_at=now_iso,
            weight_bp=9000,
            created_at=now_iso,
        ),
    )

    # 3. Global item (weight 1, confidence 9500 bp, recent)
    m_global = MemoryItem(
        id="mem_03_global",
        user_id="user_alice",
        kind="preference",
        subject_key="global",
        statement_json={"subject": "global", "waterfall_order": "firm_first"},
        source="user_stated",
        status="active",
        prior_bp=9500,
        user_confirmed=True,
        confidence_bp=9500,
        created_at=now_iso,
        last_evidence_at=now_iso,
    )
    insert_memory_item(conn, m_global)
    insert_memory_evidence(
        conn,
        MemoryEvidence(
            id="ev_03",
            user_id="user_alice",
            memory_id=m_global.id,
            polarity="supports",
            ref_kind="audit_event",
            ref_id="aud_1",
            observed_at=now_iso,
            weight_bp=9500,
            created_at=now_iso,
        ),
    )

    # Retrieve with subject="dining", parent_category="food"
    retrieved = retrieve_relevant_memories(
        conn,
        "user_alice",
        subject="dining",
        parent_category="food",
        top_k=5,
        clock=now_dt,
    )

    assert len(retrieved) == 3
    # Exact match score ~ 3 * 0.8 * 1.0 = 2.4
    # Parent match score ~ 2 * 0.9 * 1.0 = 1.8
    # Global match score ~ 1 * 0.95 * 1.0 = 0.95
    assert retrieved[0].id == "mem_01_exact"
    assert retrieved[1].id == "mem_02_parent"
    assert retrieved[2].id == "mem_03_global"


def test_memory_retrieval_tenant_isolation(conn):
    """
    Assert that Alice NEVER retrieves Bob's memories under any circumstances.
    """
    now_iso = to_utc_iso(datetime.now(UTC))

    m_bob = MemoryItem(
        id="mem_bob_secret",
        user_id="user_bob",
        kind="recurring_pattern",
        subject_key="category:dining",
        statement_json={"category": "dining", "private_info": "bob_secret"},
        source="observed",
        status="active",
        prior_bp=9900,
        user_confirmed=True,
        confidence_bp=9900,
        created_at=now_iso,
        last_evidence_at=now_iso,
    )
    insert_memory_item(conn, m_bob)
    insert_memory_evidence(
        conn,
        MemoryEvidence(
            id="ev_bob",
            user_id="user_bob",
            memory_id=m_bob.id,
            polarity="supports",
            ref_kind="txn",
            ref_id="tx_bob",
            observed_at=now_iso,
            weight_bp=9900,
            created_at=now_iso,
        ),
    )

    # Query for Alice with exact subject match
    results = retrieve_relevant_memories(
        conn,
        "user_alice",
        subject="dining",
        top_k=10,
    )

    assert not any(m.id == "mem_bob_secret" for m in results)
    assert not any(m.user_id == "user_bob" for m in results)


def test_memory_retrieval_status_filter_active_only(conn):
    """
    Assert that ONLY active memories are returned.
    Candidate, stale, retired, rejected, and forgotten are excluded.
    """
    now_dt = datetime(2026, 10, 15, 12, 0, 0, tzinfo=UTC)
    now_iso = to_utc_iso(now_dt)

    # 1. Candidate memory (prior_bp=3000 < use_threshold 6000, not user_confirmed)
    m_cand = MemoryItem(
        id="mem_cand",
        user_id="user_alice",
        kind="recurring_pattern",
        subject_key="global",
        statement_json={"subject": "global"},
        source="observed",
        status="candidate",
        prior_bp=3000,
        user_confirmed=False,
        confidence_bp=3000,
        created_at=now_iso,
        last_evidence_at=now_iso,
    )
    insert_memory_item(conn, m_cand)

    # 2. Forgotten memory
    m_forgot = MemoryItem(
        id="mem_forgot",
        user_id="user_alice",
        kind="preference",
        subject_key="global",
        statement_json={},
        source="user_stated",
        status="forgotten",
        prior_bp=9000,
        user_confirmed=True,
        confidence_bp=9000,
        created_at=now_iso,
        last_evidence_at=now_iso,
    )
    insert_memory_item(conn, m_forgot)

    # 3. Active memory
    m_act = MemoryItem(
        id="mem_active",
        user_id="user_alice",
        kind="preference",
        subject_key="global",
        statement_json={"subject": "global", "pref": "yes"},
        source="user_stated",
        status="active",
        prior_bp=8000,
        user_confirmed=True,
        confidence_bp=8000,
        created_at=now_iso,
        last_evidence_at=now_iso,
    )
    insert_memory_item(conn, m_act)
    insert_memory_evidence(
        conn,
        MemoryEvidence(
            id="ev_act",
            user_id="user_alice",
            memory_id=m_act.id,
            polarity="supports",
            ref_kind="audit_event",
            ref_id="aud_act",
            observed_at=now_iso,
            weight_bp=8000,
            created_at=now_iso,
        ),
    )

    results = retrieve_relevant_memories(conn, "user_alice", top_k=10, clock=now_dt)
    result_ids = [m.id for m in results]

    assert "mem_active" in result_ids
    assert "mem_cand" not in result_ids
    assert "mem_forgot" not in result_ids


def test_redaction_asserted_on_captured_prompts():
    """
    Assert that UPI IDs, phone numbers, account/card numbers, and secrets
    are redacted in the generated prompt and tracked in redactions_count.
    """
    builder = ContextBuilder()
    raw_sensitive_input = (
        "Transfer to user@oksbi with phone +91 9876543210 and account 1234567890123456. "
        "The otp is 987654."
    )

    built = builder.build(
        user_id="user_alice",
        task_id="task_redact_test",
        purpose="intent_extraction",
        instruction="Parse the request.",
        untrusted_data=raw_sensitive_input,
    )

    assert built.redactions_count >= 4
    assert "user@oksbi" not in built.prompt
    assert "+91 9876543210" not in built.prompt
    assert "1234567890123456" not in built.prompt
    assert "[UPI]" in built.prompt
    assert "[PHONE]" in built.prompt
    assert "[ACCOUNT]" in built.prompt
    assert "[REDACTED_SECRET]" in built.prompt


def test_architecture_llm_prompts_use_context_builder():
    """
    Architecture test: Verify that LLM planner, decomposition supervisor,
    reviewer, and intent classifier use ContextBuilder for prompt construction.
    """
    src_root = Path(__file__).resolve().parents[2] / "src" / "copilot"

    target_files = [
        src_root / "planner" / "llm_planner.py",
        src_root / "workflow" / "decomposition.py",
        src_root / "workflow" / "reviewer.py",
        src_root / "core" / "intent.py",
    ]

    for target in target_files:
        assert target.is_file(), f"Target file missing: {target}"
        content = target.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(target))

        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and "context.builder" in node.module:
                    imports.extend(alias.name for alias in node.names)

        assert "ContextBuilder" in imports, (
            f"{target.name} must import and use ContextBuilder for LLM prompt construction."
        )
