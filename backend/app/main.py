import asyncio
import os

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from app.core.state import client, ensure_db_indexes, logger, seed_default_alert_configs
from app.routers.activity import router as activity_router
from app.routers.alerts import router as alerts_router
from app.routers.analytics import router as analytics_router
from app.routers.assignment_rules import router as assignment_rules_router
from app.routers.auth import router as auth_router
from app.routers.call_summary import router as call_summary_router
from app.routers.campaigns import router as campaigns_router
from app.routers.leads import router as leads_router
from app.routers.marketing import router as marketing_router
from app.routers.misc import router as misc_router
from app.routers.my_dashboard import router as my_dashboard_router
from app.routers.notifications import router as notifications_router
from app.routers.projects import router as projects_router
from app.routers.reminders import process_reminders, router as reminders_router
from app.routers.suggestions import router as suggestions_router
from app.routers.tasks import router as tasks_router
from app.routers.transfers import router as transfers_router
from app.routers.whatsapp import router as whatsapp_router

app = FastAPI(title="Arihant Sales Intelligence API")

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in [
    auth_router,
    projects_router,
    leads_router,
    analytics_router,
    campaigns_router,
    call_summary_router,
    tasks_router,
    notifications_router,
    assignment_rules_router,
    alerts_router,
    suggestions_router,
    whatsapp_router,
    activity_router,
    my_dashboard_router,
    transfers_router,
    marketing_router,
    reminders_router,
    misc_router,
]:
    app.include_router(r, prefix="/api")

reminder_task = None


async def _reminder_scheduler():
    while True:
        try:
            await asyncio.sleep(3600)
            await process_reminders()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Reminder scheduler error: {e}")
            await asyncio.sleep(60)


@app.on_event("startup")
async def startup_event():
    global reminder_task
    await ensure_db_indexes()
    await seed_default_alert_configs()
    reminder_task = asyncio.create_task(_reminder_scheduler())
    asyncio.create_task(process_reminders())
    logger.info("Startup: Alert configs seeded, reminder scheduler started")


@app.on_event("shutdown")
async def shutdown_db_client():
    global reminder_task
    if reminder_task:
        reminder_task.cancel()
    client.close()
