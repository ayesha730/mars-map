from fastapi import APIRouter, Request
from app.core.config import resolve_dem_path
from app.models.schemas import HealthStatus

router = APIRouter()


@router.get("/health", response_model=HealthStatus)
async def get_health(request: Request):
    """
    Returns the system health, version, planetary datum information, and DEM status.
    """
    regional_dems = getattr(request.app.state, "regional_dems", {})
    jezero_entry = regional_dems.get("jezero_crater")
    dem_loaded = bool(
        jezero_entry
        and jezero_entry.transformer
        and not jezero_entry.transformer.is_closed
    )
    dem_path = resolve_dem_path()
    dem_exists = dem_path.exists()

    return HealthStatus(
        dem_available=dem_exists,
        dem_loaded=dem_loaded or dem_exists,
        dem_path=str(dem_path) if dem_exists else None,
    )
