"""
Synthetic data v5: personas for measuring experiment outcomes against known ground truth
(PLAN_PHASE4 section 6). Earlier generators (v1 to v4) are untouched.

Every persona spends on one category (`food`) on most days. The generator knows the truth the
measurement engine has to recover:

* ``reducer``       genuinely spends about 35% less during the experiment window
* ``null``          spends exactly as usual (any "win" is noise)
* ``festival``      has a festival inside the window and another in its history; both are declared
                    as contextual exceptions, so a fair engine must set them aside
* ``recategoriser`` changes nothing, but moves part of the window's payments to another category
                    to make the target look met

Only integers are used: paise, basis points, and a seeded ``random.Random``.
"""

import random
from dataclasses import dataclass, field
from datetime import date, timedelta

DEFAULT_START = "2026-09-01"  # a Tuesday; windows are aligned to this weekday
CATEGORY = "food"
OTHER_CATEGORY = "shopping"


@dataclass(frozen=True)
class V5Persona:
    code: str
    description: str
    prob_pct: int = 55  # chance of a payment on a given day
    mean_paise: int = 24000  # about 240 rupees per payment
    spread_paise: int = 9000
    prob_cut_bp: int = 0  # true behaviour change in the window: fewer payments...
    amount_cut_bp: int = 0  # ...and smaller ones
    festival_days: tuple[int, int] | None = None  # first and last day index inside the window
    festival_multiplier: int = 1
    historic_festival_window: int | None = None  # 1 = the window just before the experiment
    recategorise_share_bp: int = 0  # share of window payments moved to another category


PERSONAS: dict[str, V5Persona] = {
    "reducer": V5Persona(
        "reducer",
        "Orders in less: about 35% lower spend in the window",
        prob_cut_bp=2000,
        amount_cut_bp=1900,
    ),
    "null": V5Persona("null", "No change: the window looks like any other"),
    "festival": V5Persona(
        "festival",
        "A festival inside the window and one in the history, both declared",
        festival_days=(4, 8),
        festival_multiplier=3,
        historic_festival_window=3,
    ),
    "recategoriser": V5Persona(
        "recategoriser",
        "No real change, but moves 45% of window payments to another category",
        recategorise_share_bp=4500,
    ),
}


@dataclass
class V5Truth:
    """What actually happened, for scoring the measurement."""

    persona: str
    true_effect_bp: int  # intended change in expected window spend (positive = spends less)
    window_start: str
    window_end: str
    exception_days: list[str] = field(default_factory=list)  # inside the window
    historic_exception: tuple[str, str] | None = None  # a past window to be set aside
    recategorised_paise: int = 0


@dataclass
class V5Data:
    rows: list[dict]  # one dict per payment: id, occurred_at (UTC), amount_paise, category_id
    truth: V5Truth
    start_date: str
    duration_days: int


def expected_effect_bp(persona: V5Persona) -> int:
    """The intended reduction of expected window spend, in basis points, from the two cuts."""
    kept = (10000 - persona.prob_cut_bp) * (10000 - persona.amount_cut_bp) // 10000
    return 10000 - kept


def generate_persona_data(
    seed: int,
    persona_code: str,
    start_date: str = DEFAULT_START,
    duration_days: int = 14,
    history_windows: int = 8,
) -> V5Data:
    """Payments for the history windows plus the experiment window, with the truth recorded."""
    persona = PERSONAS[persona_code]
    rng = random.Random(seed)
    start = date.fromisoformat(start_date)
    first_day = start - timedelta(days=history_windows * duration_days)
    end = start + timedelta(days=duration_days - 1)

    hist_range: tuple[date, date] | None = None
    if persona.historic_festival_window:
        w = persona.historic_festival_window
        hist_range = (
            start - timedelta(days=w * duration_days),
            start - timedelta(days=(w - 1) * duration_days + 1),
        )
    exception_days: list[date] = []
    if persona.festival_days:
        first, last = persona.festival_days
        exception_days = [start + timedelta(days=i) for i in range(first, last + 1)]

    rows: list[dict] = []
    recategorised = 0
    day = first_day
    n = 0
    while day <= end:
        in_window = day >= start
        prob = persona.prob_pct
        mean = persona.mean_paise
        festival = day in exception_days or (
            hist_range is not None and hist_range[0] <= day <= hist_range[1]
        )
        if festival:
            prob = 100
            mean = mean * persona.festival_multiplier
        elif in_window:
            prob = prob * (10000 - persona.prob_cut_bp) // 10000
            mean = mean * (10000 - persona.amount_cut_bp) // 10000
        if rng.randrange(100) < prob:
            amount = max(100, mean + rng.randint(-persona.spread_paise, persona.spread_paise))
            category = CATEGORY
            if (
                in_window
                and persona.recategorise_share_bp
                and (rng.randrange(10000) < persona.recategorise_share_bp)
            ):
                category = OTHER_CATEGORY  # the move happens later, through the real tool
                recategorised += amount
            n += 1
            rows.append(
                {
                    "id": f"v5_{seed}_{n}",
                    "occurred_at": f"{day.isoformat()}T06:30:00Z",  # noon in IST
                    "amount_paise": amount,
                    "category_id": CATEGORY,
                    "move_to": category if category != CATEGORY else None,
                }
            )
        day += timedelta(days=1)

    truth = V5Truth(
        persona=persona_code,
        true_effect_bp=expected_effect_bp(persona),
        window_start=start.isoformat(),
        window_end=end.isoformat(),
        exception_days=[d.isoformat() for d in exception_days],
        historic_exception=(
            (hist_range[0].isoformat(), hist_range[1].isoformat()) if hist_range else None
        ),
        recategorised_paise=recategorised,
    )
    return V5Data(rows=rows, truth=truth, start_date=start_date, duration_days=duration_days)
