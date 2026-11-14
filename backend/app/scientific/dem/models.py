"""
Pydantic data models for DEM coordinate transformation, pixel indexing,
and geometric/elevation coverage verification.
"""

from __future__ import annotations

from enum import Enum
import math
from typing import Optional
from pydantic import BaseModel, Field, field_validator


def _validate_finite_coordinate(field_name: str, v: object) -> float:
    if isinstance(v, bool):
        raise ValueError(f"{field_name} cannot be a boolean value")
    if not isinstance(v, (int, float)) or not math.isfinite(v):
        raise ValueError(f"{field_name} must be a finite number, got {v}")
    return float(v)


class CoverageStatus(str, Enum):
    """
    Status of a coordinate relative to a DEM raster dataset.
    """
    VALID = "valid"
    OUT_OF_BOUNDS = "out_of_bounds"
    NODATA_COLLAR = "nodata_collar"
    ELEVATION_UNAVAILABLE = "elevation_unavailable"


class ProjectedPoint(BaseModel):
    """
    Point in the projected CRS (e.g. Equirectangular metres).
    """
    x_m: float = Field(..., description="Easting coordinate in metres")
    y_m: float = Field(..., description="Northing coordinate in metres")
    crs_wkt: Optional[str] = Field(None, description="WKT string of projected CRS")

    @field_validator("x_m", "y_m", mode="before")
    @classmethod
    def validate_projected_finite(cls, v: object, info) -> float:
        return _validate_finite_coordinate(info.field_name, v)


class ContinuousPixelPoint(BaseModel):
    """
    Continuous floating-point pixel coordinate in raster space.
    Origin (0.0, 0.0) is the top-left outer corner of cell (0, 0).
    """
    col_cont: float = Field(..., description="Continuous column coordinate (0.0 <= col < width)")
    row_cont: float = Field(..., description="Continuous row coordinate (0.0 <= row < height)")

    @field_validator("col_cont", "row_cont", mode="before")
    @classmethod
    def validate_pixel_finite(cls, v: object, info) -> float:
        return _validate_finite_coordinate(info.field_name, v)


class ContainingCell(BaseModel):
    """
    Discrete integer indices of the containing raster cell (floor of continuous coordinates).
    """
    col: int = Field(..., description="Discrete column index (floor(col_cont))")
    row: int = Field(..., description="Discrete row index (floor(row_cont))")

    @field_validator("col", "row", mode="before")
    @classmethod
    def validate_cell_int(cls, v: object, info) -> int:
        if isinstance(v, bool) or not isinstance(v, int):
            raise ValueError(f"{info.field_name} must be an integer, got {v}")
        return v


class DEMCoordinateResult(BaseModel):
    """
    Structured outcome of transforming geographic coordinates through a DEM raster.

    Separates:
    - Geometric coverage: whether the continuous coordinates lie inside [0, width) x [0, height).
    - Containing cell validity: whether the discrete raster cell contains a non-NoData finite elevation.
    - Bilinear elevation: strictly separated from containing cell elevation.
    """
    lon_deg: float = Field(..., description="Input longitude in positive-east degrees [-180, 180]")
    lat_deg: float = Field(..., description="Input planetocentric latitude in degrees [-90, 90]")
    projected: ProjectedPoint = Field(..., description="Projected coordinates in metres")
    pixel_cont: ContinuousPixelPoint = Field(..., description="Continuous pixel coordinates")
    containing_cell: Optional[ContainingCell] = Field(None, description="Discrete cell indices if geometrically inside")
    geometric_coverage: bool = Field(..., description="True if continuous pixel is within half-open bounds [0, W) x [0, H)")
    elevation_valid: bool = Field(..., description="True if containing cell contains valid non-NoData finite elevation")
    containing_elevation_m: Optional[float] = Field(None, description="Elevation of containing cell in metres, or None if invalid")
    bilinear_elevation_m: Optional[float] = Field(None, description="Bilinear interpolated elevation; None in Milestone 1")
    status: CoverageStatus = Field(..., description="Machine-readable coverage classification")
    message: Optional[str] = Field(None, description="Diagnostic details")

    @field_validator("lon_deg", "lat_deg", mode="before")
    @classmethod
    def validate_geographic_finite(cls, v: object, info) -> float:
        return _validate_finite_coordinate(info.field_name, v)
