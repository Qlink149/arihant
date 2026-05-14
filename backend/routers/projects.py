from fastapi import APIRouter, Depends

from backend.app_state import PROJECT_REGISTRY, get_current_user


router = APIRouter()


@router.get("/projects")
async def get_projects(current_user: dict = Depends(get_current_user)):
    return PROJECT_REGISTRY

