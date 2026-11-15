"""
Service layer for AresPath elevation sampling.
Provides region-isolated DEM resolution, identity verification, schema mapping,
and legacy Jezero DEM service compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any, Mapping, Optional, Sequence

import numpy as np
import rasterio
from rasterio.errors import RasterioError

try:
    from pyproj import CRS, Transformer
except ImportError:
    CRS = None
    Transformer = None

from app.models.schemas import ElevationSampleResponse
from app.scientific.dem.transformer import DEMTransformer
from app.core.config import resolve_dem_path, JEZERO_DEM_PATH

_resolve_default_dem_path = resolve_dem_path

# Technical debt note: SUPPORTED_REGIONS currently duplicates existing endpoint
# catalogues (_REGIONS in regions.py, REGION_REGISTRY in routes.py, _KNOWN_REGIONS in layers.py)
# and may be centralized in a future dedicated core configuration refactor.
SUPPORTED_REGIONS: frozenset[str] = frozenset(["jezero_crater", "gale_crater"])


@dataclass(frozen=True)
class RegionalDEM:
    """
    Explicit binding between a canonical Mars region identifier and its
    associated DEMTransformer instance.
    """
    region_id: str
    transformer: DEMTransformer


class RegionNotFoundError(KeyError):
    """Raised when a requested region_id is not in SUPPORTED_REGIONS."""
    def __init__(self, region_id: str, supported: Optional[Sequence[str]] = None):
        super().__init__(f"Region '{region_id}' is not recognised.")
        self.region_id = region_id
        self.supported = list(supported or SUPPORTED_REGIONS)


class DEMUnavailableError(RuntimeError):
    """Raised when the elevation dataset cannot be opened or loaded."""
    def __init__(self, message_or_region_id: str = ""):
        if " " in message_or_region_id or not message_or_region_id:
            super().__init__(message_or_region_id or "The elevation dataset is not currently available.")
            self.region_id = None
        else:
            super().__init__(f"The elevation dataset for region '{message_or_region_id}' is not currently loaded.")
            self.region_id = message_or_region_id


class RegionAssociationError(ValueError):
    """Raised when a mapping key does not match the bound RegionalDEM.region_id."""
    def __init__(self, key: str, bound_region_id: str):
        super().__init__(
            f"Regional DEM association mismatch: mapping key '{key}' does not match entry region_id '{bound_region_id}'."
        )
        self.key = key
        self.bound_region_id = bound_region_id


def sample_elevation(
    region_id: str,
    lon_deg: float,
    lat_deg: float,
    regional_dems: Mapping[str, RegionalDEM],
) -> ElevationSampleResponse:
    """
    Samples nearest-neighbor point elevation for a Mars surface coordinate.

    Enforces two-factor region-to-DEM verification before delegating to the transformer:
    1. Validates that region_id belongs to SUPPORTED_REGIONS.
    2. Resolves regional_dems.get(region_id).
    3. Validates entry availability (raises DEMUnavailableError if absent or transformer is None).
    4. Validates mapping key and RegionalDEM.region_id equality (raises RegionAssociationError).
    5. Samples coordinates through dem_entry.transformer.transform_coordinate(lon_deg, lat_deg).
    """
    if region_id not in SUPPORTED_REGIONS:
        raise RegionNotFoundError(region_id)

    dem_entry = regional_dems.get(region_id)
    if dem_entry is None or dem_entry.transformer is None:
        raise DEMUnavailableError(region_id)

    if dem_entry.region_id != region_id:
        raise RegionAssociationError(key=region_id, bound_region_id=dem_entry.region_id)

    result = dem_entry.transformer.transform_coordinate(lon_deg=lon_deg, lat_deg=lat_deg)

    return ElevationSampleResponse(
        region_id=region_id,
        latitude=result.lat_deg,
        longitude=result.lon_deg,
        status=result.status,
        geometric_coverage=result.geometric_coverage,
        elevation_valid=result.elevation_valid,
        elevation_m=result.containing_elevation_m,
        sampling_method="nearest_neighbor",
        message=result.message,
    )


class JezeroDEMService:
    """Reads real elevation samples from the Jezero CTX DEM."""

    def __init__(self, raster_path: Optional[Path] = None) -> None:
        self.raster_path = Path(raster_path) if raster_path is not None else _resolve_default_dem_path()
        self._dataset = None
        self._transformer = None
        self._lock = RLock()

    def open(self) -> None:
        """Open the raster once and prepare its CRS transformation."""
        with self._lock:
            if self._dataset is not None:
                return

            if not self.raster_path.is_file():
                # Re-check resolution in case files were downloaded after init
                self.raster_path = _resolve_default_dem_path()
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

                if Transformer is not None and CRS is not None:
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
                else:
                    class _MarsTransformerFallback:
                        def transform(self, lon: float, lat: float) -> tuple[float, float]:
                            import math
                            R = 3396190.0
                            cos_ts = math.cos(math.radians(18.4663))
                            x = R * cos_ts * math.radians(lon)
                            y = R * math.radians(lat)
                            return x, y
                    self._transformer = _MarsTransformerFallback()

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
