"""
Markdown and HTML renderers for MonthlyReview documents (PLAN_PHASE1 Section 5.8).

INVARIANT:
The renderer output must contain only numbers that are directly derived from the MonthlyReview
object (amounts, percentages, counts, days, period). No numbers may be invented or hardcoded.
"""

import re
from decimal import Decimal
from typing import Any

from jinja2 import Environment, select_autoescape

from copilot.core.advice import format_inr
from copilot.review.models import MonthlyReviewData

_NUMBER_RE = re.compile(
    r"(?<![\w.,])(?P<num>\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?![\d,]*\d)"
)


def _format_pct(val: float | int | None) -> str:
    if val is None:
        return "-"
    return f"{val}%"


def _format_money(paise: int | None) -> str:
    if paise is None:
        return "-"
    return format_inr(paise)


# -------------------------------------------------------------------------------------------------
# Markdown Template
# -------------------------------------------------------------------------------------------------

_MD_TEMPLATE = (
    "# Monthly Financial Review: {{ review.period }} (v{{ review.version }})\n\n"
    "**Generated:** {{ review.generated_at }} | **Run ID:** `{{ review.run_id }}`\n\n"
    "## Financial Summary\n"
    "- **Total Income:** {{ format_inr(review.income_paise) }}\n"
    "- **Total Spend:** {{ format_inr(review.spend_paise) }}\n"
    "- **Net Cashflow:** {{ format_inr(review.net_paise) }}\n"
    "{% if review.previous_period %}\n"
    "- **Previous Period ({{ review.previous_period }}):** "
    "Income {{ format_inr(review.previous_income_paise) }}, "
    "Spend {{ format_inr(review.previous_spend_paise) }}, "
    "Net {{ format_inr(review.previous_net_paise) }}\n"
    "{% endif %}\n\n"
    "## Category Expenditure\n"
    "| Category | Spend | Previous | Change | Change % |\n"
    "| :--- | :--- | :--- | :--- | :--- |\n"
    "{% for c in review.category_totals %}\n"
    "| {{ c.category_name }} | {{ format_inr(c.current_spend_paise) }} "
    "| {{ format_inr(c.previous_spend_paise) }} "
    "| {{ format_inr(c.change_paise) }} | {{ format_pct(c.change_pct) }} |\n"
    "{% endfor %}\n\n"
    "## Budget Performance\n"
    "| Category | Spent | Limit | Used | Status |\n"
    "| :--- | :--- | :--- | :--- | :--- |\n"
    "{% for b in review.budget_statuses %}\n"
    "| {{ b.category_name }} | {{ format_inr(b.spent_paise) }} "
    "| {{ format_inr(b.limit_paise) }} | {{ format_pct(b.pct_used) }} "
    "| {{ b.status }} |\n"
    "{% endfor %}\n\n"
    "## Recurring Commitments\n"
    "{% if review.recurring_payments %}\n"
    "| Merchant | Typical Amount | Cadence | Confidence |\n"
    "| :--- | :--- | :--- | :--- |\n"
    "{% for r in review.recurring_payments %}\n"
    "| {{ r.merchant }} | {{ format_inr(r.typical_amount_paise) }} "
    "| {{ r.cadence_days }} days | {{ r.confidence }} |\n"
    "{% endfor %}\n"
    "{% else %}\n"
    "No recurring commitments detected.\n"
    "{% endif %}\n\n"
    "## Detected Anomalies\n"
    "{% if review.anomalies %}\n"
    "| Transaction | Merchant | Amount | Occurred At | Reason |\n"
    "| :--- | :--- | :--- | :--- |\n"
    "{% for a in review.anomalies %}\n"
    "| `{{ a.transaction_id }}` | {{ a.merchant }} "
    "| {{ format_inr(a.amount_paise) }} | {{ a.occurred_at }} | {{ a.reason }} |\n"
    "{% endfor %}\n"
    "{% else %}\n"
    "No anomalous transactions flagged for this period.\n"
    "{% endif %}\n\n"
    "## Month-End Forecast\n"
    "{% if review.forecast %}\n"
    "- **Spent So Far:** {{ format_inr(review.forecast.spent_so_far_paise) }}\n"
    "- **Projected Total:** {{ format_inr(review.forecast.projected_total_paise) }}\n"
    "- **Projected Range:** {{ format_inr(review.forecast.projected_range_paise[0]) }} - "
    "{{ format_inr(review.forecast.projected_range_paise[1]) }}\n"
    "{% if review.forecast.insufficient_data %}\n"
    "*(Insufficient historical baseline for fixed forecast)*\n"
    "{% endif %}\n"
    "{% endif %}\n\n"
    "## Financial Guidance & Advice\n"
    "{% if review.advice %}\n"
    "{% for item in review.advice %}\n"
    "- [{{ item.status }}] {{ item.text }}\n"
    "{% for asm in item.assumptions %}\n"
    "  - Assumption: {{ asm }}\n"
    "{% endfor %}\n"
    "{% endfor %}\n"
    "{% else %}\n"
    "No specific financial guidance items generated for this period.\n"
    "{% endif %}\n\n"
    "## Data Quality Notes\n"
    "- **Review Queue Size:** {{ review.data_quality.review_queue_size }}\n"
    "- **Duplicate Charges Flagged:** {{ review.data_quality.duplicates_flagged }}\n"
    "- **Recorded Days:** {{ review.data_quality.days_recorded }} / "
    "{{ review.data_quality.days_in_month }}\n"
    "- **Missing Activity Days:** {{ review.data_quality.missing_days }}\n"
    "- **Partial Month:** {{ 'Yes' if review.data_quality.is_partial_month else 'No' }}\n"
)

# -------------------------------------------------------------------------------------------------
# HTML Template
# -------------------------------------------------------------------------------------------------

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Monthly Financial Review - {{ review.period }}</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            line-height: 1.5;
            color: #1e293b;
            background: #f8fafc;
            margin: 0;
            padding: 2em;
        }
        .container {
            max-width: 900px;
            margin: 0 auto;
            background: #ffffff;
            border-radius: 8px;
            padding: 2em;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }
        h1, h2 { color: #0f172a; margin-top: 1.5em; }
        .header-meta { color: #64748b; font-size: 0.9em; margin-bottom: 2em; }
        .summary-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 1em;
            margin-bottom: 2em;
        }
        .card {
            background: #f1f5f9;
            padding: 1em;
            border-radius: 6px;
            border-left: 4px solid #3b82f6;
        }
        .card-label { font-size: 0.85em; color: #475569; text-transform: uppercase; }
        .card-value { font-size: 1.5em; font-weight: bold; color: #0f172a; margin-top: 0.2em; }
        table { width: 100%; border-collapse: collapse; margin-top: 1em; margin-bottom: 2em; }
        th, td { text-align: left; padding: 0.75em; border-bottom: 1px solid #e2e8f0; }
        th { background: #f8fafc; font-weight: 600; color: #334155; }
        .badge {
            display: inline-block;
            padding: 0.2em 0.6em;
            border-radius: 4px;
            font-size: 0.8em;
            font-weight: 600;
            text-transform: uppercase;
        }
        .badge-ok { background: #dcfce7; color: #166534; }
        .badge-warning { background: #fef9c3; color: #854d0e; }
        .badge-exceeded { background: #fee2e2; color: #991b1b; }
        .badge-projected_exceed { background: #ffedd5; color: #9a3412; }
        .advice-box {
            background: #eff6ff;
            border-left: 4px solid #2563eb;
            padding: 1em;
            margin-bottom: 1em;
            border-radius: 4px;
        }
        .data-quality {
            background: #f8fafc;
            padding: 1em;
            border-radius: 6px;
            border: 1px solid #e2e8f0;
        }
    </style>
</head>
<body>
<div class="container">
    <h1>Monthly Financial Review: {{ review.period }} <small>(v{{ review.version }})</small></h1>
    <div class="header-meta">
        Generated: {{ review.generated_at }} | Run ID: {{ review.run_id }}
    </div>

    <h2>Overview</h2>
    <div class="summary-grid">
        <div class="card">
            <div class="card-label">Total Income</div>
            <div class="card-value">{{ format_inr(review.income_paise) }}</div>
        </div>
        <div class="card">
            <div class="card-label">Total Spend</div>
            <div class="card-value">{{ format_inr(review.spend_paise) }}</div>
        </div>
        <div class="card">
            <div class="card-label">Net Cashflow</div>
            <div class="card-value">{{ format_inr(review.net_paise) }}</div>
        </div>
    </div>
    {% if review.previous_period %}
    <p><em>
        Comparison with {{ review.previous_period }}:
        Income {{ format_inr(review.previous_income_paise) }},
        Spend {{ format_inr(review.previous_spend_paise) }},
        Net {{ format_inr(review.previous_net_paise) }}
    </em></p>
    {% endif %}

    <h2>Category Spend</h2>
    <table>
        <thead>
            <tr>
                <th>Category</th>
                <th>Spend</th>
                <th>Previous</th>
                <th>Change</th>
                <th>Change %</th>
            </tr>
        </thead>
        <tbody>
            {% for c in review.category_totals %}
            <tr>
                <td>{{ c.category_name }}</td>
                <td>{{ format_inr(c.current_spend_paise) }}</td>
                <td>{{ format_inr(c.previous_spend_paise) }}</td>
                <td>{{ format_inr(c.change_paise) }}</td>
                <td>{{ format_pct(c.change_pct) }}</td>
            </tr>
            {% endfor %}
        </tbody>
    </table>

    <h2>Budget Performance</h2>
    <table>
        <thead>
            <tr>
                <th>Category</th>
                <th>Spent</th>
                <th>Limit</th>
                <th>Used</th>
                <th>Status</th>
            </tr>
        </thead>
        <tbody>
            {% for b in review.budget_statuses %}
            <tr>
                <td>{{ b.category_name }}</td>
                <td>{{ format_inr(b.spent_paise) }}</td>
                <td>{{ format_inr(b.limit_paise) }}</td>
                <td>{{ format_pct(b.pct_used) }}</td>
                <td><span class="badge badge-{{ b.status }}">{{ b.status }}</span></td>
            </tr>
            {% endfor %}
        </tbody>
    </table>

    <h2>Recurring Commitments</h2>
    {% if review.recurring_payments %}
    <table>
        <thead>
            <tr>
                <th>Merchant</th>
                <th>Typical Amount</th>
                <th>Cadence</th>
                <th>Confidence</th>
            </tr>
        </thead>
        <tbody>
            {% for r in review.recurring_payments %}
            <tr>
                <td>{{ r.merchant }}</td>
                <td>{{ format_inr(r.typical_amount_paise) }}</td>
                <td>{{ r.cadence_days }} days</td>
                <td>{{ r.confidence }}</td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
    {% else %}
    <p>No recurring commitments detected.</p>
    {% endif %}

    <h2>Detected Anomalies</h2>
    {% if review.anomalies %}
    <table>
        <thead>
            <tr>
                <th>Transaction</th>
                <th>Merchant</th>
                <th>Amount</th>
                <th>Occurred At</th>
                <th>Reason</th>
            </tr>
        </thead>
        <tbody>
            {% for a in review.anomalies %}
            <tr>
                <td><code>{{ a.transaction_id }}</code></td>
                <td>{{ a.merchant }}</td>
                <td>{{ format_inr(a.amount_paise) }}</td>
                <td>{{ a.occurred_at }}</td>
                <td>{{ a.reason }}</td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
    {% else %}
    <p>No anomalous transactions flagged.</p>
    {% endif %}

    <h2>Month-End Forecast</h2>
    {% if review.forecast %}
    <ul>
        <li>Spent So Far: {{ format_inr(review.forecast.spent_so_far_paise) }}</li>
        <li>Projected Total: {{ format_inr(review.forecast.projected_total_paise) }}</li>
        <li>Projected Range:
            {{ format_inr(review.forecast.projected_range_paise[0]) }} -
            {{ format_inr(review.forecast.projected_range_paise[1]) }}
        </li>
    </ul>
    {% endif %}

    <h2>Financial Guidance</h2>
    {% if review.advice %}
    {% for item in review.advice %}
    <div class="advice-box">
        <strong>[{{ item.status|upper }}]</strong> {{ item.text }}
        {% if item.assumptions %}
        <ul>
            {% for asm in item.assumptions %}
            <li>Assumption: {{ asm }}</li>
            {% endfor %}
        </ul>
        {% endif %}
    </div>
    {% endfor %}
    {% else %}
    <p>No advice items generated.</p>
    {% endif %}

    <h2>Data Quality & Completeness</h2>
    <div class="data-quality">
        <ul>
            <li>Review Queue Size: {{ review.data_quality.review_queue_size }}</li>
            <li>Duplicate Charges Flagged: {{ review.data_quality.duplicates_flagged }}</li>
            <li>Recorded Activity Days:
                {{ review.data_quality.days_recorded }} / {{ review.data_quality.days_in_month }}
            </li>
            <li>Missing Activity Days: {{ review.data_quality.missing_days }}</li>
            <li>Partial Month: {{ "Yes" if review.data_quality.is_partial_month else "No" }}</li>
        </ul>
    </div>
</div>
</body>
</html>
"""


def render_markdown(review: MonthlyReviewData) -> str:
    """Render the MonthlyReviewData to a clean GitHub-flavored Markdown report."""
    env = Environment(autoescape=False)
    template = env.from_string(_MD_TEMPLATE)
    return template.render(
        review=review,
        format_inr=_format_money,
        format_pct=_format_pct,
    )


def render_html(review: MonthlyReviewData) -> str:
    """Render the MonthlyReviewData to a modern, self-contained HTML report."""
    env = Environment(autoescape=select_autoescape(["html", "xml"]))
    template = env.from_string(_HTML_TEMPLATE)
    return template.render(
        review=review,
        format_inr=_format_money,
        format_pct=_format_pct,
    )


def extract_numbers_from_rendered_text(text: str) -> set[Decimal]:
    """
    Extract all numerical values present in rendered text or markdown.
    Strips currency symbols and commas before parsing.
    """
    clean_text = re.sub(r"<style.*?</style>", "", text, flags=re.DOTALL)
    clean_text = re.sub(r"<[^>]+>", " ", clean_text)
    clean_text = clean_text.replace("₹", "").replace("Rs.", "").replace("Rs", "")

    numbers: set[Decimal] = set()
    for match in _NUMBER_RE.finditer(clean_text):
        token = match.group("num").replace(",", "")
        try:
            val = Decimal(token)
            numbers.add(val)
        except Exception:
            continue
    return numbers


def extract_all_review_numbers(review: MonthlyReviewData) -> set[Decimal]:
    """
    Collect all numbers inherent to the review data object:
    - year, month, version
    - paise amounts (both as integer paise and converted to rupee Decimal)
    - percentages and counts
    - numbers inside advice text and transaction IDs
    """
    nums: set[Decimal] = set()

    def add_val(val: Any) -> None:
        if val is None:
            return
        if isinstance(val, (int, float, Decimal)):
            d = Decimal(str(val))
            nums.add(d)
            nums.add(abs(d))
        elif isinstance(val, str):
            for match in _NUMBER_RE.finditer(val.replace(",", "")):
                try:
                    num_val = Decimal(match.group("num"))
                    nums.add(num_val)
                    nums.add(abs(num_val))
                except Exception:
                    pass

    def add_money(paise: int | None) -> None:
        if paise is None:
            return
        nums.add(Decimal(paise))
        nums.add(Decimal(abs(paise)))
        rupees = Decimal(abs(paise)) / Decimal(100)
        nums.add(rupees)
        nums.add(-rupees)
        if abs(paise) % 100 == 0:
            nums.add(Decimal(abs(paise) // 100))
            nums.add(Decimal(-(abs(paise) // 100)))

    add_val(review.id)
    add_val(review.run_id)
    add_val(review.year)
    add_val(review.month)
    add_val(review.version)
    add_money(review.income_paise)
    add_money(review.spend_paise)
    add_money(review.net_paise)

    if review.previous_income_paise is not None:
        add_money(review.previous_income_paise)
    if review.previous_spend_paise is not None:
        add_money(review.previous_spend_paise)
    if review.previous_net_paise is not None:
        add_money(review.previous_net_paise)

    for c in review.category_totals:
        add_val(c.category_name)
        add_money(c.current_spend_paise)
        if c.previous_spend_paise is not None:
            add_money(c.previous_spend_paise)
        if c.change_paise is not None:
            add_money(c.change_paise)
        if c.change_pct is not None:
            add_val(c.change_pct)

    for b in review.budget_statuses:
        add_val(b.category_name)
        add_money(b.spent_paise)
        add_money(b.limit_paise)
        if b.pct_used is not None:
            add_val(b.pct_used)

    for r in review.recurring_payments:
        add_val(r.merchant)
        add_money(r.typical_amount_paise)
        if r.cadence_days is not None:
            add_val(r.cadence_days)
        add_val(r.confidence)

    for a in review.anomalies:
        add_val(a.transaction_id)
        add_val(a.merchant)
        add_money(a.amount_paise)
        add_val(a.occurred_at)
        add_val(a.reason)

    if review.forecast:
        add_money(review.forecast.spent_so_far_paise)
        add_money(review.forecast.projected_total_paise)
        add_money(review.forecast.projected_range_paise[0])
        add_money(review.forecast.projected_range_paise[1])

    for adv in review.advice:
        add_val(adv.text)
        for asm in adv.assumptions:
            add_val(asm)

    add_val(review.data_quality.review_queue_size)
    add_val(review.data_quality.duplicates_flagged)
    add_val(review.data_quality.missing_days)
    add_val(review.data_quality.days_recorded)
    add_val(review.data_quality.days_in_month)

    # Date tokens in period (e.g. 2026, 9)
    add_val(review.period)
    if review.previous_period:
        add_val(review.previous_period)

    # Generated timestamp
    add_val(review.generated_at)

    return nums
