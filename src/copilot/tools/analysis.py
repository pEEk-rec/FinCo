import calendar
from typing import TYPE_CHECKING

from copilot.core.anomalies import detect_anomalies
from copilot.core.forecast import forecast_month
from copilot.core.timeutil import month_bounds, now_utc
from copilot.db.repo import list_accounts, list_budgets, list_transactions
from copilot.tools.contracts import SideEffect, ToolInput, ToolOutput, ToolSpec
from copilot.tools.financial import budget_status, days_elapsed_in_month, net_spend_by_category

if TYPE_CHECKING:
    from copilot.tools.executor import ExecutionContext

# ---------------------------------------------------------------------------------------------
# detect_anomalies (READ)
# ---------------------------------------------------------------------------------------------


class DetectAnomaliesInput(ToolInput):
    pass


class DetectAnomaliesOutput(ToolOutput):
    anomalies: list[dict]


def detect_anomalies_handler(ctx: "ExecutionContext") -> DetectAnomaliesOutput:
    # Just grab all transactions for now. In real life, we'd bound this.
    txs = list_transactions(ctx.conn, ctx.user_id, "1970-01-01T00:00:00Z", "2030-01-01T00:00:00Z")
    anomalies = detect_anomalies(txs)
    return DetectAnomaliesOutput(anomalies=anomalies)


# ---------------------------------------------------------------------------------------------
# forecast_month (READ)
# ---------------------------------------------------------------------------------------------


class ForecastMonthInput(ToolInput):
    year: int
    month: int


class ForecastMonthOutput(ToolOutput):
    spent_so_far: int
    projected_total: int
    projected_range: tuple[int, int]
    breakdown: dict
    insufficient_data: bool


def forecast_month_handler(ctx: "ExecutionContext", year: int, month: int) -> ForecastMonthOutput:
    txs = list_transactions(ctx.conn, ctx.user_id, *month_bounds(year, month))
    days_in_month = calendar.monthrange(year, month)[1]
    elapsed = days_elapsed_in_month(year, month, now_utc(ctx.clock))

    # We should get recurring series. Since we don't have list_recurring_series yet in repo,
    # let's just query it directly
    recurring_rows = ctx.conn.execute(
        "SELECT id, merchant_normalized, typical_amount_paise "
        "FROM recurring_series WHERE user_id = ?",
        (ctx.user_id,),
    ).fetchall()

    from collections import namedtuple

    Series = namedtuple("Series", ["merchant_normalized", "typical_amount_paise"])
    series = [Series(row[1], row[2]) for row in recurring_rows]

    res = forecast_month(txs, series, elapsed, days_in_month)
    return ForecastMonthOutput(**res)


# ---------------------------------------------------------------------------------------------
# get_financial_state (READ)
# ---------------------------------------------------------------------------------------------


class FinancialStateSnapshot(ToolOutput):
    balance_paise: int
    category_totals: dict[str | None, int]
    budgets: list[dict]
    review_queue_size: int


class GetFinancialStateInput(ToolInput):
    year: int
    month: int


def get_financial_state_handler(
    ctx: "ExecutionContext", year: int, month: int
) -> FinancialStateSnapshot:
    # balance
    accs = list_accounts(ctx.conn, ctx.user_id)
    balance = sum(a.opening_balance_paise for a in accs)

    all_txs = list_transactions(
        ctx.conn, ctx.user_id, "1970-01-01T00:00:00Z", "2030-01-01T00:00:00Z"
    )
    for tx in all_txs:
        if not tx.is_duplicate_of:
            balance -= tx.amount_paise

    # category totals this month
    month_txs = list_transactions(ctx.conn, ctx.user_id, *month_bounds(year, month))
    cat_totals = net_spend_by_category(month_txs)

    # budget status
    days_in_month = calendar.monthrange(year, month)[1]
    elapsed = days_elapsed_in_month(year, month, now_utc(ctx.clock))

    budgets_out = []
    for budget in list_budgets(ctx.conn, ctx.user_id):
        spent = cat_totals.get(budget.category_id, 0)
        # Using simple run-rate for budgets here, to avoid circular dependencies
        from copilot.tools.financial import run_rate_forecast

        projected = run_rate_forecast(spent, elapsed, days_in_month)
        pct_used, status = budget_status(
            spent, budget.limit_paise, budget.warn_threshold_pct, projected, budget.forecast_warn
        )
        budgets_out.append(
            {
                "category_id": budget.category_id,
                "status": status,
                "spent": spent,
                "limit": budget.limit_paise,
            }
        )

    # review queue size (confidence < 0.8)
    review_queue = sum(
        1 for tx in all_txs if tx.category_confidence is not None and tx.category_confidence < 0.8
    )

    return FinancialStateSnapshot(
        balance_paise=balance,
        category_totals=cat_totals,
        budgets=budgets_out,
        review_queue_size=review_queue,
    )


# ---------------------------------------------------------------------------------------------
# Specs
# ---------------------------------------------------------------------------------------------

ANALYSIS_TOOLS = (
    ToolSpec(
        name="detect_anomalies",
        description="Detect unusual transactions.",
        input_model=DetectAnomaliesInput,
        output_model=DetectAnomaliesOutput,
        side_effect=SideEffect.READ,
        handler=detect_anomalies_handler,
    ),
    ToolSpec(
        name="forecast_month",
        description="Forecast end of month spend.",
        input_model=ForecastMonthInput,
        output_model=ForecastMonthOutput,
        side_effect=SideEffect.READ,
        handler=forecast_month_handler,
    ),
    ToolSpec(
        name="get_financial_state",
        description="Get an overview snapshot of the financial state.",
        input_model=GetFinancialStateInput,
        output_model=FinancialStateSnapshot,
        side_effect=SideEffect.READ,
        handler=get_financial_state_handler,
    ),
)
