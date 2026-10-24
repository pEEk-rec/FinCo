"""
Where Account Aggregator data comes from (PLAN_CAPTURE Stage C7).

`MockAASource` stands in for a bank behind an AA: it speaks the ReBIT Deposit schema (the same
shape a sandbox returns), so the parser, the fetch pipeline and reconciliation are exercised
exactly as they will be live. `bank_side_feed` makes it a believable bank: it "posts" the
payments FinCo already heard about by alert, after a short delay, with the UTR in the narration.

`SandboxAASource` wraps the gateway client in `copilot.live.aa`. It needs the owner's sandbox
credentials in `.env`; without them it is absent and the mock is used.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from copilot.core.timeutil import now_utc, to_utc_iso
from copilot.live.aa import AAClient, AAConfig, AAError, parse_fi_data
from copilot.live.statement import StatementRow


@dataclass(frozen=True)
class AAFetchResult:
    rows: list[StatementRow]
    #: The reply as received, kept only until the data life ends. None where the gateway
    #: already decrypts and we keep no copy.
    payload: dict[str, Any] | None


class AASource(Protocol):
    name: str

    def fetch(self, range_from: datetime, range_to: datetime) -> AAFetchResult: ...


def rebit_deposit_payload(
    txns: list[dict[str, Any]], masked_account: str, start: datetime, end: datetime
) -> dict[str, Any]:
    """A FI data reply in the ReBIT Deposit schema (profile, summary, transactions)."""
    return {
        "status": "COMPLETED",
        "fiType": "DEPOSIT",
        "fi": [
            {
                "fipId": "MOCK-FIP",
                "Account": {
                    "type": "deposit",
                    "maskedAccNumber": masked_account,
                    "version": "1.1",
                    "linkedAccRef": "mock-link-1",
                    "Transactions": {
                        "startDate": to_utc_iso(start)[:10],
                        "endDate": to_utc_iso(end)[:10],
                        "Transaction": txns,
                    },
                },
            }
        ],
    }


class MockAASource:
    name = "mock"

    def __init__(self, feed: Callable[[], list[dict[str, Any]]], masked_account: str = "XXXX1234"):
        self._feed = feed
        self._masked = masked_account

    def fetch(self, range_from: datetime, range_to: datetime) -> AAFetchResult:
        payload = rebit_deposit_payload(self._feed(), self._masked, range_from, range_to)
        return AAFetchResult(parse_fi_data(payload), payload)


def bank_side_feed(
    conn: sqlite3.Connection, user_id: str, clock: datetime | None = None, delay_hours: int = 2
) -> Callable[[], list[dict[str, Any]]]:
    """What a bank would hold: payments heard about by alert, posted after a short delay."""

    def feed() -> list[dict[str, Any]]:
        cutoff = now_utc(clock) - timedelta(hours=delay_hours)
        out: list[dict[str, Any]] = []
        for e in conn.execute(
            "SELECT * FROM payment_events WHERE user_id = ? AND state IN ('posted', 'orphaned')"
            " AND occurred_at <= ? ORDER BY occurred_at, id",
            (user_id, to_utc_iso(cutoff)),
        ):
            utr = e["utr"] or ""
            name = (e["display_name"] or "").upper()[:40]
            out.append(
                {
                    "txnId": utr or e["id"],
                    "type": "DEBIT" if e["direction"] == "debit" else "CREDIT",
                    "mode": "UPI",
                    "amount": f"{e['amount_paise'] // 100}.{e['amount_paise'] % 100:02d}",
                    "currentBalance": "0.00",
                    "transactionTimestamp": e["occurred_at"],
                    "valueDate": e["occurred_at"][:10],
                    "narration": f"UPI/{utr or 'NA'}/{name}",
                    "reference": utr or e["id"],
                }
            )
        return out

    return feed


class SandboxAASource:
    name = "sandbox"

    def __init__(self, client: AAClient, consent_ref: str) -> None:
        self._client = client
        self._ref = consent_ref

    def status(self) -> str:
        return self._client.consent_status(self._ref)

    def fetch(self, range_from: datetime, range_to: datetime) -> AAFetchResult:
        return AAFetchResult(self._client.fetch_rows(self._ref, range_from, range_to), None)


def sandbox_source(
    consent_ref: str | None, env: dict[str, str] | None = None
) -> SandboxAASource | None:
    cfg = AAConfig.from_env(env)
    if cfg is None or not consent_ref:
        return None
    return SandboxAASource(AAClient(cfg), consent_ref)


__all__ = [
    "AAError",
    "AAFetchResult",
    "AASource",
    "MockAASource",
    "SandboxAASource",
    "bank_side_feed",
    "rebit_deposit_payload",
    "sandbox_source",
]
