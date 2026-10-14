"""
Read an e-mailed or pasted receipt into line items, so one bank debit can be split by category.

The bank only says "Rs 850 to AMAZON PAY". The receipt says what was in the order. Splits are
integer paise that add up exactly to the debit; fees and discounts are spread over the items
in proportion, with the rounding remainder handed out by largest fraction.
"""

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from copilot.core.money import rupees_to_paise

_CONFIG = Path(__file__).resolve().parents[3] / "config" / "rails.yaml"
_LINE = re.compile(
    r"^(?P<label>.+?)\s*(?:[x×]\s*(?P<qty>\d+))?\s*[:\-]?\s*"
    r"(?:rs\.?|inr|₹)\s*(?P<amt>-?[\d,]+(?:\.\d{1,2})?)\s*$",
    re.I,
)
_MERCHANT = re.compile(r"^(?:from|sold by|restaurant|merchant|store)\s*:?\s*(.+)$", re.I)


@lru_cache(maxsize=1)
def rails_config() -> dict:
    """config/rails.yaml (loaded once)."""
    return yaml.safe_load(_CONFIG.read_text(encoding="utf-8"))


@dataclass
class Receipt:
    merchant: str | None
    items: list[tuple[str, str | None, int]] = field(default_factory=list)  # label, cat, paise
    fees_paise: int = 0  # taxes, delivery and so on, minus discounts
    total_paise: int | None = None
    problems: list[str] = field(default_factory=list)

    @property
    def items_paise(self) -> int:
        return sum(p for _, _, p in self.items)


class NotAReceipt(ValueError):
    """The text has no priced lines."""


def _has(label: str, words: list[str]) -> bool:
    low = label.lower()
    return any(re.search(rf"\b{re.escape(w)}", low) for w in words)


def item_category(label: str) -> str | None:
    """The category an item most likely belongs to, from its words."""
    for category, words in rails_config()["item_keywords"].items():
        if _has(label, words):
            return category
    return None


def parse_receipt(text: str) -> Receipt:
    """Read a receipt. Totals that do not add up are reported, never silently fixed."""
    cfg = rails_config()
    receipt = Receipt(merchant=None)
    for raw in text.splitlines():
        line = " ".join(raw.split())
        if not line:
            continue
        m = _LINE.match(line)
        if not m:
            hit = _MERCHANT.match(line)
            if hit and receipt.merchant is None:
                receipt.merchant = hit.group(1).strip()
            elif receipt.merchant is None and re.match(r"^[A-Za-z][A-Za-z &.'-]{2,30}$", line):
                receipt.merchant = line
            continue
        label = m.group("label").strip(" -:")
        amount = rupees_to_paise(m.group("amt").replace(",", ""))
        if _has(label, cfg["total_words"]) and not _has(label, cfg["fee_words"]):
            receipt.total_paise = abs(amount)
        elif _has(label, cfg["discount_words"]):
            receipt.fees_paise -= abs(amount)
        elif _has(label, cfg["fee_words"]):
            receipt.fees_paise += amount
        else:
            receipt.items.append((label, item_category(label), amount))
    if not receipt.items:
        raise NotAReceipt("no priced items found")
    if receipt.total_paise is None:
        receipt.total_paise = receipt.items_paise + receipt.fees_paise
        receipt.problems.append("no total line; used items plus fees")
    elif receipt.total_paise != receipt.items_paise + receipt.fees_paise:
        receipt.problems.append("items and fees do not add up to the total")
    return receipt


def _spread(total: int, weights: list[int]) -> list[int]:
    """Split `total` over `weights` in whole paise that sum exactly (largest remainder)."""
    base = sum(weights)
    if base <= 0:
        raise ValueError("weights must be positive")
    sign = -1 if total < 0 else 1
    mag = abs(total)
    shares = [mag * w // base for w in weights]
    order = sorted(range(len(weights)), key=lambda i: (mag * weights[i]) % base, reverse=True)
    for i in order[: mag - sum(shares)]:
        shares[i] += 1
    return [sign * s for s in shares]


def split_by_category(
    receipt: Receipt, payment_paise: int, fallback_category: str
) -> list[tuple[str, int]]:
    """
    Category amounts that add up to `payment_paise` exactly.

    Raises ValueError when the receipt does not match the payment (it is then not a split).
    """
    if receipt.problems and "do not add up" in " ".join(receipt.problems):
        raise ValueError("receipt does not add up")
    if receipt.total_paise != payment_paise:
        raise ValueError("receipt total differs from the payment")
    by_category: dict[str, int] = {}
    for _, category, paise in receipt.items:
        key = category or fallback_category
        by_category[key] = by_category.get(key, 0) + paise
    keys = list(by_category)
    extra = (
        _spread(receipt.fees_paise, [by_category[k] for k in keys])
        if receipt.fees_paise
        else [0] * len(keys)
    )
    parts = [(k, by_category[k] + e) for k, e in zip(keys, extra, strict=True)]
    if sum(p for _, p in parts) != payment_paise:
        raise ValueError("split does not add up")
    return parts
