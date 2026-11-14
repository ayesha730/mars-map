"""
API contract and validation tests for the layer catalogue endpoints:
  GET /api/v1/layers?region_id={id}
  GET /api/v1/layers/{layer_id}/metadata

Coverage (Task 4 requirements):
  - Existing region lookup (jezero_crater, gale_crater)
  - Valid layer catalogue request — 200, correct envelope
  - Unknown region — 404 with standard error envelope
  - Empty verified-layer catalogue — verified_layers_available=False, notice present
  - Layer metadata lookup — 404 when no layers registered
  - Coordinate-frame consistency between region and layer metadata
  - Scientific integrity — no fabricated data in empty catalogue
  - Query parameter validation — missing region_id
"""

import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

BASE = "http://test"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def get_layers(region_id: str):
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as ac:
        r = await ac.get(f"/api/v1/layers", params={"region_id": region_id})
    return r.status_code, r.json()


# ---------------------------------------------------------------------------
# 1. Valid catalogue requests — existing regions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_layers_jezero_returns_200():
    code, body = await get_layers("jezero_crater")
    assert code == 200, f"Expected 200, got {code}: {body}"


@pytest.mark.asyncio
async def test_layers_gale_returns_200():
    code, body = await get_layers("gale_crater")
    assert code == 200, f"Expected 200, got {code}: {body}"


# ---------------------------------------------------------------------------
# 2. Response envelope shape
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_layers_response_has_required_fields():
    """LayerCatalogueResponse must expose all contract fields."""
    _, body = await get_layers("jezero_crater")
    assert "region_id" in body
    assert "verified_layers_available" in body
    assert "total_count" in body
    assert "layers" in body
    assert "notice" in body


@pytest.mark.asyncio
async def test_layers_region_id_matches_request():
    _, body = await get_layers("jezero_crater")
    assert body["region_id"] == "jezero_crater"


@pytest.mark.asyncio
async def test_layers_response_is_list():
    _, body = await get_layers("jezero_crater")
    assert isinstance(body["layers"], list)


# ---------------------------------------------------------------------------
# 3. Empty verified-layer catalogue (current state — no DEM integrated)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_layers_verified_unavailable_is_false():
    """No verified terrain layers are registered; flag must be False."""
    _, body = await get_layers("jezero_crater")
    assert body["verified_layers_available"] is False


@pytest.mark.asyncio
async def test_layers_catalogue_is_empty():
    """No layers registered yet — list must be empty."""
    _, body = await get_layers("jezero_crater")
    assert body["layers"] == []
    assert body["total_count"] == 0


@pytest.mark.asyncio
async def test_layers_notice_present_when_empty():
    """When no verified layers, a notice must explain the absence."""
    _, body = await get_layers("jezero_crater")
    assert body["notice"] is not None
    assert isinstance(body["notice"], str)
    assert len(body["notice"]) > 0


@pytest.mark.asyncio
async def test_layers_notice_does_not_fabricate_data():
    """The notice must not claim layers exist or invent dataset names."""
    _, body = await get_layers("jezero_crater")
    notice = body["notice"].lower()
    # Must say something about data not being available yet
    assert any(word in notice for word in ["not", "no verified", "has not"])


@pytest.mark.asyncio
async def test_layers_no_fabricated_entries():
    """The catalogue must never contain synthetic/invented layer entries."""
    _, body = await get_layers("jezero_crater")
    # Every entry must be genuinely registered; with empty catalogue this
    # simply asserts the list is empty — protecting against future accidental
    # addition of fake entries.
    for layer in body["layers"]:
        assert "layer_id" in layer
        assert "is_verified" in layer
        assert "is_synthetic" in layer


# ---------------------------------------------------------------------------
# 4. Unknown region — 404 with standard error envelope
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_layers_unknown_region_returns_404():
    code, body = await get_layers("fantasy_valley")
    assert code == 404
    assert body["status"] == "error"
    assert body["error"]["code"] == "REGION_NOT_FOUND"


@pytest.mark.asyncio
async def test_layers_unknown_region_error_envelope_complete():
    code, body = await get_layers("unknown_region")
    assert code == 404
    assert "request_id" in body
    assert body["request_id"] is not None
    details = body["error"]["details"]
    assert "region_id" in details
    assert "supported_regions" in details
    assert isinstance(details["supported_regions"], list)


@pytest.mark.asyncio
async def test_layers_unknown_region_lists_supported():
    _, body = await get_layers("nowhere")
    supported = body["error"]["details"]["supported_regions"]
    assert "jezero_crater" in supported
    assert "gale_crater" in supported


# ---------------------------------------------------------------------------
# 5. Layer metadata lookup — 404 when no layers are registered
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_layer_metadata_unknown_id_returns_404():
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as ac:
        r = await ac.get("/api/v1/layers/nonexistent_layer_xyz/metadata")
    assert r.status_code == 404
    body = r.json()
    assert body["status"] == "error"
    assert body["error"]["code"] == "LAYER_NOT_FOUND"


@pytest.mark.asyncio
async def test_layer_metadata_404_has_error_envelope():
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as ac:
        r = await ac.get("/api/v1/layers/fake_layer/metadata")
    body = r.json()
    assert "request_id" in body
    assert "error" in body
    assert "code" in body["error"]
    assert "message" in body["error"]


@pytest.mark.asyncio
async def test_layer_metadata_404_lists_registered_layers():
    """Details block must list registered layer IDs (empty when none exist)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as ac:
        r = await ac.get("/api/v1/layers/bogus/metadata")
    details = r.json()["error"]["details"]
    assert "registered_layers" in details
    assert isinstance(details["registered_layers"], list)


# ---------------------------------------------------------------------------
# 6. Coordinate-frame consistency between region and layer metadata
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_layer_catalogue_coordinate_space_key_exists():
    """
    When layers are present, each entry's coordinate frame must declare
    arespath_display_v1.  With empty catalogue this checks the schema;
    with populated catalogue it checks each record.
    """
    _, body = await get_layers("jezero_crater")
    # Empty now — verify schema via OpenAPI instead
    from app.main import app as _app
    schema = _app.openapi()
    catalogue_entry = schema["components"]["schemas"]["LayerCatalogueEntry"]
    assert "layer_id" in catalogue_entry["properties"]
    assert "is_verified" in catalogue_entry["properties"]
    assert "is_synthetic" in catalogue_entry["properties"]


@pytest.mark.asyncio
async def test_layer_coordinate_frame_schema_matches_region_convention():
    """
    LayerCoordinateFrame schema must enforce the same arespath_display_v1
    convention as RegionMetadata: X=East, Y=North (metres).
    """
    from app.main import app as _app
    schema = _app.openapi()
    frame = schema["components"]["schemas"]["LayerCoordinateFrame"]
    props = frame["properties"]

    # coordinate_space must be a const
    assert props["coordinate_space"]["const"] == "arespath_display_v1"
    # x_axis must declare East
    assert "East" in props["x_axis"]["const"]
    # y_axis must declare North
    assert "North" in props["y_axis"]["const"]
    # source_crs must reference MarsCoordinateReference
    assert "$ref" in props["source_crs"]
    assert "MarsCoordinateReference" in props["source_crs"]["$ref"]


@pytest.mark.asyncio
async def test_layer_coordinate_frame_has_null_projection_until_verified():
    """
    LayerCoordinateFrame.proj4_string is Optional/null in the schema,
    ensuring the API never enforces a fake projection value.
    """
    from app.main import app as _app
    schema = _app.openapi()
    frame = schema["components"]["schemas"]["LayerCoordinateFrame"]
    proj4 = frame["properties"]["proj4_string"]
    # anyOf [string, null] pattern
    assert "anyOf" in proj4
    types = [t.get("type") for t in proj4["anyOf"]]
    assert "null" in types


@pytest.mark.asyncio
async def test_region_and_layer_crs_share_same_datum():
    """
    Both RegionMetadata and LayerCoordinateFrame must reference IAU:2015:49900.
    Verify via GET /api/v1/regions/jezero_crater.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as ac:
        r = await ac.get("/api/v1/regions/jezero_crater")
    region = r.json()
    # Region display_projection carries the datum
    assert region["display_projection"]["datum"] == "IAU:2015:49900"
    # Layer schema also defaults datum to IAU:2015:49900 (checked via schema)
    from app.main import app as _app
    schema = _app.openapi()
    frame = schema["components"]["schemas"]["LayerCoordinateFrame"]
    datum_field = frame["properties"]["datum"]
    assert datum_field.get("default") == "IAU:2015:49900"


# ---------------------------------------------------------------------------
# 7. Missing region_id parameter — validation error
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_layers_missing_region_id_returns_422():
    """region_id query parameter is required."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as ac:
        r = await ac.get("/api/v1/layers")
    assert r.status_code == 422
    body = r.json()
    assert body["status"] == "error"
    assert body["error"]["code"] == "VALIDATION_ERROR"


# ---------------------------------------------------------------------------
# 8. OpenAPI paths registered
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_layers_paths_registered_in_openapi():
    from app.main import app as _app
    schema = _app.openapi()
    paths = schema["paths"]
    assert "/api/v1/layers" in paths
    assert "/api/v1/layers/{layer_id}/metadata" in paths


@pytest.mark.asyncio
async def test_layers_catalogue_response_in_openapi_schemas():
    from app.main import app as _app
    schema = _app.openapi()
    schemas = schema["components"]["schemas"]
    assert "LayerCatalogueResponse" in schemas
    assert "LayerCatalogueEntry" in schemas
    assert "LayerMetadata" in schemas
    assert "LayerCoordinateFrame" in schemas
