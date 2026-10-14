"""
Demo content for the rails: a day of bank alerts, the receipt that explains one of them, and the
statement rows the bank posts the next morning (a stand-in for the nightly Account Aggregator sync).
"""

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from copilot.core.timeutil import from_utc_iso, now_utc, to_utc_iso
from copilot.rails.engine import ReconcileOut, categorize, ensure_schema, reconcile

ALERTS = [
    {
        "label": "SBI debit: Swiggy",
        "text": "Dear SBI User, your A/c X1234-debited by Rs 480.00 on 18Mar24 transfer to SWIGGY "
        "Ref No 428912345678. If not done by you forward this SMS to 1800111109. Avl Bal Rs 5,210",
    },
    {
        "label": "HDFC UPI: Zomato party order",
        "text": "Rs 2350.00 debited from a/c **1234 on 18-03-24 to VPA zomato@icici "
        "(UPI Ref No 428912345679). Not you? Call HDFC",
    },
    {
        "label": "ICICI: college canteen",
        "text": "ICICI Bank Acct XX1234 debited for Rs 60.00 on 18-Mar-24; CANTEEN credited. "
        "UPI:428912345680.",
    },
    {
        "label": "Axis UPI: Amazon Pay",
        "text": "INR 850.00 debited from A/c no. XX1234 on 18-03-2024 11:42:11 "
        "UPI/P2M/428987654321/AMAZON PAY",
    },
    {
        "label": "HDFC card: DMart",
        "text": "Spent Rs.1,249.00 on HDFC Bank Card x4012 at DMART PUNE on 18-03-24",
    },
    {
        "label": "UPI to a person (needs your input)",
        "text": "INR 500.00 debited from A/c XX1234 UPI/P2A/428911111111/SURESH KUMAR",
    },
]

NOISE = [
    {
        "label": "OTP message (ignored)",
        "text": "Your OTP is 481516 for a payment of Rs 850. Do not share.",
    },
    {
        "label": "Autopay notice (ignored)",
        "text": "Rs 999.00 will be debited on 20-03-24 via autopay mandate for NETFLIX.",
    },
]

RECEIPT = """Amazon.in
Order #402-1873645
Python Textbook x1 ₹600.00
Chips x2 ₹200.00
Chocolate ₹50.00
Delivery ₹40.00
Discount -₹40.00
Total ₹850.00
Paid via UPI"""

# (minutes after the alert, amount in paise, narration, direction): what the bank posts next day
_STATEMENT = [
    (35, 48000, "UPI-SWIGGY-428912345678-swiggy@icici", "debit"),
    (40, 235000, "UPI/ZOMATO/zomato@icici/428912345679", "debit"),
    (45, 6000, "UPI/CANTEEN/canteen4410@oksbi/428912345680", "debit"),
    (50, 85000, "UPI/AMAZON PAY/428987654321", "debit"),
    (55, 124900, "POS 4012XXXXXXXX1234 DMART PUNE IN", "debit"),
    (60, 200000, "ATM-WDL/CASH/HDFC00012/KOTHRUD PUNE", "debit"),
]
_ALERT_TIMES = {
    0: "2024-03-18T05:42:00Z",
    1: "2024-03-18T06:30:00Z",
    2: "2024-03-18T06:30:00Z",
    3: "2024-03-18T06:12:11Z",
    4: "2024-03-18T06:30:00Z",
    5: "2024-03-18T06:30:00Z",
}


@dataclass
class SyncOut:
    posted: int
    skipped_existing: int
    reconcile: ReconcileOut


def nightly_sync(conn: sqlite3.Connection, user_id: str, clock: datetime | None) -> SyncOut:
    """
    Post the statement rows (idempotent, like real ingestion) and reconcile alerts against them.

    The row id is a hash of account, time, amount and narration, so syncing twice adds nothing.
    """
    ensure_schema(conn)
    now = now_utc(clock)
    base = from_utc_iso("2024-03-18T06:30:00Z")
    posted = skipped = 0
    for minutes, paise, narration, direction in _STATEMENT:
        when = to_utc_iso(base + timedelta(hours=14, minutes=minutes))  # posted next morning
        # the statement carries the original payment time, not the posting time
        occurred = to_utc_iso(base + timedelta(minutes=minutes - 35))
        key = f"a1|{occurred}|{paise}|{narration}"
        tid = "aa_sync_" + hashlib.sha256(key.encode()).hexdigest()[:20]
        category, source = categorize(narration, paise, direction)
        cur = conn.execute(
            "INSERT OR IGNORE INTO transactions (id, user_id, account_id, occurred_at, amount_paise,"
            " direction, merchant_raw, description, category_id, category_confidence,"
            " category_source, created_at) VALUES (?, ?, 'a1', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                tid,
                user_id,
                occurred,
                paise,
                direction,
                narration,
                "Statement row",
                category,
                0.9 if category else None,
                "rule" if category else "none",
                when,
            ),
        )
        posted += cur.rowcount
        skipped += 1 - cur.rowcount
    return SyncOut(
        posted=posted, skipped_existing=skipped, reconcile=reconcile(conn, user_id, clock)
    )


def reset(conn: sqlite3.Connection, user_id: str) -> None:
    """Back to the start of the day: drop rail records and the synced statement rows."""
    ensure_schema(conn)
    conn.execute("DELETE FROM rail_splits WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM rail_events WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM transactions WHERE id LIKE 'aa_sync_%'")
