"""
Deterministic finding builder for the workflow analysis results.

Transforms structured outputs from analysis tools into typed Finding objects.
Enforces the safety invariants:
- Labels must match ^[a-z][a-z0-9_]*$
- Values must be integers with explicit units (paise, percent, count, days)
- Descriptions must not contain any raw digits
"""

from typing import Any

from copilot.models.findings import Finding, FindingNumber


def build_findings_from_analysis(
    year: int,
    month: int,
    analysis_results: dict[str, Any],
) -> list[Finding]:
    """
    Produce a deduplicated list of Findings from analysis tool outputs.
    """
    period = f"{year:04d}-{month:02d}"
    findings: list[Finding] = []

    # 1. Budget findings (warning / exceeded / projected_exceed)
    budgets = analysis_results.get("budgets") or []
    for b in budgets:
        status = b.get("status")
        spent = b.get("spent_paise", 0)
        limit = b.get("limit_paise", 0)
        cat_id = b.get("category_id") or "all"
        cat_name = b.get("category_name") or cat_id

        if status in ("warning", "exceeded", "projected_exceed"):
            numbers = [
                FindingNumber(label="spent", value=int(spent), unit="paise"),
                FindingNumber(label="limit", value=int(limit), unit="paise"),
            ]
            pct = b.get("pct_used")
            if pct is not None:
                numbers.append(FindingNumber(label="percent_used", value=int(pct), unit="percent"))

            findings.append(
                Finding(
                    id=f"finding_budget_{cat_id}",
                    kind="budget_status",
                    period=period,
                    subject=cat_name,
                    numbers=numbers,
                    reference_ids=[cat_id],
                    description="Monthly category budget limit exceeded or near limit",
                )
            )

    # 2. Top Category Spend findings
    for b in sorted(budgets, key=lambda x: x.get("spent_paise", 0), reverse=True)[:3]:
        spent = b.get("spent_paise", 0)
        if spent > 0:
            cat_id = b.get("category_id") or "general"
            cat_name = b.get("category_name") or cat_id
            findings.append(
                Finding(
                    id=f"finding_spend_{cat_id}",
                    kind="category_spend",
                    period=period,
                    subject=cat_name,
                    numbers=[FindingNumber(label="spend", value=int(spent), unit="paise")],
                    reference_ids=[cat_id],
                    description="Net category expenditure during period",
                )
            )

    # 3. Forecast findings
    forecast = analysis_results.get("forecast") or {}
    proj = forecast.get("projected_total") or forecast.get("projected_spend_paise")
    if proj is not None and proj > 0:
        findings.append(
            Finding(
                id=f"finding_forecast_{year}_{month:02d}",
                kind="forecast",
                period=period,
                subject="Total Monthly Expenditure",
                numbers=[
                    FindingNumber(label="projected_spend", value=int(proj), unit="paise")
                ],
                description="Projected total expenditure for current month",
            )
        )

    # 4. Anomaly findings
    anomalies = analysis_results.get("anomalies") or []
    for a in anomalies:
        tx_id = a.get("transaction_id") or "tx_unknown"
        merchant = a.get("merchant_raw") or a.get("merchant_normalized") or "Merchant"
        amount = a.get("amount_paise", 0)
        findings.append(
            Finding(
                id=f"finding_anomaly_{tx_id}",
                kind="anomaly",
                period=period,
                subject=merchant,
                numbers=[FindingNumber(label="amount", value=int(amount), unit="paise")],
                reference_ids=[tx_id],
                description="Unusually large expenditure detected",
            )
        )

    # 5. Recurring payment findings
    recurring_series = analysis_results.get("recurring") or []
    for s in recurring_series:
        merchant = s.get("merchant_normalized") or "Subscription"
        amount = s.get("typical_amount_paise", 0)
        if amount > 0:
            findings.append(
                Finding(
                    id=f"finding_recurring_{merchant}",
                    kind="recurring",
                    period=period,
                    subject=merchant,
                    numbers=[FindingNumber(label="amount", value=int(amount), unit="paise")],
                    description="Detected recurring payment series",
                )
            )

    return findings
