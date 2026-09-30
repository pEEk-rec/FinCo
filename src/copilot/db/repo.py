"""
Data access layer for persistent state.

Every function takes `user_id` and filters by it. No function commits: callers wrap their
unit of work in `copilot.db.connection.savepoint`.
"""

import sqlite3
from typing import Optional

from copilot.models.domain import Account, Budget, Category, Transaction, User


def insert_user(conn: sqlite3.Connection, user: User) -> None:
    """Insert a new user."""
    conn.execute("INSERT INTO users (id, created_at) VALUES (?, ?)", (user.id, user.created_at))


def insert_account(conn: sqlite3.Connection, account: Account) -> None:
    """Insert a new account."""
    conn.execute(
        """
        INSERT INTO accounts (id, user_id, name, opening_balance_paise, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            account.id,
            account.user_id,
            account.name,
            account.opening_balance_paise,
            account.created_at,
        ),
    )


def get_account(conn: sqlite3.Connection, user_id: str, account_id: str) -> Optional[Account]:
    """Get an account by ID, or None if it does not exist for this user."""
    row = conn.execute(
        "SELECT * FROM accounts WHERE id = ? AND user_id = ?", (account_id, user_id)
    ).fetchone()
    return Account(**dict(row)) if row else None


def list_accounts(conn: sqlite3.Connection, user_id: str) -> list[Account]:
    """List all accounts for a user, ordered by id."""
    rows = conn.execute(
        "SELECT * FROM accounts WHERE user_id = ? ORDER BY id", (user_id,)
    ).fetchall()
    return [Account(**dict(row)) for row in rows]


def insert_category(conn: sqlite3.Connection, category: Category) -> None:
    """Insert a new category."""
    conn.execute(
        "INSERT INTO categories (id, user_id, name, created_at) VALUES (?, ?, ?, ?)",
        (category.id, category.user_id, category.name, category.created_at),
    )


def get_category(conn: sqlite3.Connection, user_id: str, category_id: str) -> Optional[Category]:
    """Get a category by ID, or None if it does not exist for this user."""
    row = conn.execute(
        "SELECT * FROM categories WHERE id = ? AND user_id = ?", (category_id, user_id)
    ).fetchone()
    return Category(**dict(row)) if row else None


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
            tx.id,
            tx.user_id,
            tx.account_id,
            tx.occurred_at,
            tx.amount_paise,
            tx.direction,
            tx.merchant_raw,
            tx.description,
            tx.category_id,
            tx.category_confidence,
            tx.category_source,
            tx.created_at,
        ),
    )


def get_transaction(conn: sqlite3.Connection, user_id: str, tx_id: str) -> Optional[Transaction]:
    """Get a transaction by ID, or None if it does not exist for this user."""
    row = conn.execute(
        "SELECT * FROM transactions WHERE id = ? AND user_id = ?", (tx_id, user_id)
    ).fetchone()
    return Transaction(**dict(row)) if row else None


def list_transactions(
    conn: sqlite3.Connection,
    user_id: str,
    start: str,
    end: str,
    category_id: Optional[str] = None,
    account_id: Optional[str] = None,
    limit: Optional[int] = None,
) -> list[Transaction]:
    """
    List a user's transactions with start <= occurred_at < end, oldest first.

    Optional filters: category, account, and a maximum row count.
    """
    query = """
        SELECT * FROM transactions
        WHERE user_id = ? AND occurred_at >= ? AND occurred_at < ?
    """
    params: list[str | int] = [user_id, start, end]
    if category_id is not None:
        query += " AND category_id = ?"
        params.append(category_id)
    if account_id is not None:
        query += " AND account_id = ?"
        params.append(account_id)
    query += " ORDER BY occurred_at ASC, id ASC"
    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)
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
            budget.id,
            budget.user_id,
            budget.category_id,
            budget.period,
            budget.limit_paise,
            budget.warn_threshold_pct,
        ),
    )


def list_budgets(conn: sqlite3.Connection, user_id: str) -> list[Budget]:
    """List all budgets for a user, ordered by category."""
    rows = conn.execute(
        "SELECT * FROM budgets WHERE user_id = ? ORDER BY category_id, id", (user_id,)
    ).fetchall()
    return [Budget(**dict(row)) for row in rows]


def update_transaction_category(
    conn: sqlite3.Connection,
    user_id: str,
    tx_id: str,
    category_id: Optional[str],
    category_source: str,
    category_confidence: Optional[float] = None,
) -> bool:
    """Update a transaction's category. Returns False if no such transaction for this user."""
    cursor = conn.execute(
        """
        UPDATE transactions
        SET category_id = ?, category_source = ?, category_confidence = ?
        WHERE id = ? AND user_id = ?
        """,
        (category_id, category_source, category_confidence, tx_id, user_id),
    )
    return cursor.rowcount == 1
