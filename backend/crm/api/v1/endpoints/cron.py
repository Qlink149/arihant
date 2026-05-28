import os

from fastapi import APIRouter, Header, HTTPException, status

from crm.services.sla_engine import SLAEngineService

router = APIRouter(prefix="/v1/cron", tags=["cron"])


def _verify_cron_secret(authorization: str | None) -> None:
    secret = os.environ.get("CRON_SECRET")
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="CRON_SECRET is not configured",
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization[7:].strip()
    if token != secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid cron secret",
            headers={"WWW-Authenticate": "Bearer"},
        )


@router.post("/process-slas")
async def process_slas(authorization: str | None = Header(default=None)):
    _verify_cron_secret(authorization)
    result = await SLAEngineService().process_all_slas()
    return result
