from pathlib import Path
from threading import RLock
from typing import Any

import numpy as np
import rasterio
from rasterio.windows import Window
try:
    from pyproj import Transformer
except ImportError:
    Transformer = None


class SlopeDEMUnavailableError(RuntimeError):
    pass


class JezeroSlopeService:
    """
    Calculates terrain gradient using a 3x3 Horn neighborhood.

    Elevation units are deliberately treated as unverified.
    The service therefore reports gradient in elevation-units per
    horizontal metre, but does not claim a slope angle in degrees.
    """

    def __init__(self) -> None:
        project_root = Path(__file__).resolve().parents[3]
        self.dem_path = (
            project_root / "data" / "jezero" / "jezero_ctx_dem_20m.tif"
        )

        self._dataset = None
        self._transformer = None
        self._lock = RLock()

    def _open(self) -> None:
        if self._dataset is not None:
            return

        if not self.dem_path.exists():
            candidate = self.dem_path.parent.parent / "raw" / "jezero" / "jezero_ctx_dem_20m.tif"
            if candidate.exists():
                self.dem_path = candidate
            else:
                raise SlopeDEMUnavailableError(
                    f"Jezero DEM not found: {self.dem_path}"
                )

        try:
            self._dataset = rasterio.open(self.dem_path)

            if self._dataset.crs is None:
                raise SlopeDEMUnavailableError(
                    "The Jezero DEM has no coordinate reference system."
                )

            if Transformer is not None:
                geodetic_crs = self._dataset.crs.geodetic_crs
                self._transformer = Transformer.from_crs(
                    geodetic_crs,
                    self._dataset.crs,
                    always_xy=True,
                )
            else:
                class _MarsSlopeTransformerFallback:
                    def transform(self, lon: float, lat: float) -> tuple[float, float]:
                        import math
                        R = 3396190.0
                        cos_ts = math.cos(math.radians(18.4663))
                        x = R * cos_ts * math.radians(lon)
                        y = R * math.radians(lat)
                        return x, y
                self._transformer = _MarsSlopeTransformerFallback()

        except Exception:
            if self._dataset is not None:
                self._dataset.close()
                self._dataset = None
            raise

    def close(self) -> None:
        with self._lock:
            if self._dataset is not None:
                self._dataset.close()
                self._dataset = None
                self._transformer = None

    def sample(self, latitude: float, longitude: float) -> dict[str, Any]:
        if not np.isfinite(latitude) or not np.isfinite(longitude):
            raise ValueError("Latitude and longitude must be finite.")

        if not -90 <= latitude <= 90:
            raise ValueError("Latitude must be between -90 and 90 degrees.")

        if not -180 <= longitude <= 180:
            raise ValueError("Longitude must be between -180 and 180 degrees.")

        with self._lock:
            self._open()

            x, y = self._transformer.transform(longitude, latitude)

            dataset = self._dataset
            inverse = ~dataset.transform
            pixel_col, pixel_row = inverse * (x, y)

            col = int(np.floor(pixel_col))
            row = int(np.floor(pixel_row))

            base = {
                "region_id": "jezero_crater",
                "latitude": float(latitude),
                "longitude": float(longitude),
                "pixel_row": row,
                "pixel_column": col,
                "method": "horn_3x3",
                "horizontal_resolution_m": [
                    abs(float(dataset.transform.a)),
                    abs(float(dataset.transform.e)),
                ],
                "vertical_units": "unverified",
                "slope_degrees": None,
            }

            if (
                row < 1
                or col < 1
                or row >= dataset.height - 1
                or col >= dataset.width - 1
            ):
                return {
                    **base,
                    "status": "insufficient_neighborhood",
                    "gradient_magnitude": None,
                    "message": (
                        "A complete 3x3 DEM neighborhood is not available "
                        "at this coordinate."
                    ),
                }

            # Horn's method assumes an axis-aligned raster grid.
            transform = dataset.transform
            if abs(transform.b) > 1e-9 or abs(transform.d) > 1e-9:
                raise SlopeDEMUnavailableError(
                    "Rotated DEM grids are not supported by this slope service."
                )

            pixel_width = abs(float(transform.a))
            pixel_height = abs(float(transform.e))

            if pixel_width <= 0 or pixel_height <= 0:
                raise SlopeDEMUnavailableError(
                    "The DEM has invalid pixel dimensions."
                )

            window = Window(col - 1, row - 1, 3, 3)
            neighborhood = dataset.read(
                1,
                window=window,
                masked=True,
            )

            values = np.asarray(neighborhood.data, dtype=np.float64)
            invalid = np.ma.getmaskarray(neighborhood)

            if invalid.any() or not np.isfinite(values).all():
                return {
                    **base,
                    "status": "nodata_neighborhood",
                    "gradient_magnitude": None,
                    "message": (
                        "The surrounding 3x3 neighborhood contains "
                        "NoData or non-finite elevation cells. "
                        "Slope was not calculated."
                    ),
                }

            z1, z2, z3 = values[0]
            z4, z5, z6 = values[1]
            z7, z8, z9 = values[2]

            # Horn 3x3 weighted finite-difference gradients.
            dz_dx = (
                (z3 + 2 * z6 + z9)
                - (z1 + 2 * z4 + z7)
            ) / (8.0 * pixel_width)

            dz_dy = (
                (z1 + 2 * z2 + z3)
                - (z7 + 2 * z8 + z9)
            ) / (8.0 * pixel_height)

            gradient = float(np.hypot(dz_dx, dz_dy))

            return {
                **base,
                "status": "valid",
                "center_elevation_raw": float(z5),
                "gradient_x_elevation_units_per_m": float(dz_dx),
                "gradient_y_elevation_units_per_m": float(dz_dy),
                "gradient_magnitude": gradient,
                "message": (
                    "Terrain gradient calculated from the real Jezero "
                    "CTX DEM using a 3x3 Horn neighborhood. Slope angle "
                    "is withheld until vertical elevation units are verified."
                ),
            }


jezero_slope_service = JezeroSlopeService()