from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import Any

import numpy as np
import rasterio
from pyproj import CRS, Transformer
from rasterio.errors import RasterioError


PROJECT_ROOT = Path(__file__).resolve().parents[3]
JEZERO_DEM_PATH = (
    PROJECT_ROOT / "data" / "jezero" / "jezero_ctx_dem_20m.tif"
)


class DEMUnavailableError(RuntimeError):
    """Raised when the Jezero elevation dataset cannot be opened."""


class JezeroDEMService:
    """Reads real elevation samples from the Jezero CTX DEM."""

    def __init__(self, raster_path: Path = JEZERO_DEM_PATH) -> None:
        self.raster_path = Path(raster_path)
        self._dataset = None
        self._transformer = None
        self._lock = RLock()

    def open(self) -> None:
        """Open the raster once and prepare its CRS transformation."""
        with self._lock:
            if self._dataset is not None:
                return

            if not self.raster_path.is_file():
                raise DEMUnavailableError(
                    f"Jezero DEM file not found: {self.raster_path}"
                )

            try:
                dataset = rasterio.open(self.raster_path)

                if dataset.crs is None:
                    dataset.close()
                    raise DEMUnavailableError(
                        "The Jezero DEM has no coordinate reference system."
                    )

                projected_crs = CRS.from_wkt(dataset.crs.to_wkt())
                geographic_crs = projected_crs.geodetic_crs

                if geographic_crs is None:
                    dataset.close()
                    raise DEMUnavailableError(
                        "The DEM's geographic CRS could not be identified."
                    )

                self._transformer = Transformer.from_crs(
                    geographic_crs,
                    projected_crs,
                    always_xy=True,
                )
                self._dataset = dataset

            except (RasterioError, ValueError) as exc:
                raise DEMUnavailableError(
                    f"Could not open Jezero DEM: {exc}"
                ) from exc

    def close(self) -> None:
        with self._lock:
            if self._dataset is not None:
                self._dataset.close()
                self._dataset = None
                self._transformer = None

    def sample(self, latitude: float, longitude: float) -> dict[str, Any]:
        """Return the elevation at the raster cell containing a Mars point."""
        if not np.isfinite(latitude) or not np.isfinite(longitude):
            raise ValueError("Coordinates must be finite numbers.")

        if not -90 <= latitude <= 90:
            raise ValueError("Latitude must be between -90 and 90 degrees.")

        if not -180 <= longitude <= 180:
            raise ValueError("Longitude must be between -180 and 180 degrees.")

        with self._lock:
            self.open()

            dataset = self._dataset
            transformer = self._transformer

            # always_xy=True means longitude first, latitude second.
            x, y = transformer.transform(longitude, latitude)

            if not np.isfinite(x) or not np.isfinite(y):
                raise ValueError(
                    "The coordinate could not be transformed into the DEM CRS."
                )

            row, col = dataset.index(x, y)

            result = {
                "region_id": "jezero_crater",
                "latitude": float(latitude),
                "longitude": float(longitude),
                "projected_x_m": float(x),
                "projected_y_m": float(y),
                "pixel_row": int(row),
                "pixel_column": int(col),
                "resolution_m": list(dataset.res),
                "sampling_method": "nearest_neighbor_containing_cell",
                "coordinate_reference": (
                    "Mars 2000 Sphere / Jezero Equirectangular"
                ),
            }

            if row < 0 or row >= dataset.height or col < 0 or col >= dataset.width:
                return {
                    **result,
                    "status": "out_of_bounds",
                    "geometric_coverage": False,
                    "elevation_valid": False,
                    "elevation_m": None,
                    "message": "Coordinate falls outside the DEM coverage.",
                }

            mask = dataset.read_masks(
                1,
                window=((row, row + 1), (col, col + 1)),
            )

            if mask[0, 0] == 0:
                return {
                    **result,
                    "status": "nodata",
                    "geometric_coverage": True,
                    "elevation_valid": False,
                    "elevation_m": None,
                    "message": "The DEM cell has no valid elevation value.",
                }

            value = float(
                dataset.read(
                    1,
                    window=((row, row + 1), (col, col + 1)),
                )[0, 0]
            )

            if not np.isfinite(value) or (
                dataset.nodata is not None and value == dataset.nodata
            ):
                return {
                    **result,
                    "status": "nodata",
                    "geometric_coverage": True,
                    "elevation_valid": False,
                    "elevation_m": None,
                    "message": "The DEM cell has no valid elevation value.",
                }

            return {
                **result,
                "status": "valid",
                "geometric_coverage": True,
                "elevation_valid": True,
                "elevation_m": value,
                "message": "Elevation sampled from the Jezero CTX DEM.",
            }


# Shared service instance: the raster is not reopened for every request.
jezero_dem_service = JezeroDEMService()