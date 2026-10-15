"""Test safety net: unit tests must NEVER touch a real database.

backend/.env points at PRODUCTION, and crm.core.state builds its Mongo client from it at import
time. A unit test that mocks one module's `db` but exercises code in another (an alert helper,
the visit log...) silently wrote to production: 4 fake Admin alerts and a fake site visit were
created that way. So, before any test module imports crm.core.state, the database URL is
replaced with an unreachable one. Real-database (integration) runs opt out:

  pytest -m integration        (or RUN_REAL_DB_TESTS=1)

state.py's load_dotenv() does not override variables that are already set, so this wins over .env.
"""

from __future__ import annotations

import os
import sys


def _is_disposable_local_db() -> bool:
    """CI starts its own throwaway Mongo and passes its URL in the process environment."""
    url = os.environ.get("MONGO_URL", "")
    return os.environ.get("CI") == "true" and ("localhost" in url or "127.0.0.1" in url)


def _wants_real_db() -> bool:
    if _is_disposable_local_db():
        return True
    if os.environ.get("RUN_REAL_DB_TESTS") == "1":
        return True
    argv = " ".join(sys.argv)
    return "integration" in argv and "not integration" not in argv


if not _wants_real_db():
    # Port 1 refuses connections at once, so an accidental DB call fails fast instead of hanging.
    os.environ["MONGO_URL"] = "mongodb://127.0.0.1:1/?serverSelectionTimeoutMS=300&connectTimeoutMS=300"
    os.environ["DB_NAME"] = "arihant_crm_unit_tests_no_db"
    os.environ.setdefault("SECRET_KEY", "unit-test-secret-key-not-for-production")
