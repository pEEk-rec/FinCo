from copilot.llm.client import FakeLLMClient
from copilot.llm.redactor import RedactingLLMClient, redact


def test_redact_removes_upi_and_account():
    prompt = "Payment to alice@okaxis for dinner, account 1234567890123."
    redacted = redact(prompt)
    assert "alice@okaxis" not in redacted
    assert "[UPI]" in redacted
    assert "1234567890123" not in redacted
    assert "[ACCOUNT]" in redacted

    # Check it preserves other numbers
    assert "Rs 100" in redact("Rs 100 via UPI")


def test_redacting_client_wraps_inner():
    fake = FakeLLMClient(["response"])
    client = RedactingLLMClient(fake)

    resp = client.complete("Here is an account 1234567890")
    assert resp == "response"
    assert fake.prompts[0] == "Here is an account [ACCOUNT]"
