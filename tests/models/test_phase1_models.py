from copilot.models.domain import (
    AdviceItem,
    Anomaly,
    Consent,
    IngestionBatch,
    LLMCategoryCache,
    MerchantOverride,
    MonthlyReview,
    RecurringSeries,
    TransferLink,
)
from copilot.models.findings import Finding, FindingNumber


def test_json_round_trips():
    """Phase 1 models can round-trip to/from JSON (used for logging/storage)."""

    # Consent
    c = Consent(
        id="c1",
        user_id="u1",
        purpose="budgeting",
        fi_types="DEPOSIT",
        account_ids='["a1"]',
        date_range_from="2024-01-01T00:00:00Z",
        date_range_to="2024-12-31T23:59:59Z",
        status="active",
        expires_at="2025-01-01T00:00:00Z",
        created_at="2024-01-01T00:00:00Z",
    )
    assert Consent.model_validate_json(c.model_dump_json()) == c

    # IngestionBatch
    ib = IngestionBatch(
        id="ib1",
        user_id="u1",
        consent_id="c1",
        account_id="a1",
        range_from="2024-01-01T00:00:00Z",
        range_to="2024-01-31T23:59:59Z",
        status="completed",
        started_at="2024-02-01T00:00:00Z",
    )
    assert IngestionBatch.model_validate_json(ib.model_dump_json()) == ib

    # MerchantOverride
    mo = MerchantOverride(
        id="mo1",
        user_id="u1",
        merchant_normalized="uber",
        category_id="cat1",
        created_by="user",
        created_at="2024-02-01T00:00:00Z",
    )
    assert MerchantOverride.model_validate_json(mo.model_dump_json()) == mo

    # LLMCategoryCache
    lcc = LLMCategoryCache(
        id="lcc1",
        user_id="u1",
        merchant_normalized="uber",
        category_id="cat1",
        confidence=0.9,
        model="gemini-1.5-flash",
        prompt_version="v1",
        created_at="2024-02-01T00:00:00Z",
    )
    assert LLMCategoryCache.model_validate_json(lcc.model_dump_json()) == lcc

    # RecurringSeries
    rs = RecurringSeries(
        id="rs1",
        user_id="u1",
        merchant_normalized="netflix",
        typical_amount_paise=100000,
        cadence_days=30,
        last_seen="2024-02-01T00:00:00Z",
        next_expected="2024-03-01T00:00:00Z",
        confidence=0.8,
        kind="subscription",
    )
    assert RecurringSeries.model_validate_json(rs.model_dump_json()) == rs

    # TransferLink
    tl = TransferLink(
        id="tl1",
        user_id="u1",
        debit_txn_id="t1",
        credit_txn_id="t2",
        confidence=0.95,
        created_at="2024-02-01T00:00:00Z",
    )
    assert TransferLink.model_validate_json(tl.model_dump_json()) == tl

    # Anomaly
    an = Anomaly(
        id="an1",
        user_id="u1",
        kind="duplicate",
        score=0.99,
        details_json="{}",
        run_id="run1",
        status="open",
        created_at="2024-02-01T00:00:00Z",
    )
    assert Anomaly.model_validate_json(an.model_dump_json()) == an

    # Finding
    fi = Finding(
        id="fi1",
        kind="category_spend",
        period="2024-02",
        subject="Food",
        numbers=[FindingNumber(label="spend", value=1000, unit="paise")],
        description="High spend",
    )
    assert Finding.model_validate_json(fi.model_dump_json()) == fi

    # AdviceItem
    ai = AdviceItem(
        id="ai1",
        user_id="u1",
        run_id="run1",
        finding_ids_json="[]",
        text="Watch out",
        evidence_json="{}",
        assumptions_json="{}",
        status="draft",
        created_at="2024-02-01T00:00:00Z",
    )
    assert AdviceItem.model_validate_json(ai.model_dump_json()) == ai

    # MonthlyReview
    mr = MonthlyReview(
        id="mr1",
        user_id="u1",
        year=2024,
        month=1,
        version=1,
        run_id="run1",
        review_json="{}",
        created_at="2024-02-01T00:00:00Z",
    )
    assert MonthlyReview.model_validate_json(mr.model_dump_json()) == mr
