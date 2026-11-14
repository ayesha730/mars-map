"""
Unit tests for AresPath API schemas.

Covers:
- MarsPoint boolean rejection and valid numeric acceptance.
- ElevationSampleRequest coordinate validation and CRS defaults/rejection.
- ElevationSampleResponse status semantics, invariants, and CoverageStatus consistency.
"""

import math
import pytest
from pydantic import ValidationError

from app.models.schemas import (
    MarsPoint,
    ElevationSampleRequest,
    ElevationSampleResponse,
    MarsCoordinateReference,
)
from app.scientific.dem.models import CoverageStatus


# ---------------------------------------------------------------------------
# 1 & 2: MarsPoint rejects Boolean coordinates
# ---------------------------------------------------------------------------

def test_marspoint_rejects_boolean_latitude():
    with pytest.raises(ValidationError, match="latitude cannot be a boolean value"):
        MarsPoint(latitude=True, longitude=77.5)
    with pytest.raises(ValidationError, match="latitude cannot be a boolean value"):
        MarsPoint(latitude=False, longitude=77.5)


def test_marspoint_rejects_boolean_longitude():
    with pytest.raises(ValidationError, match="longitude cannot be a boolean value"):
        MarsPoint(latitude=18.4, longitude=True)
    with pytest.raises(ValidationError, match="longitude cannot be a boolean value"):
        MarsPoint(latitude=18.4, longitude=False)


# ---------------------------------------------------------------------------
# 3: MarsPoint accepts integer and floating-point coordinates
# ---------------------------------------------------------------------------

def test_marspoint_accepts_integer_and_floating_coordinates():
    # Integer inputs (must be coerced to float without error)
    p1 = MarsPoint(latitude=18, longitude=77)
    assert p1.latitude == 18.0
    assert isinstance(p1.latitude, float)
    assert p1.longitude == 77.0
    assert isinstance(p1.longitude, float)

    # Float inputs
    p2 = MarsPoint(latitude=18.45, longitude=77.45)
    assert pytest.approx(p2.latitude) == 18.45
    assert pytest.approx(p2.longitude) == 77.45

    # Valid boundaries
    p_min = MarsPoint(latitude=-90, longitude=-180)
    assert p_min.latitude == -90.0
    assert p_min.longitude == -180.0

    p_max = MarsPoint(latitude=90.0, longitude=180.0)
    assert p_max.latitude == 90.0
    assert p_max.longitude == 180.0


# ---------------------------------------------------------------------------
# 4 & 5: ElevationSampleRequest rejects Boolean coordinates
# ---------------------------------------------------------------------------

def test_elevation_request_rejects_boolean_latitude():
    with pytest.raises(ValidationError, match="latitude cannot be a boolean value"):
        ElevationSampleRequest(region_id="jezero_crater", latitude=True, longitude=77.5)
    with pytest.raises(ValidationError, match="latitude cannot be a boolean value"):
        ElevationSampleRequest(region_id="jezero_crater", latitude=False, longitude=77.5)


def test_elevation_request_rejects_boolean_longitude():
    with pytest.raises(ValidationError, match="longitude cannot be a boolean value"):
        ElevationSampleRequest(region_id="jezero_crater", latitude=18.4, longitude=True)
    with pytest.raises(ValidationError, match="longitude cannot be a boolean value"):
        ElevationSampleRequest(region_id="jezero_crater", latitude=18.4, longitude=False)


# ---------------------------------------------------------------------------
# 6: ElevationSampleRequest accepts valid coordinate-reference defaults
# ---------------------------------------------------------------------------

def test_elevation_request_accepts_valid_coordinate_reference_defaults():
    req = ElevationSampleRequest(region_id="jezero_crater", latitude=18.45, longitude=77.45)
    assert req.region_id == "jezero_crater"
    assert pytest.approx(req.latitude) == 18.45
    assert pytest.approx(req.longitude) == 77.45

    # Default CRS verification
    crs = req.coordinate_reference
    assert crs.body == "Mars"
    assert crs.latitude_type == "planetocentric"
    assert crs.longitude_direction == "positive_east"
    assert crs.longitude_domain == "-180_to_180"
    assert crs.angular_unit == "degrees"

    # Integer coordinates accepted
    req_int = ElevationSampleRequest(region_id="jezero_crater", latitude=18, longitude=77)
    assert req_int.latitude == 18.0
    assert req_int.longitude == 77.0


# ---------------------------------------------------------------------------
# 7: Invalid coordinate-reference conventions are rejected
# ---------------------------------------------------------------------------

def test_elevation_request_invalid_coordinate_reference_rejected():
    base_payload = {"region_id": "jezero_crater", "latitude": 18.4, "longitude": 77.5}

    # Wrong body
    with pytest.raises(ValidationError, match="coordinate_reference.body"):
        ElevationSampleRequest(**base_payload, coordinate_reference={"body": "Earth"})

    # Wrong latitude_type
    with pytest.raises(ValidationError, match="coordinate_reference.latitude_type"):
        ElevationSampleRequest(**base_payload, coordinate_reference={"latitude_type": "planetographic"})

    # Wrong longitude_direction
    with pytest.raises(ValidationError, match="coordinate_reference.longitude_direction"):
        ElevationSampleRequest(**base_payload, coordinate_reference={"longitude_direction": "positive_west"})

    # Wrong longitude_domain
    with pytest.raises(ValidationError, match="coordinate_reference.longitude_domain"):
        ElevationSampleRequest(**base_payload, coordinate_reference={"longitude_domain": "0_to_360"})


# ---------------------------------------------------------------------------
# 8: Valid response construction
# ---------------------------------------------------------------------------

def test_valid_elevation_response_construction():
    resp = ElevationSampleResponse(
        region_id="jezero_crater",
        latitude=18.45,
        longitude=77.45,
        status=CoverageStatus.VALID,
        geometric_coverage=True,
        elevation_valid=True,
        elevation_m=-2571.12,
    )
    assert resp.region_id == "jezero_crater"
    assert pytest.approx(resp.latitude) == 18.45
    assert pytest.approx(resp.longitude) == 77.45
    assert resp.status == CoverageStatus.VALID
    assert resp.geometric_coverage is True
    assert resp.elevation_valid is True
    assert pytest.approx(resp.elevation_m) == -2571.12
    assert resp.sampling_method == "nearest_neighbor"
    assert resp.coordinate_reference.body == "Mars"
    assert resp.message is None


# ---------------------------------------------------------------------------
# 9: Invalid elevation/status combinations are rejected
# ---------------------------------------------------------------------------

def test_invalid_elevation_status_combinations_rejected():
    base = {
        "region_id": "jezero_crater",
        "latitude": 18.45,
        "longitude": 77.45,
    }

    # 1. elevation_valid=True requires non-null elevation_m
    with pytest.raises(ValidationError, match="elevation_valid=True requires a non-null elevation_m"):
        ElevationSampleResponse(
            **base,
            status=CoverageStatus.VALID,
            geometric_coverage=True,
            elevation_valid=True,
            elevation_m=None,
        )

    # 2. elevation_valid=True requires finite elevation_m
    with pytest.raises(ValidationError, match="elevation_valid=True requires a finite elevation_m"):
        ElevationSampleResponse(
            **base,
            status=CoverageStatus.VALID,
            geometric_coverage=True,
            elevation_valid=True,
            elevation_m=float("nan"),
        )
    with pytest.raises(ValidationError, match="elevation_valid=True requires a finite elevation_m"):
        ElevationSampleResponse(
            **base,
            status=CoverageStatus.VALID,
            geometric_coverage=True,
            elevation_valid=True,
            elevation_m=float("inf"),
        )

    # 3. elevation_valid=False requires elevation_m=None
    with pytest.raises(ValidationError, match="elevation_valid=False requires elevation_m=None"):
        ElevationSampleResponse(
            **base,
            status=CoverageStatus.OUT_OF_BOUNDS,
            geometric_coverage=False,
            elevation_valid=False,
            elevation_m=-2500.0,
        )

    # 4. CoverageStatus.VALID requires geometric_coverage=True
    with pytest.raises(ValidationError, match="CoverageStatus.VALID requires geometric_coverage=True"):
        ElevationSampleResponse(
            **base,
            status=CoverageStatus.VALID,
            geometric_coverage=False,
            elevation_valid=True,
            elevation_m=-2500.0,
        )

    # 5. CoverageStatus.VALID requires elevation_valid=True
    with pytest.raises(ValidationError, match="CoverageStatus.VALID requires elevation_valid=True"):
        ElevationSampleResponse(
            **base,
            status=CoverageStatus.VALID,
            geometric_coverage=True,
            elevation_valid=False,
            elevation_m=None,
        )

    # 6. CoverageStatus.OUT_OF_BOUNDS requires geometric_coverage=False
    with pytest.raises(ValidationError, match="CoverageStatus.OUT_OF_BOUNDS requires geometric_coverage=False"):
        ElevationSampleResponse(
            **base,
            status=CoverageStatus.OUT_OF_BOUNDS,
            geometric_coverage=True,
            elevation_valid=False,
            elevation_m=None,
        )

    # 7. CoverageStatus.OUT_OF_BOUNDS requires elevation_valid=False
    with pytest.raises(ValidationError, match="CoverageStatus.OUT_OF_BOUNDS requires elevation_valid=False"):
        ElevationSampleResponse(
            **base,
            status=CoverageStatus.OUT_OF_BOUNDS,
            geometric_coverage=False,
            elevation_valid=True,
            elevation_m=-2500.0,
        )

    # 8. CoverageStatus.NODATA_COLLAR requires geometric_coverage=True
    with pytest.raises(ValidationError, match="CoverageStatus.NODATA_COLLAR requires geometric_coverage=True"):
        ElevationSampleResponse(
            **base,
            status=CoverageStatus.NODATA_COLLAR,
            geometric_coverage=False,
            elevation_valid=False,
            elevation_m=None,
        )

    # 9. CoverageStatus.NODATA_COLLAR requires elevation_valid=False (and elevation_m=None)
    with pytest.raises(ValidationError, match="CoverageStatus.NODATA_COLLAR requires elevation_valid=False"):
        ElevationSampleResponse(
            **base,
            status=CoverageStatus.NODATA_COLLAR,
            geometric_coverage=True,
            elevation_valid=True,
            elevation_m=-2500.0,
        )

    # 10. CoverageStatus.ELEVATION_UNAVAILABLE requires geometric_coverage=True
    with pytest.raises(ValidationError, match="CoverageStatus.ELEVATION_UNAVAILABLE requires geometric_coverage=True"):
        ElevationSampleResponse(
            **base,
            status=CoverageStatus.ELEVATION_UNAVAILABLE,
            geometric_coverage=False,
            elevation_valid=False,
            elevation_m=None,
        )

    # 11. CoverageStatus.ELEVATION_UNAVAILABLE requires elevation_valid=False
    with pytest.raises(ValidationError, match="CoverageStatus.ELEVATION_UNAVAILABLE requires elevation_valid=False"):
        ElevationSampleResponse(
            **base,
            status=CoverageStatus.ELEVATION_UNAVAILABLE,
            geometric_coverage=True,
            elevation_valid=True,
            elevation_m=-2500.0,
        )


# ---------------------------------------------------------------------------
# 10: All existing CoverageStatus values are handled consistently
# ---------------------------------------------------------------------------

def test_all_coverage_status_values_handled_consistently():
    base = {"region_id": "jezero_crater", "latitude": 18.45, "longitude": 77.45}

    # VALID
    r_valid = ElevationSampleResponse(
        **base,
        status=CoverageStatus.VALID,
        geometric_coverage=True,
        elevation_valid=True,
        elevation_m=-2571.12,
    )
    assert r_valid.status == CoverageStatus.VALID
    assert r_valid.status == "valid"

    # OUT_OF_BOUNDS
    r_oob = ElevationSampleResponse(
        **base,
        status=CoverageStatus.OUT_OF_BOUNDS,
        geometric_coverage=False,
        elevation_valid=False,
        elevation_m=None,
        message="Coordinates lie outside the raster geometric bounds",
    )
    assert r_oob.status == CoverageStatus.OUT_OF_BOUNDS
    assert r_oob.status == "out_of_bounds"

    # NODATA_COLLAR
    r_nodata = ElevationSampleResponse(
        **base,
        status=CoverageStatus.NODATA_COLLAR,
        geometric_coverage=True,
        elevation_valid=False,
        elevation_m=None,
        message="Containing pixel lies in a NoData or masked collar region",
    )
    assert r_nodata.status == CoverageStatus.NODATA_COLLAR
    assert r_nodata.status == "nodata_collar"

    # ELEVATION_UNAVAILABLE
    r_unavail = ElevationSampleResponse(
        **base,
        status=CoverageStatus.ELEVATION_UNAVAILABLE,
        geometric_coverage=True,
        elevation_valid=False,
        elevation_m=None,
        message="Raster dataset not attached; elevation sampling unavailable",
    )
    assert r_unavail.status == CoverageStatus.ELEVATION_UNAVAILABLE
    assert r_unavail.status == "elevation_unavailable"

    # String parsing into CoverageStatus enum
    r_str = ElevationSampleResponse(
        **base,
        status="valid",
        geometric_coverage=True,
        elevation_valid=True,
        elevation_m=-2000.0,
    )
    assert r_str.status == CoverageStatus.VALID

    # Ensure internal pipeline details are strictly excluded from response fields
    fields = ElevationSampleResponse.model_fields.keys()
    assert "projected" not in fields
    assert "pixel_cont" not in fields
    assert "containing_cell" not in fields
    assert "bilinear_elevation_m" not in fields
