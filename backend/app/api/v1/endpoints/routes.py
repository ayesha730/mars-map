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
from app.scientific.dem.service import RegionalDEM
from app.scientific.geodesy import haversine_distance
from app.scientific.routing.astar import (
    AStarRouter,
    StartOutOfBoundsError,
    DestinationOutOfBoundsError,
    StartNoDataError,
    DestinationNoDataError,
    PathNotFoundError,
    RoutingError,
)

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
        "routing_available": True,
        "routing_unavailable_reason": "ROUTING_DATA_UNAVAILABLE",
        "unavailable_detail": (
            "Operational DEM transformer is not loaded for Jezero Crater."
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

    # --- Check operational Regional DEM from app state ---
    regional_dems = getattr(http_request.app.state, "regional_dems", {})
    dem_entry: Optional[RegionalDEM] = regional_dems.get(payload.region_id)

    if dem_entry is not None and dem_entry.transformer is not None and not dem_entry.transformer.is_closed:
        # Operational DEM available: run deterministic A* routing
        router = AStarRouter(dem_entry.transformer)
        try:
            res = router.find_route(
                start_lon=payload.start.longitude,
                start_lat=payload.start.latitude,
                dest_lon=payload.destination.longitude,
                dest_lat=payload.destination.latitude,
            )

            route_id = f"route_{uuid.uuid4().hex[:12]}"
            route_geometry = RouteGeometry(
                coordinate_space="arespath_display_v1",
                points=res.waypoints_display,
            )
            terrain_summary = TerrainSummary(
                min_elevation_m=res.min_elevation_m,
                max_elevation_m=res.max_elevation_m,
                max_slope_deg=None,   # Not evaluated: slope derivation is future work
                hazard_count=None,    # Not evaluated: automated hazard detection not implemented
                surface_types=["mars_ctx_dem_terrain"],
                evaluation_status="measured_elevation_only",
            )

            # Profile semantics documentation
            if payload.routing_profile.value == "demonstration":
                profile_note = (
                    "Routing profile 'demonstration' uses verified 3D Euclidean terrain traversal "
                    "over the 20m CTX DEM grid."
                )
            else:
                profile_note = (
                    f"Routing profile '{payload.routing_profile.value}' is currently aliased to the baseline "
                    "3D Euclidean traversal model. Profile-specific cost weighting (slope penalties for 'safe', "
                    "velocity models for 'fast', and science interest weighting for 'science') is reserved "
                    "for future telemetry integration."
                )

            warnings = [
                "Route computed using deterministic A* pathfinding over verified CTX DEM 20m elevation grid.",
                "Traversability model uses 3D Euclidean terrain traversal. Advanced rover slip and slope safety constraints are research metrics.",
                profile_note,
            ]
            if res.is_globally_optimal:
                warnings.append("Path optimality is mathematically verified across the entire regional DEM domain.")

            data_sources = [
                "MRO_CTX_DEM_20M_JEZERO_IAU2015",
                "NASA_PDS_GEOSCIENCES_NODE",
            ]

            return RouteResponse(
                status="success",
                route_id=route_id,
                region_id=payload.region_id,
                algorithm=RouteAlgorithm.ASTAR,
                distance_m=res.distance_m,
                route_geometry=route_geometry,
                terrain_summary=terrain_summary,
                warnings=warnings,
                data_sources=data_sources,
            )

        except (StartOutOfBoundsError, DestinationOutOfBoundsError) as exc:
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                content=ErrorResponse(
                    error=ErrorDetail(
                        code="COORDINATE_OUT_OF_BOUNDS",
                        message=str(exc),
                        details={"region_id": payload.region_id},
                    ),
                    request_id=request_id,
                ).model_dump(),
            )
        except (StartNoDataError, DestinationNoDataError) as exc:
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                content=ErrorResponse(
                    error=ErrorDetail(
                        code="NODATA_COLLAR_COORDINATE",
                        message=str(exc),
                        details={"region_id": payload.region_id},
                    ),
                    request_id=request_id,
                ).model_dump(),
            )
        except PathNotFoundError as exc:
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                content=ErrorResponse(
                    error=ErrorDetail(
                        code="NO_TRAVERSABLE_PATH",
                        message=str(exc),
                        details={"region_id": payload.region_id},
                    ),
                    request_id=request_id,
                ).model_dump(),
            )
        except RoutingError as exc:
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                content=ErrorResponse(
                    error=ErrorDetail(
                        code="ROUTING_ERROR",
                        message=str(exc),
                        details={"region_id": payload.region_id},
                    ),
                    request_id=request_id,
                ).model_dump(),
            )

    # --- Routing data unavailable (expected state when DEM dataset is not loaded) ---
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
                code=region.get("routing_unavailable_reason", "ROUTING_DATA_UNAVAILABLE"),
                message=(
                    f"Routing is not available for region '{payload.region_id}'. "
                    f"{region.get('unavailable_detail', 'No operational DEM transformer loaded.')}"
                ),
                details={
                    "region_id": payload.region_id,
                    "routing_profile": payload.routing_profile,
                    "great_circle_distance_m": round(gc_distance_m, 2),
                    "distance_method": region.get("distance_data_source", "haversine_spherical_approximation_IAU2015"),
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
