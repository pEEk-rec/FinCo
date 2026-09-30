import pytest
from pydantic import ValidationError

from copilot.models.domain import Account, Budget, Transaction


def make_tx(**overrides) -> Transaction:
    data = {
        "id": "t1",
        "user_id": "u1",
        "account_id": "a1",
        "occurred_at": "2024-01-15T10:00:00Z",
        "amount_paise": 1000,
        "direction": "debit",
        "merchant_raw": "m",
        "description": "d",
        "created_at": "2024-01-15T10:00:00Z",
    }
    data.update(overrides)
    return Transaction(**data)


def test_valid_transaction():
    tx = make_tx()
    assert tx.amount_paise == 1000
    assert tx.category_source == "none"


@pytest.mark.parametrize("bad", [1000.0, "1000", True])
def test_amount_must_be_real_int(bad):
    with pytest.raises(ValidationError):
        make_tx(amount_paise=bad)


@pytest.mark.parametrize(
    "direction, amount", [("debit", -1), ("credit", 1), ("debit", 0), ("credit", 0)]
)
def test_sign_must_match_direction(direction, amount):
    with pytest.raises(ValidationError, match="amount_paise"):
        make_tx(direction=direction, amount_paise=amount)


def test_timestamp_normalised_to_canonical_utc():
    # 23:30 IST on Jan 31 is stored as 18:00Z so string comparison files it in January
    tx = make_tx(occurred_at="2024-01-31T23:30:00+05:30")
    assert tx.occurred_at == "2024-01-31T18:00:00Z"


@pytest.mark.parametrize("bad", ["yesterday", "2024-01-31T18:00:00", ""])
def test_bad_timestamp_rejected(bad):
    with pytest.raises(ValidationError):
        make_tx(occurred_at=bad)


def test_unknown_field_rejected():
    with pytest.raises(ValidationError, match="amount_rupees"):
        make_tx(amount_rupees=5)


def test_empty_id_rejected():
    with pytest.raises(ValidationError):
        make_tx(id="")


def test_budget_limit_must_be_int():
    with pytest.raises(ValidationError):
        Budget(id="b", user_id="u1", category_id="c1", limit_paise=500.0, warn_threshold_pct=80)
    with pytest.raises(ValidationError):
        Budget(id="b", user_id="u1", category_id="c1", limit_paise=-1, warn_threshold_pct=80)


def test_account_opening_balance():
    acc = Account(id="a1", user_id="u1", name="Savings", created_at="2024-01-01T00:00:00Z")
    assert acc.opening_balance_paise == 0
    with pytest.raises(ValidationError):
        Account(
            id="a1",
            user_id="u1",
            name="S",
            created_at="2024-01-01T00:00:00Z",
            opening_balance_paise=10.5,
        )
