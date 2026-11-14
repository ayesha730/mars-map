"""
Service for transforming coordinates between geographic (Mars 2000 Sphere),
projected raster CRS (Equirectangular), and continuous pixel space.

Also determines half-open geometric coverage and discrete containing-cell
elevation validity using Rasterio masks and explicit NoData checks.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Optional, Tuple, Union

import affine
import rasterio
from rasterio.crs import CRS
from rasterio.io import DatasetReader
from rasterio.warp import transform as warp_transform
from rasterio.windows import Window

from app.scientific.geodesy import validate_coordinates
from app.scientific.dem.models import (
    ContainingCell,
    ContinuousPixelPoint,
    CoverageStatus,
    DEMCoordinateResult,
    ProjectedPoint,
)


class DEMTransformer:
    """
    Handles coordinate transformations and coverage checks for a DEM raster.

    Coordinates:
    - Geographic: Planetocentric latitude [-90, 90], positive-east longitude [-180, 180] (degrees).
    - Projected: Easting (X) and Northing (Y) in metres according to the raster CRS.
    - Continuous pixel: Floating-point (col_cont, row_cont) with origin (0.0, 0.0) at the
      top-left outer corner of cell (0, 0).
    """

    def __init__(
        self,
        crs: CRS,
        transform: affine.Affine,
        width: int,
        height: int,
        nodata: Optional[float] = None,
        dataset: Optional[DatasetReader] = None,
        owns_dataset: bool = False,
    ) -> None:
        if crs is None or not isinstance(crs, CRS):
            raise ValueError(f"Raster CRS must be a valid rasterio.crs.CRS instance, got {crs!r}")
        if crs.geodetic_crs is None:
            raise ValueError(f"Raster CRS must have an associated geodetic CRS: {crs!r}")

        if transform is None or not isinstance(transform, affine.Affine):
            raise ValueError(f"Raster transform must be a valid affine.Affine instance, got {transform!r}")
        if transform.is_degenerate:
            raise ValueError("Raster affine transform is degenerate and cannot be inverted")

        if isinstance(width, bool) or not isinstance(width, int) or width <= 0:
            raise ValueError(f"Raster width must be a positive integer, got {width!r}")
        if isinstance(height, bool) or not isinstance(height, int) or height <= 0:
            raise ValueError(f"Raster height must be a positive integer, got {height!r}")

        self.crs = crs
        self.geodetic_crs = crs.geodetic_crs
        self.transform = transform
        self.inv_transform = ~transform
        self.width = width
        self.height = height
        self.nodata = nodata
        self.dataset = dataset
        self._owns_dataset = owns_dataset
        self._closed = False

    @property
    def is_closed(self) -> bool:
        """
        Indicates whether this transformer or its attached dataset is closed.
        """
        if self._closed:
            return True
        if self.dataset is not None and self.dataset.closed:
            return True
        return False

    def close(self) -> None:
        """
        Closes the underlying raster dataset if and only if this transformer
        owns it (e.g. opened via from_file). If the dataset was supplied externally
        via from_dataset, ownership remains with the caller and the external
        dataset is left open.
        """
        if self._closed:
            return
        self._closed = True
        if self._owns_dataset and self.dataset is not None and not self.dataset.closed:
            self.dataset.close()

    def __enter__(self) -> DEMTransformer:
        if self._closed:
            raise RuntimeError("Cannot enter context: DEMTransformer is already closed")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    @classmethod
    def from_dataset(cls, dataset: DatasetReader) -> DEMTransformer:
        """
        Creates a transformer directly from an open Rasterio DatasetReader.
        Dataset ownership remains strictly with the caller; this transformer
        will not close or take exclusive ownership of the provided dataset.
        """
        if dataset is None or not isinstance(dataset, DatasetReader):
            raise ValueError(f"dataset must be an open rasterio.io.DatasetReader, got {dataset!r}")
        if dataset.closed:
            raise ValueError("dataset must be an open rasterio.io.DatasetReader, but it is closed")

        return cls(
            crs=dataset.crs,
            transform=dataset.transform,
            width=dataset.width,
            height=dataset.height,
            nodata=dataset.nodata,
            dataset=dataset,
            owns_dataset=False,
        )

    @classmethod
    def from_file(cls, filepath: Union[str, Path]) -> DEMTransformer:
        """
        Opens a GeoTIFF and creates a transformer from its metadata and open dataset.
        The opened dataset remains open until explicitly closed via close() or
        by using this transformer as a context manager.
        """
        ds = rasterio.open(filepath)
        return cls(
            crs=ds.crs,
            transform=ds.transform,
            width=ds.width,
            height=ds.height,
            nodata=ds.nodata,
            dataset=ds,
            owns_dataset=True,
        )

    def geographic_to_projected(self, lon_deg: float, lat_deg: float) -> Tuple[float, float]:
        """
        Transforms validated Mars geographic coordinates to projected metres.
        Longitude is mapped to X (Easting) and Latitude to Y (Northing).
        """
        validate_coordinates(lat=lat_deg, lon=lon_deg, lon_domain="[-180, 180]")
        xs, ys = warp_transform(self.geodetic_crs, self.crs, [lon_deg], [lat_deg])
        return xs[0], ys[0]

    def projected_to_geographic(self, x_m: float, y_m: float) -> Tuple[float, float]:
        """
        Transforms projected metres back to geographic coordinates.
        Rejects Boolean, non-numeric, and non-finite X/Y coordinates.
        Returns (lon_deg, lat_deg).
        """
        if isinstance(x_m, bool) or not isinstance(x_m, (int, float)) or not math.isfinite(x_m):
            raise ValueError(f"Projected X coordinate must be a finite number, got {x_m!r}")
        if isinstance(y_m, bool) or not isinstance(y_m, (int, float)) or not math.isfinite(y_m):
            raise ValueError(f"Projected Y coordinate must be a finite number, got {y_m!r}")
        lons, lats = warp_transform(self.crs, self.geodetic_crs, [x_m], [y_m])
        return lons[0], lats[0]

    def projected_to_pixel(self, x_m: float, y_m: float) -> Tuple[float, float]:
        """
        Converts projected metres to continuous pixel coordinates (col_cont, row_cont)
        using the inverse affine transform.
        Rejects Boolean, non-numeric, and non-finite X/Y coordinates.
        """
        if isinstance(x_m, bool) or not isinstance(x_m, (int, float)) or not math.isfinite(x_m):
            raise ValueError(f"Projected X coordinate must be a finite number, got {x_m!r}")
        if isinstance(y_m, bool) or not isinstance(y_m, (int, float)) or not math.isfinite(y_m):
            raise ValueError(f"Projected Y coordinate must be a finite number, got {y_m!r}")
        col_cont, row_cont = self.inv_transform @ (x_m, y_m)
        return col_cont, row_cont

    def pixel_to_projected(self, col_cont: float, row_cont: float) -> Tuple[float, float]:
        """
        Converts continuous pixel coordinates to projected metres using the affine transform.
        Rejects Boolean, non-numeric, and non-finite pixel coordinates.
        """
        if isinstance(col_cont, bool) or not isinstance(col_cont, (int, float)) or not math.isfinite(col_cont):
            raise ValueError(f"Continuous column coordinate must be a finite number, got {col_cont!r}")
        if isinstance(row_cont, bool) or not isinstance(row_cont, (int, float)) or not math.isfinite(row_cont):
            raise ValueError(f"Continuous row coordinate must be a finite number, got {row_cont!r}")
        x_m, y_m = self.transform @ (col_cont, row_cont)
        return x_m, y_m

    def geographic_to_pixel(self, lon_deg: float, lat_deg: float) -> Tuple[float, float]:
        """
        Converts geographic coordinates directly to continuous pixel coordinates.
        """
        x_m, y_m = self.geographic_to_projected(lon_deg, lat_deg)
        return self.projected_to_pixel(x_m, y_m)

    def pixel_to_geographic(self, col_cont: float, row_cont: float) -> Tuple[float, float]:
        """
        Converts continuous pixel coordinates directly to geographic coordinates.
        """
        x_m, y_m = self.pixel_to_projected(col_cont, row_cont)
        return self.projected_to_geographic(x_m, y_m)

    def is_geometrically_covered(self, col_cont: float, row_cont: float) -> bool:
        """
        Evaluates half-open geometric coverage:
        0.0 <= col_cont < width  and  0.0 <= row_cont < height.

        Explicitly rejects Boolean, non-numeric, and non-finite coordinates
        (NaN, +inf, -inf) by returning False.
        """
        if isinstance(col_cont, bool) or isinstance(row_cont, bool):
            return False
        if not isinstance(col_cont, (int, float)) or not isinstance(row_cont, (int, float)):
            return False
        if not math.isfinite(col_cont) or not math.isfinite(row_cont):
            return False
        return 0.0 <= col_cont < self.width and 0.0 <= row_cont < self.height

    def is_four_neighbor_eligible_geometric(self, col_cont: float, row_cont: float) -> bool:
        """
        Evaluates whether continuous coordinates fall within the general
        geometric four-neighbor eligibility region:
        0.5 <= col_cont < (width - 0.5)  and  0.5 <= row_cont < (height - 0.5).

        Note: If outer boundary cells are NoData (as in the Jezero CTX DEM),
        the effective valid eligibility region is narrower.
        """
        if isinstance(col_cont, bool) or isinstance(row_cont, bool):
            return False
        if not isinstance(col_cont, (int, float)) or not isinstance(row_cont, (int, float)):
            return False
        if not math.isfinite(col_cont) or not math.isfinite(row_cont):
            return False
        return 0.5 <= col_cont < (self.width - 0.5) and 0.5 <= row_cont < (self.height - 0.5)

    def get_containing_cell(self, col_cont: float, row_cont: float) -> Optional[ContainingCell]:
        """
        Computes discrete containing cell indices using floor:
        c = floor(col_cont), r = floor(row_cont).
        Returns None if continuous coordinates are outside half-open geometric bounds.
        """
        if not self.is_geometrically_covered(col_cont, row_cont):
            return None
        return ContainingCell(col=math.floor(col_cont), row=math.floor(row_cont))

    def transform_coordinate(self, lon_deg: float, lat_deg: float) -> DEMCoordinateResult:
        """
        End-to-end evaluation of a geographic point:
        1. Validates Mars coordinates.
        2. Transforms to projected metres.
        3. Converts to continuous pixel coordinates.
        4. Evaluates half-open geometric bounds.
        5. Evaluates containing cell elevation validity (via mask, NoData, finite checks).
        """
        if self._closed:
            raise RuntimeError("Cannot transform coordinates: DEMTransformer is closed")

        # Validate coordinates (raises ValueError if non-finite, boolean, or out of range)
        validate_coordinates(lat=lat_deg, lon=lon_deg, lon_domain="[-180, 180]")

        # 1. Project
        x_m, y_m = self.geographic_to_projected(lon_deg, lat_deg)
        proj_pt = ProjectedPoint(x_m=x_m, y_m=y_m, crs_wkt=self.crs.to_wkt())

        # 2. Pixel coordinates
        col_cont, row_cont = self.projected_to_pixel(x_m, y_m)
        pixel_pt = ContinuousPixelPoint(col_cont=col_cont, row_cont=row_cont)

        # 3. Geometric bounds check (half-open)
        geom_covered = self.is_geometrically_covered(col_cont, row_cont)
        if not geom_covered:
            return DEMCoordinateResult(
                lon_deg=lon_deg,
                lat_deg=lat_deg,
                projected=proj_pt,
                pixel_cont=pixel_pt,
                containing_cell=None,
                geometric_coverage=False,
                elevation_valid=False,
                containing_elevation_m=None,
                bilinear_elevation_m=None,
                status=CoverageStatus.OUT_OF_BOUNDS,
                message="Coordinates lie outside the raster geometric bounds",
            )

        # 4. Containing cell
        c_cell = math.floor(col_cont)
        r_cell = math.floor(row_cont)
        cell = ContainingCell(col=c_cell, row=r_cell)

        # 5. Check elevation validity if dataset is attached
        if self.dataset is None:
            return DEMCoordinateResult(
                lon_deg=lon_deg,
                lat_deg=lat_deg,
                projected=proj_pt,
                pixel_cont=pixel_pt,
                containing_cell=cell,
                geometric_coverage=True,
                elevation_valid=False,
                containing_elevation_m=None,
                bilinear_elevation_m=None,
                status=CoverageStatus.ELEVATION_UNAVAILABLE,
                message="Raster dataset not attached; elevation sampling unavailable",
            )

        if self.dataset.closed:
            raise RuntimeError("Cannot sample elevation: underlying raster dataset is closed")

        # Read containing cell value and mask
        win = Window(c_cell, r_cell, 1, 1)
        mask_val = self.dataset.read_masks(1, window=win)[0, 0]
        val = float(self.dataset.read(1, window=win)[0, 0])

        is_mask_valid = (mask_val != 0)
        is_finite = math.isfinite(val)
        is_not_nodata = (self.nodata is None or val != self.nodata)

        if is_mask_valid and is_finite and is_not_nodata:
            return DEMCoordinateResult(
                lon_deg=lon_deg,
                lat_deg=lat_deg,
                projected=proj_pt,
                pixel_cont=pixel_pt,
                containing_cell=cell,
                geometric_coverage=True,
                elevation_valid=True,
                containing_elevation_m=val,
                bilinear_elevation_m=None,
                status=CoverageStatus.VALID,
                message=None,
            )
        else:
            return DEMCoordinateResult(
                lon_deg=lon_deg,
                lat_deg=lat_deg,
                projected=proj_pt,
                pixel_cont=pixel_pt,
                containing_cell=cell,
                geometric_coverage=True,
                elevation_valid=False,
                containing_elevation_m=None,
                bilinear_elevation_m=None,
                status=CoverageStatus.NODATA_COLLAR,
                message="Containing pixel lies in a NoData or masked collar region",
            )
