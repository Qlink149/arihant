import os

from fastapi import FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.cors import CORSMiddleware

from crm.api.v1.router import api_router
from crm.core.rate_limit import limiter
from crm.core.platform_ops import warn_if_platform_operator_env_missing
from crm.core.secrets import validate_production_secrets
from crm.core.state import client, db, ensure_db_indexes, logger, seed_default_alert_configs

app = FastAPI(title="Arihant Sales Intelligence API")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Total-Count"],
)

app.include_router(api_router, prefix="/api")


async def warn_if_no_admin_user() -> None:
    count = await db.users.count_documents({"role": "admin"})
    if count == 0:
        logger.critical(
            "WARNING: No admin user found. Run seed script to create first admin: "
            "python scripts/create_admin.py (set ADMIN_EMAIL, ADMIN_PASSWORD, ADMIN_NAME)"
        )


@app.on_event("startup")
async def startup_event():
    validate_production_secrets()
    warn_if_platform_operator_env_missing()
    await warn_if_no_admin_user()
    await ensure_db_indexes()
    await seed_default_alert_configs()
    logger.info("Startup: Alert configs seeded")


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
