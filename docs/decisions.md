# Architecture Decisions Log

## Deferred
- LangGraph and fixed agent workflows
- Actual categorization logic / LLM categorization
- Monthly review, advice drafting, dispute flow UI
- Real planner, hypothesis/evidence reasoning
- What-if simulation, adaptive alerts
- Real bank and payment integrations
- Authentication and multi-user access

## Step 0: Project skeleton
What was built: The foundational project structure, `pyproject.toml`, and configuration for testing and linting.
Why it was designed this way: A standard modern Python structure with Pydantic for models and pytest/ruff for QA ensures strictness from day one.
What it is deliberately not doing: No application code or logic is written yet.

## Step 1: Money and time primitives
What was built: Core utilities for handling money as integer paise and time as UTC ISO strings with IST bounds.
Why it was designed this way: Prevents floating-point errors by using exact integers/Decimals for money, and enforces a standard timezone (Asia/Kolkata) to avoid naive datetime bugs.
What it is deliberately not doing: No general-purpose timezone conversion or currency conversion is implemented; it strictly handles INR and IST.

## Step 2: Domain models and database schema
What was built: Pydantic models for core entities (User, Account, Category, Transaction, Budget) and a raw SQLite schema with strict `CHECK` constraints.
Why it was designed this way: A raw SQLite schema avoids the overhead of an ORM while providing strong guarantees (e.g., negative budget limit prevention, foreign keys). `user_id` is mandatory on all tables to enforce data boundaries natively.
What it is deliberately not doing: No goals or virtual buckets logic is implemented; the tables are just reserved. No ORM is used.


