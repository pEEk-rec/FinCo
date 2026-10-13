from collections import namedtuple

from copilot.core.forecast import forecast_month

Tx = namedtuple(
    "Tx",
    [
        "amount_paise",
        "merchant_normalized",
        "merchant_raw",
        "direction",
        "excluded_from_spend",
        "is_duplicate_of",
    ],
)
Series = namedtuple("Series", ["merchant_normalized", "typical_amount_paise"])


def test_forecast_month():
    txs = [
        Tx(2000, "Netflix", "NETFLIX", "debit", False, None),
        Tx(500, "Coffee", "COFFEE", "debit", False, None),
    ]
    series = [
        Series("Netflix", 2000),
        Series("Spotify", 1000),
    ]

    res = forecast_month(txs, series, days_elapsed=15, days_in_month=30)

    assert res["breakdown"]["spent_fixed"] == 2000
    assert res["breakdown"]["pending_fixed"] == 1000
    assert res["breakdown"]["spent_variable"] == 500
    # Variable is 500 in 15 days -> 1000 in 30 days
    assert res["breakdown"]["projected_variable"] == 1000

    assert res["projected_total"] == 2000 + 1000 + 1000
    assert not res["insufficient_data"]

    res2 = forecast_month(txs, series, days_elapsed=2, days_in_month=30)
    assert res2["insufficient_data"]
