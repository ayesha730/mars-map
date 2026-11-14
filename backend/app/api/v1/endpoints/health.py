from fastapi import APIRouter
from app.models.schemas import HealthStatus

router = APIRouter()

@router.get("/health", response_model=HealthStatus)
async def get_health():
    """
    Returns the system health, version, and planetary datum information.
    """
    return HealthStatus()
