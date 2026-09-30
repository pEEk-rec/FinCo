"""
Seeded synthetic transactions for an Indian student, with planted anomalies as ground truth.

Determinism rules: all randomness comes from one `random.Random(seed)`, IDs are drawn from it
too, and no wall clock is read. The same arguments always produce identical output.
Merchant strings are deliberately messy (as UPI narrations are) for Phase 1 categorisation.
"""

import calendar
import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

from copilot.core.timeutil import IST, to_utc_iso
from copilot.models.domain import Transaction

AnomalyKind = Literal["large_transaction", "duplicate_charge", "new_merchant"]

UPI_HANDLES = ("ybl", "okaxis", "oksbi", "paytm", "ibl")


@dataclass(frozen=True)
class Merchant:
    """A recurring spend pattern: how often and how much, in whole rupees."""

    code: str
    description: str
    per_month: tuple[int, int]
    rupees: tuple[int, int]


# Regular monthly life of a hostel student. Amounts are whole rupees (typical for UPI).
MERCHANTS: tuple[Merchant, ...] = (
    Merchant("HOSTELMESS", "Mess bill", (1, 1), (3200, 3600)),
    Merchant("SWIGGY", "Food delivery", (4, 9), (120, 450)),
    Merchant("ZOMATO", "Food delivery", (2, 6), (150, 500)),
    Merchant("CANTEEN", "College canteen", (8, 15), (20, 90)),
    Merchant("BLINKIT", "Groceries", (1, 4), (150, 700)),
    Merchant("SPOTIFY", "Music subscription", (1, 1), (119, 119)),
    Merchant("JIORECHARGE", "Mobile recharge", (1, 1), (299, 299)),
    Merchant("RAPIDO", "Bike taxi", (3, 8), (35, 140)),
    Merchant("IRCTC", "Train ticket", (0, 1), (400, 1500)),
    Merchant("XEROXCORNER", "Printouts", (2, 5), (10, 80)),
    Merchant("AMAZON", "Books and stationery", (0, 2), (199, 899)),
)
# Never used by the regular pattern, so it can be planted as a "new merchant".
NEW_MERCHANT = Merchant("DECATHLON", "Sports gear", (1, 1), (1499, 2499))
LARGE_MERCHANT = Merchant("CROMA", "Electronics", (1, 1), (18000, 22000))
POCKET_MONEY_RUPEES = (8000, 10000)


@dataclass(frozen=True)
class Anomaly:
    """A planted anomaly and the transactions that make it up."""

    kind: AnomalyKind
    transaction_ids: tuple[str, ...]
    note: str


@dataclass
class SynthResult:
    """Generated transactions (oldest first) and the anomalies planted among them."""

    transactions: list[Transaction] = field(default_factory=list)
    ground_truth: list[Anomaly] = field(default_factory=list)


class _Builder:
    """Holds the seeded RNG and creates transactions for one user/account."""

    def __init__(self, seed: int, user_id: str, account_id: str) -> None:
        self.rng = random.Random(seed)
        self.user_id = user_id
        self.account_id = account_id

    def new_id(self) -> str:
        """A UUID4-shaped id drawn from the seeded RNG."""
        return str(uuid.UUID(int=self.rng.getrandbits(128), version=4))

    def moment(self, year: int, month: int, day: int | None = None) -> datetime:
        """A random waking-hours IST time in the month (or on `day`)."""
        if day is None:
            day = self.rng.randint(1, calendar.monthrange(year, month)[1])
        hour = self.rng.randint(7, 23)
        return datetime(year, month, day, hour, self.rng.randint(0, 59), tzinfo=IST)

    def narration(self, code: str) -> str:
        """Messy UPI narration, e.g. 'UPI-SWIGGY-swiggy8123@ybl-REF402918374651'."""
        handle = f"{code.lower()}{self.rng.randint(100, 9999)}@{self.rng.choice(UPI_HANDLES)}"
        ref = self.rng.randint(10**11, 10**12 - 1)
        return self.rng.choice(("UPI-{c}-{h}-REF{r}", "UPI/{c}/{h}/{r}", "{c} UPI {r} {h}")).format(
            c=code, h=handle, r=ref
        )

    def make(self, when: datetime, paise: int, merchant_raw: str, description: str) -> Transaction:
        """A transaction; paise > 0 is a debit, paise < 0 a credit."""
        ts = to_utc_iso(when)
        return Transaction(
            id=self.new_id(),
            user_id=self.user_id,
            account_id=self.account_id,
            occurred_at=ts,
            amount_paise=paise,
            direction="debit" if paise > 0 else "credit",
            merchant_raw=merchant_raw,
            description=description,
            created_at=ts,
        )

    def spend(self, merchant: Merchant, when: datetime) -> Transaction:
        """One debit at `merchant`."""
        paise = self.rng.randint(*merchant.rupees) * 100
        return self.make(when, paise, self.narration(merchant.code), merchant.description)


def _months(start_year: int, start_month: int, count: int) -> list[tuple[int, int]]:
    """`count` consecutive (year, month) pairs from the start month."""
    out = []
    year, month = start_year, start_month
    for _ in range(count):
        out.append((year, month))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return out


def generate_transactions(
    seed: int,
    months: int,
    user_id: str,
    account_id: str,
    *,
    start_year: int = 2024,
    start_month: int = 1,
) -> SynthResult:
    """
    Generate `months` months of transactions and plant one of each anomaly in the last month.

    Planted anomalies (returned in `ground_truth`):
      - large_transaction: one electronics purchase of Rs 18,000 to 22,000
      - duplicate_charge:  an exact copy (same merchant string and amount) 2 minutes later
      - new_merchant:      the first ever purchase at a merchant not seen before
    """
    if months < 1:
        raise ValueError("months must be >= 1")
    b = _Builder(seed, user_id, account_id)
    result = SynthResult()
    periods = _months(start_year, start_month, months)

    for year, month in periods:
        pocket = b.rng.randint(*POCKET_MONEY_RUPEES) * 100
        result.transactions.append(
            b.make(
                b.moment(year, month, day=1),
                -pocket,
                f"NEFT-CR-PARENT-POCKETMONEY-REF{b.rng.randint(10**9, 10**10 - 1)}",
                "Pocket money",
            )
        )
        for merchant in MERCHANTS:
            for _ in range(b.rng.randint(*merchant.per_month)):
                result.transactions.append(b.spend(merchant, b.moment(year, month)))

    year, month = periods[-1]
    large = b.spend(LARGE_MERCHANT, b.moment(year, month))
    new = b.spend(NEW_MERCHANT, b.moment(year, month))
    # Day <= 28 and hour <= 23 keep "+2 minutes" inside the same month.
    first_charge_at = b.moment(year, month, day=b.rng.randint(1, 28))
    original = b.spend(MERCHANTS[1], first_charge_at)
    duplicate = b.make(
        first_charge_at + timedelta(minutes=2),
        original.amount_paise,
        original.merchant_raw,
        original.description,
    )
    result.transactions += [large, new, original, duplicate]
    result.ground_truth = [
        Anomaly("large_transaction", (large.id,), "Unusually large electronics purchase"),
        Anomaly("duplicate_charge", (original.id, duplicate.id), "Same charge twice"),
        Anomaly("new_merchant", (new.id,), f"First purchase at {NEW_MERCHANT.code}"),
    ]
    result.transactions.sort(key=lambda t: (t.occurred_at, t.id))
    return result
