import pytest
import math
from app.scientific.geodesy import normalize_longitude, validate_coordinates, haversine_distance, MARS_IAU2015_SPHERE_RADIUS_M

def test_latitude_boundary_validation():
    assert validate_coordinates(90, 0) is True
    assert validate_coordinates(-90, 0) is True
    with pytest.raises(ValueError, match="Latitude"):
        validate_coordinates(90.1, 0)
    with pytest.raises(ValueError, match="Latitude"):
        validate_coordinates(-90.1, 0)

def test_longitude_boundary_validation():
    # Longitude validation boundaries in confirmed [-180, 180] domain
    assert validate_coordinates(0, 180) is True
    assert validate_coordinates(0, -180) is True
    assert validate_coordinates(0, 0) is True
    assert validate_coordinates(0, 77.5) is True
    assert validate_coordinates(0, -133.8) is True
    with pytest.raises(ValueError, match="Longitude"):
        validate_coordinates(0, 180.1)
    with pytest.raises(ValueError, match="Longitude"):
        validate_coordinates(0, -180.1)
    with pytest.raises(ValueError, match="Longitude"):
        validate_coordinates(0, 360)

def test_legacy_longitude_domain_validation():
    # Explicit legacy [0, 360) half-open domain validation
    assert validate_coordinates(0, 0, lon_domain="[0, 360)") is True
    assert validate_coordinates(0, 180, lon_domain="[0, 360)") is True
    assert validate_coordinates(0, 359.9, lon_domain="[0, 360)") is True
    with pytest.raises(ValueError, match="Longitude"):
        validate_coordinates(0, -0.1, lon_domain="[0, 360)")
    with pytest.raises(ValueError, match="Longitude"):
        validate_coordinates(0, 360, lon_domain="[0, 360)")
    with pytest.raises(ValueError, match="Longitude"):
        validate_coordinates(0, 360.1, lon_domain="[0, 360)")

def test_unsupported_longitude_domain_rejected():
    # Obsolete [0, 360] inclusive domain must be rejected
    with pytest.raises(ValueError, match="Unsupported longitude domain"):
        validate_coordinates(0, 180, lon_domain="[0, 360]")
    with pytest.raises(ValueError, match="Unsupported longitude domain"):
        validate_coordinates(0, 0, lon_domain="0_to_360")
    with pytest.raises(ValueError, match="Unsupported longitude domain"):
        validate_coordinates(0, 0, lon_domain="invalid_domain")

def test_boolean_coordinates_rejected():
    # Reject Boolean coordinates for latitude and longitude in validate_coordinates
    with pytest.raises(ValueError, match="Latitude"):
        validate_coordinates(True, 0)
    with pytest.raises(ValueError, match="Latitude"):
        validate_coordinates(False, 0)
    with pytest.raises(ValueError, match="Longitude"):
        validate_coordinates(0, True)
    with pytest.raises(ValueError, match="Longitude"):
        validate_coordinates(0, False)

    # normalize_longitude must also reject Boolean longitude
    with pytest.raises(ValueError, match="Longitude"):
        normalize_longitude(True)
    with pytest.raises(ValueError, match="Longitude"):
        normalize_longitude(False)

def test_non_finite_coordinates_rejected():
    # Reject NaN and +/- infinity for both latitude and longitude
    with pytest.raises(ValueError, match="Latitude"):
        validate_coordinates(float('nan'), 0)
    with pytest.raises(ValueError, match="Longitude"):
        validate_coordinates(0, float('nan'))
    with pytest.raises(ValueError, match="Latitude"):
        validate_coordinates(float('inf'), 0)
    with pytest.raises(ValueError, match="Longitude"):
        validate_coordinates(0, float('inf'))
    with pytest.raises(ValueError, match="Latitude"):
        validate_coordinates(float('-inf'), 0)
    with pytest.raises(ValueError, match="Longitude"):
        validate_coordinates(0, float('-inf'))

    with pytest.raises(ValueError, match="Longitude"):
        normalize_longitude(float('nan'))
    with pytest.raises(ValueError, match="Longitude"):
        normalize_longitude(float('inf'))
    with pytest.raises(ValueError, match="Longitude"):
        normalize_longitude(float('-inf'))

def test_longitude_normalization_and_wrapping():
    # Confirmed convention: default domain [-180, 180], positive-east
    assert normalize_longitude(0) == 0
    assert normalize_longitude(180) == 180
    assert normalize_longitude(-180) == 180
    assert normalize_longitude(181) == -179
    assert normalize_longitude(-181) == 179
    assert normalize_longitude(360) == 0
    assert normalize_longitude(-360) == 0
    assert normalize_longitude(-1) == -1
    assert normalize_longitude(361) == 1

    # Preserving explicit call with wrap_to_360=False
    assert normalize_longitude(180, wrap_to_360=False) == 180
    assert normalize_longitude(181, wrap_to_360=False) == -179

    # Explicit legacy wrapping to [0, 360)
    assert normalize_longitude(360, wrap_to_360=True) == 0
    assert normalize_longitude(361, wrap_to_360=True) == 1
    assert normalize_longitude(-1, wrap_to_360=True) == 359
    assert normalize_longitude(180, wrap_to_360=True) == 180

def test_positive_east_normalization():
    # Multi-turn positive-east wrapping
    assert normalize_longitude(540) == 180     # 540 = 180 + 360
    assert normalize_longitude(-540) == 180    # -540 = -180 - 360
    assert normalize_longitude(541) == -179    # 541 = 181 + 360 -> -179
    assert normalize_longitude(-541) == 179    # -541 = -181 - 360 -> 179
    assert normalize_longitude(720) == 0
    assert normalize_longitude(-720) == 0

def test_same_point_distance_is_zero():
    dist = haversine_distance(18.65, 226.2, 18.65, 226.2)
    assert dist == 0

def test_symmetric_distance():
    lat1, lon1 = 18.65, 226.2
    lat2, lon2 = -14.57, 175.47
    dist12 = haversine_distance(lat1, lon1, lat2, lon2)
    dist21 = haversine_distance(lat2, lon2, lat1, lon1)
    assert pytest.approx(dist12) == dist21

def test_haversine_distance_equivalent_longitudes_new_domain():
    # 226.2 in [0, 360) is equivalent to 226.2 - 360 = -133.8 in [-180, 180]
    lat1, lon1_legacy, lon1_new = 18.65, 226.2, -133.8
    lat2, lon2 = -14.57, 175.47

    dist_legacy = haversine_distance(lat1, lon1_legacy, lat2, lon2)
    dist_new = haversine_distance(lat1, lon1_new, lat2, lon2)

    assert pytest.approx(dist_new, rel=1e-9) == dist_legacy

def test_known_spherical_distance_mars_radius():
    # Test across 1 degree of latitude at the equator
    # Expected: (2 * pi * R) / 360
    expected = (2 * 3.141592653589793 * MARS_IAU2015_SPHERE_RADIUS_M) / 360
    actual = haversine_distance(0, 0, 1, 0)
    assert pytest.approx(actual, rel=1e-5) == expected

def test_correct_use_of_mars_radius():
    # Earth radius is ~6371km, Mars is ~3396km.
    # Distance for 1 degree lat on Earth is ~111km, on Mars it's ~59km.
    dist_mars = haversine_distance(0, 0, 1, 0)
    # 1 degree on Mars in meters
    assert 59000 < dist_mars < 60000
