"""
GET /api/v1/layers?region_id={id}
GET /api/v1/layers/{layer_id}/metadata

Terrain / map layer catalogue and metadata endpoints.

SCIENTIFIC INTEGRITY CONTRACT
------------------------------
No verified Mars terrain datasets (HiRISE, CTX DEM, HRSC, MOLA, etc.) are
bundled with the current codebase.  Rather than fabricating NASA product IDs,
resolution figures, or coverage strings, this implementation:

  1. Returns a valid, empty LayerCatalogueResponse with
     verified_layers_available=False and an explicit notice.
  2. Documents what real datasets would populate each field.
  3. Keeps all numeric projection / transformation parameters null.

When a real dataset is integrated:
  - Add a LayerCatalogueEntry to _LAYER_CATALOGUE with is_verified=True.
  - Add a LayerMetadata record to _LAYER_METADATA with the PDS-sourced
    proj4_string, origin, and transformation parameters filled in.
  - Set verified_layers_available=True in the catalogue response builder.

COORDINATE METADATA CONSISTENCY
---------------------------------
Every layer's LayerCoordinateFrame carries the same arespath_display_v1
convention as the parent region's RegionMetadata, with:
  - X = East, metres
  - Y = North, metres
  - Projection definition (null until dataset integrated)
  - Region-specific origin (null until dataset integrated)
  - Transformation method and parameters (null until dataset integrated)
  - Source CRS (MarsCoordinateReference — always populated)
"""

from __future__ import annotations

import io
import math
import uuid
from typing import Dict, List, Optional

import numpy as np
from PIL import Image
import rasterio
from rasterio.enums import Resampling
from rasterio.windows import bounds as window_bounds, from_bounds
from fastapi import APIRouter, Query, Request, Response, status
from fastapi.responses import JSONResponse

from app.core.config import JEZERO_ORTHO_PATH, JEZERO_DEM_PATH, MARS_IAU2015_SPHERE_RADIUS_M
from app.models.schemas import (
    ErrorDetail,
    ErrorResponse,
    LayerCatalogueEntry,
    LayerCatalogueResponse,
    LayerCoordinateFrame,
    LayerMetadata,
    LayerType,
    DatasetProvenance,
    MarsCoordinateReference,
)

router = APIRouter()

# ---------------------------------------------------------------------------
# Local raster dataset mappings
# ---------------------------------------------------------------------------
_LAYER_RASTER_PATHS = {
    "jezero_ctx_orthomosaic_6m": JEZERO_ORTHO_PATH,
    "jezero_ctx_dem_20m": JEZERO_DEM_PATH,
}


# ---------------------------------------------------------------------------
# Layer catalogue registry
# ---------------------------------------------------------------------------
# Keyed by region_id → list of LayerCatalogueEntry.
#
# Currently empty for all regions: no verified terrain datasets are
# available.  Add entries here when a dataset is integrated.
#
# DO NOT add synthetic entries to this registry — the endpoint communicates
# the absence of verified data via verified_layers_available=False and the
# notice field, not via fabricated layer records.
# ---------------------------------------------------------------------------

_LAYER_CATALOGUE: Dict[str, List[LayerCatalogueEntry]] = {
    "jezero_crater": [
        LayerCatalogueEntry(
            layer_id="jezero_ctx_dem_20m",
            region_id="jezero_crater",
            layer_type=LayerType.DEM,
            display_name="Jezero Crater CTX DEM (20m)",
            description=(
                "Digital elevation model derived from stereo CTX pairs for Jezero Crater "
                "(USGS/JPL TRN product, DOI: 10.5066/P906QQT8). Elevation ground truth "
                "for AresPath A* terrain routing."
            ),
            is_verified=True,
            is_synthetic=False,
            resolution_m_per_px=20.0,
            coverage="Lat 17.5805°N to 19.2902°N, Lon 76.9974°E to 78.5826°E",
            data_source="DOI: 10.5066/P906QQT8 (USGS Astrogeology / NASA JPL)",
            reference_url="https://astrogeology.usgs.gov/search/map/mars_2020_science_investigation_ctx_dem_mosaic",
        ),
        LayerCatalogueEntry(
            layer_id="jezero_ctx_orthomosaic_6m",
            region_id="jezero_crater",
            layer_type=LayerType.ORTHOIMAGE,
            display_name="Jezero Crater CTX Orthorectified Image Mosaic (6m)",
            description=(
                "MRO Context Camera orthorectified optical mosaic (USGS/JPL TRN product, "
                "DOI: 10.5066/P9GV1ND3). Visual context layer for rover landing site navigation."
            ),
            is_verified=True,
            is_synthetic=False,
            resolution_m_per_px=6.0,
            coverage="Lat 18.2110°N to 18.7212°N, Lon 77.1605°E to 77.6992°E",
            data_source="DOI: 10.5066/P9GV1ND3 (USGS Astrogeology / NASA JPL)",
            reference_url="https://astrogeology.usgs.gov/search/map/mars-2020-terrain-relative-navigation-context-camera-orthorectified-image-mosaic",
        ),
    ],
    "gale_crater": [],
}

# ---------------------------------------------------------------------------
# Layer metadata registry
# ---------------------------------------------------------------------------
# Keyed by layer_id → LayerMetadata.
# ---------------------------------------------------------------------------

_LAYER_METADATA: Dict[str, LayerMetadata] = {
    "jezero_ctx_dem_20m": LayerMetadata(
        layer_id="jezero_ctx_dem_20m",
        region_id="jezero_crater",
        layer_type=LayerType.DEM,
        display_name="Jezero Crater CTX DEM (20m)",
        description=(
            "Digital elevation model derived from stereo CTX pairs for Jezero Crater "
            "(USGS/JPL TRN product, DOI: 10.5066/P906QQT8). Elevation ground truth "
            "for AresPath A* terrain routing."
        ),
        is_verified=True,
        is_synthetic=False,
        dataset_provenance=DatasetProvenance(
            name="Mars 2020 Terrain Relative Navigation CTX DTM Mosaic",
            agency="USGS Astrogeology / NASA JPL",
            instrument="Context Camera (CTX)",
            mission="Mars Reconnaissance Orbiter (MRO) / Mars 2020",
            resolution_m_per_px=20.0,
            coverage="Jezero Crater regional basin: Lat [17.5805°N, 19.2902°N], Lon [76.9974°E, 78.5826°E]",
            reference_url="https://astrogeology.usgs.gov/search/map/mars_2020_science_investigation_ctx_dem_mosaic",
            is_synthetic=False,
        ),
        coordinate_frame=LayerCoordinateFrame(
            coordinate_space="arespath_display_v1",
            source_crs=MarsCoordinateReference(),
            x_axis="East, metres",
            y_axis="North, metres",
            projection_name="Equirectangular",
            proj4_string="+proj=eqc +lat_ts=18.4663 +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +R=3396190 +units=m +no_defs",
            datum="IAU:2015:49900",
            semi_major_axis_m=3396190.0,
            origin_latitude_deg=18.4354,
            origin_longitude_deg=77.7900,
            transformation_method="Mars 2000 Sphere Equirectangular (standard parallel 18.4663°N, R=3,396,190m)",
            transformation_parameters={
                "standard_parallel_1": 18.4663,
                "central_meridian": 0.0,
                "semi_major_axis_m": 3396190.0,
                "false_easting": 0.0,
                "false_northing": 0.0,
            },
        ),
        availability_note="Verified GeoTIFF dataset loaded in AresPath DEM service.",
    ),
    "jezero_ctx_orthomosaic_6m": LayerMetadata(
        layer_id="jezero_ctx_orthomosaic_6m",
        region_id="jezero_crater",
        layer_type=LayerType.ORTHOIMAGE,
        display_name="Jezero Crater CTX Orthorectified Image Mosaic (6m)",
        description=(
            "MRO Context Camera orthorectified optical mosaic (USGS/JPL TRN product, "
            "DOI: 10.5066/P9GV1ND3). Visual context layer for rover landing site navigation."
        ),
        is_verified=True,
        is_synthetic=False,
        dataset_provenance=DatasetProvenance(
            name="Mars 2020 Terrain Relative Navigation Context Camera (CTX) Orthorectified Image Mosaic",
            agency="USGS Astrogeology / NASA JPL",
            instrument="Context Camera (CTX)",
            mission="Mars Reconnaissance Orbiter (MRO) / Mars 2020",
            resolution_m_per_px=6.0,
            coverage="Jezero Crater Perseverance landing area: Lat [18.2110°N, 18.7212°N], Lon [77.1605°E, 77.6992°E]",
            reference_url="https://astrogeology.usgs.gov/search/map/mars-2020-terrain-relative-navigation-context-camera-orthorectified-image-mosaic",
            is_synthetic=False,
        ),
        coordinate_frame=LayerCoordinateFrame(
            coordinate_space="arespath_display_v1",
            source_crs=MarsCoordinateReference(),
            x_axis="East, metres",
            y_axis="North, metres",
            projection_name="Equirectangular",
            proj4_string="+proj=eqc +lat_ts=0 +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +R=3396190 +units=m +no_defs",
            datum="IAU:2015:49900",
            semi_major_axis_m=3396190.0,
            origin_latitude_deg=18.4661,
            origin_longitude_deg=77.4299,
            transformation_method="Mars 2000 Sphere Equirectangular (standard parallel 0°N, R=3,396,190m)",
            transformation_parameters={
                "standard_parallel_1": 0.0,
                "central_meridian": 0.0,
                "semi_major_axis_m": 3396190.0,
                "false_easting": 0.0,
                "false_northing": 0.0,
            },
        ),
        availability_note="Verified optical context imagery available for Mars 2020 landing ellipse.",
    ),
}

# ---------------------------------------------------------------------------
# Known regions (mirrors routes.REGION_REGISTRY keys)
# ---------------------------------------------------------------------------

_KNOWN_REGIONS = frozenset(["jezero_crater", "gale_crater"])
_REGION_ALIASES = {
    "jezero": "jezero_crater",
    "jezero_crater": "jezero_crater",
    "gale": "gale_crater",
    "gale_crater": "gale_crater",
}

# ---------------------------------------------------------------------------
# Shared notice text
# ---------------------------------------------------------------------------

_UNAVAILABLE_NOTICE = (
    "No verified terrain layers are currently registered for this region. "
    "Layers will appear here once a verified Mars surface dataset "
    "(e.g. MRO HiRISE or CTX DEM from NASA PDS Geosciences Node) has been "
    "integrated and validated. "
    "Do not use this response to infer that the region has no terrain data — "
    "it means only that AresPath has not yet ingested a dataset for it."
)


# ---------------------------------------------------------------------------
# GET /api/v1/layers
# ---------------------------------------------------------------------------

@router.get(
    "/layers",
    response_model=LayerCatalogueResponse,
    summary="List terrain / map layers available for a region",
    description=(
        "Returns the layer catalogue for the specified region.\n\n"
        "**Scientific integrity**: When no verified terrain datasets have been "
        "integrated, returns a valid empty catalogue with "
        "`verified_layers_available=false` and an explicit `notice`. "
        "Never fabricates NASA product IDs, resolution, or coverage data.\n\n"
        "**Coordinate consistency**: Every layer embeds the same "
        "`arespath_display_v1` coordinate frame as the parent region, "
        "ensuring X=East, Y=North (metres) throughout."
    ),
    responses={
        200: {
            "model": LayerCatalogueResponse,
            "description": "Layer catalogue (may be empty if no verified data)",
        },
        404: {"model": ErrorResponse, "description": "Region not found"},
        422: {"model": ErrorResponse, "description": "Missing or invalid query parameter"},
    },
    tags=["Layers"],
)
async def list_layers(
    region_id: str = Query(..., description="Region identifier (e.g. 'jezero_crater')"),
    http_request: Request = None,
):
    """
    Returns the layer catalogue for the given region.

    When no verified terrain layers exist the response is a valid empty
    catalogue — `verified_layers_available` is `false` and `layers` is `[]`.
    The `notice` field explains the absence without fabricating data.
    """
    request_id = str(uuid.uuid4())

    norm_region_id = _REGION_ALIASES.get(region_id, region_id)
    if norm_region_id not in _KNOWN_REGIONS:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=ErrorResponse(
                error=ErrorDetail(
                    code="REGION_NOT_FOUND",
                    message=f"Region '{region_id}' is not recognised.",
                    details={
                        "region_id": region_id,
                        "supported_regions": sorted(_KNOWN_REGIONS),
                    },
                ),
                request_id=request_id,
            ).model_dump(),
        )

    layers = _LAYER_CATALOGUE.get(norm_region_id, [])
    verified_count = sum(1 for lyr in layers if lyr.is_verified)
    verified_available = verified_count > 0

    return LayerCatalogueResponse(
        region_id=norm_region_id,
        verified_layers_available=verified_available,
        total_count=len(layers),
        layers=layers,
        notice=None if verified_available else _UNAVAILABLE_NOTICE,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/layers/{layer_id} & GET /api/v1/layers/{layer_id}/metadata
# ---------------------------------------------------------------------------

@router.get(
    "/layers/{layer_id}",
    response_model=LayerMetadata,
    summary="Get full coordinate-frame metadata for a specific layer",
    description="Returns the full metadata record for a layer.",
    responses={
        200: {"model": LayerMetadata, "description": "Layer metadata"},
        404: {"model": ErrorResponse, "description": "Layer not found"},
    },
    tags=["Layers"],
)
@router.get(
    "/layers/{layer_id}/metadata",
    response_model=LayerMetadata,
    summary="Get full coordinate-frame metadata for a specific layer",
    description=(
        "Returns the full metadata record for a layer, including:\n"
        "- Coordinate frame (arespath_display_v1)\n"
        "- Source CRS (Mars, planetocentric, positive-east, −180..180°)\n"
        "- Projection definition\n"
        "- Region-specific display-frame origin\n"
        "- Transformation method and parameters\n"
        "- Dataset provenance\n"
    ),
    responses={
        200: {"model": LayerMetadata, "description": "Layer metadata"},
        404: {"model": ErrorResponse, "description": "Layer not found"},
    },
    tags=["Layers"],
)
async def get_layer_metadata(layer_id: str, http_request: Request = None):
    """
    Returns full coordinate-frame and provenance metadata for one layer.
    """
    request_id = str(uuid.uuid4())

    layer = _LAYER_METADATA.get(layer_id)
    if layer is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=ErrorResponse(
                error=ErrorDetail(
                    code="LAYER_NOT_FOUND",
                    message=f"Layer '{layer_id}' is not registered.",
                    details={
                        "layer_id": layer_id,
                        "registered_layers": list(_LAYER_METADATA.keys()),
                    },
                ),
                request_id=request_id,
            ).model_dump(),
        )

    return layer


# ---------------------------------------------------------------------------
# GET /api/v1/layers/{layer_id}/render & GET /api/v1/layers/{layer_id}/preview
# ---------------------------------------------------------------------------

@router.get(
    "/layers/{layer_id}/render",
    summary="Render a windowed PNG preview of a map layer",
    responses={
        200: {
            "content": {"image/png": {}},
            "description": "Rendered PNG image with spatial bounds headers",
        },
        404: {"model": ErrorResponse, "description": "Layer not found"},
        422: {"model": ErrorResponse, "description": "Invalid parameters, empty window, or out-of-coverage bounds"},
        503: {"model": ErrorResponse, "description": "Raster file missing or unavailable"},
    },
    tags=["Layers"],
)
@router.get(
    "/layers/{layer_id}/preview",
    summary="Render a windowed PNG preview of a map layer",
    responses={
        200: {
            "content": {"image/png": {}},
            "description": "Rendered PNG image with spatial bounds headers",
        },
        404: {"model": ErrorResponse, "description": "Layer not found"},
        422: {"model": ErrorResponse, "description": "Invalid parameters, empty window, or out-of-coverage bounds"},
        503: {"model": ErrorResponse, "description": "Raster file missing or unavailable"},
    },
    tags=["Layers"],
)
async def render_layer_preview(
    layer_id: str,
    min_lon: float = Query(..., description="Minimum longitude in planetocentric degrees [-180, 180]"),
    min_lat: float = Query(..., description="Minimum latitude in planetocentric degrees [-90, 90]"),
    max_lon: float = Query(..., description="Maximum longitude in planetocentric degrees [-180, 180]"),
    max_lat: float = Query(..., description="Maximum latitude in planetocentric degrees [-90, 90]"),
    max_dimension: int = Query(1024, ge=16, le=2048, description="Maximum width or height of output PNG (default 1024, max 2048)"),
    http_request: Request = None,
):
    """
    Renders a memory-efficient windowed PNG preview of an orthorectified image layer.

    **Coordinate Contract**:
    - Query bounding box is in canonical Martian planetocentric degrees:
      positive-east longitude in [-180.0, 180.0], latitude in [-90.0, 90.0].
    - Requested coordinates are transformed into the layer's native source CRS
      (Equirectangular standard parallel 0.0° for ESRI:103885) before windowed read.

    **NoData and Transparency**:
    - Value 0 (NoData / unexposed collar) is rendered fully transparent (Alpha = 0).
    - Valid optical imagery pixels (DN in [1, 255]) are rendered fully opaque (Alpha = 255).

    **Memory Safety Guarantee**:
    - Reads only the requested sub-grid window; never loads full rasters into memory.
    - Output dimensions are capped to `max_dimension` (default 1024, max 2048).
    """
    request_id = str(uuid.uuid4())

    # 1. Layer existence check
    layer = _LAYER_METADATA.get(layer_id)
    if layer is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=ErrorResponse(
                error=ErrorDetail(
                    code="LAYER_NOT_FOUND",
                    message=f"Layer '{layer_id}' is not registered.",
                    details={"layer_id": layer_id, "registered_layers": list(_LAYER_METADATA.keys())},
                ),
                request_id=request_id,
            ).model_dump(),
        )

    # 2. Layer type check — only orthoimage layers support optical preview
    if layer.layer_type != LayerType.ORTHOIMAGE:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=ErrorResponse(
                error=ErrorDetail(
                    code="UNSUPPORTED_LAYER_OPERATION",
                    message=(
                        f"Layer '{layer_id}' has layer_type '{layer.layer_type.value}'. "
                        "Raster preview rendering is supported only for optical orthoimage layers. "
                        "Elevation DEM layers must not be interpreted as imagery."
                    ),
                    details={"layer_id": layer_id, "layer_type": layer.layer_type.value},
                ),
                request_id=request_id,
            ).model_dump(),
        )

    # 3. Coordinate domain checks
    if not (-180.0 <= min_lon <= 180.0 and -180.0 <= max_lon <= 180.0):
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=ErrorResponse(
                error=ErrorDetail(
                    code="COORDINATE_OUT_OF_BOUNDS",
                    message="Longitude must lie within planetocentric positive-east [-180.0, 180.0] degrees.",
                    details={"min_lon": min_lon, "max_lon": max_lon},
                ),
                request_id=request_id,
            ).model_dump(),
        )

    if not (-90.0 <= min_lat <= 90.0 and -90.0 <= max_lat <= 90.0):
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=ErrorResponse(
                error=ErrorDetail(
                    code="COORDINATE_OUT_OF_BOUNDS",
                    message="Latitude must lie within planetocentric [-90.0, 90.0] degrees.",
                    details={"min_lat": min_lat, "max_lat": max_lat},
                ),
                request_id=request_id,
            ).model_dump(),
        )

    # 4. Bounding box ordering checks
    if min_lon >= max_lon:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=ErrorResponse(
                error=ErrorDetail(
                    code="VALIDATION_ERROR",
                    message=f"min_lon ({min_lon}) must be strictly less than max_lon ({max_lon}).",
                    details={"min_lon": min_lon, "max_lon": max_lon},
                ),
                request_id=request_id,
            ).model_dump(),
        )

    if min_lat >= max_lat:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=ErrorResponse(
                error=ErrorDetail(
                    code="VALIDATION_ERROR",
                    message=f"min_lat ({min_lat}) must be strictly less than max_lat ({max_lat}).",
                    details={"min_lat": min_lat, "max_lat": max_lat},
                ),
                request_id=request_id,
            ).model_dump(),
        )

    # 5. Raster dataset file presence check
    raster_path = _LAYER_RASTER_PATHS.get(layer_id)
    if raster_path is None or not raster_path.exists():
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=ErrorResponse(
                error=ErrorDetail(
                    code="RASTER_FILE_NOT_FOUND",
                    message=f"Underlying raster file for layer '{layer_id}' is not available on disk.",
                    details={"layer_id": layer_id, "path": str(raster_path)},
                ),
                request_id=request_id,
            ).model_dump(),
        )

    # 6. Transform requested geographic bounds to layer source CRS (Equirectangular standard parallel 0.0°)
    R = MARS_IAU2015_SPHERE_RADIUS_M
    x_min = math.radians(min_lon) * R
    x_max = math.radians(max_lon) * R
    y_min = math.radians(min_lat) * R
    y_max = math.radians(max_lat) * R

    try:
        with rasterio.open(raster_path) as src:
            raster_box = src.bounds

            # Check if requested projected bbox overlaps raster bounds at all
            if x_max <= raster_box.left or x_min >= raster_box.right or y_max <= raster_box.bottom or y_min >= raster_box.top:
                cov_lon_min = math.degrees(raster_box.left / R)
                cov_lon_max = math.degrees(raster_box.right / R)
                cov_lat_min = math.degrees(raster_box.bottom / R)
                cov_lat_max = math.degrees(raster_box.top / R)
                return JSONResponse(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    content=ErrorResponse(
                        error=ErrorDetail(
                            code="BOUNDS_OUT_OF_COVERAGE",
                            message=(
                                f"Requested bounding box [{min_lon:.4f}°E, {min_lat:.4f}°N, {max_lon:.4f}°E, {max_lat:.4f}°N] "
                                f"does not intersect the raster coverage of layer '{layer_id}'."
                            ),
                            details={
                                "layer_id": layer_id,
                                "layer_coverage_lon": [round(cov_lon_min, 4), round(cov_lon_max, 4)],
                                "layer_coverage_lat": [round(cov_lat_min, 4), round(cov_lat_max, 4)],
                            },
                        ),
                        request_id=request_id,
                    ).model_dump(),
                )

            # Window extraction
            win = from_bounds(x_min, y_min, x_max, y_max, src.transform)
            round_win = win.round_offsets().round_lengths()

            if round_win.width <= 0 or round_win.height <= 0:
                return JSONResponse(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    content=ErrorResponse(
                        error=ErrorDetail(
                            code="EMPTY_RASTER_WINDOW",
                            message="Requested geographic bounding box resolves to an empty pixel window.",
                            details={"window": str(round_win)},
                        ),
                        request_id=request_id,
                    ).model_dump(),
                )

            # Compute actual pixel footprint in projected and geographic coordinates
            actual_left, actual_bottom, actual_right, actual_top = window_bounds(round_win, src.transform)
            actual_min_lon = math.degrees(actual_left / R)
            actual_max_lon = math.degrees(actual_right / R)
            actual_min_lat = math.degrees(actual_bottom / R)
            actual_max_lat = math.degrees(actual_top / R)

            # Calculate target output dimensions BEFORE allocating arrays (Memory Decimation)
            orig_w = int(round_win.width)
            orig_h = int(round_win.height)
            if max_dimension and (orig_w > max_dimension or orig_h > max_dimension):
                scale = min(max_dimension / orig_w, max_dimension / orig_h)
                target_w = max(1, int(round(orig_w * scale)))
                target_h = max(1, int(round(orig_h * scale)))
            else:
                target_w = orig_w
                target_h = orig_h

            # Decimated windowed read directly into target shape
            # Bilinear resampling for continuous optical pixels
            arr = src.read(
                1,
                window=round_win,
                out_shape=(target_h, target_w),
                resampling=Resampling.bilinear,
                boundless=True,
                fill_value=0,
            )

            # Nearest-neighbor resampling for mask to prevent dark halos and false collars
            mask = src.read_masks(
                1,
                window=round_win,
                out_shape=(target_h, target_w),
                resampling=Resampling.nearest,
                boundless=True,
            )

    except Exception as exc:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=ErrorResponse(
                error=ErrorDetail(
                    code="RASTER_READ_ERROR",
                    message=f"Failed to read raster window: {exc}",
                    details={"layer_id": layer_id},
                ),
                request_id=request_id,
            ).model_dump(),
        )

    # 7. RGBA Image Construction directly at target size
    # Value 0 is transparent collar/boundless, 255 is valid imagery
    rgba = np.zeros((target_h, target_w, 4), dtype=np.uint8)
    rgba[..., 0] = np.where(mask == 0, 0, arr)
    rgba[..., 1] = np.where(mask == 0, 0, arr)
    rgba[..., 2] = np.where(mask == 0, 0, arr)
    rgba[..., 3] = mask

    img = Image.fromarray(rgba, mode="RGBA")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    png_bytes = buf.getvalue()

    headers = {
        "Content-Type": "image/png",
        "X-Spatial-Layer-Id": layer_id,
        "X-Spatial-CRS": "ESRI:103885",
        "X-Spatial-Min-Lon": f"{min_lon:.6f}",
        "X-Spatial-Min-Lat": f"{min_lat:.6f}",
        "X-Spatial-Max-Lon": f"{max_lon:.6f}",
        "X-Spatial-Max-Lat": f"{max_lat:.6f}",
        "X-Spatial-Actual-Min-Lon": f"{actual_min_lon:.6f}",
        "X-Spatial-Actual-Min-Lat": f"{actual_min_lat:.6f}",
        "X-Spatial-Actual-Max-Lon": f"{actual_max_lon:.6f}",
        "X-Spatial-Actual-Max-Lat": f"{actual_max_lat:.6f}",
        "X-Spatial-Image-Width": str(img.width),
        "X-Spatial-Image-Height": str(img.height),
        "X-Spatial-NoData-Alpha": "0",
        "Cache-Control": "public, max-age=3600",
    }

    return Response(content=png_bytes, media_type="image/png", headers=headers)
