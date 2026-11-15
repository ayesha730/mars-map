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
            projection_name="Equirectangular",
            proj4_string=(
                "+proj=eqc +lat_ts=18.4663 +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 "
                "+R=3396190 +units=m +no_defs"
            ),
            wkt2_string=(
                'PROJCS["Jezero_Crater_Projection",GEOGCS["GCS_Mars_2000_Sphere",'
                'DATUM["Mars_2000_(Sphere)",SPHEROID["Mars_2000_Sphere",3396190,0]],'
                'PRIMEM["Reference_Meridian",0],UNIT["degree",0.0174532925199433]],'
                'PROJECTION["Equirectangular"],PARAMETER["standard_parallel_1",18.4663],'
                'PARAMETER["central_meridian",0],PARAMETER["false_easting",0],'
                'PARAMETER["false_northing",0],UNIT["metre",1]]'
            ),
            datum="IAU:2015:49900",
            semi_major_axis_m=3396190.0,
            inverse_flattening=0.0,
        ),
        display_origin=DisplayOrigin(
            description="Center of Jezero Crater CTX mosaic (18.4354°N, 77.7900°E)",
            latitude_deg=18.4354,
            longitude_deg=77.7900,
            source="USGS Mars 2020 CTX DEM mosaic (DOI: 10.5066/P906QQT8)",
        ),
        transformation=TransformationParameters(
            method="Mars 2000 Sphere Equirectangular (standard parallel 18.4663°N, R=3,396,190m)",
            parameters={
                "standard_parallel_1": 18.4663,
                "central_meridian": 0.0,
                "semi_major_axis_m": 3396190.0,
                "false_easting": 0.0,
                "false_northing": 0.0,
            },
            notes=(
                "Direct equirectangular transformation from Mars planetocentric "
                "lat/lon to arespath_display_v1 projected metres."
            ),
        ),
        datasets=[
            DatasetProvenance(
                name="Mars 2020 Terrain Relative Navigation CTX DTM Mosaic",
                agency="USGS Astrogeology / NASA JPL",
                instrument="Context Camera (CTX)",
                mission="Mars Reconnaissance Orbiter (MRO) / Mars 2020",
                resolution_m_per_px=20.0,
                coverage="Jezero Crater regional basin: Lat [17.5805°N, 19.2902°N], Lon [76.9974°E, 78.5826°E]",
                reference_url="https://astrogeology.usgs.gov/search/map/mars_2020_science_investigation_ctx_dem_mosaic",
                is_synthetic=False,
                synthetic_description=None,
            ),
            DatasetProvenance(
                name="Mars 2020 Terrain Relative Navigation Context Camera (CTX) Orthorectified Image Mosaic",
                agency="USGS Astrogeology / NASA JPL",
                instrument="Context Camera (CTX)",
                mission="Mars Reconnaissance Orbiter (MRO) / Mars 2020",
                resolution_m_per_px=6.0,
                coverage="Jezero Crater Perseverance landing area: Lat [18.2110°N, 18.7212°N], Lon [77.1605°E, 77.6992°E]",
                reference_url="https://astrogeology.usgs.gov/search/map/mars-2020-terrain-relative-navigation-context-camera-orthorectified-image-mosaic",
                is_synthetic=False,
                synthetic_description=None,
            ),
        ],
        routing_available=True,
        routing_unavailable_reason=None,
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


def _sync_region(region: RegionMetadata, http_request: Optional[Request]) -> RegionMetadata:
    """
    Synchronizes region routing_available status with the live application DEM state.
    """
    if http_request is not None and hasattr(http_request.app, "state") and hasattr(http_request.app.state, "regional_dems"):
        dems = getattr(http_request.app.state, "regional_dems", {})
        entry = dems.get(region.region_id)
        is_active = bool(entry is not None and entry.transformer is not None and not entry.transformer.is_closed)
        if is_active != region.routing_available:
            return region.model_copy(update={
                "routing_available": is_active,
                "routing_unavailable_reason": None if is_active else "ROUTING_DATA_UNAVAILABLE",
            })
    return region


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/regions",
    response_model=List[RegionMetadata],
    summary="List all supported Mars surface regions with full metadata",
    tags=["Regions"],
)
async def list_regions(http_request: Request = None):
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
    return [_sync_region(r, http_request) for r in _REGIONS.values()]


@router.get(
    "/regions/{region_id}",
    response_model=RegionMetadata,
    summary="Get metadata for a specific Mars surface region",
    responses={
        404: {"model": ErrorResponse, "description": "Region not found"},
    },
    tags=["Regions"],
)
async def get_region(region_id: str, http_request: Request = None):
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
    return _sync_region(region, http_request)
