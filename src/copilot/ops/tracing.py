"""
Observability and Tracing System (PLAN_PHASE3 Section 5.15).

Provides:
- Span API: `with span(kind, name, attrs=None):`
  Supported kinds: 'node', 'tool', 'llm', 'job', 'skill', 'specialist', 'mcp'
- Context propagation: manages trace_id and parent_span_id via contextvars
- Safety Rule 19: strictly forbids user text, merchant names, memory statements,
  or raw queries in span attributes
- Persistence to `trace_spans` SQLite table and JSONL export
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
import sqlite3
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal

from copilot.core.timeutil import now_utc, to_utc_iso
from copilot.db.repo_phase3 import insert_span, list_spans
from copilot.models.phase3 import Span

logger = logging.getLogger(__name__)

SpanKind = Literal["node", "tool", "llm", "job", "skill", "specialist", "mcp"]
VALID_SPAN_KINDS: set[str] = {
    "node",
    "tool",
    "llm",
    "job",
    "skill",
    "specialist",
    "mcp",
}

# Context variables for trace context propagation
_current_trace_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_current_trace_id", default=None
)
_current_parent_span_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_current_parent_span_id", default=None
)
_current_user_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_current_user_id", default=None
)
_current_conn: contextvars.ContextVar[sqlite3.Connection | None] = contextvars.ContextVar(
    "_current_conn", default=None
)
_span_collector: contextvars.ContextVar[list[Span] | None] = contextvars.ContextVar(
    "_span_collector", default=None
)

# Safety Rule 19: forbidden attribute keys
FORBIDDEN_ATTR_KEYS = {
    "user_text",
    "raw_text",
    "query",
    "prompt",
    "merchant",
    "merchant_name",
    "statement",
    "statement_text",
    "user_message",
    "memory_statement",
    "free_text",
}


def sanitize_and_validate_attrs(attrs: dict[str, Any] | None) -> dict[str, Any]:
    """
    Validate span attributes per Safety Rule 19:
    - Never user text, merchant names, memory statements, or raw prompts.
    - Only structural identifiers, counts, codes, durations, models, versions,
      and aggregate metrics.
    """
    if not attrs:
        return {}

    sanitized: dict[str, Any] = {}
    for k, v in attrs.items():
        k_lower = k.lower()
        if k_lower in FORBIDDEN_ATTR_KEYS:
            raise ValueError(
                f"Safety Rule 19 violation: Span attribute key '{k}' contains prohibited raw text."
            )
        # Check for free-form multi-word user strings in string values
        if isinstance(v, str) and len(v) > 120 and " " in v:
            # Check if it looks like arbitrary user prose rather than an ID, path, or code
            if not re.match(r"^[a-zA-Z0-9_\-\./:]+$", v):
                raise ValueError(
                    f"Safety Rule 19 violation: Span attr '{k}' contains raw user text."
                )

        sanitized[k] = v

    return sanitized


def get_current_trace_id() -> str | None:
    return _current_trace_id.get()


def get_current_span_id() -> str | None:
    return _current_parent_span_id.get()


@contextmanager
def trace_context(
    user_id: str,
    trace_id: str | None = None,
    conn: sqlite3.Connection | None = None,
    collector: list[Span] | None = None,
) -> Iterator[str]:
    """
    Establish a root tracing context with trace_id, user_id, and optional DB connection.
    """
    active_trace_id = trace_id or f"tr_{uuid.uuid4().hex[:16]}"
    token_trace = _current_trace_id.set(active_trace_id)
    token_user = _current_user_id.set(user_id)
    token_parent = _current_parent_span_id.set(None)
    token_conn = _current_conn.set(conn)
    token_coll = _span_collector.set(collector)

    try:
        yield active_trace_id
    finally:
        _current_trace_id.reset(token_trace)
        _current_user_id.reset(token_user)
        _current_parent_span_id.reset(token_parent)
        _current_conn.reset(token_conn)
        _span_collector.reset(token_coll)


@contextmanager
def span(
    kind: SpanKind,
    name: str,
    attrs: dict[str, Any] | None = None,
    user_id: str | None = None,
    trace_id: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> Iterator[Span]:
    """
    Tracing span context manager (PLAN_PHASE3 Section 5.15).

    Supports kinds: 'node', 'tool', 'llm', 'job', 'skill', 'specialist', 'mcp'.
    Propagates parent-child relationships and commits completed spans to DB.
    """
    if kind not in VALID_SPAN_KINDS:
        raise ValueError(
            f"Invalid span kind '{kind}'. Must be one of: {sorted(VALID_SPAN_KINDS)}"
        )

    clean_attrs = sanitize_and_validate_attrs(attrs)

    resolved_user_id = user_id or _current_user_id.get() or "system"
    resolved_trace_id = (
        trace_id or _current_trace_id.get() or f"tr_{uuid.uuid4().hex[:16]}"
    )
    parent_span_id = _current_parent_span_id.get()
    span_id = f"sp_{uuid.uuid4().hex[:16]}"
    span_db_id = f"span_{uuid.uuid4().hex[:16]}"
    active_conn = conn or _current_conn.get()

    t0 = time.perf_counter()
    start_dt = now_utc()
    start_iso = to_utc_iso(start_dt)

    # Set as active span in context
    token_parent = _current_parent_span_id.set(span_id)
    token_trace = _current_trace_id.set(resolved_trace_id)
    token_user = _current_user_id.set(resolved_user_id)

    status: Literal["ok", "error"] = "ok"
    error_code: str | None = None

    # Placeholder span object yieldable to caller
    active_span = Span(
        id=span_db_id,
        user_id=resolved_user_id,
        trace_id=resolved_trace_id,
        span_id=span_id,
        parent_span_id=parent_span_id,
        kind=kind,  # type: ignore[arg-type]
        name=name,
        started_at=start_iso,
        duration_ms=0,
        status="ok",
        error_code=None,
        attrs=clean_attrs,
        created_at=start_iso,
    )

    try:
        yield active_span
    except Exception as exc:
        status = "error"
        error_code = type(exc).__name__
        active_span.status = "error"
        active_span.error_code = error_code
        raise
    finally:
        duration_ms = max(0, int((time.perf_counter() - t0) * 1000))
        active_span.duration_ms = duration_ms
        active_span.status = status
        active_span.error_code = error_code

        # Reset contextvars
        _current_parent_span_id.reset(token_parent)
        _current_trace_id.reset(token_trace)
        _current_user_id.reset(token_user)

        # Collect in memory collector if active
        collector = _span_collector.get()
        if collector is not None:
            collector.append(active_span)

        # Persist to database if connection available
        if active_conn is not None:
            try:
                insert_span(active_conn, active_span)
            except Exception as e:
                logger.warning("Failed to insert trace span into database: %s", e)


def export_trace_spans_jsonl(
    conn: sqlite3.Connection,
    user_id: str,
    trace_id: str | None = None,
    output_path: str | Path | None = None,
) -> str:
    """
    Export trace spans as JSON Lines. Optionally writes to output_path.
    """
    spans = list_spans(conn, user_id=user_id, trace_id=trace_id, limit=10000)
    lines = [json.dumps(s.model_dump(mode="json")) for s in spans]
    content = "\n".join(lines)
    if lines:
        content += "\n"

    if output_path is not None:
        p = Path(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    return content


def build_span_tree(spans: list[Span]) -> list[dict[str, Any]]:
    """
    Reconstruct hierarchical tree of spans from flat list using span_id and parent_span_id.
    """
    span_map: dict[str, dict[str, Any]] = {}
    roots: list[dict[str, Any]] = []

    for s in spans:
        span_map[s.span_id] = {
            "span": s,
            "children": [],
        }

    for s in spans:
        node = span_map[s.span_id]
        if s.parent_span_id and s.parent_span_id in span_map:
            span_map[s.parent_span_id]["children"].append(node)
        else:
            roots.append(node)

    return roots
