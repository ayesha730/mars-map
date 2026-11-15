from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict

from app.models.schemas import (
    CoverageStatus,
    ElevationSampleRequest,
    ElevationSampleResponse,
)
from app.scientific.dem.service import (
    DEMUnavailableError,
    jezero_dem_service,
)
from app.scientific.dem.slope_service import (
    SlopeDEMUnavailableError,
    jezero_slope_service,
)

router = APIRouter()


class SlopeSampleResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    region_id: str
    latitude: float
    longitude: float
    pixel_row: int
    pixel_column: int
    method: str
    horizontal_resolution_m: list[float]
    vertical_units: str
    status: str
    center_elevation_raw: Optional[float] = None
    gradient_x_elevation_units_per_m: Optional[float] = None
    gradient_y_elevation_units_per_m: Optional[float] = None
    gradient_magnitude: Optional[float] = None
    slope_degrees: Optional[float] = None
    message: str


@router.post(
    "/sample",
    response_model=ElevationSampleResponse,
    status_code=status.HTTP_200_OK,
)
def sample_elevation(
    payload: ElevationSampleRequest,
) -> ElevationSampleResponse:
    """Sample a real elevation value from the Jezero CTX DEM."""

    if payload.region_id != "jezero_crater":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "REGION_NOT_FOUND",
                "message": (
                    f"Elevation sampling is not configured for "
                    f"region '{payload.region_id}'."
                ),
            },
        )

    try:
        result = jezero_dem_service.sample(
            latitude=payload.latitude,
            longitude=payload.longitude,
        )

    except DEMUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "DEM_UNAVAILABLE",
                "message": str(exc),
            },
        ) from exc

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "INVALID_COORDINATE",
                "message": str(exc),
            },
        ) from exc

    if result["status"] == "valid":
        coverage_status = CoverageStatus.VALID
    elif result["status"] == "out_of_bounds":
        coverage_status = CoverageStatus.OUT_OF_BOUNDS
    else:
        coverage_status = CoverageStatus.ELEVATION_UNAVAILABLE

    return ElevationSampleResponse(
        region_id=payload.region_id,
        latitude=payload.latitude,
        longitude=payload.longitude,
        status=coverage_status,
        geometric_coverage=result["geometric_coverage"],
        elevation_valid=result["elevation_valid"],
        elevation_m=result["elevation_m"],
        sampling_method="nearest_neighbor",
        coordinate_reference=payload.coordinate_reference,
        message=result["message"],
    )


@router.post(
    "/slope",
    response_model=SlopeSampleResponse,
    status_code=status.HTTP_200_OK,
)
def sample_slope(
    payload: ElevationSampleRequest,
) -> SlopeSampleResponse:
    """Calculate terrain gradient from the real Jezero CTX DEM."""

    if payload.region_id != "jezero_crater":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "REGION_NOT_FOUND",
                "message": (
                    f"Slope analysis is not configured for "
                    f"region '{payload.region_id}'."
                ),
            },
        )

    try:
        result = jezero_slope_service.sample(
            latitude=payload.latitude,
            longitude=payload.longitude,
        )

    except SlopeDEMUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "DEM_UNAVAILABLE",
                "message": str(exc),
            },
        ) from exc

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "INVALID_COORDINATE",
                "message": str(exc),
            },
        ) from exc

    return SlopeSampleResponse(**result)