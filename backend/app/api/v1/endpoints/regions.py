"""
GET /api/v1/regions
GET /api/v1/regions/{region_id}

Region and layer metadata endpoint, satisfying the metadata contract:
  - Source coordinate reference system
  - Latitude type and longitude convention
  - Display projection definition
  - Local display-frame origin
  - X/Y axis units
  - Transformation method and parameters
  - Dataset coverage and provenance

NOTE ON SCIENTIFIC INTEGRITY
-----------------------------
Actual numeric projection parameters (standard parallels, false easting, etc.)
depend on the specific DEM/orthoimage dataset used for each region.
They are NOT invented here — fields that require verified dataset config are
set to None with an explicit note.  When a dataset is integrated, populate
those fields from its documented metadata (e.g. PDS label, FITS header,
PROJ4 string from the GeoTIFF).
"""

from __future__ import annotations

import uuid
from typing import List

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from app.models.schemas import (
    RegionMetadata,
    DisplayProjectionDefinition,
    DisplayOrigin,
    TransformationParameters,
    DatasetProvenance,
    MarsCoordinateReference,
    ErrorResponse,
    ErrorDetail,
)

router = APIRouter()

# ---------------------------------------------------------------------------
# Region metadata registry
# ---------------------------------------------------------------------------
# All numeric projection parameters are explicitly None until a verified
# dataset is integrated.  This is intentional — see module docstring.
# ---------------------------------------------------------------------------

_REGIONS: dict[str, RegionMetadata] = {
    "jezero_crater": RegionMetadata(
        region_id="jezero_crater",
        display_name="Jezero Crater",
        description=(
            "Ancient lake-delta system, landing site of NASA Mars 2020 "
            "Perseverance rover (~18.4°N, 77.7°E)."
        ),
        source_crs=MarsCoordinateReference(),
        display_projection=DisplayProjectionDefinition(
            projection_name=None,  # To be populated from verified DEM PDS label
            proj4_string=None,     # Requires verified CTX/HiRISE dataset config
            wkt2_string=None,      # Requires verified CTX/HiRISE dataset config
        ),
        display_origin=DisplayOrigin(
            description=(
                "Region-specific origin, to be defined from the verified DEM "
                "dataset extent.  Not yet assigned."
            ),
            latitude_deg=None,   # Populated from verified dataset config
            longitude_deg=None,  # Populated from verified dataset config
            source=None,
        ),
        transformation=TransformationParameters(
            method="Pending — awaiting verified DEM dataset integration",
            parameters=None,     # Populated from verified dataset config
            notes=(
                "Transformation from Mars planetocentric lat/lon to the "
                "arespath_display_v1 local East-North frame will be defined "
                "once the HiRISE/CTX DEM PDS label is processed."
            ),
        ),
        datasets=[
            DatasetProvenance(
                name="Placeholder — no verified terrain dataset integrated",
                agency="N/A",
                instrument=None,
                mission=None,
                resolution_m_per_px=None,
                coverage=None,
                reference_url=None,
                is_synthetic=True,
                synthetic_description=(
                    "Real data would be a CTX or HiRISE DEM from MRO, "
                    "available via NASA PDS Geosciences Node."
                ),
            )
        ],
        routing_available=False,
        routing_unavailable_reason="ROUTING_DATA_UNAVAILABLE",
    ),
    "gale_crater": RegionMetadata(
        region_id="gale_crater",
        display_name="Gale Crater",
        description=(
            "Impact crater with central mound (Aeolis Mons / Mt Sharp), "
            "landing site of NASA MSL Curiosity rover (~5.4°S, 137.8°E)."
        ),
        source_crs=MarsCoordinateReference(),
        display_projection=DisplayProjectionDefinition(
            projection_name=None,
            proj4_string=None,
            wkt2_string=None,
        ),
        display_origin=DisplayOrigin(
            description=(
                "Region-specific origin — to be defined from verified DEM."
            ),
            latitude_deg=None,
            longitude_deg=None,
            source=None,
        ),
        transformation=TransformationParameters(
            method="Pending — awaiting verified DEM dataset integration",
            parameters=None,
            notes="Same approach as Jezero; dataset not yet integrated.",
        ),
        datasets=[
            DatasetProvenance(
                name="Placeholder — no verified terrain dataset integrated",
                agency="N/A",
                is_synthetic=True,
                synthetic_description=(
                    "Real data would be CTX/HiRISE DEM from MRO via NASA PDS."
                ),
            )
        ],
        routing_available=False,
        routing_unavailable_reason="ROUTING_DATA_UNAVAILABLE",
    ),
}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/regions",
    response_model=List[RegionMetadata],
    summary="List all supported Mars surface regions with full metadata",
    tags=["Regions"],
)
async def list_regions():
    """
    Returns the full metadata contract for every registered Mars surface
    region, including:
    - Source coordinate reference system
    - Display projection definition (None where dataset not yet integrated)
    - Local display-frame origin
    - X/Y axis units
    - Transformation method and parameters
    - Dataset coverage and provenance
    """
    return list(_REGIONS.values())


@router.get(
    "/regions/{region_id}",
    response_model=RegionMetadata,
    summary="Get metadata for a specific Mars surface region",
    responses={
        404: {"model": ErrorResponse, "description": "Region not found"},
    },
    tags=["Regions"],
)
async def get_region(region_id: str, http_request: Request):
    """
    Returns the full metadata contract for the requested region.
    """
    region = _REGIONS.get(region_id)
    if region is None:
        request_id = str(uuid.uuid4())
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=ErrorResponse(
                error=ErrorDetail(
                    code="REGION_NOT_FOUND",
                    message=f"Region '{region_id}' is not recognised.",
                    details={
                        "region_id": region_id,
                        "supported_regions": list(_REGIONS.keys()),
                    },
                ),
                request_id=request_id,
            ).model_dump(),
        )
    return region
