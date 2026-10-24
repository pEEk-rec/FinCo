"""
Virtual Buckets Tools and Handlers (PLAN_PHASE3 Section 5.3 & Stage 3.4).

Provides 10+ tool specifications and handlers for:
- Managing virtual buckets (create, update, archive)
- Category mapping to buckets (1-to-1 uniqueness)
- Allocation, release, and paired reassignment
- Reallocation draft proposal, user decision, and application lifecycle
- Summary and status evaluations for planners and users
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

from pydantic import Field, StrictInt

from copilot.audit.events import record_event
from copilot.core.buckets import (
    bucket_balance,
    current_period_str,
    load_buckets_config,
)
from copilot.core.buckets import (
    get_allocation_summary as core_get_allocation_summary,
)
from copilot.core.buckets import (
    rollover_buckets as core_rollover_buckets,
)
from copilot.core.errors import ErrorCode, ToolFailure
from copilot.core.timeutil import IST, from_utc_iso, now_utc, to_utc_iso
from copilot.db.repo import get_category
from copilot.db.repo_phase3 import (
    get_bucket,
    get_reallocation_draft,
    insert_bucket,
    insert_bucket_allocation,
    insert_reallocation_draft,
    map_bucket_category,
    update_reallocation_draft_status,
)
from copilot.db.repo_phase3 import (
    list_buckets as repo_list_buckets,
)
from copilot.db.repo_phase3 import (
    update_bucket as repo_update_bucket,
)
from copilot.models.phase3 import (
    AllocationSummary,
    Bucket,
    BucketAllocation,
    BucketBalance,
    ReallocationDraft,
)
from copilot.tools.contracts import SideEffect, ToolInput, ToolOutput, ToolSpec
from copilot.tools.registry import register

if TYPE_CHECKING:
    from copilot.tools.executor import ExecutionContext


# -------------------------------------------------------------------------------------------------
# 1. create_bucket
# -------------------------------------------------------------------------------------------------
class CreateBucketInput(ToolInput):
    """Input parameters for creating a new virtual bucket."""

    name: str = Field(min_length=1)
    kind: Literal["spending", "goal", "commitment", "flexible"] = "spending"
    period_policy: Literal["reset_monthly", "accumulate"] | None = None
    goal_id: str | None = None
    commitment_id: str | None = None
    sort_order: int = 0


class CreateBucketOutput(ToolOutput):
    """Result of creating a new virtual bucket."""

    bucket: Bucket


def create_bucket_handler(ctx: "ExecutionContext", **kwargs) -> CreateBucketOutput:
    params = CreateBucketInput.model_validate(kwargs)
    config = load_buckets_config()

    if params.kind not in config.allowed_kinds:
        raise ToolFailure(
            ErrorCode.INVALID_INPUT,
            f"Invalid kind '{params.kind}'. Allowed: {config.allowed_kinds}",
            retryable=False,
        )

    policy = params.period_policy or config.default_period_policy.get(params.kind, "reset_monthly")
    if policy not in config.allowed_period_policies:
        raise ToolFailure(
            ErrorCode.INVALID_INPUT,
            f"Invalid period_policy '{policy}'. Allowed: {config.allowed_period_policies}",
            retryable=False,
        )

    bid = f"b_{uuid.uuid4().hex[:12]}"
    ts = to_utc_iso(now_utc(ctx.clock))
    b = Bucket(
        id=bid,
        user_id=ctx.user_id,
        name=params.name.strip(),
        kind=params.kind,
        period_policy=policy,  # type: ignore[arg-type]
        goal_id=params.goal_id,
        commitment_id=params.commitment_id,
        status="active",
        sort_order=params.sort_order,
        created_at=ts,
    )
    insert_bucket(ctx.conn, b)

    record_event(
        ctx.conn,
        user_id=ctx.user_id,
        actor=ctx.actor,
        event_type="bucket_created",
        reason=f"Bucket '{b.name}' ({b.kind}, {b.period_policy}) created by {ctx.actor}",
        run_id=ctx.run_id,
        entity_type="bucket",
        entity_id=b.id,
        after_data=b.model_dump(mode="json"),
        clock=ctx.clock,
    )
    return CreateBucketOutput(bucket=b)


# -------------------------------------------------------------------------------------------------
# 2. update_bucket
# -------------------------------------------------------------------------------------------------
class UpdateBucketInput(ToolInput):
    """Input parameters for modifying an existing virtual bucket."""

    bucket_id: str
    name: str | None = None
    period_policy: Literal["reset_monthly", "accumulate"] | None = None
    sort_order: int | None = None
    status: Literal["active", "archived"] | None = None


class UpdateBucketOutput(ToolOutput):
    """Result of updating a virtual bucket."""

    bucket: Bucket


def update_bucket_handler(ctx: "ExecutionContext", **kwargs) -> UpdateBucketOutput:
    params = UpdateBucketInput.model_validate(kwargs)
    existing = get_bucket(ctx.conn, ctx.user_id, params.bucket_id)
    if existing is None:
        raise ToolFailure(
            ErrorCode.NOT_FOUND,
            f"Bucket '{params.bucket_id}' not found for user.",
            retryable=False,
        )

    updated = repo_update_bucket(
        ctx.conn,
        ctx.user_id,
        params.bucket_id,
        name=params.name.strip() if params.name is not None else None,
        period_policy=params.period_policy,
        status=params.status,
        sort_order=params.sort_order,
    )
    if not updated:
        return UpdateBucketOutput(bucket=existing)

    current = get_bucket(ctx.conn, ctx.user_id, params.bucket_id)
    if current is None:
        raise ToolFailure(ErrorCode.INTERNAL_ERROR, "Failed to retrieve updated bucket.")

    record_event(
        ctx.conn,
        user_id=ctx.user_id,
        actor=ctx.actor,
        event_type="bucket_updated",
        reason=f"Bucket '{current.name}' updated by {ctx.actor}",
        run_id=ctx.run_id,
        entity_type="bucket",
        entity_id=current.id,
        before_data=existing.model_dump(mode="json"),
        after_data=current.model_dump(mode="json"),
        clock=ctx.clock,
    )
    return UpdateBucketOutput(bucket=current)


# -------------------------------------------------------------------------------------------------
# 3. archive_bucket
# -------------------------------------------------------------------------------------------------
class ArchiveBucketInput(ToolInput):
    """Input parameters for archiving an existing virtual bucket."""

    bucket_id: str


class ArchiveBucketOutput(ToolOutput):
    """Result of archiving a virtual bucket."""

    bucket_id: str
    status: Literal["archived"]


def archive_bucket_handler(ctx: "ExecutionContext", **kwargs) -> ArchiveBucketOutput:
    params = ArchiveBucketInput.model_validate(kwargs)
    existing = get_bucket(ctx.conn, ctx.user_id, params.bucket_id)
    if existing is None:
        raise ToolFailure(
            ErrorCode.NOT_FOUND,
            f"Bucket '{params.bucket_id}' not found for user.",
            retryable=False,
        )

    repo_update_bucket(ctx.conn, ctx.user_id, params.bucket_id, status="archived")

    record_event(
        ctx.conn,
        user_id=ctx.user_id,
        actor=ctx.actor,
        event_type="bucket_archived",
        reason=f"Bucket '{existing.name}' archived by {ctx.actor}",
        run_id=ctx.run_id,
        entity_type="bucket",
        entity_id=existing.id,
        metadata={"previous_status": existing.status},
        clock=ctx.clock,
    )
    return ArchiveBucketOutput(bucket_id=params.bucket_id, status="archived")


# -------------------------------------------------------------------------------------------------
# 4. map_category_to_bucket
# -------------------------------------------------------------------------------------------------
class MapCategoryToBucketInput(ToolInput):
    """Input parameters for mapping a category to a virtual bucket."""

    bucket_id: str
    category_id: str


class MapCategoryToBucketOutput(ToolOutput):
    """Result of mapping a category to a virtual bucket."""

    bucket_id: str
    category_id: str
    mapped: bool


def map_category_to_bucket_handler(ctx: "ExecutionContext", **kwargs) -> MapCategoryToBucketOutput:
    params = MapCategoryToBucketInput.model_validate(kwargs)
    bucket = get_bucket(ctx.conn, ctx.user_id, params.bucket_id)
    if bucket is None:
        raise ToolFailure(
            ErrorCode.NOT_FOUND,
            f"Bucket '{params.bucket_id}' not found for user.",
            retryable=False,
        )

    category = get_category(ctx.conn, ctx.user_id, params.category_id)
    if category is None:
        raise ToolFailure(
            ErrorCode.NOT_FOUND,
            f"Category '{params.category_id}' not found for user.",
            retryable=False,
        )

    ts = to_utc_iso(now_utc(ctx.clock))
    map_bucket_category(ctx.conn, ctx.user_id, params.bucket_id, params.category_id, ts)

    record_event(
        ctx.conn,
        user_id=ctx.user_id,
        actor=ctx.actor,
        event_type="bucket_category_mapped",
        reason=(f"Category '{category.name}' mapped to bucket '{bucket.name}' by {ctx.actor}"),
        run_id=ctx.run_id,
        entity_type="bucket_category",
        entity_id=f"{params.bucket_id}:{params.category_id}",
        metadata={"bucket_id": params.bucket_id, "category_id": params.category_id},
        clock=ctx.clock,
    )
    return MapCategoryToBucketOutput(
        bucket_id=params.bucket_id, category_id=params.category_id, mapped=True
    )


# -------------------------------------------------------------------------------------------------
# 5. allocate_to_bucket
# -------------------------------------------------------------------------------------------------
class AllocateToBucketInput(ToolInput):
    """Input parameters for allocating funds to a bucket."""

    bucket_id: str
    amount_paise: StrictInt = Field(gt=0)
    period: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")


class AllocateToBucketOutput(ToolOutput):
    """Result of allocating funds to a bucket."""

    allocation: BucketAllocation
    bucket_balance: BucketBalance


def allocate_to_bucket_handler(ctx: "ExecutionContext", **kwargs) -> AllocateToBucketOutput:
    params = AllocateToBucketInput.model_validate(kwargs)
    bucket = get_bucket(ctx.conn, ctx.user_id, params.bucket_id)
    if bucket is None:
        raise ToolFailure(
            ErrorCode.NOT_FOUND,
            f"Bucket '{params.bucket_id}' not found for user.",
            retryable=False,
        )

    now_dt = ctx.clock if isinstance(ctx.clock, datetime) else now_utc()
    period_str = params.period or current_period_str(now_dt)
    ts = to_utc_iso(now_dt)

    alloc_id = f"ba_{uuid.uuid4().hex[:12]}"
    alloc = BucketAllocation(
        id=alloc_id,
        user_id=ctx.user_id,
        bucket_id=bucket.id,
        amount_paise=params.amount_paise,
        kind="allocate",
        period=period_str,
        pair_id=None,
        source="user",
        draft_id=None,
        created_at=ts,
    )
    insert_bucket_allocation(ctx.conn, alloc)

    record_event(
        ctx.conn,
        user_id=ctx.user_id,
        actor=ctx.actor,
        event_type="bucket_allocated",
        reason=(
            f"Allocated {params.amount_paise} paise to bucket '{bucket.name}' "
            f"for period {period_str} by {ctx.actor}"
        ),
        run_id=ctx.run_id,
        entity_type="bucket_allocation",
        entity_id=alloc_id,
        metadata={
            "bucket_id": bucket.id,
            "amount_paise": params.amount_paise,
            "period": period_str,
        },
        clock=ctx.clock,
    )

    bal = bucket_balance(ctx.conn, ctx.user_id, bucket, period_str)
    return AllocateToBucketOutput(allocation=alloc, bucket_balance=bal)


# -------------------------------------------------------------------------------------------------
# 6. release_from_bucket
# -------------------------------------------------------------------------------------------------
class ReleaseFromBucketInput(ToolInput):
    """Input parameters for releasing funds from a bucket."""

    bucket_id: str
    amount_paise: StrictInt = Field(gt=0)
    period: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")


class ReleaseFromBucketOutput(ToolOutput):
    """Result of releasing funds from a bucket."""

    allocation: BucketAllocation
    bucket_balance: BucketBalance


def release_from_bucket_handler(ctx: "ExecutionContext", **kwargs) -> ReleaseFromBucketOutput:
    params = ReleaseFromBucketInput.model_validate(kwargs)
    bucket = get_bucket(ctx.conn, ctx.user_id, params.bucket_id)
    if bucket is None:
        raise ToolFailure(
            ErrorCode.NOT_FOUND,
            f"Bucket '{params.bucket_id}' not found for user.",
            retryable=False,
        )

    now_dt = ctx.clock if isinstance(ctx.clock, datetime) else now_utc()
    period_str = params.period or current_period_str(now_dt)
    ts = to_utc_iso(now_dt)

    alloc_id = f"ba_{uuid.uuid4().hex[:12]}"
    alloc = BucketAllocation(
        id=alloc_id,
        user_id=ctx.user_id,
        bucket_id=bucket.id,
        amount_paise=-params.amount_paise,
        kind="release",
        period=period_str,
        pair_id=None,
        source="user",
        draft_id=None,
        created_at=ts,
    )
    insert_bucket_allocation(ctx.conn, alloc)

    record_event(
        ctx.conn,
        user_id=ctx.user_id,
        actor=ctx.actor,
        event_type="bucket_released",
        reason=(
            f"Released {params.amount_paise} paise from bucket '{bucket.name}' "
            f"for period {period_str} by {ctx.actor}"
        ),
        run_id=ctx.run_id,
        entity_type="bucket_allocation",
        entity_id=alloc_id,
        metadata={
            "bucket_id": bucket.id,
            "amount_paise": params.amount_paise,
            "period": period_str,
        },
        clock=ctx.clock,
    )

    bal = bucket_balance(ctx.conn, ctx.user_id, bucket, period_str)
    return ReleaseFromBucketOutput(allocation=alloc, bucket_balance=bal)


# -------------------------------------------------------------------------------------------------
# 7. reassign_between_buckets
# -------------------------------------------------------------------------------------------------
class ReassignBetweenBucketsInput(ToolInput):
    """Input parameters for reassigning funds between two buckets."""

    from_bucket_id: str
    to_bucket_id: str
    amount_paise: StrictInt = Field(gt=0)
    period: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")


class ReassignBetweenBucketsOutput(ToolOutput):
    """Result of reassigning funds between two buckets."""

    pair_id: str
    amount_paise: int
    from_balance: BucketBalance
    to_balance: BucketBalance


def reassign_between_buckets_handler(
    ctx: "ExecutionContext", **kwargs
) -> ReassignBetweenBucketsOutput:
    params = ReassignBetweenBucketsInput.model_validate(kwargs)
    if params.from_bucket_id == params.to_bucket_id:
        raise ToolFailure(
            ErrorCode.INVALID_INPUT,
            "from_bucket_id and to_bucket_id must be different buckets.",
            retryable=False,
        )

    b_from = get_bucket(ctx.conn, ctx.user_id, params.from_bucket_id)
    if b_from is None:
        raise ToolFailure(
            ErrorCode.NOT_FOUND,
            f"Source bucket '{params.from_bucket_id}' not found.",
            retryable=False,
        )

    b_to = get_bucket(ctx.conn, ctx.user_id, params.to_bucket_id)
    if b_to is None:
        raise ToolFailure(
            ErrorCode.NOT_FOUND,
            f"Destination bucket '{params.to_bucket_id}' not found.",
            retryable=False,
        )

    now_dt = ctx.clock if isinstance(ctx.clock, datetime) else now_utc()
    period_str = params.period or current_period_str(now_dt)
    ts = to_utc_iso(now_dt)

    pair_id = f"reassign_{uuid.uuid4().hex[:12]}"
    out_row = BucketAllocation(
        id=f"ba_{uuid.uuid4().hex[:12]}",
        user_id=ctx.user_id,
        bucket_id=b_from.id,
        amount_paise=-params.amount_paise,
        kind="reassign_out",
        period=period_str,
        pair_id=pair_id,
        source="user",
        draft_id=None,
        created_at=ts,
    )
    in_row = BucketAllocation(
        id=f"ba_{uuid.uuid4().hex[:12]}",
        user_id=ctx.user_id,
        bucket_id=b_to.id,
        amount_paise=params.amount_paise,
        kind="reassign_in",
        period=period_str,
        pair_id=pair_id,
        source="user",
        draft_id=None,
        created_at=ts,
    )
    insert_bucket_allocation(ctx.conn, out_row)
    insert_bucket_allocation(ctx.conn, in_row)

    record_event(
        ctx.conn,
        user_id=ctx.user_id,
        actor=ctx.actor,
        event_type="bucket_reassigned",
        reason=(
            f"Reassigned {params.amount_paise} paise from '{b_from.name}' "
            f"to '{b_to.name}' by {ctx.actor}"
        ),
        run_id=ctx.run_id,
        entity_type="bucket_allocation_pair",
        entity_id=pair_id,
        metadata={
            "from_bucket_id": b_from.id,
            "to_bucket_id": b_to.id,
            "amount_paise": params.amount_paise,
            "period": period_str,
        },
        clock=ctx.clock,
    )

    bal_from = bucket_balance(ctx.conn, ctx.user_id, b_from, period_str)
    bal_to = bucket_balance(ctx.conn, ctx.user_id, b_to, period_str)
    return ReassignBetweenBucketsOutput(
        pair_id=pair_id,
        amount_paise=params.amount_paise,
        from_balance=bal_from,
        to_balance=bal_to,
    )


# -------------------------------------------------------------------------------------------------
# 8. draft_reallocation / create_reallocation_draft
# -------------------------------------------------------------------------------------------------
class DraftReallocationInput(ToolInput):
    """Input parameters for drafting a bucket reallocation."""

    from_bucket_id: str
    to_bucket_id: str
    amount_paise: StrictInt = Field(gt=0)
    reason_json: dict[str, Any] = Field(default_factory=dict)
    simulation_id: str | None = None


class DraftReallocationOutput(ToolOutput):
    """Result of creating a bucket reallocation draft."""

    draft: ReallocationDraft


def draft_reallocation_handler(ctx: "ExecutionContext", **kwargs) -> DraftReallocationOutput:
    params = DraftReallocationInput.model_validate(kwargs)
    if params.from_bucket_id == params.to_bucket_id:
        raise ToolFailure(
            ErrorCode.INVALID_INPUT,
            "from_bucket_id and to_bucket_id must be different buckets.",
            retryable=False,
        )

    b_from = get_bucket(ctx.conn, ctx.user_id, params.from_bucket_id)
    if b_from is None:
        raise ToolFailure(
            ErrorCode.NOT_FOUND,
            f"Source bucket '{params.from_bucket_id}' not found.",
            retryable=False,
        )

    b_to = get_bucket(ctx.conn, ctx.user_id, params.to_bucket_id)
    if b_to is None:
        raise ToolFailure(
            ErrorCode.NOT_FOUND,
            f"Destination bucket '{params.to_bucket_id}' not found.",
            retryable=False,
        )

    ts = to_utc_iso(now_utc(ctx.clock))
    draft_id = f"rd_{uuid.uuid4().hex[:12]}"
    draft = ReallocationDraft(
        id=draft_id,
        user_id=ctx.user_id,
        from_bucket_id=params.from_bucket_id,
        to_bucket_id=params.to_bucket_id,
        amount_paise=params.amount_paise,
        reason_json=params.reason_json,
        simulation_id=params.simulation_id,
        status="draft",
        created_at=ts,
    )
    insert_reallocation_draft(ctx.conn, draft)

    record_event(
        ctx.conn,
        user_id=ctx.user_id,
        actor=ctx.actor,
        event_type="reallocation_draft_created",
        reason=(
            f"Drafted reallocation of {params.amount_paise} paise from '{b_from.name}' "
            f"to '{b_to.name}' by {ctx.actor}"
        ),
        run_id=ctx.run_id,
        entity_type="reallocation_draft",
        entity_id=draft_id,
        after_data=draft.model_dump(mode="json"),
        clock=ctx.clock,
    )
    return DraftReallocationOutput(draft=draft)


# -------------------------------------------------------------------------------------------------
# 9. decide_reallocation / decide_reallocation_draft
# -------------------------------------------------------------------------------------------------
class DecideReallocationInput(ToolInput):
    """Input parameters for approving or rejecting a reallocation draft."""

    draft_id: str
    decision: Literal["approve", "reject"]


class DecideReallocationOutput(ToolOutput):
    """Result of deciding a reallocation draft."""

    draft: ReallocationDraft


def decide_reallocation_handler(ctx: "ExecutionContext", **kwargs) -> DecideReallocationOutput:
    params = DecideReallocationInput.model_validate(kwargs)
    draft = get_reallocation_draft(ctx.conn, ctx.user_id, params.draft_id)
    if draft is None:
        raise ToolFailure(
            ErrorCode.NOT_FOUND,
            f"Reallocation draft '{params.draft_id}' not found.",
            retryable=False,
        )

    if draft.status != "draft":
        raise ToolFailure(
            ErrorCode.INVALID_INPUT,
            f"Draft '{params.draft_id}' is already in status '{draft.status}'.",
            retryable=False,
        )

    config = load_buckets_config()
    now_dt = ctx.clock if isinstance(ctx.clock, datetime) else now_utc()
    created_dt = from_utc_iso(draft.created_at)
    ts = to_utc_iso(now_dt)

    if (now_dt - created_dt).total_seconds() > (config.draft_ttl_days * 86400):
        update_reallocation_draft_status(ctx.conn, ctx.user_id, draft.id, "expired")
        raise ToolFailure(
            ErrorCode.INVALID_INPUT,
            f"Reallocation draft '{params.draft_id}' has expired (TTL {config.draft_ttl_days}d).",
            retryable=False,
        )

    new_status = "approved" if params.decision == "approve" else "rejected"
    update_reallocation_draft_status(ctx.conn, ctx.user_id, draft.id, new_status, decided_at=ts)
    updated = draft.model_copy(update={"status": new_status, "decided_at": ts})

    record_event(
        ctx.conn,
        user_id=ctx.user_id,
        actor=ctx.actor,
        event_type="reallocation_draft_decided",
        reason=f"Draft '{draft.id}' was {new_status} by {ctx.actor}",
        run_id=ctx.run_id,
        entity_type="reallocation_draft",
        entity_id=draft.id,
        before_data=draft.model_dump(mode="json"),
        after_data=updated.model_dump(mode="json"),
        clock=ctx.clock,
    )
    return DecideReallocationOutput(draft=updated)


# -------------------------------------------------------------------------------------------------
# 10. apply_reallocation / apply_reallocation_draft
# -------------------------------------------------------------------------------------------------
class ApplyReallocationInput(ToolInput):
    """Input parameters for applying an approved reallocation draft."""

    draft_id: str
    period: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")


class ApplyReallocationOutput(ToolOutput):
    """Result of applying a reallocation draft."""

    draft: ReallocationDraft
    pair_id: str


def apply_reallocation_handler(ctx: "ExecutionContext", **kwargs) -> ApplyReallocationOutput:
    params = ApplyReallocationInput.model_validate(kwargs)
    draft = get_reallocation_draft(ctx.conn, ctx.user_id, params.draft_id)
    if draft is None:
        raise ToolFailure(
            ErrorCode.NOT_FOUND,
            f"Reallocation draft '{params.draft_id}' not found.",
            retryable=False,
        )

    if draft.status != "approved":
        raise ToolFailure(
            ErrorCode.INVALID_INPUT,
            f"Draft status is '{draft.status}', but must be 'approved' to apply.",
            retryable=False,
        )

    config = load_buckets_config()
    now_dt = ctx.clock if isinstance(ctx.clock, datetime) else now_utc()
    created_dt = from_utc_iso(draft.created_at)
    ts = to_utc_iso(now_dt)

    if (now_dt - created_dt).total_seconds() > (config.draft_ttl_days * 86400):
        update_reallocation_draft_status(ctx.conn, ctx.user_id, draft.id, "expired")
        raise ToolFailure(
            ErrorCode.INVALID_INPUT,
            f"Reallocation draft '{params.draft_id}' has expired.",
            retryable=False,
        )

    period_str = params.period or current_period_str(now_dt)
    pair_id = f"reassign_{uuid.uuid4().hex[:12]}"
    out_row = BucketAllocation(
        id=f"ba_{uuid.uuid4().hex[:12]}",
        user_id=ctx.user_id,
        bucket_id=draft.from_bucket_id,
        amount_paise=-draft.amount_paise,
        kind="reassign_out",
        period=period_str,
        pair_id=pair_id,
        source="approved_draft",
        draft_id=draft.id,
        created_at=ts,
    )
    in_row = BucketAllocation(
        id=f"ba_{uuid.uuid4().hex[:12]}",
        user_id=ctx.user_id,
        bucket_id=draft.to_bucket_id,
        amount_paise=draft.amount_paise,
        kind="reassign_in",
        period=period_str,
        pair_id=pair_id,
        source="approved_draft",
        draft_id=draft.id,
        created_at=ts,
    )
    insert_bucket_allocation(ctx.conn, out_row)
    insert_bucket_allocation(ctx.conn, in_row)

    update_reallocation_draft_status(ctx.conn, ctx.user_id, draft.id, "applied", applied_at=ts)
    updated = draft.model_copy(update={"status": "applied", "applied_at": ts})

    record_event(
        ctx.conn,
        user_id=ctx.user_id,
        actor=ctx.actor,
        event_type="reallocation_applied",
        reason=(
            f"Applied approved reallocation of {draft.amount_paise} paise from "
            f"'{draft.from_bucket_id}' to '{draft.to_bucket_id}' by {ctx.actor}"
        ),
        run_id=ctx.run_id,
        entity_type="reallocation_draft",
        entity_id=draft.id,
        before_data=draft.model_dump(mode="json"),
        after_data=updated.model_dump(mode="json"),
        clock=ctx.clock,
    )

    # Record useful feedback for acted-on alert (PLAN_PHASE3 Section 5.16)
    try:
        from copilot.core.learning import record_feedback

        b_target = get_bucket(ctx.conn, ctx.user_id, draft.to_bucket_id)
        target_name = b_target.name if b_target and b_target.name else draft.to_bucket_id
        record_feedback(
            ctx.conn,
            user_id=ctx.user_id,
            subject_kind="alert_kind",
            subject_key=f"budget_risk:{target_name}",
            signal="useful",
            clock=ctx.clock,
            run_id=ctx.run_id,
        )
    except Exception:
        pass

    return ApplyReallocationOutput(draft=updated, pair_id=pair_id)


# -------------------------------------------------------------------------------------------------
# 11. list_buckets (READ)
# -------------------------------------------------------------------------------------------------
class ListBucketsInput(ToolInput):
    """Input parameters for listing virtual buckets."""

    status: Literal["active", "archived"] | None = "active"


class ListBucketsOutput(ToolOutput):
    """List of virtual buckets."""

    buckets: list[Bucket]


def list_buckets_handler(ctx: "ExecutionContext", **kwargs) -> ListBucketsOutput:
    params = ListBucketsInput.model_validate(kwargs)
    buckets = repo_list_buckets(ctx.conn, ctx.user_id, status=params.status)
    return ListBucketsOutput(buckets=buckets)


# -------------------------------------------------------------------------------------------------
# 12. get_bucket_status (READ)
# -------------------------------------------------------------------------------------------------
class GetBucketStatusInput(ToolInput):
    """Input parameters for getting bucket balance and status."""

    bucket_id: str
    period: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")


class GetBucketStatusOutput(ToolOutput):
    """Derived balance and status for a virtual bucket."""

    balance: BucketBalance


def get_bucket_status_handler(ctx: "ExecutionContext", **kwargs) -> GetBucketStatusOutput:
    params = GetBucketStatusInput.model_validate(kwargs)
    bucket = get_bucket(ctx.conn, ctx.user_id, params.bucket_id)
    if bucket is None:
        raise ToolFailure(
            ErrorCode.NOT_FOUND,
            f"Bucket '{params.bucket_id}' not found for user.",
            retryable=False,
        )

    period_str = params.period or current_period_str()
    bal = bucket_balance(ctx.conn, ctx.user_id, bucket, period_str)
    return GetBucketStatusOutput(balance=bal)


# -------------------------------------------------------------------------------------------------
# 13. get_allocation_summary (READ)
# -------------------------------------------------------------------------------------------------
class GetAllocationSummaryInput(ToolInput):
    """Input parameters for getting allocation summary."""

    period: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")


class GetAllocationSummaryOutput(ToolOutput):
    """Summary of bucket balances and unallocated liquid reserves."""

    summary: AllocationSummary


def get_allocation_summary_handler(ctx: "ExecutionContext", **kwargs) -> GetAllocationSummaryOutput:
    params = GetAllocationSummaryInput.model_validate(kwargs)
    period_str = params.period or current_period_str()
    summary = core_get_allocation_summary(ctx.conn, ctx.user_id, period_str)
    return GetAllocationSummaryOutput(summary=summary)


class RolloverBucketsInput(ToolInput):
    """Input for monthly bucket rollover."""

    period: str | None = None
    closing_period: str | None = None


class RolloverBucketsOutput(ToolOutput):
    """Result of monthly bucket rollover."""

    closing_period: str
    released_allocation_ids: list[str]
    count: int


def rollover_buckets_handler(ctx: "ExecutionContext", **kwargs) -> RolloverBucketsOutput:
    params = RolloverBucketsInput.model_validate(kwargs)
    closing_period = params.closing_period or params.period
    if not closing_period:
        now_dt = ctx.clock if isinstance(ctx.clock, datetime) else now_utc()
        ist_now = now_dt.astimezone(IST)
        prev_y, prev_m = (
            (ist_now.year - 1, 12) if ist_now.month == 1 else (ist_now.year, ist_now.month - 1)
        )
        closing_period = f"{prev_y:04d}-{prev_m:02d}"

    released_ids = core_rollover_buckets(ctx.conn, ctx.user_id, closing_period)
    return RolloverBucketsOutput(
        closing_period=closing_period,
        released_allocation_ids=released_ids,
        count=len(released_ids),
    )


# -------------------------------------------------------------------------------------------------
# Tool Specifications & Registry
# -------------------------------------------------------------------------------------------------
BUCKET_TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="create_bucket",
        description="Create a new virtual spending, goal, commitment, or flexible bucket.",
        input_model=CreateBucketInput,
        output_model=CreateBucketOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=create_bucket_handler,
    ),
    ToolSpec(
        name="update_bucket",
        description="Update properties of an existing virtual bucket.",
        input_model=UpdateBucketInput,
        output_model=UpdateBucketOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=update_bucket_handler,
    ),
    ToolSpec(
        name="archive_bucket",
        description="Archive an existing virtual bucket so it is excluded from active allocations.",
        input_model=ArchiveBucketInput,
        output_model=ArchiveBucketOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=archive_bucket_handler,
    ),
    ToolSpec(
        name="map_category_to_bucket",
        description="Map a spending category to a virtual bucket with one-to-one uniqueness.",
        input_model=MapCategoryToBucketInput,
        output_model=MapCategoryToBucketOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=map_category_to_bucket_handler,
    ),
    ToolSpec(
        name="allocate_to_bucket",
        description="Allocate funds to a virtual bucket for a specific period.",
        input_model=AllocateToBucketInput,
        output_model=AllocateToBucketOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=allocate_to_bucket_handler,
    ),
    ToolSpec(
        name="release_from_bucket",
        description="Release allocated funds from a virtual bucket back to unallocated.",
        input_model=ReleaseFromBucketInput,
        output_model=ReleaseFromBucketOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=release_from_bucket_handler,
    ),
    ToolSpec(
        name="reassign_between_buckets",
        description="Reassign allocated funds from one virtual bucket to another.",
        input_model=ReassignBetweenBucketsInput,
        output_model=ReassignBetweenBucketsOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=reassign_between_buckets_handler,
    ),
    ToolSpec(
        name="draft_reallocation",
        description="Create a reallocation draft between buckets for user review.",
        input_model=DraftReallocationInput,
        output_model=DraftReallocationOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=draft_reallocation_handler,
    ),
    ToolSpec(
        name="create_reallocation_draft",
        description="Create a reallocation draft between buckets for user review.",
        input_model=DraftReallocationInput,
        output_model=DraftReallocationOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=draft_reallocation_handler,
    ),
    ToolSpec(
        name="decide_reallocation",
        description="Approve or reject a pending bucket reallocation draft.",
        input_model=DecideReallocationInput,
        output_model=DecideReallocationOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=decide_reallocation_handler,
    ),
    ToolSpec(
        name="decide_reallocation_draft",
        description="Approve or reject a pending bucket reallocation draft.",
        input_model=DecideReallocationInput,
        output_model=DecideReallocationOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=decide_reallocation_handler,
    ),
    ToolSpec(
        name="apply_reallocation",
        description="Apply an approved bucket reallocation draft.",
        input_model=ApplyReallocationInput,
        output_model=ApplyReallocationOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=apply_reallocation_handler,
    ),
    ToolSpec(
        name="apply_reallocation_draft",
        description="Apply an approved bucket reallocation draft.",
        input_model=ApplyReallocationInput,
        output_model=ApplyReallocationOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=apply_reallocation_handler,
    ),
    ToolSpec(
        name="list_buckets",
        description="List virtual buckets for the current user.",
        input_model=ListBucketsInput,
        output_model=ListBucketsOutput,
        side_effect=SideEffect.READ,
        handler=list_buckets_handler,
    ),
    ToolSpec(
        name="get_bucket_status",
        description="Evaluate derived balance, spent amount, and status for a virtual bucket.",
        input_model=GetBucketStatusInput,
        output_model=GetBucketStatusOutput,
        side_effect=SideEffect.READ,
        handler=get_bucket_status_handler,
    ),
    ToolSpec(
        name="get_allocation_summary",
        description="Summarize reserved bucket totals and available unallocated funds.",
        input_model=GetAllocationSummaryInput,
        output_model=GetAllocationSummaryOutput,
        side_effect=SideEffect.READ,
        handler=get_allocation_summary_handler,
    ),
    ToolSpec(
        name="rollover_buckets",
        description="Rollover unspent balances for reset_monthly buckets to unallocated.",
        input_model=RolloverBucketsInput,
        output_model=RolloverBucketsOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=rollover_buckets_handler,
    ),
)


def register_bucket_tools(register_fn=register) -> None:
    """Register all virtual bucket tools into the tool registry."""
    for spec in BUCKET_TOOLS:
        register_fn(spec)
