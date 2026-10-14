"""The answer writer may reword, but never introduce a number the data did not produce."""

from copilot.core.answers import AnswerFact, check_text, ungrounded_numbers

FACTS = [AnswerFact(label="spent", text="₹7,172")]


def test_a_text_using_only_computed_figures_is_grounded():
    assert ungrounded_numbers("You spent ₹7,172 on dining.", FACTS) == []
    assert check_text("You spent ₹7,172 on dining.", FACTS, causal_ok=False) == []


def test_an_invented_figure_is_rejected():
    assert ungrounded_numbers("You spent ₹7,172, about 12% more.", FACTS) == ["12"]
    assert check_text("You spent ₹9,999 on dining.", FACTS, causal_ok=False)
