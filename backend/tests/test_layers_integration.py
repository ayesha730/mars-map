"""
Integration and scientific validation tests for Increment 4:
NASA Jezero Multi-Layer Map Backend.

Covers:
  - Layer registry initialization
  - Missing dataset handling
  - Layer metadata endpoints (/api/v1/layers/{id} and /api/v1/layers/{id}/metadata)
  - Coverage intersection between DEM and orthomosaic
  - CRS compatibility and transformation contract
  - NoData handling for elevation and imagery
  - Layer API responses and aliases
  - Resource cleanup and lifecycle safety
  - Route API regression verification
"""

import math
import pytest
import rasterio
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.core.config import JEZERO_DEM_PATH, JEZERO_ORTHO_PATH, MARS_IAU2015_SPHERE_RADIUS_M
from app.scientific.dem.transformer import DEMTransformer

BASE = "http://test"


# ---------------------------------------------------------------------------
# 1. Layer Registry Initialization
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_layer_registry_initialization():
    """Verify both verified Jezero layers are registered with valid metadata."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as ac:
        r = await ac.get("/api/v1/layers", params={"region_id": "jezero_crater"})
    assert r.status_code == 200
    data = r.json()
    assert data["verified_layers_available"] is True
    assert data["total_count"] == 2
    layer_ids = [l["layer_id"] for l in data["layers"]]
    assert "jezero_ctx_dem_20m" in layer_ids
    assert "jezero_ctx_orthomosaic_6m" in layer_ids

    for layer in data["layers"]:
        assert layer["is_verified"] is True
        assert layer["is_synthetic"] is False
        assert layer["resolution_m_per_px"] in (20.0, 6.0)
        assert layer["data_source"] is not None


# ---------------------------------------------------------------------------
# 2. Missing Dataset & Region Handling
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_missing_region_returns_404():
    """Requesting layers for an unregistered region returns 404 with error envelope."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as ac:
        r = await ac.get("/api/v1/layers", params={"region_id": "olympus_mons"})
    assert r.status_code == 404
    data = r.json()
    assert data["status"] == "error"
    assert data["error"]["code"] == "REGION_NOT_FOUND"
    assert "request_id" in data


@pytest.mark.asyncio
async def test_missing_layer_metadata_returns_404():
    """Requesting metadata for an unregistered layer ID returns 404."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as ac:
        r = await ac.get("/api/v1/layers/nonexistent_layer/metadata")
    assert r.status_code == 404
    data = r.json()
    assert data["status"] == "error"
    assert data["error"]["code"] == "LAYER_NOT_FOUND"


# ---------------------------------------------------------------------------
# 3. Layer Metadata Endpoints
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dem_layer_metadata_contract():
    """Verify full metadata contract for the 20m CTX DEM layer."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as ac:
        r = await ac.get("/api/v1/layers/jezero_ctx_dem_20m/metadata")
    assert r.status_code == 200
    meta = r.json()
    assert meta["layer_id"] == "jezero_ctx_dem_20m"
    assert meta["layer_type"] == "dem"
    assert meta["is_verified"] is True
    assert meta["dataset_provenance"]["resolution_m_per_px"] == 20.0
    assert "10.5066/P906QQT8" in meta["description"]
    # Coordinate frame
    cf = meta["coordinate_frame"]
    assert cf["datum"] == "IAU:2015:49900"
    assert cf["projection_name"] == "Equirectangular"
    assert "lat_ts=18.4663" in cf["proj4_string"]
    assert cf["transformation_parameters"]["standard_parallel_1"] == 18.4663


@pytest.mark.asyncio
async def test_orthomosaic_layer_metadata_contract():
    """Verify full metadata contract for the 6m CTX orthomosaic layer."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as ac:
        r = await ac.get("/api/v1/layers/jezero_ctx_orthomosaic_6m")
    assert r.status_code == 200
    meta = r.json()
    assert meta["layer_id"] == "jezero_ctx_orthomosaic_6m"
    assert meta["layer_type"] == "orthoimage"
    assert meta["is_verified"] is True
    assert meta["dataset_provenance"]["resolution_m_per_px"] == 6.0
    assert "10.5066/P9GV1ND3" in meta["description"]
    cf = meta["coordinate_frame"]
    assert cf["datum"] == "IAU:2015:49900"
    assert cf["projection_name"] == "Equirectangular"
    assert "lat_ts=0" in cf["proj4_string"]


# ---------------------------------------------------------------------------
# 4. Coverage Intersection
# ---------------------------------------------------------------------------

def test_dem_and_orthomosaic_coverage_intersection():
    """
    Verify that the geographic coverage of the CTX orthomosaic is
    strictly contained within the coverage of the regional Jezero DEM.
    """
    R = MARS_IAU2015_SPHERE_RADIUS_M

    with rasterio.open(JEZERO_DEM_PATH) as dem, rasterio.open(JEZERO_ORTHO_PATH) as ortho:
        # DEM: standard parallel 18.4663 deg
        cos_ts_dem = math.cos(math.radians(18.4663))
        dem_lon_min = math.degrees(dem.bounds.left / (R * cos_ts_dem))
        dem_lon_max = math.degrees(dem.bounds.right / (R * cos_ts_dem))
        dem_lat_min = math.degrees(dem.bounds.bottom / R)
        dem_lat_max = math.degrees(dem.bounds.top / R)

        # Ortho: standard parallel 0.0 deg
        ortho_lon_min = math.degrees(ortho.bounds.left / R)
        ortho_lon_max = math.degrees(ortho.bounds.right / R)
        ortho_lat_min = math.degrees(ortho.bounds.bottom / R)
        ortho_lat_max = math.degrees(ortho.bounds.top / R)

    # Assert orthomosaic is completely contained in the regional DEM footprint
    assert dem_lon_min < ortho_lon_min, f"{dem_lon_min} not < {ortho_lon_min}"
    assert dem_lon_max > ortho_lon_max, f"{dem_lon_max} not > {ortho_lon_max}"
    assert dem_lat_min < ortho_lat_min, f"{dem_lat_min} not < {ortho_lat_min}"
    assert dem_lat_max > ortho_lat_max, f"{dem_lat_max} not > {ortho_lat_max}"


# ---------------------------------------------------------------------------
# 5. CRS Compatibility & Transformation
# ---------------------------------------------------------------------------

def test_crs_and_datum_compatibility():
    """Both datasets must share the IAU 2015 Mars Sphere (R=3,396,190m)."""
    with rasterio.open(JEZERO_DEM_PATH) as dem, rasterio.open(JEZERO_ORTHO_PATH) as ortho:
        # Both define Mars 2000 Sphere with semi-major axis = 3,396,190m
        assert dem.crs is not None
        assert ortho.crs is not None
        assert "3396190" in dem.crs.to_wkt()
        assert "3396190" in ortho.crs.to_wkt()
        # DEM has standard parallel 18.4663
        assert "18.4663" in dem.crs.to_wkt()
        # Ortho has standard parallel 0
        assert "standard_parallel_1\",0" in ortho.crs.to_wkt() or "standard_parallel_1\", 0" in ortho.crs.to_wkt()


# ---------------------------------------------------------------------------
# 6. NoData Handling
# ---------------------------------------------------------------------------

def test_nodata_specifications():
    """Verify distinct, documented NoData values for elevation and imagery."""
    with rasterio.open(JEZERO_DEM_PATH) as dem:
        assert dem.nodata is not None
        assert math.isclose(dem.nodata, -3.4028234663852886e+38, rel_tol=1e-5)
        assert dem.dtypes[0] == "float32"

    with rasterio.open(JEZERO_ORTHO_PATH) as ortho:
        assert ortho.nodata == 0.0
        assert ortho.dtypes[0] == "uint8"


# ---------------------------------------------------------------------------
# 7. Layer API Responses & Aliases
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_layer_api_alias_equivalence():
    """Querying region_id='jezero' and 'jezero_crater' returns identical layers."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as ac:
        r1 = await ac.get("/api/v1/layers", params={"region_id": "jezero_crater"})
        r2 = await ac.get("/api/v1/layers", params={"region_id": "jezero"})
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["layers"] == r2.json()["layers"]


# ---------------------------------------------------------------------------
# 8. Resource Cleanup
# ---------------------------------------------------------------------------

def test_dem_transformer_resource_cleanup():
    """Verify that opening and closing transformer instances leaves no leaked handles."""
    tf = DEMTransformer.from_file(JEZERO_ORTHO_PATH)
    assert not tf.is_closed
    tf.close()
    assert tf.is_closed


# ---------------------------------------------------------------------------
# 9. Existing Route API Regression
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_route_api_zero_regression():
    """Verify that A* routing endpoint functions identically with multi-layer backend."""
    from app.main import lifespan
    body = {
        "region_id": "jezero_crater",
        "start": {"latitude": 18.450, "longitude": 77.450},
        "destination": {"latitude": 18.460, "longitude": 77.470},
        "coordinate_reference": {
            "body": "Mars",
            "latitude_type": "planetocentric",
            "longitude_direction": "positive_east",
            "longitude_domain": "-180_to_180",
            "angular_unit": "degrees",
        },
        "routing_profile": "demonstration",
    }
    async with lifespan(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as ac:
            r = await ac.post("/api/v1/routes", json=body)
    assert r.status_code == 200
    resp = r.json()
    assert resp["status"] == "success"
    assert resp["algorithm"] == "a_star"
    assert resp["distance_m"] > 0
    assert len(resp["route_geometry"]["points"]) > 1
    assert "x" in resp["route_geometry"]["points"][0]
    assert "y" in resp["route_geometry"]["points"][0]
    assert resp["terrain_summary"]["min_elevation_m"] is not None
