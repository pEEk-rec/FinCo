"""
Tool specifications and handlers for investigation (PLAN_PHASE2 Section 5.4 & Stage 2.4).

Governance:
- investigate_anomaly and explain_change: SideEffect.READ, planner-selectable (compute class).
- dismiss_anomaly: SideEffect.WRITE_LOGICAL, user actor only, NOT planner-selectable.
"""

from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import Field

from copilot.audit.events import record_event
from copilot.config.phase2 import load_investigation_config
from copilot.core.errors import ErrorCode, ToolFailure
from copilot.core.investigation import decompose_spend_change, run_investigation_suite
from copilot.core.timeutil import IST, month_bounds, now_utc
from copilot.db import repo
from copilot.models.agentic import Investigation
from copilot.tools.contracts import SideEffect, ToolInput, ToolOutput, ToolSpec
from copilot.tools.registry import register

if TYPE_CHECKING:
    from copilot.tools.executor import ExecutionContext


# -------------------------------------------------------------------------------------------------
# 1. investigate_anomaly
# -------------------------------------------------------------------------------------------------


class InvestigateAnomalyInput(ToolInput):
    """Input for investigating a detected financial anomaly."""

    anomaly_id: str = Field(description="Identifier or transaction ID of the anomaly to examine")


class InvestigateAnomalyOutput(ToolOutput):
    """Output containing the investigation result, hypotheses, and evidence."""

    investigation: Investigation
    decomposition: dict[str, int]


def investigate_anomaly_handler(
    ctx: "ExecutionContext", anomaly_id: str
) -> InvestigateAnomalyOutput:
    """Investigate an anomaly against baseline transactions and catalogue hypotheses."""
    config = load_investigation_config()

    # Look up the target transaction(s) associated with this anomaly
    # Check if anomaly_id is a direct transaction ID for this user
    all_txs = repo.list_transactions(
        ctx.conn, ctx.user_id, "1970-01-01T00:00:00Z", "2030-01-01T00:00:00Z"
    )

    matching_txs = [t for t in all_txs if t.id == anomaly_id]
    if not matching_txs:
        # Check by merchant or partial ID
        matching_txs = [
            t for t in all_txs if anomaly_id in t.id or anomaly_id in (t.merchant_raw or "")
        ]

    if not matching_txs:
        raise ToolFailure(
            ErrorCode.INVALID_INPUT,
            f"No transactions found matching anomaly '{anomaly_id}' for user",
        )

    target_tx = matching_txs[0]
    period = target_tx.occurred_at[:7]  # YYYY-MM

    # Collect target month transactions vs baseline history
    target_bounds = month_bounds(int(period[:4]), int(period[5:7]))
    target_txns = repo.list_transactions(ctx.conn, ctx.user_id, *target_bounds)

    # Baseline lookback
    baseline_txns = [t for t in all_txs if t.occurred_at < target_bounds[0]]

    decomp = decompose_spend_change(baseline_txns, target_txns)
    inv = run_investigation_suite(
        user_id=ctx.user_id,
        target_txns=target_txns,
        baseline_txns=baseline_txns,
        subject_kind="anomaly",
        subject_ref={
            "anomaly_id": anomaly_id,
            "txn_id": target_tx.id,
            "category_id": target_tx.category_id,
        },
        period=period,
        config=config,
        conn=ctx.conn,
    )

    repo.insert_investigation(ctx.conn, inv)

    record_event(
        ctx.conn,
        ctx.user_id,
        ctx.actor,
        "investigation_executed",
        "Investigated anomaly against hypothesis catalogue",
        metadata={
            "investigation_id": inv.id,
            "anomaly_id": anomaly_id,
            "outcome": inv.outcome,
            "explained_share_bp": inv.explained_share_bp,
        },
    )

    return InvestigateAnomalyOutput(
        investigation=inv,
        decomposition={
            "volume_effect_paise": decomp.volume_effect_paise,
            "ticket_effect_paise": decomp.ticket_effect_paise,
            "new_merchant_paise": decomp.new_merchant_paise,
            "stopped_merchant_paise": decomp.stopped_merchant_paise,
            "residual_paise": decomp.residual_paise,
            "total_change_paise": decomp.total_change_paise,
        },
    )


# -------------------------------------------------------------------------------------------------
# 2. explain_change
# -------------------------------------------------------------------------------------------------


class ExplainChangeInput(ToolInput):
    """Input for explaining period-over-period spend changes in a category or merchant."""

    period: str | None = Field(default=None, description="Target IST calendar month (YYYY-MM)")
    category_id: str | None = Field(default=None, description="Optional category to focus on")
    merchant: str | None = Field(default=None, description="Optional merchant name to focus on")
    baseline_period: str | None = Field(
        default=None, description="Optional baseline month (YYYY-MM); defaults to prior month"
    )


class ExplainChangeOutput(ToolOutput):
    """Output of change explanation."""

    investigation: Investigation
    decomposition: dict[str, int]


def explain_change_handler(
    ctx: "ExecutionContext",
    period: str | None = None,
    category_id: str | None = None,
    merchant: str | None = None,
    baseline_period: str | None = None,
) -> ExplainChangeOutput:
    """Explain why spend changed in a category or period compared to baseline."""
    config = load_investigation_config()

    if period is None:
        now_dt = ctx.clock if isinstance(ctx.clock, datetime) else now_utc()
        ist_now = now_dt.astimezone(IST)
        period = f"{ist_now.year:04d}-{ist_now.month:02d}"

    try:
        t_year = int(period[:4])
        t_month = int(period[5:7])
    except Exception:
        raise ToolFailure(
            ErrorCode.INVALID_INPUT,
            f"Invalid target period '{period}'; expected format YYYY-MM",
        ) from None

    t_bounds = month_bounds(t_year, t_month)
    target_all = repo.list_transactions(ctx.conn, ctx.user_id, *t_bounds)

    if baseline_period:
        try:
            b_year = int(baseline_period[:4])
            b_month = int(baseline_period[5:7])
            b_bounds = month_bounds(b_year, b_month)
            base_all = repo.list_transactions(ctx.conn, ctx.user_id, *b_bounds)
        except Exception:
            raise ToolFailure(
                ErrorCode.INVALID_INPUT,
                f"Invalid baseline period '{baseline_period}'; expected format YYYY-MM",
            ) from None
    else:
        # Default baseline: prior month or up to 3 lookback months
        b_year, b_month = (t_year - 1, 12) if t_month == 1 else (t_year, t_month - 1)
        b_bounds = month_bounds(b_year, b_month)
        base_all = repo.list_transactions(ctx.conn, ctx.user_id, *b_bounds)

    # Filter by category or merchant if specified
    if category_id:
        target_txns = [t for t in target_all if getattr(t, "category_id", None) == category_id]
        base_txns = [t for t in base_all if getattr(t, "category_id", None) == category_id]
        subject_kind = "category_change"
        subject_ref = {"category_id": category_id, "period": period, "baseline": baseline_period}
    elif merchant:
        target_txns = [
            t
            for t in target_all
            if merchant.lower() in (t.merchant_normalized or t.merchant_raw or "").lower()
        ]
        base_txns = [
            t
            for t in base_all
            if merchant.lower() in (t.merchant_normalized or t.merchant_raw or "").lower()
        ]
        subject_kind = "merchant_change"
        subject_ref = {"merchant": merchant, "period": period, "baseline": baseline_period}
    else:
        target_txns = target_all
        base_txns = base_all
        subject_kind = "period_change"
        subject_ref = {"period": period, "baseline": baseline_period}

    decomp = decompose_spend_change(base_txns, target_txns)
    inv = run_investigation_suite(
        user_id=ctx.user_id,
        target_txns=target_txns,
        baseline_txns=base_txns,
        subject_kind=subject_kind,
        subject_ref=subject_ref,
        period=period,
        config=config,
        conn=ctx.conn,
    )

    repo.insert_investigation(ctx.conn, inv)

    record_event(
        ctx.conn,
        ctx.user_id,
        ctx.actor,
        "change_explained",
        "Explained period spend change against hypothesis catalogue",
        metadata={
            "investigation_id": inv.id,
            "period": period,
            "outcome": inv.outcome,
            "explained_share_bp": inv.explained_share_bp,
        },
    )

    return ExplainChangeOutput(
        investigation=inv,
        decomposition={
            "volume_effect_paise": decomp.volume_effect_paise,
            "ticket_effect_paise": decomp.ticket_effect_paise,
            "new_merchant_paise": decomp.new_merchant_paise,
            "stopped_merchant_paise": decomp.stopped_merchant_paise,
            "residual_paise": decomp.residual_paise,
            "total_change_paise": decomp.total_change_paise,
        },
    )


# -------------------------------------------------------------------------------------------------
# 3. dismiss_anomaly
# -------------------------------------------------------------------------------------------------


class DismissAnomalyInput(ToolInput):
    """Input for dismissing a detected anomaly as expected."""

    anomaly_id: str = Field(description="Anomaly ID to dismiss")
    reason: str | None = Field(default=None, description="Optional user dismissal reason")


class DismissAnomalyOutput(ToolOutput):
    """Result of anomaly dismissal."""

    anomaly_id: str
    status: str = "dismissed"
    reason: str | None = None


def dismiss_anomaly_handler(
    ctx: "ExecutionContext", anomaly_id: str, reason: str | None = None
) -> DismissAnomalyOutput:
    """User tool to dismiss an anomaly as expected or planned."""
    record_event(
        ctx.conn,
        ctx.user_id,
        ctx.actor,
        "anomaly_dismissed",
        reason or "User dismissed anomaly as expected",
        metadata={"anomaly_id": anomaly_id, "reason": reason},
    )
    return DismissAnomalyOutput(
        anomaly_id=anomaly_id,
        status="dismissed",
        reason=reason,
    )


# -------------------------------------------------------------------------------------------------
# Registration
# -------------------------------------------------------------------------------------------------


def register_investigation_tools(register_fn: Callable[[ToolSpec], None] = register) -> None:
    """Register investigation tools into the global registry."""
    register_fn(
        ToolSpec(
            name="investigate_anomaly",
            description="Investigate a detected financial anomaly using the hypothesis catalogue.",
            side_effect=SideEffect.READ,
            input_model=InvestigateAnomalyInput,
            output_model=InvestigateAnomalyOutput,
            handler=investigate_anomaly_handler,
        )
    )

    register_fn(
        ToolSpec(
            name="explain_change",
            description="Explain period-over-period spend changes via deterministic decomposition.",
            side_effect=SideEffect.READ,
            input_model=ExplainChangeInput,
            output_model=ExplainChangeOutput,
            handler=explain_change_handler,
        )
    )

    register_fn(
        ToolSpec(
            name="investigate_month_change",
            description=(
                "Investigate period-over-period spend changes via deterministic decomposition."
            ),
            side_effect=SideEffect.READ,
            input_model=ExplainChangeInput,
            output_model=ExplainChangeOutput,
            handler=explain_change_handler,
        )
    )

    register_fn(
        ToolSpec(
            name="dismiss_anomaly",
            description="User tool to dismiss a detected anomaly as expected.",
            side_effect=SideEffect.WRITE_LOGICAL,
            input_model=DismissAnomalyInput,
            output_model=DismissAnomalyOutput,
            handler=dismiss_anomaly_handler,
        )
    )
