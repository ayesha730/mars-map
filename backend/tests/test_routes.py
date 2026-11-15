import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


ROUTE_ENDPOINT = "/api/v1/routes"

# A short route inside the Jezero DEM coverage.
VALID_PAYLOAD = {
    "region_id": "jezero_crater",
    "start": {
        "latitude": 18.4,
        "longitude": 77.7,
    },
    "destination": {
        "latitude": 18.405,
        "longitude": 77.705,
    },
}

SAME_POINT_PAYLOAD = {
    "region_id": "jezero_crater",
    "start": {
        "latitude": 18.4,
        "longitude": 77.7,
    },
    "destination": {
        "latitude": 18.4,
        "longitude": 77.7,
    },
}


async def post_route(payload: dict):
    """Send a route request and return its status code and JSON body."""
    transport = ASGITransport(app=app)

    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.post(ROUTE_ENDPOINT, json=payload)

    return response.status_code, response.json()


# -------------------------------------------------------------------
# Successful Jezero routing
# -------------------------------------------------------------------

@pytest.mark.asyncio
async def test_jezero_route_returns_success():
    code, body = await post_route(VALID_PAYLOAD)

    assert code == 200, body
    assert body["status"] == "success"
    assert body["region_id"] == "jezero_crater"
    assert body["algorithm"] == "a_star"
    assert body["distance_m"] > 0
    assert len(body["route_geometry"]["points"]) > 1


@pytest.mark.asyncio
async def test_jezero_route_uses_native_dem_coordinates():
    code, body = await post_route(VALID_PAYLOAD)

    assert code == 200, body
    assert body["route_geometry"]["coordinate_space"] in (
        "jezero_dem_native_projected_crs",
        "arespath_display_v1",
    )


@pytest.mark.asyncio
async def test_jezero_route_points_have_x_and_y():
    code, body = await post_route(VALID_PAYLOAD)

    assert code == 200, body

    points = body["route_geometry"]["points"]

    assert len(points) > 1

    for point in points:
        assert "x" in point
        assert "y" in point
        assert isinstance(point["x"], (int, float))
        assert isinstance(point["y"], (int, float))


@pytest.mark.asyncio
async def test_jezero_route_has_data_sources():
    code, body = await post_route(VALID_PAYLOAD)

    assert code == 200, body
    assert isinstance(body["data_sources"], list)
    assert len(body["data_sources"]) > 0


@pytest.mark.asyncio
async def test_jezero_route_does_not_claim_unverified_elevation_units():
    code, body = await post_route(VALID_PAYLOAD)

    assert code == 200, body

    terrain = body["terrain_summary"]

    # Slope is unevaluated in this release
    assert terrain["max_slope_deg"] is None
    # If elevation is evaluated, it must be valid numbers or None
    if terrain["min_elevation_m"] is not None:
        assert isinstance(terrain["min_elevation_m"], (int, float))
    if terrain["max_elevation_m"] is not None:
        assert isinstance(terrain["max_elevation_m"], (int, float))


@pytest.mark.asyncio
async def test_jezero_route_includes_warnings():
    code, body = await post_route(VALID_PAYLOAD)

    assert code == 200, body
    assert isinstance(body["warnings"], list)
    assert len(body["warnings"]) > 0


# -------------------------------------------------------------------
# Routing profiles
# -------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "profile",
    ["safe", "fast"],
)
async def test_supported_routing_profiles(profile):
    payload = {
        **VALID_PAYLOAD,
        "routing_profile": profile,
    }

    code, body = await post_route(payload)

    assert code == 200, body
    assert body["status"] == "success"


@pytest.mark.asyncio
async def test_science_profile_is_not_available():
    payload = {
        **VALID_PAYLOAD,
        "routing_profile": "science",
    }

    code, body = await post_route(payload)

    assert code == 503
    assert body["error"]["code"] == "SCIENCE_PROFILE_UNAVAILABLE"


# -------------------------------------------------------------------
# Same-point route
# -------------------------------------------------------------------

@pytest.mark.asyncio
async def test_same_point_route_distance_is_zero():
    code, body = await post_route(SAME_POINT_PAYLOAD)

    assert code == 200, body
    assert body["status"] == "success"
    assert body["distance_m"] == 0


# -------------------------------------------------------------------
# Region availability
# -------------------------------------------------------------------

@pytest.mark.asyncio
async def test_gale_crater_routing_is_unavailable():
    payload = {
        **VALID_PAYLOAD,
        "region_id": "gale_crater",
    }

    code, body = await post_route(payload)

    assert code == 503
    assert body["error"]["code"] == "ROUTING_DATA_UNAVAILABLE"


@pytest.mark.asyncio
async def test_unknown_region_returns_404():
    payload = {
        **VALID_PAYLOAD,
        "region_id": "unknown_region",
    }

    code, body = await post_route(payload)

    assert code == 404


# -------------------------------------------------------------------
# Request validation
# -------------------------------------------------------------------

@pytest.mark.asyncio
async def test_missing_region_id_returns_422():
    payload = {
        "start": VALID_PAYLOAD["start"],
        "destination": VALID_PAYLOAD["destination"],
    }

    code, body = await post_route(payload)

    assert code == 422


@pytest.mark.asyncio
async def test_missing_start_returns_422():
    payload = {
        "region_id": "jezero_crater",
        "destination": VALID_PAYLOAD["destination"],
    }

    code, body = await post_route(payload)

    assert code == 422


@pytest.mark.asyncio
async def test_missing_destination_returns_422():
    payload = {
        "region_id": "jezero_crater",
        "start": VALID_PAYLOAD["start"],
    }

    code, body = await post_route(payload)

    assert code == 422


@pytest.mark.asyncio
async def test_invalid_latitude_returns_422():
    payload = {
        **VALID_PAYLOAD,
        "start": {
            "latitude": 95.0,
            "longitude": 77.7,
        },
    }

    code, body = await post_route(payload)

    assert code == 422


@pytest.mark.asyncio
async def test_invalid_longitude_returns_422():
    payload = {
        **VALID_PAYLOAD,
        "start": {
            "latitude": 18.4,
            "longitude": 200.0,
        },
    }

    code, body = await post_route(payload)

    assert code == 422


@pytest.mark.asyncio
async def test_invalid_routing_profile_returns_422():
    payload = {
        **VALID_PAYLOAD,
        "routing_profile": "unknown",
    }

    code, body = await post_route(payload)

    assert code == 422


@pytest.mark.asyncio
async def test_default_coordinate_reference_is_accepted():
    payload = {
        **VALID_PAYLOAD,
    }

    code, body = await post_route(payload)

    assert code == 200, body
    assert body["status"] == "success"


# -------------------------------------------------------------------
# Coordinate boundary validation
# -------------------------------------------------------------------

@pytest.mark.asyncio
async def test_negative_latitude_is_not_rejected_by_schema():
    payload = {
        **VALID_PAYLOAD,
        "start": {
            "latitude": -18.4,
            "longitude": 77.7,
        },
    }

    code, body = await post_route(payload)

    # Negative latitude is a valid geographic coordinate and must pass Pydantic schema validation.
    # It fails at routing domain level (COORDINATE_OUT_OF_BOUNDS / ROUTE_COMPUTATION_FAILED), not schema VALIDATION_ERROR.
    assert body.get("error", {}).get("code") != "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_negative_longitude_is_not_rejected_by_schema():
    payload = {
        **VALID_PAYLOAD,
        "start": {
            "latitude": 18.4,
            "longitude": -77.7,
        },
    }

    code, body = await post_route(payload)

    # Negative longitude is valid geographically and must pass Pydantic schema validation.
    # It fails at routing domain level (COORDINATE_OUT_OF_BOUNDS / ROUTE_COMPUTATION_FAILED), not schema VALIDATION_ERROR.
    assert body.get("error", {}).get("code") != "VALIDATION_ERROR"