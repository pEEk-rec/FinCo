"""
The live Ask stream: server-sent events over a token-authenticated POST.

A POST (not the usual GET) because the question travels in the body, never in a URL or a log line.
The agent runs on its own thread with its own database connection (SQLite connections must not
hop between the threads a web server uses), and a queue hands each event to the response as soon
as the agent produces it.

Events:
  step    one thing the agent did   (data: stage, title, detail, ms, and for a tool: tool, ok, data)
  result  the finished run          (data: the same shape `POST /api/ask` returns)
  error   the run could not finish  (data: message)
  : keepalive  a comment line while a slow step (a model call) is running
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import AsyncIterator

from copilot.api.agent import ask_events
from copilot.api.capture_stream import sse
from copilot.api.contracts import AskOut
from copilot.api.state import ApiState

log = logging.getLogger("copilot.api.ask_stream")

KEEPALIVE_SECONDS = 10.0
_DONE = object()


async def ask_stream(state: ApiState, text: str, use_llm: bool = True) -> AsyncIterator[str]:
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[object] = asyncio.Queue()

    def put(item: object) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, item)

    def work() -> None:
        conn = state.connect()
        try:
            for kind, data in ask_events(state, conn, text, use_llm):
                if kind == "result":
                    data = AskOut.model_validate(data).model_dump(mode="json")
                put((kind, data))
        except Exception:  # noqa: BLE001 - say so plainly; the details go to the log, not the page
            log.exception("The streamed ask failed")
            put(("error", {"message": "The agent could not finish this question. Try again."}))
        finally:
            conn.close()
            put(_DONE)

    threading.Thread(target=work, name="ask-stream", daemon=True).start()
    while True:
        try:
            item = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_SECONDS)
        except TimeoutError:
            yield ": keepalive\n\n"
            continue
        if item is _DONE:
            return
        kind, data = item  # type: ignore[misc]
        yield sse(kind, data)
