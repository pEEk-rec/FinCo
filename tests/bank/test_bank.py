from collections import Counter

import pytest

from copilot.audit.events import list_events
from copilot.bank.loader import ingest_transactions, parse_record
from copilot.bank.mock_bank import MockBankConnector, to_raw_record
from copilot.bank.synth import MERCHANTS, NEW_MERCHANT, generate_transactions
from copilot.core.errors import ErrorCode, ToolFailure
from copilot.core.timeutil import month_bounds, month_of
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_account, insert_user, list_transactions
from copilot.models.domain import Account, User

T0 = "2024-01-01T00:00:00Z"
ALL_TIME = ("2020-01-01T00:00:00Z", "2030-01-01T00:00:00Z")


def gen(seed: int = 42, months: int = 3):
    return generate_transactions(seed, months, "u1", "a1")


# ---------------------------------------------------------------------------------------------
# Synthetic data
# ---------------------------------------------------------------------------------------------


def test_same_seed_identical_output():
    first, second = gen(7), gen(7)
    assert [t.model_dump() for t in first.transactions] == [
        t.model_dump() for t in second.transactions
    ]
    assert first.ground_truth == second.ground_truth


def test_different_seeds_differ():
    assert [t.id for t in gen(1).transactions] != [t.id for t in gen(2).transactions]


def test_shape_of_generated_data():
    result = gen(months=3)
    txs = result.transactions
    assert len({t.id for t in txs}) == len(txs)  # unique ids
    assert txs == sorted(txs, key=lambda t: (t.occurred_at, t.id))
    assert {month_of(t.occurred_at) for t in txs} == {(2024, 1), (2024, 2), (2024, 3)}
    assert all(t.category_source == "none" and t.category_id is None for t in txs)
    # One pocket-money credit per month, everything else is spend
    credits = [t for t in txs if t.direction == "credit"]
    assert len(credits) == 3
    assert all(t.amount_paise < 0 for t in credits)


def test_merchant_strings_are_messy():
    raws = [t.merchant_raw for t in gen().transactions if t.direction == "debit"]
    assert any(r.startswith("UPI-SWIGGY-") for r in raws)
    assert any("@" in r for r in raws)
    assert len(set(raws)) > len(MERCHANTS)  # same merchant, many spellings/refs


def test_ground_truth_anomalies_present():
    result = gen(months=3)
    by_id = {t.id: t for t in result.transactions}
    kinds = {a.kind: a for a in result.ground_truth}
    assert set(kinds) == {"large_transaction", "duplicate_charge", "new_merchant"}
    for anomaly in result.ground_truth:
        assert all(tx_id in by_id for tx_id in anomaly.transaction_ids)
        # All planted in the last month
        assert all(month_of(by_id[i].occurred_at) == (2024, 3) for i in anomaly.transaction_ids)

    [large_id] = kinds["large_transaction"].transaction_ids
    regular_max = max(t.amount_paise for t in result.transactions if t.id not in {large_id})
    assert by_id[large_id].amount_paise >= 1_800_000
    assert by_id[large_id].amount_paise > regular_max

    first, second = (by_id[i] for i in kinds["duplicate_charge"].transaction_ids)
    assert (first.merchant_raw, first.amount_paise) == (second.merchant_raw, second.amount_paise)
    assert first.id != second.id
    assert first.occurred_at < second.occurred_at

    [new_id] = kinds["new_merchant"].transaction_ids
    new_merchant_txs = [t for t in result.transactions if NEW_MERCHANT.code in t.merchant_raw]
    assert [t.id for t in new_merchant_txs] == [new_id]


def test_months_must_be_positive():
    with pytest.raises(ValueError):
        generate_transactions(1, 0, "u1", "a1")


# ---------------------------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------------------------


def test_raw_record_round_trips_through_parser():
    for tx in gen(months=1).transactions:
        assert parse_record(to_raw_record(tx), "u1") == tx


def test_connector_filters_by_range():
    bank = MockBankConnector.from_seed(42, 3, "u1", "a1")
    start, end = month_bounds(2024, 2)
    records = bank.fetch_transactions("a1", start, end)
    assert records
    assert all(start <= r["posted_at"] < end for r in records)


@pytest.mark.parametrize(
    "account, start, end, code",
    [
        ("nope", *ALL_TIME, ErrorCode.NOT_FOUND),
        ("a1", ALL_TIME[1], ALL_TIME[0], ErrorCode.INVALID_INPUT),
    ],
)
def test_connector_rejects_bad_requests(account, start, end, code):
    bank = MockBankConnector.from_seed(42, 1, "u1", "a1")
    with pytest.raises(ToolFailure) as info:
        bank.fetch_transactions(account, start, end)
    assert info.value.error.code == code


def test_connector_simulated_failure():
    bank = MockBankConnector.from_seed(42, 1, "u1", "a1", fail=True)
    with pytest.raises(ToolFailure) as info:
        bank.fetch_transactions("a1", *ALL_TIME)
    assert info.value.error.code == ErrorCode.TOOL_FAILURE
    assert info.value.error.retryable is True


@pytest.mark.parametrize(
    "change",
    [{"type": "XX"}, {"amount": "12.345"}, {"amount": "0.00"}, {"posted_at": "yesterday"}],
)
def test_parse_record_rejects_malformed(change):
    record = to_raw_record(gen(months=1).transactions[0]) | change
    with pytest.raises(ValueError):
        parse_record(record, "u1")


# ---------------------------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------------------------


@pytest.fixture
def conn():
    c = get_connection(":memory:")
    init_db(c)
    insert_user(c, User(id="u1", created_at=T0))
    insert_account(c, Account(id="a1", user_id="u1", name="Savings", created_at=T0))
    c.commit()
    return c


def test_loader_inserts_expected_rows(conn):
    result = gen(months=3)
    bank = MockBankConnector(result.transactions)
    report = ingest_transactions(conn, bank, "u1", "a1", *ALL_TIME)
    assert (report.fetched, report.inserted, report.skipped_existing) == (
        len(result.transactions),
        len(result.transactions),
        0,
    )
    stored = list_transactions(conn, "u1", *ALL_TIME)
    assert stored == result.transactions
    [event] = list_events(conn, "u1", event_type="transactions_ingested")
    assert event.metadata["inserted"] == len(result.transactions)


def test_loader_is_idempotent(conn):
    bank = MockBankConnector.from_seed(42, 2, "u1", "a1")
    first = ingest_transactions(conn, bank, "u1", "a1", *ALL_TIME)
    second = ingest_transactions(conn, bank, "u1", "a1", *ALL_TIME)
    assert second.inserted == 0
    assert second.skipped_existing == first.inserted
    assert len(list_transactions(conn, "u1", *ALL_TIME)) == first.inserted


def test_duplicate_charge_is_loaded_not_deduplicated(conn):
    result = gen(months=3)
    ingest_transactions(conn, MockBankConnector(result.transactions), "u1", "a1", *ALL_TIME)
    [dup] = [a for a in result.ground_truth if a.kind == "duplicate_charge"]
    stored_ids = {t.id for t in list_transactions(conn, "u1", *ALL_TIME)}
    assert set(dup.transaction_ids) <= stored_ids
    raws = Counter(t.merchant_raw for t in list_transactions(conn, "u1", *ALL_TIME))
    assert raws.most_common(1)[0][1] == 2


def test_loader_reports_connector_failure_and_writes_nothing(conn):
    bank = MockBankConnector.from_seed(42, 1, "u1", "a1", fail=True)
    with pytest.raises(ToolFailure) as info:
        ingest_transactions(conn, bank, "u1", "a1", *ALL_TIME)
    assert info.value.error.code == ErrorCode.TOOL_FAILURE
    assert list_transactions(conn, "u1", *ALL_TIME) == []
    assert list_events(conn, "u1") == []


def test_loader_rejects_batch_with_malformed_record(conn):
    class BrokenBank:
        def fetch_transactions(self, account_id, start, end):
            good = to_raw_record(gen(months=1).transactions[0])
            return [good, good | {"amount": "abc"}]

    with pytest.raises(ToolFailure) as info:
        ingest_transactions(conn, BrokenBank(), "u1", "a1", *ALL_TIME)
    assert info.value.error.code == ErrorCode.INVALID_INPUT
    assert list_transactions(conn, "u1", *ALL_TIME) == []  # all or nothing


def test_loader_unknown_account(conn):
    bank = MockBankConnector.from_seed(42, 1, "u1", "a1")
    with pytest.raises(ToolFailure) as info:
        ingest_transactions(conn, bank, "u1", "missing", *ALL_TIME)
    assert info.value.error.code == ErrorCode.NOT_FOUND
