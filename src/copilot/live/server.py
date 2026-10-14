"""`python -m copilot.live`: the main app on real data, with the rails and AA routes added."""

import argparse
import os
import secrets
from pathlib import Path

import uvicorn

from copilot.api.app import create_app
from copilot.api.state import ApiState
from copilot.live import service
from copilot.live.aa import AAClient
from copilot.live.api import WEBHOOK_PATH, attach_live_routes, load_aa

DEFAULT_DB = Path(__file__).resolve().parents[3] / "frontend" / ".demo" / "live.db"


def build_live(
    db: Path,
    token: str | None,
    webhook_secret: str | None,
    use_llm: bool,
    aa: AAClient | None | str = "env",
):
    """(app, state, webhook secret). Real clock, empty profile, model off unless asked."""
    state = ApiState(
        db_path=db,
        user_id="me",
        clock=None,
        data_source="connected",
        llm="auto" if use_llm else None,
        allowed_origins=("http://localhost:5273", "http://127.0.0.1:5273"),
    )
    if token:
        state.token = token
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = state.connect()
    try:
        service.seed_live(state, conn)
        conn.commit()
    finally:
        conn.close()
    secret = webhook_secret or secrets.token_urlsafe(18)
    app = create_app(state)
    attach_live_routes(app, state, secret, load_aa() if aa == "env" else aa)  # type: ignore[arg-type]
    return app, state, secret


def main() -> None:
    parser = argparse.ArgumentParser(prog="copilot.live")
    parser.add_argument("--db", default=os.environ.get("LIVE_DB", str(DEFAULT_DB)))
    parser.add_argument("--port", type=int, default=int(os.environ.get("LIVE_PORT", "8200")))
    parser.add_argument("--token", default=os.environ.get("LIVE_TOKEN"))
    parser.add_argument("--webhook-secret", default=os.environ.get("LIVE_WEBHOOK_SECRET"))
    parser.add_argument("--no-llm", action="store_true", help="keep the language model off")
    args = parser.parse_args()
    app, state, secret = build_live(
        Path(args.db), args.token, args.webhook_secret, not args.no_llm
    )
    print(f"FinCo LIVE API on http://127.0.0.1:{args.port}   (real data, database: {args.db})")
    print(f"Session token: {state.token}")
    print(
        f"SMS webhook: POST http://<this-computer>:{args.port}{WEBHOOK_PATH}  header X-Webhook-Secret: {secret}"
    )
    uvicorn.run(
        app,
        host="0.0.0.0" if os.environ.get("LIVE_LAN") else "127.0.0.1",
        port=args.port,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
