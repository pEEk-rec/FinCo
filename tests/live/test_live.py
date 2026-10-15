"""Live mode: real statement import, the SMS webhook, and the Account Aggregator flow."""

import json
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from copilot.core.timeutil import IST
from copilot.live.aa import AAClient, AAConfig, AAError, parse_fi_data
from copilot.live.api import WEBHOOK_PATH
from copilot.live.server import build_live
from copilot.live.statement import NotAStatement, parse_statement
from copilot.tools.registry import clear_registry

AUTH = {"Authorization": "Bearer live-token"}
HOOK = {"X-Webhook-Secret": "hook-secret"}

HDFC_STYLE = """Account Statement, Account No: XXXX1234
Statement from 01/03/2024 to 31/03/2024

Date,Narration,Chq./Ref.No.,Value Dt,Withdrawal Amt.,Deposit Amt.,Closing Balance
01/03/24,UPI-SWIGGY-swiggy@icici-428912345678,0000428912345678,01/03/24,"1,250.50",,"48,000.00"
02/03/24,UPI-ZOMATO-zomato@hdfc-428912345679,0000428912345679,02/03/24,480.00,,"47,520.00"
03/03/24,NEFT CR-ACME-SALARY,N0303,03/03/24,,"25,000.00","72,520.00"
04/03/24,UPI-SOME SHOP-shop@ybl-428912345680,0000428912345680,04/03/24,330.00,,"72,190.00"
05/03/24,UPI-SOME SHOP-shop@ybl-428912345680,0000428912345680,05/03/24,not a number,,"72,190.00"
"""

SINGLE_AMOUNT = """Txn Date,Description,Amount,Dr/Cr,Balance
15-Mar-2024,POS 4012XXXXXXXX1234 DMART PUNE IN,"1,249.00",Dr,10000
16-Mar-2024,UPI/CANTEEN/canteen@oksbi/699910770735,60.00,Dr,9940
17-Mar-2024,REFUND AMAZON,500.00,Cr,10440
"""


@pytest.fixture
def live(tmp_path):
    clear_registry()
    app, state, _ = build_live(tmp_path / "live.db", "live-token", "hook-secret", False)
    yield TestClient(app), state
    clear_registry()


# ----------------------------------------------------------------------------- statements


def test_bank_style_statement_with_preamble_is_read():
    parsed = parse_statement(HDFC_STYLE)
    assert [r.amount_paise for r in parsed.rows] == [125050, 48000, 2500000, 33000]
    assert [r.direction for r in parsed.rows] == ["debit", "debit", "credit", "debit"]
    assert parsed.rows[0].reference == "0000428912345678"
    assert parsed.rejected_count == 1 and "line" not in parsed.rejected[0][1]


def test_single_amount_column_with_dr_cr_is_read():
    rows = parse_statement(SINGLE_AMOUNT).rows
    assert [(r.amount_paise, r.direction) for r in rows] == [
        (124900, "debit"),
        (6000, "debit"),
        (50000, "credit"),
    ]


def test_a_file_that_is_not_a_statement_is_refused():
    with pytest.raises(NotAStatement):
        parse_statement("name,age\nasha,20\n")


def test_import_adds_rows_categorises_and_is_idempotent(live):
    client, _ = live
    body = {"text": SINGLE_AMOUNT}
    first = client.post("/api/live/import/statement", headers=AUTH, json=body).json()
    assert first["inserted"] == 3 and first["skipped_existing"] == 0
    assert first["needs_review"] == 0  # DMart, canteen are known
    again = client.post("/api/live/import/statement", headers=AUTH, json=body).json()
    assert again["inserted"] == 0 and again["skipped_existing"] == 3


def test_identical_rows_in_one_file_are_both_kept(live):
    client, _ = live
    text = (
        "Date,Narration,Debit,Credit\n"
        "01/03/2024,UPI-CHAI POINT-chai@ybl,40.00,\n"
        "01/03/2024,UPI-CHAI POINT-chai@ybl,40.00,\n"
    )
    out = client.post("/api/live/import/statement", headers=AUTH, json={"text": text}).json()
    assert out["inserted"] == 2


def test_unknown_merchant_goes_to_the_review_queue(live):
    client, _ = live
    text = "Date,Narration,Debit,Credit\n02/03/2024,UPI-ZXQ VENTURES-zq@ybl,99.00,\n"
    out = client.post("/api/live/import/statement", headers=AUTH, json={"text": text}).json()
    assert out["needs_review"] == 1
    queue = client.get("/api/review-queue", headers=AUTH).json()
    assert queue["total"] == 1


def test_existing_screens_read_the_imported_rows(live):
    client, _ = live
    client.post("/api/live/import/statement", headers=AUTH, json={"text": SINGLE_AMOUNT})
    listing = client.get("/api/transactions", headers=AUTH).json()
    assert listing["total"] == 3
    assert client.get("/api/session", headers=AUTH).json()["data_source"] == "connected"


def test_import_is_audited_with_counts_only(live):
    client, state = live
    client.post("/api/live/import/statement", headers=AUTH, json={"text": SINGLE_AMOUNT})
    conn = state.connect()
    try:
        row = conn.execute(
            "SELECT after_json FROM audit_events WHERE event_type = 'live_statement_imported'"
        ).fetchone()
    finally:
        conn.close()
    data = json.loads(row["after_json"])
    assert data["inserted"] == 3 and "DMART" not in row["after_json"]


# ----------------------------------------------------------------------------- webhook


def test_webhook_needs_its_own_secret(live):
    client, _ = live
    msg = {"message": "Spent Rs.1,249.00 on HDFC Bank Card x4012 at DMART PUNE on 18-03-24"}
    assert client.post(WEBHOOK_PATH, json=msg).status_code == 401
    assert client.post(WEBHOOK_PATH, json=msg, headers=AUTH).status_code == 401  # token is not it
    ok = client.post(WEBHOOK_PATH, json=msg, headers=HOOK)
    assert ok.status_code == 200 and ok.json()["outcome"] == "provisional"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"json": {"text": "INR 60.00 debited from A/c XX1234 UPI/P2M/428900000009/CANTEEN"}},
        {"data": {"message": "INR 60.00 debited from A/c XX1234 UPI/P2M/428900000009/CANTEEN"}},
        {
            "content": "INR 60.00 debited from A/c XX1234 UPI/P2M/428900000009/CANTEEN",
            "headers": {"Content-Type": "text/plain"},
        },
    ],
)
def test_webhook_accepts_the_common_forwarder_shapes(live, kwargs):
    client, _ = live
    headers = {**HOOK, **kwargs.pop("headers", {})}
    out = client.post(WEBHOOK_PATH, headers=headers, **kwargs)
    assert out.status_code == 200 and out.json()["outcome"] == "provisional"


def test_webhook_ignores_otps_and_keeps_secret_in_query_form(live):
    client, _ = live
    otp = client.post(
        WEBHOOK_PATH + "?secret=hook-secret", json={"text": "Your OTP is 481516 for Rs 500"}
    )
    assert otp.status_code == 200 and otp.json()["outcome"] == "refused"
    assert client.get("/api/live/events", headers=AUTH).json() == []


def test_alert_then_statement_verifies_without_double_counting(live):
    client, _ = live
    client.post(
        WEBHOOK_PATH,
        headers=HOOK,
        json={"text": "Spent Rs.1,249.00 on HDFC Bank Card x4012 at DMART PUNE on 15-03-24"},
    )
    out = client.post(
        "/api/live/import/statement", headers=AUTH, json={"text": SINGLE_AMOUNT}
    ).json()
    assert out["verified_alerts"] == 1 and out["still_provisional"] == 0
    events = client.get("/api/live/events", headers=AUTH).json()
    assert events[0]["status"] == "verified"


def test_live_routes_need_the_session_token(live):
    client, _ = live
    for path in ("/api/live/status", "/api/live/pacing", "/api/live/events"):
        assert client.get(path).status_code == 401
    status = client.get("/api/live/status", headers=AUTH).json()
    assert status["live"] and status["webhook"]["path"] == WEBHOOK_PATH
    assert status["aa"]["configured"] is False


# ----------------------------------------------------------------------------- AA


FI_REPLY = {
    "id": "sess-1",
    "status": "COMPLETED",
    "fips": [
        {
            "fipID": "FIP-1",
            "accounts": [
                {
                    "maskedAccNumber": "XXXX1234",
                    "data": {
                        "account": {
                            "transactions": {
                                "transaction": [
                                    {
                                        "type": "DEBIT",
                                        "mode": "UPI",
                                        "amount": "1,249.00",
                                        "txnId": "T1",
                                        "narration": "UPI/DMART PUNE/428900000001",
                                        "transactionTimestamp": "2024-03-15T10:30:00+05:30",
                                    },
                                    {
                                        "type": "CREDIT",
                                        "amount": "25000.00",
                                        "txnId": "T2",
                                        "narration": "NEFT CR SALARY",
                                        "valueDate": "2024-03-03",
                                    },
                                    {
                                        "type": "DEBIT",
                                        "amount": "60.00",
                                        "txnId": "T3",
                                        "narration": "UPI/CANTEEN/428900000002",
                                        "transactionTimestamp": "2024-03-16T08:00:00Z",
                                    },
                                ]
                            }
                        }
                    },
                }
            ],
        }
    ],
}


class FakeGateway:
    """Stands in for the FIU gateway; also checks the headers are sent."""

    def __init__(self, consent_status="ACTIVE", polls_pending=1):
        self.consent_status = consent_status
        self.polls_pending = polls_pending
        self.calls: list[tuple[str, str]] = []

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url.split("//", 1)[1].split("/", 1)[1]))
        assert headers["x-client-id"] == "cid" and headers["x-client-secret"] == "sec"
        assert headers["x-product-instance-id"] == "pid"
        if method == "POST" and url.endswith("/v2/consents"):
            sent = json.loads(body)
            assert sent["vua"] == "9876543210@onemoney"
            return 200, {"id": "c-1", "url": "https://approve.example/c-1", "status": "PENDING"}
        if method == "GET" and url.endswith("/v2/consents/c-1"):
            return 200, {"id": "c-1", "status": self.consent_status}
        if method == "POST" and url.endswith("/v2/sessions"):
            return 200, {"id": "sess-1", "status": "PENDING"}
        if method == "GET" and url.endswith("/v2/sessions/sess-1"):
            if self.polls_pending > 0:
                self.polls_pending -= 1
                return 200, {"id": "sess-1", "status": "PENDING"}
            return 200, FI_REPLY
        return 404, {"message": "no such route"}


def _client(gateway):
    cfg = AAConfig("https://aa.example", "cid", "sec", "pid")
    return AAClient(cfg, gateway)


def test_fi_data_parses_to_statement_rows():
    rows = parse_fi_data(FI_REPLY)
    assert [(r.amount_paise, r.direction) for r in rows] == [
        (124900, "debit"),
        (2500000, "credit"),
        (6000, "debit"),
    ]
    assert rows[0].occurred_at == "2024-03-15T05:00:00Z"


def test_aa_flow_consent_then_fetch(monkeypatch):
    monkeypatch.setattr("copilot.live.aa.time.sleep", lambda s: None)
    gateway = FakeGateway()
    client = _client(gateway)
    now = datetime(2024, 3, 18, 12, 0, tzinfo=IST)
    consent = client.create_consent("+91 98765 43210", now, now)
    assert consent["id"] == "c-1" and consent["url"].startswith("https://approve.example")
    rows = client.fetch_rows("c-1", now, now, wait_s=5)
    assert len(rows) == 3 and gateway.polls_pending == 0


def test_aa_refuses_to_fetch_before_consent_is_active():
    client = _client(FakeGateway(consent_status="PENDING"))
    now = datetime(2024, 3, 18, 12, 0, tzinfo=IST)
    with pytest.raises(AAError, match="pending"):
        client.fetch_rows("c-1", now, now)


def test_aa_errors_do_not_leak_credentials():
    def failing(method, url, headers, body):
        return 401, {"message": "bad credentials"}

    client = AAClient(AAConfig("https://aa.example", "cid", "SECRET-VALUE", "pid"), failing)
    with pytest.raises(AAError) as err:
        client.consent_status("c-1")
    assert "SECRET-VALUE" not in str(err.value)


def test_aa_routes_import_through_the_same_path(tmp_path, monkeypatch):
    monkeypatch.setattr("copilot.live.aa.time.sleep", lambda s: None)
    clear_registry()
    gateway = FakeGateway()
    app, _, _ = build_live(tmp_path / "aa.db", "live-token", "hook-secret", False, _client(gateway))
    client = TestClient(app)
    made = client.post("/api/live/aa/consent", headers=AUTH, json={"mobile": "9876543210"}).json()
    assert made["id"] == "c-1"
    assert client.get("/api/live/aa/consent/c-1", headers=AUTH).json()["status"] == "ACTIVE"
    out = client.post("/api/live/aa/fetch", headers=AUTH, json={"consent_id": "c-1"}).json()
    assert out["source"] == "account_aggregator" and out["inserted"] == 3
    again = client.post("/api/live/aa/fetch", headers=AUTH, json={"consent_id": "c-1"})
    assert again.status_code in (200, 502)
    clear_registry()


def test_aa_routes_say_so_when_no_gateway_is_configured(live):
    client, _ = live
    out = client.post("/api/live/aa/consent", headers=AUTH, json={"mobile": "9876543210"})
    assert out.status_code == 409 and out.json()["code"] == "NOT_CONFIGURED"


def test_the_demo_app_has_no_live_routes(tmp_path):
    from copilot.api.app import create_app
    from copilot.api.state import ApiState

    app = create_app(ApiState(db_path=tmp_path / "demo.db"))
    assert not any(getattr(r, "path", "").startswith("/api/live") for r in app.routes)


# ----------------------------------------------------------------------------- AI categorising

UNKNOWN_CSV = (
    "Date,Narration,Debit,Credit\n"
    "02/03/2024,UPI-ZXQ VENTURES-zq@ybl,99.00,\n"
    "03/03/2024,UPI-MYSTERY LAB-ml@ybl,150.00,\n"
)


def _reply(*decisions):
    return json.dumps(
        {
            "decisions": [
                {"merchant_normalized": m, "category_id": c, "confidence": p}
                for m, c, p in decisions
            ]
        }
    )


def _with_model(live, reply):
    from copilot.llm.client import FakeLLMClient

    client, state = live
    state.llm = FakeLLMClient([reply])
    return client, state, state.llm


def test_model_labels_unknown_merchants_and_unsure_ones_stay_for_review(live):
    client, state, fake = _with_model(
        live, _reply(("zxq ventures zq", "shopping", 0.95), ("mystery lab ml", "education", 0.4))
    )
    out = client.post("/api/live/import/statement", headers=AUTH, json={"text": UNKNOWN_CSV}).json()
    assert out["ai_used"] is True and out["ai_applied"] == 1
    assert out["needs_review"] == 1  # only the unsure one is left
    queue = client.get("/api/review-queue", headers=AUTH).json()["items"]
    assert queue[0]["suggestions"][0]["reason"] == "ai_suggestion"
    assert len(fake.prompts) == 1  # one call for both merchants


def test_model_only_sees_redacted_merchant_text(live):
    client, state, fake = _with_model(live, _reply(("zxq ventures zq", "shopping", 0.95)))
    client.post("/api/live/import/statement", headers=AUTH, json={"text": UNKNOWN_CSV})
    assert "1234" not in fake.prompts[0] and "99.00" not in fake.prompts[0]


def test_an_unknown_category_from_the_model_is_ignored(live):
    client, _, _ = _with_model(live, _reply(("zxq ventures zq", "not_a_category", 0.99)))
    out = client.post("/api/live/import/statement", headers=AUTH, json={"text": UNKNOWN_CSV}).json()
    assert out["ai_applied"] == 0 and out["needs_review"] == 2


def test_a_failing_model_never_breaks_the_import(live):
    from copilot.llm.client import FakeLLMClient

    client, state = live
    state.llm = FakeLLMClient([])  # raises on first use
    out = client.post("/api/live/import/statement", headers=AUTH, json={"text": UNKNOWN_CSV})
    assert out.status_code == 200 and out.json()["inserted"] == 2
    assert out.json()["needs_review"] == 2 and out.json()["ai_note"]


def test_no_model_means_everything_unknown_waits_for_review(live):
    client, _ = live
    out = client.post("/api/live/import/statement", headers=AUTH, json={"text": UNKNOWN_CSV}).json()
    assert out["ai_used"] is False and out["needs_review"] == 2 and out["ai_note"]


def test_remembered_choice_labels_the_same_merchant_next_time(live):
    client, _ = live
    client.post("/api/live/import/statement", headers=AUTH, json={"text": UNKNOWN_CSV})
    item = client.get("/api/review-queue", headers=AUTH).json()["items"][0]["transaction"]
    done = client.post(
        f"/api/transactions/{item['id']}/category",
        headers=AUTH,
        json={"category_id": "education", "remember": True},
    )
    assert done.status_code == 200
    again = "Date,Narration,Debit,Credit\n20/03/2024," + item["merchant_raw"] + ",75.00,\n"
    out = client.post("/api/live/import/statement", headers=AUTH, json={"text": again}).json()
    assert out["needs_review"] == 1  # the other unknown one; this merchant is remembered


def test_everyday_life_categories_exist_and_rules_use_them(live):
    client, _ = live
    names = {c["id"] for c in client.get("/api/categories", headers=AUTH).json()}
    assert {"health", "cash", "transfers", "personal"} <= names
    text = (
        "Date,Narration,Debit,Credit\n"
        "02/03/2024,UPI-LOKMANYA HOSPITAL PUNE-lk@icici,1850.00,\n"
        "03/03/2024,ATM-WDL/CASH/HDFC00012/KOTHRUD PUNE,2000.00,\n"
    )
    out = client.post("/api/live/import/statement", headers=AUTH, json={"text": text}).json()
    assert out["needs_review"] == 0
    cats = {
        t["merchant_raw"][:6]: t["category_id"]
        for t in client.get("/api/transactions", headers=AUTH).json()["items"]
    }
    assert cats["UPI-LO"] == "health" and cats["ATM-WD"] == "cash"


def test_review_never_suggests_income_for_a_payment(live):
    client, _ = live
    client.post("/api/live/import/statement", headers=AUTH, json={"text": SINGLE_AMOUNT})
    client.post("/api/live/import/statement", headers=AUTH, json={"text": UNKNOWN_CSV})
    for item in client.get("/api/review-queue", headers=AUTH).json()["items"]:
        assert "income" not in [s["category_id"] for s in item["suggestions"]]
