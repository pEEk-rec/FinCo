"""
Command Line Interface for Finance Copilot (PLAN_PHASE1 Section 5.9).
"""

__all__ = ["app"]


def __getattr__(name: str):
    if name == "app":
        from copilot.cli.main import app

        return app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
