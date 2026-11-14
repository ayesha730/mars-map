import math
from typing import Tuple
from app.core.config import MARS_IAU2015_SPHERE_RADIUS_M

def normalize_longitude(lon: float, wrap_to_360: bool = False) -> float:
    """
    Normalizes longitude to the confirmed Mars convention [-180, 180] (default)
    or legacy [0, 360).

    Default: Positive-East [-180, 180].
    Legacy mode [0, 360) must be explicitly requested with wrap_to_360=True.

    Boundary behavior:
    - In [-180, 180], both -180 and +180 map to the canonical positive-east
      antimeridian representation (+180.0).

    Rejects non-finite values (NaN, infinity) and booleans by raising ValueError.
    """
    if isinstance(lon, bool):
        raise ValueError(f"Longitude cannot be a boolean value, got {lon}")
    if not isinstance(lon, (int, float)) or not math.isfinite(lon):
        raise ValueError(f"Longitude must be a finite number, got {lon}")

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
    lon_domain: str = "[-180, 180]",
    angular_unit: str = "Degrees"
) -> bool:
    """
    Validates Mars coordinate constraints.
    - Coordinates must be finite numbers (rejects Booleans, NaN, and infinity).
    - Latitude must be in [-90, 90].
    - Longitude must be in [-180, 180] by default (Positive-East).
      If legacy [0, 360) is explicitly requested, validates against [0, 360).
    - Rejects unsupported longitude domains.
    Does not silently normalize invalid coordinates.
    """
    if isinstance(lat, bool):
        raise ValueError(f"Latitude cannot be a boolean value, got {lat}")
    if not isinstance(lat, (int, float)) or not math.isfinite(lat):
        raise ValueError(f"Latitude must be a finite number, got {lat}")

    if isinstance(lon, bool):
        raise ValueError(f"Longitude cannot be a boolean value, got {lon}")
    if not isinstance(lon, (int, float)) or not math.isfinite(lon):
        raise ValueError(f"Longitude must be a finite number, got {lon}")

    if not -90.0 <= lat <= 90.0:
        raise ValueError(f"Latitude {lat} out of range [-90, 90] for {body}")

    if lon_domain == "[0, 360)":
        if not (0.0 <= lon < 360.0):
            raise ValueError(f"Longitude {lon} out of range [0, 360) for {body}")
    elif lon_domain in ("[-180, 180]", "-180_to_180"):
        if not (-180.0 <= lon <= 180.0):
            raise ValueError(f"Longitude {lon} out of range [-180, 180] for {body}")
    else:
        raise ValueError(f"Unsupported longitude domain: {lon_domain}")

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
