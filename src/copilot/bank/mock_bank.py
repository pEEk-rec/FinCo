"""
Mock bank connector: simulates an external source returning raw bank records.

The record format is invented for this project (not a real bank's): rupee amounts as strings,
'DR'/'CR' for direction, and a free-text narration. `copilot.bank.loader` converts records
into domain Transactions, so parsing is exercised the way a real connector will need.
No network, no real data.
"""

from copilot.bank.loader import RawRecord
from copilot.bank.synth import generate_transactions
from copilot.core.errors import ErrorCode, ToolFailure
from copilot.core.money import paise_to_rupees_str
from copilot.core.timeutil import normalize_utc_iso
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


class MockBankConnector:
    """
    In-memory stand-in for a bank API holding records for one or more accounts.

    Set `fail=True` to simulate an outage: every fetch raises ToolFailure(TOOL_FAILURE),
    marked retryable.
    """

    def __init__(self, transactions: list[Transaction], fail: bool = False) -> None:
        self._records = [to_raw_record(tx) for tx in transactions]
        self.fail = fail

    @classmethod
    def from_seed(
        cls, seed: int, months: int, user_id: str, account_id: str, fail: bool = False
    ) -> "MockBankConnector":
        """Build a connector backed by `generate_transactions(seed, months, ...)`."""
        return cls(generate_transactions(seed, months, user_id, account_id).transactions, fail)

    def fetch_transactions(self, account_id: str, start: str, end: str) -> list[RawRecord]:
        """Raw records for `account_id` with start <= posted_at < end, oldest first."""
        if self.fail:
            raise ToolFailure(ErrorCode.TOOL_FAILURE, "Mock bank is unavailable.", retryable=True)
        start, end = normalize_utc_iso(start), normalize_utc_iso(end)
        if start >= end:
            raise ToolFailure(ErrorCode.INVALID_INPUT, "start must be before end.")
        if not any(r["account_no"] == account_id for r in self._records):
            raise ToolFailure(ErrorCode.NOT_FOUND, f"Unknown account '{account_id}'.")
        return [
            dict(r)
            for r in self._records
            if r["account_no"] == account_id and start <= r["posted_at"] < end
        ]
