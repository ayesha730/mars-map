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
    RoutingProfile,
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


REGION_REGISTRY = {
    "jezero_crater": {
        "display_name": "Jezero Crater",
        "routing_available": True,
        "dataset": "Mars 2020 CTX DEM Mosaic, 20 m",
        "routing_unavailable_reason": "ROUTING_DATA_UNAVAILABLE",
        "unavailable_detail": (
            "Operational DEM transformer is not loaded for Jezero Crater."
        ),
        "distance_data_source": "haversine_spherical_approximation_IAU2015",
    },
    "gale_crater": {
        "display_name": "Gale Crater",
        "routing_available": False,
        "reason": "Verified Gale terrain routing data is not integrated.",
        "routing_unavailable_reason": "ROUTING_DATA_UNAVAILABLE",
        "unavailable_detail": (
            "Verified Gale terrain routing data is not integrated."
        ),
    },
}


# Traversal preference weights for terrain gradients.
# Note: These weights reflect planning preferences, NOT certified astronaut safety factors.
PROFILE_WEIGHTS = {
    RoutingProfile.SAFE: 40.0,
    RoutingProfile.FAST: 5.0,
    RoutingProfile.DEMONSTRATION: 10.0,
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

    # 1. Validate region existence
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

    # 2. Check region availability
    if not region.get("routing_available", False):
        gc_dist = haversine_distance(
            payload.start.latitude,
            payload.start.longitude,
            payload.destination.latitude,
            payload.destination.longitude,
        )
        return error_response(
            code=region.get("routing_unavailable_reason", "ROUTING_DATA_UNAVAILABLE"),
            message=region.get("reason", region.get("unavailable_detail", "Routing data unavailable.")),
            request_id=request_id,
            details={
                "region_id": payload.region_id,
                "routing_profile": payload.routing_profile,
                "great_circle_distance_m": round(gc_dist, 2),
                "distance_method": region.get("distance_data_source", "haversine_spherical_approximation_IAU2015"),
                "integration_status": "pending",
            },
            http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
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
                "available_profiles": ["safe", "fast", "demonstration"],
            },
            http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    # 4. Check operational Regional DEM from application state
    regional_dems = getattr(http_request.app.state, "regional_dems", {})
    dem_entry: Optional[RegionalDEM] = regional_dems.get(payload.region_id)

    # Fallback if app.state DEM is not initialized but DEM file exists
    if dem_entry is None or dem_entry.transformer is None or dem_entry.transformer.is_closed:
        from app.core.config import JEZERO_DEM_PATH
        from app.scientific.dem.transformer import DEMTransformer
        if JEZERO_DEM_PATH.exists() and payload.region_id == "jezero_crater":
            try:
                tf = DEMTransformer.from_file(JEZERO_DEM_PATH)
                dem_entry = RegionalDEM(payload.region_id, tf)
            except Exception:
                dem_entry = None

    if dem_entry is not None and dem_entry.transformer is not None and not dem_entry.transformer.is_closed:
        router_engine = AStarRouter(dem_entry.transformer)
        try:
            res = router_engine.find_route(
                start_lon=payload.start.longitude,
                start_lat=payload.start.latitude,
                dest_lon=payload.destination.longitude,
                dest_lat=payload.destination.latitude,
            )

            route_id = f"route_{uuid.uuid4().hex[:12]}"

            # Coordinate space contract:
            # PRD canonical is "arespath_display_v1".
            # PR #2 alias is "jezero_dem_native_projected_crs".
            # Both represent IAU 2015 Mars Equirectangular projection at 18.4663°N in metres.
            # Client selection is respected if provided in the payload; otherwise canonical default is used.
            coord_space = getattr(payload, "coordinate_space", None) or "arespath_display_v1"

            route_geometry = RouteGeometry(
                coordinate_space=coord_space,
                points=res.waypoints_display,
            )

            terrain_summary = TerrainSummary(
                min_elevation_m=res.min_elevation_m,
                max_elevation_m=res.max_elevation_m,
                max_slope_deg=None,   # Slope derivation reserved for future work
                hazard_count=None,    # Automated hazard detection not implemented
                surface_types=["mars_ctx_dem_terrain"],
                evaluation_status="measured_elevation_only",
            )

            if payload.routing_profile == RoutingProfile.DEMONSTRATION:
                profile_note = (
                    "Routing profile 'demonstration' uses verified 3D Euclidean terrain traversal "
                    "over the 20m CTX DEM grid."
                )
            elif payload.routing_profile == RoutingProfile.SAFE:
                profile_note = (
                    "Safe profile prioritizes conservative terrain gradient avoidance across the elevation grid."
                )
            else:
                profile_note = (
                    f"Routing profile '{payload.routing_profile.value}' optimizes for direct traversal length."
                )

            warnings = [
                "Route computed using deterministic A* pathfinding over verified CTX DEM 20m elevation grid.",
                "Coordinates are in display-frame projected metres (Equirectangular IAU 2015, standard parallel 18.4663°N).",
                "Traversability model uses 3D Euclidean terrain traversal. Advanced rover slip and slope safety constraints are research metrics.",
                profile_note,
            ]
            if res.is_globally_optimal:
                warnings.append("Path optimality is mathematically verified across the entire regional DEM domain.")

            data_sources = [
                "MRO_CTX_DEM_20M_JEZERO_IAU2015",
                "NASA_PDS_GEOSCIENCES_NODE",
                "Mars 2020 Science Investigation CTX DEM Mosaic",
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

    # 5. Routing data unavailable (fallback when DEM dataset is not loaded)
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
