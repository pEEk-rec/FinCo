"""
Read a bank statement export (CSV) into rows, tolerant of how Indian banks lay them out.

Banks differ in column names, date formats, one amount column or separate debit and credit
columns, and often put account details above the header row. A row that cannot be read is
reported with its line number, never guessed and never silently dropped.
"""

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import datetime

from copilot.core.money import rupees_to_paise
from copilot.core.timeutil import IST, to_utc_iso

_DATE_COLS = ("date", "txn date", "transaction date", "value date", "tran date", "posting date")
_TEXT_COLS = (
    "narration",
    "description",
    "particulars",
    "transaction remarks",
    "remarks",
    "details",
    "transaction description",
    "transaction details",
)
_DEBIT_COLS = (
    "debit",
    "withdrawal",
    "withdrawal amt.",
    "withdrawals",
    "dr",
    "debit amount",
    "withdrawal amount",
)
_CREDIT_COLS = (
    "credit",
    "deposit",
    "deposit amt.",
    "deposits",
    "cr",
    "credit amount",
    "deposit amount",
)
_AMOUNT_COLS = ("amount", "transaction amount", "txn amount")
_TYPE_COLS = ("dr/cr", "cr/dr", "type", "transaction type")
_REF_COLS = (
    "chq./ref.no.",
    "ref no",
    "reference",
    "utr",
    "chq/ref number",
    "ref no./cheque no.",
    "reference no",
    "ref.no.",
    "cheque no",
    "txn id",
    "transaction id",
)
_DATE_FORMATS = (
    "%d/%m/%y",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d-%m-%y",
    "%d-%b-%Y",
    "%d-%b-%y",
    "%d %b %Y",
    "%d %b %y",
    "%Y-%m-%d",
    "%d/%m/%Y %H:%M:%S",
    "%d-%m-%Y %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
)
MAX_ROWS = 20000
MAX_REJECTED_SHOWN = 15


@dataclass(frozen=True)
class StatementRow:
    occurred_at: str  # UTC "...Z"
    amount_paise: int  # positive
    direction: str  # "debit" | "credit"
    narration: str
    reference: str | None


@dataclass
class ParsedStatement:
    rows: list[StatementRow] = field(default_factory=list)
    rejected: list[tuple[int, str]] = field(default_factory=list)  # (line number, reason)
    rejected_count: int = 0


class NotAStatement(ValueError):
    """No header row with a date and a description was found."""


def _find(headers: list[str], names: tuple[str, ...]) -> int | None:
    for name in names:
        if name in headers:
            return headers.index(name)
    return None


def _amount(cell: str) -> tuple[int, str | None] | None:
    """(paise, 'debit'|'credit'|None from a Dr/Cr suffix), or None when blank or zero."""
    text = cell.strip()
    if not text:
        return None
    tag = None
    m = re.search(r"\b(dr|cr)\.?$", text, re.I)
    if m:
        tag = "debit" if m.group(1).lower() == "dr" else "credit"
        text = text[: m.start()].strip()
    text = re.sub(r"(?i)^(?:rs\.?|inr|₹)\s*", "", text).replace(",", "").strip()
    if not text:
        return None
    paise = rupees_to_paise(text.lstrip("-"))
    return (paise, tag) if paise else None


def _when(cell: str) -> str:
    text = cell.strip()
    for fmt in _DATE_FORMATS:
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        if parsed.hour == parsed.minute == parsed.second == 0:
            parsed = parsed.replace(hour=12)  # a date alone: midday keeps the IST day stable
        return to_utc_iso(parsed.replace(tzinfo=IST))
    raise ValueError(f"unreadable date {text!r}")


def parse_statement(text: str) -> ParsedStatement:
    """Parse CSV text. Raises NotAStatement if no usable header row exists."""
    sample = text[:4000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(text), dialect))
    header_at = None
    for i, row in enumerate(rows[:60]):
        cells = [c.strip().lower() for c in row]
        if _find(cells, _DATE_COLS) is not None and _find(cells, _TEXT_COLS) is not None:
            header_at = i
            break
    if header_at is None:
        raise NotAStatement("no header row with a date column and a description column")
    headers = [c.strip().lower() for c in rows[header_at]]
    c_date, c_text = _find(headers, _DATE_COLS), _find(headers, _TEXT_COLS)
    c_dr, c_cr = _find(headers, _DEBIT_COLS), _find(headers, _CREDIT_COLS)
    c_amt, c_type = _find(headers, _AMOUNT_COLS), _find(headers, _TYPE_COLS)
    c_ref = _find(headers, _REF_COLS)
    if c_dr is None and c_amt is None:
        raise NotAStatement("no debit or amount column")
    out = ParsedStatement()
    for line_no, row in enumerate(rows[header_at + 1 :], start=header_at + 2):
        if not any(c.strip() for c in row):
            continue
        if len(out.rows) + out.rejected_count >= MAX_ROWS:
            break
        try:
            if c_date is None or c_text is None or len(row) <= max(c_date, c_text):
                raise ValueError("short row")
            if not row[c_date].strip():
                continue  # footers, totals, blank dates
            narration = " ".join(row[c_text].split())
            if not narration:
                raise ValueError("empty description")
            debit = _amount(row[c_dr]) if c_dr is not None and c_dr < len(row) else None
            credit = _amount(row[c_cr]) if c_cr is not None and c_cr < len(row) else None
            if debit and credit:
                raise ValueError("both debit and credit filled")
            if debit:
                paise, direction = debit[0], "debit"
            elif credit:
                paise, direction = credit[0], "credit"
            elif c_amt is not None and c_amt < len(row) and (single := _amount(row[c_amt])):
                paise, tag = single
                kind = (
                    row[c_type].strip().lower() if c_type is not None and c_type < len(row) else ""
                )
                direction = tag or (
                    "credit" if kind.startswith(("cr", "credit", "deposit")) else "debit"
                )
                if not tag and not kind and row[c_amt].strip().startswith("-"):
                    direction = "debit"
            else:
                raise ValueError("no amount")
            ref = row[c_ref].strip() if c_ref is not None and c_ref < len(row) else ""
            out.rows.append(
                StatementRow(_when(row[c_date]), paise, direction, narration, ref or None)
            )
        except ValueError as exc:
            out.rejected_count += 1
            if len(out.rejected) < MAX_REJECTED_SHOWN:
                out.rejected.append((line_no, str(exc)))
    return out
