"""Small helpers the route modules share."""

import sqlite3
from typing import Any

from copilot.api.errors import ApiError, ApiException, unwrap
from copilot.api.state import ApiState
from copilot.review.models import MonthlyReviewData
from copilot.tools.executor import execute_tool

MAX_CATEGORIES = 60


def call_tool(
    state: ApiState, conn: sqlite3.Connection, tool: str, args: dict, actor: str = "user"
) -> Any:
    """Run one tool through the governed executor, as the user unless told otherwise, and commit."""
    out = unwrap(execute_tool(state.context(conn, actor), tool, args))  # type: ignore[arg-type]
    conn.commit()
    return out


def dump_data(data: Any) -> Any:
    if hasattr(data, "model_dump"):
        return data.model_dump(mode="json")
    if isinstance(data, list):
        return [dump_data(x) for x in data]
    if isinstance(data, dict):
        return {k: dump_data(v) for k, v in data.items()}
    return data


def sms_fields(raw: bytes, content_type: str) -> tuple[str, str]:
    """(sender, text) from a JSON or form body, whatever the forwarder app calls the fields."""
    import json as _json
    from urllib.parse import parse_qs

    senders = ("sender", "from", "address", "originating_address", "number")
    texts = ("text", "message", "body", "sms", "content")
    data: dict[str, object] = {}
    try:
        if "json" in content_type or raw.lstrip().startswith(b"{"):
            loaded = _json.loads(raw.decode("utf-8", errors="replace"))
            data = loaded if isinstance(loaded, dict) else {}
        else:
            data = {k: v[0] for k, v in parse_qs(raw.decode("utf-8", errors="replace")).items()}
    except ValueError:
        return "", ""

    def first(keys: tuple[str, ...]) -> str:
        for k in keys:
            v = data.get(k)
            if isinstance(v, str) and v.strip():
                return v
        return ""

    return first(senders), first(texts)


def sms_shape(raw: bytes, content_type: str) -> str:
    """What a forwarder sent, with no values: the content type, the size and the field names."""
    import json as _json
    from urllib.parse import parse_qs

    names: list[str] = []
    try:
        if "json" in content_type or raw.lstrip().startswith(b"{"):
            loaded = _json.loads(raw.decode("utf-8", errors="replace"))
            names = [str(k) for k in loaded] if isinstance(loaded, dict) else []
        else:
            names = list(parse_qs(raw.decode("utf-8", errors="replace")))
    except ValueError:
        names = []
    kind = content_type.split(";")[0] or "none"
    return f"content type {kind}, {len(raw)} bytes, fields: {', '.join(names) or 'none'}"


def parse_period(period: str) -> tuple[int, int]:
    try:
        year, month = (int(p) for p in period.split("-"))
    except ValueError as exc:
        raise ApiException(
            422, ApiError(code="INVALID_INPUT", message="period must be YYYY-MM")
        ) from exc
    if not 1 <= month <= 12:
        raise ApiException(422, ApiError(code="INVALID_INPUT", message="month must be 01..12"))
    return year, month


def json_list(raw: str | None) -> list[Any]:
    import json

    if not raw:
        return []
    value = json.loads(raw)
    return value if isinstance(value, list) else [value]


def refresh_advice_status(conn: sqlite3.Connection, review: MonthlyReviewData) -> MonthlyReviewData:
    """Show only this period's advice, with each item's current decision status."""
    items = []
    for item in review.advice:
        row = conn.execute(
            "SELECT status, evidence_json FROM advice_items WHERE id = ?", (item.id,)
        ).fetchone()
        if row is None or f'"period": "{review.period}"' not in (row["evidence_json"] or ""):
            continue
        status = (
            row["status"] if row["status"] in ("draft", "approved", "rejected") else item.status
        )
        items.append(item.model_copy(update={"status": status}))
    return review.model_copy(update={"advice": items})
