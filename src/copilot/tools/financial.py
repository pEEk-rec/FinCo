"""
Deterministic financial tools. All money math happens here, never in the LLM.

Layout: pure functions first (data in, data out, integer paise only, no DB, no clock), then
thin handlers that fetch data and call them, then the ToolSpecs.

Sign convention (see models/domain.py): debit amount_paise > 0, credit amount_paise < 0.

Refund policy (decided 2026-09-30): credits are netted against spend *within their own
category*, and a category's net spend is floored at 0 (a refund larger than this month's spend
does not create negative spend). Uncategorised credits (salary, transfers in) are not spend and
are excluded. Uncategorised debits form their own `None` bucket.
"""

import calendar
from collections.abc import Callable, Iterable
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from pydantic import Field, model_validator

from copilot.audit.events import record_event
from copilot.core.errors import ErrorCode, ToolFailure
from copilot.core.timeutil import IST, month_bounds, now_utc, to_utc_iso
from copilot.db.repo import (
    get_account,
    get_category,
    get_transaction,
    list_accounts,
    list_budgets,
    list_transactions,
    update_transaction_category,
)
from copilot.models.domain import Id, Transaction, UtcTimestamp
from copilot.tools.contracts import SideEffect, ToolInput, ToolOutput, ToolSpec
from copilot.tools.registry import register

if TYPE_CHECKING:
    from copilot.tools.executor import ExecutionContext

# Earliest timestamp we treat as "all time" for balance queries.
_EPOCH = "1970-01-01T00:00:00Z"

BudgetState = Literal["ok", "warning", "exceeded", "projected_exceed"]

# ---------------------------------------------------------------------------------------------
# Pure functions
# ---------------------------------------------------------------------------------------------


def net_spend_by_category(txs: Iterable[Transaction]) -> dict[str | None, int]:
    """
    Net spend per category in paise, following the module's refund policy.

    Returns only buckets with spend > 0, keyed by category id (None = uncategorised).
    """
    net: dict[str | None, int] = {}
    for tx in txs:
        if tx.category_id is None and tx.direction == "credit":
            continue  # uncategorised income is not spend
        net[tx.category_id] = net.get(tx.category_id, 0) + tx.amount_paise
    return {cat: total for cat, total in net.items() if total > 0}


def budget_status(
    spent_paise: int,
    limit_paise: int,
    warn_threshold_pct: int,
    projected_spend_paise: int = 0,
    forecast_warn: bool = False,
) -> tuple[int | None, BudgetState]:
    """
    Status of one budget, using integer comparisons only.

    - exceeded: spent > limit (exactly at the limit is not exceeded)
    - warning:  spent > 0 and spent * 100 >= warn_threshold_pct * limit
    - ok:       otherwise
    pct_used is floor(spent * 100 / limit), or None when the limit is 0.
    """
    pct_used = None if limit_paise == 0 else spent_paise * 100 // limit_paise
    if spent_paise > limit_paise:
        return pct_used, "exceeded"
    if spent_paise > 0 and spent_paise * 100 >= warn_threshold_pct * limit_paise:
        return pct_used, "warning"
    if forecast_warn and projected_spend_paise > limit_paise:
        return pct_used, "projected_exceed"
    return pct_used, "ok"


def days_elapsed_in_month(year: int, month: int, now: datetime) -> int:
    """
    Days of (year, month) elapsed at `now`, counted in IST and including today.

    0 for a future month, the full month length for a past month.
    """
    today = now.astimezone(IST).date()
    days_in_month = calendar.monthrange(year, month)[1]
    if (today.year, today.month) < (year, month):
        return 0
    if (today.year, today.month) > (year, month):
        return days_in_month
    return today.day


def run_rate_forecast(spent_paise: int, days_elapsed: int, days_in_month: int) -> int:
    """
    Forecast month-end spend as spent / days_elapsed * days_in_month, rounded half up.

    Limits: assumes spend is spread evenly over the month, so one large early purchase
    (rent, fees) is extrapolated as if it repeats. Returns `spent_paise` when no day has
    elapsed. Replace this function to plug in a better forecaster.
    """
    if spent_paise < 0:
        raise ValueError("spent_paise must be >= 0")
    if days_elapsed <= 0:
        return spent_paise
    numerator = spent_paise * days_in_month
    return (2 * numerator + days_elapsed) // (2 * days_elapsed)


def compute_balance(opening_balance_paise: int, txs: Iterable[Transaction]) -> int:
    """Balance = opening balance - sum(amount_paise): debits (+) reduce it, credits (-) raise it."""
    return opening_balance_paise - sum(tx.amount_paise for tx in txs)


# ---------------------------------------------------------------------------------------------
# Shared input shapes
# ---------------------------------------------------------------------------------------------


class MonthInput(ToolInput):
    """A calendar month in IST."""

    year: int = Field(ge=2000, le=2100)
    month: int = Field(ge=1, le=12)


# ---------------------------------------------------------------------------------------------
# 1. get_transactions (READ)
# ---------------------------------------------------------------------------------------------


class GetTransactionsInput(ToolInput):
    """Half-open UTC range [start_utc, end_utc) with optional filters."""

    start_utc: UtcTimestamp
    end_utc: UtcTimestamp
    category_id: Id | None = None
    limit: int | None = Field(default=None, ge=1, le=1000)

    @model_validator(mode="after")
    def _start_before_end(self) -> "GetTransactionsInput":
        """Reject empty or inverted ranges."""
        if self.start_utc >= self.end_utc:
            raise ValueError("start_utc must be before end_utc")
        return self


class TransactionOutput(ToolOutput):
    """The fields of a transaction an agent needs to see."""

    id: str
    occurred_at: str
    amount_paise: int
    direction: Literal["debit", "credit"]
    merchant_raw: str
    description: str
    category_id: str | None
    category_source: str


class GetTransactionsOutput(ToolOutput):
    """Transactions, oldest first."""

    transactions: list[TransactionOutput]


def get_transactions_handler(
    ctx: "ExecutionContext",
    start_utc: str,
    end_utc: str,
    category_id: str | None,
    limit: int | None,
) -> GetTransactionsOutput:
    """Fetch the user's transactions in range."""
    txs = list_transactions(ctx.conn, ctx.user_id, start_utc, end_utc, category_id, limit=limit)
    return GetTransactionsOutput(
        transactions=[
            TransactionOutput(**tx.model_dump(include=set(TransactionOutput.model_fields)))
            for tx in txs
        ]
    )


# ---------------------------------------------------------------------------------------------
# 2. get_balance (READ)
# ---------------------------------------------------------------------------------------------


class GetBalanceInput(ToolInput):
    """One account, or all of the user's accounts when omitted."""

    account_id: Id | None = None


class GetBalanceOutput(ToolOutput):
    """Balance as of `as_of_utc` (future-dated transactions are ignored)."""

    balance_paise: int
    as_of_utc: str
    account_ids: list[str]


def get_balance_handler(ctx: "ExecutionContext", account_id: str | None) -> GetBalanceOutput:
    """Opening balance(s) plus all transactions up to now."""
    if account_id is not None:
        account = get_account(ctx.conn, ctx.user_id, account_id)
        if account is None:
            raise ToolFailure(ErrorCode.NOT_FOUND, f"Account '{account_id}' not found.")
        accounts = [account]
    else:
        accounts = list_accounts(ctx.conn, ctx.user_id)

    as_of = to_utc_iso(now_utc(ctx.clock))
    balance = 0
    for account in accounts:
        txs = list_transactions(ctx.conn, ctx.user_id, _EPOCH, as_of, account_id=account.id)
        balance += compute_balance(account.opening_balance_paise, txs)
    return GetBalanceOutput(
        balance_paise=balance, as_of_utc=as_of, account_ids=[a.id for a in accounts]
    )


# ---------------------------------------------------------------------------------------------
# 3. aggregate_spend_by_category (READ)
# ---------------------------------------------------------------------------------------------


class CategoryTotal(ToolOutput):
    """Net spend in one category (None = uncategorised)."""

    category_id: str | None
    total_spend_paise: int


class AggregateSpendOutput(ToolOutput):
    """Per-category net spend; the totals always sum to grand_total_spend_paise."""

    totals: list[CategoryTotal]
    grand_total_spend_paise: int


def aggregate_spend_by_category_handler(
    ctx: "ExecutionContext", year: int, month: int
) -> AggregateSpendOutput:
    """Net spend per category for an IST calendar month."""
    txs = list_transactions(ctx.conn, ctx.user_id, *month_bounds(year, month))
    by_category = net_spend_by_category(txs)
    # Stable order: named categories by id, uncategorised last.
    ordered = sorted(by_category.items(), key=lambda item: (item[0] is None, item[0] or ""))
    return AggregateSpendOutput(
        totals=[CategoryTotal(category_id=c, total_spend_paise=t) for c, t in ordered],
        grand_total_spend_paise=sum(by_category.values()),
    )


# ---------------------------------------------------------------------------------------------
# 4. check_budgets (READ)
# ---------------------------------------------------------------------------------------------


class BudgetStatusOutput(ToolOutput):
    """One budget's status for the month."""

    category_id: str
    spent_paise: int
    limit_paise: int
    warn_threshold_pct: int
    pct_used: int | None
    status: BudgetState


class CheckBudgetsOutput(ToolOutput):
    """Every budget of the user, ordered by category."""

    statuses: list[BudgetStatusOutput]


def check_budgets_handler(ctx: "ExecutionContext", year: int, month: int) -> CheckBudgetsOutput:
    """Compare each budget with the month's net spend in its category."""
    txs = list_transactions(ctx.conn, ctx.user_id, *month_bounds(year, month))
    spend = net_spend_by_category(txs)
    days_in_month = calendar.monthrange(year, month)[1]
    elapsed = days_elapsed_in_month(year, month, now_utc(ctx.clock))
    statuses = []
    for budget in list_budgets(ctx.conn, ctx.user_id):
        spent = spend.get(budget.category_id, 0)
        projected = run_rate_forecast(spent, elapsed, days_in_month)
        pct_used, status = budget_status(
            spent, budget.limit_paise, budget.warn_threshold_pct, projected, budget.forecast_warn
        )
        statuses.append(
            BudgetStatusOutput(
                category_id=budget.category_id,
                spent_paise=spent,
                limit_paise=budget.limit_paise,
                warn_threshold_pct=budget.warn_threshold_pct,
                pct_used=pct_used,
                status=status,
            )
        )
    return CheckBudgetsOutput(statuses=statuses)


# ---------------------------------------------------------------------------------------------
# 5. forecast_category_spend (READ)
# ---------------------------------------------------------------------------------------------


class ForecastInput(MonthInput):
    """Month plus the category to forecast."""

    category_id: Id


class ForecastOutput(ToolOutput):
    """Run-rate projection and the numbers it was computed from."""

    method: Literal["run_rate"]
    projected_spend_paise: int
    spent_so_far_paise: int
    days_elapsed: int
    days_in_month: int


def forecast_category_spend_handler(
    ctx: "ExecutionContext", year: int, month: int, category_id: str
) -> ForecastOutput:
    """Project month-end net spend for one category (see `run_rate_forecast` for limits)."""
    if get_category(ctx.conn, ctx.user_id, category_id) is None:
        raise ToolFailure(ErrorCode.NOT_FOUND, f"Category '{category_id}' not found.")
    txs = list_transactions(ctx.conn, ctx.user_id, *month_bounds(year, month), category_id)
    spent = net_spend_by_category(txs).get(category_id, 0)
    days_in_month = calendar.monthrange(year, month)[1]
    elapsed = days_elapsed_in_month(year, month, now_utc(ctx.clock))
    return ForecastOutput(
        method="run_rate",
        projected_spend_paise=run_rate_forecast(spent, elapsed, days_in_month),
        spent_so_far_paise=spent,
        days_elapsed=elapsed,
        days_in_month=days_in_month,
    )


# ---------------------------------------------------------------------------------------------
# 6. recategorize_transaction (WRITE_LOGICAL, needs approval per policy)
# ---------------------------------------------------------------------------------------------


class RecategorizeInput(ToolInput):
    """Move one transaction to another category (None = uncategorised)."""

    transaction_id: Id
    new_category_id: Id | None
    remember: bool = False


class RecategorizeOutput(ToolOutput):
    """What changed, and the audit event that holds the undo information."""

    transaction_id: str
    previous_category_id: str | None
    new_category_id: str | None
    audit_event_id: str


def recategorize_transaction_handler(
    ctx: "ExecutionContext",
    transaction_id: str,
    new_category_id: str | None,
    remember: bool = False,
) -> RecategorizeOutput:
    """
    Set a transaction's category (source 'user', confidence 1.0) and audit before/after.

    If remember=True, creates a merchant override and re-applies it to past agent-set
    transactions of that merchant.
    """
    tx = get_transaction(ctx.conn, ctx.user_id, transaction_id)
    if tx is None:
        raise ToolFailure(ErrorCode.NOT_FOUND, f"Transaction '{transaction_id}' not found.")
    if new_category_id is not None and get_category(ctx.conn, ctx.user_id, new_category_id) is None:
        raise ToolFailure(ErrorCode.NOT_FOUND, f"Category '{new_category_id}' not found.")

    if tx.category_source == "user" and ctx.actor != "user":
        raise ToolFailure(
            ErrorCode.DENIED_BY_POLICY, "Agent cannot recategorize a user-set transaction."
        )

    before = {
        "category_id": tx.category_id,
        "category_source": tx.category_source,
        "category_confidence": tx.category_confidence,
        "needs_review": tx.needs_review,
    }
    after = {
        "category_id": new_category_id,
        "category_source": "user",
        "category_confidence": 1.0,
        "needs_review": False,  # the user's choice settles it
    }
    update_transaction_category(
        ctx.conn, ctx.user_id, transaction_id, new_category_id, "user", 1.0, needs_review=False
    )
    event_id = record_event(
        ctx.conn,
        user_id=ctx.user_id,
        actor=ctx.actor,
        event_type="transaction_recategorized",
        reason="Transaction category changed via recategorize_transaction.",
        run_id=ctx.run_id,
        entity_type="transaction",
        entity_id=transaction_id,
        before_data=before,
        after_data=after,
        clock=ctx.clock,
    )

    if remember and tx.merchant_normalized:
        # Create override
        import uuid

        ctx.conn.execute(
            """
            INSERT INTO merchant_overrides (
                id, user_id, merchant_normalized, category_id, created_by, created_at
            )
            VALUES (?, ?, ?, ?, 'user', ?)
            ON CONFLICT(user_id, merchant_normalized) DO UPDATE SET
                category_id = excluded.category_id,
                created_at = excluded.created_at
            """,
            (
                str(uuid.uuid4()),
                ctx.user_id,
                tx.merchant_normalized,
                new_category_id,
                tx.created_at,
            ),
        )

        # Apply to past non-user transactions
        past_txs = ctx.conn.execute(
            "SELECT id, category_id, category_source, category_confidence, needs_review "
            "FROM transactions "
            "WHERE user_id = ? AND merchant_normalized = ? "
            "AND category_source != 'user' AND id != ?",
            (ctx.user_id, tx.merchant_normalized, transaction_id),
        ).fetchall()

        if past_txs:
            before_batch = {}
            after_batch = {}
            for p_tx in past_txs:
                p_id = p_tx[0]
                before_batch[p_id] = {
                    "category_id": p_tx[1],
                    "category_source": p_tx[2],
                    "category_confidence": p_tx[3],
                    "needs_review": bool(p_tx[4]),
                }
                after_batch[p_id] = {
                    "category_id": new_category_id,
                    "category_source": "override",
                    "category_confidence": 1.0,
                    "needs_review": False,
                }
                update_transaction_category(
                    ctx.conn,
                    ctx.user_id,
                    p_id,
                    new_category_id,
                    "override",
                    1.0,
                    needs_review=False,
                )

            record_event(
                ctx.conn,
                user_id=ctx.user_id,
                actor=ctx.actor,
                event_type="override_applied",
                reason=f"Override applied from transaction {transaction_id}",
                run_id=ctx.run_id,
                entity_type="transaction_batch",
                entity_id=tx.merchant_normalized,
                before_data=before_batch,
                after_data=after_batch,
                clock=ctx.clock,
            )

    return RecategorizeOutput(
        transaction_id=transaction_id,
        previous_category_id=tx.category_id,
        new_category_id=new_category_id,
        audit_event_id=event_id,
    )


# ---------------------------------------------------------------------------------------------
# 7. ingest_statements (WRITE_LOGICAL)
# ---------------------------------------------------------------------------------------------


class IngestStatementsInput(ToolInput):
    account_id: str
    consent_id: str


class IngestStatementsOutput(ToolOutput):
    fetched: int
    inserted: int
    skipped_existing: int
    duplicates_flagged: int


from copilot.bank.ingest import ingest_statements_handler  # noqa: E402
from copilot.tools.advice import ADVICE_TOOLS  # noqa: E402
from copilot.tools.analysis import ANALYSIS_TOOLS  # noqa: E402
from copilot.tools.categorisation import (  # noqa: E402
    CategorizeBatchInput,
    CategorizeBatchOutput,
    UndoCategorizeBatchInput,
    UndoCategorizeBatchOutput,
    categorize_batch_handler,
    undo_categorize_batch_handler,
)

# ---------------------------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------------------------
from copilot.tools.patterns import (  # noqa: E402
    DetectRecurringInput,
    DetectRecurringOutput,
    DetectTransfersInput,
    DetectTransfersOutput,
    detect_recurring_handler,
    detect_transfers_handler,
)
from copilot.tools.undo import UNDO_TOOL  # noqa: E402

FINANCIAL_TOOLS: tuple[ToolSpec, ...] = (
    ANALYSIS_TOOLS
    + (UNDO_TOOL,)
    + ADVICE_TOOLS
    + (
        ToolSpec(
            name="get_transactions",
            description="List the user's transactions in a UTC time range, optionally by category.",
            input_model=GetTransactionsInput,
            output_model=GetTransactionsOutput,
            side_effect=SideEffect.READ,
            handler=get_transactions_handler,
        ),
        ToolSpec(
            name="get_balance",
            description="Current balance of one account or all accounts, in paise.",
            input_model=GetBalanceInput,
            output_model=GetBalanceOutput,
            side_effect=SideEffect.READ,
            handler=get_balance_handler,
        ),
        ToolSpec(
            name="aggregate_spend_by_category",
            description="Net spend per category for an IST calendar month, in paise.",
            input_model=MonthInput,
            output_model=AggregateSpendOutput,
            side_effect=SideEffect.READ,
            handler=aggregate_spend_by_category_handler,
        ),
        ToolSpec(
            name="check_budgets",
            description="Status (ok / warning / exceeded) of every monthly budget.",
            input_model=MonthInput,
            output_model=CheckBudgetsOutput,
            side_effect=SideEffect.READ,
            handler=check_budgets_handler,
        ),
        ToolSpec(
            name="forecast_category_spend",
            description="Run-rate forecast of month-end spend for one category.",
            input_model=ForecastInput,
            output_model=ForecastOutput,
            side_effect=SideEffect.READ,
            handler=forecast_category_spend_handler,
        ),
        ToolSpec(
            name="recategorize_transaction",
            description="Change a transaction's category; audited and reversible.",
            input_model=RecategorizeInput,
            output_model=RecategorizeOutput,
            side_effect=SideEffect.WRITE_LOGICAL,
            handler=recategorize_transaction_handler,
        ),
        ToolSpec(
            name="categorize_batch",
            description="Batch update transaction categories.",
            input_model=CategorizeBatchInput,
            output_model=CategorizeBatchOutput,
            side_effect=SideEffect.WRITE_LOGICAL,
            handler=categorize_batch_handler,
        ),
        ToolSpec(
            name="undo_categorize_batch",
            description="Undo a batch categorization by run ID.",
            input_model=UndoCategorizeBatchInput,
            output_model=UndoCategorizeBatchOutput,
            side_effect=SideEffect.WRITE_LOGICAL,
            handler=undo_categorize_batch_handler,
        ),
        ToolSpec(
            name="ingest_statements",
            description="Ingest bank records from a consent. Allowed for agent.",
            input_model=IngestStatementsInput,
            output_model=IngestStatementsOutput,
            side_effect=SideEffect.WRITE_LOGICAL,
            handler=ingest_statements_handler,
        ),
    )
)


def register_financial_tools(register_fn: Callable[[ToolSpec], None] = register) -> None:
    """Register every financial tool (into the global registry by default)."""
    register(
        ToolSpec(
            name="detect_transfers",
            description="Find and link own-account transfers, excluding them from spend.",
            side_effect=SideEffect.WRITE_LOGICAL,
            input_model=DetectTransfersInput,
            output_model=DetectTransfersOutput,
            handler=detect_transfers_handler,
        )
    )
    register(
        ToolSpec(
            name="detect_recurring",
            description="Detect recurring series of transactions.",
            side_effect=SideEffect.WRITE_LOGICAL,
            input_model=DetectRecurringInput,
            output_model=DetectRecurringOutput,
            handler=detect_recurring_handler,
        )
    )
    for spec in FINANCIAL_TOOLS:
        register_fn(spec)
