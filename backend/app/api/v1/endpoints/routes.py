from __future__ import annotations

import uuid

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
    RoutingProfile,
)
from app.scientific.geodesy import haversine_distance
from app.scientific.dem.routing_service import (
    jezero_routing_service,
    RoutingDataError,
)

router = APIRouter()


REGION_REGISTRY = {
    "jezero_crater": {
        "display_name": "Jezero Crater",
        "routing_available": True,
        "dataset": "Mars 2020 CTX DEM Mosaic, 20 m",
    },
    "gale_crater": {
        "display_name": "Gale Crater",
        "routing_available": False,
        "reason": "Verified Gale terrain routing data is not integrated.",
    },
}


# These weights control preference for lower terrain gradients.
# They do NOT represent certified astronaut safety levels.
PROFILE_WEIGHTS = {
    RoutingProfile.SAFE: 40.0,
    RoutingProfile.FAST: 5.0,
}


def error_response(
    code: str,
    message: str,
    request_id: str,
    details: dict | None = None,
    http_status: int = 503,
):
    return JSONResponse(
        status_code=http_status,
        content=ErrorResponse(
            error=ErrorDetail(
                code=code,
                message=message,
                details=details,
            ),
            request_id=request_id,
        ).model_dump(mode="json"),
    )


@router.post(
    "/routes",
    summary="Compute a surface route on Mars",
    response_model=RouteResponse,
    responses={
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
    tags=["Routes"],
)
async def compute_route(
    payload: RouteRequest,
    http_request: Request,
):
    request_id = str(uuid.uuid4())

    # 1. Validate region
    region = REGION_REGISTRY.get(payload.region_id)

    if region is None:
        return error_response(
            code="REGION_NOT_FOUND",
            message=f"Region '{payload.region_id}' is not recognised.",
            request_id=request_id,
            details={
                "supported_regions": list(REGION_REGISTRY.keys()),
            },
            http_status=status.HTTP_404_NOT_FOUND,
        )

    # 2. Keep unsupported regions unavailable
    if not region["routing_available"]:
        return error_response(
            code="ROUTING_DATA_UNAVAILABLE",
            message=region["reason"],
            request_id=request_id,
            details={
                "region_id": payload.region_id,
                "integration_status": "pending",
            },
        )

    # 3. Science profile requires additional verified science layers
    if payload.routing_profile == RoutingProfile.SCIENCE:
        return error_response(
            code="SCIENCE_PROFILE_UNAVAILABLE",
            message=(
                "Science-oriented routing is not yet available. "
                "Verified science observation layers must be integrated first."
            ),
            request_id=request_id,
            details={
                "available_profiles": ["safe", "fast"],
            },
        )

    # 4. Calculate informational great-circle distance
    great_circle_distance = haversine_distance(
        payload.start.latitude,
        payload.start.longitude,
        payload.destination.latitude,
        payload.destination.longitude,
    )

    # 5. Compute actual terrain route using Jezero DEM + A*
    gradient_weight = PROFILE_WEIGHTS[payload.routing_profile]

    try:
        result = jezero_routing_service.compute_route(
            start_latitude=payload.start.latitude,
            start_longitude=payload.start.longitude,
            destination_latitude=payload.destination.latitude,
            destination_longitude=payload.destination.longitude,
            gradient_weight=gradient_weight,
        )

    except RoutingDataError as exc:
        return error_response(
            code="ROUTE_COMPUTATION_FAILED",
            message=str(exc),
            request_id=request_id,
            details={
                "region_id": payload.region_id,
                "routing_profile": payload.routing_profile.value,
            },
        )

    except ValueError as exc:
        return error_response(
            code="INVALID_ROUTE_INPUT",
            message=str(exc),
            request_id=request_id,
            details=None,
            http_status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    except Exception:
        return error_response(
            code="ROUTING_INTERNAL_ERROR",
            message="An unexpected error occurred during route computation.",
            request_id=request_id,
        )

    # 6. Preserve the actual DEM coordinate system.
    # Do not label these points as arespath_display_v1.
    route_points = [
        DisplayPoint(x=x, y=y)
        for x, y in result.projected_points
    ]

    # 7. Build response
    warnings = [
        "Route generated using the Jezero CTX DEM and A* search.",
        "Coordinates are in the native projected CRS of the Jezero DEM.",
        "DEM vertical units are unverified; elevation and slope summaries are omitted.",
        "Terrain-gradient cost is a relative planning preference, not a certified safety assessment.",
        "Great-circle distance is informational and differs from terrain route distance.",
    ]

    if payload.routing_profile == RoutingProfile.SAFE:
        warnings.append(
            "Safe profile uses a stronger terrain-gradient penalty; "
            "it does not guarantee a hazard-free route."
        )
    else:
        warnings.append(
            "Fast profile uses a lower terrain-gradient penalty "
            "to favour shorter traversal."
        )

    return RouteResponse(
        status="success",
        route_id=str(uuid.uuid4()),
        region_id=payload.region_id,
        algorithm=RouteAlgorithm.ASTAR,
        distance_m=float(result.path.distance_m),
        route_geometry=RouteGeometry(
            coordinate_space="jezero_dem_native_projected_crs",
            points=route_points,
        ),
        terrain_summary=TerrainSummary(
            min_elevation_m=None,
            max_elevation_m=None,
            max_slope_deg=None,
            hazard_count=0,
            surface_types=[],
        ),
        warnings=warnings,
        data_sources=[
            "Mars 2020 Science Investigation CTX DEM Mosaic",
            "Jezero DEM 20m raster",
            "A* terrain cost-grid routing",
        ],
    )