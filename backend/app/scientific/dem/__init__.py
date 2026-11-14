"""
DEM processing package for AresPath.
Provides coordinate transformations, raster sampling, and coverage verification.
"""

from app.scientific.dem.models import (
    CoverageStatus,
    ProjectedPoint,
    ContinuousPixelPoint,
    ContainingCell,
    DEMCoordinateResult,
)
from app.scientific.dem.transformer import DEMTransformer

__all__ = [
    "CoverageStatus",
    "ProjectedPoint",
    "ContinuousPixelPoint",
    "ContainingCell",
    "DEMCoordinateResult",
    "DEMTransformer",
]
