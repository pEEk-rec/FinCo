"""
Agent interaction loop and LLM stub.
"""
from typing import Any, Dict, Optional, Tuple

from copilot.core.errors import ErrorCode
from copilot.core.timeutil import IST, month_bounds, now_utc
from copilot.tools.executor import ExecutionContext, execute_tool


def mock_llm_decide(
    text: str, ctx: ExecutionContext
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """
    Mock LLM that parses user text into tool calls.
    Returns (tool_name, tool_input).
    """
    text = text.lower()
    
    if "balance" in text:
        return "get_balance", {}
        
    if "transaction" in text:
        current = now_utc(ctx.clock).astimezone(IST)
        start_utc, end_utc = month_bounds(current.year, current.month)
        return "get_transactions", {"start_utc": start_utc, "end_utc": end_utc}
        
    if "budget" in text:
        current = now_utc(ctx.clock).astimezone(IST)
        return "check_budgets", {"year": current.year, "month": current.month}
        
    if "recategorize" in text:
        parts = text.split()
        tx_id = None
        cat_id = None
        if len(parts) >= 4:
            tx_id = parts[1]
            cat_id = parts[3]
        return "recategorize_transaction", {"transaction_id": tx_id, "new_category_id": cat_id}
        
    return None, None

def run_turn(ctx: ExecutionContext, user_msg: str, approved: bool = False) -> str:
    """
    Run one turn of the agent loop.
    """
    tool_name, tool_input = mock_llm_decide(user_msg, ctx)
    
    if not tool_name:
        return "I didn't understand that. Try asking about balance, transactions, or budgets."
        
    result = execute_tool(ctx, tool_name, tool_input, approved=approved) # type: ignore
    
    if result.ok:
        if tool_name == "get_balance":
            return f"Your balance is {result.data.balance_paise / 100:.2f}" # type: ignore
        elif tool_name == "get_transactions":
            count = len(result.data.transactions) # type: ignore
            return f"You have {count} transactions in the current period."
        elif tool_name == "check_budgets":
            statuses = result.data.statuses # type: ignore
            exceeded = [s for s in statuses if s.status == "exceeded"] # type: ignore
            if exceeded:
                return f"Warning: {len(exceeded)} budgets exceeded."
            return "All budgets are looking good."
        elif tool_name == "recategorize_transaction":
            return "Transaction successfully recategorized."
        return str(result.data.model_dump()) # type: ignore
    else:
        if result.error.code == ErrorCode.APPROVAL_REQUIRED: # type: ignore
            return f"Action requires approval: {result.error.message}" # type: ignore
        elif result.error.code == ErrorCode.DENIED_BY_POLICY: # type: ignore
            return f"Action denied by policy: {result.error.message}" # type: ignore
        elif result.error.code == ErrorCode.INVALID_INPUT: # type: ignore
            return f"Invalid input provided: {result.error.message}" # type: ignore
        else:
            return f"Error executing tool: {result.error.message}" # type: ignore
