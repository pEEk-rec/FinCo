"""
The capture lane (PLAN_CAPTURE Stage C1): record a payment as it happens, decide whether to ask
about it, offer the best three guesses, and keep the user's answer as the truth.

Nothing here stores or sees raw message text; callers hand in already-parsed fields. All writes
leave the transaction open (the caller commits) and every change is audited.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from copilot.audit.events import Actor, record_event
from copilot.config.capture import CaptureConfig, load_capture_config
from copilot.core.capture_learning import learn_from_label, unlearn, with_learned_weights
from copilot.core.capture_logic import (
    AskContext,
    AskDecision,
    EventFacts,
    Guess,
    HistoryRow,
    classify_counterparty,
    counterparty_key,
    decide_ask,
    normalise_name,
    rank_guesses,
)
from copilot.core.errors import ErrorCode, ToolFailure
from copilot.core.timeutil import IST, from_utc_iso, now_utc, to_utc_iso
from copilot.models.capture import (
    CounterpartyProfile,
    GuessView,
    PaymentEvent,
    PromptView,
)

_HISTORY_LIMIT = 600


@dataclass(frozen=True)
class RecordedEvent:
    event: PaymentEvent
    created: bool
    decision: AskDecision
    guesses: list[GuessView]


# ---------------------------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------------------------
def _row_to_event(r: sqlite3.Row) -> PaymentEvent:
    return PaymentEvent(
        id=r["id"],
        user_id=r["user_id"],
        source=r["source"],
        simulated=bool(r["simulated"]),
        amount_paise=r["amount_paise"],
        direction=r["direction"],
        account_last4=r["account_last4"],
        utr=r["utr"],
        counterparty_key=r["counterparty_key"],
        counterparty_kind=r["counterparty_kind"],
        display_name=r["display_name"],
        bank=r["bank"],
        channel=r["channel"],
        occurred_at=r["occurred_at"],
        state=r["state"],
        category_id=r["category_id"],
        credit_kind=r["credit_kind"],
        category_source=r["category_source"],
        needs_review=bool(r["needs_review"]),
        created_at=r["created_at"],
    )


def get_event(conn: sqlite3.Connection, user_id: str, event_id: str) -> PaymentEvent | None:
    row = conn.execute(
        "SELECT * FROM payment_events WHERE user_id = ? AND id = ?", (user_id, event_id)
    ).fetchone()
    return _row_to_event(row) if row else None


def get_profile(conn: sqlite3.Connection, user_id: str, key: str) -> CounterpartyProfile | None:
    row = conn.execute(
        "SELECT * FROM counterparty_profiles WHERE user_id = ? AND counterparty_key = ?",
        (user_id, key),
    ).fetchone()
    if not row:
        return None
    return CounterpartyProfile(
        counterparty_key=row["counterparty_key"],
        kind=row["kind"],
        display_name=row["display_name"],
        policy=row["policy"],
        policy_category_id=row["policy_category_id"],
        recent_categories=json.loads(row["recent_categories_json"]),
        seen_count=row["seen_count"],
    )


def _categories(conn: sqlite3.Connection, user_id: str) -> dict[str, str]:
    rows = conn.execute("SELECT id, name FROM categories WHERE user_id = ?", (user_id,)).fetchall()
    return {r[0]: r[1] for r in rows}


def _label_name(label: str, cats: dict[str, str]) -> str:
    return cats.get(label) or label.replace("_", " ").capitalize()


def _history(conn: sqlite3.Connection, user_id: str) -> list[HistoryRow]:
    rows = conn.execute(
        "SELECT counterparty_key, category_id, credit_kind, amount_paise, occurred_at, direction"
        " FROM payment_events WHERE user_id = ? AND category_source IN ('user', 'auto')"
        " AND state != 'reversed' ORDER BY occurred_at DESC LIMIT ?",
        (user_id, _HISTORY_LIMIT),
    ).fetchall()
    out: list[HistoryRow] = []
    for r in rows:
        label = r["credit_kind"] if r["direction"] == "credit" else r["category_id"]
        if label:
            out.append(
                HistoryRow(
                    r["counterparty_key"], label, r["amount_paise"],
                    from_utc_iso(r["occurred_at"]).astimezone(IST), r["direction"],
                )
            )  # fmt: skip
    return out


def _merchant_confidence(profile, known_cat: str | None, cfg: CaptureConfig) -> int:
    """
    How sure we are of a known shop's category. A rule the user set outright is fully trusted;
    one learned from answers is trusted once the last two answers agree with it, so a single odd
    tap does not silently flip the shop.
    """
    if not known_cat:
        return 0
    recent = profile.recent_categories if profile else []
    if len(recent) >= 2 and not (recent[-1] == recent[-2] == known_cat):
        return cfg.ask.unsteady_merchant_bp
    return 10000


def _known_merchants(conn: sqlite3.Connection, user_id: str) -> dict[str, str]:
    rows = conn.execute(
        "SELECT merchant_normalized, category_id FROM merchant_overrides WHERE user_id = ?",
        (user_id,),
    ).fetchall()
    return {r[0]: r[1] for r in rows}


# ---------------------------------------------------------------------------------------------
# The context the ask policy needs
# ---------------------------------------------------------------------------------------------
def _fingerprint(
    utr: str | None,
    amount: int,
    direction: str,
    account: str | None,
    key: str,
    when: str,
    bank: str | None,
) -> str:
    if utr:
        return "utr:" + hashlib.sha256(utr.encode()).hexdigest()[:32]
    raw = f"{amount}|{direction}|{account}|{key}|{when[:16]}|{bank}"
    return "fp:" + hashlib.sha256(raw.encode()).hexdigest()[:32]


def _recurring_category(conn: sqlite3.Connection, user_id: str, name: str) -> str | None:
    """The usual category of a counterparty that has a recurring series (an AutoPay, a rent)."""
    series = conn.execute(
        "SELECT 1 FROM recurring_series WHERE user_id = ? AND merchant_normalized = ?",
        (user_id, name),
    ).fetchone()
    if not series:
        return None
    row = conn.execute(
        "SELECT category_id, COUNT(*) c FROM transactions WHERE user_id = ?"
        " AND merchant_normalized = ? AND category_id IS NOT NULL GROUP BY category_id"
        " ORDER BY c DESC, category_id LIMIT 1",
        (user_id, name),
    ).fetchone()
    return row[0] if row else None


def _refund_target(
    conn: sqlite3.Connection, user_id: str, key: str, amount: int, when: str
) -> str | None:
    """An earlier debit to the same counterparty for the same amount, not yet refunded."""
    since = to_utc_iso(from_utc_iso(when) - timedelta(days=45))
    row = conn.execute(
        "SELECT id FROM payment_events d WHERE d.user_id = ? AND d.direction = 'debit'"
        " AND d.counterparty_key = ? AND d.amount_paise = ? AND d.occurred_at BETWEEN ? AND ?"
        " AND NOT EXISTS (SELECT 1 FROM capture_labels l WHERE l.user_id = d.user_id"
        "                 AND l.linked_event_id = d.id AND l.credit_kind = 'refund')"
        " ORDER BY d.occurred_at DESC LIMIT 1",
        (user_id, key, amount, since, when),
    ).fetchone()
    return row[0] if row else None


def _prompts_today(conn: sqlite3.Connection, user_id: str, local_now: datetime) -> int:
    start = to_utc_iso(local_now.replace(hour=0, minute=0, second=0, microsecond=0))
    return conn.execute(
        "SELECT COUNT(*) FROM prompt_log"
        " WHERE user_id = ? AND decision = 'ask' AND created_at >= ?",
        (user_id, start),
    ).fetchone()[0]


def _minutes_since_prompt(
    conn: sqlite3.Connection, user_id: str, key: str, now: datetime
) -> int | None:
    row = conn.execute(
        "SELECT p.created_at FROM prompt_log p JOIN payment_events e ON e.id = p.event_id"
        " WHERE p.user_id = ? AND p.decision = 'ask' AND e.counterparty_key = ?"
        " ORDER BY p.created_at DESC LIMIT 1",
        (user_id, key),
    ).fetchone()
    return int((now - from_utc_iso(row[0])).total_seconds() // 60) if row else None


def _known_inflow_kind(profile: CounterpartyProfile | None) -> str | None:
    """Two earlier credits from this payer both labelled salary (or both allowance)."""
    if not profile:
        return None
    last = profile.recent_categories[-2:]
    return (
        last[0]
        if len(last) == 2 and last[0] == last[1] and last[0] in ("salary", "allowance")
        else None
    )


def record_args_from_parsed(parsed, *, source: str, simulated: bool) -> dict:
    """The arguments `record_payment_event` takes, from a parsed alert. A reversal alert quotes
    the UTR of the payment it undoes, so that goes in `reversal_of_utr`, not `utr`."""
    reversal = parsed.kind == "reversal"
    return {
        "source": source,
        "amount_paise": parsed.amount_paise,
        "direction": parsed.direction,
        "display_name": parsed.display_name,
        "occurred_at": parsed.occurred_at,
        "vpa": parsed.vpa,
        "account_last4": parsed.account_last4,
        "utr": None if reversal else parsed.utr,
        "bank": parsed.bank,
        "channel": parsed.channel,
        "simulated": simulated,
        "reversal_of_utr": parsed.utr if reversal else None,
    }


# ---------------------------------------------------------------------------------------------
# Recording a payment
# ---------------------------------------------------------------------------------------------
def record_payment_event(
    conn: sqlite3.Connection,
    user_id: str,
    *,
    source: str,
    amount_paise: int,
    direction: str,
    display_name: str,
    occurred_at: str,
    vpa: str | None = None,
    account_last4: str | None = None,
    utr: str | None = None,
    bank: str | None = None,
    channel: str = "other",
    simulated: bool = False,
    actor: Actor = "system",
    run_id: str | None = None,
    clock: datetime | None = None,
    llm_client=None,
    cfg: CaptureConfig | None = None,
    reversal_of_utr: str | None = None,
) -> RecordedEvent:
    """Idempotent: the same UTR (or the same payment fingerprint) is recorded once."""
    cfg = cfg or load_capture_config()
    now = now_utc(clock)
    local_now = now.astimezone(IST)
    known = _known_merchants(conn, user_id)
    own_keys = frozenset(
        r[0]
        for r in conn.execute(
            "SELECT counterparty_key FROM counterparty_profiles"
            " WHERE user_id = ? AND kind = 'self'",
            (user_id,),
        )
    )
    key, kind = classify_counterparty(
        display_name, vpa, channel, cfg, own_keys=own_keys, known_merchant_names=frozenset(known)
    )
    # A reversal alert quotes the *original* payment's UTR. It must not collide with it:
    # the reversal is recorded without a UTR and linked to the payment it undoes.
    original_id = None
    if reversal_of_utr:
        found = conn.execute(
            "SELECT id FROM payment_events WHERE user_id = ? AND utr = ? AND direction = 'debit'",
            (user_id, reversal_of_utr),
        ).fetchone()
        original_id = found[0] if found else None
        utr = None
        key = f"reversal:{reversal_of_utr}"
    fp = _fingerprint(utr, amount_paise, direction, account_last4, key, occurred_at, bank)
    if reversal_of_utr:
        fp = "rev:" + hashlib.sha256(reversal_of_utr.encode()).hexdigest()[:32]

    existing = conn.execute(
        "SELECT * FROM payment_events WHERE user_id = ?"
        " AND (fingerprint = ? OR (utr IS NOT NULL AND utr = ?))",
        (user_id, fp, utr),
    ).fetchone()
    if existing:
        event = _row_to_event(existing)
        prompt = _prompt_row(conn, user_id, event.id)
        decision = AskDecision(prompt["decision"] if prompt else "no_ask", "duplicate")
        guesses = [GuessView(**g) for g in json.loads(prompt["guesses_json"])] if prompt else []
        return RecordedEvent(event, False, decision, guesses)

    event_id = f"pev_{uuid.uuid4().hex[:12]}"
    created = to_utc_iso(now)
    conn.execute(
        "INSERT INTO payment_events (id, user_id, source, simulated, amount_paise, direction,"
        " account_last4, utr, fingerprint, counterparty_key, counterparty_kind, display_name,"
        " bank, channel, occurred_at, state, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'posted', ?)",
        (
            event_id, user_id, source, int(simulated), amount_paise, direction, account_last4,
            utr, fp, key, kind, display_name.strip()[:80], bank, channel, occurred_at, created,
        ),
    )  # fmt: skip
    _touch_profile(conn, user_id, key, kind, display_name.strip()[:80], occurred_at, created)

    profile = get_profile(conn, user_id, key)
    name_norm = normalise_name(display_name)
    known_cat = known.get(name_norm) or known.get(key)
    ctx = AskContext(
        local_time=local_now,
        prompts_today=_prompts_today(conn, user_id, local_now),
        minutes_since_counterparty_prompt=_minutes_since_prompt(conn, user_id, key, now),
        known_merchant_category=known_cat,
        known_merchant_confidence_bp=_merchant_confidence(profile, known_cat, cfg),
        recurring_category=(
            _recurring_category(conn, user_id, name_norm) if direction == "debit" else None
        ),
        refund_of_event_id=original_id
        or (
            _refund_target(conn, user_id, key, amount_paise, occurred_at)
            if direction == "credit"
            else None
        ),
        known_inflow_kind=_known_inflow_kind(profile) if direction == "credit" else None,
        policy=profile.policy if profile else "learn",
        policy_category=profile.policy_category_id if profile else None,
        recent_categories=tuple(profile.recent_categories) if profile else (),
    )
    decision = decide_ask(EventFacts(amount_paise, direction, kind, channel), ctx, cfg)  # type: ignore[arg-type]

    cats = _categories(conn, user_id)
    hint = None
    if (
        decision.action in ("ask", "inbox", "guess_only")
        and direction == "debit"
        and kind in ("merchant", "unknown")
    ):
        hint = _llm_hint(conn, user_id, llm_client, name_norm, cats, cfg, now, run_id)
    guesses = _guesses(conn, user_id, key, direction, amount_paise, occurred_at, cats, cfg, hint)

    prompt_id = f"prm_{uuid.uuid4().hex[:12]}"
    status = "pending" if decision.action in ("ask", "inbox") else "not_needed"
    expires = (
        to_utc_iso(now + timedelta(hours=cfg.prompts.ttl_hours)) if status == "pending" else None
    )
    conn.execute(
        "INSERT INTO prompt_log (id, user_id, event_id, decision, reason, guesses_json, status,"
        " created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            prompt_id, user_id, event_id, decision.action, decision.reason,
            json.dumps([g.model_dump() for g in guesses]), status, created, expires,
        ),
    )  # fmt: skip

    if original_id:
        # The payment it undoes no longer counts, and its question is no longer needed.
        conn.execute(
            "UPDATE payment_events SET state = 'reversed' WHERE user_id = ? AND id = ?",
            (user_id, original_id),
        )
        conn.execute(
            "UPDATE payment_events SET reversed_event_id = ? WHERE user_id = ? AND id = ?",
            (original_id, user_id, event_id),
        )
        conn.execute(
            "UPDATE prompt_log SET status = 'dismissed' WHERE user_id = ? AND event_id = ?"
            " AND status = 'pending'",
            (user_id, original_id),
        )
        record_event(
            conn, user_id=user_id, actor=actor, event_type="payment_reversed",
            reason="A reversal cancelled an earlier payment", run_id=run_id,
            entity_type="payment_event", entity_id=original_id,
            metadata={"reversal_event_id": event_id}, clock=now,
        )  # fmt: skip

    # What the event itself carries straight away.
    if decision.action == "auto_label":
        _set_label(
            conn, user_id, event_id, decision.category_id, decision.credit_kind, "auto",
            False, created, linked=decision.linked_event_id,
        )  # fmt: skip
    elif decision.action == "guess_only" and guesses:
        top = guesses[0].label
        _set_label(
            conn, user_id, event_id,
            top if direction == "debit" else None,
            top if direction == "credit" else None,
            "guess", True, created,
        )  # fmt: skip

    record_event(
        conn,
        user_id=user_id,
        actor=actor,
        event_type="payment_event_recorded",
        reason=f"Payment captured ({decision.action}: {decision.reason})",
        run_id=run_id,
        entity_type="payment_event",
        entity_id=event_id,
        metadata={
            "source": source,
            "simulated": simulated,
            "direction": direction,
            "amount_paise": amount_paise,
            "decision": decision.action,
            "reason": decision.reason,
            "counterparty_kind": kind,
        },
        clock=now,
    )
    event = get_event(conn, user_id, event_id)
    assert event is not None
    return RecordedEvent(event, True, decision, guesses)


def _prompt_row(conn: sqlite3.Connection, user_id: str, event_id: str):
    return conn.execute(
        "SELECT * FROM prompt_log WHERE user_id = ? AND event_id = ?", (user_id, event_id)
    ).fetchone()


def _touch_profile(
    conn: sqlite3.Connection, user_id: str, key: str, kind: str, name: str, seen: str, now: str
) -> None:
    conn.execute(
        "INSERT INTO counterparty_profiles (id, user_id, counterparty_key, kind, display_name,"
        " seen_count, last_seen_at, updated_at) VALUES (?, ?, ?, ?, ?, 1, ?, ?)"
        " ON CONFLICT(user_id, counterparty_key) DO UPDATE SET"
        " seen_count = seen_count + 1, last_seen_at = excluded.last_seen_at,"
        " display_name = excluded.display_name, updated_at = excluded.updated_at",
        (f"cpp_{uuid.uuid4().hex[:12]}", user_id, key, kind, name, seen, now),
    )


def _set_label(
    conn: sqlite3.Connection,
    user_id: str,
    event_id: str,
    category_id: str | None,
    credit_kind: str | None,
    source: str,
    needs_review: bool,
    now: str,
    *,
    linked: str | None = None,
    rank_picked: int | None = None,
    note: str | None = None,
    split: list | None = None,
) -> str:
    conn.execute(
        "UPDATE payment_events SET category_id = ?, credit_kind = ?, category_source = ?,"
        " needs_review = ? WHERE user_id = ? AND id = ?",
        (category_id, credit_kind, source, int(needs_review), user_id, event_id),
    )
    label_id = f"lbl_{uuid.uuid4().hex[:12]}"
    conn.execute(
        "INSERT INTO capture_labels (id, user_id, event_id, category_id, credit_kind, split_json,"
        " note, source, rank_picked, linked_event_id, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            label_id, user_id, event_id, category_id, credit_kind,
            json.dumps(split) if split else None, note, source, rank_picked, linked, now,
        ),
    )  # fmt: skip
    return label_id


def _guesses(
    conn: sqlite3.Connection,
    user_id: str,
    key: str,
    direction: str,
    amount: int,
    occurred_at: str,
    cats: dict[str, str],
    cfg: CaptureConfig,
    hint: str | None,
) -> list[GuessView]:
    fallback = (
        list(cfg.credits.categories)
        if direction == "credit"
        else _ledger_order(conn, user_id, cats)
    )
    ranked = rank_guesses(
        counterparty=key,
        direction=direction,  # type: ignore[arg-type]
        amount_paise=amount,
        when=from_utc_iso(occurred_at).astimezone(IST),
        history=_history(conn, user_id),
        cfg=with_learned_weights(conn, user_id, cfg),
        hint_label=hint,
        fallback_labels=fallback,
    )
    return [_view(g, cats) for g in ranked]


def _ledger_order(conn: sqlite3.Connection, user_id: str, cats: dict[str, str]) -> list[str]:
    """Categories by how much the user spends on them, so the very first guesses are sensible."""
    rows = conn.execute(
        "SELECT category_id, COUNT(*) c FROM transactions WHERE user_id = ? AND direction = 'debit'"
        " AND category_id IS NOT NULL GROUP BY category_id ORDER BY c DESC, category_id",
        (user_id,),
    ).fetchall()
    ordered = [r[0] for r in rows if r[0] in cats]
    return ordered + [c for c in sorted(cats) if c not in ordered]


def _view(g: Guess, cats: dict[str, str]) -> GuessView:
    return GuessView(
        label=g.label, name=_label_name(g.label, cats), score_bp=g.score_bp, reasons=list(g.reasons)
    )


def _llm_hint(
    conn: sqlite3.Connection,
    user_id: str,
    llm,
    name_norm: str,
    cats: dict[str, str],
    cfg: CaptureConfig,
    now: datetime,
    run_id: str | None,
) -> str | None:
    """
    A category hint for a merchant-like name, through the router. Only the normalised name and
    the user's own category list go out; never a person, never message text. The hint only joins
    the candidates: ranking stays deterministic and nothing is labelled by it.
    """
    if llm is None or not cfg.llm_suggest.enabled or not name_norm or not cats:
        return None
    start = to_utc_iso(now.astimezone(IST).replace(hour=0, minute=0, second=0, microsecond=0))
    used = conn.execute(
        "SELECT COUNT(*) FROM audit_events WHERE user_id = ? AND event_type = 'capture_llm_hint'"
        " AND occurred_at >= ?",
        (user_id, start),
    ).fetchone()[0]
    if used >= cfg.llm_suggest.max_calls_per_day:
        return None
    from copilot.core.pipeline import ask_llm

    record_event(
        conn, user_id=user_id, actor="system", event_type="capture_llm_hint",
        reason="Asked the model for a category hint for a merchant name", run_id=run_id,
        metadata={"merchant": name_norm}, clock=now,
    )  # fmt: skip
    try:
        decisions, _calls, _failed = ask_llm(llm, [name_norm], cats, max_retries=1, batch_size=1)
    except ToolFailure:
        return None
    return decisions[0].category_id if decisions and decisions[0].category_id else None


# ---------------------------------------------------------------------------------------------
# Labelling (the user's answer)
# ---------------------------------------------------------------------------------------------
def _label_state(e: PaymentEvent) -> dict:
    return {
        "category_id": e.category_id,
        "credit_kind": e.credit_kind,
        "category_source": e.category_source,
        "needs_review": e.needs_review,
    }


def label_payment_event(
    conn: sqlite3.Connection,
    user_id: str,
    event_id: str,
    *,
    category_id: str | None = None,
    credit_kind: str | None = None,
    note: str | None = None,
    split: list[dict] | None = None,
    rank_picked: int | None = None,
    linked_event_id: str | None = None,
    actor: Actor = "user",
    run_id: str | None = None,
    clock: datetime | None = None,
    cfg: CaptureConfig | None = None,
) -> PaymentEvent:
    """Record the user's answer. A user's label is never overwritten by anyone else."""
    cfg = cfg or load_capture_config()
    event = get_event(conn, user_id, event_id)
    if event is None:
        raise ToolFailure(ErrorCode.NOT_FOUND, f"Payment {event_id} not found.")
    if actor != "user" and event.category_source == "user":
        raise ToolFailure(
            ErrorCode.INVALID_INPUT, "A label you chose is never overwritten automatically."
        )
    if event.direction == "debit":
        if credit_kind or not category_id:
            raise ToolFailure(ErrorCode.INVALID_INPUT, "A payment out needs a category.")
        if category_id not in _categories(conn, user_id):
            raise ToolFailure(ErrorCode.INVALID_INPUT, f"Unknown category {category_id!r}.")
    else:
        if category_id or not credit_kind:
            raise ToolFailure(ErrorCode.INVALID_INPUT, "Money coming in needs a credit kind.")
        if credit_kind not in cfg.credits.categories:
            raise ToolFailure(ErrorCode.INVALID_INPUT, f"Unknown credit kind {credit_kind!r}.")
    if linked_event_id:
        linked = get_event(conn, user_id, linked_event_id)
        if linked is None or linked.direction != "debit" or linked.id == event.id:
            raise ToolFailure(ErrorCode.INVALID_INPUT, "That payment cannot be linked.")
        if event.direction != "credit":
            raise ToolFailure(ErrorCode.INVALID_INPUT, "Only incoming money can be linked.")

    before = _label_state(event)
    now = now_utc(clock)
    label = category_id if event.direction == "debit" else credit_kind
    assert label is not None
    learned = learn_from_label(
        conn, user_id, counterparty=event.counterparty_key, direction=event.direction,
        amount_paise=event.amount_paise, when=from_utc_iso(event.occurred_at).astimezone(IST),
        label=label, history=_history(conn, user_id), cfg=cfg,
        simulated=event.simulated, actor=actor, clock=now,
    )  # fmt: skip
    label_id = _set_label(
        conn, user_id, event_id, category_id, credit_kind,
        "user" if actor == "user" else "auto", False, to_utc_iso(now),
        linked=linked_event_id, rank_picked=rank_picked, note=note, split=split,
    )  # fmt: skip
    assert label is not None
    prompt = _prompt_row(conn, user_id, event_id)
    prompt_before = prompt["status"] if prompt else None
    if prompt:
        conn.execute(
            "UPDATE prompt_log SET status = 'answered', answered_at = ? WHERE id = ?",
            (to_utc_iso(now), prompt["id"]),
        )
    profile_before = get_profile(conn, user_id, event.counterparty_key)
    _remember_label(conn, user_id, event, label, to_utc_iso(now))
    override_before = _remember_merchant(conn, user_id, event, category_id, to_utc_iso(now))

    after = _label_state(get_event(conn, user_id, event_id))  # type: ignore[arg-type]
    record_event(
        conn,
        user_id=user_id,
        actor=actor,
        event_type="payment_labeled",
        reason=f"Payment labelled {label}",
        run_id=run_id,
        entity_type="payment_event",
        entity_id=event_id,
        before_data=before,
        after_data=after,
        metadata={
            "label_id": label_id,
            "rank_picked": rank_picked,
            "prompt_status_before": prompt_before,
            "profile_recent_before": profile_before.recent_categories if profile_before else [],
            "override_before": override_before,
            "learned": learned,
        },
        clock=now,
    )
    return get_event(conn, user_id, event_id)  # type: ignore[return-value]


def _remember_label(
    conn: sqlite3.Connection, user_id: str, event: PaymentEvent, label: str, now: str
) -> None:
    row = conn.execute(
        "SELECT recent_categories_json FROM counterparty_profiles"
        " WHERE user_id = ? AND counterparty_key = ?",
        (user_id, event.counterparty_key),
    ).fetchone()
    recent = json.loads(row[0]) if row else []
    recent = (recent + [label])[-10:]
    conn.execute(
        "UPDATE counterparty_profiles SET recent_categories_json = ?, updated_at = ?"
        " WHERE user_id = ? AND counterparty_key = ?",
        (json.dumps(recent), now, user_id, event.counterparty_key),
    )


def _remember_merchant(
    conn: sqlite3.Connection, user_id: str, event: PaymentEvent, category_id: str | None, now: str
) -> dict | None:
    """A merchant's answer becomes an override (never a person's: rent and dinner differ).
    Returns what was there before, so an undo can put it back."""
    if event.direction != "debit" or event.counterparty_kind not in ("merchant", "unknown"):
        return None
    if not category_id:
        return None
    name = normalise_name(event.display_name)
    if not name:
        return None
    prior = conn.execute(
        "SELECT id, category_id FROM merchant_overrides"
        " WHERE user_id = ? AND merchant_normalized = ?",
        (user_id, name),
    ).fetchone()
    conn.execute(
        "INSERT INTO merchant_overrides (id, user_id, merchant_normalized, category_id, created_by,"
        " created_at) VALUES (?, ?, ?, ?, 'user', ?)"
        " ON CONFLICT(user_id, merchant_normalized) DO UPDATE SET"
        " category_id = excluded.category_id,"
        " created_at = excluded.created_at",
        (str(uuid.uuid4()), user_id, name, category_id, now),
    )
    return {"merchant": name, "category_id": prior["category_id"] if prior else None}


# ---------------------------------------------------------------------------------------------
# Undo (called from the central `undo` tool)
# ---------------------------------------------------------------------------------------------
def undo_label(
    conn: sqlite3.Connection, user_id: str, event_id: str, before: dict, after: dict, meta: dict
) -> None:
    event = get_event(conn, user_id, event_id)
    if event is None:
        raise ToolFailure(ErrorCode.NOT_FOUND, f"Payment {event_id} not found.")
    if _label_state(event) != after:
        raise ToolFailure(
            ErrorCode.STALE_DATA, "Undo refused: the label changed after this action."
        )
    conn.execute(
        "UPDATE payment_events SET category_id = ?, credit_kind = ?, category_source = ?,"
        " needs_review = ? WHERE user_id = ? AND id = ?",
        (
            before["category_id"], before["credit_kind"], before["category_source"],
            int(before["needs_review"]), user_id, event_id,
        ),
    )  # fmt: skip
    if meta.get("label_id"):
        conn.execute(
            "DELETE FROM capture_labels WHERE user_id = ? AND id = ?", (user_id, meta["label_id"])
        )
    if meta.get("prompt_status_before"):
        conn.execute(
            "UPDATE prompt_log SET status = ?, answered_at = NULL"
            " WHERE user_id = ? AND event_id = ?",
            (meta["prompt_status_before"], user_id, event_id),
        )
    conn.execute(
        "UPDATE counterparty_profiles SET recent_categories_json = ?"
        " WHERE user_id = ? AND counterparty_key = ?",
        (json.dumps(meta.get("profile_recent_before") or []), user_id, event.counterparty_key),
    )
    if meta.get("learned"):
        unlearn(conn, user_id, meta["learned"])
    prior = meta.get("override_before")
    if prior:
        if prior["category_id"] is None:
            conn.execute(
                "DELETE FROM merchant_overrides WHERE user_id = ? AND merchant_normalized = ?",
                (user_id, prior["merchant"]),
            )
        else:
            conn.execute(
                "UPDATE merchant_overrides SET category_id = ?"
                " WHERE user_id = ? AND merchant_normalized = ?",
                (prior["category_id"], user_id, prior["merchant"]),
            )


# ---------------------------------------------------------------------------------------------
# Pending prompts, counterparty policy, and the time-to-live fallback
# ---------------------------------------------------------------------------------------------
def pending_prompts(conn: sqlite3.Connection, user_id: str, limit: int = 50) -> list[PromptView]:
    cats = _categories(conn, user_id)
    rows = conn.execute(
        "SELECT p.*, e.id AS eid FROM prompt_log p JOIN payment_events e ON e.id = p.event_id"
        " WHERE p.user_id = ? AND p.status = 'pending' ORDER BY p.created_at, p.id LIMIT ?",
        (user_id, limit),
    ).fetchall()
    out = []
    for r in rows:
        event = get_event(conn, user_id, r["event_id"])
        if event is None:
            continue
        guesses = []
        for g in json.loads(r["guesses_json"]):
            guesses.append(GuessView(**{**g, "name": _label_name(g["label"], cats)}))
        out.append(
            PromptView(
                prompt_id=r["id"],
                event=event,
                decision=r["decision"],
                reason=r["reason"],
                guesses=guesses,
                status=r["status"],
                created_at=r["created_at"],
                expires_at=r["expires_at"],
            )  # fmt: skip
        )
    return out


def recent_auto_tagged(conn: sqlite3.Connection, user_id: str, since: str) -> list[dict]:
    """Payments tagged without asking since `since`: the quiet 'Tagged Food. Change' chips."""
    cats = _categories(conn, user_id)
    rows = conn.execute(
        "SELECT p.id, p.reason, p.event_id FROM prompt_log p"
        " WHERE p.user_id = ? AND p.decision = 'auto_label' AND p.created_at >= ?"
        " ORDER BY p.created_at, p.id",
        (user_id, since),
    ).fetchall()
    out = []
    for r in rows:
        event = get_event(conn, user_id, r["event_id"])
        if event is None:
            continue
        label = event.category_id or event.credit_kind
        out.append(
            {
                "prompt_id": r["id"],
                "reason": r["reason"],
                "name": _label_name(label, cats) if label else "",
                "event": event.model_dump(mode="json"),
            }
        )
    return out


def set_counterparty_policy(
    conn: sqlite3.Connection,
    user_id: str,
    key: str,
    policy: str,
    category_id: str | None = None,
    *,
    actor: Actor = "user",
    run_id: str | None = None,
    clock: datetime | None = None,
) -> CounterpartyProfile:
    profile = get_profile(conn, user_id, key)
    if profile is None:
        raise ToolFailure(ErrorCode.NOT_FOUND, f"Counterparty {key!r} not found.")
    if policy == "always_category":
        if not category_id or category_id not in _categories(conn, user_id):
            raise ToolFailure(ErrorCode.INVALID_INPUT, "Pick one of your categories.")
    else:
        category_id = None
    now = now_utc(clock)
    conn.execute(
        "UPDATE counterparty_profiles SET policy = ?, policy_category_id = ?, updated_at = ?"
        " WHERE user_id = ? AND counterparty_key = ?",
        (policy, category_id, to_utc_iso(now), user_id, key),
    )
    record_event(
        conn, user_id=user_id, actor=actor, event_type="counterparty_policy_set",
        reason=f"Policy for {profile.display_name}: {policy}", run_id=run_id,
        entity_type="counterparty", entity_id=key,
        before_data={"policy": profile.policy, "category_id": profile.policy_category_id},
        after_data={"policy": policy, "category_id": category_id}, clock=now,
    )  # fmt: skip
    return get_profile(conn, user_id, key)  # type: ignore[return-value]


def expire_prompts(
    conn: sqlite3.Connection, user_id: str, clock: datetime | None = None, run_id: str | None = None
) -> int:
    """Past their time to live, unanswered prompts apply their best guess *as a guess*."""
    now = now_utc(clock)
    rows = conn.execute(
        "SELECT * FROM prompt_log WHERE user_id = ? AND status = 'pending' AND expires_at <= ?",
        (user_id, to_utc_iso(now)),
    ).fetchall()
    count = 0
    for r in rows:
        guesses = json.loads(r["guesses_json"])
        event = get_event(conn, user_id, r["event_id"])
        if event is None:
            continue
        if guesses and event.category_source != "user":
            top = guesses[0]["label"]
            _set_label(
                conn, user_id, event.id,
                top if event.direction == "debit" else None,
                top if event.direction == "credit" else None,
                "guess", True, to_utc_iso(now),
            )  # fmt: skip
        conn.execute("UPDATE prompt_log SET status = 'expired' WHERE id = ?", (r["id"],))
        record_event(
            conn, user_id=user_id, actor="system", event_type="prompt_expired",
            reason="Unanswered prompt applied its best guess as a guess", run_id=run_id,
            entity_type="payment_event", entity_id=event.id, clock=now,
        )  # fmt: skip
        count += 1
    return count


__all__ = [
    "RecordedEvent",
    "counterparty_key",
    "expire_prompts",
    "get_event",
    "get_profile",
    "label_payment_event",
    "pending_prompts",
    "record_payment_event",
    "set_counterparty_policy",
    "undo_label",
]
