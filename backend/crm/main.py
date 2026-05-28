import os

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from crm.api.v1.router import api_router
from crm.core.platform_ops import warn_if_platform_operator_env_missing
from crm.core.state import client, ensure_db_indexes, logger, seed_default_alert_configs

app = FastAPI(title="Arihant Sales Intelligence API")

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Total-Count"],
)

app.include_router(api_router, prefix="/api")


@app.on_event("startup")
async def startup_event():
    warn_if_platform_operator_env_missing()
    await ensure_db_indexes()
    await seed_default_alert_configs()
    logger.info("Startup: Alert configs seeded")


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
