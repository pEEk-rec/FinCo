"""`python -m copilot.rails`: run the rails demo API on its own port and database."""

import argparse
import os
from pathlib import Path

import uvicorn

from copilot.api.services import DEMO_CLOCK, ensure_demo
from copilot.api.state import ApiState
from copilot.rails.api import create_rails_app
from copilot.rails.engine import ensure_schema

DEFAULT_DB = Path(__file__).resolve().parents[3] / "frontend" / ".demo" / "rails.db"


def build_state(db: Path, token: str | None) -> ApiState:
    """A demo-seeded state with its own database file (never the main demo's)."""
    state = ApiState(db_path=db, clock=DEMO_CLOCK, llm=None)
    if token:
        state.token = token
    db.parent.mkdir(parents=True, exist_ok=True)
    ensure_demo(state, "imported")
    conn = state.connect()
    try:
        ensure_schema(conn)
        conn.commit()
    finally:
        conn.close()
    return state


def serve(db: Path, port: int, token: str | None) -> None:
    state = build_state(db, token)
    print(f"FinCo Rails demo on http://127.0.0.1:{port}/?token={state.token}")
    print(f"API docs: http://127.0.0.1:{port}/docs   (database: {db})")
    uvicorn.run(create_rails_app(state), host="127.0.0.1", port=port, log_level="warning")


def main() -> None:
    parser = argparse.ArgumentParser(prog="copilot.rails")
    parser.add_argument("--db", default=os.environ.get("RAILS_DB", str(DEFAULT_DB)))
    parser.add_argument("--port", type=int, default=int(os.environ.get("RAILS_PORT", "8100")))
    parser.add_argument("--token", default=os.environ.get("RAILS_TOKEN"))
    args = parser.parse_args()
    serve(Path(args.db), args.port, args.token)


if __name__ == "__main__":
    main()
