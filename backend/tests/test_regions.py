"""
API contract tests for region metadata endpoints:
  GET /api/v1/regions
  GET /api/v1/regions/{region_id}

Verifies the full metadata contract is satisfied.
"""

import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

BASE = "http://test"


@pytest.mark.asyncio
async def test_list_regions_returns_200():
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as ac:
        r = await ac.get("/api/v1/regions")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) >= 1


@pytest.mark.asyncio
async def test_list_regions_contains_known_regions():
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as ac:
        r = await ac.get("/api/v1/regions")
    ids = [item["region_id"] for item in r.json()]
    assert "jezero_crater" in ids
    assert "gale_crater" in ids


@pytest.mark.asyncio
async def test_region_metadata_contract_fields():
    """Every region must expose the full metadata contract."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as ac:
        r = await ac.get("/api/v1/regions/jezero_crater")
    assert r.status_code == 200
    data = r.json()

    # Required top-level fields
    assert "region_id" in data
    assert "source_crs" in data
    assert "display_coordinate_space" in data
    assert "display_projection" in data
    assert "display_origin" in data
    assert "x_axis" in data
    assert "y_axis" in data
    assert "transformation" in data
    assert "datasets" in data
    assert "routing_available" in data


@pytest.mark.asyncio
async def test_region_source_crs_matches_convention():
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as ac:
        r = await ac.get("/api/v1/regions/jezero_crater")
    crs = r.json()["source_crs"]
    assert crs["body"] == "Mars"
    assert crs["latitude_type"] == "planetocentric"
    assert crs["longitude_direction"] == "positive_east"
    assert crs["longitude_domain"] == "-180_to_180"
    assert crs["angular_unit"] == "degrees"


@pytest.mark.asyncio
async def test_region_display_space_is_arespath_v1():
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as ac:
        r = await ac.get("/api/v1/regions/jezero_crater")
    data = r.json()
    assert data["display_coordinate_space"] == "arespath_display_v1"
    assert "East" in data["x_axis"]
    assert "North" in data["y_axis"]


@pytest.mark.asyncio
async def test_region_datasets_are_explicit_about_synthetic():
    """Datasets must honestly flag synthetic/placeholder data."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as ac:
        r = await ac.get("/api/v1/regions/jezero_crater")
    datasets = r.json()["datasets"]
    assert len(datasets) >= 1
    for ds in datasets:
        assert "is_synthetic" in ds
        # If synthetic, must explain what real data would be
        if ds["is_synthetic"]:
            assert ds.get("synthetic_description") is not None


@pytest.mark.asyncio
async def test_region_routing_unavailable_has_reason():
    """Gale crater has no routing dataset integrated; routing must be unavailable with a reason."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as ac:
        r = await ac.get("/api/v1/regions/gale_crater")
    data = r.json()
    assert data["routing_available"] is False
    assert data["routing_unavailable_reason"] is not None


@pytest.mark.asyncio
async def test_jezero_routing_available():
    """Jezero crater has verified DEM integrated; routing must be available when initialized."""
    from app.main import lifespan
    async with lifespan(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as ac:
            r = await ac.get("/api/v1/regions/jezero_crater")
        data = r.json()
        assert data["routing_available"] is True
        assert data["routing_unavailable_reason"] is None


@pytest.mark.asyncio
async def test_region_not_found_returns_404_envelope():
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as ac:
        r = await ac.get("/api/v1/regions/fake_region_xyz")
    assert r.status_code == 404
    body = r.json()
    assert body["status"] == "error"
    assert body["error"]["code"] == "REGION_NOT_FOUND"
    assert "request_id" in body


@pytest.mark.asyncio
async def test_transformation_method_is_documented():
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as ac:
        r = await ac.get("/api/v1/regions/jezero_crater")
    t = r.json()["transformation"]
    assert isinstance(t["method"], str)
    assert len(t["method"]) > 0
