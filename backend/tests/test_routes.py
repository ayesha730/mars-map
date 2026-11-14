"""
API contract and validation tests for POST /api/v1/routes.

Coverage:
  - Request schema validation (happy path, bad fields, wrong CRS)
  - Response envelope shape for ROUTING_DATA_UNAVAILABLE
  - Region not found (404)
  - Error envelope always present on failure
  - All routing profiles accepted
  - Coordinate boundary conditions
  - Same-point request
"""

import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

BASE = "http://test"
ROUTES_URL = "/api/v1/routes"

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

VALID_PAYLOAD = {
    "region_id": "jezero_crater",
    "start": {"latitude": 18.4, "longitude": 77.5},
    "destination": {"latitude": 18.6, "longitude": 77.9},
    "coordinate_reference": {
        "body": "Mars",
        "latitude_type": "planetocentric",
        "longitude_direction": "positive_east",
        "longitude_domain": "-180_to_180",
        "angular_unit": "degrees",
    },
    "routing_profile": "safe",
}


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

async def post_route(payload: dict) -> tuple:
    """Returns (status_code, json_body)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as ac:
        r = await ac.post(ROUTES_URL, json=payload)
    return r.status_code, r.json()


# ---------------------------------------------------------------------------
# 1. ROUTING_DATA_UNAVAILABLE — shape contract
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_routes_unavailable_returns_503():
    code, body = await post_route(VALID_PAYLOAD)
    assert code == 503, f"Expected 503, got {code}: {body}"


@pytest.mark.asyncio
async def test_routes_unavailable_error_envelope():
    """Response must follow PRD error envelope: status, error.code, error.message, request_id."""
    code, body = await post_route(VALID_PAYLOAD)
    assert body["status"] == "error"
    assert body["error"]["code"] == "ROUTING_DATA_UNAVAILABLE"
    assert isinstance(body["error"]["message"], str)
    assert len(body["error"]["message"]) > 0
    assert "request_id" in body
    assert body["request_id"] is not None


@pytest.mark.asyncio
async def test_routes_unavailable_details_contains_distance():
    """Details block must include an informational great-circle distance, not a fabricated route."""
    _, body = await post_route(VALID_PAYLOAD)
    details = body["error"]["details"]
    assert "great_circle_distance_m" in details
    assert isinstance(details["great_circle_distance_m"], float)
    assert details["great_circle_distance_m"] >= 0


@pytest.mark.asyncio
async def test_routes_unavailable_distance_disclaimer_present():
    """Details must carry a disclaimer that the distance is NOT a navigable route."""
    _, body = await post_route(VALID_PAYLOAD)
    details = body["error"]["details"]
    assert "distance_disclaimer" in details
    disclaimer = details["distance_disclaimer"].lower()
    assert "not" in disclaimer or "approximation" in disclaimer


@pytest.mark.asyncio
async def test_routes_unavailable_region_id_in_details():
    _, body = await post_route(VALID_PAYLOAD)
    assert body["error"]["details"]["region_id"] == "jezero_crater"


# ---------------------------------------------------------------------------
# 2. Region not found
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_routes_unknown_region_returns_404():
    payload = {**VALID_PAYLOAD, "region_id": "atlantis_city"}
    code, body = await post_route(payload)
    assert code == 404
    assert body["status"] == "error"
    assert body["error"]["code"] == "REGION_NOT_FOUND"


@pytest.mark.asyncio
async def test_routes_unknown_region_lists_supported():
    payload = {**VALID_PAYLOAD, "region_id": "nowhere"}
    _, body = await post_route(payload)
    details = body["error"]["details"]
    assert "supported_regions" in details
    assert isinstance(details["supported_regions"], list)
    assert "jezero_crater" in details["supported_regions"]


# ---------------------------------------------------------------------------
# 3. Validation errors — PRD envelope
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_missing_region_id_returns_422():
    payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "region_id"}
    code, body = await post_route(payload)
    assert code == 422
    assert body["status"] == "error"
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert "request_id" in body


@pytest.mark.asyncio
async def test_missing_start_returns_422():
    payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "start"}
    code, body = await post_route(payload)
    assert code == 422
    assert body["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_missing_destination_returns_422():
    payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "destination"}
    code, body = await post_route(payload)
    assert code == 422
    assert body["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_latitude_out_of_range_returns_422():
    payload = {
        **VALID_PAYLOAD,
        "start": {"latitude": 91.0, "longitude": 77.5},
    }
    code, body = await post_route(payload)
    assert code == 422
    assert body["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_longitude_out_of_range_returns_422():
    payload = {
        **VALID_PAYLOAD,
        "start": {"latitude": 18.4, "longitude": 181.0},
    }
    code, body = await post_route(payload)
    assert code == 422
    assert body["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_negative_latitude_boundary_accepted():
    payload = {
        **VALID_PAYLOAD,
        "start": {"latitude": -90.0, "longitude": 0.0},
        "destination": {"latitude": -89.9, "longitude": 0.0},
    }
    code, _ = await post_route(payload)
    # Should reach routing (503), not fail validation (422)
    assert code == 503


@pytest.mark.asyncio
async def test_negative_longitude_boundary_accepted():
    payload = {
        **VALID_PAYLOAD,
        "start": {"latitude": 0.0, "longitude": -180.0},
        "destination": {"latitude": 0.0, "longitude": -179.0},
    }
    code, _ = await post_route(payload)
    assert code == 503  # Not a validation error


@pytest.mark.asyncio
async def test_wrong_crs_body_returns_422():
    payload = {
        **VALID_PAYLOAD,
        "coordinate_reference": {
            "body": "Earth",          # Wrong
            "latitude_type": "planetocentric",
            "longitude_direction": "positive_east",
            "longitude_domain": "-180_to_180",
            "angular_unit": "degrees",
        },
    }
    code, body = await post_route(payload)
    assert code == 422
    assert body["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_wrong_crs_longitude_direction_returns_422():
    payload = {
        **VALID_PAYLOAD,
        "coordinate_reference": {
            "body": "Mars",
            "latitude_type": "planetocentric",
            "longitude_direction": "positive_west",   # Wrong
            "longitude_domain": "-180_to_180",
            "angular_unit": "degrees",
        },
    }
    code, body = await post_route(payload)
    assert code == 422
    assert body["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_invalid_routing_profile_returns_422():
    payload = {**VALID_PAYLOAD, "routing_profile": "warp_speed"}
    code, body = await post_route(payload)
    assert code == 422
    assert body["error"]["code"] == "VALIDATION_ERROR"


# ---------------------------------------------------------------------------
# 4. All valid routing profiles are accepted (reach routing layer, not 422)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("profile", ["safe", "fast", "science"])
async def test_all_routing_profiles_accepted(profile):
    payload = {**VALID_PAYLOAD, "routing_profile": profile}
    code, body = await post_route(payload)
    # Should hit routing (503), not validation failure (422)
    assert code == 503, (
        f"Profile '{profile}' got {code} instead of 503. Body: {body}"
    )


# ---------------------------------------------------------------------------
# 5. Same-point request (distance should be 0 or near-0)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_same_point_route_distance_is_zero():
    payload = {
        **VALID_PAYLOAD,
        "start": {"latitude": 18.4, "longitude": 77.5},
        "destination": {"latitude": 18.4, "longitude": 77.5},
    }
    _, body = await post_route(payload)
    # Still 503 (unavailable), but distance in details must be 0
    details = body["error"]["details"]
    assert details["great_circle_distance_m"] == 0.0


# ---------------------------------------------------------------------------
# 6. Gale Crater — second supported region
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_gale_crater_region_accepted():
    payload = {
        **VALID_PAYLOAD,
        "region_id": "gale_crater",
        "start": {"latitude": -5.4, "longitude": 137.8},
        "destination": {"latitude": -5.5, "longitude": 137.9},
    }
    code, body = await post_route(payload)
    assert code == 503
    assert body["error"]["code"] == "ROUTING_DATA_UNAVAILABLE"


# ---------------------------------------------------------------------------
# 7. Default coordinate_reference (omitted from request)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_default_crs_accepted():
    """coordinate_reference defaults to the confirmed Mars convention."""
    payload = {
        "region_id": "jezero_crater",
        "start": {"latitude": 18.4, "longitude": 77.5},
        "destination": {"latitude": 18.6, "longitude": 77.9},
    }
    code, _ = await post_route(payload)
    assert code == 503  # Reaches routing, not validation failure
