"""
POST /api/v1/routes

Implements the AresPath route-planning endpoint.

Scientific integrity guarantee
-------------------------------
No real Mars terrain data or operational A* service is bundled with the
current codebase.  Rather than fabricating a successful route, this endpoint
returns a documented ROUTING_DATA_UNAVAILABLE response while the data
integration work is in progress.

When a verified terrain dataset (e.g. HiRISE / CTX DEM) and an operational
A* graph service are wired in, replace the _compute_route stub below and
flip region_metadata["jezero_crater"]["routing_available"] to True.
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from app.models.schemas import (
    RouteRequest,
    RouteResponse,
    RouteGeometry,
    TerrainSummary,
    RouteAlgorithm,
    DisplayPoint,
    ErrorResponse,
    ErrorDetail,
    MarsCoordinateReference,
)
from app.scientific.geodesy import haversine_distance

router = APIRouter()


# ---------------------------------------------------------------------------
# Region registry
# ---------------------------------------------------------------------------
# This is a lightweight in-process registry that documents *what we know*
# about each supported region.  routing_available is False until real terrain
# data and a routing service are integrated.
# ---------------------------------------------------------------------------

REGION_REGISTRY: dict[str, dict] = {
    "jezero_crater": {
        "display_name": "Jezero Crater",
        "routing_available": False,
        "routing_unavailable_reason": "ROUTING_DATA_UNAVAILABLE",
        "unavailable_detail": (
            "Verified Mars terrain data (HiRISE/CTX DEM) and an operational "
            "A* path-finding service are not yet integrated. "
            "Connect a real dataset to enable routing."
        ),
        "distance_data_source": "haversine_spherical_approximation_IAU2015",
    },
    "gale_crater": {
        "display_name": "Gale Crater",
        "routing_available": False,
        "routing_unavailable_reason": "ROUTING_DATA_UNAVAILABLE",
        "unavailable_detail": (
            "Verified Mars terrain data and routing service not yet integrated."
        ),
        "distance_data_source": "haversine_spherical_approximation_IAU2015",
    },
}


# ---------------------------------------------------------------------------
# Routing stub
# ---------------------------------------------------------------------------

def _compute_route(request: RouteRequest) -> Optional[RouteResponse]:
    """
    Stub: returns None when no operational routing service is available.
    Replace this function body when real terrain data is integrated.
    """
    return None


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.post(
    "/routes",
    summary="Compute a surface route on Mars",
    response_model=RouteResponse,
    responses={
        200: {"model": RouteResponse, "description": "Route successfully computed"},
        422: {"model": ErrorResponse, "description": "Request validation error"},
        503: {
            "model": ErrorResponse,
            "description": "Routing data unavailable for the requested region",
        },
        404: {"model": ErrorResponse, "description": "Region not found"},
    },
    tags=["Routes"],
)
async def compute_route(payload: RouteRequest, http_request: Request):
    """
    Compute a surface traversal route between two Mars coordinates.

    **Coordinate convention** (must match request `coordinate_reference`):
    - body = Mars
    - latitude_type = planetocentric
    - longitude_direction = positive_east
    - longitude_domain = -180_to_180
    - angular_unit = degrees

    **Route geometry** is returned in the `arespath_display_v1` coordinate
    space: X = East metres, Y = North metres, region-specific projection.

    **Scientific integrity**: Returns `ROUTING_DATA_UNAVAILABLE` rather than
    fabricated routes when verified terrain data is not operational.
    """
    request_id = str(uuid.uuid4())

    # --- Region validation ---
    region = REGION_REGISTRY.get(payload.region_id)
    if region is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=ErrorResponse(
                error=ErrorDetail(
                    code="REGION_NOT_FOUND",
                    message=f"Region '{payload.region_id}' is not recognised.",
                    details={
                        "region_id": payload.region_id,
                        "supported_regions": list(REGION_REGISTRY.keys()),
                    },
                ),
                request_id=request_id,
            ).model_dump(),
        )

    # --- Try routing service ---
    result = _compute_route(payload)

    if result is not None:
        return result

    # --- Routing data unavailable (expected state until DEM is integrated) ---
    if not region["routing_available"]:
        # Provide haversine great-circle distance as informational only
        gc_distance_m = haversine_distance(
            payload.start.latitude,
            payload.start.longitude,
            payload.destination.latitude,
            payload.destination.longitude,
        )

        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=ErrorResponse(
                error=ErrorDetail(
                    code=region["routing_unavailable_reason"],
                    message=(
                        f"Routing is not available for region '{payload.region_id}'. "
                        f"{region['unavailable_detail']}"
                    ),
                    details={
                        "region_id": payload.region_id,
                        "routing_profile": payload.routing_profile,
                        "great_circle_distance_m": round(gc_distance_m, 2),
                        "distance_method": region["distance_data_source"],
                        "distance_disclaimer": (
                            "Great-circle distance is a spherical approximation "
                            "using MARS_IAU2015_SPHERE_RADIUS_M=3396190 m. "
                            "It does NOT account for terrain, obstacles, or slope. "
                            "It is not a navigable route."
                        ),
                        "integration_status": "pending",
                    },
                ),
                request_id=request_id,
            ).model_dump(),
        )

    # Fallback (should not be reached with current stub)
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content=ErrorResponse(
            error=ErrorDetail(
                code="ROUTING_DATA_UNAVAILABLE",
                message="Routing service is not available.",
                details=None,
            ),
            request_id=request_id,
        ).model_dump(),
    )
