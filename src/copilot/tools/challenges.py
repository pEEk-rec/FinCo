"""
Tool specifications and handlers for challenge offers and suggestion jobs.
(PLAN_PHASE4 Section 5.4, Section 5.11 & Stage 4.10)

Governance rules:
- list_offers, get_offer_details:
    SideEffect.READ. Allowed for all actors, planner-selectable.
- accept_offer, dismiss_offer:
    SideEffect.WRITE_LOGICAL. Allowed for user, denied for agent (human opt-in only).
    Never planner-selectable.
- suggest_challenges:
    SideEffect.READ / COMPUTE. Allowed for agent, never planner-selectable.
- expire_offers, weekly_offers:
    SideEffect.WRITE_LOGICAL. Allowed for agent and user (runtime maintenance jobs).
    Never planner-selectable.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Literal

from pydantic import Field

from copilot.audit.events import record_event
from copilot.config.phase4 import load_challenge_templates
from copilot.core.challenges import generate_challenge_offers
from copilot.core.experiments import (
    design_experiment,
)
from copilot.core.experiments import (
    start_experiment as core_start_experiment,
)
from copilot.core.learning_loop import update_template_posterior
from copilot.core.timeutil import IST, from_utc_iso, now_utc, to_utc_iso
from copilot.db.repo_phase4 import (
    get_offer as repo_get_offer,
)
from copilot.db.repo_phase4 import (
    list_offers as repo_list_offers,
)
from copilot.db.repo_phase4 import (
    update_offer as repo_update_offer,
)
from copilot.models.phase4 import Offer
from copilot.tools.contracts import SideEffect, ToolInput, ToolOutput, ToolSpec
from copilot.tools.registry import register

if TYPE_CHECKING:
    from copilot.tools.executor import ExecutionContext


# -------------------------------------------------------------------------------------------------
# 1. list_offers
# -------------------------------------------------------------------------------------------------
class ListOffersInput(ToolInput):
    """Input for listing challenge offers."""

    status: Literal["shown", "accepted", "dismissed", "expired"] | None = None


class ListOffersOutput(ToolOutput):
    offers: list[Offer]


def list_offers_handler(ctx: ExecutionContext, **kwargs) -> ListOffersOutput:
    params = ListOffersInput.model_validate(kwargs)
    offers = repo_list_offers(ctx.conn, ctx.user_id, status=params.status)
    return ListOffersOutput(offers=offers)


# -------------------------------------------------------------------------------------------------
# 2. get_offer_details
# -------------------------------------------------------------------------------------------------
class GetOfferDetailsInput(ToolInput):
    """Input for retrieving single challenge offer details."""

    offer_id: str


class GetOfferDetailsOutput(ToolOutput):
    offer: Offer | None


def get_offer_details_handler(ctx: ExecutionContext, **kwargs) -> GetOfferDetailsOutput:
    params = GetOfferDetailsInput.model_validate(kwargs)
    offer = repo_get_offer(ctx.conn, ctx.user_id, params.offer_id)
    return GetOfferDetailsOutput(offer=offer)


# -------------------------------------------------------------------------------------------------
# 3. accept_offer (User Only)
# -------------------------------------------------------------------------------------------------
class AcceptOfferInput(ToolInput):
    """Input for accepting a challenge offer to start an experiment."""

    offer_id: str


class AcceptOfferOutput(ToolOutput):
    offer_id: str
    experiment_id: str
    status: str


def accept_offer_handler(ctx: ExecutionContext, **kwargs) -> AcceptOfferOutput:
    params = AcceptOfferInput.model_validate(kwargs)
    offer = repo_get_offer(ctx.conn, ctx.user_id, params.offer_id)
    if not offer:
        raise ValueError(f"Offer '{params.offer_id}' not found")
    if offer.status != "shown":
        raise ValueError(
            f"Offer '{params.offer_id}' cannot be accepted; current status is '{offer.status}'"
        )

    clock_dt = ctx.clock if isinstance(ctx.clock, datetime) else now_utc()
    start_date = clock_dt.strftime("%Y-%m-%d")

    params_data = dict(offer.params_json or {})
    metric_code = params_data.get("metric_code")
    if not metric_code:
        templates = load_challenge_templates()
        if offer.template_code in templates:
            metric_code = templates[offer.template_code].metric_code
        else:
            metric_code = "category_spend"

    design_params = {
        "title": params_data.get("title") or f"Challenge: {offer.template_code}",
        "metric_code": metric_code,
        "categories": params_data.get("categories", []),
        "merchants": params_data.get("merchants", []),
        "duration_days": params_data.get("duration_days", 14),
        "difficulty": offer.difficulty,
        "target_value": params_data.get("target_value"),
        "start_date": start_date,
        "origin": "offer",
        "offer_id": offer.id,
        "goal_id": params_data.get("goal_id"),
        "intervention": params_data.get("intervention"),
    }

    # 1. Design experiment in offered state
    exp = design_experiment(
        conn=ctx.conn,
        user_id=ctx.user_id,
        template_code=offer.template_code,
        params=design_params,
        clock=clock_dt,
    )

    # 2. Activate experiment
    active_exp = core_start_experiment(
        conn=ctx.conn,
        user_id=ctx.user_id,
        experiment_id=exp.id,
        clock=clock_dt,
    )

    # 3. Mark offer as accepted
    offer.status = "accepted"
    offer.decided_at = to_utc_iso(clock_dt)
    repo_update_offer(ctx.conn, offer)

    record_event(
        ctx.conn,
        user_id=ctx.user_id,
        actor=ctx.actor,
        event_type="offer_accepted",
        reason=f"Accepted challenge offer for experiment '{active_exp.id}'",
        run_id=ctx.run_id,
        entity_id=offer.id,
        clock=clock_dt,
    )

    return AcceptOfferOutput(
        offer_id=offer.id,
        experiment_id=active_exp.id,
        status="accepted",
    )


# -------------------------------------------------------------------------------------------------
# 4. dismiss_offer (User Only)
# -------------------------------------------------------------------------------------------------
class DismissOfferInput(ToolInput):
    """Input for dismissing a challenge offer."""

    offer_id: str
    reason: str | None = None


class DismissOfferOutput(ToolOutput):
    offer_id: str
    status: str


def dismiss_offer_handler(ctx: ExecutionContext, **kwargs) -> DismissOfferOutput:
    params = DismissOfferInput.model_validate(kwargs)
    offer = repo_get_offer(ctx.conn, ctx.user_id, params.offer_id)
    if not offer:
        raise ValueError(f"Offer '{params.offer_id}' not found")
    if offer.status != "shown":
        raise ValueError(
            f"Offer '{params.offer_id}' cannot be dismissed; status is '{offer.status}'"
        )

    clock_dt = ctx.clock if isinstance(ctx.clock, datetime) else now_utc()
    offer.status = "dismissed"
    repo_update_offer(ctx.conn, offer)

    # Update template posterior with small failure weight (dismissed_offer)
    update_template_posterior(
        conn=ctx.conn,
        user_id=ctx.user_id,
        template_code=offer.template_code,
        event_type="dismissed_offer",
        clock=clock_dt,
    )

    record_event(
        ctx.conn,
        user_id=ctx.user_id,
        actor=ctx.actor,
        event_type="offer_dismissed",
        reason=params.reason or "Dismissed challenge offer without penalty",
        run_id=ctx.run_id,
        entity_id=offer.id,
        clock=clock_dt,
    )

    return DismissOfferOutput(offer_id=offer.id, status="dismissed")


# -------------------------------------------------------------------------------------------------
# 5. suggest_challenges (Agent Only)
# -------------------------------------------------------------------------------------------------
class SuggestChallengesInput(ToolInput):
    """Input for generating challenge suggestions for user."""

    max_offers: int = Field(default=3, ge=1, le=5)
    week_start: str | None = Field(default=None, description="Week start, YYYY-MM-DD.")


class SuggestChallengesOutput(ToolOutput):
    offers: list[Offer]


def suggest_challenges_handler(ctx: ExecutionContext, **kwargs) -> SuggestChallengesOutput:
    params = SuggestChallengesInput.model_validate(kwargs)
    clock_dt = ctx.clock if isinstance(ctx.clock, datetime) else now_utc()

    # Rest weeks and quiet weeks are decided inside the generator, which also records why
    # nothing was offered, so no model call is spent when there is nothing to show.
    offers = generate_challenge_offers(
        conn=ctx.conn,
        user_id=ctx.user_id,
        clock=clock_dt,
        week_start=params.week_start,
        max_offers=params.max_offers,
        llm_client=ctx.llm_client,
        run_id=ctx.run_id,
        actor=ctx.actor,
    )
    return SuggestChallengesOutput(offers=offers)


# -------------------------------------------------------------------------------------------------
# 6. expire_offers (Runtime Job)
# -------------------------------------------------------------------------------------------------
class ExpireOffersInput(ToolInput):
    """Input for expiring stale challenge offers past their valid window."""

    expiry_days: int = Field(default=7, ge=1)


class ExpireOffersOutput(ToolOutput):
    expired_count: int


def expire_offers_handler(ctx: ExecutionContext, **kwargs) -> ExpireOffersOutput:
    params = ExpireOffersInput.model_validate(kwargs)
    clock_dt = ctx.clock if isinstance(ctx.clock, datetime) else now_utc()
    today_d = clock_dt.date()

    shown_offers = repo_list_offers(ctx.conn, ctx.user_id, status="shown")
    expired_count = 0

    for off in shown_offers:
        created_d = from_utc_iso(off.created_at).astimezone(IST).date()
        if (today_d - created_d).days >= params.expiry_days:
            off.status = "expired"
            repo_update_offer(ctx.conn, off)
            expired_count += 1
            record_event(
                ctx.conn,
                user_id=ctx.user_id,
                actor=ctx.actor,
                event_type="offer_expired",
                reason=f"Offer expired after {params.expiry_days} days without response",
                run_id=ctx.run_id,
                entity_id=off.id,
                clock=clock_dt,
            )

    return ExpireOffersOutput(expired_count=expired_count)


# -------------------------------------------------------------------------------------------------
# 7. weekly_offers (Runtime Job)
# -------------------------------------------------------------------------------------------------
class WeeklyOffersInput(ToolInput):
    """Input for weekly offer generation job."""

    max_offers: int = Field(default=3, ge=1, le=5)


class WeeklyOffersOutput(ToolOutput):
    offers_created: int


def weekly_offers_handler(ctx: ExecutionContext, **kwargs) -> WeeklyOffersOutput:
    params = WeeklyOffersInput.model_validate(kwargs)
    clock_dt = ctx.clock if isinstance(ctx.clock, datetime) else now_utc()

    offers = generate_challenge_offers(
        conn=ctx.conn,
        user_id=ctx.user_id,
        clock=clock_dt,
        max_offers=params.max_offers,
        llm_client=ctx.llm_client,
        run_id=ctx.run_id,
        actor=ctx.actor,
    )
    return WeeklyOffersOutput(offers_created=len(offers))


# -------------------------------------------------------------------------------------------------
# Specifications and Registration
# -------------------------------------------------------------------------------------------------
CHALLENGE_TOOLS = (
    ToolSpec(
        name="list_offers",
        description="List weekly challenge offers for user with optional status filter.",
        input_model=ListOffersInput,
        output_model=ListOffersOutput,
        side_effect=SideEffect.READ,
        handler=list_offers_handler,
    ),
    ToolSpec(
        name="get_offer_details",
        description="Get specific challenge offer details by id.",
        input_model=GetOfferDetailsInput,
        output_model=GetOfferDetailsOutput,
        side_effect=SideEffect.READ,
        handler=get_offer_details_handler,
    ),
    ToolSpec(
        name="accept_offer",
        description="User action: accept a shown challenge offer to start an experiment.",
        input_model=AcceptOfferInput,
        output_model=AcceptOfferOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=accept_offer_handler,
    ),
    ToolSpec(
        name="dismiss_offer",
        description="User action: dismiss a challenge offer with optional reason.",
        input_model=DismissOfferInput,
        output_model=DismissOfferOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=dismiss_offer_handler,
    ),
    ToolSpec(
        name="suggest_challenges",
        description="Generate candidate challenge suggestions for user (agent only).",
        input_model=SuggestChallengesInput,
        output_model=SuggestChallengesOutput,
        side_effect=SideEffect.READ,
        handler=suggest_challenges_handler,
    ),
    ToolSpec(
        name="expire_offers",
        description="Runtime maintenance job: expire stale challenge offers.",
        input_model=ExpireOffersInput,
        output_model=ExpireOffersOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=expire_offers_handler,
    ),
    ToolSpec(
        name="weekly_offers",
        description="Runtime maintenance job: generate weekly challenge offers.",
        input_model=WeeklyOffersInput,
        output_model=WeeklyOffersOutput,
        side_effect=SideEffect.WRITE_LOGICAL,
        handler=weekly_offers_handler,
    ),
)


def register_challenge_tools(register_fn=register) -> None:
    """Register all challenge tools into the global registry."""
    for spec in CHALLENGE_TOOLS:
        register_fn(spec)
