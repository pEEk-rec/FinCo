"""
Router tests. A fake network and a virtual clock stand in for the providers, so rate limits,
failures and recovery are checked exactly and instantly, with no real API calls.
"""

import json
import logging
import threading
from collections import defaultdict

import pytest
from pydantic import BaseModel

from copilot.llm.routing import LLMRouter, LLMUnavailable, RouterConfig
from copilot.llm.routing.providers import HttpResponse, parse_response
from copilot.llm.routing.router import Clock, keys_from_env, read_env
from copilot.llm.routing.slots import fingerprint, parse_duration

GROQ_KEYS = [
    "gsk_test_key_one_aaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "gsk_test_key_two_bbbbbbbbbbbbbbbbbbbbbbbbbbbb",
]
GEM_KEYS = ["AQ.test_gem_one_cccccccccccccccccccc", "AQ.test_gem_two_dddddddddddddddddddd"]


class FakeClock(Clock):
    def __init__(self) -> None:
        self.t = 1000.0

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += max(0.0, seconds)


def config(
    *, rpm=10, tpm=None, rpd=None, deadline=500.0, safety=1.0, json_mode=True, max_wait=90.0
) -> RouterConfig:
    limits = {"rpm": rpm, "tpm": tpm, "rpd": rpd, "timeout_s": 10, "safety": safety}
    limits = {k: v for k, v in limits.items() if v is not None}
    task = {
        "max_tokens": 100,
        "deadline_s": deadline,
        "max_wait_s": max_wait,
        "json_mode": json_mode,
        "candidates": [
            {"provider": "groq", "model": "groq-big"},
            {"provider": "gemini", "model": "gem-fast"},
            {"provider": "groq", "model": "groq-small"},
        ],
    }
    return RouterConfig.model_validate(
        {
            "providers": {"groq": limits, "gemini": limits},
            "tasks": {
                "general": task,
                "planning": task,
                "narration": {
                    **task,
                    "candidates": [
                        {"provider": "gemini", "model": "gem-fast"},
                        {"provider": "groq", "model": "groq-big"},
                    ],
                },
            },
        }
    )


def groq_ok(text='{"a": 1}', tokens=50, remaining=None, reset="1s") -> HttpResponse:
    headers = {}
    if remaining is not None:
        headers = {
            "x-ratelimit-remaining-tokens": str(remaining),
            "x-ratelimit-reset-tokens": reset,
        }
    body = {
        "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
        "usage": {"total_tokens": tokens},
    }
    return HttpResponse(200, headers, json.dumps(body).encode())


def gem_ok(text='{"a": 1}') -> HttpResponse:
    body = {
        "candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}],
        "usageMetadata": {"totalTokenCount": 40},
    }
    return HttpResponse(200, {}, json.dumps(body).encode())


def err(status, headers=None, text="boom") -> HttpResponse:
    return HttpResponse(status, headers or {}, text.encode())


class FakeNet:
    """Scripted provider behaviour. `rules` is a list of callables (model, key, n) -> response."""

    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.calls: list[dict] = []
        self.rules: list = []
        self.counts: dict[tuple[str, str], int] = defaultdict(int)
        self.lock = threading.Lock()

    def __call__(self, url, headers, body, timeout):
        payload = json.loads(body)
        if "generativelanguage" in url:
            model, key, provider = (
                url.split("/models/")[1].split(":")[0],
                headers["x-goog-api-key"],
                "gemini",
            )
            prompt = payload["contents"][0]["parts"][0]["text"]
        else:
            model, key, provider = payload["model"], headers["Authorization"][7:], "groq"
            prompt = payload["messages"][-1]["content"]
        with self.lock:
            self.counts[(model, key)] += 1
            n = self.counts[(model, key)]
            self.calls.append(
                {
                    "t": self.clock.now(),
                    "model": model,
                    "key": key,
                    "provider": provider,
                    "prompt": prompt,
                    "payload": payload,
                    "headers": headers,
                }
            )
        for rule in self.rules:
            out = rule(model, key, n)
            if out is not None:
                if isinstance(out, Exception):
                    raise out
                return out
        return groq_ok() if provider == "groq" else gem_ok()


def make(cfg=None, groq=GROQ_KEYS, gem=GEM_KEYS):
    clock = FakeClock()
    net = FakeNet(clock)
    router = LLMRouter(cfg or config(), {"groq": list(groq), "gemini": list(gem)}, net, clock)
    return router, net, clock


# ---------------------------------------------------------------------------------------------
# Routing and rate limits
# ---------------------------------------------------------------------------------------------


def test_tasks_use_their_own_preferred_model():
    router, net, _ = make()
    router.complete("hi", purpose="planning")
    router.complete("hi", task="narration")
    assert [c["model"] for c in net.calls] == ["groq-big", "gem-fast"]


def test_complete_accepts_enum_like_purpose_and_unknown_tasks_fall_back_to_general():
    class P:
        value = "narration"

    router, net, _ = make()
    router.complete("x", purpose=P())
    router.complete("x", purpose="something_new")
    assert net.calls[0]["model"] == "gem-fast" and net.calls[1]["model"] == "groq-big"


def windows(calls, key, span=60.0):
    times = sorted(c["t"] for c in calls if c["key"] == key)
    return max((sum(1 for t in times if t0 <= t < t0 + span) for t0 in times), default=0)


def test_requests_per_minute_are_never_exceeded_on_any_key():
    router, net, _ = make(config(rpm=4))
    for _ in range(60):
        router.complete("go", task="general")
    for key in GROQ_KEYS + GEM_KEYS:
        assert windows(net.calls, key) <= 4, key
    assert len(net.calls) == 60
    assert not any(
        t["rate_limited"] for t in [router.snapshot()["totals"]]
    )  # the provider never had to say 429


def test_tokens_per_minute_are_never_exceeded():
    router, net, _ = make(config(rpm=100, tpm=600), gem=[])
    net.rules.append(lambda model, key, n: groq_ok(tokens=250))  # each call really uses 250 tokens
    for _ in range(12):
        router.complete("p" * 400, task="general")
    assert len(net.calls) == 12
    for key in GROQ_KEYS:
        stamps = sorted(c["t"] for c in net.calls if c["key"] == key)
        for t0 in stamps:
            in_window = sum(1 for t in stamps if t0 <= t < t0 + 60)
            assert in_window * 250 <= 600, (key, in_window)  # at most two 250-token calls a minute


def test_a_single_call_bigger_than_the_minute_budget_is_refused_not_sent():
    router, net, _ = make(config(rpm=100, tpm=100), gem=[])
    with pytest.raises(LLMUnavailable):
        router.complete("x" * 4000, task="general")
    assert net.calls == []


def test_daily_budget_is_enforced_per_key():
    router, net, _ = make(config(rpm=100, rpd=3, deadline=5.0), groq=GROQ_KEYS[:1], gem=[])
    for _ in range(3):
        router.complete("x", task="general")
    with pytest.raises(LLMUnavailable):
        router.complete("x", task="general")
    assert len(net.calls) == 3


def test_load_spreads_across_keys():
    router, net, _ = make(config(rpm=50), gem=[])
    for _ in range(20):
        router.complete("x", task="general")
    used = defaultdict(int)
    for c in net.calls:
        used[c["key"]] += 1
    assert set(used) == set(GROQ_KEYS) and min(used.values()) >= 8


# ---------------------------------------------------------------------------------------------
# Failure handling and learning
# ---------------------------------------------------------------------------------------------


def test_rate_limited_key_rests_for_exactly_what_the_provider_asked():
    router, net, clock = make(config(rpm=100), gem=[])
    net.rules.append(
        lambda model, key, n: (
            err(429, {"retry-after": "30"}) if key == GROQ_KEYS[0] and n == 1 else None
        )
    )
    router.complete("x", task="general")  # first key says 429, second serves it
    assert [c["key"] for c in net.calls][-1] == GROQ_KEYS[1]
    first_429_at = net.calls[0]["t"]
    for _ in range(5):
        router.complete("x", task="general")
    used_first_key_early = [
        c for c in net.calls[1:] if c["key"] == GROQ_KEYS[0] and c["t"] < first_429_at + 30
    ]
    assert used_first_key_early == []
    clock.t += 31
    for _ in range(4):
        router.complete("x", task="general")
    assert any(c["key"] == GROQ_KEYS[0] for c in net.calls[1:])  # back in rotation
    assert router.snapshot()["totals"]["rate_limited"] == 1


def test_rejected_key_is_retired_and_never_used_again():
    router, net, _ = make(config(rpm=100), gem=[])
    net.rules.append(lambda model, key, n: err(401) if key == GROQ_KEYS[0] else None)
    for _ in range(6):
        router.complete("x", task="general")
    assert sum(1 for c in net.calls if c["key"] == GROQ_KEYS[0]) == 1
    snap = router.snapshot()
    assert snap["totals"]["keys_rejected"] == 1
    assert {k["id"]: k["state"] for k in snap["providers"]["groq"]["keys"]}[
        fingerprint(GROQ_KEYS[0])
    ] == "rejected"


def test_retired_model_is_dropped_and_the_next_one_serves():
    router, net, _ = make()
    net.rules.append(lambda model, key, n: err(404) if model == "groq-big" else None)
    for _ in range(4):
        router.complete("x", task="general")
    assert (
        sum(1 for c in net.calls if c["model"] == "groq-big") == 1
    )  # tried once, then never again
    assert {m["model"]: m["state"] for m in router.snapshot()["models"]}["groq-big"] == "paused"


def test_overloaded_model_backs_off_and_the_ranking_learns():
    router, net, clock = make()
    net.rules.append(lambda model, key, n: err(503) if model == "groq-big" else None)
    for _ in range(6):
        router.complete("x", task="general")
    big_calls = [c for c in net.calls if c["model"] == "groq-big"]
    assert 1 <= len(big_calls) <= 3  # stops being tried first
    net.rules.clear()
    clock.t += 600  # backoff over: it recovers and is used again
    for _ in range(8):
        router.complete("x", task="general")
    assert any(c["model"] == "groq-big" and c["t"] > 1500 for c in net.calls)


def test_timeout_fails_over_within_the_deadline():
    router, net, _ = make()
    net.rules.append(lambda model, key, n: TimeoutError("slow") if model == "groq-big" else None)
    result = router.route("general", "x")
    assert result.model == "gem-fast"
    assert [a.outcome for a in result.attempts] == ["timeout", "ok"]


def test_invalid_reply_escalates_to_another_model_with_the_reason_attached():
    router, net, _ = make()
    net.rules.append(
        lambda model, key, n: groq_ok("not json at all") if model == "groq-big" else None
    )

    class Plan(BaseModel):
        a: int

    value, result = router.structured("planning", "make a plan", Plan)
    assert value.a == 1
    assert result.model == "gem-fast" and result.escalations == 1
    retry_prompt = [c["prompt"] for c in net.calls if c["model"] == "gem-fast"][0]
    assert "previous reply was rejected" in retry_prompt and "make a plan" in retry_prompt


def test_truncated_reply_is_not_accepted():
    router, net, _ = make()
    body = {"choices": [{"message": {"content": '{"a":'}, "finish_reason": "length"}]}
    net.rules.append(
        lambda model, key, n: (
            HttpResponse(200, {}, json.dumps(body).encode()) if model == "groq-big" else None
        )
    )
    assert router.route("general", "x").model == "gem-fast"


def test_provider_remaining_token_report_is_followed():
    router, net, clock = make(config(rpm=100), groq=GROQ_KEYS[:1], gem=[])
    net.rules.append(lambda model, key, n: groq_ok(remaining=50, reset="20s") if n == 1 else None)
    router.complete("x", task="general")
    t_first = clock.t
    router.complete("x", task="general")
    assert clock.t - t_first >= 20  # waited for the provider's own reset, did not guess


def test_everything_failing_raises_a_typed_error_quickly():
    router, net, clock = make(config(deadline=10.0))
    net.rules.append(lambda model, key, n: err(503))
    started = clock.t
    with pytest.raises(LLMUnavailable) as info:
        router.complete("x", task="general")
    assert info.value.error.retryable is True
    assert clock.t - started <= 10.0


def test_waiting_longer_than_the_deadline_gives_up_instead_of_sleeping():
    router, net, clock = make(config(rpm=1, deadline=5.0), groq=GROQ_KEYS[:1], gem=[])
    router.complete("x", task="general")
    started = clock.t
    with pytest.raises(LLMUnavailable):
        router.complete("x", task="general")
    assert clock.t - started < 5.0


# ---------------------------------------------------------------------------------------------
# Safety and plumbing
# ---------------------------------------------------------------------------------------------


def test_keys_never_appear_in_snapshots_or_logs(caplog):
    router, net, _ = make()
    net.rules.append(lambda model, key, n: err(401) if key == GROQ_KEYS[0] else None)
    with caplog.at_level(logging.DEBUG):
        for _ in range(4):
            router.complete("x", task="general")
    blob = json.dumps(router.snapshot()) + caplog.text
    for key in GROQ_KEYS + GEM_KEYS:
        assert key not in blob and key[:12] not in blob


def test_json_mode_is_requested_per_provider():
    router, net, _ = make()
    router.route("general", "x")
    router.route("narration", "x")
    groq = next(c for c in net.calls if c["provider"] == "groq")["payload"]
    gem = next(c for c in net.calls if c["provider"] == "gemini")["payload"]
    assert groq["response_format"] == {"type": "json_object"}
    assert gem["generationConfig"]["responseMimeType"] == "application/json"


def test_concurrent_callers_cannot_overspend_a_key():
    router = LLMRouter(
        config(rpm=5, deadline=3.0), {"groq": GROQ_KEYS, "gemini": []}, FakeNet(Clock())
    )
    net: FakeNet = router.transport  # type: ignore[assignment]
    net.clock = router.clock
    outcomes = []

    def worker():
        try:
            router.complete("x", task="general")
            outcomes.append("ok")
        except LLMUnavailable:
            outcomes.append("unavailable")

    threads = [threading.Thread(target=worker) for _ in range(16)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert outcomes.count("ok") == 10  # two keys x five per minute, no more
    per_key = defaultdict(int)
    for c in net.calls:
        per_key[c["key"]] += 1
    assert max(per_key.values()) <= 5


def test_snapshot_reports_per_task_activity():
    router, _, _ = make()
    router.complete("x", task="planning")
    router.complete("x", task="narration")
    snap = router.snapshot()
    assert snap["tasks"]["planning"]["ok"] == 1 and snap["tasks"]["narration"]["ok"] == 1
    assert snap["routes"]["planning"][0] == "groq:groq-big"


def test_parse_duration_forms():
    assert parse_duration("1m26.4s") == pytest.approx(86.4)
    assert parse_duration("2.76s") == pytest.approx(2.76)
    assert parse_duration("350ms") == pytest.approx(0.35)
    assert parse_duration("30") == 30.0
    assert parse_duration("soon") is None and parse_duration(None) is None


def test_keys_from_env_dedupes_and_reads_legacy_names():
    env = {
        "GEMINI_API_KEYS": "a,b, c ",
        "GEMINI_API_KEY": "a",
        "GEMINI_KEY_PLANNER": "d",
        "GROQ_API_KEYS": "x,y",
        "GROQ_API_KEY": "x",
    }
    assert keys_from_env(env) == {"groq": ["x", "y"], "gemini": ["a", "b", "c", "d"]}


def test_env_file_is_parsed(tmp_path, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEYS", raising=False)
    path = tmp_path / ".env"
    path.write_text("# comment\nGROQ_API_KEYS=k1,k2\nGEMINI_API_KEY='g1'\n", encoding="utf-8")
    assert keys_from_env(read_env(path)) == {"groq": ["k1", "k2"], "gemini": ["g1"]}


def test_provider_reply_parsing_rejects_empty_and_blocked():
    from copilot.llm.routing.config import Candidate
    from copilot.llm.routing.providers import CallError

    cand = Candidate(provider="gemini", model="m")
    blocked = HttpResponse(
        200, {}, json.dumps({"candidates": [{"finishReason": "SAFETY"}]}).encode()
    )
    with pytest.raises(CallError) as info:
        parse_response(cand, blocked)
    assert info.value.kind == "blocked"
    with pytest.raises(CallError):
        parse_response(cand, HttpResponse(200, {}, b"{}"))
