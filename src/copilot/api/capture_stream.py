"""
The live prompt stream (PLAN_CAPTURE Stage C6): server-sent events over a token-authenticated
GET. A prompt is sent only when the ask policy said *ask*; payments held for the inbox, guessed,
or labelled automatically do not interrupt anyone (auto-labelled ones may appear as a quiet
"Tagged Food. Change" chip, if the user has that switched on).

Events:
  prompt       a payment waiting for an answer     (data: PromptView)
  resolved     that prompt was answered elsewhere  (data: {prompt_id, event_id})
  auto_tagged  a payment tagged without asking     (data: {prompt_id, event, name, reason})
  : keepalive  a comment line, so proxies keep the connection open

The stream reads the database on a short interval instead of keeping its own queue, so it
survives restarts and many tabs, and a reconnect simply re-announces what is still pending.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from datetime import timedelta

from fastapi import Request

from copilot.api.state import ApiState
from copilot.config.capture import load_capture_config
from copilot.core import capture as core
from copilot.core.timeutil import now_utc, to_utc_iso

KEEPALIVE_SECONDS = 15.0
AUTO_TAG_WINDOW_SECONDS = 20


def sse(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def capture_events(
    state: ApiState,
    request: Request | None = None,
    *,
    interval: float = 1.0,
    once: bool = False,
) -> AsyncIterator[str]:
    """Yield SSE frames until the client leaves. `once` sends the current state and stops."""
    show_chips = load_capture_config().prompts.show_silent_tag_chips
    announced: dict[str, str] = {}  # prompt_id -> event_id
    tagged: set[str] = set()
    last_beat = time.monotonic()
    first = True
    while True:
        conn = state.connect()
        try:
            pending = {
                p.prompt_id: p
                for p in core.pending_prompts(conn, state.user_id)
                if p.decision == "ask"
            }
            chips = (
                core.recent_auto_tagged(
                    conn,
                    state.user_id,
                    to_utc_iso(now_utc(state.clock) - timedelta(seconds=AUTO_TAG_WINDOW_SECONDS)),
                )
                if show_chips
                else []
            )
        finally:
            conn.close()
        for pid, prompt in pending.items():
            if pid not in announced:
                announced[pid] = prompt.event.id
                yield sse("prompt", prompt.model_dump(mode="json"))
        for pid in [p for p in announced if p not in pending]:
            yield sse("resolved", {"prompt_id": pid, "event_id": announced.pop(pid)})
        for chip in chips:
            if chip["prompt_id"] not in tagged:
                tagged.add(chip["prompt_id"])
                yield sse("auto_tagged", chip)
        if once:
            return
        if first or time.monotonic() - last_beat >= KEEPALIVE_SECONDS:
            yield ": keepalive\n\n"
            last_beat = time.monotonic()
            first = False
        if request is not None and await request.is_disconnected():
            return
        await asyncio.sleep(interval)
