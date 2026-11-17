# ruff: noqa: E501  (long SQL and prose lines)
"""
Calibration (PLAN_AGENTIC_V2, A4): what a stage's score really means for this user.

Every stage claims a raw score in basis points. Calibration keeps, per stage and per bin of raw
score, how often that stage was actually right, and turns a claim into an honest probability.
Until there is evidence a bin leans on a prior (the stage is believed to mean what it says, or, for
the deterministic stages, a stated accuracy from `config/understand.yaml`). The bins are then pooled
so the result never goes *down* as the raw score goes up (isotonic, by pool-adjacent-violators).
"""

from __future__ import annotations

import sqlite3
import uuid

from copilot.understand.config import UnderstandConfig, load_understand_config

#: Deterministic stages are believed to be right far more often than their raw score says. Said once,
#: here and in the config file's comment, and corrected by evidence as soon as there is some.
STAGE_PRIOR_BP = {"S1": 9800, "S3": 9750}
BINS = 10


def _bin(raw_bp: int) -> int:
    return max(0, min(BINS - 1, raw_bp // 1000))


class Calibrator:
    def __init__(
        self, conn: sqlite3.Connection, user_id: str, cfg: UnderstandConfig | None = None
    ) -> None:
        self.conn = conn
        self.user_id = user_id
        self.cfg = cfg or load_understand_config()
        self._cache: dict[str, list[tuple[int, int]]] = {}

    def _counts(self, stage: str) -> list[tuple[int, int]]:
        if stage not in self._cache:
            rows = {
                r[0]: (r[1], r[2])
                for r in self.conn.execute(
                    "SELECT bin, n, correct FROM calibration_bins WHERE user_id = ? AND stage = ?",
                    (self.user_id, stage),
                )
            }
            self._cache[stage] = [rows.get(i, (0, 0)) for i in range(BINS)]
        return self._cache[stage]

    def table(self, stage: str) -> list[tuple[int, int, int]]:
        """(posterior bp, evidence weight, observations) per bin, after pooling."""
        counts = self._counts(stage)
        strength = self.cfg.calibration.prior_strength
        post: list[list[float]] = []
        for i, (n, correct) in enumerate(counts):
            prior = STAGE_PRIOR_BP.get(stage, i * 1000 + 500)
            w = n + strength
            post.append([(correct * 10000 + strength * prior) / w if w else prior, w])
        # pool adjacent violators: a higher raw score may never mean a lower probability
        blocks: list[list[float]] = []  # [value, weight, bins covered]
        for p, w in post:
            blocks.append([p, w, 1])
            while len(blocks) > 1 and blocks[-2][0] > blocks[-1][0]:
                v2, w2, c2 = blocks.pop()
                v1, w1, c1 = blocks.pop()
                blocks.append([(v1 * w1 + v2 * w2) / (w1 + w2), w1 + w2, c1 + c2])
        out: list[tuple[int, int, int]] = []
        i = 0
        for value, weight, cover in blocks:
            for _ in range(int(cover)):
                out.append((round(value), round(weight), counts[i][0]))
                i += 1
        return out

    def apply(self, stage: str, raw_bp: int) -> int:
        """The calibrated probability, in basis points, of a stage's claim."""
        if stage == "S0":
            return raw_bp
        return self.table(stage)[_bin(raw_bp)][0]

    def update(self, stage: str, raw_bp: int, correct: bool) -> None:
        b = _bin(raw_bp)
        self.conn.execute(
            "INSERT INTO calibration_bins (id, user_id, stage, bin, n, correct)"
            " VALUES (?, ?, ?, ?, 1, ?)"
            " ON CONFLICT(user_id, stage, bin) DO UPDATE SET n = n + 1, correct = correct + ?",
            (f"cal_{uuid.uuid4().hex[:12]}", self.user_id, stage, b, int(correct), int(correct)),
        )
        self._cache.pop(stage, None)

    def reset(self) -> int:
        self._cache.clear()
        return self.conn.execute(
            "DELETE FROM calibration_bins WHERE user_id = ?", (self.user_id,)
        ).rowcount
