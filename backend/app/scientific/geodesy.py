import math
from typing import Tuple
from app.core.config import MARS_IAU2015_SPHERE_RADIUS_M

def normalize_longitude(lon: float, wrap_to_360: bool = True) -> float:
    """
    Normalizes longitude to [0, 360) or [-180, 180].
    Default: Positive-East [0, 360).
    """
    lon = lon % 360
    if not wrap_to_360 and lon > 180:
        lon -= 360
    return lon

def validate_coordinates(
    lat: float,
    lon: float,
    body: str = "Mars",
    lat_type: str = "Planetocentric",
    lon_dir: str = "Positive-East",
    lon_domain: str = "[0, 360)",
    angular_unit: str = "Degrees"
) -> bool:
    """
    Validates Mars coordinate constraints.
    - Latitude must be in [-90, 90].
    """
    if not -90 <= lat <= 90:
        raise ValueError(f"Latitude {lat} out of range [-90, 90] for {body}")
    return True

def haversine_distance(
    lat1: float, lon1: float,
    lat2: float, lon2: float
) -> float:
    """
    Calculates the great-circle distance between two points on Mars using the Haversine formula.

    This is a spherical approximation using MARS_IAU2015_SPHERE_RADIUS_M.
    Results are in meters.
    """
    # Convert degrees to radians
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    lambda1, lambda2 = math.radians(lon1), math.radians(lon2)

    dphi = phi2 - phi1
    dlambda = lambda2 - lambda1

    a = math.sin(dphi / 2.0)**2 + \
        math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0)**2

    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return MARS_IAU2015_SPHERE_RADIUS_M * c
