"""
Core domain models for Finance Copilot.
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field


class User(BaseModel):
    id: str
    created_at: str

class Account(BaseModel):
    id: str
    user_id: str
    name: str
    created_at: str

class Category(BaseModel):
    id: str
    user_id: str
    name: str
    created_at: str

class Transaction(BaseModel):
    id: str
    user_id: str
    account_id: str
    occurred_at: str  # UTC ISO
    
    # Amount convention: positive values indicate a spend (debit), 
    # negative values indicate a credit (refund, income).
    amount_paise: int
    direction: Literal["debit", "credit"]
    
    merchant_raw: str
    description: str
    
    category_id: Optional[str] = None
    category_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    category_source: Literal["rule", "llm", "user", "none"] = "none"
    
    created_at: str

class Budget(BaseModel):
    id: str
    user_id: str
    category_id: str
    period: Literal["monthly"] = "monthly"
    limit_paise: int = Field(ge=0)
    warn_threshold_pct: int = Field(ge=0, le=100)
