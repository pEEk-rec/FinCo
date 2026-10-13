"""
Data access layer for persistent state.

Every function takes `user_id` and filters by it. No function commits: callers wrap their
unit of work in `copilot.db.connection.savepoint`.
"""

import sqlite3

from copilot.models.domain import Account, Budget, Category, Transaction, User
from copilot.models.memory import MemoryEntry


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


def get_account(conn: sqlite3.Connection, user_id: str, account_id: str) -> Account | None:
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


def get_category(conn: sqlite3.Connection, user_id: str, category_id: str) -> Category | None:
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
            category_source, created_at, fingerprint, batch_id,
            merchant_normalized, mode, is_duplicate_of, needs_review,
            excluded_from_spend
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            tx.fingerprint,
            tx.batch_id,
            tx.merchant_normalized,
            tx.mode,
            tx.is_duplicate_of,
            1 if tx.needs_review else 0,
            1 if tx.excluded_from_spend else 0,
        ),
    )


def get_transaction(conn: sqlite3.Connection, user_id: str, tx_id: str) -> Transaction | None:
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
    category_id: str | None = None,
    account_id: str | None = None,
    limit: int | None = None,
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
            id, user_id, category_id, period, limit_paise, warn_threshold_pct, forecast_warn
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            budget.id,
            budget.user_id,
            budget.category_id,
            budget.period,
            budget.limit_paise,
            budget.warn_threshold_pct,
            1 if budget.forecast_warn else 0,
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
    category_id: str | None,
    category_source: str,
    category_confidence: float | None = None,
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


def insert_memory_entry(conn: sqlite3.Connection, entry: MemoryEntry) -> None:
    """Insert a memory entry."""
    conn.execute(
        """
        INSERT INTO memory_entries (
            id, user_id, kind, content, source, confidence,
            created_at, last_confirmed_at, provenance
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            entry.id,
            entry.user_id,
            entry.kind,
            entry.content,
            entry.source,
            entry.confidence,
            entry.created_at,
            entry.last_confirmed_at,
            entry.provenance,
        ),
    )


def list_memory_entries(
    conn: sqlite3.Connection, user_id: str, kind: str | None = None
) -> list[MemoryEntry]:
    """List a user's memory entries (optionally one kind), oldest first. No ranking."""
    query = "SELECT * FROM memory_entries WHERE user_id = ?"
    params: list[str] = [user_id]
    if kind is not None:
        query += " AND kind = ?"
        params.append(kind)
    query += " ORDER BY created_at ASC, id ASC"
    return [MemoryEntry(**dict(row)) for row in conn.execute(query, params).fetchall()]
