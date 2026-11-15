"""
Unit and regression tests for AresPath elevation service layer.

Covers:
1. Valid Jezero sampling.
2. Valid Gale sampling using a distinct synthetic raster and its own projection.
3. NoData collar.
4. Out-of-bounds coordinate.
5. Unknown region, proving no transformer is called.
6. Known region with no loaded DEM.
7. Mismatched mapping key and RegionalDEM.region_id, proving zero calls to transform_coordinate.
8. Closed transformer.
9. Boolean, NaN, positive infinity, negative infinity, and out-of-range coordinates.
10. M2-A response consistency and public-schema boundaries.
"""

from unittest.mock import MagicMock
import math
import numpy as np
from pathlib import Path
import pytest
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_origin

from app.models.schemas import ElevationSampleResponse
from app.scientific.dem.models import CoverageStatus
from app.scientific.dem.transformer import DEMTransformer
from app.scientific.dem.service import (
    RegionalDEM,
    SUPPORTED_REGIONS,
    RegionNotFoundError,
    DEMUnavailableError,
    RegionAssociationError,
    sample_elevation,
)

# Verified Jezero CTX DEM CRS WKT (standard parallel 18.4663 deg N)
JEZERO_CRS_WKT = (
    'PROJCS["Jezero_Crater_Projection",'
    'GEOGCS["GCS_Mars_2000_Sphere",'
    'DATUM["Mars_2000_(Sphere)",'
    'SPHEROID["Mars_2000_Sphere",3396190,0]],'
    'PRIMEM["Reference_Meridian",0],'
    'UNIT["degree",0.0174532925199433,AUTHORITY["EPSG","9122"]]],'
    'PROJECTION["Equirectangular"],'
    'PARAMETER["standard_parallel_1",18.4663],'
    'PARAMETER["central_meridian",0],'
    'PARAMETER["false_easting",0],'
    'PARAMETER["false_northing",0],'
    'UNIT["metre",1,AUTHORITY["EPSG","9001"]],'
    'AXIS["Easting",EAST],'
    'AXIS["Northing",NORTH]]'
)

# Gale Crater Projection WKT (standard parallel -5.36 deg S, Mars sphere 3,396,190 m)
GALE_CRS_WKT = (
    'PROJCS["Gale_Crater_Projection",'
    'GEOGCS["GCS_Mars_2000_Sphere",'
    'DATUM["Mars_2000_(Sphere)",'
    'SPHEROID["Mars_2000_Sphere",3396190,0]],'
    'PRIMEM["Reference_Meridian",0],'
    'UNIT["degree",0.0174532925199433,AUTHORITY["EPSG","9122"]]],'
    'PROJECTION["Equirectangular"],'
    'PARAMETER["standard_parallel_1",-5.36],'
    'PARAMETER["central_meridian",0],'
    'PARAMETER["false_easting",0],'
    'PARAMETER["false_northing",0],'
    'UNIT["metre",1,AUTHORITY["EPSG","9001"]],'
    'AXIS["Easting",EAST],'
    'AXIS["Northing",NORTH]]'
)

NODATA_VALUE = -3.4028234663852886e+38


@pytest.fixture
def jezero_synthetic_dem(tmp_path):
    """
    Creates a 10x10 synthetic GeoTIFF for Jezero Crater with 20m resolution.
    Returns (DEMTransformer, numpy.ndarray data array).
    """
    tif_path = tmp_path / "synthetic_jezero_10x10.tif"
    crs = CRS.from_wkt(JEZERO_CRS_WKT)
    transform = from_origin(4329000.0, 1143420.0, 20.0, 20.0)

    data = np.full((10, 10), -2500.0, dtype=np.float32)
    for r in range(10):
        for c in range(10):
            data[r, c] = -2500.0 + (r * 10.0) + c

    # Jezero boundary NoData pattern
    data[0, :] = NODATA_VALUE   # Top row
    data[9, :] = NODATA_VALUE   # Bottom row
    data[:, 9] = NODATA_VALUE   # Right column
    data[0, 0] = NODATA_VALUE   # Corner

    with rasterio.open(
        tif_path,
        "w",
        driver="GTiff",
        height=10,
        width=10,
        count=1,
        dtype="float32",
        crs=crs,
        transform=transform,
        nodata=NODATA_VALUE,
    ) as dst:
        dst.write(data, 1)

    ds = rasterio.open(tif_path)
    tf = DEMTransformer.from_dataset(ds)
    return tf, data, ds


@pytest.fixture
def gale_synthetic_dem(tmp_path):
    """
    Creates a distinct 10x10 synthetic GeoTIFF for Gale Crater with its own
    projection (standard parallel -5.36) and distinct elevation gradient (-4500 m floor).
    Returns (DEMTransformer, numpy.ndarray data array).
    """
    tif_path = tmp_path / "synthetic_gale_10x10.tif"
    crs = CRS.from_wkt(GALE_CRS_WKT)
    # Origin around Gale Crater coordinates (~137.8 deg E, -5.4 deg N)
    transform = from_origin(8130000.0, -310000.0, 20.0, 20.0)

    data = np.full((10, 10), -4500.0, dtype=np.float32)
    for r in range(10):
        for c in range(10):
            data[r, c] = -4500.0 + (r * 15.0) + c

    data[0, :] = NODATA_VALUE   # Top row
    data[9, :] = NODATA_VALUE   # Bottom row
    data[:, 9] = NODATA_VALUE   # Right column
    data[0, 0] = NODATA_VALUE   # Corner

    with rasterio.open(
        tif_path,
        "w",
        driver="GTiff",
        height=10,
        width=10,
        count=1,
        dtype="float32",
        crs=crs,
        transform=transform,
        nodata=NODATA_VALUE,
    ) as dst:
        dst.write(data, 1)

    ds = rasterio.open(tif_path)
    tf = DEMTransformer.from_dataset(ds)
    return tf, data, ds


# ---------------------------------------------------------------------------
# 1. Valid Jezero sampling
# ---------------------------------------------------------------------------

def test_sample_elevation_valid_jezero(jezero_synthetic_dem):
    tf, data, ds = jezero_synthetic_dem
    try:
        dem_map = {"jezero_crater": RegionalDEM("jezero_crater", tf)}

        # Query pixel center (col=5, row=5)
        lon_deg, lat_deg = tf.pixel_to_geographic(5.5, 5.5)
        resp = sample_elevation("jezero_crater", lon_deg, lat_deg, dem_map)

        # Expected elevation dynamically extracted from synthetic raster array
        expected_elevation = float(data[5, 5])

        assert resp.region_id == "jezero_crater"
        assert resp.status == CoverageStatus.VALID
        assert resp.status == "valid"
        assert resp.geometric_coverage is True
        assert resp.elevation_valid is True
        assert resp.elevation_m is not None
        assert pytest.approx(resp.elevation_m) == expected_elevation
        assert resp.sampling_method == "nearest_neighbor"
        assert resp.coordinate_reference.body == "Mars"
        assert resp.message is None
    finally:
        ds.close()


# ---------------------------------------------------------------------------
# 2. Valid Gale sampling using distinct synthetic raster and its own projection
# ---------------------------------------------------------------------------

def test_sample_elevation_valid_gale_distinct_raster(jezero_synthetic_dem, gale_synthetic_dem):
    j_tf, j_data, j_ds = jezero_synthetic_dem
    g_tf, g_data, g_ds = gale_synthetic_dem
    try:
        # Register both distinct regional DEMs in mapping
        dem_map = {
            "jezero_crater": RegionalDEM("jezero_crater", j_tf),
            "gale_crater": RegionalDEM("gale_crater", g_tf),
        }

        # Query Gale pixel center (col=4, row=4)
        g_lon, g_lat = g_tf.pixel_to_geographic(4.5, 4.5)
        g_resp = sample_elevation("gale_crater", g_lon, g_lat, dem_map)

        expected_gale_elevation = float(g_data[4, 4])

        assert g_resp.region_id == "gale_crater"
        assert g_resp.status == CoverageStatus.VALID
        assert g_resp.geometric_coverage is True
        assert g_resp.elevation_valid is True
        assert pytest.approx(g_resp.elevation_m) == expected_gale_elevation

        # Prove Gale elevation is completely distinct from Jezero's elevation range
        # Gale is ~ -4440 m, Jezero is ~ -2500 m
        assert g_resp.elevation_m < -4000.0

        # Query Jezero point on the same registry mapping to verify co-existence
        j_lon, j_lat = j_tf.pixel_to_geographic(4.5, 4.5)
        j_resp = sample_elevation("jezero_crater", j_lon, j_lat, dem_map)
        expected_jezero_elevation = float(j_data[4, 4])
        assert pytest.approx(j_resp.elevation_m) == expected_jezero_elevation
        assert j_resp.elevation_m > -3000.0
    finally:
        j_ds.close()
        g_ds.close()


# ---------------------------------------------------------------------------
# 3. NoData collar
# ---------------------------------------------------------------------------

def test_sample_elevation_nodata_collar(jezero_synthetic_dem):
    tf, data, ds = jezero_synthetic_dem
    try:
        dem_map = {"jezero_crater": RegionalDEM("jezero_crater", tf)}

        # Query row 0 pixel center (col=5, row=0) which is NoData
        lon_deg, lat_deg = tf.pixel_to_geographic(5.5, 0.5)
        resp = sample_elevation("jezero_crater", lon_deg, lat_deg, dem_map)

        assert resp.region_id == "jezero_crater"
        assert resp.status == CoverageStatus.NODATA_COLLAR
        assert resp.status == "nodata_collar"
        assert resp.geometric_coverage is True
        assert resp.elevation_valid is False
        assert resp.elevation_m is None
        assert resp.message == "Containing pixel lies in a NoData or masked collar region"
    finally:
        ds.close()


# ---------------------------------------------------------------------------
# 4. Out-of-bounds coordinate
# ---------------------------------------------------------------------------

def test_sample_elevation_out_of_bounds(jezero_synthetic_dem):
    tf, _, ds = jezero_synthetic_dem
    try:
        dem_map = {"jezero_crater": RegionalDEM("jezero_crater", tf)}

        # Query outside the 10x10 raster extent (col=15.0, row=5.0)
        lon_deg, lat_deg = tf.pixel_to_geographic(15.0, 5.0)
        resp = sample_elevation("jezero_crater", lon_deg, lat_deg, dem_map)

        assert resp.region_id == "jezero_crater"
        assert resp.status == CoverageStatus.OUT_OF_BOUNDS
        assert resp.status == "out_of_bounds"
        assert resp.geometric_coverage is False
        assert resp.elevation_valid is False
        assert resp.elevation_m is None
        assert resp.message == "Coordinates lie outside the raster geometric bounds"
    finally:
        ds.close()


# ---------------------------------------------------------------------------
# 5. Unknown region, proving no transformer is called
# ---------------------------------------------------------------------------

def test_sample_elevation_unknown_region_raises_not_found(jezero_synthetic_dem):
    tf, _, ds = jezero_synthetic_dem
    try:
        # Mock transformer to prove zero calls
        spy_tf = MagicMock(spec=tf)
        dem_map = {"jezero_crater": RegionalDEM("jezero_crater", spy_tf)}

        with pytest.raises(RegionNotFoundError) as exc_info:
            sample_elevation("olympus_mons", 77.45, 18.45, dem_map)

        assert exc_info.value.region_id == "olympus_mons"
        assert "olympus_mons" in str(exc_info.value)
        # Proves no transformer method was called
        assert spy_tf.transform_coordinate.call_count == 0
    finally:
        ds.close()


# ---------------------------------------------------------------------------
# 6. Known region with no loaded DEM
# ---------------------------------------------------------------------------

def test_sample_elevation_known_region_no_dem_raises_unavailable(jezero_synthetic_dem):
    tf, _, ds = jezero_synthetic_dem
    try:
        # dem_map only has jezero_crater; gale_crater is known but absent from mapping
        spy_tf = MagicMock(spec=tf)
        dem_map = {"jezero_crater": RegionalDEM("jezero_crater", spy_tf)}

        assert "gale_crater" in SUPPORTED_REGIONS

        with pytest.raises(DEMUnavailableError) as exc_info:
            sample_elevation("gale_crater", 137.8, -5.4, dem_map)

        assert exc_info.value.region_id == "gale_crater"
        assert "gale_crater" in str(exc_info.value)
        # Proves Jezero transformer was never called for Gale request
        assert spy_tf.transform_coordinate.call_count == 0
    finally:
        ds.close()


# ---------------------------------------------------------------------------
# 7. Mismatched mapping key and RegionalDEM.region_id, proving zero calls
# ---------------------------------------------------------------------------

def test_sample_elevation_mismatched_mapping_entry_raises_association_error(jezero_synthetic_dem):
    tf, _, ds = jezero_synthetic_dem
    try:
        spy_tf = MagicMock(spec=tf)
        # Deliberately construct corrupted mapping: key is 'gale_crater', but bound region_id is 'jezero_crater'
        corrupted_map = {
            "gale_crater": RegionalDEM(region_id="jezero_crater", transformer=spy_tf)
        }

        with pytest.raises(RegionAssociationError) as exc_info:
            sample_elevation("gale_crater", 137.8, -5.4, corrupted_map)

        assert exc_info.value.key == "gale_crater"
        assert exc_info.value.bound_region_id == "jezero_crater"
        assert "association mismatch" in str(exc_info.value)

        # Proves zero calls to the mismatched transformer's transform_coordinate
        assert spy_tf.transform_coordinate.call_count == 0
    finally:
        ds.close()


# ---------------------------------------------------------------------------
# 8. Closed transformer
# ---------------------------------------------------------------------------

def test_sample_elevation_closed_transformer_raises_runtime_error(tmp_path):
    # Create transformer via from_file so that closing it closes the handle
    crs = CRS.from_wkt(JEZERO_CRS_WKT)
    transform = from_origin(4329000.0, 1143420.0, 20.0, 20.0)
    tif_path = tmp_path / "closed_test_dem.tif"

    data = np.full((10, 10), -2500.0, dtype=np.float32)
    with rasterio.open(
        tif_path, "w", driver="GTiff", height=10, width=10, count=1,
        dtype="float32", crs=crs, transform=transform, nodata=NODATA_VALUE
    ) as dst:
        dst.write(data, 1)

    tf = DEMTransformer.from_file(tif_path)
    dem_map = {"jezero_crater": RegionalDEM("jezero_crater", tf)}

    # Close the transformer
    tf.close()
    assert tf.is_closed is True

    with pytest.raises(RuntimeError, match="closed"):
        sample_elevation("jezero_crater", 77.45, 18.45, dem_map)


# ---------------------------------------------------------------------------
# 9. Boolean, NaN, positive infinity, negative infinity, and out-of-range coordinates
# ---------------------------------------------------------------------------

def test_sample_elevation_rejects_invalid_coordinates(jezero_synthetic_dem):
    tf, _, ds = jezero_synthetic_dem
    try:
        dem_map = {"jezero_crater": RegionalDEM("jezero_crater", tf)}

        # Boolean rejection
        with pytest.raises(ValueError, match="Latitude cannot be a boolean"):
            sample_elevation("jezero_crater", 77.45, True, dem_map)
        with pytest.raises(ValueError, match="Latitude cannot be a boolean"):
            sample_elevation("jezero_crater", 77.45, False, dem_map)
        with pytest.raises(ValueError, match="Longitude cannot be a boolean"):
            sample_elevation("jezero_crater", True, 18.45, dem_map)
        with pytest.raises(ValueError, match="Longitude cannot be a boolean"):
            sample_elevation("jezero_crater", False, 18.45, dem_map)

        # NaN rejection
        with pytest.raises(ValueError, match="Latitude must be a finite number"):
            sample_elevation("jezero_crater", 77.45, float("nan"), dem_map)
        with pytest.raises(ValueError, match="Longitude must be a finite number"):
            sample_elevation("jezero_crater", float("nan"), 18.45, dem_map)

        # Infinity rejection
        with pytest.raises(ValueError, match="Latitude must be a finite number"):
            sample_elevation("jezero_crater", 77.45, float("inf"), dem_map)
        with pytest.raises(ValueError, match="Latitude must be a finite number"):
            sample_elevation("jezero_crater", 77.45, float("-inf"), dem_map)
        with pytest.raises(ValueError, match="Longitude must be a finite number"):
            sample_elevation("jezero_crater", float("inf"), 18.45, dem_map)
        with pytest.raises(ValueError, match="Longitude must be a finite number"):
            sample_elevation("jezero_crater", float("-inf"), 18.45, dem_map)

        # Out-of-range planetary coordinates
        with pytest.raises(ValueError, match="out of range"):
            sample_elevation("jezero_crater", 77.45, 91.0, dem_map)
        with pytest.raises(ValueError, match="out of range"):
            sample_elevation("jezero_crater", 77.45, -91.0, dem_map)
        with pytest.raises(ValueError, match="out of range"):
            sample_elevation("jezero_crater", 181.0, 18.45, dem_map)
        with pytest.raises(ValueError, match="out of range"):
            sample_elevation("jezero_crater", -181.0, 18.45, dem_map)
    finally:
        ds.close()


# ---------------------------------------------------------------------------
# 10. M2-A response consistency and public-schema boundaries
# ---------------------------------------------------------------------------

def test_sample_elevation_m2a_response_consistency_and_boundaries(jezero_synthetic_dem):
    tf, _, ds = jezero_synthetic_dem
    try:
        dem_map = {"jezero_crater": RegionalDEM("jezero_crater", tf)}

        # 1. Valid point
        lon_v, lat_v = tf.pixel_to_geographic(5.5, 5.5)
        resp_v = sample_elevation("jezero_crater", lon_v, lat_v, dem_map)
        assert isinstance(resp_v, ElevationSampleResponse)
        # Strict Pydantic model validation
        validated_v = ElevationSampleResponse.model_validate(resp_v)
        assert validated_v.status == CoverageStatus.VALID
        assert validated_v.status == "valid"
        assert validated_v.geometric_coverage is True
        assert validated_v.elevation_valid is True
        assert validated_v.elevation_m is not None
        assert math.isfinite(validated_v.elevation_m)

        # 2. NoData collar point
        lon_c, lat_c = tf.pixel_to_geographic(5.5, 0.5)
        resp_c = sample_elevation("jezero_crater", lon_c, lat_c, dem_map)
        assert isinstance(resp_c, ElevationSampleResponse)
        validated_c = ElevationSampleResponse.model_validate(resp_c)
        assert validated_c.status == CoverageStatus.NODATA_COLLAR
        assert validated_c.status == "nodata_collar"
        assert validated_c.geometric_coverage is True
        assert validated_c.elevation_valid is False
        assert validated_c.elevation_m is None

        # 3. Out-of-bounds point
        lon_o, lat_o = tf.pixel_to_geographic(15.0, 5.0)
        resp_o = sample_elevation("jezero_crater", lon_o, lat_o, dem_map)
        assert isinstance(resp_o, ElevationSampleResponse)
        validated_o = ElevationSampleResponse.model_validate(resp_o)
        assert validated_o.status == CoverageStatus.OUT_OF_BOUNDS
        assert validated_o.status == "out_of_bounds"
        assert validated_o.geometric_coverage is False
        assert validated_o.elevation_valid is False
        assert validated_o.elevation_m is None

        # 4. Public schema boundary check: internal pipeline attributes must not exist
        dumped = resp_v.model_dump()
        assert "projected" not in dumped
        assert "pixel_cont" not in dumped
        assert "containing_cell" not in dumped
        assert "bilinear_elevation_m" not in dumped

        # Invariants
        assert resp_v.sampling_method == "nearest_neighbor"
        assert resp_v.coordinate_reference.body == "Mars"
        assert resp_v.coordinate_reference.latitude_type == "planetocentric"
        assert resp_v.coordinate_reference.longitude_direction == "positive_east"
        assert resp_v.coordinate_reference.longitude_domain == "-180_to_180"
    finally:
        ds.close()
