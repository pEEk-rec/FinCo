"""Data access layer for persistent state."""
import sqlite3
from typing import List, Optional

from copilot.models.domain import Budget, Transaction


def insert_transaction(conn: sqlite3.Connection, tx: Transaction) -> None:
    """Insert a new transaction."""
    conn.execute(
        """
        INSERT INTO transactions (
            id, user_id, account_id, occurred_at, amount_paise, direction,
            merchant_raw, description, category_id, category_confidence,
            category_source, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            tx.id, tx.user_id, tx.account_id, tx.occurred_at, tx.amount_paise, tx.direction,
            tx.merchant_raw, tx.description, tx.category_id, tx.category_confidence,
            tx.category_source, tx.created_at
        )
    )
    conn.commit()

def get_transaction(conn: sqlite3.Connection, user_id: str, tx_id: str) -> Optional[Transaction]:
    """Get a transaction by ID, filtering by user_id."""
    row = conn.execute(
        "SELECT * FROM transactions WHERE id = ? AND user_id = ?",
        (tx_id, user_id)
    ).fetchone()
    
    if not row:
        return None
    return Transaction(**dict(row))

def list_transactions(
    conn: sqlite3.Connection,
    user_id: str,
    start: str,
    end: str,
    category_id: Optional[str] = None
) -> List[Transaction]:
    """
    List transactions for a user in a given time range [start, end).
    """
    query = """
        SELECT * FROM transactions
        WHERE user_id = ? AND occurred_at >= ? AND occurred_at < ?
    """
    params = [user_id, start, end]
    
    if category_id is not None:
        query += " AND category_id = ?"
        params.append(category_id)
        
    query += " ORDER BY occurred_at ASC"
    
    rows = conn.execute(query, params).fetchall()
    return [Transaction(**dict(row)) for row in rows]

def insert_budget(conn: sqlite3.Connection, budget: Budget) -> None:
    """Insert a new budget."""
    conn.execute(
        """
        INSERT INTO budgets (
            id, user_id, category_id, period, limit_paise, warn_threshold_pct
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            budget.id, budget.user_id, budget.category_id, budget.period,
            budget.limit_paise, budget.warn_threshold_pct
        )
    )
    conn.commit()

def list_budgets(conn: sqlite3.Connection, user_id: str) -> List[Budget]:
    """List all budgets for a user."""
    rows = conn.execute(
        "SELECT * FROM budgets WHERE user_id = ?",
        (user_id,)
    ).fetchall()
    return [Budget(**dict(row)) for row in rows]

def update_transaction_category(
    conn: sqlite3.Connection,
    user_id: str,
    tx_id: str,
    category_id: Optional[str],
    category_source: str,
    category_confidence: Optional[float] = None
) -> None:
    """Update the category of an existing transaction."""
    conn.execute(
        """
        UPDATE transactions
        SET category_id = ?, category_source = ?, category_confidence = ?
        WHERE id = ? AND user_id = ?
        """,
        (category_id, category_source, category_confidence, tx_id, user_id)
    )
    conn.commit()
