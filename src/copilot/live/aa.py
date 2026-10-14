"""
Account Aggregator client for an FIU gateway (consent, data session, decrypted FI data).

This follows the provider-style flow that Indian AA gateways expose: create a consent request,
send the user to the approval page, wait until the consent is active, open a data session for a
date range, then read the (already decrypted) financial information. Credentials come from the
environment; with none configured the client is simply absent and nothing here runs.

STATUS: written from the provider's public documentation and covered by tests against a local
fake gateway. It has NOT been run against a live sandbox, because that needs your credentials.
Endpoint paths and header names are configurable below so a mismatch is a config change.
"""

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from copilot.core.money import rupees_to_paise
from copilot.core.timeutil import IST, to_utc_iso
from copilot.live.statement import StatementRow

# (method, url, headers, body or None) -> (status, parsed json or None)
Transport = Callable[[str, str, dict[str, str], bytes | None], tuple[int, Any]]


class AAError(RuntimeError):
    """The gateway refused or failed. The message never contains credentials."""


@dataclass(frozen=True)
class AAConfig:
    base_url: str
    client_id: str
    client_secret: str
    product_instance_id: str
    consent_path: str = "/v2/consents"
    session_path: str = "/v2/sessions"
    id_header: str = "x-client-id"
    secret_header: str = "x-client-secret"
    product_header: str = "x-product-instance-id"
    vua_suffix: str = "@onemoney"

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "AAConfig | None":
        e = env if env is not None else dict(os.environ)
        need = ("AA_BASE_URL", "AA_CLIENT_ID", "AA_CLIENT_SECRET", "AA_PRODUCT_INSTANCE_ID")
        if not all(e.get(k) for k in need):
            return None
        return cls(
            base_url=e["AA_BASE_URL"].rstrip("/"),
            client_id=e["AA_CLIENT_ID"],
            client_secret=e["AA_CLIENT_SECRET"],
            product_instance_id=e["AA_PRODUCT_INSTANCE_ID"],
            vua_suffix=e.get("AA_VUA_SUFFIX", "@onemoney"),
        )

    @property
    def host(self) -> str:
        return urlparse(self.base_url).netloc


def urllib_transport(
    method: str, url: str, headers: dict[str, str], body: bytes | None
) -> tuple[int, Any]:
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        raw, status = exc.read(), exc.code
    except (urllib.error.URLError, TimeoutError) as exc:
        raise AAError(f"gateway unreachable ({type(exc).__name__})") from exc
    try:
        return status, json.loads(raw.decode("utf-8")) if raw else None
    except (UnicodeDecodeError, json.JSONDecodeError):
        return status, None


class AAClient:
    def __init__(self, config: AAConfig, transport: Transport = urllib_transport) -> None:
        self.config = config
        self._transport = transport

    def _call(self, method: str, path: str, payload: dict | None = None) -> Any:
        cfg = self.config
        headers = {
            cfg.id_header: cfg.client_id,
            cfg.secret_header: cfg.client_secret,
            cfg.product_header: cfg.product_instance_id,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        status, data = self._transport(method, cfg.base_url + path, headers, body)
        if status >= 400:
            hint = ""
            if isinstance(data, dict):
                hint = str(data.get("errorMsg") or data.get("message") or data.get("error") or "")
            raise AAError(f"gateway returned {status}{': ' + hint[:120] if hint else ''}")
        return data

    # ---- consent -------------------------------------------------------------------------

    def create_consent(
        self, mobile: str, range_from: datetime, range_to: datetime, months_valid: int = 3
    ) -> dict[str, str]:
        """Start a consent request. The user opens the returned URL to approve it."""
        digits = "".join(c for c in mobile if c.isdigit())[-10:]
        if len(digits) != 10:
            raise AAError("a ten digit mobile number is needed to find the user's AA handle")
        data = self._call(
            "POST",
            self.config.consent_path,
            {
                "consentDuration": {"unit": "MONTH", "value": str(months_valid)},
                "vua": digits + self.config.vua_suffix,
                "dataRange": {"from": to_utc_iso(range_from), "to": to_utc_iso(range_to)},
                "context": [],
            },
        )
        if not isinstance(data, dict) or not data.get("id"):
            raise AAError("gateway reply had no consent id")
        return {
            "id": str(data["id"]),
            "url": str(data.get("url", "")),
            "status": str(data.get("status", "PENDING")),
        }

    def consent_status(self, consent_id: str) -> str:
        data = self._call("GET", f"{self.config.consent_path}/{consent_id}")
        return str((data or {}).get("status", "UNKNOWN")).upper()

    # ---- data ----------------------------------------------------------------------------

    def fetch_rows(
        self,
        consent_id: str,
        range_from: datetime,
        range_to: datetime,
        wait_s: float = 25.0,
        poll_s: float = 1.5,
    ) -> list[StatementRow]:
        """Open a data session, wait for it, and return the transactions as statement rows."""
        status = self.consent_status(consent_id)
        if status != "ACTIVE":
            raise AAError(f"consent is {status.lower()}, not active; approve it first")
        session = self._call(
            "POST",
            self.config.session_path,
            {
                "consentId": consent_id,
                "format": "json",
                "dataRange": {"from": to_utc_iso(range_from), "to": to_utc_iso(range_to)},
            },
        )
        sid = (session or {}).get("id")
        if not sid:
            raise AAError("gateway reply had no session id")
        deadline = time.monotonic() + wait_s
        while True:
            data = self._call("GET", f"{self.config.session_path}/{sid}")
            state = str((data or {}).get("status", "")).upper()
            if state in ("COMPLETED", "PARTIAL"):
                return parse_fi_data(data)
            if state in ("FAILED", "EXPIRED", "REJECTED"):
                raise AAError(f"data session {state.lower()}")
            if time.monotonic() > deadline:
                raise AAError("data session is still pending; try again shortly")
            time.sleep(poll_s)


# ---- FI data (ReBIT deposit schema) ----------------------------------------------------------


def _walk(node: Any) -> Iterator[dict]:
    """Every transaction-like dict anywhere in the reply, whatever the nesting."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key.lower() in ("transaction", "transactions") and isinstance(value, list):
                for item in value:
                    if isinstance(item, dict) and "amount" in item:
                        yield item
            elif key.lower() == "transactions" and isinstance(value, dict):
                yield from _walk(value)
            else:
                yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def _stamp(txn: dict) -> str:
    raw = str(txn.get("transactionTimestamp") or txn.get("valueDate") or "")
    if not raw:
        raise ValueError("transaction has no date")
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=IST)
    if len(raw) <= 10:  # a date only
        parsed = parsed.replace(hour=12)
    return to_utc_iso(parsed)


def parse_fi_data(payload: Any) -> list[StatementRow]:
    """Read deposit-account transactions out of a data-session reply."""
    rows: list[StatementRow] = []
    for txn in _walk(payload):
        kind = str(txn.get("type", "")).upper()
        if kind not in ("DEBIT", "CREDIT"):
            continue
        paise = rupees_to_paise(str(txn["amount"]).replace(",", ""))
        if paise <= 0:
            continue
        narration = " ".join(str(txn.get("narration") or txn.get("mode") or "").split())
        rows.append(
            StatementRow(
                occurred_at=_stamp(txn),
                amount_paise=paise,
                direction=kind.lower(),
                narration=narration or "BANK TRANSACTION",
                reference=str(txn.get("txnId") or txn.get("reference") or "") or None,
            )
        )
    return rows
