import pytest
from app.scientific.geodesy import normalize_longitude, validate_coordinates, haversine_distance, MARS_IAU2015_SPHERE_RADIUS_M

def test_latitude_boundary_validation():
    assert validate_coordinates(90, 0) is True
    assert validate_coordinates(-90, 0) is True
    with pytest.raises(ValueError):
        validate_coordinates(90.1, 0)
    with pytest.raises(ValueError):
        validate_coordinates(-90.1, 0)

def test_longitude_normalization_and_wrapping():
    # Positive-East [0, 360)
    assert normalize_longitude(360) == 0
    assert normalize_longitude(361) == 1
    assert normalize_longitude(-1) == 359
    # [-180, 180]
    assert normalize_longitude(180, wrap_to_360=False) == 180
    assert normalize_longitude(181, wrap_to_360=False) == -179

def test_same_point_distance_is_zero():
    dist = haversine_distance(18.65, 226.2, 18.65, 226.2)
    assert dist == 0

def test_symmetric_distance():
    lat1, lon1 = 18.65, 226.2
    lat2, lon2 = -14.57, 175.47
    dist12 = haversine_distance(lat1, lon1, lat2, lon2)
    dist21 = haversine_distance(lat2, lon2, lat1, lon1)
    assert pytest.approx(dist12) == dist21

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
