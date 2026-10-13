from typing import Any, NamedTuple


class Series(NamedTuple):
    merchant_normalized: str
    typical_amount_paise: int


def forecast_month(
    txs: list[Any],
    recurring_series: list[Any],
    days_elapsed: int,
    days_in_month: int,
) -> dict:
    """
    Project month-end spend splitting fixed vs variable.
    """
    if days_elapsed <= 0:
        days_elapsed = 1  # prevent division by zero for day 0

    spent_fixed = 0
    spent_variable = 0

    # merchants that are part of recurring series
    recurring_merchants = {s.merchant_normalized for s in recurring_series}

    paid_recurring_merchants = set()

    for tx in txs:
        if tx.direction == "credit" or tx.excluded_from_spend or tx.is_duplicate_of:
            continue

        merchant = tx.merchant_normalized or tx.merchant_raw
        if merchant in recurring_merchants:
            spent_fixed += tx.amount_paise
            paid_recurring_merchants.add(merchant)
        else:
            spent_variable += tx.amount_paise

    pending_fixed = 0
    for s in recurring_series:
        if s.merchant_normalized not in paid_recurring_merchants:
            pending_fixed += s.typical_amount_paise

    # Run rate for variable
    projected_variable = (spent_variable * days_in_month) // days_elapsed

    total_projected = spent_fixed + pending_fixed + projected_variable

    # Range: +/- 20% on variable
    margin = int(projected_variable * 0.2)

    return {
        "spent_so_far": spent_fixed + spent_variable,
        "projected_total": total_projected,
        "projected_range": (total_projected - margin, total_projected + margin),
        "breakdown": {
            "spent_fixed": spent_fixed,
            "pending_fixed": pending_fixed,
            "spent_variable": spent_variable,
            "projected_variable": projected_variable,
        },
        "insufficient_data": days_elapsed < 3,
    }
