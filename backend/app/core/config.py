"""
Core configuration and planetary constants for AresPath.
"""

from pathlib import Path

# Mars Mean Volumetric Radius (IAU 2015)
# Associated with IAU:2015:49900 Mars Datum.
# Reference: https://planetarynames.wr.usgs.gov/Page/Planets
MARS_IAU2015_SPHERE_RADIUS_M = 3_396_190.0

API_V1_STR = "/api/v1"
PROJECT_NAME = "AresPath"
VERSION = "0.1.0"


def resolve_dem_path() -> Path:
    """
    Resolves the canonical Jezero DEM raster file across deployment environments:
      1. data/jezero/jezero_ctx_dem_20m.tif (Render Root Directory = 'backend')
      2. backend/data/jezero/jezero_ctx_dem_20m.tif (repository root execution)
      3. data/raw/jezero/jezero_ctx_dem_20m.tif (local archive fallback)
    """
    cwd = Path.cwd()
    backend_root = Path(__file__).resolve().parents[2]
    repo_root = Path(__file__).resolve().parents[3]

    candidates = [
        cwd / "data" / "jezero" / "jezero_ctx_dem_20m.tif",
        backend_root / "data" / "jezero" / "jezero_ctx_dem_20m.tif",
        cwd / "backend" / "data" / "jezero" / "jezero_ctx_dem_20m.tif",
        repo_root / "backend" / "data" / "jezero" / "jezero_ctx_dem_20m.tif",
        repo_root / "data" / "jezero" / "jezero_ctx_dem_20m.tif",
        repo_root / "data" / "raw" / "jezero" / "jezero_ctx_dem_20m.tif",
        cwd / "data" / "raw" / "jezero" / "jezero_ctx_dem_20m.tif",
        backend_root / "data" / "raw" / "jezero" / "jezero_ctx_dem_20m.tif",
    ]

    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()

    return (cwd / "data" / "jezero" / "jezero_ctx_dem_20m.tif").resolve()


def resolve_ortho_path() -> Path:
    """
    Resolves the optical CTX orthomosaic raster file across deployment environments.
    """
    cwd = Path.cwd()
    backend_root = Path(__file__).resolve().parents[2]
    repo_root = Path(__file__).resolve().parents[3]

    candidates = [
        cwd / "data" / "jezero" / "jezero_ctx_orthomosaic_6m.tif",
        backend_root / "data" / "jezero" / "jezero_ctx_orthomosaic_6m.tif",
        cwd / "backend" / "data" / "jezero" / "jezero_ctx_orthomosaic_6m.tif",
        repo_root / "backend" / "data" / "jezero" / "jezero_ctx_orthomosaic_6m.tif",
        repo_root / "data" / "raw" / "jezero" / "jezero_ctx_orthomosaic_6m.tif",
        cwd / "data" / "raw" / "jezero" / "jezero_ctx_orthomosaic_6m.tif",
        backend_root / "data" / "raw" / "jezero" / "jezero_ctx_orthomosaic_6m.tif",
    ]

    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()

    return (cwd / "data" / "jezero" / "jezero_ctx_orthomosaic_6m.tif").resolve()


JEZERO_DEM_PATH = resolve_dem_path()
JEZERO_ORTHO_PATH = resolve_ortho_path()
DATA_DIR = JEZERO_DEM_PATH.parent.parent
