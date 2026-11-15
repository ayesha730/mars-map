from fastapi import APIRouter

from app.api.v1.endpoints import (
    health,
    routes,
    regions,
    layers,
    elevation,
)

api_router = APIRouter()

# Health — service status and planetary datum
api_router.include_router(
    health.router,
)

# Routes — POST /api/v1/routes
api_router.include_router(
    routes.router,
)

# Regions — GET /api/v1/regions
#           GET /api/v1/regions/{region_id}
api_router.include_router(
    regions.router,
)

# Layers — GET /api/v1/layers
#          GET /api/v1/layers/{layer_id}/metadata
api_router.include_router(
    layers.router,
)

# Elevation — POST /api/v1/elevation/sample
api_router.include_router(
    elevation.router,
    prefix="/elevation",
    tags=["Elevation"],
)