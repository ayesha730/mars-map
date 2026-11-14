from fastapi import APIRouter
from app.api.v1.endpoints import health, routes, regions, layers

api_router = APIRouter()

# Health — preserved, unchanged
api_router.include_router(health.router)

# Routes — POST /api/v1/routes
api_router.include_router(routes.router)

# Regions — GET /api/v1/regions, GET /api/v1/regions/{region_id}
api_router.include_router(regions.router)

# Layers — GET /api/v1/layers, GET /api/v1/layers/{layer_id}/metadata
api_router.include_router(layers.router)
