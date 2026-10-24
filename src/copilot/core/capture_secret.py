"""
The webhook secret for the SMS bridge (PLAN_CAPTURE Stage C5).

The phone automation sends this in a header. It comes from the CAPTURE_WEBHOOK_SECRET
environment variable, or from `data/capture_secret` (git-ignored), which `copilot capture
bridge-setup` creates on first use. There is no default and no open endpoint: without a secret
the webhook refuses everything.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from copilot.core.config import PROJECT_ROOT

SECRET_FILE = PROJECT_ROOT / "data" / "capture_secret"
ENV_VAR = "CAPTURE_WEBHOOK_SECRET"


def load_capture_secret(path: Path | None = None) -> str | None:
    """The configured secret, or None when the bridge has not been set up."""
    env = os.environ.get(ENV_VAR, "").strip()
    if env:
        return env
    file = path or SECRET_FILE
    if file.exists():
        text = file.read_text(encoding="utf-8").strip()
        return text or None
    return None


def ensure_capture_secret(path: Path | None = None) -> tuple[str, bool]:
    """(secret, created). Creates a strong one the first time and keeps it on this computer."""
    existing = load_capture_secret(path)
    if existing:
        return existing, False
    file = path or SECRET_FILE
    file.parent.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_urlsafe(24)
    file.write_text(secret + "\n", encoding="utf-8")
    try:
        file.chmod(0o600)
    except OSError:  # not supported on every platform; the file is still git-ignored
        pass
    return secret, True
