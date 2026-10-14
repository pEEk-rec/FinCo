"""`copilot serve`: start the API on localhost with a per-session token."""

from pathlib import Path

import uvicorn

from copilot.api.app import create_app
from copilot.api.services import DEMO_CLOCK, ensure_demo
from copilot.api.state import ApiState


def serve(db: str, port: int = 8765, demo: str = "empty", token: str | None = None) -> None:
    """Run the API. demo: 'empty' seeds categories/budgets/consent only; 'imported' also imports."""
    state = ApiState(db_path=Path(db), clock=DEMO_CLOCK)
    if token:
        state.token = token
    ensure_demo(state, "imported" if demo == "imported" else "empty")
    print(f"FinCo API on http://127.0.0.1:{port}")
    print(f"Session token: {state.token}")
    uvicorn.run(create_app(state), host="127.0.0.1", port=port, log_level="warning")
