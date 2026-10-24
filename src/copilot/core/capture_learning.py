"""
Learning from labels (PLAN_CAPTURE Stage C8).

Each time the user labels a payment, every ranking signal that had a view is asked: would you
have put this label first? Its answer is one Beta update in the Phase 3 learner
(`feedback_stats`, subject kind `capture_signal`). The effective weight of a signal is its
configured weight times the learner's clamped multiplier, renormalised to 10000 basis points, so
no signal can be switched off or take over: the multiplier bounds are the same as everywhere else
(`config/learning.yaml`), and the ranking stays deterministic and explainable.

What does not learn:
  * simulated events, unless `learn_from_simulated` is switched on for a demo;
  * anything the user did not choose themselves (an automatic label teaches nothing);
  * a person's policy: that moves only by the k-of-n rule or an explicit choice (capture core).

An undo of the label takes its updates back, so a mis-tap does not leave a lesson behind.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

from copilot.audit.events import Actor, record_event
from copilot.config.capture import CaptureConfig, RankingWeights
from copilot.config.phase3 import LearningConfig, load_learning_config
from copilot.core.capture_logic import HistoryRow, signal_votes
from copilot.core.learning import (
    compute_posterior_mean,
    compute_sensitivity_multiplier,
    get_learned_multiplier,
)
from copilot.core.timeutil import now_utc, to_utc_iso
from copilot.db.repo_phase3 import get_feedback_stat, upsert_feedback_stat

KIND = "capture_signal"
SIGNALS = (
    "counterparty_history",
    "time_pattern",
    "amount_band",
    "day_of_month",
    "merchant_hint",
    "recency",
)
_TOTAL = 10000


def _normalise(raw: dict[str, float]) -> dict[str, int]:
    """Scale to exactly 10000 by the largest remainder, so the weights stay a clean partition."""
    total = sum(raw.values())
    scaled = {k: v * _TOTAL / total for k, v in raw.items()}
    out = {k: int(v) for k, v in scaled.items()}
    left = _TOTAL - sum(out.values())
    for k in sorted(scaled, key=lambda k: (-(scaled[k] - out[k]), k))[:left]:
        out[k] += 1
    return out


def effective_weights(
    conn: sqlite3.Connection,
    user_id: str,
    cfg: CaptureConfig,
    learning: LearningConfig | None = None,
) -> RankingWeights:
    learning = learning or load_learning_config()
    base = cfg.ranking.weights.model_dump()
    raw = {
        s: base[s] * get_learned_multiplier(conn, user_id, KIND, s, learning)[0] for s in SIGNALS
    }
    return RankingWeights(**_normalise(raw))


def with_learned_weights(
    conn: sqlite3.Connection, user_id: str, cfg: CaptureConfig
) -> CaptureConfig:
    """The capture config with this user's learned ranking weights."""
    weights = effective_weights(conn, user_id, cfg)
    return cfg.model_copy(update={"ranking": cfg.ranking.model_copy(update={"weights": weights})})


def _bump(
    conn: sqlite3.Connection,
    user_id: str,
    signal: str,
    which: str,
    sign: int,
    now: str,
    learning: LearningConfig,
) -> None:
    stat = get_feedback_stat(conn, user_id, KIND, signal)
    alpha = stat.alpha_milli if stat else learning.prior_alpha * 1000
    beta = stat.beta_milli if stat else learning.prior_beta * 1000
    if which == "useful":
        alpha = max(1, alpha + sign * 1000)
    else:
        beta = max(1, beta + sign * 1000)
    upsert_feedback_stat(conn, user_id, KIND, signal, alpha, beta, now)


def learn_from_label(
    conn: sqlite3.Connection,
    user_id: str,
    *,
    counterparty: str,
    direction: str,
    amount_paise: int,
    when: datetime,
    label: str,
    history: list[HistoryRow],
    cfg: CaptureConfig,
    simulated: bool,
    actor: Actor,
    clock: datetime | None = None,
) -> dict[str, str]:
    """Update the signals' posteriors from one user label. Returns what changed (for undo)."""
    if actor != "user" or (simulated and not cfg.learn_from_simulated):
        return {}
    votes = signal_votes(
        counterparty=counterparty,
        direction=direction,  # type: ignore[arg-type]
        amount_paise=amount_paise,
        when=when,
        history=history,
        cfg=cfg,
        hint_label=None,  # the hint is not stored, so that signal cannot be replayed here
    )
    learning = load_learning_config()
    now = to_utc_iso(now_utc(clock))
    learned = {s: ("useful" if top == label else "not_useful") for s, top in votes.items()}
    for signal, which in learned.items():
        _bump(conn, user_id, signal, which, 1, now, learning)
    if learned:
        record_event(
            conn, user_id=user_id, actor=actor, event_type="capture_learning_updated",
            reason="Ranking signals learned from the label you chose",
            entity_type="feedback_stat", entity_id=KIND, metadata={"signals": learned}, clock=clock,
        )  # fmt: skip
    return learned


def unlearn(
    conn: sqlite3.Connection, user_id: str, learned: dict[str, str], clock: datetime | None = None
) -> None:
    learning = load_learning_config()
    now = to_utc_iso(now_utc(clock))
    for signal, which in learned.items():
        _bump(conn, user_id, signal, which, -1, now, learning)


def summary(conn: sqlite3.Connection, user_id: str, cfg: CaptureConfig) -> list[dict[str, Any]]:
    """Base against effective weight per signal, for `copilot learning show`."""
    learning = load_learning_config()
    base = cfg.ranking.weights.model_dump()
    eff = effective_weights(conn, user_id, cfg, learning).model_dump()
    rows = []
    for s in SIGNALS:
        stat = get_feedback_stat(conn, user_id, KIND, s)
        a = stat.alpha_milli if stat else learning.prior_alpha * 1000
        b = stat.beta_milli if stat else learning.prior_beta * 1000
        p = compute_posterior_mean(a, b)
        rows.append(
            {
                "signal": s,
                "base_bp": base[s],
                "effective_bp": eff[s],
                "multiplier": compute_sensitivity_multiplier(p, learning),
                "p": round(p, 4),
                "evidence": (a + b) // 1000 - learning.prior_alpha - learning.prior_beta,
            }
        )
    return rows
