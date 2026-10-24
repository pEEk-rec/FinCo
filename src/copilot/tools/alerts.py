"""
Adaptive Alerts Tools (PLAN_PHASE2 Section 5.7 & Stage 2.5).

Implements:
- evaluate_alerts (WRITE_LOGICAL on alerts, allowed for agent)
- decide_alert (actor user tool for acknowledge/dismiss/snooze)
- set_alert_preference (actor user tool for configuring preferences)
- list_alerts (read tool for viewing active/historical alerts)
"""

import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field

from copilot.audit.events import record_event
from copilot.config.phase2 import load_alerts_config
from copilot.core.alerts import (
    build_why_text,
    evaluate_category_alert_signals,
)
from copilot.core.anomalies import detect_anomalies
from copilot.core.errors import ErrorCode, ToolFailure
from copilot.core.memory import get_active_contextual_exception
from copilot.core.timeutil import (
    IST,
    from_utc_iso,
    month_bounds,
    now_utc,
    to_utc_iso,
)
from copilot.db import repo
from copilot.models.agentic import Alert, AlertPreference, AlertSeverity, AlertStatus
from copilot.tools.contracts import (
    SideEffect,
    ToolInput,
    ToolOutput,
    ToolSpec,
)
from copilot.tools.executor import ExecutionContext
from copilot.tools.financial import net_spend_by_category
from copilot.tools.registry import register

# -------------------------------------------------------------------------------------------------
# Models
# -------------------------------------------------------------------------------------------------


class AlertSummary(BaseModel):
    id: str
    kind: str
    subject_key: str
    period: str
    score_bp: int
    severity: AlertSeverity
    why_text: str
    status: AlertStatus
    snoozed_until: str | None = None
    created_at: str


class EvaluateAlertsInput(ToolInput):
    period: str | None = Field(
        default=None, description="Month in YYYY-MM format; defaults to current"
    )
    task_id: str | None = None
    run_id: str | None = None


class EvaluateAlertsOutput(ToolOutput):
    period: str
    alerts: list[AlertSummary]
    created_count: int
    escalated_count: int
    suppressed_count: int


class DecideAlertInput(ToolInput):
    alert_id: str = Field(min_length=1)
    action: Literal["acknowledge", "dismiss", "snooze"]
    reason: str | None = None
    snooze_days: int | None = Field(default=None, ge=1, le=90)


class DecideAlertOutput(ToolOutput):
    alert_id: str
    action: str
    status: AlertStatus
    updated: bool


class SetAlertPreferenceInput(ToolInput):
    category_id: str | None = None
    kind: str | None = None
    min_severity: AlertSeverity = "info"
    muted: bool = False
    max_open_alerts: int | None = Field(default=None, gt=0)


class SetAlertPreferenceOutput(ToolOutput):
    preference_id: str
    updated: bool


class ListAlertsInput(ToolInput):
    status: AlertStatus | None = None
    limit: int = Field(default=50, ge=1, le=200)


class ListAlertsOutput(ToolOutput):
    alerts: list[AlertSummary]


# -------------------------------------------------------------------------------------------------
# Handlers
# -------------------------------------------------------------------------------------------------


def evaluate_alerts_handler(
    ctx: ExecutionContext,
    period: str | None = None,
    task_id: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """
    Evaluate all budget and spend signals for the user in the target period.
    Handles multi-signal scoring, preferences, dedup, in-place escalation, and suppression audit.
    """
    now = ctx.clock if isinstance(ctx.clock, datetime) else now_utc()
    period = period or now.astimezone(IST).strftime("%Y-%m")
    config = load_alerts_config()

    # Load categories, budgets, and spends
    categories = repo.list_categories(ctx.conn, ctx.user_id)
    year, month = int(period[:4]), int(period[5:7])
    start_utc, end_utc = month_bounds(year, month)
    cur_txs = repo.list_transactions(ctx.conn, ctx.user_id, start_utc, end_utc)
    spend_by_cat = net_spend_by_category(cur_txs)
    all_budgets = repo.list_budgets(ctx.conn, ctx.user_id)
    budgets = {b.category_id: b for b in all_budgets if b.period in ("monthly", period)}

    # Trailing history for baselines (up to 3 prior complete months)
    prior_months = []
    y_cur, m_cur = year, month
    for _ in range(3):
        y_cur, m_cur = (y_cur - 1, 12) if m_cur == 1 else (y_cur, m_cur - 1)
        prior_months.append(f"{y_cur:04d}-{m_cur:02d}")

    # Load active goals for impact
    goals = repo.list_goals(ctx.conn, ctx.user_id, status="active")
    goals_affected: list[str] = []
    # If any goal status is currently at_risk or off_track
    for g in goals:
        if getattr(g, "status", None) in ("at_risk", "off_track"):
            goals_affected.append(g.status)

    # Open anomalies in period
    anomalies_list = detect_anomalies(cur_txs)
    anom_by_cat: dict[str, list[dict[str, Any]]] = {}
    for a in anomalies_list:
        cat = a.get("category_id") or "uncategorized"
        anom_by_cat.setdefault(cat, []).append(a)

    # User preferences
    preferences = repo.list_alert_preferences(ctx.conn, ctx.user_id)
    pref_by_cat = {p.category_id: p for p in preferences if p.category_id}
    global_pref = next((p for p in preferences if not p.category_id and not p.kind), None)

    # Days in month and current day in IST
    import calendar

    days_in_month = calendar.monthrange(year, month)[1]
    now_ist = now.astimezone(IST)
    if period == now_ist.strftime("%Y-%m"):
        current_day = now_ist.day
    else:
        current_day = days_in_month

    # Open alerts count for capacity check
    open_alerts = repo.list_alerts(ctx.conn, ctx.user_id, status="open")
    open_alerts_count = len(open_alerts)

    sev_rank = {"info": 1, "notice": 2, "warning": 3, "critical": 4}

    created_count = 0
    escalated_count = 0
    suppressed_count = 0

    # Evaluate each category
    for cat in categories:
        cat_id = cat.id
        spent = spend_by_cat.get(cat_id, 0)
        budget = budgets.get(cat_id)
        limit = budget.limit_paise if budget else 0

        # Historical spend-to-date across prior months
        hist_spends_to_date = []
        for pm in prior_months:
            py, pm_int = int(pm[:4]), int(pm[5:7])
            p_start, p_end = month_bounds(py, pm_int)
            pm_txs = repo.list_transactions(ctx.conn, ctx.user_id, p_start, p_end)
            pm_spend = sum(
                t.amount_paise
                for t in pm_txs
                if t.category_id == cat_id
                and t.direction == "debit"
                and len(t.occurred_at) >= 10
                and int(t.occurred_at[8:10]) <= current_day
            )
            if pm_txs:
                hist_spends_to_date.append(pm_spend)

        # Basic run-rate forecast
        if current_day > 0 and spent > 0:
            daily_rate = spent / current_day
            fc_expected = int(spent + daily_rate * (days_in_month - current_day))
            fc_low = int(fc_expected * 0.85)
            fc_high = int(fc_expected * 1.15)
        else:
            fc_expected = spent
            fc_low = spent
            fc_high = spent

        budget_status = "ok"
        if limit > 0:
            if spent >= limit:
                budget_status = "exceeded"
            elif spent >= int(0.80 * limit):
                budget_status = "warning"
        projected_exceed = limit > 0 and fc_expected > limit

        # Check active contextual exception for this category and period
        # (PLAN_PHASE3 Section 5.8 & 5.9)
        active_exc = get_active_contextual_exception(ctx.conn, ctx.user_id, cat_id, period, now)
        active_exc_dict = None
        if active_exc:
            active_exc_dict = {
                "id": active_exc.id,
                "reason": (active_exc.statement_json or {}).get("reason", "exception"),
                "category": cat_id,
                "period": period,
                "statement": active_exc.statement_json,
            }

        breakdown = evaluate_category_alert_signals(
            category_id=cat_id,
            spent_paise=spent,
            limit_paise=limit,
            budget_status=budget_status,
            fc_low=fc_low,
            fc_expected=fc_expected,
            fc_high=fc_high,
            projected_exceed=projected_exceed,
            historical_spends_to_date=hist_spends_to_date,
            anomalies=anom_by_cat.get(cat_id, []),
            goals_affected=goals_affected,
            history_months=len(hist_spends_to_date),
            txn_count=len(hist_spends_to_date) * 3,  # Approximate transaction count
            config=config,
            current_day=current_day,
            days_in_month=days_in_month,
            active_exception=active_exc_dict,
        )

        # Apply Bounded Feedback Learning (PLAN_PHASE3 Section 5.16)
        from copilot.core.learning import (
            apply_learning_to_alert,
            get_learned_multiplier,
            is_hard_floor_alert,
        )

        subj_key = f"budget_risk:{cat_id}"
        m, p, a_m, b_m = get_learned_multiplier(ctx.conn, ctx.user_id, "alert_kind", subj_key)
        alert_ctx = {
            "budget_status": budget_status,
            "spent_paise": spent,
            "limit_paise": limit,
            "goals_affected": goals_affected,
        }
        is_hard_floor = is_hard_floor_alert(alert_ctx)
        adj_score_bp, adj_sev, learning_note = apply_learning_to_alert(
            breakdown.score_bp, breakdown.severity, m, is_hard_floor, config
        )

        if adj_sev is None:
            # Score below info tier -> no alert
            continue

        why_text = build_why_text(breakdown.components)
        if learning_note:
            why_text += f" ({learning_note.capitalize()}.)"

        breakdown.components["learning"] = {
            "multiplier": m,
            "p": round(p, 4),
            "is_hard_floor": is_hard_floor,
            "note": learning_note,
        }
        dedup_key = f"{ctx.user_id}:{period}:budget_risk:{cat_id}"

        # Preference checks
        cat_pref = pref_by_cat.get(cat_id) or global_pref
        if cat_pref:
            if cat_pref.muted:
                suppressed_count += 1
                record_event(
                    ctx.conn,
                    ctx.user_id,
                    ctx.actor,
                    event_type="alert_suppressed",
                    reason="Alert suppressed because category preference is muted",
                    run_id=ctx.run_id,
                    metadata={
                        "category_id": cat_id,
                        "period": period,
                        "score_bp": adj_score_bp,
                        "reason": "muted",
                    },
                    clock=ctx.clock,
                )
                continue
            if sev_rank[adj_sev] < sev_rank.get(cat_pref.min_severity, 1):
                suppressed_count += 1
                record_event(
                    ctx.conn,
                    ctx.user_id,
                    ctx.actor,
                    event_type="alert_suppressed",
                    reason="Alert suppressed because severity is below user min_severity",
                    run_id=ctx.run_id,
                    metadata={
                        "category_id": cat_id,
                        "period": period,
                        "score_bp": adj_score_bp,
                        "reason": "min_severity",
                    },
                    clock=ctx.clock,
                )
                continue
            max_open = cat_pref.max_open_alerts or config.default_max_open_alerts
            if open_alerts_count >= max_open:
                suppressed_count += 1
                record_event(
                    ctx.conn,
                    ctx.user_id,
                    ctx.actor,
                    event_type="alert_suppressed",
                    reason="Alert suppressed because max open alerts limit reached",
                    run_id=ctx.run_id,
                    metadata={
                        "category_id": cat_id,
                        "period": period,
                        "score_bp": adj_score_bp,
                        "reason": "max_open_alerts",
                    },
                    clock=ctx.clock,
                )
                continue

        # Check existing alert for dedup, cooldown, escalation
        existing = repo.get_alert_by_dedup_key(ctx.conn, ctx.user_id, dedup_key)
        if existing:
            if existing.status == "dismissed":
                decided_at = from_utc_iso(existing.decided_at) if existing.decided_at else now
                if (now - decided_at).days < config.cooldown_days:
                    suppressed_count += 1
                    record_event(
                        ctx.conn,
                        ctx.user_id,
                        ctx.actor,
                        event_type="alert_suppressed",
                        reason="Alert suppressed because dismissed within cooldown window",
                        run_id=ctx.run_id,
                        metadata={
                            "category_id": cat_id,
                            "period": period,
                            "dedup_key": dedup_key,
                            "reason": "cooldown",
                        },
                        clock=ctx.clock,
                    )
                    continue
            elif existing.status == "snoozed":
                snoozed_until = (
                    from_utc_iso(existing.snoozed_until) if existing.snoozed_until else now
                )
                if now < snoozed_until:
                    suppressed_count += 1
                    record_event(
                        ctx.conn,
                        ctx.user_id,
                        ctx.actor,
                        event_type="alert_suppressed",
                        reason="Alert suppressed because snoozed until future timestamp",
                        run_id=ctx.run_id,
                        metadata={
                            "category_id": cat_id,
                            "period": period,
                            "dedup_key": dedup_key,
                            "reason": "snoozed",
                        },
                        clock=ctx.clock,
                    )
                    continue
            elif existing.status == "open":
                # Check for in-place escalation
                if sev_rank[adj_sev] > sev_rank[existing.severity]:
                    repo.update_alert_in_place(
                        ctx.conn,
                        ctx.user_id,
                        existing.id,
                        adj_score_bp,
                        adj_sev,
                        breakdown.components,
                        why_text,
                    )
                    escalated_count += 1
                    record_event(
                        ctx.conn,
                        ctx.user_id,
                        ctx.actor,
                        event_type="alert_escalated",
                        reason="Existing open alert escalated in place due to worsened metrics",
                        run_id=ctx.run_id,
                        metadata={
                            "alert_id": existing.id,
                            "old_severity": existing.severity,
                            "new_severity": adj_sev,
                            "score_bp": adj_score_bp,
                        },
                        clock=ctx.clock,
                    )
                    continue
                else:
                    # Already open at same or higher severity -> do not duplicate
                    continue

        # Create new open alert
        alert_id = str(uuid.uuid4())
        new_alert = Alert(
            id=alert_id,
            user_id=ctx.user_id,
            kind="budget_risk",
            subject_key=cat_id,
            period=period,
            score_bp=adj_score_bp,
            severity=adj_sev,
            components=breakdown.components,
            why_text=why_text,
            status="open",
            dedup_key=dedup_key,
            run_id=run_id,
            created_at=to_utc_iso(now),
        )
        repo.insert_alert(ctx.conn, new_alert)
        created_count += 1
        open_alerts_count += 1
        record_event(
            ctx.conn,
            ctx.user_id,
            ctx.actor,
            event_type="alert_created",
            reason=f"Adaptive alert created for category {cat_id}",
            run_id=ctx.run_id,
            metadata={
                "alert_id": alert_id,
                "category_id": cat_id,
                "period": period,
                "severity": adj_sev,
                "score_bp": adj_score_bp,
            },
            clock=ctx.clock,
        )

    # Return refreshed open alerts
    active_alerts = repo.list_alerts(ctx.conn, ctx.user_id, status="open")
    summaries = [
        AlertSummary(
            id=a.id,
            kind=a.kind,
            subject_key=a.subject_key,
            period=a.period,
            score_bp=a.score_bp,
            severity=a.severity,
            why_text=a.why_text,
            status=a.status,
            snoozed_until=a.snoozed_until,
            created_at=a.created_at,
        )
        for a in active_alerts
    ]

    return {
        "period": period,
        "alerts": [s.model_dump() for s in summaries],
        "created_count": created_count,
        "escalated_count": escalated_count,
        "suppressed_count": suppressed_count,
    }


def decide_alert_handler(
    ctx: ExecutionContext,
    alert_id: str,
    action: Literal["acknowledge", "dismiss", "snooze"],
    reason: str | None = None,
    snooze_days: int | None = None,
) -> dict[str, Any]:
    """
    User action on an adaptive alert: acknowledge, dismiss, or snooze.
    """
    alert = repo.get_alert(ctx.conn, ctx.user_id, alert_id)
    if not alert:
        raise ToolFailure(
            ErrorCode.NOT_FOUND,
            f"Alert {alert_id} not found for user {ctx.user_id}",
        )

    now = ctx.clock if isinstance(ctx.clock, datetime) else now_utc()
    decided_at = to_utc_iso(now)

    new_status: AlertStatus
    snoozed_until: str | None = None
    dismiss_reason: str | None = None

    if action == "acknowledge":
        new_status = "acknowledged"
        try:
            from copilot.core.learning import record_feedback

            record_feedback(
                ctx.conn,
                user_id=ctx.user_id,
                subject_kind="alert_kind",
                subject_key=f"{alert.kind}:{alert.subject_key}",
                signal="useful",
                clock=ctx.clock,
                run_id=ctx.run_id,
            )
        except Exception:
            pass
    elif action == "dismiss":
        new_status = "dismissed"
        dismiss_reason = reason or "User dismissed"
        is_contextual = False
        if reason:
            r_clean = reason.strip().lower()
            if r_clean not in (
                "user dismissed",
                "dismissed",
                "no reason",
                "none",
                "dismiss",
                "",
            ):
                is_contextual = True

        if is_contextual:
            # Contextual dismissal goes to memory as an exception, NOT to learning!
            try:
                from copilot.core.memory import record_contextual_exception

                clean_r = reason.strip()
                label = clean_r.split(":")[0].strip().lower() if ":" in clean_r else clean_r.lower()
                if label not in (
                    "festival",
                    "travel",
                    "one_off_purchase",
                    "medical",
                    "family_event",
                    "other",
                ):
                    label = "other"

                record_contextual_exception(
                    ctx.conn,
                    user_id=ctx.user_id,
                    category=alert.subject_key,
                    period=alert.period,
                    reason=label,
                    clock=now,
                    run_id=ctx.run_id,
                )
            except Exception:
                pass
        else:
            # Generic dismissal without reason is negative feedback
            try:
                from copilot.core.learning import record_feedback

                record_feedback(
                    ctx.conn,
                    user_id=ctx.user_id,
                    subject_kind="alert_kind",
                    subject_key=f"{alert.kind}:{alert.subject_key}",
                    signal="not_useful",
                    clock=ctx.clock,
                    run_id=ctx.run_id,
                )
            except Exception:
                pass
    elif action == "snooze":
        new_status = "snoozed"
        days = snooze_days or 7
        snoozed_until = to_utc_iso(now + timedelta(days=days))
    else:
        raise ToolFailure(
            ErrorCode.INVALID_INPUT,
            f"Unknown alert action {action}",
        )

    updated = repo.update_alert_status(
        ctx.conn,
        ctx.user_id,
        alert_id,
        status=new_status,
        decided_at=decided_at,
        dismiss_reason=dismiss_reason,
        snoozed_until=snoozed_until,
    )

    record_event(
        ctx.conn,
        ctx.user_id,
        ctx.actor,
        event_type="alert_decided",
        reason=f"Alert {alert_id} decided by {ctx.actor}: {action}",
        run_id=ctx.run_id,
        metadata={
            "alert_id": alert_id,
            "action": action,
            "status": new_status,
            "reason": dismiss_reason,
            "snoozed_until": snoozed_until,
        },
        clock=ctx.clock,
    )

    return {
        "alert_id": alert_id,
        "action": action,
        "status": new_status,
        "updated": updated,
    }


def set_alert_preference_handler(
    ctx: ExecutionContext,
    category_id: str | None = None,
    kind: str | None = None,
    min_severity: AlertSeverity = "info",
    muted: bool = False,
    max_open_alerts: int | None = None,
) -> dict[str, Any]:
    """
    Set user alert preference per-category or globally.
    """
    pref_id = str(uuid.uuid4())
    pref = AlertPreference(
        id=pref_id,
        user_id=ctx.user_id,
        category_id=category_id,
        kind=kind,
        min_severity=min_severity,
        muted=muted,
        max_open_alerts=max_open_alerts,
    )
    repo.set_alert_preference(ctx.conn, pref)

    if muted and category_id:
        try:
            from copilot.core.learning import record_feedback

            record_feedback(
                ctx.conn,
                user_id=ctx.user_id,
                subject_kind="alert_kind",
                subject_key=f"budget_risk:{category_id}",
                signal="not_useful",
                clock=ctx.clock,
                run_id=ctx.run_id,
            )
        except Exception:
            pass
    record_event(
        ctx.conn,
        ctx.user_id,
        ctx.actor,
        event_type="alert_preference_updated",
        reason="User alert preference updated",
        run_id=ctx.run_id,
        metadata={
            "preference_id": pref_id,
            "category_id": category_id,
            "min_severity": min_severity,
            "muted": muted,
            "max_open_alerts": max_open_alerts,
        },
        clock=ctx.clock,
    )
    return {"preference_id": pref_id, "updated": True}


def list_alerts_handler(
    ctx: ExecutionContext,
    status: AlertStatus | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """
    List alerts for user.
    """
    alerts = repo.list_alerts(ctx.conn, ctx.user_id, status=status, limit=limit)
    summaries = [
        AlertSummary(
            id=a.id,
            kind=a.kind,
            subject_key=a.subject_key,
            period=a.period,
            score_bp=a.score_bp,
            severity=a.severity,
            why_text=a.why_text,
            status=a.status,
            snoozed_until=a.snoozed_until,
            created_at=a.created_at,
        )
        for a in alerts
    ]
    return {"alerts": [s.model_dump() for s in summaries]}


# -------------------------------------------------------------------------------------------------
# Registration
# -------------------------------------------------------------------------------------------------


def register_alert_tools(register_fn: Callable[[ToolSpec], None] = register) -> None:
    """Register adaptive alerts tools into the global registry."""
    register_fn(
        ToolSpec(
            name="evaluate_alerts",
            description="Evaluate all spend and budget signals and generate adaptive alerts.",
            side_effect=SideEffect.WRITE_LOGICAL,
            input_model=EvaluateAlertsInput,
            output_model=EvaluateAlertsOutput,
            handler=evaluate_alerts_handler,
        )
    )

    register_fn(
        ToolSpec(
            name="decide_alert",
            description="User action to acknowledge, dismiss, or snooze an alert.",
            side_effect=SideEffect.WRITE_LOGICAL,
            input_model=DecideAlertInput,
            output_model=DecideAlertOutput,
            handler=decide_alert_handler,
        )
    )

    register_fn(
        ToolSpec(
            name="set_alert_preference",
            description="Set user preference for alert silencing, severity thresholds, or limits.",
            side_effect=SideEffect.WRITE_LOGICAL,
            input_model=SetAlertPreferenceInput,
            output_model=SetAlertPreferenceOutput,
            handler=set_alert_preference_handler,
        )
    )

    register_fn(
        ToolSpec(
            name="list_alerts",
            description="List active or historical adaptive alerts.",
            side_effect=SideEffect.READ,
            input_model=ListAlertsInput,
            output_model=ListAlertsOutput,
            handler=list_alerts_handler,
        )
    )
