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

# Regional DEM dataset storage
DATA_DIR = Path(__file__).resolve().parents[3] / "data"
JEZERO_DEM_PATH = DATA_DIR / "raw" / "jezero" / "jezero_ctx_dem_20m.tif"
JEZERO_ORTHO_PATH = DATA_DIR / "raw" / "jezero" / "jezero_ctx_orthomosaic_6m.tif"
