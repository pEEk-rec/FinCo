# ruff: noqa: E501  (SQL and prose lines)
"""
The values profile (PLAN_AGENTIC_V2, A8): what matters to this person, in a fixed, typed shape.

Two sources, always labelled. **Stated** values are what the user said and confirmed. **Inferred**
values are suggestions read from their own money (when income arrives, which payments are fixed);
they are stored unconfirmed and nothing uses them until the user confirms. There is no field for
anything sensitive (religion, caste, health, politics, sexuality, family status) and the schema
refuses unknown fields, so one cannot be added by accident. Everything is editable and deletable.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, TypeAdapter, ValidationError

from copilot.audit.events import Actor, record_event
from copilot.common.errors import ErrorCode, ToolFailure
from copilot.common.timeutil import now_utc, to_utc_iso

Provenance = Literal["stated", "inferred"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FixedCommitment(_Strict):
    name: str = Field(min_length=1, max_length=60)
    category_id: str
    amount_paise: StrictInt = Field(gt=0)
    day_of_month: int = Field(ge=1, le=28)


class Income(_Strict):
    kind: Literal["monthly", "irregular", "none"]
    expected_paise: StrictInt = Field(ge=0)
    day_of_month: int | None = Field(default=None, ge=1, le=28)


Priorities = Annotated[list[str], Field(max_length=12)]

#: field name -> the type its value must have. This is the whole profile; nothing else is stored.
FIELDS: dict[str, Any] = {
    "priorities": Priorities,  # category ids, most important first
    "fixed_commitments": list[FixedCommitment],
    "income": Income,
    "savings_intent_paise": Annotated[StrictInt, Field(ge=0)],
    "nudge_style": Literal["gentle", "direct", "numbers"],
    "checkin_weekday": Annotated[int, Field(ge=0, le=6)],
    "language": Literal["en", "hinglish"],
}
_ADAPTERS = {k: TypeAdapter(v) for k, v in FIELDS.items()}

#: words that must never appear in a profile field name (checked by a test and at import).
FORBIDDEN_WORDS = (
    "religion", "caste", "health", "politic", "sexual", "orientation", "ethnic", "race",
    "marital", "family", "children", "disability", "gender", "age",
)  # fmt: skip
assert not any(t.startswith(w) for f in FIELDS for t in f.split("_") for w in FORBIDDEN_WORDS), (
    "a profile field names something sensitive"
)

INTERVIEW = [
    ("income", "How does your money usually arrive?"),
    ("fixed_commitments", "Which payments are fixed every month (rent, fees, loans)?"),
    ("savings_intent_paise", "How much would you like to set aside each month?"),
    ("priorities", "Which spending matters most to you, most important first?"),
    ("nudge_style", "How should I talk to you: gently, directly, or just the numbers?"),
    ("checkin_weekday", "Which day suits a weekly check-in?"),
]


def validate(field: str, value: Any) -> Any:
    if field not in FIELDS:
        raise ToolFailure(ErrorCode.INVALID_INPUT, f"There is no profile field called {field!r}.")
    try:
        parsed = _ADAPTERS[field].validate_python(value)
    except ValidationError as exc:
        raise ToolFailure(
            ErrorCode.INVALID_INPUT, f"That is not a valid {field}: {exc.errors()[0]['msg']}"
        ) from exc
    return _ADAPTERS[field].dump_python(parsed, mode="json")


def _row(conn: sqlite3.Connection, user_id: str, field: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM user_profile WHERE user_id = ? AND field = ?", (user_id, field)
    ).fetchone()


def set_field(
    conn: sqlite3.Connection,
    user_id: str,
    field: str,
    value: Any,
    *,
    provenance: Provenance = "stated",
    actor: Actor = "user",
    evidence: dict | None = None,
    run_id: str | None = None,
    clock: datetime | None = None,
) -> dict:
    """Set one field. A stated value is confirmed by the act of saying it; an inferred one is not."""
    if provenance == "stated" and actor != "user":
        raise ToolFailure(ErrorCode.INVALID_INPUT, "Only you can state a value for your profile.")
    clean = validate(field, value)
    existing = _row(conn, user_id, field)
    if (
        existing
        and existing["provenance"] == "stated"
        and existing["confirmed"]
        and provenance == "inferred"
    ):
        return {"field": field, "kept": "stated"}  # a suggestion never replaces what you said
    now = to_utc_iso(now_utc(clock))
    confirmed = int(provenance == "stated")
    conn.execute(
        "INSERT INTO user_profile (id, user_id, field, value_json, provenance, confirmed, evidence_json, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(user_id, field) DO UPDATE SET value_json = excluded.value_json,"
        " provenance = excluded.provenance, confirmed = excluded.confirmed,"
        " evidence_json = excluded.evidence_json, updated_at = excluded.updated_at",
        (f"prf_{uuid.uuid4().hex[:12]}", user_id, field, json.dumps(clean), provenance, confirmed,
         json.dumps(evidence or {}), now),
    )  # fmt: skip
    record_event(
        conn, user_id=user_id, actor=actor, event_type="profile_set",
        reason=f"Profile field {field} set ({provenance})", run_id=run_id,
        entity_type="profile", entity_id=field,
        before_data={"value": json.loads(existing["value_json"])} if existing else None,
        after_data={"value": clean, "provenance": provenance, "confirmed": bool(confirmed)},
        clock=clock,
    )  # fmt: skip
    return {"field": field, "provenance": provenance, "confirmed": bool(confirmed)}


def confirm_field(
    conn: sqlite3.Connection,
    user_id: str,
    field: str,
    *,
    actor: Actor = "user",
    clock: datetime | None = None,
) -> dict:
    """The user accepts an inferred suggestion. It becomes stated."""
    if actor != "user":
        raise ToolFailure(ErrorCode.INVALID_INPUT, "Only you can confirm a suggestion.")
    row = _row(conn, user_id, field)
    if row is None:
        raise ToolFailure(ErrorCode.NOT_FOUND, f"Nothing to confirm for {field}.")
    conn.execute(
        "UPDATE user_profile SET confirmed = 1, provenance = 'stated', updated_at = ? WHERE user_id = ? AND field = ?",
        (to_utc_iso(now_utc(clock)), user_id, field),
    )
    record_event(
        conn, user_id=user_id, actor=actor, event_type="profile_confirmed",
        reason=f"Suggestion for {field} confirmed", entity_type="profile", entity_id=field, clock=clock,
    )  # fmt: skip
    return {"field": field, "confirmed": True}


def delete_field(
    conn: sqlite3.Connection,
    user_id: str,
    field: str,
    *,
    actor: Actor = "user",
    clock: datetime | None = None,
) -> int:
    """Remove a field and the evidence kept for it."""
    if actor != "user":
        raise ToolFailure(ErrorCode.INVALID_INPUT, "Only you can remove a part of your profile.")
    n = conn.execute(
        "DELETE FROM user_profile WHERE user_id = ? AND field = ?", (user_id, field)
    ).rowcount
    if n:
        record_event(
            conn, user_id=user_id, actor=actor, event_type="profile_deleted",
            reason=f"Profile field {field} removed", entity_type="profile", entity_id=field, clock=clock,
        )  # fmt: skip
    return n


class ProfileView(BaseModel):
    values: dict[str, Any]  # confirmed values only: what the system may use
    suggestions: dict[str, Any]  # inferred and not yet confirmed
    missing: list[str]


def get_profile(conn: sqlite3.Connection, user_id: str) -> ProfileView:
    values: dict[str, Any] = {}
    suggestions: dict[str, Any] = {}
    for r in conn.execute("SELECT * FROM user_profile WHERE user_id = ?", (user_id,)):
        (values if r["confirmed"] else suggestions)[r["field"]] = json.loads(r["value_json"])
    return ProfileView(
        values=values, suggestions=suggestions, missing=[f for f in FIELDS if f not in values]
    )


def confirmed(conn: sqlite3.Connection, user_id: str, field: str, default: Any = None) -> Any:
    """What the rest of the system may rely on: a confirmed value, else the default."""
    return get_profile(conn, user_id).values.get(field, default)


# ---- inferring from the user's own money -----------------------------------------------------------
def infer_suggestions(conn: sqlite3.Connection, user_id: str) -> dict[str, dict]:
    """Suggestions from the ledger: when income arrives and which payments are fixed. Not stored."""
    out: dict[str, dict] = {}
    income = conn.execute(
        "SELECT merchant_normalized, typical_amount_paise, next_expected FROM recurring_series"
        " WHERE user_id = ? AND kind = 'income' ORDER BY typical_amount_paise DESC LIMIT 1",
        (user_id,),
    ).fetchone()
    if income:
        out["income"] = {
            "value": {"kind": "monthly", "expected_paise": income["typical_amount_paise"],
                      "day_of_month": min(28, int(income["next_expected"][8:10]))},
            "evidence": {"from": "a regular credit", "name": income["merchant_normalized"]},
        }  # fmt: skip
    fixed = []
    for r in conn.execute(
        "SELECT s.merchant_normalized, s.typical_amount_paise, s.next_expected, t.category_id FROM recurring_series s"
        " LEFT JOIN transactions t ON t.user_id = s.user_id AND t.merchant_normalized = s.merchant_normalized"
        " AND t.category_id IS NOT NULL WHERE s.user_id = ? AND s.kind = 'bill' AND s.cadence_days BETWEEN 26 AND 35"
        " GROUP BY s.id LIMIT 8",
        (user_id,),
    ):
        if r["category_id"]:
            fixed.append({"name": r["merchant_normalized"][:60], "category_id": r["category_id"],
                          "amount_paise": r["typical_amount_paise"],
                          "day_of_month": min(28, int(r["next_expected"][8:10]))})  # fmt: skip
    if fixed:
        out["fixed_commitments"] = {
            "value": fixed,
            "evidence": {"from": "payments that repeat monthly"},
        }
    return out


def store_inferred(
    conn: sqlite3.Connection, user_id: str, clock: datetime | None = None
) -> list[str]:
    """Save suggestions as unconfirmed, for the user to confirm or ignore."""
    stored = []
    for field, s in infer_suggestions(conn, user_id).items():
        res = set_field(conn, user_id, field, s["value"], provenance="inferred", actor="system",
                        evidence=s["evidence"], clock=clock)  # fmt: skip
        if "kept" not in res:
            stored.append(field)
    return stored
