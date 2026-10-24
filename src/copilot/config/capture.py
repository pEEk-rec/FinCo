"""
Pydantic schemas and strict loaders for the Capture track's YAML configuration
(PLAN_CAPTURE Stage C0): the ask policy, the bank sender allowlist, per-bank SMS templates,
reconciliation and the Account Aggregator consent defaults.

Everything is validated at load time so a typo in a config file fails loudly at start-up
instead of silently changing how payments are asked about or parsed.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from copilot.core.config import PROJECT_ROOT

CONFIG_DIR = PROJECT_ROOT / "config"

_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_SENDER = re.compile(r"^[A-Z0-9][A-Z0-9-]{1,10}[A-Z0-9]$")

SmsKind = Literal["debit", "credit", "reversal", "autopay", "upi_lite_summary", "otp"]
#: Fields a template pattern may capture. Anything else is a typo.
TEMPLATE_GROUPS = frozenset(
    {"amount", "account", "utr", "counterparty", "balance", "channel", "date", "time"}
)


def _read(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path.name}: expected a mapping at the top level")
    return data


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------------------------
# 1. capture.yaml: when to ask, how to guess, how often to interrupt
# ---------------------------------------------------------------------------------------------
class PersonPolicy(_Strict):
    """Auto-label a person only when the same category was chosen k of the last n times."""

    k: int = Field(ge=1, le=10)
    n: int = Field(ge=1, le=10)

    @model_validator(mode="after")
    def k_not_above_n(self) -> PersonPolicy:
        if self.k > self.n:
            raise ValueError("person_policy.k cannot exceed n")
        return self


class AskPolicyConfig(_Strict):
    min_ask_amount_paise: int = Field(ge=0)
    auto_accept_min_confidence_bp: int = Field(ge=0, le=10000)
    #: Confidence in a known merchant whose last two answers disagree: below the line, so ask.
    unsteady_merchant_bp: int = Field(ge=0, le=10000)
    ask_about_cash: bool
    person_policy: PersonPolicy


class QuietHours(_Strict):
    start: str
    end: str

    @field_validator("start", "end")
    @classmethod
    def valid_clock(cls, v: str) -> str:
        if not _HHMM.match(v):
            raise ValueError(f"expected HH:MM, got {v!r}")
        return v


class PromptConfig(_Strict):
    max_per_day: int = Field(ge=0, le=50)
    ttl_hours: int = Field(ge=1, le=240)
    per_counterparty_cooldown_hours: int = Field(ge=0, le=168)
    quiet_hours: QuietHours
    show_silent_tag_chips: bool


class RankingWeights(_Strict):
    """Basis-point weights of the explainable guess ranking (ADR-0001 D4)."""

    counterparty_history: int = Field(ge=0, le=10000)
    time_pattern: int = Field(ge=0, le=10000)
    amount_band: int = Field(ge=0, le=10000)
    day_of_month: int = Field(ge=0, le=10000)
    merchant_hint: int = Field(ge=0, le=10000)
    recency: int = Field(ge=0, le=10000)


class RankingConfig(_Strict):
    guess_count: int = Field(ge=1, le=5)
    history_half_life_days: int = Field(ge=1, le=365)
    weights: RankingWeights

    @model_validator(mode="after")
    def weights_sum_to_one(self) -> RankingConfig:
        total = sum(self.weights.model_dump().values())
        if total != 10000:
            raise ValueError(f"ranking weights must sum to 10000 basis points, got {total}")
        return self


class LlmSuggestConfig(_Strict):
    """Only normalised merchant-like names ever go to the model; never persons or SMS text."""

    enabled: bool
    max_calls_per_day: int = Field(ge=0, le=500)


class WebhookConfig(_Strict):
    secret_header: str = Field(min_length=3)
    max_body_bytes: int = Field(ge=256, le=65536)
    rate_limit_per_minute: int = Field(ge=1, le=600)


class CreditConfig(_Strict):
    """Categories a credit can take. Refunds, own transfers and known inflows auto-label."""

    categories: list[str] = Field(min_length=1)
    auto_label_known_inflows: bool

    @field_validator("categories")
    @classmethod
    def unique(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v):
            raise ValueError("credit categories must be unique")
        return v


class ClassifyConfig(_Strict):
    """Words that tell a business from a person when the bank gives only a name or a VPA."""

    business_words: list[str] = Field(min_length=1)
    merchant_vpa_markers: list[str] = Field(min_length=1)
    own_account_phrases: list[str] = Field(min_length=1)
    person_max_name_tokens: int = Field(ge=1, le=6)

    @field_validator("business_words", "merchant_vpa_markers", "own_account_phrases")
    @classmethod
    def lower_case(cls, v: list[str]) -> list[str]:
        return [x.strip().lower() for x in v if x.strip()]


class SmsConfig(_Strict):
    """Limits and the template-drift alarm for the SMS parser (PLAN_CAPTURE Stage C2)."""

    max_text_chars: int = Field(ge=100, le=2000)
    drift_window_days: int = Field(ge=1, le=90)
    drift_min_messages: int = Field(ge=1, le=1000)
    drift_alert_bp: int = Field(ge=0, le=10000)


class PushConfig(_Strict):
    """Web Push to the user's own devices (Stage C6b). Payloads are deliberately small."""

    enabled: bool
    #: Browsers show at most this many action buttons; the rest are on the tap-through sheet.
    max_actions: int = Field(ge=0, le=3)
    #: When true the notification says only "1 payment to tag"; the amount and payee stay in-app.
    lock_screen_safe: bool
    ttl_seconds: int = Field(ge=60, le=86400)
    subject: str = Field(min_length=7)
    #: A subscription that fails this many times in a row is removed.
    max_failures: int = Field(ge=1, le=20)


class CaptureConfig(_Strict):
    push: PushConfig
    sms: SmsConfig
    classify: ClassifyConfig
    ask: AskPolicyConfig
    prompts: PromptConfig
    ranking: RankingConfig
    credits: CreditConfig
    llm_suggest: LlmSuggestConfig
    webhook: WebhookConfig
    #: Count simulated events in learning only when a demo explicitly asks for it.
    learn_from_simulated: bool = False


# ---------------------------------------------------------------------------------------------
# 2. sms_senders.yaml: the allowlist. Anything not listed is dropped unread.
# ---------------------------------------------------------------------------------------------
class BankSenders(_Strict):
    name: str = Field(min_length=1)
    #: Sender IDs (DLT headers). The owner confirms the real ones before enabling a bank.
    sender_ids: list[str] = Field(min_length=1)
    enabled: bool

    @field_validator("sender_ids")
    @classmethod
    def valid_ids(cls, v: list[str]) -> list[str]:
        for s in v:
            if not _SENDER.match(s):
                raise ValueError(f"sender id {s!r} must be upper-case letters, digits or '-'")
        return v


class SmsSendersConfig(_Strict):
    banks: dict[str, BankSenders]

    @model_validator(mode="after")
    def no_sender_shared(self) -> SmsSendersConfig:
        seen: dict[str, str] = {}
        for code, bank in self.banks.items():
            for sender in bank.sender_ids:
                if sender in seen and seen[sender] != code:
                    raise ValueError(f"sender {sender} listed for both {seen[sender]} and {code}")
                seen[sender] = code
        return self

    def allowed_senders(self) -> dict[str, str]:
        """Enabled sender id -> bank code. The only senders any message is read from."""
        return {s: c for c, b in self.banks.items() if b.enabled for s in b.sender_ids}


# ---------------------------------------------------------------------------------------------
# 3. sms_templates/<bank>.yaml
# ---------------------------------------------------------------------------------------------
class SmsTemplate(_Strict):
    name: str = Field(min_length=1)
    kind: SmsKind
    pattern: str
    drop: bool = False

    @field_validator("pattern")
    @classmethod
    def compiles(cls, v: str) -> str:
        try:
            re.compile(v)
        except re.error as exc:
            raise ValueError(f"pattern does not compile: {exc}") from exc
        return v

    @model_validator(mode="after")
    def check_groups(self) -> SmsTemplate:
        groups = set(re.compile(self.pattern).groupindex)
        unknown = groups - TEMPLATE_GROUPS
        if unknown:
            raise ValueError(f"unknown capture groups {sorted(unknown)}")
        if self.kind == "otp":
            if not self.drop:
                raise ValueError("an otp template must set drop: true")
            if groups:
                raise ValueError("an otp template must not capture anything")
        elif self.kind != "upi_lite_summary" and "amount" not in groups:
            raise ValueError(f"{self.kind} template {self.name!r} must capture 'amount'")
        return self


class BankTemplates(_Strict):
    bank: str
    #: `skeleton` until C2 fills the patterns from the redacted corpus; `ready` after.
    status: Literal["skeleton", "ready"]
    templates: list[SmsTemplate]

    @model_validator(mode="after")
    def ready_needs_templates(self) -> BankTemplates:
        has_payment = any(t.kind in ("debit", "credit") for t in self.templates)
        if self.status == "ready" and not has_payment:
            raise ValueError(f"{self.bank}: a ready bank needs a debit or credit template")
        names = [t.name for t in self.templates]
        if len(set(names)) != len(names):
            raise ValueError(f"{self.bank}: template names must be unique")
        return self


# ---------------------------------------------------------------------------------------------
# 4. reconcile.yaml
# ---------------------------------------------------------------------------------------------
class CoverageConfig(_Strict):
    window_days: int = Field(ge=1, le=90)
    min_ledger_txns: int = Field(ge=1, le=100)
    warn_below_bp: int = Field(ge=0, le=10000)


class ReconcileConfig(_Strict):
    #: Tried in this order; the first rule that gives exactly one match wins.
    match_order: list[Literal["utr", "amount_account_time"]] = Field(min_length=1)
    time_window_minutes: int = Field(ge=1, le=1440)
    orphan_after_hours: int = Field(ge=1, le=720)
    provisional_ledger: bool
    coverage: CoverageConfig

    @field_validator("match_order")
    @classmethod
    def utr_first(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v):
            raise ValueError("match_order lists a rule twice")
        if v[0] != "utr":
            raise ValueError("a UTR match must be tried first")
        return v


# ---------------------------------------------------------------------------------------------
# 5. aa.yaml: consent artefact defaults (ADR-0002)
# ---------------------------------------------------------------------------------------------
class AaFrequency(_Strict):
    unit: Literal["HOUR", "DAY", "MONTH"]
    value: int = Field(ge=1, le=31)


class AaDataLife(_Strict):
    unit: Literal["DAY", "MONTH", "YEAR"]
    value: int = Field(ge=1, le=60)


class AaConfig(_Strict):
    #: 102 is "Customer spending patterns, budget or other reportings" in the ReBIT purpose list.
    purpose_code: Literal["102"]
    fi_types: list[Literal["DEPOSIT"]] = Field(min_length=1)
    consent_types: list[Literal["PROFILE", "SUMMARY", "TRANSACTIONS"]] = Field(min_length=1)
    fetch_type: Literal["ONETIME", "PERIODIC"]
    frequency: AaFrequency
    consent_mode: Literal["VIEW", "STORE", "QUERY", "STREAM"]
    consent_duration_months: int = Field(ge=1, le=24)
    data_range_months: int = Field(ge=1, le=24)
    data_life: AaDataLife
    connector: Literal["mock", "sandbox", "statement"]
    fetch_on_monthly_review: bool

    @model_validator(mode="after")
    def periodic_not_faster_than_hourly(self) -> AaConfig:
        if self.fetch_type == "ONETIME" and self.consent_mode == "STREAM":
            raise ValueError("a one-time fetch cannot stream")
        if self.frequency.unit == "HOUR" and self.frequency.value > 24:
            raise ValueError("an hourly frequency above 24 should be expressed in days")
        return self


# ---------------------------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------------------------
@lru_cache(maxsize=4)
def load_capture_config(path: Path | None = None) -> CaptureConfig:
    return CaptureConfig.model_validate(_read(path or CONFIG_DIR / "capture.yaml"))


@lru_cache(maxsize=4)
def load_sms_senders(path: Path | None = None) -> SmsSendersConfig:
    return SmsSendersConfig.model_validate(_read(path or CONFIG_DIR / "sms_senders.yaml"))


@lru_cache(maxsize=4)
def load_sms_templates(directory: Path | None = None) -> dict[str, BankTemplates]:
    folder = directory or CONFIG_DIR / "sms_templates"
    banks: dict[str, BankTemplates] = {}
    for path in sorted(folder.glob("*.yaml")):
        banks[path.stem] = BankTemplates.model_validate(_read(path))
    return banks


@lru_cache(maxsize=4)
def load_reconcile_config(path: Path | None = None) -> ReconcileConfig:
    return ReconcileConfig.model_validate(_read(path or CONFIG_DIR / "reconcile.yaml"))


@lru_cache(maxsize=4)
def load_aa_config(path: Path | None = None) -> AaConfig:
    return AaConfig.model_validate(_read(path or CONFIG_DIR / "aa.yaml"))


def validate_capture_setup(
    senders: SmsSendersConfig | None = None,
    templates: dict[str, BankTemplates] | None = None,
) -> list[str]:
    """Cross-file checks. Returns problems (empty when the whole setup is consistent)."""
    problems: list[str] = []
    senders = senders or load_sms_senders()
    templates = templates if templates is not None else load_sms_templates()
    for code, bank in templates.items():
        if code not in senders.banks:
            problems.append(f"templates for {code!r} but no such bank in sms_senders.yaml")
        if bank.bank != code:
            problems.append(f"{code}.yaml names bank {bank.bank!r}")
    for code, b in senders.banks.items():
        if b.enabled and code not in templates:
            problems.append(f"bank {code!r} is enabled but has no template file")
        if b.enabled and templates.get(code) and templates[code].status != "ready":
            problems.append(f"bank {code!r} is enabled but its templates are still a skeleton")
    return problems
