"""Helpers every command module shares: amounts typed by people, and reading tool output."""

from decimal import Decimal
from typing import Any

from copilot.conversation.intent import parse_amount_paise


def parse_cli_amount(amt_str: str) -> int:
    """Parse monetary amount string into integer paise.

    Accepts: '50000', '50000.50', '₹50,000', 'Rs. 20,000', '20k', '2.5 lakh'.
    """
    clean = amt_str.strip()
    res = parse_amount_paise(clean)
    if res is not None:
        return res
    clean_num = clean.replace(",", "").replace("₹", "").replace("Rs.", "").replace("Rs", "").strip()
    try:
        val = Decimal(clean_num)
        return int(round(val * 100))
    except Exception as exc:
        raise ValueError(f"Invalid monetary amount: '{amt_str}'") from exc


def tool_out(res: Any, key: str) -> Any:
    """Extract a named attribute from a ToolOutput model or dict."""
    if hasattr(res.data, key):
        return getattr(res.data, key)
    if isinstance(res.data, dict):
        return res.data.get(key)
    return None


def tool_dict(res: Any) -> dict[str, Any]:
    """Serialize ToolOutput model or dict to plain dictionary."""
    if hasattr(res.data, "model_dump"):
        return res.data.model_dump(mode="json")
    if isinstance(res.data, dict):
        return res.data
    return {}
