"""
Deterministic financial tools.
All money math happens here, never in the LLM.
"""
import calendar
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from copilot.audit.events import record_event
from copilot.core.timeutil import IST, month_bounds, now_utc
from copilot.db.repo import (
    get_transaction,
    list_budgets,
    list_transactions,
    update_transaction_category,
)
from copilot.tools.contracts import SideEffect, ToolSpec


# --- 1. get_transactions ---
class GetTransactionsInput(BaseModel):
    start_utc: str
    end_utc: str
    category_id: Optional[str] = None
    limit: Optional[int] = Field(default=None, gt=0)

class TransactionOutput(BaseModel):
    id: str
    amount_paise: int
    direction: str
    merchant_raw: str
    category_id: Optional[str]
    occurred_at: str

class GetTransactionsOutput(BaseModel):
    transactions: List[TransactionOutput]

def get_transactions_handler(
    ctx, start_utc: str, end_utc: str, 
    category_id: Optional[str] = None, limit: Optional[int] = None
) -> dict:
    txs = list_transactions(ctx.conn, ctx.user_id, start_utc, end_utc, category_id)
    if limit is not None:
        txs = txs[:limit]
    
    out_txs = [
        {
            "id": t.id, "amount_paise": t.amount_paise, "direction": t.direction, 
            "merchant_raw": t.merchant_raw, "category_id": t.category_id, 
            "occurred_at": t.occurred_at
        }
        for t in txs
    ]
    return {"transactions": out_txs}

# --- 2. get_balance ---
class GetBalanceInput(BaseModel):
    pass

class GetBalanceOutput(BaseModel):
    balance_paise: int

def get_balance_handler(ctx) -> dict:
    """Calculate balance as sum of credits minus sum of debits."""
    txs = list_transactions(ctx.conn, ctx.user_id, "1970-01-01T00:00:00Z", "9999-12-31T23:59:59Z")
    
    balance = 0
    for t in txs:
        if t.direction == "credit":
            balance += t.amount_paise
        else:
            balance -= t.amount_paise
            
    return {"balance_paise": balance}

# --- 3. aggregate_spend_by_category ---
class AggregateSpendInput(BaseModel):
    year: int
    month: int

class CategoryTotal(BaseModel):
    category_id: Optional[str]  # None means uncategorized
    total_spend_paise: int

class AggregateSpendOutput(BaseModel):
    totals: List[CategoryTotal]
    grand_total_spend_paise: int

def aggregate_spend_by_category_handler(ctx, year: int, month: int) -> dict:
    """Aggregate total spend per category. Excludes credits/refunds (only debits)."""
    start_utc, end_utc = month_bounds(year, month)
    txs = list_transactions(ctx.conn, ctx.user_id, start_utc, end_utc)
    
    totals: Dict[Optional[str], int] = {}
    grand_total = 0
    
    for t in txs:
        if t.direction == "debit":
            totals[t.category_id] = totals.get(t.category_id, 0) + t.amount_paise
            grand_total += t.amount_paise
            
    out = [{"category_id": cat, "total_spend_paise": amount} for cat, amount in totals.items()]
    return {"totals": out, "grand_total_spend_paise": grand_total}

# --- 4. check_budgets ---
class CheckBudgetsInput(BaseModel):
    year: int
    month: int

class BudgetStatus(BaseModel):
    category_id: str
    spent_paise: int
    limit_paise: int
    pct_used: int
    status: Literal["ok", "warning", "exceeded"]

class CheckBudgetsOutput(BaseModel):
    statuses: List[BudgetStatus]

def check_budgets_handler(ctx, year: int, month: int) -> dict:
    start_utc, end_utc = month_bounds(year, month)
    txs = list_transactions(ctx.conn, ctx.user_id, start_utc, end_utc)
    budgets = list_budgets(ctx.conn, ctx.user_id)
    
    spend_by_cat: Dict[str, int] = {}
    for t in txs:
        if t.direction == "debit" and t.category_id:
            spend_by_cat[t.category_id] = spend_by_cat.get(t.category_id, 0) + t.amount_paise
            
    out = []
    for b in budgets:
        spent = spend_by_cat.get(b.category_id, 0)
        pct_used = (
            int((spent / b.limit_paise) * 100) if b.limit_paise > 0 
            else (100 if spent > 0 else 0)
        )
        
        status = "ok"
        if spent > b.limit_paise:
            status = "exceeded"
        elif pct_used >= b.warn_threshold_pct:
            status = "warning"
            
        out.append({
            "category_id": b.category_id,
            "spent_paise": spent,
            "limit_paise": b.limit_paise,
            "pct_used": pct_used,
            "status": status
        })
        
    return {"statuses": out}

# --- 5. forecast_category_spend ---
class ForecastInput(BaseModel):
    year: int
    month: int
    category_id: str

class ForecastOutput(BaseModel):
    projected_spend_paise: int
    spent_so_far_paise: int
    days_elapsed: int
    days_in_month: int

def forecast_category_spend_handler(ctx, year: int, month: int, category_id: str) -> dict:
    """
    Simple deterministic run-rate forecast.
    """
    start_utc, end_utc = month_bounds(year, month)
    txs = list_transactions(ctx.conn, ctx.user_id, start_utc, end_utc, category_id)
    
    spent = sum(t.amount_paise for t in txs if t.direction == "debit")
    
    days_in_month = calendar.monthrange(year, month)[1]
    
    current_utc = now_utc(ctx.clock)
    current_ist = current_utc.astimezone(IST)
    
    if current_ist.year > year or (current_ist.year == year and current_ist.month > month):
        days_elapsed = days_in_month
    elif current_ist.year < year or (current_ist.year == year and current_ist.month < month):
        days_elapsed = 0
    else:
        days_elapsed = current_ist.day
        
    if days_elapsed == 0:
        projected = 0
    else:
        projected = int((spent / days_elapsed) * days_in_month)
        
    return {
        "projected_spend_paise": projected,
        "spent_so_far_paise": spent,
        "days_elapsed": days_elapsed,
        "days_in_month": days_in_month
    }

# --- 6. recategorize_transaction ---
class RecategorizeInput(BaseModel):
    transaction_id: str
    new_category_id: Optional[str]

class RecategorizeOutput(BaseModel):
    success: bool

def recategorize_transaction_handler(
    ctx, transaction_id: str, new_category_id: Optional[str]
) -> dict:
    tx = get_transaction(ctx.conn, ctx.user_id, transaction_id)
    if not tx:
        raise ValueError(f"Transaction {transaction_id} not found")
        
    before = {
        "category_id": tx.category_id, 
        "category_source": tx.category_source, 
        "category_confidence": tx.category_confidence
    }
    
    update_transaction_category(
        ctx.conn, ctx.user_id, transaction_id, new_category_id, "user", 1.0
    )
    
    after = {"category_id": new_category_id, "category_source": "user", "category_confidence": 1.0}
    
    record_event(
        ctx.conn,
        user_id=ctx.user_id,
        actor="agent",
        event_type="recategorize_transaction",
        reason="User requested recategorization via tool",
        run_id=ctx.run_id,
        entity_type="transaction",
        entity_id=transaction_id,
        before_data=before,
        after_data=after
    )
    
    return {"success": True}

# --- Registration Helper ---
def register_financial_tools(registry_register):
    registry_register(ToolSpec(
        name="get_transactions", description="Get transactions",
        input_model=GetTransactionsInput, output_model=GetTransactionsOutput,
        side_effect=SideEffect.READ, handler=get_transactions_handler
    ))
    registry_register(ToolSpec(
        name="get_balance", description="Get balance",
        input_model=GetBalanceInput, output_model=GetBalanceOutput,
        side_effect=SideEffect.READ, handler=get_balance_handler
    ))
    registry_register(ToolSpec(
        name="aggregate_spend_by_category", description="Aggregate spend",
        input_model=AggregateSpendInput, output_model=AggregateSpendOutput,
        side_effect=SideEffect.READ, handler=aggregate_spend_by_category_handler
    ))
    registry_register(ToolSpec(
        name="check_budgets", description="Check budgets",
        input_model=CheckBudgetsInput, output_model=CheckBudgetsOutput,
        side_effect=SideEffect.READ, handler=check_budgets_handler
    ))
    registry_register(ToolSpec(
        name="forecast_category_spend", description="Forecast spend",
        input_model=ForecastInput, output_model=ForecastOutput,
        side_effect=SideEffect.READ, handler=forecast_category_spend_handler
    ))
    registry_register(ToolSpec(
        name="recategorize_transaction", description="Recategorize a transaction",
        input_model=RecategorizeInput, output_model=RecategorizeOutput,
        side_effect=SideEffect.WRITE_LOGICAL, handler=recategorize_transaction_handler
    ))
