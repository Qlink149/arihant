"""Production secret validation at startup."""

from __future__ import annotations

import os
import sys

WEAK_DEFAULTS = frozenset(
    {
        "",
        "secret",
        "changeme",
        "your-secret-key",
        "supersecretkey",
        "development",
        "test",
        "arihant-secret-key-change-in-production",
        "change-me-to-a-long-random-string",
    }
)


def validate_production_secrets() -> None:
    if os.getenv("ENVIRONMENT", "").strip().lower() == "test":
        return

    secret_key = os.getenv("SECRET_KEY", "")
    cron_secret = os.getenv("CRON_SECRET", "")

    if secret_key.lower() in WEAK_DEFAULTS or len(secret_key) < 32:
        print(
            "FATAL: SECRET_KEY is missing or too weak. "
            "Set a strong SECRET_KEY (32+ chars) in environment."
        )
        sys.exit(1)

    if cron_secret.lower() in WEAK_DEFAULTS or len(cron_secret) < 16:
        print(
            "FATAL: CRON_SECRET is missing or too weak. "
            "Set a strong CRON_SECRET in environment."
        )
        sys.exit(1)
