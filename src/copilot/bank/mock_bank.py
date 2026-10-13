"""
Mock bank connector: simulates an external source returning raw bank records via Account Aggregator.

The record format is invented for this project (not a real bank's): rupee amounts as strings,
'DR'/'CR' for direction, and a free-text narration. No network, no real data.
"""

import abc
import datetime
import uuid
from typing import Any

from copilot.bank.ingest import RawRecord
from copilot.bank.synth import generate_transactions
from copilot.core.errors import ErrorCode, ToolFailure
from copilot.core.money import paise_to_rupees_str
from copilot.core.timeutil import IST, normalize_utc_iso
from copilot.models.domain import Transaction


def to_raw_record(tx: Transaction) -> RawRecord:
    """Render a Transaction in the mock bank's external format."""
    return {
        "txn_ref": tx.id,
        "account_no": tx.account_id,
        "posted_at": tx.occurred_at,
        "amount": paise_to_rupees_str(abs(tx.amount_paise)),
        "type": "DR" if tx.direction == "debit" else "CR",
        "narration": tx.merchant_raw,
        "remarks": tx.description,
    }


class BankConnector(abc.ABC):
    @abc.abstractmethod
    def create_consent(
        self, user_id: str, account_ids: list[str], range_from: str, range_to: str, purpose: str
    ) -> str:  # noqa: E501
        """Request data access. Returns a consent ID (status pending)."""
        pass

    @abc.abstractmethod
    def approve_consent(self, consent_id: str) -> None:
        """Simulate user approval of a consent (becomes active)."""
        pass

    @abc.abstractmethod
    def fetch_session(self, consent_id: str) -> list[RawRecord]:
        """Fetch transactions for an active consent."""
        pass


class MockAAConnector(BankConnector):
    """
    In-memory stand-in for a bank API holding records.
    """

    def __init__(self, transactions: list[Transaction], fail: bool = False) -> None:
        self._records = [to_raw_record(tx) for tx in transactions]
        self.fail = fail
        self._consents: dict[str, dict[str, Any]] = {}

    @classmethod
    def from_seed(
        cls, seed: int, months: int, user_id: str, account_id: str, fail: bool = False
    ) -> "MockAAConnector":
        """Build a connector backed by `generate_transactions(seed, months, ...)`."""
        return cls(generate_transactions(seed, months, user_id, account_id).transactions, fail)

    def create_consent(
        self, user_id: str, account_ids: list[str], range_from: str, range_to: str, purpose: str
    ) -> str:  # noqa: E501
        consent_id = f"mock-consent-{uuid.uuid4().hex[:8]}"
        self._consents[consent_id] = {
            "user_id": user_id,
            "account_ids": account_ids,
            "range_from": normalize_utc_iso(range_from),
            "range_to": normalize_utc_iso(range_to),
            "status": "pending",
            "expires_at": None,
        }
        return consent_id

    def approve_consent(self, consent_id: str) -> None:
        if consent_id not in self._consents:
            raise ToolFailure(ErrorCode.NOT_FOUND, f"Unknown consent {consent_id}")
        self._consents[consent_id]["status"] = "active"
        now = datetime.datetime.now(tz=IST)
        # expire in 1 day for mock
        self._consents[consent_id]["expires_at"] = normalize_utc_iso(
            (now + datetime.timedelta(days=1)).isoformat()
        )  # noqa: E501

    def fetch_session(self, consent_id: str) -> list[RawRecord]:
        if self.fail:
            raise ToolFailure(ErrorCode.TOOL_FAILURE, "Mock bank is unavailable.", retryable=True)

        if consent_id not in self._consents:
            raise ToolFailure(ErrorCode.NOT_FOUND, f"Unknown consent {consent_id}")

        consent = self._consents[consent_id]
        if consent["status"] != "active":
            raise ToolFailure(ErrorCode.DENIED_BY_POLICY, f"Consent {consent_id} is not active")

        now_iso = normalize_utc_iso(datetime.datetime.now(tz=IST).isoformat())
        if consent["expires_at"] < now_iso:
            consent["status"] = "expired"
            raise ToolFailure(ErrorCode.DENIED_BY_POLICY, f"Consent {consent_id} has expired")

        start = consent["range_from"]
        end = consent["range_to"]
        allowed_accounts = set(consent["account_ids"])

        return [
            dict(r)
            for r in self._records
            if r["account_no"] in allowed_accounts and start <= r["posted_at"] < end
        ]
