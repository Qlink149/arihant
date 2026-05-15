from fastapi import APIRouter

router = APIRouter()


@router.get("/")
async def root():
    return {"message": "Arihant Sales Intelligence API", "version": "1.0.0"}


@router.get("/health")
async def health():
    return {"status": "healthy"}
