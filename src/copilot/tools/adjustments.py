"""
Tool specifications and handlers for adaptive challenge adjustments.
(PLAN_PHASE4 Section 5.5, Stage 4.5)

Governance rules:
- accept_adjustment, reject_adjustment:
    SideEffect.WRITE_LOGICAL. Allowed for user, denied for agent (human-in-the-loop).
    Never planner-selectable.
- list_adjustments:
    SideEffect.READ. Allowed for all actors, planner-selectable.
- run_adaptive_detectors, expire_stale_proposals:
    SideEffect.WRITE_LOGICAL. Allowed for agent and user (runtime maintenance jobs).
    Never planner-selectable.
"""

from typing import TYPE_CHECKING, Literal

from pydantic import Field

from copilot.core.adaptive import (
    accept_adjustment as core_accept_adjustment,
)
from copilot.core.adaptive import (
    expire_stale_proposals as core_expire_stale_proposals,
)
from copilot.core.adaptive import (
    reject_adjustment as core_reject_adjustment,
)
from copilot.core.adaptive import (
    run_adaptive_detectors as core_run_adaptive_detectors,
)
from copilot.db.repo_phase4 import (
    list_adjustment_proposals as repo_list_adjustment_proposals,
)
from copilot.models.phase4 import AdjustmentProposal
from copilot.tools.contracts import SideEffect, ToolInput, ToolOutput, ToolSpec
from copilot.tools.registry import register

if TYPE_CHECKING:
    from copilot.tools.executor import ExecutionContext


# ---------------------------------------------------------------------------------------------
# 1. list_adjustments
# ---------------------------------------------------------------------------------------------
class ListAdjustmentsInput(ToolInput):
    """Input for listing adjustment proposals."""

    experiment_id: str | None = None
    status: Literal["proposed", "accepted", "rejected", "expired", "auto_applied_pause"] | None = (
        None
    )


class ListAdjustmentsOutput(ToolOutput):
    proposals: list[AdjustmentProposal]


def list_adjustments_handler(ctx: "ExecutionContext", **kwargs) -> ListAdjustmentsOutput:
    params = ListAdjustmentsInput.model_validate(kwargs)
    proposals = repo_list_adjustment_proposals(
        ctx.conn,
        ctx.user_id,
        experiment_id=params.experiment_id,
        status=params.status,
    )
    return ListAdjustmentsOutput(proposals=proposals)


# ---------------------------------------------------------------------------------------------
# 2. accept_adjustment
# ---------------------------------------------------------------------------------------------
class AcceptAdjustmentInput(ToolInput):
    """Input for accepting an adjustment proposal."""

    proposal_id: str


class AcceptAdjustmentOutput(ToolOutput):
    proposal: AdjustmentProposal


def accept_adjustment_handler(ctx: "ExecutionContext", **kwargs) -> AcceptAdjustmentOutput:
    params = AcceptAdjustmentInput.model_validate(kwargs)
    prop = core_accept_adjustment(
        ctx.conn,
        ctx.user_id,
        params.proposal_id,
        clock=ctx.clock,
    )
    return AcceptAdjustmentOutput(proposal=prop)


# ---------------------------------------------------------------------------------------------
# 3. reject_adjustment
# ---------------------------------------------------------------------------------------------
class RejectAdjustmentInput(ToolInput):
    """Input for rejecting an adjustment proposal."""

    proposal_id: str
    reason: str | None = None


class RejectAdjustmentOutput(ToolOutput):
    proposal: AdjustmentProposal


def reject_adjustment_handler(ctx: "ExecutionContext", **kwargs) -> RejectAdjustmentOutput:
    params = RejectAdjustmentInput.model_validate(kwargs)
    prop = core_reject_adjustment(
        ctx.conn,
        ctx.user_id,
        params.proposal_id,
        clock=ctx.clock,
    )
    return RejectAdjustmentOutput(proposal=prop)


# ---------------------------------------------------------------------------------------------
# 4. run_adaptive_detectors
# ---------------------------------------------------------------------------------------------
class RunAdaptiveDetectorsInput(ToolInput):
    """Input for running adaptive challenge detectors on active experiments."""

    experiment_id: str | None = None


class RunAdaptiveDetectorsOutput(ToolOutput):
    proposals: list[AdjustmentProposal]


def run_adaptive_detectors_handler(ctx: "ExecutionContext", **kwargs) -> RunAdaptiveDetectorsOutput:
    params = RunAdaptiveDetectorsInput.model_validate(kwargs)
    proposals = core_run_adaptive_detectors(
        ctx.conn,
        ctx.user_id,
        experiment_id=params.experiment_id,
        clock=ctx.clock,
    )
    return RunAdaptiveDetectorsOutput(proposals=proposals)


# ---------------------------------------------------------------------------------------------
# 5. expire_stale_proposals
# ---------------------------------------------------------------------------------------------
class ExpireStaleProposalsInput(ToolInput):
    """Input for expiring stale adjustment proposals."""

    expiry_days: int = Field(default=14, ge=1, le=90)


class ExpireStaleProposalsOutput(ToolOutput):
    expired_ids: list[str]


def expire_stale_proposals_handler(ctx: "ExecutionContext", **kwargs) -> ExpireStaleProposalsOutput:
    params = ExpireStaleProposalsInput.model_validate(kwargs)
    expired_ids = core_expire_stale_proposals(
        ctx.conn,
        ctx.user_id,
        expiry_days=params.expiry_days,
        clock=ctx.clock,
    )
    return ExpireStaleProposalsOutput(expired_ids=expired_ids)


# ---------------------------------------------------------------------------------------------
# Tool Specifications
# ---------------------------------------------------------------------------------------------
LIST_ADJUSTMENTS_SPEC = ToolSpec(
    name="list_adjustments",
    description="List adaptive adjustment proposals for active or past experiments.",
    input_model=ListAdjustmentsInput,
    output_model=ListAdjustmentsOutput,
    side_effect=SideEffect.READ,
    handler=list_adjustments_handler,
)

ACCEPT_ADJUSTMENT_SPEC = ToolSpec(
    name="accept_adjustment",
    description="User accepts an adaptive proposal (pause, resume, ease target, or extend).",
    input_model=AcceptAdjustmentInput,
    output_model=AcceptAdjustmentOutput,
    side_effect=SideEffect.WRITE_LOGICAL,
    handler=accept_adjustment_handler,
)

REJECT_ADJUSTMENT_SPEC = ToolSpec(
    name="reject_adjustment",
    description="User rejects an adaptive adjustment proposal.",
    input_model=RejectAdjustmentInput,
    output_model=RejectAdjustmentOutput,
    side_effect=SideEffect.WRITE_LOGICAL,
    handler=reject_adjustment_handler,
)

RUN_ADAPTIVE_DETECTORS_SPEC = ToolSpec(
    name="run_adaptive_detectors",
    description="Runtime maintenance job: run adaptive detectors over active experiments.",
    input_model=RunAdaptiveDetectorsInput,
    output_model=RunAdaptiveDetectorsOutput,
    side_effect=SideEffect.WRITE_LOGICAL,
    handler=run_adaptive_detectors_handler,
)

EXPIRE_STALE_PROPOSALS_SPEC = ToolSpec(
    name="expire_stale_proposals",
    description="Runtime maintenance job: expire stale adjustment proposals.",
    input_model=ExpireStaleProposalsInput,
    output_model=ExpireStaleProposalsOutput,
    side_effect=SideEffect.WRITE_LOGICAL,
    handler=expire_stale_proposals_handler,
)


def register_adjustment_tools() -> None:
    """Register all adjustment tools with the global registry."""
    register(LIST_ADJUSTMENTS_SPEC)
    register(ACCEPT_ADJUSTMENT_SPEC)
    register(REJECT_ADJUSTMENT_SPEC)
    register(RUN_ADAPTIVE_DETECTORS_SPEC)
    register(EXPIRE_STALE_PROPOSALS_SPEC)
