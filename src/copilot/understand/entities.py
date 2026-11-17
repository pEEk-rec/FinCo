# ruff: noqa: E501  (long SQL and prose lines)
"""
Merchant entities (PLAN_AGENTIC_V2, A2): one shop, however many ways a bank spells it.

A label belongs to an *entity*, not to a string, so one answer covers every variant from every
bank. The rules that keep this safe:

* a person is never merged with a merchant, and two persons are only ever the same when they
  share the exact same VPA (or, with no VPA, the exact same name on the same rail);
* a truncated name joins a longer one only when it is a long-enough prefix of exactly one entity;
  if two entities fit, nothing is merged and a "same shop?" question is logged instead;
* every merge and split is audited, logged with a snapshot, and can be undone exactly.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from copilot.audit.events import Actor, record_event
from copilot.common.errors import ErrorCode, ToolFailure
from copilot.common.timeutil import now_utc, to_utc_iso
from copilot.understand.config import UnderstandConfig, load_dictionary, load_understand_config
from copilot.understand.descriptor import Descriptor


@dataclass(frozen=True)
class Resolution:
    entity_id: str
    kind: str
    created: bool
    ambiguous: tuple[str, ...] = field(default=())  # other entities that also fitted


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class EntityStore:
    def __init__(
        self,
        conn: sqlite3.Connection,
        user_id: str,
        cfg: UnderstandConfig | None = None,
        clock: datetime | None = None,
    ) -> None:
        self.conn = conn
        self.user_id = user_id
        self.cfg = cfg or load_understand_config()
        self.clock = clock
        self._brands = self._brand_index()

    # ---- the dictionary ----------------------------------------------------------------------
    @staticmethod
    def _brand_index() -> dict[str, tuple[str, str]]:
        """squashed name or handle -> (brand display name, category)."""
        out: dict[str, tuple[str, str]] = {}
        for b in load_dictionary().brands:
            for n in b.names:
                out[_sq(n)] = (b.name, b.category)
            for h in b.handles:
                out[_sq(h)] = (b.name, b.category)
        return out

    def brand_for(self, desc: Descriptor) -> tuple[str, str] | None:
        for key in (desc.squash, desc.brand or ""):
            if key and key in self._brands:
                return self._brands[key]
        return None

    # ---- reading -----------------------------------------------------------------------------
    def _now(self) -> str:
        return to_utc_iso(now_utc(self.clock))

    def canonical(self, entity_id: str) -> str:
        """Follow merged_into to the surviving entity."""
        seen = set()
        while entity_id not in seen:
            seen.add(entity_id)
            row = self.conn.execute(
                "SELECT merged_into FROM merchant_entities WHERE user_id = ? AND id = ?",
                (self.user_id, entity_id),
            ).fetchone()
            if not row or not row[0]:
                return entity_id
            entity_id = row[0]
        return entity_id

    def entity(self, entity_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM merchant_entities WHERE user_id = ? AND id = ?",
            (self.user_id, self.canonical(entity_id)),
        ).fetchone()

    def aliases(self, entity_id: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM entity_aliases WHERE user_id = ? AND entity_id = ? ORDER BY created_at, id",
            (self.user_id, entity_id),
        ).fetchall()

    # ---- resolving ---------------------------------------------------------------------------
    def _exact(self, desc: Descriptor) -> dict[str, int]:
        """entity id -> strongest exact evidence, from the alias table."""
        found: dict[str, int] = {}
        keys = []
        if desc.vpa:
            keys.append(("vpa", desc.vpa, self.cfg.entities.exact_vpa_bp))
        if desc.name and not (desc.person_hint and desc.vpa):
            keys.append(("name", desc.name, self.cfg.entities.exact_name_bp))
        if desc.squash and len(desc.squash) >= 4 and not desc.person_hint:
            keys.append(("squash", desc.squash, self.cfg.entities.squash_equal_bp))
        brand = self.brand_for(desc)
        if brand and not desc.person_hint:
            keys.append(("squash", _sq(brand[0]), self.cfg.entities.squash_equal_bp))
        for typ, val, bp in keys:
            row = self.conn.execute(
                "SELECT entity_id FROM entity_aliases WHERE user_id = ? AND alias_type = ?"
                " AND alias_value = ?",
                (self.user_id, typ, val),
            ).fetchone()
            if row:
                eid = self.canonical(row[0])
                found[eid] = max(found.get(eid, 0), bp)
        return found

    def _prefix(self, desc: Descriptor) -> set[str]:
        n = self.cfg.entities.min_prefix_chars
        sq = desc.squash
        if desc.person_hint or len(sq) < 4:
            return set()
        rows = self.conn.execute(
            "SELECT a.entity_id, a.alias_value FROM entity_aliases a"
            " JOIN merchant_entities e ON e.id = a.entity_id"
            " WHERE a.user_id = ? AND a.alias_type = 'squash' AND e.kind != 'person'",
            (self.user_id,),
        ).fetchall()
        hits: set[str] = set()
        for eid, value in rows:
            short, long_ = (sq, value) if len(sq) <= len(value) else (value, sq)
            if len(short) >= n and long_.startswith(short) and short != long_:
                hits.add(self.canonical(eid))
        return hits

    def _kind(self, desc: Descriptor) -> str:
        if self.brand_for(desc):
            return "merchant"
        if desc.person_hint:
            return "person"
        if desc.raw_rail in ("card", "mandate", "atm", "bank"):
            return "merchant"
        return "unknown" if desc.raw_rail == "upi" else "merchant"

    def _attach(self, entity_id: str, desc: Descriptor, bp_by_type: dict[str, int]) -> None:
        kind = self.entity(entity_id)["kind"]  # type: ignore[index]
        add: list[tuple[str, str]] = []
        if desc.vpa:
            add.append(("vpa", desc.vpa))
        if desc.name and not (kind == "person" and desc.vpa):
            add.append(("name", desc.name))
        if desc.squash and len(desc.squash) >= 4 and kind != "person":
            add.append(("squash", desc.squash))
        for typ, val in add:
            self.conn.execute(
                "INSERT OR IGNORE INTO entity_aliases (id, user_id, entity_id, alias_type,"
                " alias_value, evidence_bp, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    _id("ali"),
                    self.user_id,
                    entity_id,
                    typ,
                    val,
                    bp_by_type.get(typ, 8000),
                    self._now(),
                ),
            )

    def resolve(self, desc: Descriptor) -> Resolution:
        """The entity this descriptor belongs to, creating one if it is new. Idempotent."""
        kind = self._kind(desc)
        exact = self._exact(desc)
        # a person never joins a merchant, nor a merchant a person
        exact = {
            e: bp
            for e, bp in exact.items()
            if (self.entity(e)["kind"] == "person") == (kind == "person")  # type: ignore[index]
        }
        e = self.cfg.entities
        bps = {"vpa": e.exact_vpa_bp, "name": e.exact_name_bp, "squash": e.squash_equal_bp}
        if exact:
            ranked = sorted(exact.items(), key=lambda kv: (-kv[1], kv[0]))
            best, others = ranked[0][0], tuple(x for x, _ in ranked[1:])
            if others and ranked[0][1] == ranked[1][1]:
                # two entities fit equally well on exact keys: keep the first, ask about the rest
                for o in others:
                    self._question(best, o, ranked[1][1])
            self._attach(best, desc, bps)
            return Resolution(best, self.entity(best)["kind"], False, others)  # type: ignore[index]
        if kind != "person":
            near = self._prefix(desc)
            if len(near) == 1:
                best = next(iter(near))
                self._attach(best, desc, {**bps, "squash": e.prefix_bp, "name": e.prefix_bp})
                return Resolution(best, self.entity(best)["kind"], False)  # type: ignore[index]
            if len(near) > 1:
                new = self._create(desc, kind)
                for o in sorted(near):
                    self._question(new, o, e.prefix_bp)
                return Resolution(new, kind, True, tuple(sorted(near)))
        return Resolution(self._create(desc, kind), kind, True)

    def _create(self, desc: Descriptor, kind: str) -> str:
        brand = self.brand_for(desc)
        display = brand[0] if brand else (desc.name or "unknown").title()
        eid = _id("ent")
        self.conn.execute(
            "INSERT INTO merchant_entities (id, user_id, kind, display_name, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (eid, self.user_id, kind, display[:80], self._now()),
        )
        e = self.cfg.entities
        self._attach(
            eid, desc, {"vpa": e.exact_vpa_bp, "name": e.exact_name_bp, "squash": e.squash_equal_bp}
        )
        if (
            brand
        ):  # the brand's own name and handle also point here, so every bank's spelling finds it
            for typ, val in (("squash", _sq(brand[0])),):
                self.conn.execute(
                    "INSERT OR IGNORE INTO entity_aliases (id, user_id, entity_id, alias_type,"
                    " alias_value, evidence_bp, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (_id("ali"), self.user_id, eid, typ, val, e.squash_equal_bp, self._now()),
                )
        return eid

    def _question(self, a: str, b: str, bp: int) -> None:
        a, b = sorted((a, b))
        if self.conn.execute(
            "SELECT 1 FROM entity_merge_log WHERE user_id = ? AND kind = 'question'"
            " AND entity_a = ? AND entity_b = ?",
            (self.user_id, a, b),
        ).fetchone():
            return
        self.conn.execute(
            "INSERT INTO entity_merge_log (id, user_id, kind, entity_a, entity_b, evidence_bp,"
            " actor, status, created_at) VALUES (?, ?, 'question', ?, ?, ?, 'system', 'open', ?)",
            (_id("emg"), self.user_id, a, b, bp, self._now()),
        )

    # ---- labels ------------------------------------------------------------------------------
    def label(
        self,
        entity_id: str,
        category_id: str,
        *,
        actor: Actor = "user",
        run_id: str | None = None,
    ) -> dict:
        """Record the user's answer. Returns before/after for audit and undo."""
        entity_id = self.canonical(entity_id)
        row = self.conn.execute(
            "SELECT recent_json, category_id FROM entity_labels WHERE user_id = ? AND entity_id = ?",
            (self.user_id, entity_id),
        ).fetchone()
        before = {"category_id": row[1], "recent": json.loads(row[0])} if row else None
        recent = (json.loads(row[0]) if row else []) + [category_id]
        recent = recent[-3:]
        now = self._now()
        self.conn.execute(
            "INSERT INTO entity_labels (id, user_id, entity_id, category_id, recent_json,"
            " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(user_id, entity_id) DO UPDATE SET category_id = excluded.category_id,"
            " recent_json = excluded.recent_json, updated_at = excluded.updated_at",
            (_id("elb"), self.user_id, entity_id, category_id, json.dumps(recent), now, now),
        )
        after = {"category_id": category_id, "recent": recent}
        record_event(
            self.conn, user_id=self.user_id, actor=actor, event_type="entity_labeled",
            reason=f"Entity labelled {category_id}", run_id=run_id, entity_type="merchant_entity",
            entity_id=entity_id, before_data=before, after_data=after, clock=self.clock,
        )  # fmt: skip
        return {"before": before, "after": after}

    def get_label(self, entity_id: str) -> tuple[str, int] | None:
        """(category, confidence in bp). One answer is trusted; two that disagree are not."""
        row = self.conn.execute(
            "SELECT category_id, recent_json FROM entity_labels WHERE user_id = ? AND entity_id = ?",
            (self.user_id, self.canonical(entity_id)),
        ).fetchone()
        if not row:
            return None
        recent = json.loads(row[1])
        if len(recent) >= 2 and recent[-1] != recent[-2]:
            return row[0], self.cfg.learning.unsteady_bp
        return row[0], 10000

    def restore_label(self, entity_id: str, before: dict | None) -> None:
        if before is None:
            self.conn.execute(
                "DELETE FROM entity_labels WHERE user_id = ? AND entity_id = ?",
                (self.user_id, entity_id),
            )
        else:
            self.conn.execute(
                "UPDATE entity_labels SET category_id = ?, recent_json = ?, updated_at = ?"
                " WHERE user_id = ? AND entity_id = ?",
                (
                    before["category_id"],
                    json.dumps(before["recent"]),
                    self._now(),
                    self.user_id,
                    entity_id,
                ),
            )

    # ---- merge, split, undo ------------------------------------------------------------------
    def merge(
        self, keep: str, absorb: str, *, actor: Actor = "user", run_id: str | None = None
    ) -> str:
        keep, absorb = self.canonical(keep), self.canonical(absorb)
        if keep == absorb:
            raise ToolFailure(ErrorCode.INVALID_INPUT, "Those are already the same shop.")
        a, b = self.entity(keep), self.entity(absorb)
        if a is None or b is None:
            raise ToolFailure(ErrorCode.NOT_FOUND, "Unknown entity.")
        if (a["kind"] == "person") != (b["kind"] == "person"):
            raise ToolFailure(ErrorCode.INVALID_INPUT, "A person and a shop are never the same.")
        moved = [r["id"] for r in self.aliases(absorb)]
        label_b = self.conn.execute(
            "SELECT category_id, recent_json FROM entity_labels WHERE user_id = ? AND entity_id = ?",
            (self.user_id, absorb),
        ).fetchone()
        label_a = self.get_label(keep)
        snapshot = {
            "moved_aliases": moved,
            "absorbed_label": list(label_b) if label_b else None,
            "relabelled": False,
        }
        self.conn.execute(
            "UPDATE entity_aliases SET entity_id = ? WHERE user_id = ? AND entity_id = ?",
            (keep, self.user_id, absorb),
        )
        if label_b:
            if label_a is None:  # the survivor had no answer: it inherits the absorbed one
                self.conn.execute(
                    "UPDATE entity_labels SET entity_id = ? WHERE user_id = ? AND entity_id = ?",
                    (keep, self.user_id, absorb),
                )
                snapshot["relabelled"] = True
            else:
                self.conn.execute(
                    "DELETE FROM entity_labels WHERE user_id = ? AND entity_id = ?",
                    (self.user_id, absorb),
                )
        self.conn.execute(
            "UPDATE merchant_entities SET merged_into = ? WHERE user_id = ? AND id = ?",
            (keep, self.user_id, absorb),
        )
        self.conn.execute(
            "UPDATE entity_merge_log SET status = 'applied' WHERE user_id = ? AND kind = 'question'"
            " AND entity_a IN (?, ?) AND entity_b IN (?, ?)",
            (self.user_id, keep, absorb, keep, absorb),
        )
        log = _id("emg")
        self.conn.execute(
            "INSERT INTO entity_merge_log (id, user_id, kind, entity_a, entity_b, actor, status,"
            " snapshot_json, created_at) VALUES (?, ?, 'merge', ?, ?, ?, 'applied', ?, ?)",
            (log, self.user_id, keep, absorb, actor, json.dumps(snapshot), self._now()),
        )
        record_event(
            self.conn, user_id=self.user_id, actor=actor, event_type="entity_merged",
            reason="Two spellings were joined as one shop", run_id=run_id,
            entity_type="entity_merge", entity_id=log, metadata={"keep": keep, "absorbed": absorb},
            clock=self.clock,
        )  # fmt: skip
        return log

    def split(
        self,
        entity_id: str,
        alias_ids: list[str],
        *,
        actor: Actor = "user",
        run_id: str | None = None,
    ) -> str:
        entity_id = self.canonical(entity_id)
        own = {r["id"] for r in self.aliases(entity_id)}
        if not alias_ids or not set(alias_ids) <= own or set(alias_ids) == own:
            raise ToolFailure(
                ErrorCode.INVALID_INPUT, "Pick some, but not all, of this shop's spellings."
            )
        src = self.entity(entity_id)
        new = _id("ent")
        self.conn.execute(
            "INSERT INTO merchant_entities (id, user_id, kind, display_name, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (new, self.user_id, src["kind"], src["display_name"], self._now()),  # type: ignore[index]
        )
        marks = ",".join("?" for _ in alias_ids)
        self.conn.execute(
            f"UPDATE entity_aliases SET entity_id = ? WHERE user_id = ? AND id IN ({marks})",
            [new, self.user_id, *alias_ids],
        )
        log = _id("emg")
        self.conn.execute(
            "INSERT INTO entity_merge_log (id, user_id, kind, entity_a, entity_b, actor, status,"
            " snapshot_json, created_at) VALUES (?, ?, 'split', ?, ?, ?, 'applied', ?, ?)",
            (
                log,
                self.user_id,
                entity_id,
                new,
                actor,
                json.dumps({"moved_aliases": alias_ids}),
                self._now(),
            ),
        )
        record_event(
            self.conn, user_id=self.user_id, actor=actor, event_type="entity_split",
            reason="A spelling was separated into its own shop", run_id=run_id,
            entity_type="entity_merge", entity_id=log, metadata={"from": entity_id, "to": new},
            clock=self.clock,
        )  # fmt: skip
        return new

    def undo(self, log_id: str, *, actor: Actor = "user") -> None:
        row = self.conn.execute(
            "SELECT * FROM entity_merge_log WHERE user_id = ? AND id = ?", (self.user_id, log_id)
        ).fetchone()
        if row is None or row["kind"] not in ("merge", "split"):
            raise ToolFailure(ErrorCode.NOT_FOUND, "Nothing to undo there.")
        if row["status"] != "applied":
            raise ToolFailure(ErrorCode.INVALID_INPUT, "That was already undone.")
        snap = json.loads(row["snapshot_json"])
        a, b = row["entity_a"], row["entity_b"]
        marks = ",".join("?" for _ in snap["moved_aliases"])
        if row["kind"] == "merge":  # b was absorbed into a: put its spellings and answer back
            self.conn.execute(
                f"UPDATE entity_aliases SET entity_id = ? WHERE user_id = ? AND id IN ({marks})",
                [b, self.user_id, *snap["moved_aliases"]],
            )
            self.conn.execute(
                "UPDATE merchant_entities SET merged_into = NULL WHERE user_id = ? AND id = ?",
                (self.user_id, b),
            )
            if snap.get("relabelled"):
                self.conn.execute(
                    "UPDATE entity_labels SET entity_id = ? WHERE user_id = ? AND entity_id = ?",
                    (b, self.user_id, a),
                )
            elif snap.get("absorbed_label"):
                cat, recent = snap["absorbed_label"]
                now = self._now()
                self.conn.execute(
                    "INSERT INTO entity_labels (id, user_id, entity_id, category_id, recent_json,"
                    " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (_id("elb"), self.user_id, b, cat, recent, now, now),
                )
        else:  # a split moved spellings from a to the new entity b: bring them home
            self.conn.execute(
                f"UPDATE entity_aliases SET entity_id = ? WHERE user_id = ? AND id IN ({marks})",
                [a, self.user_id, *snap["moved_aliases"]],
            )
            self.conn.execute(
                "UPDATE merchant_entities SET merged_into = ? WHERE user_id = ? AND id = ?",
                (a, self.user_id, b),
            )
        self.conn.execute(
            "UPDATE entity_merge_log SET status = 'undone' WHERE user_id = ? AND id = ?",
            (self.user_id, log_id),
        )
        record_event(
            self.conn, user_id=self.user_id, actor=actor, event_type="entity_merge_undone",
            reason="A merge or split was undone", entity_type="entity_merge", entity_id=log_id,
            clock=self.clock,
        )  # fmt: skip


def _sq(text: str) -> str:
    return "".join(c for c in text.lower() if c.isalnum())
