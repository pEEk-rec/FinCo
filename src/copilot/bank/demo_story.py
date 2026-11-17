"""
The demo bank's story: a student's last ~11 weeks, ending yesterday, built from today's date.

Why this exists: the older synthetic bank is dated early 2024, so on a real clock the current month
looks empty. This one is always "recent", so the dashboard, the budget pace and the review inbox
all have something true to show the moment the bank is connected.

It reads like a student's real month, spread over many kinds of spending: eating (mess, canteen,
Swiggy), groceries, getting about, shopping, films, subscriptions, a pharmacy, a salon, a course,
rent and the monthly allowance. Most payments are ones a rule recognises. About one in six is not
(a tea stall, a friend, a book shop), so the Review inbox has real work and the "answer once,
settle them all" flow has something to teach. Everything is deterministic: the same day always
produces the same story.

`LIVE_PAYMENTS` is what the demo's "next live payment" button plays, in order: a first-time
shop and a friend (both ask), a known merchant (labelled silently), then more of each.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta

from copilot.common.timeutil import IST, to_utc_iso
from copilot.models.domain import Transaction

SEED = 2026
DAYS = 78  # about eleven weeks, ending yesterday


@dataclass(frozen=True)
class LivePayment:
    counterparty: str
    vpa: str
    amount_paise: int
    note: str  # what the demo audience should notice


LIVE_PAYMENTS: tuple[LivePayment, ...] = (
    LivePayment("Gupta Juice Centre", "guptajuice@okicici", 8000, "a new shop: it asks you"),
    LivePayment("Swiggy", "swiggy@icici", 34900, "a known app: tagged silently, with Change"),
    LivePayment("Rahul Sharma", "rahul.sharma@okhdfcbank", 45000, "a friend: always asks"),
    LivePayment("Apollo Pharmacy", "apollopharmacy@icici", 26000, "a pharmacy: tagged Health"),
    LivePayment("Campus Book Depot", "campusbooks@ybl", 64000, "another new shop: it asks"),
    LivePayment("Zepto", "zepto@icici", 42800, "groceries: tagged silently"),
    LivePayment("Ankita Verma", "ankita.v@okaxis", 25000, "a friend splitting dinner: asks"),
    LivePayment("BookMyShow", "bookmyshow@icici", 52000, "a movie night: tagged Entertainment"),
    LivePayment("Sharma Tea Stall", "sharmatea@paytm", 2000, "a small stall: asks"),
    LivePayment(
        "Urban Company", "urbancompany@axisbank", 49900, "a salon visit: tagged Personal care"
    ),
)


def _ref(rng: random.Random) -> str:
    return "".join(rng.choice("0123456789") for _ in range(12))


def _at(day: datetime, hour: int, rng: random.Random) -> str:
    return to_utc_iso(day.replace(hour=hour, minute=rng.randint(0, 59), second=0, microsecond=0))


# (day of month, hour, narration, rupees or (low, high), note, is a credit)
MONTHLY: tuple[tuple[int, int, str, int | tuple[int, int], str, bool], ...] = (
    (1, 9, "NEFT-CR-ALLOWANCE", 14000, "Allowance", True),
    (3, 10, "UPI-YOUTUBE PREMIUM-youtube@okicici", 129, "YouTube Premium", False),
    (5, 11, "NEFT-HOSTEL RENT", 6500, "Hostel rent", False),
    (7, 18, "UPI-CULT FIT-cultfit@okicici", 799, "Gym", False),
    (8, 10, "UPI-HOTSTAR-hotstar@icici", 149, "Hotstar", False),
    (12, 20, "UPI-JIORECHARGE-jio@ybl", 299, "Mobile recharge", False),
    (14, 11, "UPI-UNACADEMY-unacademy@icici", 499, "Course", False),
    (15, 12, "UPI-CAMPUS BOOK DEPOT-campusbooks@ybl", 540, "Books", False),
    (20, 19, "UPI-BESCOM-bescom@sbi", (300, 480), "Electricity share", False),
)

# (narration, chance per day, lowest rupees, highest rupees, hour, "any" | "weekday" | "weekend")
DAILY: tuple[tuple[str, float, int, int, int, str], ...] = (
    # Eating: the mess every weekday, the canteen, the odd order in.
    ("UPI-HOSTELMESS-hostelmess@ybl", 0.80, 55, 75, 13, "weekday"),
    ("UPI-CANTEEN-canteen@ybl", 0.25, 25, 50, 16, "any"),
    ("UPI-SWIGGY-swiggy@icici", 0.07, 180, 350, 21, "any"),
    ("UPI-ZOMATO-zomato@icici", 0.04, 200, 400, 22, "any"),
    ("UPI-DOMINOS-dominos@icici", 0.02, 250, 450, 20, "weekend"),
    ("UPI-STARBUCKS-starbucks@icici", 0.015, 280, 420, 17, "weekend"),
    # Groceries: the quick-commerce top-up, the weekly shop, the corner store.
    ("UPI-ZEPTO-zepto@icici", 0.05, 150, 400, 19, "any"),
    ("UPI-BIGBASKET-bigbasket@icici", 0.015, 400, 800, 11, "weekend"),
    ("UPI-DMART-dmart@icici", 0.015, 600, 1000, 18, "weekend"),
    ("UPI-RAMESH GENERAL STORE-rameshgs@okaxis", 0.06, 40, 160, 18, "any"),
    # Getting about.
    ("UPI-RAPIDO-rapido@ybl", 0.10, 35, 85, 9, "any"),
    ("UPI-DELHI METRO-dmrc@sbi", 0.08, 30, 100, 8, "weekday"),
    ("UPI-UBER INDIA-uber@axisbank", 0.03, 110, 240, 8, "any"),
    ("UPI-REDBUS-redbus@icici", 0.012, 400, 800, 7, "weekend"),
    # Shopping.
    ("UPI-AMAZON PAY-amazon@apl", 0.03, 300, 1200, 18, "any"),
    ("UPI-FLIPKART-flipkart@axisbank", 0.015, 400, 1200, 19, "any"),
    ("UPI-MYNTRA-myntra@ybl", 0.012, 600, 1500, 20, "weekend"),
    ("UPI-NYKAA-nykaa@icici", 0.012, 300, 800, 20, "any"),
    # Fun.
    ("UPI-BOOKMYSHOW-bookmyshow@icici", 0.035, 250, 600, 19, "weekend"),
    ("UPI-STEAM-steam@axisbank", 0.01, 200, 500, 22, "any"),
    # Health and looking after yourself.
    ("UPI-APOLLO PHARMACY-apollopharmacy@icici", 0.03, 100, 450, 17, "any"),
    ("UPI-MEDPLUS-medplus@ybl", 0.012, 80, 300, 17, "any"),
    ("UPI-URBAN COMPANY-urbancompany@axisbank", 0.12, 300, 600, 15, "weekend"),
    ("UPI-NATURALS SALON-naturals@ybl", 0.05, 250, 450, 16, "weekend"),
    # The ones nothing recognises: they are what Review is for.
    ("UPI-SHARMA TEA STALL-sharmatea@paytm", 0.08, 10, 20, 17, "any"),
    ("UPI-RAJU CHAAT CORNER-rajuchaat@ybl", 0.02, 40, 120, 18, "any"),
    ("UPI-GUPTA JUICE CENTRE-guptajuice@okicici", 0.035, 60, 90, 17, "any"),
    ("UPI-SRI BALAJI MEDICALS-balajimed@ybl", 0.015, 80, 300, 17, "any"),
    ("UPI-SHARMA STATIONERS-sharma77@paytm", 0.015, 40, 150, 11, "weekday"),
    ("UPI-CITY CYCLE WORKS-citycycle@ibl", 0.008, 300, 600, 12, "any"),
)


def build_demo_story(user_id: str, account_id: str, now: datetime) -> list[Transaction]:
    """Every payment the demo bank holds, oldest first. `now` is the app's clock."""
    today = now.astimezone(IST).replace(hour=0, minute=0, second=0, microsecond=0)
    out: list[Transaction] = []

    def add(day: datetime, hour: int, rng: random.Random, narration: str, rupees: int, **kw: str):
        credit = kw.get("credit") == "1"
        when = _at(day, hour, rng)
        paise = rupees * 100
        out.append(
            Transaction(
                id=f"demo_story_{len(out):04d}",
                user_id=user_id,
                account_id=account_id,
                occurred_at=when,
                amount_paise=-paise if credit else paise,
                direction="credit" if credit else "debit",
                merchant_raw=narration,
                description=kw.get("note", "UPI payment"),
                created_at=when,
            )
        )

    for back in range(DAYS, 0, -1):
        day = today - timedelta(days=back)
        rng = random.Random(f"{SEED}-{day.date()}")
        weekday = day.weekday() < 5
        weekend = not weekday

        # Once a month: the money in, the fixed bills, the subscriptions, the course.
        for dom, hour, narr, amount, note, credit in MONTHLY:
            if day.day == dom:
                add(
                    day,
                    hour,
                    rng,
                    f"{narr}-REF{_ref(rng)}",
                    amount if isinstance(amount, int) else rng.randint(*amount),
                    credit="1" if credit else "0",
                    note=note,
                )
        if day.day in (9, 24):  # a train home twice a month
            add(day, 7, rng, f"UPI-IRCTC-irctc@sbi-REF{_ref(rng)}", rng.randint(260, 420))

        # Everyday spending: each line is a chance on this day.
        for narr, chance, low, high, hour, when in DAILY:
            if when == "weekday" and not weekday:
                continue
            if when == "weekend" and not weekend:
                continue
            if rng.random() < chance:
                add(day, hour, rng, f"{narr}-REF{_ref(rng)}", rng.randint(low, high))

        # A friend, now and then: a person, so FinCo always asks.
        if rng.random() < 0.04:
            friend = rng.choice(["RAHUL SHARMA", "ANKITA VERMA", "SIDDHARTH RAO"])
            handle = friend.split()[0].lower()
            add(day, 20, rng, f"UPI-{friend}-{handle}@okaxis-REF{_ref(rng)}", rng.randint(150, 800))
    return out
