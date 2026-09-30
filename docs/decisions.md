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
