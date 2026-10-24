"""`copilot serve`: start the API on localhost with a per-session token."""

from pathlib import Path

import uvicorn

from copilot.api.app import create_app
from copilot.api.services import DEMO_CLOCK, ensure_demo
from copilot.api.state import ApiState


def serve(
    db: str,
    port: int = 8765,
    demo: str = "empty",
    token: str | None = None,
    real_time: bool = False,
    lan: bool = False,
) -> None:
    """
    Run the API. demo: 'empty' seeds categories/budgets/consent only; 'imported' also imports.
    `real_time` uses the real clock instead of the fixed demo date (needed for live alerts).
    `lan` listens on the local network so a phone on the same Wi-Fi can reach the SMS bridge;
    only the bridge secret then protects it, so use a network you trust.
    """
    state = ApiState(db_path=Path(db), clock=None if real_time else DEMO_CLOCK)
    if token:
        state.token = token
    ensure_demo(state, "imported" if demo == "imported" else "empty")
    print(f"FinCo API on http://127.0.0.1:{port}")
    print(f"Session token: {state.token}")
    host = "0.0.0.0" if lan else "127.0.0.1"  # noqa: S104 - the owner asked for it
    if lan:
        print("WARNING: listening on the local network. Only the secrets protect this API.")
    uvicorn.run(create_app(state), host=host, port=port, log_level="warning")
