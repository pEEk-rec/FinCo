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

AnomalyKind = Literal["large_transaction", "duplicate_charge", "new_merchant", "unusual_frequency"]

UPI_HANDLES = ("ybl", "okaxis", "oksbi", "paytm", "ibl")


@dataclass(frozen=True)
class Merchant:
    """A recurring spend pattern: how often and how much, in whole rupees."""

    code: str
    description: str
    per_month: tuple[int, int]
    rupees: tuple[int, int]
    category: str
    recurring: bool = False


# Regular monthly life.
MERCHANTS: tuple[Merchant, ...] = (
    Merchant("HOSTELMESS", "Mess bill", (1, 1), (3200, 3600), "food", True),
    Merchant("SWIGGY", "Food delivery", (4, 9), (120, 450), "food"),
    Merchant("ZOMATO", "Food delivery", (2, 6), (150, 500), "food"),
    Merchant("CANTEEN", "College canteen", (8, 15), (20, 90), "food"),
    Merchant("BLINKIT", "Groceries", (1, 4), (150, 700), "shopping"),
    Merchant("SPOTIFY", "Music subscription", (1, 1), (119, 119), "entertainment", True),
    Merchant("NETFLIX", "Video subscription", (1, 1), (199, 199), "entertainment", True),
    Merchant("JIORECHARGE", "Mobile recharge", (1, 1), (299, 299), "bills", True),
    Merchant("RAPIDO", "Bike taxi", (3, 8), (35, 140), "travel"),
    Merchant("UBER", "Cab rides", (1, 4), (150, 500), "travel"),
    Merchant("IRCTC", "Train ticket", (0, 1), (400, 1500), "travel"),
    Merchant("XEROXCORNER", "Printouts", (2, 5), (10, 80), "shopping"),
    Merchant("AMAZON", "Books and stationery", (0, 2), (199, 899), "shopping"),
    Merchant("RENT", "Flat rent", (1, 1), (8000, 12000), "housing", True),
)

NEW_MERCHANT = Merchant("DECATHLON", "Sports gear", (1, 1), (1499, 2499), "shopping")
LARGE_MERCHANT = Merchant("CROMA", "Electronics", (1, 1), (18000, 22000), "shopping")
POCKET_MONEY_RUPEES = (15000, 20000)


@dataclass(frozen=True)
class Anomaly:
    """A planted anomaly and the transactions that make it up."""

    kind: AnomalyKind
    transaction_ids: tuple[str, ...]
    note: str


@dataclass(frozen=True)
class GroundTruthTxn:
    """Hidden ground truth per transaction."""

    txn_id: str
    true_category: str | None
    is_transfer: bool
    is_recurring: bool
    is_anomaly: bool
    anomaly_kind: str | None = None


@dataclass
class SynthResult:
    """Generated transactions (oldest first) and the anomalies planted among them."""

    transactions: list[Transaction] = field(default_factory=list)
    ground_truth: list[Anomaly] = field(default_factory=list)
    tx_truth: dict[str, GroundTruthTxn] = field(default_factory=dict)


class _Builder:
    """Holds the seeded RNG and creates transactions for one user/account."""

    def __init__(self, seed: int, user_id: str, account_ids: list[str]) -> None:
        self.rng = random.Random(seed)
        self.user_id = user_id
        self.account_ids = account_ids

    def new_id(self) -> str:
        """A UUID4-shaped id drawn from the seeded RNG."""
        return str(uuid.UUID(int=self.rng.getrandbits(128), version=4))

    def moment(
        self, year: int, month: int, day: int | None = None, hour: int | None = None
    ) -> datetime:  # noqa: E501
        """A random waking-hours IST time in the month (or on `day`)."""
        if day is None:
            day = self.rng.randint(1, calendar.monthrange(year, month)[1])
        if hour is None:
            hour = self.rng.randint(7, 23)
        return datetime(year, month, day, hour, self.rng.randint(0, 59), tzinfo=IST)

    def narration(self, code: str) -> str:
        """Messy UPI narration, e.g. 'UPI-SWIGGY-swiggy8123@ybl-REF402918374651'."""
        handle = f"{code.lower()}{self.rng.randint(100, 9999)}@{self.rng.choice(UPI_HANDLES)}"
        ref = self.rng.randint(10**11, 10**12 - 1)
        return self.rng.choice(
            (
                "UPI-{c}-{h}-REF{r}",
                "UPI/{c}/{h}/{r}",
                "{c} UPI {r} {h}",
                "IMPS-{c}-{r}",
                "NEFT-{c}-{r}",
            )
        ).format(  # noqa: E501
            c=code, h=handle, r=ref
        )

    def make(
        self, when: datetime, paise: int, merchant_raw: str, description: str, account_id: str
    ) -> Transaction:  # noqa: E501
        """A transaction; paise > 0 is a debit, paise < 0 a credit."""
        ts = to_utc_iso(when)
        return Transaction(
            id=self.new_id(),
            user_id=self.user_id,
            account_id=account_id,
            occurred_at=ts,
            amount_paise=paise,
            direction="debit" if paise > 0 else "credit",
            merchant_raw=merchant_raw,
            description=description,
            created_at=ts,
        )

    def spend(self, merchant: Merchant, when: datetime, account_id: str) -> Transaction:
        """One debit at `merchant`."""
        paise = self.rng.randint(*merchant.rupees) * 100
        return self.make(
            when, paise, self.narration(merchant.code), merchant.description, account_id
        )  # noqa: E501


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
    account_ids: str | list[str],
    *,
    start_year: int = 2024,
    start_month: int = 1,
) -> SynthResult:
    if isinstance(account_ids, str):
        account_ids = [account_ids]

    if months < 1:
        raise ValueError("months must be >= 1")
    if not account_ids:
        raise ValueError("must provide at least one account_id")

    b = _Builder(seed, user_id, account_ids)
    result = SynthResult()
    periods = _months(start_year, start_month, months)

    def add_truth(
        tx: Transaction,
        true_cat: str | None,
        is_transfer: bool,
        is_recurring: bool,
        anomaly: str | None = None,
    ):  # noqa: E501
        result.tx_truth[tx.id] = GroundTruthTxn(
            txn_id=tx.id,
            true_category=true_cat,
            is_transfer=is_transfer,
            is_recurring=is_recurring,
            is_anomaly=bool(anomaly),
            anomaly_kind=anomaly,
        )

    primary_acc = account_ids[0]
    secondary_acc = account_ids[1] if len(account_ids) > 1 else primary_acc

    for year, month in periods:
        pocket = b.rng.randint(*POCKET_MONEY_RUPEES) * 100
        # Salary/Pocket money
        tx = b.make(
            b.moment(year, month, day=1),
            -pocket,
            f"NEFT-CR-ALLOWANCE-REF{b.rng.randint(10**9, 10**10 - 1)}",
            "Allowance",
            primary_acc,
        )
        result.transactions.append(tx)
        add_truth(tx, "income", False, True)

        # Spends
        for merchant in MERCHANTS:
            for _ in range(b.rng.randint(*merchant.per_month)):
                tx = b.spend(merchant, b.moment(year, month), primary_acc)
                result.transactions.append(tx)
                add_truth(tx, merchant.category, False, merchant.recurring)

        # Own-account transfer
        if primary_acc != secondary_acc and b.rng.random() < 0.5:
            transfer_amount = b.rng.randint(1000, 5000) * 100
            t_time = b.moment(year, month, day=15)

            debit_tx = b.make(
                t_time,
                transfer_amount,
                f"IMPS-SELF-TRANSFER-{secondary_acc}",
                "Transfer to savings",
                primary_acc,
            )  # noqa: E501
            credit_tx = b.make(
                t_time + timedelta(seconds=b.rng.randint(10, 60)),
                -transfer_amount,
                f"IMPS-SELF-TRANSFER-{primary_acc}",
                "Received from checking",
                secondary_acc,
            )  # noqa: E501

            result.transactions.extend([debit_tx, credit_tx])
            add_truth(debit_tx, None, True, False)
            add_truth(credit_tx, None, True, False)

        # Refund
        if b.rng.random() < 0.2:
            refund_amount = b.rng.randint(200, 1000) * 100
            r_time = b.moment(year, month, day=20)
            refund_tx = b.make(
                r_time, -refund_amount, "UPI-REFUND-AMAZON-123", "Refund", primary_acc
            )  # noqa: E501
            result.transactions.append(refund_tx)
            add_truth(refund_tx, "shopping", False, False)

    # Anomalies in the last month
    year, month = periods[-1]

    # large purchase
    large = b.spend(LARGE_MERCHANT, b.moment(year, month), primary_acc)

    # new merchant
    new = b.spend(NEW_MERCHANT, b.moment(year, month), primary_acc)

    # duplicate charge
    first_charge_at = b.moment(year, month, day=b.rng.randint(1, 28))
    original = b.spend(MERCHANTS[1], first_charge_at, primary_acc)
    duplicate = b.make(
        first_charge_at + timedelta(minutes=2),
        original.amount_paise,
        original.merchant_raw,
        original.description,
        primary_acc,
    )

    result.transactions.extend([large, new, original, duplicate])

    add_truth(large, LARGE_MERCHANT.category, False, False, "large_transaction")
    add_truth(new, NEW_MERCHANT.category, False, False, "new_merchant")
    add_truth(original, MERCHANTS[1].category, False, False)
    add_truth(duplicate, MERCHANTS[1].category, False, False, "duplicate_charge")

    result.ground_truth = [
        Anomaly("large_transaction", (large.id,), "Unusually large electronics purchase"),
        Anomaly("duplicate_charge", (original.id, duplicate.id), "Same charge twice"),
        Anomaly("new_merchant", (new.id,), f"First purchase at {NEW_MERCHANT.code}"),
    ]

    result.transactions.sort(key=lambda t: (t.occurred_at, t.id))
    return result
