"""Hinglish questions (A10): a thin layer in front of the existing rule reader."""

import json
from pathlib import Path

import pytest

from copilot.conversation.hinglish import looks_hinglish, to_english
from copilot.conversation.intent import check_input_gate
from copilot.db.connection import get_connection, init_db
from copilot.db.repo import insert_user
from copilot.models.domain import User

DATA = Path(__file__).resolve().parents[2] / "eval" / "data" / "hinglish_intents.json"
CASES = json.loads(DATA.read_text("utf-8"))


@pytest.fixture(scope="module")
def conn():
    c = get_connection(":memory:", check_same_thread=False)
    init_db(c)
    insert_user(c, User(id="u1", created_at="2026-01-01T00:00:00Z"))
    return c


def classify(conn, text):
    from copilot.conversation.intent import (
        classify_intent,
        parse_amount_paise,
        parse_period,
        resolve_entities,
    )

    t = to_english(text)
    return classify_intent(
        t, resolve_entities(t, conn, "u1"), parse_period(t), parse_amount_paise(t)
    ).type


def test_english_passes_through_untouched():
    for q in (
        "how much did I spend on food last month",
        "show my subscriptions",
        "am I within budget",
    ):
        assert to_english(q) == q and not looks_hinglish(q)


def test_hinglish_words_and_phrases_become_english():
    assert "this month" in to_english("is mahine khane pe kitna gaya")
    assert "last month" in to_english("pichle mahine travel pe kitna kharcha hua")


def test_the_input_gate_still_refuses_money_movement_said_in_hinglish_words():
    refused, cls, _ = check_input_gate(
        to_english("mere dost ko 500 rupees transfer karo send money")
    )
    assert refused and cls == "MONEY_MOVEMENT"


@pytest.mark.parametrize("intent", list(CASES["dev"]))
def test_dev_questions_land_on_their_intent(conn, intent):
    wrong = [q for q in CASES["dev"][intent] if classify(conn, q) != intent]
    # the dev set built the glossary; it should be (almost) fully understood
    assert len(wrong) <= 1, wrong


def test_held_out_hinglish_meets_the_target_declared_before_tuning(conn):
    total = ok = confidently_wrong = 0
    for intent, qs in CASES["held_out"].items():
        for q in qs:
            got = classify(conn, q)
            total += 1
            ok += got == intent
            confidently_wrong += got not in (intent, "unknown")
    assert ok / total >= CASES["target_accuracy"], f"{ok}/{total}"
    assert confidently_wrong / total <= CASES["target_max_wrong"], (
        f"{confidently_wrong}/{total} wrong"
    )
