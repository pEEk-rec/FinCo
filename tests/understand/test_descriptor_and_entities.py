"""Narration parsing (A1) and merchant entities (A2)."""

import pytest

from copilot.common.errors import ToolFailure
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_category, insert_user
from copilot.models.domain import Category, User
from copilot.understand.descriptor import parse_descriptor
from copilot.understand.entities import EntityStore

USER = "u1"


@pytest.fixture
def store():
    conn = get_connection(":memory:", check_same_thread=False)
    init_db(conn)
    insert_user(conn, User(id=USER, created_at="2026-01-01T00:00:00Z"))
    for c in ("food", "shopping"):
        insert_category(
            conn, Category(id=c, user_id=USER, name=c.title(), created_at="2026-01-01T00:00:00Z")
        )
    return EntityStore(conn, USER)


# ---- A1: descriptors ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("raw", "rail", "name", "vpa", "person"),
    [
        ("UPI/628912345678/SWIGGY8/swiggy8@ybl/HDFC", "upi", "swiggy", "swiggy8@ybl", False),
        (
            "UPI-LANTERNCAFETRA-lantern@okaxis-628912345678",
            "upi",
            "lanterncafetra",
            "lantern@okaxis",
            False,
        ),
        ("POS 4321 LANTERN CAFE TRADERS BANGALORE IN", "card", "lantern cafe traders", None, False),
        ("UPI/628912345678/RAMESH K/9876543210@ybl/SBI", "upi", "ramesh k", "9876543210@ybl", True),
        ("IMPS/628912345678/PRIYA SHARMA", "imps", "priya sharma", None, True),
        ("swiggy@icici", "upi", "swiggy", "swiggy@icici", False),
        ("NACH-NETFLIX-123456", "mandate", "netflix", None, False),
        ("ECOM AMAZON PAY INDIA", "card", "amazon pay india", None, False),
    ],
)
def test_golden_narrations(raw, rail, name, vpa, person):
    d = parse_descriptor(raw)
    assert (d.raw_rail, d.name, d.vpa, d.person_hint) == (rail, name, vpa, person)


def test_the_parser_never_invents_a_vpa():
    for raw in ("POS 4321 SOME SHOP IN", "ATM WDL KORAMANGALA", "Amazon Pay India", "INTEREST PD"):
        assert parse_descriptor(raw).vpa is None


def test_a_shop_with_a_business_word_is_not_a_person_even_with_two_words():
    d = parse_descriptor("IMPS/628912345678/RAMESH STORES")
    assert d.person_hint is False


def test_a_card_code_in_the_narration_is_read():
    assert parse_descriptor("POS 4321 SOME SHOP MCC:5812 IN").mcc == "5812"
    assert parse_descriptor("POS 4321 SOME SHOP IN").mcc is None


# ---- A2: entities ------------------------------------------------------------------------------
def test_one_shop_in_every_bank_spelling_is_one_entity(store):
    full = store.resolve(
        parse_descriptor("UPI/628912345678/LANTERN CAFE TRADERS/lantern@okaxis/HDFC")
    )
    short = store.resolve(parse_descriptor("UPI-LANTERNCAFETRA-lantern@okaxis-628912345679"))
    card = store.resolve(parse_descriptor("POS 4321 LANTERN CAFE TRADERS BANGALORE IN"))
    assert full.created and not short.created and not card.created
    assert full.entity_id == short.entity_id == card.entity_id


def test_a_truncated_name_alone_joins_the_longer_one_by_prefix(store):
    a = store.resolve(parse_descriptor("POS 4321 LANTERN CAFE TRADERS BANGALORE IN"))
    b = store.resolve(parse_descriptor("ECOM LANTERNCAFETRA"))
    assert a.entity_id == b.entity_id


def test_a_prefix_that_fits_two_shops_merges_with_neither_and_asks(store):
    a = store.resolve(parse_descriptor("POS 4321 CAMPUS CANTEEN FOODS BANGALORE IN"))
    b = store.resolve(parse_descriptor("POS 4321 CAMPUS CANTEEN BLOCK B BANGALORE IN"))
    assert a.entity_id != b.entity_id
    c = store.resolve(parse_descriptor("ECOM CAMPUSCANTEEN"))
    assert c.created and c.ambiguous, "never merged on ambiguity"
    q = store.conn.execute(
        "SELECT COUNT(*) FROM entity_merge_log WHERE kind = 'question'"
    ).fetchone()[0]
    assert q == 2


def test_a_too_short_fragment_is_never_trusted_as_a_prefix(store):
    a = store.resolve(parse_descriptor("POS 4321 SHARMA STATIONERS BANGALORE IN"))
    b = store.resolve(parse_descriptor("ECOM SHARMA"))
    assert a.entity_id != b.entity_id


def test_a_person_is_never_a_shop_and_two_people_only_share_an_exact_vpa(store):
    p1 = store.resolve(parse_descriptor("UPI/628912345678/RAMESH K/9876543210@ybl/SBI"))
    p2 = store.resolve(parse_descriptor("UPI/628912345679/RAMESH KUMAR/9876543210@ybl/SBI"))
    other = store.resolve(parse_descriptor("UPI/628912345680/RAMESH K/9123456789@ybl/SBI"))
    shop = store.resolve(parse_descriptor("POS 4321 RAMESH K STORES BANGALORE IN"))
    assert p1.kind == "person" and p1.entity_id == p2.entity_id
    assert other.entity_id != p1.entity_id, "the same name on another number is another person"
    assert shop.kind != "person" and shop.entity_id != p1.entity_id


def test_a_known_brand_resolves_to_one_entity_across_handles_and_names(store):
    a = store.resolve(parse_descriptor("UPI/628912345678/SWIGGY/swiggy@ybl/HDFC"))
    b = store.resolve(parse_descriptor("POS 4321 SWIGGY INSTAMART BANGALORE IN"))
    assert a.entity_id == b.entity_id
    assert store.entity(a.entity_id)["display_name"] == "Swiggy"


# ---- labels, merge, split, undo ----------------------------------------------------------------
def test_one_answer_is_trusted_and_two_that_disagree_are_not(store):
    e = store.resolve(parse_descriptor("POS 4321 LANTERN CAFE TRADERS BANGALORE IN")).entity_id
    store.label(e, "food")
    assert store.get_label(e) == ("food", 10000)
    store.label(e, "shopping")
    cat, conf = store.get_label(e)
    assert cat == "shopping" and conf < 10000
    store.label(e, "shopping")
    assert store.get_label(e) == ("shopping", 10000)


def test_a_merge_moves_spellings_and_the_label_and_undo_restores_exactly(store):
    a = store.resolve(parse_descriptor("POS 4321 LANTERN CAFE TRADERS BANGALORE IN")).entity_id
    b = store.resolve(parse_descriptor("POS 4321 GREEN LEAF JUICE CENTRE BANGALORE IN")).entity_id
    store.label(b, "food")
    before_a = {r["id"] for r in store.aliases(a)}
    before_b = {r["id"] for r in store.aliases(b)}
    log = store.merge(a, b)
    assert store.canonical(b) == a and {r["id"] for r in store.aliases(a)} == before_a | before_b
    assert store.get_label(a) == ("food", 10000), "the survivor inherits the only answer"
    store.undo(log)
    assert store.canonical(b) == b
    assert {r["id"] for r in store.aliases(a)} == before_a and {
        r["id"] for r in store.aliases(b)
    } == before_b
    assert store.get_label(b) == ("food", 10000) and store.get_label(a) is None


def test_a_merge_of_a_person_and_a_shop_is_refused(store):
    p = store.resolve(parse_descriptor("UPI/628912345678/RAMESH K/9876543210@ybl/SBI")).entity_id
    s = store.resolve(parse_descriptor("POS 4321 LANTERN CAFE TRADERS BANGALORE IN")).entity_id
    with pytest.raises(ToolFailure):
        store.merge(s, p)


def test_split_separates_some_spellings_and_undo_brings_them_home(store):
    e = store.resolve(
        parse_descriptor("UPI/628912345678/LANTERN CAFE TRADERS/lantern@okaxis/HDFC")
    ).entity_id
    store.resolve(parse_descriptor("POS 4321 LANTERN CAFE TRADERS BANGALORE IN"))
    aliases = store.aliases(e)
    vpa = [a["id"] for a in aliases if a["alias_type"] == "vpa"]
    new = store.split(e, vpa)
    assert new != e and {r["id"] for r in store.aliases(new)} == set(vpa)
    # all of them or none of them is not a split
    with pytest.raises(ToolFailure):
        store.split(e, [a["id"] for a in store.aliases(e)])
    log = store.conn.execute("SELECT id FROM entity_merge_log WHERE kind = 'split'").fetchone()[0]
    store.undo(log)
    assert {r["id"] for r in store.aliases(e)} == {a["id"] for a in aliases}


def test_every_merge_and_split_is_audited(store):
    a = store.resolve(parse_descriptor("POS 4321 LANTERN CAFE TRADERS BANGALORE IN")).entity_id
    b = store.resolve(parse_descriptor("POS 4321 GREEN LEAF JUICE CENTRE BANGALORE IN")).entity_id
    store.merge(a, b)
    n = store.conn.execute(
        "SELECT COUNT(*) FROM audit_events WHERE event_type = 'entity_merged'"
    ).fetchone()[0]
    assert n == 1
