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


# -------------------------------------------------------------------------------------------------
# Phase 2 Synthetic Data Generator v3 (PLAN_PHASE2 Section 5.4 & Stage 2.4)
# -------------------------------------------------------------------------------------------------
DEV_SEEDS: tuple[int, ...] = (42, 101, 202, 303, 404)
HELD_OUT_SEEDS: tuple[int, ...] = (777, 888, 999)


@dataclass(frozen=True)
class InjectedCause:
    """A planted cause for investigation testing with hidden ground truth."""

    kind: str
    category: str | None
    month: str  # YYYY-MM
    transaction_ids: tuple[str, ...]
    expected_amount_paise: int
    note: str


@dataclass
class SynthResultV3:
    """Generated transactions for Phase 2 investigation with hidden ground truth."""

    transactions: list[Transaction] = field(default_factory=list)
    ground_truth_causes: list[InjectedCause] = field(default_factory=list)
    tx_truth: dict[str, GroundTruthTxn] = field(default_factory=dict)
    baseline_months: list[str] = field(default_factory=list)
    target_month: str = ""
    profile: str = "standard"


def generate_transactions_v3(
    seed: int,
    months: int,
    user_id: str,
    account_ids: str | list[str],
    *,
    start_year: int = 2026,
    start_month: int = 6,
    target_cause: str | None = None,
    profile: Literal["standard", "hard"] = "standard",
) -> SynthResultV3:
    """
    Generate deterministic transactions for Phase 2 investigation engine evaluation.

    Supports hidden ground-truth causes:
    - one_off_large
    - recurring_change
    - more_frequent
    - new_merchant
    - miscategorization
    - duplicate_or_refund
    - seasonal_or_timing
    - no_cause
    - overlapping (hard profile)
    """
    if isinstance(account_ids, str):
        account_ids = [account_ids]

    if months < 2:
        raise ValueError("months must be >= 2 for v3 (requires at least 1 baseline + target)")
    if not account_ids:
        raise ValueError("must provide at least one account_id")

    b = _Builder(seed, user_id, account_ids)
    result = SynthResultV3(profile=profile)
    periods = _months(start_year, start_month, months)

    target_year, target_m = periods[-1]
    result.target_month = f"{target_year:04d}-{target_m:02d}"
    result.baseline_months = [f"{y:04d}-{m:02d}" for y, m in periods[:-1]]

    primary_acc = account_ids[0]

    def add_truth(
        tx: Transaction,
        true_cat: str | None,
        is_transfer: bool,
        is_recurring: bool,
        anomaly: str | None = None,
    ) -> None:
        result.tx_truth[tx.id] = GroundTruthTxn(
            txn_id=tx.id,
            true_category=true_cat,
            is_transfer=is_transfer,
            is_recurring=is_recurring,
            is_anomaly=bool(anomaly),
            anomaly_kind=anomaly,
        )

    hard_aliases = {
        "SWIGGY": "BUNDLTECH-BANGALORE",
        "ZOMATO": "ZOMATO-MEDIA-PVT-LTD",
        "BLINKIT": "COMMERCE-BLINKIT-GURGAON",
        "SPOTIFY": "SPOTIFY-INDIA-MUMBAI",
    }

    # Deterministic fixed expenses across months for realistic baseline
    fixed_rent_rupees = b.rng.randint(8000, 12000)
    fixed_mess_rupees = b.rng.randint(3200, 3600)

    def _make_merch_tx(merch: Merchant, when: datetime) -> Transaction:
        if merch.code == "RENT":
            return b.make(
                when,
                fixed_rent_rupees * 100,
                b.narration(merch.code),
                merch.description,
                primary_acc,
            )
        if merch.code == "HOSTELMESS":
            return b.make(
                when,
                fixed_mess_rupees * 100,
                b.narration(merch.code),
                merch.description,
                primary_acc,
            )
        return b.spend(merch, when, primary_acc)

    # Generate baseline months
    for y, m in periods[:-1]:
        pocket = b.rng.randint(*POCKET_MONEY_RUPEES) * 100
        inc_tx = b.make(
            b.moment(y, m, day=1),
            -pocket,
            f"NEFT-CR-ALLOWANCE-REF{b.rng.randint(10**9, 10**10 - 1)}",
            "Allowance",
            primary_acc,
        )
        result.transactions.append(inc_tx)
        add_truth(inc_tx, "income", False, True)

        for merch in MERCHANTS:
            for _ in range(b.rng.randint(*merch.per_month)):
                tx = _make_merch_tx(merch, b.moment(y, m))
                tx = tx.model_copy(
                    update={
                        "category_id": merch.category,
                        "merchant_normalized": merch.code,
                    }
                )
                if profile == "hard" and merch.code in hard_aliases and b.rng.random() < 0.5:
                    tx = tx.model_copy(
                        update={"merchant_raw": f"POS/DEBIT/{hard_aliases[merch.code]}"}
                    )
                result.transactions.append(tx)
                add_truth(tx, merch.category, False, merch.recurring)

    # Generate target month
    y, m = periods[-1]
    pocket = b.rng.randint(*POCKET_MONEY_RUPEES) * 100
    inc_tx = b.make(
        b.moment(y, m, day=1),
        -pocket,
        f"NEFT-CR-ALLOWANCE-REF{b.rng.randint(10**9, 10**10 - 1)}",
        "Allowance",
        primary_acc,
    )
    result.transactions.append(inc_tx)
    add_truth(inc_tx, "income", False, True)

    max_day = 10 if target_cause == "seasonal_or_timing" else None

    # Base merchants for target month
    for merch in MERCHANTS:
        if target_cause in ("more_frequent", "overlapping") and merch.code == "SWIGGY":
            count = b.rng.randint(16, 22)
        elif target_cause == "recurring_change" and merch.code == "RENT":
            continue
        elif target_cause == "miscategorization" and merch.code == "BLINKIT":
            continue
        else:
            count = b.rng.randint(*merch.per_month)

        for _ in range(count):
            moment = b.moment(y, m, day=b.rng.randint(1, max_day) if max_day else None)
            tx = _make_merch_tx(merch, moment)
            tx = tx.model_copy(
                update={
                    "category_id": merch.category,
                    "merchant_normalized": merch.code,
                }
            )
            if profile == "hard" and merch.code in hard_aliases and b.rng.random() < 0.6:
                tx = tx.model_copy(update={"merchant_raw": f"POS/DEBIT/{hard_aliases[merch.code]}"})
            result.transactions.append(tx)
            add_truth(tx, merch.category, False, merch.recurring)

    # Injected Causes execution
    if target_cause == "one_off_large":
        large_tx = b.spend(LARGE_MERCHANT, b.moment(y, m, day=15), primary_acc)
        large_tx = large_tx.model_copy(
            update={
                "category_id": LARGE_MERCHANT.category,
                "merchant_normalized": LARGE_MERCHANT.code,
            }
        )
        result.transactions.append(large_tx)
        add_truth(large_tx, LARGE_MERCHANT.category, False, False, "one_off_large")
        result.ground_truth_causes.append(
            InjectedCause(
                kind="one_off_large",
                category=LARGE_MERCHANT.category,
                month=result.target_month,
                transaction_ids=(large_tx.id,),
                expected_amount_paise=large_tx.amount_paise,
                note="Unusually large purchase at CROMA",
            )
        )
    elif target_cause == "recurring_change":
        rent_hike_paise = 2500_00
        hike_tx = b.make(
            b.moment(y, m, day=1),
            fixed_rent_rupees * 100 + rent_hike_paise,
            b.narration("RENT"),
            "Flat rent (revised lease)",
            primary_acc,
        )
        hike_tx = hike_tx.model_copy(
            update={
                "category_id": "housing",
                "merchant_normalized": "RENT",
            }
        )
        result.transactions.append(hike_tx)
        add_truth(hike_tx, "housing", False, True, "recurring_change")
        result.ground_truth_causes.append(
            InjectedCause(
                kind="recurring_change",
                category="housing",
                month=result.target_month,
                transaction_ids=(hike_tx.id,),
                expected_amount_paise=rent_hike_paise,
                note="Monthly rent increase of ₹2,500 upon lease renewal",
            )
        )
    elif target_cause in ("more_frequent", "overlapping"):
        swiggy_txs = [
            t.id
            for t in result.transactions
            if t.occurred_at.startswith(result.target_month) and "SWIGGY" in (t.merchant_raw or "")
        ]
        result.ground_truth_causes.append(
            InjectedCause(
                kind="more_frequent",
                category="food",
                month=result.target_month,
                transaction_ids=tuple(swiggy_txs),
                expected_amount_paise=sum(
                    t.amount_paise for t in result.transactions if t.id in swiggy_txs
                ),
                note="Higher order frequency at Swiggy",
            )
        )
    if target_cause in ("new_merchant", "overlapping"):
        new_tx = b.spend(NEW_MERCHANT, b.moment(y, m, day=12), primary_acc)
        new_tx = new_tx.model_copy(
            update={
                "category_id": NEW_MERCHANT.category,
                "merchant_normalized": NEW_MERCHANT.code,
            }
        )
        result.transactions.append(new_tx)
        add_truth(new_tx, NEW_MERCHANT.category, False, False, "new_merchant")
        result.ground_truth_causes.append(
            InjectedCause(
                kind="new_merchant",
                category=NEW_MERCHANT.category,
                month=result.target_month,
                transaction_ids=(new_tx.id,),
                expected_amount_paise=new_tx.amount_paise,
                note=f"First spend at new merchant {NEW_MERCHANT.code}",
            )
        )
    elif target_cause == "miscategorization":
        misc_tx = b.make(
            b.moment(y, m, day=18),
            2450_00,
            b.narration("BLINKIT"),
            "Blinkit Quick Delivery",
            primary_acc,
        )
        misc_tx = misc_tx.model_copy(
            update={
                "category_id": "travel",
                "merchant_normalized": "BLINKIT",
            }
        )
        result.transactions.append(misc_tx)
        add_truth(misc_tx, "travel", False, False, "miscategorization")
        result.ground_truth_causes.append(
            InjectedCause(
                kind="miscategorization",
                category="travel",
                month=result.target_month,
                transaction_ids=(misc_tx.id,),
                expected_amount_paise=2450_00,
                note="Blinkit spend miscategorized under travel instead of shopping",
            )
        )
    elif target_cause == "duplicate_or_refund":
        first_at = b.moment(y, m, day=14)
        orig = b.spend(MERCHANTS[1], first_at, primary_acc)
        orig = orig.model_copy(
            update={
                "category_id": MERCHANTS[1].category,
                "merchant_normalized": MERCHANTS[1].code,
            }
        )
        dup = b.make(
            first_at + timedelta(minutes=2),
            orig.amount_paise,
            orig.merchant_raw,
            orig.description,
            primary_acc,
        )
        dup = dup.model_copy(
            update={
                "category_id": MERCHANTS[1].category,
                "merchant_normalized": MERCHANTS[1].code,
                "is_duplicate_of": orig.id,
            }
        )
        refund = b.make(
            first_at + timedelta(days=2),
            -orig.amount_paise,
            f"REFUND-{orig.merchant_raw}",
            "Refund for duplicate charge",
            primary_acc,
        )
        refund = refund.model_copy(
            update={
                "category_id": MERCHANTS[1].category,
                "merchant_normalized": MERCHANTS[1].code,
            }
        )
        result.transactions.extend([orig, dup, refund])
        add_truth(orig, MERCHANTS[1].category, False, False)
        add_truth(dup, MERCHANTS[1].category, False, False, "duplicate_or_refund")
        add_truth(refund, MERCHANTS[1].category, False, False)
        result.ground_truth_causes.append(
            InjectedCause(
                kind="duplicate_or_refund",
                category=MERCHANTS[1].category,
                month=result.target_month,
                transaction_ids=(orig.id, dup.id, refund.id),
                expected_amount_paise=orig.amount_paise,
                note="Duplicate charge with matching refund",
            )
        )
    elif target_cause == "seasonal_or_timing":
        result.ground_truth_causes.append(
            InjectedCause(
                kind="seasonal_or_timing",
                category=None,
                month=result.target_month,
                transaction_ids=(),
                expected_amount_paise=0,
                note="Partial month effect (only 10 days)",
            )
        )
    elif target_cause == "no_cause":
        result.ground_truth_causes.append(
            InjectedCause(
                kind="no_cause",
                category=None,
                month=result.target_month,
                transaction_ids=(),
                expected_amount_paise=0,
                note="Normal unstructured spending variance",
            )
        )

    result.transactions.sort(key=lambda t: (t.occurred_at, t.id))
    return result
