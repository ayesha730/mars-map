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

import uuid
from typing import Dict, List

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import JSONResponse

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
    "jezero_crater": [],  # Populated when HiRISE/CTX DEM is integrated
    "gale_crater": [],    # Populated when HiRISE/CTX DEM is integrated
}

# ---------------------------------------------------------------------------
# Layer metadata registry
# ---------------------------------------------------------------------------
# Keyed by layer_id → LayerMetadata.
# ---------------------------------------------------------------------------

_LAYER_METADATA: Dict[str, LayerMetadata] = {}

# ---------------------------------------------------------------------------
# Known regions (mirrors routes.REGION_REGISTRY keys)
# ---------------------------------------------------------------------------

_KNOWN_REGIONS = frozenset(["jezero_crater", "gale_crater"])

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

    if region_id not in _KNOWN_REGIONS:
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

    layers = _LAYER_CATALOGUE.get(region_id, [])
    verified_count = sum(1 for lyr in layers if lyr.is_verified)
    verified_available = verified_count > 0

    return LayerCatalogueResponse(
        region_id=region_id,
        verified_layers_available=verified_available,
        total_count=len(layers),
        layers=layers,
        notice=None if verified_available else _UNAVAILABLE_NOTICE,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/layers/{layer_id}/metadata
# ---------------------------------------------------------------------------

@router.get(
    "/layers/{layer_id}/metadata",
    response_model=LayerMetadata,
    summary="Get full coordinate-frame metadata for a specific layer",
    description=(
        "Returns the full metadata record for a layer, including:\n"
        "- Coordinate frame (arespath_display_v1)\n"
        "- Source CRS (Mars, planetocentric, positive-east, −180..180°)\n"
        "- Projection definition (null until dataset integrated)\n"
        "- Region-specific display-frame origin (null until dataset integrated)\n"
        "- Transformation method and parameters (null until dataset integrated)\n"
        "- Dataset provenance\n\n"
        "**Scientific integrity**: Numeric fields are null, not invented, "
        "when the underlying dataset has not yet been integrated."
    ),
    responses={
        200: {"model": LayerMetadata, "description": "Layer metadata"},
        404: {"model": ErrorResponse, "description": "Layer not found"},
    },
    tags=["Layers"],
)
async def get_layer_metadata(layer_id: str, http_request: Request):
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
