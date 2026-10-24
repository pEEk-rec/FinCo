"""
Record the model's reading of a fixed set of questions into a cassette (PLAN_PHASE4 section 0.8.6).

    python scripts/record_intent_cassette.py                        # first set: about 25 calls
    python scripts/record_intent_cassette.py --offset 4 --name fresh   # an untouched second set

The questions are the first four held-out phrasings of each Phase 4 intent plus five questions
that belong to other intents. The model's raw replies are saved in
tests/cassettes/phase4_intents.json, and `copilot eval --phase 4` replays them offline, so the
same live check is never paid for twice. Questions are synthetic; no key or personal data is
stored. The run stops at LIVE_MAX_CALLS (default 25) or at the first quota error.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

os.environ.setdefault("FINCO_LLM_PRIMARY", "1")

from copilot.api.llm import build_llm  # noqa: E402
from copilot.core.intent import create_agent_task  # noqa: E402
from copilot.eval.harness_phase4 import PHASE4_INTENTS, _new_db  # noqa: E402

CASSETTE = ROOT / "tests" / "cassettes" / "phase4_intents.json"
PER_INTENT = 4
NEGATIVES = 5


class Recorder:
    """Passes calls to the real client and keeps what it answered, in order, per question."""

    def __init__(self, inner, limit: int) -> None:
        self.inner = inner
        self.limit = limit
        self.calls = 0
        self.replies: list[str] = []

    def complete(self, prompt: str, **options) -> str:
        if self.calls >= self.limit:
            raise RuntimeError("live call cap reached")
        self.calls += 1
        reply = self.inner.complete(prompt, **options)
        self.replies.append(reply)
        return reply


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--offset", type=int, default=0, help="skip this many per intent")
    parser.add_argument("--name", default="", help="cassette name suffix")
    args = parser.parse_args()
    cassette_path = (
        CASSETTE.with_name(f"phase4_intents_{args.name}.json") if args.name else CASSETTE
    )
    data = json.loads((ROOT / "eval" / "data" / "phase4_intents.json").read_text("utf-8"))
    lo, hi = args.offset, args.offset + PER_INTENT
    questions = [(i, q) for i in PHASE4_INTENTS for q in data["held_out"][i][lo:hi]]
    questions += [("negative", q) for q in data["negatives"][args.offset : args.offset + NEGATIVES]]
    llm = build_llm()
    if llm is None:
        print("No model is configured (keys missing, or FINCO_LLM=off). Nothing recorded.")
        return 1
    limit = int(os.environ.get("LIVE_MAX_CALLS", "25"))
    recorder = Recorder(llm, limit)
    conn = _new_db()
    cassette: dict[str, dict] = {}
    for expected, text in questions:
        before = len(recorder.replies)
        try:
            task = create_agent_task(conn, "u_eval", text, llm_client=recorder)
        except Exception as exc:  # noqa: BLE001 - a failed question is recorded, the run goes on
            print(f"failed on {text!r}: {type(exc).__name__}: {exc}")
            continue
        cassette[text] = {
            "expected": expected,
            "replies": recorder.replies[before:],
            "got": task.intent.type if task.intent else None,
            "source": task.intent.source if task.intent else None,
        }
        print(f"{expected:>22} -> {cassette[text]['got']}")
    cassette_path.parent.mkdir(parents=True, exist_ok=True)
    cassette_path.write_text(json.dumps(cassette, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{len(cassette)} questions, {recorder.calls} live calls -> {cassette_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
