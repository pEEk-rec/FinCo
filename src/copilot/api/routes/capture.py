"""Capture: the SMS bridge, notifications on your devices and payments tagged as they happen."""

import logging
import re
import secrets
import sqlite3
import time
from collections import deque

from fastapi import BackgroundTasks, FastAPI, Query, Request
from pydantic import BaseModel

from copilot.api.contracts import (
    BridgeBankOut,
    BridgeHealthOut,
    CaptureInboxOut,
    CaptureLabelIn,
    CapturePolicyIn,
    CaptureSimulateIn,
    CaptureSmsOut,
    PushActionIn,
    PushActionOut,
    PushDeviceOut,
    PushStatusOut,
    PushSubscribeIn,
    PushUnsubscribeIn,
)
from copilot.api.deps import Conn, auth
from copilot.api.errors import ApiError, ApiException, unwrap
from copilot.api.helpers import sms_fields, sms_shape
from copilot.api.state import ApiState
from copilot.audit.events import record_event
from copilot.capture.today import TodayView, build_today
from copilot.common.timeutil import now_utc
from copilot.tools.capture import (
    LabelPaymentEventOutput,
    SetCounterpartyPolicyOutput,
    SimulatePaymentOutput,
)
from copilot.tools.executor import execute_tool

log = logging.getLogger("copilot.api")


class DemoPaymentOut(BaseModel):
    """The scripted payment the demo just played, and what to point out about it."""

    counterparty: str
    amount_paise: int
    note: str
    position: int
    total: int


def register(app: FastAPI, state: ApiState) -> None:
    # -- Capture: the SMS bridge ---------------------------------------------------------------
    sms_hits: deque[float] = deque()
    reject_audits: deque[float] = deque()

    def _recent(window: deque[float], limit: int) -> bool:
        """Record a hit; True when `limit` hits already happened in the last minute."""
        now = time.monotonic()
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= limit:
            return True
        window.append(now)
        return False

    def _reject(code: int, error: str, message: str, why: str) -> ApiException:
        """Refuse, and write one audit row (capped) that says why. Never any message content."""
        if not _recent(reject_audits, 20):
            conn = state.connect()
            try:
                record_event(
                    conn, state.user_id, "system", "capture_webhook_rejected",
                    f"The SMS bridge refused a request: {why}.",
                    metadata={"why": why}, clock=now_utc(state.clock),
                )  # fmt: skip
                conn.commit()
            finally:
                conn.close()
        return ApiException(code, ApiError(code=error, message=message))

    @app.post("/api/capture/sms", response_model=CaptureSmsOut)
    async def capture_sms(request: Request, background: BackgroundTasks) -> CaptureSmsOut:
        """
        The phone's SMS forwarder posts here. Order matters: secret, rate limit and size are
        checked before any message is looked at; the sender allowlist is checked before the
        text is parsed; and the text is never stored, logged or returned.
        """
        from copilot.capture.events import record_args_from_parsed
        from copilot.capture.secret import load_capture_secret
        from copilot.capture.sms_parser import (
            Dropped,
            ParsedPayment,
            parse_sms,
            record_parse_outcome,
        )
        from copilot.config.capture import load_capture_config, load_sms_senders

        cfg = load_capture_config().webhook
        secret = state.capture_secret or load_capture_secret()
        if not secret:
            raise ApiException(
                503,
                ApiError(
                    code="SETUP_REQUIRED",
                    message="The SMS bridge has no secret yet. Run: copilot capture bridge-setup",
                ),
            )
        supplied = request.headers.get(cfg.secret_header.lower(), "")
        if not supplied or not secrets.compare_digest(supplied, secret):
            raise _reject(401, "UNAUTHORIZED", "Missing or invalid bridge secret.", "bad_secret")
        if _recent(sms_hits, cfg.rate_limit_per_minute):
            raise ApiException(
                429, ApiError(code="RATE_LIMITED", message="Too many alerts this minute.")
            )
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > cfg.max_body_bytes:
            raise ApiException(413, ApiError(code="INVALID_INPUT", message="Message too large."))
        raw = await request.body()
        if len(raw) > cfg.max_body_bytes:
            raise ApiException(413, ApiError(code="INVALID_INPUT", message="Message too large."))
        sender, text = sms_fields(raw, request.headers.get("content-type", ""))
        if not sender or not text:
            raise ApiException(
                422,
                ApiError(
                    code="INVALID_INPUT",
                    message="Send the sender and the message text. Received: "
                    + sms_shape(raw, request.headers.get("content-type", "")),
                ),
            )

        now = now_utc(state.clock)
        senders = state.capture_senders or load_sms_senders()
        outcome = parse_sms(
            sender,
            text,
            now,
            senders=senders,  # type: ignore[arg-type]
            any_sender=(
                load_capture_config().sms.accept_any_sender
                if state.capture_any_sender is None
                else state.capture_any_sender
            ),
        )
        log.warning(
            "sms webhook: %s%s, sender %s, %d characters",
            type(outcome).__name__,
            f" ({outcome.reason})" if isinstance(outcome, Dropped) else "",
            "a phone number" if re.fullmatch(r"\+?[\d\s-]{5,}", sender.strip()) else "a header",
            len(text),
        )  # never the text, never the sender itself
        del text, raw  # the message is not kept past this point

        conn = state.connect()
        try:
            record_parse_outcome(conn, state.user_id, outcome, now)
            if isinstance(outcome, Dropped):
                conn.commit()
                return CaptureSmsOut(outcome="dropped", reason=outcome.reason)
            if not isinstance(outcome, ParsedPayment):
                conn.commit()
                return CaptureSmsOut(outcome="unparsed", reason="format_not_recognised")
            res = execute_tool(
                state.context(conn, "system"),
                "record_payment_event",
                record_args_from_parsed(outcome, source="sms", simulated=False),
            )
            conn.commit()
            data = unwrap(res)
            if data.created:  # type: ignore[attr-defined]
                _announce(background, conn, data.event.id)  # type: ignore[attr-defined]
            return CaptureSmsOut(
                outcome="recorded" if data.created else "duplicate",  # type: ignore[attr-defined]
                event_id=data.event.id,  # type: ignore[attr-defined]
                decision=data.decision,  # type: ignore[attr-defined]
            )
        finally:
            conn.close()

    @app.get("/api/capture/bridge", response_model=BridgeHealthOut, dependencies=auth)
    def capture_bridge(conn: Conn) -> BridgeHealthOut:
        from copilot.capture.secret import load_capture_secret
        from copilot.capture.sms_parser import drift_report
        from copilot.config.capture import load_sms_senders

        senders = state.capture_senders or load_sms_senders()
        now = now_utc(state.clock)
        drift = {d.bank: d for d in drift_report(conn, state.user_id, now)}
        banks = []
        for code, b in senders.banks.items():  # type: ignore[attr-defined]
            last = conn.execute(
                "SELECT MAX(occurred_at) FROM sms_parse_log WHERE user_id = ? AND bank = ?",
                (state.user_id, code),
            ).fetchone()[0]
            d = drift.get(code)
            banks.append(
                BridgeBankOut(
                    bank=code,
                    name=b.name,
                    enabled=b.enabled,
                    last_received_at=last,
                    parsed=d.parsed if d else 0,
                    unparsed=d.unparsed if d else 0,
                    failure_bp=d.failure_bp if d else 0,
                    drifting=bool(d and d.alert),
                )  # fmt: skip
            )
        return BridgeHealthOut(
            secret_configured=bool(state.capture_secret or load_capture_secret()),
            banks=banks,
            any_enabled=any(b.enabled for b in banks),
        )

    # -- Capture: notifications on the user's devices ------------------------------------------
    def _push_in_background(kind: str, prompt_id: str, except_sub: str | None = None) -> None:
        """Send pushes after the response. A failure here must never break a request."""
        from copilot.capture import events as _core
        from copilot.capture import push as capture_push

        sender = state.push_sender or capture_push.real_sender
        conn = state.connect()
        try:
            if kind == "prompt":
                view = next(
                    (
                        p
                        for p in _core.pending_prompts(conn, state.user_id)
                        if p.prompt_id == prompt_id
                    ),
                    None,
                )
                if view is not None:
                    capture_push.notify_prompt(
                        conn,
                        state.user_id,
                        view,
                        sender,
                        clock=now_utc(state.clock),  # type: ignore[arg-type]
                    )
            else:
                capture_push.notify_resolved(
                    conn, state.user_id, prompt_id, sender,  # type: ignore[arg-type]
                    except_subscription=except_sub, clock=now_utc(state.clock),
                )  # fmt: skip
            conn.commit()
        except Exception:  # noqa: BLE001
            log.warning("push delivery failed", exc_info=False)
        finally:
            conn.close()

    def _announce(background: BackgroundTasks, conn: sqlite3.Connection, event_id: str) -> None:
        """Queue a push for this payment's prompt, when the ask policy wants an answer."""
        row = conn.execute(
            "SELECT id FROM prompt_log WHERE user_id = ? AND event_id = ? AND decision = 'ask'"
            " AND status = 'pending'",
            (state.user_id, event_id),
        ).fetchone()
        if row:
            background.add_task(_push_in_background, "prompt", row[0], None)

    @app.get("/api/capture/push/status", response_model=PushStatusOut, dependencies=auth)
    def push_status(conn: Conn) -> PushStatusOut:
        from copilot.capture import push as capture_push
        from copilot.config.capture import load_capture_config

        cfg = load_capture_config().push
        _private, public = capture_push.ensure_vapid()
        conn.commit()
        return PushStatusOut(
            enabled=cfg.enabled,
            public_key=public,
            lock_screen_safe=cfg.lock_screen_safe,
            max_actions=cfg.max_actions,
            devices=[
                PushDeviceOut(id=s.id, label=s.label)
                for s in capture_push.list_subscriptions(conn, state.user_id)
            ],
        )

    @app.post("/api/capture/push/subscribe", response_model=PushDeviceOut, dependencies=auth)
    def push_subscribe(body: PushSubscribeIn, conn: Conn) -> PushDeviceOut:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "register_push_subscription",
                {
                    "endpoint": body.endpoint,
                    "p256dh": body.keys.p256dh,
                    "auth": body.keys.auth,
                    "label": body.label,
                },
            )
        )
        conn.commit()
        return PushDeviceOut(id=out.subscription_id, label=body.label)  # type: ignore[attr-defined]

    @app.post("/api/capture/push/unsubscribe", dependencies=auth)
    def push_unsubscribe(body: PushUnsubscribeIn, conn: Conn) -> dict[str, bool]:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"), "remove_push_subscription", {"endpoint": body.endpoint}
            )
        )
        conn.commit()
        return {"removed": out.removed}  # type: ignore[attr-defined]

    @app.post("/api/capture/push/action", response_model=PushActionOut)
    def push_action(body: PushActionIn, background: BackgroundTasks) -> PushActionOut:
        """A notification button. The first answer wins; the other devices' notifications close."""
        from copilot.capture import push as capture_push

        conn = state.connect()
        try:
            delivery = capture_push.verify_token(conn, state.user_id, body.token, body.prompt_id)
            if delivery is None:
                raise ApiException(
                    401, ApiError(code="UNAUTHORIZED", message="That button is no longer valid.")
                )
            now = now_utc(state.clock)
            capture_push.mark_used(conn, delivery, now)
            event_id = capture_push.prompt_is_pending(conn, state.user_id, body.prompt_id)
            if event_id is None:
                conn.commit()
                return PushActionOut(outcome="already_tagged")
            args = {"event_id": event_id, "rank_picked": body.rank}
            args["credit_kind" if body.credit else "category_id"] = body.label
            unwrap(execute_tool(state.context(conn, "user"), "label_payment_event", args))
            conn.commit()
            background.add_task(
                _push_in_background, "resolved", body.prompt_id, delivery.subscription_id
            )
            return PushActionOut(outcome="tagged")
        finally:
            conn.close()

    @app.get("/api/capture/today", response_model=TodayView, dependencies=auth)
    def capture_today(
        conn: Conn, day: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    ) -> TodayView:
        """One day, every payment in and out, grouped by what is left for you to do."""
        return build_today(conn, state.user_id, day, clock=now_utc(state.clock))

    # -- Capture: payments tagged at the moment of payment -------------------------------------
    @app.get("/api/capture/inbox", response_model=CaptureInboxOut, dependencies=auth)
    def capture_inbox(conn: Conn) -> CaptureInboxOut:
        from copilot.capture import simulator as capture_sim
        from copilot.config.capture import load_capture_config

        out = unwrap(execute_tool(state.context(conn, "user"), "pending_prompts", {}))
        prompts = out.prompts  # type: ignore[attr-defined]
        return CaptureInboxOut(
            prompts=prompts,
            pending_count=len(prompts),
            banks=capture_sim.banks(),
            kinds=list(capture_sim.KINDS),
            credit_kinds=list(load_capture_config().credits.categories),
        )

    @app.post("/api/capture/simulate", response_model=SimulatePaymentOutput, dependencies=auth)
    def capture_simulate(
        body: CaptureSimulateIn, conn: Conn, background: BackgroundTasks
    ) -> SimulatePaymentOutput:
        out = unwrap(
            execute_tool(state.context(conn, "user"), "simulate_payment_event", body.model_dump())
        )
        conn.commit()
        _announce(background, conn, out.event.id)  # type: ignore[attr-defined]
        return out  # type: ignore[return-value]

    @app.post("/api/demo/live-payment", response_model=DemoPaymentOut, dependencies=auth)
    def demo_live_payment(conn: Conn, background: BackgroundTasks) -> DemoPaymentOut:
        """Demo: play the next scripted payment through the same path a real alert takes."""
        from copilot.bank.demo_story import LIVE_PAYMENTS

        pick = LIVE_PAYMENTS[state.demo_cursor % len(LIVE_PAYMENTS)]
        position = state.demo_cursor % len(LIVE_PAYMENTS) + 1
        state.demo_cursor += 1
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "simulate_payment_event",
                {
                    "bank": "hdfc",
                    "kind": "debit",
                    "amount_paise": pick.amount_paise,
                    "counterparty": pick.counterparty,
                    "vpa": pick.vpa,
                },
            )
        )
        conn.commit()
        _announce(background, conn, out.event.id)  # type: ignore[attr-defined]
        return DemoPaymentOut(
            counterparty=pick.counterparty,
            amount_paise=pick.amount_paise,
            note=pick.note,
            position=position,
            total=len(LIVE_PAYMENTS),
        )

    @app.post("/api/capture/labels", response_model=LabelPaymentEventOutput, dependencies=auth)
    def capture_label(
        body: CaptureLabelIn, conn: Conn, background: BackgroundTasks
    ) -> LabelPaymentEventOutput:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "label_payment_event",
                body.model_dump(exclude_none=True),
            )
        )
        conn.commit()
        row = conn.execute(
            "SELECT id FROM prompt_log WHERE user_id = ? AND event_id = ?",
            (state.user_id, body.event_id),
        ).fetchone()
        if row:
            background.add_task(_push_in_background, "resolved", row[0], None)
        return out  # type: ignore[return-value]

    @app.post(
        "/api/capture/counterparty-policy",
        response_model=SetCounterpartyPolicyOutput,
        dependencies=auth,
    )
    def capture_policy(body: CapturePolicyIn, conn: Conn) -> SetCounterpartyPolicyOutput:
        out = unwrap(
            execute_tool(
                state.context(conn, "user"),
                "set_counterparty_policy",
                body.model_dump(exclude_none=True),
            )
        )
        conn.commit()
        return out  # type: ignore[return-value]
