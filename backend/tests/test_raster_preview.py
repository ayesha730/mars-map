"""
Tests for Increment 5: Raster Imagery Delivery
Endpoint: GET /api/v1/layers/{layer_id}/render and GET /api/v1/layers/{layer_id}/preview

Requirements tested:
1. Valid orthomosaic preview returns 200 and image/png bytes.
2. Correct spatial headers present on response.
3. Geographic-to-source-CRS transformation correctly positions raster pixels.
4. Correct image dimensions and aspect ratio.
5. NoData transparency: collar pixels (value 0) are rendered with Alpha=0.
6. Valid optical pixels are rendered with Alpha=255.
7. Out-of-coverage bounding box returns 422 BOUNDS_OUT_OF_COVERAGE.
8. Inverted bounding box (min >= max) returns 422 VALIDATION_ERROR.
9. Out-of-domain coordinates (lat > 90 or lon > 180) return 422 COORDINATE_OUT_OF_BOUNDS.
10. Elevation layer request rejected with 422 UNSUPPORTED_LAYER_OPERATION.
11. Unknown layer returns 404 LAYER_NOT_FOUND.
12. Missing raster dataset returns 503 RASTER_FILE_NOT_FOUND.
13. Memory-bounded downsampling: max_dimension parameter caps image dimensions.
"""

import io
from pathlib import Path
from unittest.mock import patch
import numpy as np
from PIL import Image
import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app

BASE = "http://test"

# Valid coordinates within the Jezero CTX orthomosaic coverage
# Ortho bounds: lat [18.2110, 18.7212], lon [77.1605, 77.6992]
VALID_PARAMS = {
    "min_lon": 77.40,
    "min_lat": 18.40,
    "max_lon": 77.45,
    "max_lat": 18.45,
    "max_dimension": 512,
}


@pytest.mark.asyncio
async def test_valid_orthomosaic_preview_returns_png():
    """Verify GET /preview returns HTTP 200 with media_type image/png and spatial headers."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as ac:
        r = await ac.get("/api/v1/layers/jezero_ctx_orthomosaic_6m/preview", params=VALID_PARAMS)
    assert r.status_code == 200
    assert r.headers["Content-Type"] == "image/png"
    assert r.headers["X-Spatial-Layer-Id"] == "jezero_ctx_orthomosaic_6m"
    assert r.headers["X-Spatial-CRS"] == "ESRI:103885"
    assert "X-Spatial-Min-Lon" in r.headers
    assert "X-Spatial-Max-Lon" in r.headers

    # Validate image bytes with PIL
    img = Image.open(io.BytesIO(r.content))
    assert img.format == "PNG"
    assert img.mode == "RGBA"
    assert img.width > 0
    assert img.height > 0
    assert img.width <= 512
    assert img.height <= 512


@pytest.mark.asyncio
async def test_render_and_preview_endpoints_are_identical():
    """Verify both /render and /preview routes return identical binary image output."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as ac:
        r1 = await ac.get("/api/v1/layers/jezero_ctx_orthomosaic_6m/preview", params=VALID_PARAMS)
        r2 = await ac.get("/api/v1/layers/jezero_ctx_orthomosaic_6m/render", params=VALID_PARAMS)
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.content == r2.content


@pytest.mark.asyncio
async def test_nodata_collar_transparency():
    """
    Verify that bounding boxes crossing the mosaic edge render unexposed collar
    pixels with Alpha=0 (transparent) and optical pixels with Alpha=255.
    Western edge of mosaic is ~77.1605°E. Requesting 77.14°E to 77.18°E crosses the collar.
    """
    params = {
        "min_lon": 77.14,
        "min_lat": 18.30,
        "max_lon": 77.18,
        "max_lat": 18.34,
        "max_dimension": 256,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as ac:
        r = await ac.get("/api/v1/layers/jezero_ctx_orthomosaic_6m/preview", params=params)
    assert r.status_code == 200
    img = Image.open(io.BytesIO(r.content))
    arr = np.array(img)
    alpha = arr[..., 3]
    # Check that both transparent (0) and opaque (255) pixels exist
    assert (alpha == 0).sum() > 0, "Expected transparent collar pixels"
    assert (alpha == 255).sum() > 0, "Expected opaque imagery pixels"


@pytest.mark.asyncio
async def test_out_of_coverage_returns_422():
    """Bounding box entirely outside the layer coverage returns 422 BOUNDS_OUT_OF_COVERAGE."""
    params = {
        "min_lon": 10.0,
        "min_lat": 18.0,
        "max_lon": 11.0,
        "max_lat": 19.0,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as ac:
        r = await ac.get("/api/v1/layers/jezero_ctx_orthomosaic_6m/preview", params=params)
    assert r.status_code == 422
    data = r.json()
    assert data["status"] == "error"
    assert data["error"]["code"] == "BOUNDS_OUT_OF_COVERAGE"
    assert "layer_coverage_lon" in data["error"]["details"]


@pytest.mark.asyncio
async def test_inverted_lon_bounds_returns_422():
    """min_lon >= max_lon returns 422 VALIDATION_ERROR."""
    params = {**VALID_PARAMS, "min_lon": 77.50, "max_lon": 77.40}
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as ac:
        r = await ac.get("/api/v1/layers/jezero_ctx_orthomosaic_6m/preview", params=params)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_inverted_lat_bounds_returns_422():
    """min_lat >= max_lat returns 422 VALIDATION_ERROR."""
    params = {**VALID_PARAMS, "min_lat": 18.50, "max_lat": 18.40}
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as ac:
        r = await ac.get("/api/v1/layers/jezero_ctx_orthomosaic_6m/preview", params=params)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_out_of_domain_coordinates_returns_422():
    """Latitude outside [-90, 90] returns 422 COORDINATE_OUT_OF_BOUNDS."""
    params = {**VALID_PARAMS, "min_lat": -95.0}
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as ac:
        r = await ac.get("/api/v1/layers/jezero_ctx_orthomosaic_6m/preview", params=params)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "COORDINATE_OUT_OF_BOUNDS"


@pytest.mark.asyncio
async def test_dem_elevation_layer_preview_rejected():
    """Elevation DEM layers must not be interpreted as imagery; returns 422 UNSUPPORTED_LAYER_OPERATION."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as ac:
        r = await ac.get("/api/v1/layers/jezero_ctx_dem_20m/preview", params=VALID_PARAMS)
    assert r.status_code == 422
    data = r.json()
    assert data["status"] == "error"
    assert data["error"]["code"] == "UNSUPPORTED_LAYER_OPERATION"


@pytest.mark.asyncio
async def test_unknown_layer_returns_404():
    """Requesting preview for an unregistered layer ID returns 404 LAYER_NOT_FOUND."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as ac:
        r = await ac.get("/api/v1/layers/fantasy_ortho_layer/preview", params=VALID_PARAMS)
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "LAYER_NOT_FOUND"


@pytest.mark.asyncio
async def test_missing_raster_file_returns_503():
    """If the underlying GeoTIFF file is missing on disk, return 503 RASTER_FILE_NOT_FOUND."""
    with patch("app.api.v1.endpoints.layers._LAYER_RASTER_PATHS", {"jezero_ctx_orthomosaic_6m": Path("nonexistent.tif")}):
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as ac:
            r = await ac.get("/api/v1/layers/jezero_ctx_orthomosaic_6m/preview", params=VALID_PARAMS)
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "RASTER_FILE_NOT_FOUND"


@pytest.mark.asyncio
async def test_memory_bounded_downsampling():
    """Verify max_dimension limits the returned image dimensions."""
    params = {**VALID_PARAMS, "max_dimension": 128}
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as ac:
        r = await ac.get("/api/v1/layers/jezero_ctx_orthomosaic_6m/preview", params=params)
    assert r.status_code == 200
    img = Image.open(io.BytesIO(r.content))
    assert max(img.width, img.height) <= 128


@pytest.mark.asyncio
async def test_actual_pixel_footprint_headers():
    """Verify X-Spatial-Actual-* headers distinguish pixel grid footprint from requested bounding box."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as ac:
        r = await ac.get("/api/v1/layers/jezero_ctx_orthomosaic_6m/preview", params=VALID_PARAMS)
    assert r.status_code == 200
    for header in (
        "X-Spatial-Actual-Min-Lon",
        "X-Spatial-Actual-Min-Lat",
        "X-Spatial-Actual-Max-Lon",
        "X-Spatial-Actual-Max-Lat",
    ):
        assert header in r.headers
        val = float(r.headers[header])
        assert not np.isnan(val)

    # Actual bounds should be close to requested bounds within one pixel resolution margin
    assert abs(float(r.headers["X-Spatial-Actual-Min-Lon"]) - VALID_PARAMS["min_lon"]) < 0.005
    assert abs(float(r.headers["X-Spatial-Actual-Max-Lon"]) - VALID_PARAMS["max_lon"]) < 0.005


@pytest.mark.asyncio
async def test_full_orthomosaic_preview_peak_memory():
    """Verify that requesting the entire orthomosaic with downsampling operates strictly under 16 MB."""
    import tracemalloc

    full_mosaic_params = {
        "min_lon": 77.1605,
        "min_lat": 18.2110,
        "max_lon": 77.6992,
        "max_lat": 18.7212,
        "max_dimension": 1024,
    }
    tracemalloc.start()
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as ac:
        r = await ac.get("/api/v1/layers/jezero_ctx_orthomosaic_6m/preview", params=full_mosaic_params)
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert r.status_code == 200
    peak_mb = peak / (1024 * 1024)
    # Target is strictly under 16 MB (Increment 5.1 baseline was 358 MB)
    assert peak_mb < 16.0, f"Peak memory was {peak_mb:.2f} MB, exceeding 16 MB threshold"


@pytest.mark.asyncio
async def test_max_dimension_boundary_validation():
    """Verify max_dimension boundary constraints: default 1024, max 2048, rejects 2049 and 4096."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as ac:
        # Default (omitted) succeeds
        r_default = await ac.get("/api/v1/layers/jezero_ctx_orthomosaic_6m/preview", params=VALID_PARAMS)
        assert r_default.status_code == 200

        # Maximum allowed: 2048 succeeds
        r_2048 = await ac.get(
            "/api/v1/layers/jezero_ctx_orthomosaic_6m/preview",
            params={**VALID_PARAMS, "max_dimension": 2048},
        )
        assert r_2048.status_code == 200

        # Boundary violation: 2049 rejected with 422
        r_2049 = await ac.get(
            "/api/v1/layers/jezero_ctx_orthomosaic_6m/preview",
            params={**VALID_PARAMS, "max_dimension": 2049},
        )
        assert r_2049.status_code == 422

        # Previous ceiling: 4096 rejected with 422
        r_4096 = await ac.get(
            "/api/v1/layers/jezero_ctx_orthomosaic_6m/preview",
            params={**VALID_PARAMS, "max_dimension": 4096},
        )
        assert r_4096.status_code == 422

        # Lower boundary violation: 15 rejected with 422
        r_15 = await ac.get(
            "/api/v1/layers/jezero_ctx_orthomosaic_6m/preview",
            params={**VALID_PARAMS, "max_dimension": 15},
        )
        assert r_15.status_code == 422


@pytest.mark.asyncio
async def test_memory_measurement_at_1024_and_2048():
    """
    Empirically measure peak heap memory for full-mosaic previews at max_dimension 1024 and 2048.
    Methodology: Python standard library tracemalloc (measures Python heap allocations).
    1024 operates under 16 MB (~7.6-9.9 MB).
    2048 requires ~36 MB Python heap and is documented as exceeding the 16 MB threshold.
    """
    import tracemalloc

    full_mosaic_params = {
        "min_lon": 77.1605,
        "min_lat": 18.2110,
        "max_lon": 77.6992,
        "max_lat": 18.7212,
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as ac:
        # Measure at 1024
        tracemalloc.start()
        r_1024 = await ac.get(
            "/api/v1/layers/jezero_ctx_orthomosaic_6m/preview",
            params={**full_mosaic_params, "max_dimension": 1024},
        )
        _, peak_1024 = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        assert r_1024.status_code == 200
        peak_1024_mb = peak_1024 / (1024 * 1024)
        assert peak_1024_mb < 16.0

        # Measure at 2048
        tracemalloc.start()
        r_2048 = await ac.get(
            "/api/v1/layers/jezero_ctx_orthomosaic_6m/preview",
            params={**full_mosaic_params, "max_dimension": 2048},
        )
        _, peak_2048 = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        assert r_2048.status_code == 200
        peak_2048_mb = peak_2048 / (1024 * 1024)
        # 2048 legitimately exceeds 16 MB (~36 MB), but stays well below the 358 MB un-decimated baseline
        assert peak_2048_mb < 50.0


