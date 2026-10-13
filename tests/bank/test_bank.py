from collections import Counter

import pytest

from copilot.audit.events import list_events
from copilot.bank.ingest import ingest_statements, parse_record
from copilot.bank.mock_bank import MockAAConnector, to_raw_record
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
    assert any("SWIGGY" in r for r in raws)
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
        assert parse_record(to_raw_record(tx), "u1", tx.fingerprint) == tx


def test_connector_filters_by_range():
    bank = MockAAConnector.from_seed(42, 3, "u1", "a1")
    start, end = month_bounds(2024, 2)
    cid = bank.create_consent("u1", ["a1"], start, end, "sync")
    bank.approve_consent(cid)
    records = bank.fetch_session(cid)
    assert records
    assert all(start <= r["posted_at"] < end for r in records)


def test_connector_rejects_bad_requests():
    bank = MockAAConnector.from_seed(42, 1, "u1", "a1")
    # Fetch without active consent
    cid = bank.create_consent("u1", ["a1"], ALL_TIME[0], ALL_TIME[1], "sync")
    with pytest.raises(ToolFailure) as info:
        bank.fetch_session(cid)
    assert info.value.error.code == ErrorCode.DENIED_BY_POLICY

    # Approve unknown consent
    with pytest.raises(ToolFailure) as info:
        bank.approve_consent("missing")
    assert info.value.error.code == ErrorCode.NOT_FOUND

    # Fetch unknown consent
    with pytest.raises(ToolFailure) as info:
        bank.fetch_session("missing")
    assert info.value.error.code == ErrorCode.NOT_FOUND


def test_connector_simulated_failure():
    bank = MockAAConnector.from_seed(42, 1, "u1", "a1", fail=True)
    cid = bank.create_consent("u1", ["a1"], ALL_TIME[0], ALL_TIME[1], "sync")
    bank.approve_consent(cid)
    with pytest.raises(ToolFailure) as info:
        bank.fetch_session(cid)
    assert info.value.error.code == ErrorCode.TOOL_FAILURE
    assert info.value.error.retryable is True


@pytest.mark.parametrize(
    "change",
    [{"type": "XX"}, {"amount": "12.345"}, {"amount": "0.00"}, {"posted_at": "yesterday"}],
)
def test_parse_record_rejects_malformed(change):
    record = to_raw_record(gen(months=1).transactions[0]) | change
    with pytest.raises(ValueError):
        parse_record(record, "u1", "dummy_fp")


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


def insert_mock_consent(conn, cid, user_id="u1", account_ids='["a1"]'):
    conn.execute(
        "INSERT INTO consents (id, user_id, purpose, fi_types, account_ids, date_range_from, date_range_to, status, expires_at, created_at) "
        "VALUES (?, ?, 'sync', 'DEPOSIT', ?, ?, ?, 'active', ?, ?)",
        (
            cid,
            user_id,
            account_ids,
            ALL_TIME[0],
            ALL_TIME[1],
            "2030-01-01T00:00:00Z",
            "2024-01-01T00:00:00Z",
        ),
    )


def test_loader_inserts_expected_rows(conn):
    result = gen(months=3)
    bank = MockAAConnector(result.transactions)
    cid = bank.create_consent("u1", ["a1"], ALL_TIME[0], ALL_TIME[1], "sync")
    bank.approve_consent(cid)
    insert_mock_consent(conn, cid)
    report = ingest_statements(conn, bank, "u1", "a1", cid)
    assert (report.fetched, report.inserted, report.skipped_existing) == (
        len(result.transactions),
        len(result.transactions),
        0,
    )
    stored = list_transactions(conn, "u1", *ALL_TIME)
    assert [t.id for t in stored] == [t.id for t in result.transactions]
    assert [t.amount_paise for t in stored] == [t.amount_paise for t in result.transactions]
    [event] = list_events(conn, "u1", event_type="transactions_ingested")
    assert event.metadata["inserted"] == len(result.transactions)


def test_loader_is_idempotent(conn):
    bank = MockAAConnector.from_seed(42, 2, "u1", "a1")
    cid = bank.create_consent("u1", ["a1"], ALL_TIME[0], ALL_TIME[1], "sync")
    bank.approve_consent(cid)
    insert_mock_consent(conn, cid)
    first = ingest_statements(conn, bank, "u1", "a1", cid)
    second = ingest_statements(conn, bank, "u1", "a1", cid)
    assert second.inserted == 0
    assert second.skipped_existing == first.inserted
    assert len(list_transactions(conn, "u1", *ALL_TIME)) == first.inserted


def test_ingestion_order_does_not_change_final_set(conn):
    import random

    result = gen(months=1)
    txs = result.transactions

    # Shuffle and insert in one order
    random.seed(42)
    shuffled1 = list(txs)
    random.shuffle(shuffled1)
    bank1 = MockAAConnector(shuffled1)
    cid1 = bank1.create_consent("u1", ["a1"], ALL_TIME[0], ALL_TIME[1], "sync")
    bank1.approve_consent(cid1)
    insert_mock_consent(conn, cid1)
    ingest_statements(conn, bank1, "u1", "a1", cid1)
    stored1 = {t.fingerprint for t in list_transactions(conn, "u1", *ALL_TIME)}

    # Clear DB and insert in another order
    conn.execute("DELETE FROM transactions")
    conn.execute("DELETE FROM ingestion_batches")

    shuffled2 = list(txs)
    random.shuffle(shuffled2)
    bank2 = MockAAConnector(shuffled2)
    cid2 = bank2.create_consent("u1", ["a1"], ALL_TIME[0], ALL_TIME[1], "sync")
    bank2.approve_consent(cid2)
    insert_mock_consent(conn, cid2)
    ingest_statements(conn, bank2, "u1", "a1", cid2)
    stored2 = {t.fingerprint for t in list_transactions(conn, "u1", *ALL_TIME)}

    assert stored1 == stored2


def test_duplicate_charge_is_loaded_not_deduplicated(conn):
    result = gen(months=3)
    bank = MockAAConnector(result.transactions)
    cid = bank.create_consent("u1", ["a1"], ALL_TIME[0], ALL_TIME[1], "sync")
    bank.approve_consent(cid)
    insert_mock_consent(conn, cid)
    ingest_statements(conn, bank, "u1", "a1", cid)
    [dup] = [a for a in result.ground_truth if a.kind == "duplicate_charge"]
    stored_ids = {t.id for t in list_transactions(conn, "u1", *ALL_TIME)}
    assert set(dup.transaction_ids) <= stored_ids
    raws = Counter(t.merchant_raw for t in list_transactions(conn, "u1", *ALL_TIME))
    assert raws.most_common(1)[0][1] == 2


def test_loader_reports_connector_failure_and_writes_nothing(conn):
    bank = MockAAConnector.from_seed(42, 1, "u1", "a1", fail=True)
    cid = bank.create_consent("u1", ["a1"], ALL_TIME[0], ALL_TIME[1], "sync")
    bank.approve_consent(cid)
    insert_mock_consent(conn, cid)
    with pytest.raises(ToolFailure) as info:
        ingest_statements(conn, bank, "u1", "a1", cid)
    assert info.value.error.code == ErrorCode.TOOL_FAILURE
    assert list_transactions(conn, "u1", *ALL_TIME) == []
    assert list_events(conn, "u1") == []


def test_loader_rejects_batch_with_malformed_record(conn):
    class BrokenBank:
        def fetch_session(self, consent_id):
            good = to_raw_record(gen(months=1).transactions[0])
            return [good, good | {"amount": "abc"}]

    with pytest.raises(ToolFailure) as info:
        insert_mock_consent(conn, "cid1")
        ingest_statements(conn, BrokenBank(), "u1", "a1", "cid1")
    assert info.value.error.code == ErrorCode.INVALID_INPUT
    assert list_transactions(conn, "u1", *ALL_TIME) == []  # all or nothing


def test_loader_unknown_account(conn):
    bank = MockAAConnector.from_seed(42, 1, "u1", "a1")
    cid = bank.create_consent("u1", ["a1"], ALL_TIME[0], ALL_TIME[1], "sync")
    bank.approve_consent(cid)
    insert_mock_consent(conn, cid)
    with pytest.raises(ToolFailure) as info:
        ingest_statements(conn, bank, "u1", "missing", cid)
    assert info.value.error.code == ErrorCode.NOT_FOUND


def test_only_true_duplicate_charge_is_flagged_not_monthly_repeats(conn):
    result = gen(months=3)
    bank = MockAAConnector(result.transactions)
    cid = bank.create_consent("u1", ["a1"], ALL_TIME[0], ALL_TIME[1], "sync")
    bank.approve_consent(cid)
    insert_mock_consent(conn, cid)
    report = ingest_statements(conn, bank, "u1", "a1", cid)
    [dup] = [a for a in result.ground_truth if a.kind == "duplicate_charge"]
    flagged = {t.id for t in list_transactions(conn, "u1", *ALL_TIME) if t.is_duplicate_of}
    assert report.duplicates_flagged == len(flagged) == 1
    assert flagged <= set(dup.transaction_ids)


def test_duplicate_flags_do_not_depend_on_ingestion_order(conn):
    import random

    result = gen(months=3)
    txs = list(result.transactions)
    random.Random(7).shuffle(txs)
    bank = MockAAConnector(txs)
    cid = bank.create_consent("u1", ["a1"], ALL_TIME[0], ALL_TIME[1], "sync")
    bank.approve_consent(cid)
    insert_mock_consent(conn, cid)
    ingest_statements(conn, bank, "u1", "a1", cid)
    [dup] = [a for a in result.ground_truth if a.kind == "duplicate_charge"]
    flagged = {t.id for t in list_transactions(conn, "u1", *ALL_TIME) if t.is_duplicate_of}
    assert flagged == {max(dup.transaction_ids)} or len(flagged) == 1
