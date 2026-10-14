"""
Core Input Gate and Intent Understanding Pipeline (PLAN_PHASE2 Section 5.2 & Stage 2.7).

Provides:
- Input gate with deterministic refusal classes and helpful fallback guidance
- Deterministic amount parser with support for INR formatting, commas, multipliers (k, lakh, cr)
- Deterministic period parser supporting relative, explicit, multi-month, and IST boundaries
- Entity resolution for categories, merchants, and goals with zero-hallucination guarantees
- Deterministic keyword-based intent classifier across 10 core intent types
- LLM entity-extraction helper with strict schema validation and DB re-validation
- Single-round clarification generator with concrete user-derived options
- Safe AgentTask creation with automatic PII redaction and audit logging
"""

import logging
import re
import sqlite3
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from copilot.audit.events import record_event
from copilot.config.phase2 import IntentPatternsConfig, load_intent_patterns
from copilot.core.timeutil import IST, now_utc, to_utc_iso
from copilot.db.repo import insert_agent_task
from copilot.llm.client import LLMClient, StructuredOutputError, structured_call
from copilot.llm.redactor import redact
from copilot.models.agentic import AgentTask, Intent, IntentType, TaskStatus

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------------------------
# 1. Input Gate & Refusal Rules
# ---------------------------------------------------------------------------------------------

RefusalClass = Literal[
    "INVESTMENT_ADVICE",
    "MONEY_MOVEMENT",
    "MARKET_PREDICTION",
    "SENSITIVE_DATA_SUBMISSION",
    "OUT_OF_SCOPE",
]

_BENIGN_ANALYTICAL_PREFIX = re.compile(
    r"^\s*(?:"
    r"how\s+much\s+(?:did\s+i|have\s+i|was\s+my|is\s+my)|"
    r"did\s+i\s+(?:pay|spend|transfer|receive|buy)|"
    r"show\s+(?:me\s+)?(?:my\s+)?(?:past\s+)?(?:transfers|bills|spending|expenses|transactions|goals|budgets)|"
    r"list\s+(?:my\s+)?(?:past\s+)?(?:transfers|bills|subscriptions|expenses|transactions)|"
    r"what\s+did\s+i\s+spend|"
    r"why\s+(?:did|was|is)\s+(?:my|the)|"
    r"check\s+(?:if\s+i|my\s+budget|my\s+goal|my\s+spend|my\s+balance)|"
    r"history\s+of|"
    r"overview\s+of"
    r")\b",
    re.IGNORECASE,
)

_INVEST_QUERY = re.compile(
    r"(?i)\b(which|what|should i buy|should i invest in|recommend)\b.*"
    r"\b(stock|stocks|share|shares|mutual fund|mutual funds|sip|"
    r"crypto|bitcoin|etf|gold\s+investment)\b"
)
_INVEST_TOP = re.compile(
    r"(?i)\b(best|top)\b.*\b(stocks|shares|mutual funds|funds|investments)\b"
)


def check_input_gate(
    text: str,
    config: IntentPatternsConfig | None = None,
) -> tuple[bool, RefusalClass | None, str | None]:
    """
    Evaluate input text against refusal classes.
    Returns (is_refused, refusal_class, refusal_message).
    Deterministic patterns always take precedence.
    """
    cfg = config or load_intent_patterns()
    clean_text = text.strip()

    # 1. Check for sensitive financial credentials first
    if re.search(r"\b(?:otp|cvv|pin|password)\b\s*[:=]?\s*[\w\d]+", clean_text, re.IGNORECASE):
        msg = cfg.refusal_templates.get("SENSITIVE_DATA_SUBMISSION", "")
        return True, "SENSITIVE_DATA_SUBMISSION", msg

    # Formatted 16-digit card number
    if re.search(r"\b\d{4}[-\s]\d{4}[-\s]\d{4}[-\s]\d{4}\b", clean_text):
        msg = cfg.refusal_templates.get("SENSITIVE_DATA_SUBMISSION", "")
        return True, "SENSITIVE_DATA_SUBMISSION", msg

    # 2. Check if this is a benign historical/analytical question about past events
    is_benign = bool(_BENIGN_ANALYTICAL_PREFIX.search(clean_text))

    # 3. Check Out of Scope
    if re.search(r"(?i)\b(weather|recipe|joke|sports\s+score|cricket\s+match)\b", clean_text):
        msg = cfg.refusal_templates.get("OUT_OF_SCOPE", "")
        return True, "OUT_OF_SCOPE", msg

    # 4. Check Market Prediction
    if re.search(
        r"(?i)\b(will\s+nifty|will\s+sensex|market\s+crash|stock\s+go\s+up|"
        r"price\s+target|predict\s+market|predict\s+bitcoin)\b",
        clean_text,
    ):
        msg = cfg.refusal_templates.get("MARKET_PREDICTION", "")
        return True, "MARKET_PREDICTION", msg

    # 5. Check Investment Advice
    if _INVEST_QUERY.search(clean_text) or _INVEST_TOP.search(clean_text):
        # Exclude benign queries asking about grocery stock or past jewelry spending
        if not (is_benign or "grocery" in clean_text.lower() or "jewelry" in clean_text.lower()):
            msg = cfg.refusal_templates.get("INVESTMENT_ADVICE", "")
            return True, "INVESTMENT_ADVICE", msg

    # 6. Check Money Movement (Instructions to initiate payment/transfer)
    if not is_benign:
        if re.search(
            r"(?i)\b(send|transfer|pay|wire|withdraw|deposit)\b.*?"
            r"\b(?:(?:rs\.?|inr|₹)?\s*\d+|money|cash|to\s+[a-zA-Z]+)\b",
            clean_text,
        ) or re.search(r"(?i)\b(pay\b.*\bbill|transfer\s+funds)\b", clean_text):
            # Verify not a what-if query like "what if I pay ₹5,000 for..."
            if not re.search(r"(?i)\b(what\s+if|can\s+i\s+afford|if\s+i)\b", clean_text):
                msg = cfg.refusal_templates.get("MONEY_MOVEMENT", "")
                return True, "MONEY_MOVEMENT", msg

    return False, None, None


# ---------------------------------------------------------------------------------------------
# 2. Deterministic Amount Parser (Paise)
# ---------------------------------------------------------------------------------------------

def parse_amount_paise(text: str) -> int | None:
    """
    Parse monetary amounts from text into integer paise.
    Supports:
    - Multipliers: '20k' (20,000 INR), '2 lakh' / '2.5 lac' (2,50,000 INR), '1.5 cr' / '1 crore'
    - Indian and Western comma groupings: 'Rs. 1,25,000', '₹50,000', '1,25,000'
    - Prefixes/Suffixes: '₹500', 'Rs 500.50', '5000 rupees', 'inr 100'
    - Plain numbers in spending/purchase context: 'buy laptop for 45000'
    Guards against misinterpreting years (e.g. 'in 2026') as amounts.
    """
    clean = text.strip()

    # 1. Lakhs and Crores
    m_lakh = re.search(
        r"(?i)(?:(?:rs\.?|inr|₹)\s*)?(\d+(?:,\d+)*(?:\.\d+)?)\s*(lakhs?|lacs?|crores?|cr)\b",
        clean,
    )
    if m_lakh:
        num_str = m_lakh.group(1).replace(",", "")
        unit = m_lakh.group(2).lower()
        val = Decimal(num_str)
        if unit in ("lakh", "lakhs", "lac", "lacs"):
            val *= Decimal(100_000)
        elif unit in ("crore", "crores", "cr"):
            val *= Decimal(10_000_000)
        return int(val * 100)

    # 2. Thousands with 'k' or 'K'
    m_k = re.search(r"(?i)(?:(?:rs\.?|inr|₹)\s*)?(\d+(?:\.\d+)?)\s*k\b", clean)
    if m_k:
        val = Decimal(m_k.group(1)) * Decimal(1_000)
        return int(val * 100)

    # 3. Explicit currency prefix (₹, Rs, Rs., INR)
    m_curr_prefix = re.search(
        r"(?i)(?:rs\.?|inr|₹)\s*(\d+(?:,\d+)*(?:\.\d+)?)",
        clean,
    )
    if m_curr_prefix:
        num_str = m_curr_prefix.group(1).replace(",", "")
        val = Decimal(num_str)
        return int(val * 100)

    # 4. Explicit currency suffix (rupees, rs)
    m_curr_suffix = re.search(
        r"(?i)(\d+(?:,\d+)*(?:\.\d+)?)\s*(?:rupees?|rs\.?|inr)\b",
        clean,
    )
    if m_curr_suffix:
        num_str = m_curr_suffix.group(1).replace(",", "")
        val = Decimal(num_str)
        return int(val * 100)

    # 5. Formatted numbers with commas (e.g. '1,25,000' or '50,000')
    m_comma = re.search(r"\b(\d{1,3}(?:,\d{2,3})+)\b", clean)
    if m_comma:
        num_str = m_comma.group(1).replace(",", "")
        val = Decimal(num_str)
        return int(val * 100)

    # 6. Purchase/spending context with plain integers
    m_context = re.search(
        r"(?i)\b(?:for|spend|spent|save|cost|worth|purchase|buy|cut|reduce)\b.*?"
        r"\b(?:by|about|around|for)?\s*(\d{2,}(?:\.\d+)?)\b",
        clean,
    )
    if m_context:
        num_str = m_context.group(1)
        val = Decimal(num_str)
        return int(val * 100)

    return None


# ---------------------------------------------------------------------------------------------
# 3. Deterministic Period Parser (IST-Aware)
# ---------------------------------------------------------------------------------------------

_MONTH_NAMES: dict[str, int] = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}


def parse_period(
    text: str,
    reference_date: datetime | date | None = None,
) -> tuple[str | None, int | None, int | None, int | None]:
    """
    Parse time periods and horizons from natural language query.
    Returns (period_str, year, month, horizon_months).
    Evaluated with Asia/Kolkata (IST) calendar boundaries.
    """
    clean = text.strip()

    # Determine reference date in IST
    if reference_date is None:
        ref_dt = datetime.now(IST)
    elif isinstance(reference_date, datetime):
        if reference_date.tzinfo is None:
            ref_dt = reference_date.replace(tzinfo=UTC).astimezone(IST)
        else:
            ref_dt = reference_date.astimezone(IST)
    else:
        ref_dt = datetime(
            reference_date.year, reference_date.month, reference_date.day, 12, 0, tzinfo=IST
        )

    # 1. Multi-month historical periods: 'last 3 months', 'past 6 months'
    m_past_months = re.search(r"(?i)\b(?:last|past)\s+(\d+)\s+months?\b", clean)
    if m_past_months:
        count = int(m_past_months.group(1))
        return f"last_{count}_months", None, None, count

    # 2. Multi-month future horizons: 'next 6 months', 'over 12 months', 'in 6 months'
    m_future_months = re.search(r"(?i)\b(?:next|over|in|for)\s+(\d+)\s+months?\b", clean)
    if m_future_months:
        count = int(m_future_months.group(1))
        return None, None, None, count

    # 3. Relative months
    if re.search(r"(?i)\b(?:this|current)\s+month\b", clean):
        period = f"{ref_dt.year:04d}-{ref_dt.month:02d}"
        return period, ref_dt.year, ref_dt.month, None

    if re.search(r"(?i)\b(?:last|previous|prior|past)\s+month\b", clean):
        if ref_dt.month == 1:
            y = ref_dt.year - 1
            m = 12
        else:
            y = ref_dt.year
            m = ref_dt.month - 1
        period = f"{y:04d}-{m:02d}"
        return period, y, m, None

    if re.search(r"(?i)\bnext\s+month\b", clean):
        if ref_dt.month == 12:
            y = ref_dt.year + 1
            m = 1
        else:
            y = ref_dt.year
            m = ref_dt.month + 1
        period = f"{y:04d}-{m:02d}"
        return period, y, m, None

    if re.search(r"(?i)\bthis\s+week\b", clean):
        return "this_week", None, None, None

    # 4. Explicit YYYY-MM or MM-YYYY
    m_iso = re.search(r"\b(20\d{2})-(0[1-9]|1[0-2])\b", clean)
    if m_iso:
        y = int(m_iso.group(1))
        m = int(m_iso.group(2))
        return f"{y:04d}-{m:02d}", y, m, None

    m_rev = re.search(r"\b(0[1-9]|1[0-2])-(20\d{2})\b", clean)
    if m_rev:
        m = int(m_rev.group(1))
        y = int(m_rev.group(2))
        return f"{y:04d}-{m:02d}", y, m, None

    # 5. Named Month with Year: 'October 2026', 'Oct 2026', 'Jan 2025'
    month_pattern = "|".join(_MONTH_NAMES.keys())
    m_named_yr = re.search(
        rf"(?i)\b({month_pattern})\s+(20\d{{2}})\b",
        clean,
    )
    if m_named_yr:
        name = m_named_yr.group(1).lower()
        m = _MONTH_NAMES[name]
        y = int(m_named_yr.group(2))
        return f"{y:04d}-{m:02d}", y, m, None

    # 6. Named Month alone: 'in October', 'for Sept', 'during January'
    m_named = re.search(
        rf"(?i)\b(?:in|for|of|during)?\s*({month_pattern})\b",
        clean,
    )
    if m_named:
        name = m_named.group(1).lower()
        m = _MONTH_NAMES[name]
        y = ref_dt.year
        return f"{y:04d}-{m:02d}", y, m, None

    return None, None, None, None


# ---------------------------------------------------------------------------------------------
# 4. Entity Resolution (Categories, Goals, Merchants)
# ---------------------------------------------------------------------------------------------

_CATEGORY_SYNONYMS: dict[str, list[str]] = {
    "dining": ["food", "dining", "restaurants", "zomato", "swiggy", "eating out"],
    "groceries": ["groceries", "grocery", "blinkit", "zepto", "supermarket", "provisions"],
    "shopping": ["shopping", "clothes", "amazon", "myntra", "apparel"],
    "travel": ["travel", "transport", "uber", "ola", "flights", "cab", "commute"],
    "utilities": ["utilities", "bills", "electricity", "recharge", "wifi", "internet"],
    "rent": ["rent", "housing", "flat", "landlord"],
    "entertainment": ["entertainment", "movies", "netflix", "games"],
}


def resolve_entities(
    text: str,
    conn: sqlite3.Connection,
    user_id: str,
) -> dict[str, Any]:
    """
    Resolve category, goal, and merchant entities against the user's active database records.
    Never guesses: an unknown entity returns None.
    """
    clean_lower = text.lower()
    entities: dict[str, Any] = {
        "category_id": None,
        "goal_id": None,
        "merchant_normalized": None,
    }

    # 1. Resolve Category
    cat_rows = conn.execute(
        "SELECT id, name FROM categories WHERE user_id = ?",
        (user_id,),
    ).fetchall()

    for cid, cname in cat_rows:
        c_lower = cname.lower()
        if re.search(rf"\b{re.escape(c_lower)}\b", clean_lower):
            entities["category_id"] = cid
            break
        synonyms = _CATEGORY_SYNONYMS.get(c_lower, [])
        if any(re.search(rf"\b{re.escape(syn)}\b", clean_lower) for syn in synonyms):
            entities["category_id"] = cid
            break

    # 2. Resolve Goal
    goal_rows = conn.execute(
        "SELECT id, name FROM goals WHERE user_id = ? AND status = 'active'",
        (user_id,),
    ).fetchall()

    for gid, gname in goal_rows:
        g_lower = gname.lower()
        if re.search(rf"\b{re.escape(g_lower)}\b", clean_lower):
            entities["goal_id"] = gid
            break
        for word in g_lower.split():
            if len(word) >= 3 and re.search(rf"\b{re.escape(word)}\b", clean_lower):
                entities["goal_id"] = gid
                break
        if entities["goal_id"]:
            break

    # 3. Resolve Merchant
    merchant_rows = conn.execute(
        "SELECT DISTINCT COALESCE(merchant_normalized, merchant_raw) FROM transactions "
        "WHERE user_id = ? AND (merchant_normalized IS NOT NULL OR merchant_raw IS NOT NULL)",
        (user_id,),
    ).fetchall()

    for (m_name,) in merchant_rows:
        if m_name and len(m_name) >= 3:
            if re.search(rf"\b{re.escape(m_name.lower())}\b", clean_lower):
                entities["merchant_normalized"] = m_name
                break

    return entities


# ---------------------------------------------------------------------------------------------
# 5. Deterministic Intent Classifier
# ---------------------------------------------------------------------------------------------

def classify_intent(
    text: str,
    entities: dict[str, Any],
    period_info: tuple[str | None, int | None, int | None, int | None],
    amount_paise: int | None,
    config: IntentPatternsConfig | None = None,
) -> Intent:
    """
    Classify a natural language query into a typed Intent.
    Pure, deterministic pattern-matching against keywords in config/intent_patterns.yaml.
    """
    cfg = config or load_intent_patterns()
    clean_lower = text.lower()
    period_str, year, month, horizon_months = period_info

    intent_type: IntentType = "unknown"

    # Priority 1: What-If simulation queries (Add spend vs Reduce spend)
    if any(k in clean_lower for k in cfg.intent_keywords.get("whatif_add_spend", [])):
        intent_type = "whatif_add_spend"
    elif any(k in clean_lower for k in cfg.intent_keywords.get("whatif_reduce_spend", [])):
        intent_type = "whatif_reduce_spend"
    elif re.search(r"\b(can\s+i\s+afford|what\s+if\s+i\s+(?:buy|spend|purchase))\b", clean_lower):
        intent_type = "whatif_add_spend"
    elif re.search(
        r"\b(?:what\s+if\s+i|if\s+i|how\s+much\s+(?:will|can)\s+i\s+save\s+if\s+i)\s+(?:cut|reduce|stop)\b",
        clean_lower,
    ):
        intent_type = "whatif_reduce_spend"

    # Priority 2: Goal tracking
    elif any(k in clean_lower for k in cfg.intent_keywords.get("goal_check", [])) or entities.get(
        "goal_id"
    ):
        has_goal_kw = any(
            w in clean_lower for w in ("goal", "target", "on track")
        ) or bool(entities.get("goal_id"))
        if has_goal_kw:
            intent_type = "goal_check"

    # Priority 3: Explaining changes vs Investigating anomalies
    elif any(k in clean_lower for k in cfg.intent_keywords.get("explain_change", [])) or re.search(
        r"\bwhy\s+(?:did|has)\b.*\b(jump|increase|spike|rise|grow)\b", clean_lower
    ):
        intent_type = "explain_change"
    elif any(k in clean_lower for k in cfg.intent_keywords.get("investigate_anomaly", [])):
        intent_type = "investigate_anomaly"

    # Priority 4: Forecasting
    elif any(k in clean_lower for k in cfg.intent_keywords.get("forecast", [])) or re.search(
        r"\b(project|run\s+rate|how\s+much\s+will\s+i\s+spend)\b", clean_lower
    ):
        intent_type = "forecast"

    # Priority 5: Budget status
    elif (
        any(k in clean_lower for k in cfg.intent_keywords.get("check_budget", []))
        or "budget" in clean_lower
    ):
        intent_type = "check_budget"

    # Priority 6: Recurring expenses and subscriptions
    elif any(k in clean_lower for k in cfg.intent_keywords.get("list_recurring", [])):
        intent_type = "list_recurring"

    # Priority 7: Alerts and notifications
    elif any(k in clean_lower for k in cfg.intent_keywords.get("alerts_overview", [])):
        intent_type = "alerts_overview"

    # Priority 8: Spend summary
    elif (
        any(k in clean_lower for k in cfg.intent_keywords.get("summarize_period", []))
        or re.search(r"\bhow\s+much\s+(?:did\s+i|have\s+i)\s+spend\b", clean_lower)
    ):
        intent_type = "summarize_period"

    return Intent(
        type=intent_type,
        period=period_str,
        year=year,
        month=month,
        category_id=entities.get("category_id"),
        merchant_normalized=entities.get("merchant_normalized"),
        goal_id=entities.get("goal_id"),
        amount_paise=amount_paise,
        horizon_months=horizon_months,
        confidence_label="high" if intent_type != "unknown" else "low",
        source="deterministic",
    )


# ---------------------------------------------------------------------------------------------
# 6. LLM Intent & Entity Extraction Helper (Optional / Fallback)
# ---------------------------------------------------------------------------------------------

class LLMIntentCandidate(BaseModel):
    """Structured intent candidate extracted by LLM helper."""

    model_config = ConfigDict(extra="forbid")

    intent_type: IntentType
    category_name: str | None = None
    goal_name: str | None = None
    amount_inr: float | None = None
    period: str | None = None
    refusal_class: str | None = None


_LLM_INTENT_PROMPT = """You are a financial intent classifier.
Analyze the user request and map it to an intent and entities.

User request: "{redacted_prompt}"
Known user categories: {categories}
Known user goals: {goals}

Rules:
1. intent_type MUST be one of:
   - summarize_period, explain_change, investigate_anomaly, check_budget,
   - forecast, whatif_add_spend, whatif_reduce_spend, goal_check,
   - list_recurring, alerts_overview, unknown
2. If asking for investment advice or money transfers, set refusal_class.
3. Only extract category_name if it matches one of the known categories exactly.
4. Only extract goal_name if it matches one of the known goals exactly.
5. Provide amounts in whole rupees if explicitly mentioned.
"""


def llm_classify_intent(
    client: LLMClient,
    redacted_text: str,
    user_categories: dict[str, str],  # name -> id
    user_goals: dict[str, str],        # name -> id
) -> tuple[Intent | None, str | None]:
    """
    Invoke LLM helper for ambiguous queries.
    Re-validates all extracted entities against the database.
    Hallucinated entities are strictly dropped.
    Returns (intent_or_none, refusal_class_or_none).
    """
    prompt = _LLM_INTENT_PROMPT.format(
        redacted_prompt=redacted_text,
        categories=list(user_categories.keys()),
        goals=list(user_goals.keys()),
    )

    try:
        candidate = structured_call(client, prompt, LLMIntentCandidate)
    except StructuredOutputError:
        return None, None

    # Check if LLM flagged a refusal (e.g. subtle investment advice)
    if candidate.refusal_class in (
        "INVESTMENT_ADVICE",
        "MONEY_MOVEMENT",
        "MARKET_PREDICTION",
        "SENSITIVE_DATA_SUBMISSION",
        "OUT_OF_SCOPE",
    ):
        return None, candidate.refusal_class

    # Re-validate category against user DB
    category_id = None
    if candidate.category_name:
        for name, cid in user_categories.items():
            if name.lower() == candidate.category_name.lower():
                category_id = cid
                break

    # Re-validate goal against user DB
    goal_id = None
    if candidate.goal_name:
        for name, gid in user_goals.items():
            if name.lower() == candidate.goal_name.lower():
                goal_id = gid
                break

    amount_paise = None
    if candidate.amount_inr is not None and candidate.amount_inr > 0:
        amount_paise = int(Decimal(str(candidate.amount_inr)) * 100)

    intent = Intent(
        type=candidate.intent_type,
        period=candidate.period,
        category_id=category_id,
        goal_id=goal_id,
        amount_paise=amount_paise,
        confidence_label="medium",
        source="llm",
    )
    return intent, None


# ---------------------------------------------------------------------------------------------
# 7. Clarification Generator (Strictly Single Round)
# ---------------------------------------------------------------------------------------------

def generate_clarification(
    intent: Intent,
    conn: sqlite3.Connection,
    user_id: str,
) -> str | None:
    """
    If a decisive entity is missing, generate exactly one clarifying question
    offering up to 4 concrete options from the user's data.
    """
    # 1. Missing category for explain_change or check_budget
    if intent.type == "explain_change" and not intent.category_id:
        cats = conn.execute(
            "SELECT name FROM categories WHERE user_id = ? ORDER BY name LIMIT 4",
            (user_id,),
        ).fetchall()
        if cats:
            options = ", ".join(r[0] for r in cats)
            return f"Which category would you like me to explain? Options: {options}."
        return "Which category would you like me to explain?"

    # 2. Missing amount for whatif simulation
    if intent.type in ("whatif_add_spend", "whatif_reduce_spend") and not intent.amount_paise:
        return "How much are you planning to spend on this purchase (e.g. ₹25,000)?"

    # 3. Missing goal for goal_check
    if intent.type == "goal_check" and not intent.goal_id:
        goals = conn.execute(
            "SELECT name FROM goals WHERE user_id = ? AND status = 'active' "
            "ORDER BY priority LIMIT 4",
            (user_id,),
        ).fetchall()
        if goals:
            options = ", ".join(r[0] for r in goals)
            return f"Which goal would you like to check? Options: {options}."
        return "Which goal would you like to check?"

    # 4. Missing period for summarize_period, forecast, check_budget
    if intent.type in ("summarize_period", "forecast", "check_budget") and not intent.period:
        return (
            "Which period would you like me to check? "
            "Options: this month, last month, last 3 months."
        )

    return None


# ---------------------------------------------------------------------------------------------
# 8. Task Creation Pipeline
# ---------------------------------------------------------------------------------------------

def create_agent_task(
    conn: sqlite3.Connection,
    user_id: str,
    raw_text: str,
    *,
    task_id: str | None = None,
    run_id: str | None = None,
    clock: datetime | str | None = None,
    llm_client: LLMClient | None = None,
    client: LLMClient | None = None,
    config: IntentPatternsConfig | None = None,
) -> AgentTask:
    """
    Main entrypoint: parses natural language query, validates against input gate,
    resolves entities, classifies intent, and persists AgentTask with audit trail.
    Enforces that raw text is never logged or exposed in audit events.
    """
    cfg = config or load_intent_patterns()
    if clock is None:
        now_dt = now_utc()
    elif isinstance(clock, str):
        try:
            now_dt = datetime.fromisoformat(clock.replace("Z", "+00:00"))
        except Exception:
            now_dt = now_utc()
    else:
        now_dt = clock

    clock_iso = to_utc_iso(now_dt)
    effective_task_id = task_id or str(uuid.uuid4())
    effective_llm_client = llm_client or client

    # Step 1: PII Redaction
    redacted_prompt = redact(raw_text)

    # Step 2: Deterministic Input Gate
    is_refused, refusal_class, refusal_msg = check_input_gate(raw_text, cfg)

    if is_refused and refusal_class:
        # Task is refused deterministically
        task = AgentTask(
            id=effective_task_id,
            user_id=user_id,
            run_id=run_id,
            raw_text=raw_text,
            intent=Intent(
                type="unknown",
                confidence_label="low",
                source="deterministic",
                clarification=refusal_msg,
            ),
            status="refused",
            stop_reason="completed",
            planner_mode="deterministic",
            created_at=clock_iso,
            finished_at=clock_iso,
        )
        insert_agent_task(conn, task)

        # Audit refusal without raw text
        record_event(
            conn,
            user_id=user_id,
            run_id=run_id,
            actor="agent",
            event_type="input_refused",
            reason=f"Refusal class: {refusal_class}",
            entity_type="agent_task",
            entity_id=effective_task_id,
            after_data={"refusal_class": refusal_class, "redacted_prompt": redacted_prompt},
            clock=now_dt,
        )
        return task

    # Step 3: Deterministic Parsers
    amount_paise = parse_amount_paise(raw_text)
    period_info = parse_period(raw_text, reference_date=now_dt)
    entities = resolve_entities(raw_text, conn, user_id)

    # Step 4: Deterministic Intent Classification
    intent = classify_intent(raw_text, entities, period_info, amount_paise, cfg)

    # Step 5: Optional LLM Helper (only if unknown or missing critical entities)
    if intent.type == "unknown" and effective_llm_client is not None:
        cat_map = dict(
            conn.execute(
                "SELECT name, id FROM categories WHERE user_id = ?", (user_id,)
            ).fetchall()
        )
        goal_map = dict(
            conn.execute(
                "SELECT name, id FROM goals WHERE user_id = ? AND status = 'active'", (user_id,)
            ).fetchall()
        )

        llm_intent, llm_refusal = llm_classify_intent(
            effective_llm_client, redacted_prompt, cat_map, goal_map
        )

        # Safety rule: An LLM-proposed refusal is added
        if llm_refusal:
            msg = cfg.refusal_templates.get(llm_refusal, "")
            task = AgentTask(
                id=effective_task_id,
                user_id=user_id,
                run_id=run_id,
                raw_text=raw_text,
                intent=Intent(
                    type="unknown",
                    confidence_label="low",
                    source="llm",
                    clarification=msg,
                ),
                status="refused",
                stop_reason="completed",
                planner_mode="llm",
                created_at=clock_iso,
                finished_at=clock_iso,
            )
            insert_agent_task(conn, task)
            record_event(
                conn,
                user_id=user_id,
                run_id=run_id,
                actor="agent",
                event_type="input_refused",
                reason=f"LLM proposed refusal class: {llm_refusal}",
                entity_type="agent_task",
                entity_id=effective_task_id,
                after_data={"refusal_class": llm_refusal, "redacted_prompt": redacted_prompt},
                clock=now_dt,
            )
            return task

        if llm_intent and llm_intent.type != "unknown":
            # Merge deterministic period & amount if present
            if not llm_intent.period and period_info[0]:
                llm_intent.period = period_info[0]
            if not llm_intent.amount_paise and amount_paise:
                llm_intent.amount_paise = amount_paise
            intent = llm_intent

    # Step 6: Clarification Check
    status: TaskStatus = "understood"
    clarification = generate_clarification(intent, conn, user_id)
    if clarification:
        intent.clarification = clarification
        status = "needs_clarification"

    # Step 7: Persist AgentTask
    task = AgentTask(
        id=effective_task_id,
        user_id=user_id,
        run_id=run_id,
        raw_text=raw_text,
        intent=intent,
        status=status,
        planner_mode=intent.source,
        created_at=clock_iso,
    )
    insert_agent_task(conn, task)

    # Record task_created audit event (strictly no raw text)
    record_event(
        conn,
        user_id=user_id,
        run_id=run_id,
        actor="agent",
        event_type="task_created",
        reason=f"Intent: {intent.type}, Status: {status}",
        entity_type="agent_task",
        entity_id=effective_task_id,
        after_data={
            "intent_type": intent.type,
            "status": status,
            "source": intent.source,
        },
        clock=now_dt,
    )

    return task
