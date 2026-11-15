"""
Unit and integration tests for DEMCoordinateTransformer and associated models.

Test Suites:
- Suite A: Pure CRS transformation tests (analytical Equirectangular vs Rasterio/PROJ).
- Suite B: Affine and continuous pixel coordinate transformations.
- Suite C: Half-open geometric boundary tests.
- Suite D: Synthetic GeoTIFF fixture tests (NoData collar, mask, and containing-cell validity).
- Suite E: Real DEM integration test (optional, gated by file existence).
"""

import math
from pathlib import Path
import pytest
import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_origin

from app.core.config import MARS_IAU2015_SPHERE_RADIUS_M
from app.scientific.dem.models import CoverageStatus, DEMCoordinateResult
from app.scientific.dem.transformer import DEMTransformer

# Verified Jezero CTX DEM CRS WKT
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

NODATA_VALUE = -3.4028234663852886e+38
from app.core.config import resolve_dem_path
REAL_DEM_PATH = resolve_dem_path()


@pytest.fixture
def jezero_crs():
    return CRS.from_wkt(JEZERO_CRS_WKT)


@pytest.fixture
def geometric_transformer(jezero_crs):
    """
    Pure geometric transformer matching Jezero raster bounds without requiring raster file.
    """
    transform = from_origin(4329000.0, 1143420.0, 20.0, 20.0)
    return DEMTransformer(
        crs=jezero_crs,
        transform=transform,
        width=4456,
        height=5067,
        nodata=NODATA_VALUE,
        dataset=None,
    )


@pytest.fixture
def synthetic_dem_file(tmp_path, jezero_crs):
    """
    Creates a small 10x10 synthetic GeoTIFF with 20m resolution mimicking
    the Jezero DEM's boundary NoData pattern:
    - Row 0: all NoData
    - Row 9: all NoData
    - Col 9: all NoData
    - Col 0, rows 1..8: valid
    - Interior (cols 1..8, rows 1..8): valid
    """
    tif_path = tmp_path / "synthetic_dem_10x10.tif"
    transform = from_origin(4329000.0, 1143420.0, 20.0, 20.0)

    data = np.full((10, 10), -2500.0, dtype=np.float32)
    # Apply synthetic elevation gradient
    for r in range(10):
        for c in range(10):
            data[r, c] = -2500.0 + (r * 10.0) + c

    # Set NoData borders matching Jezero pattern
    data[0, :] = NODATA_VALUE    # Top row
    data[9, :] = NODATA_VALUE    # Bottom row
    data[:, 9] = NODATA_VALUE    # Right column
    data[0, 0] = NODATA_VALUE    # Top-left corner is NoData

    with rasterio.open(
        tif_path,
        "w",
        driver="GTiff",
        height=10,
        width=10,
        count=1,
        dtype="float32",
        crs=jezero_crs,
        transform=transform,
        nodata=NODATA_VALUE,
    ) as dst:
        dst.write(data, 1)

    return tif_path


# ---------------------------------------------------------------------------
# Suite A: Pure CRS Transformation Tests
# ---------------------------------------------------------------------------

def test_crs_matches_analytical_equirectangular(geometric_transformer):
    """
    Verifies that geographic_to_projected matches the closed-form spherical
    Equirectangular projection equations:
    X = R * lambda * cos(phi_ts)
    Y = R * phi
    """
    r_mars = MARS_IAU2015_SPHERE_RADIUS_M
    phi_ts_rad = math.radians(18.4663)

    test_points = [
        (0.0, 0.0),
        (77.45, 18.45),
        (77.0, 18.0),
        (-133.8, -14.5),
        (180.0, 45.0),
        (-180.0, -45.0),
    ]

    for lon_deg, lat_deg in test_points:
        x_proj, y_proj = geometric_transformer.geographic_to_projected(lon_deg, lat_deg)

        x_analytical = r_mars * math.radians(lon_deg) * math.cos(phi_ts_rad)
        y_analytical = r_mars * math.radians(lat_deg)

        assert pytest.approx(x_proj, abs=1e-6) == x_analytical
        assert pytest.approx(y_proj, abs=1e-6) == y_analytical


def test_crs_round_trip_accuracy(geometric_transformer):
    """
    Verifies geographic -> projected -> geographic round-trip precision.
    """
    test_points = [
        (0.0, 0.0),
        (77.45, 18.45),
        (77.58, 18.38),
        (-45.0, 20.0),
        (179.9, -89.9),
    ]

    for lon_deg, lat_deg in test_points:
        x_m, y_m = geometric_transformer.geographic_to_projected(lon_deg, lat_deg)
        r_lon, r_lat = geometric_transformer.projected_to_geographic(x_m, y_m)

        assert pytest.approx(r_lon, abs=1e-10) == lon_deg
        assert pytest.approx(r_lat, abs=1e-10) == lat_deg


def test_crs_argument_order_verification(geometric_transformer):
    """
    Confirms longitude is strictly passed as X and latitude as Y.
    Swapping axes would project ~18.45 deg as longitude and ~77.45 deg as latitude.
    """
    lon_deg = 77.45
    lat_deg = 18.45
    x_m, y_m = geometric_transformer.geographic_to_projected(lon_deg, lat_deg)

    # For positive-east longitude 77.45 near standard parallel 18.4663, X must be ~4.35e6 m
    assert 4.3e6 < x_m < 4.4e6
    # Latitude 18.45 on Mars radius 3396190 m must be ~1.09e6 m
    assert 1.0e6 < y_m < 1.15e6


# ---------------------------------------------------------------------------
# Suite B: Affine and Pixel Coordinate Invertibility
# ---------------------------------------------------------------------------

def test_affine_forward_inverse_consistency(geometric_transformer):
    """
    Verifies pixel_to_projected and projected_to_pixel invertibility across grid points.
    """
    test_pixels = [
        (0.0, 0.0),
        (1272.214, 2490.092),
        (4455.999, 5066.999),
        (100.5, 200.5),
        (2228.0, 2533.5),
    ]

    for c, r in test_pixels:
        x, y = geometric_transformer.pixel_to_projected(c, r)
        c_inv, r_inv = geometric_transformer.projected_to_pixel(x, y)
        assert pytest.approx(c_inv, abs=1e-9) == c
        assert pytest.approx(r_inv, abs=1e-9) == r


# ---------------------------------------------------------------------------
# Suite C: Half-Open Geometric Boundary Tests
# ---------------------------------------------------------------------------

def test_half_open_geometric_bounds(geometric_transformer):
    """
    Verifies strict half-open bounds:
    0.0 <= col_cont < width  and  0.0 <= row_cont < height.
    """
    w = geometric_transformer.width   # 4456
    h = geometric_transformer.height  # 5067

    # Inside
    assert geometric_transformer.is_geometrically_covered(0.0, 0.0) is True
    assert geometric_transformer.is_geometrically_covered(w - 0.001, h - 0.001) is True
    assert geometric_transformer.is_geometrically_covered(100.0, 100.0) is True

    # Boundary upper edges (must be rejected)
    assert geometric_transformer.is_geometrically_covered(w, 0.0) is False
    assert geometric_transformer.is_geometrically_covered(0.0, h) is False
    assert geometric_transformer.is_geometrically_covered(w, h) is False

    # Negative coordinates (must be rejected)
    assert geometric_transformer.is_geometrically_covered(-0.0001, 0.0) is False
    assert geometric_transformer.is_geometrically_covered(0.0, -0.0001) is False
    assert geometric_transformer.is_geometrically_covered(-1.0, -1.0) is False


def test_four_neighbor_eligibility_bounds(geometric_transformer):
    """
    Verifies the four-neighbor continuous region:
    0.5 <= col_cont < (width - 0.5) and 0.5 <= row_cont < (height - 0.5).
    """
    w = geometric_transformer.width   # 4456
    h = geometric_transformer.height  # 5067

    assert geometric_transformer.is_four_neighbor_eligible_geometric(0.5, 0.5) is True
    assert geometric_transformer.is_four_neighbor_eligible_geometric(w - 0.5001, h - 0.5001) is True

    # Outer half-pixel collar cannot form 4 surrounding pixel centers
    assert geometric_transformer.is_four_neighbor_eligible_geometric(0.499, 0.5) is False
    assert geometric_transformer.is_four_neighbor_eligible_geometric(0.5, 0.499) is False
    assert geometric_transformer.is_four_neighbor_eligible_geometric(w - 0.5, 100.0) is False
    assert geometric_transformer.is_four_neighbor_eligible_geometric(100.0, h - 0.5) is False


def test_containing_cell_calculation(geometric_transformer):
    """
    Verifies containing cell indices are floor(col_cont) and floor(row_cont).
    """
    cell = geometric_transformer.get_containing_cell(1272.214, 2490.092)
    assert cell is not None
    assert cell.col == 1272
    assert cell.row == 2490

    # Near upper bound
    cell_edge = geometric_transformer.get_containing_cell(4455.999, 5066.999)
    assert cell_edge is not None
    assert cell_edge.col == 4455
    assert cell_edge.row == 5066

    # Outside
    assert geometric_transformer.get_containing_cell(4456.0, 5066.0) is None
    assert geometric_transformer.get_containing_cell(-0.1, 10.0) is None


# ---------------------------------------------------------------------------
# Suite D: Synthetic GeoTIFF Fixture Tests (Mask and NoData Validation)
# ---------------------------------------------------------------------------

def test_synthetic_raster_valid_interior(synthetic_dem_file):
    """
    Tests query at valid interior pixel (col=5, row=5) on a 10x10 synthetic raster.
    """
    with rasterio.open(synthetic_dem_file) as ds:
        tf = DEMTransformer.from_dataset(ds)

        # Compute geographic coordinate for pixel (5.5, 5.5)
        lon_deg, lat_deg = tf.pixel_to_geographic(5.5, 5.5)
        res = tf.transform_coordinate(lon_deg, lat_deg)

        assert res.geometric_coverage is True
        assert res.elevation_valid is True
        assert res.containing_cell is not None
        assert res.containing_cell.col == 5
        assert res.containing_cell.row == 5
        assert res.containing_elevation_m is not None
        assert pytest.approx(res.containing_elevation_m, abs=0.1) == (-2500.0 + 50.0 + 5.0)
        assert res.bilinear_elevation_m is None
        assert res.status == CoverageStatus.VALID


def test_synthetic_raster_nodata_collar_row0(synthetic_dem_file):
    """
    Tests query in top NoData border (col=5, row=0).
    Geometric coverage is True, but elevation is NoData.
    """
    with rasterio.open(synthetic_dem_file) as ds:
        tf = DEMTransformer.from_dataset(ds)

        lon_deg, lat_deg = tf.pixel_to_geographic(5.5, 0.5)
        res = tf.transform_coordinate(lon_deg, lat_deg)

        assert res.geometric_coverage is True
        assert res.elevation_valid is False
        assert res.containing_cell is not None
        assert res.containing_cell.col == 5
        assert res.containing_cell.row == 0
        assert res.containing_elevation_m is None
        assert res.status == CoverageStatus.NODATA_COLLAR


def test_synthetic_raster_nodata_collar_col9(synthetic_dem_file):
    """
    Tests query in right NoData border (col=9, row=5).
    """
    with rasterio.open(synthetic_dem_file) as ds:
        tf = DEMTransformer.from_dataset(ds)

        lon_deg, lat_deg = tf.pixel_to_geographic(9.5, 5.5)
        res = tf.transform_coordinate(lon_deg, lat_deg)

        assert res.geometric_coverage is True
        assert res.elevation_valid is False
        assert res.containing_cell is not None
        assert res.containing_cell.col == 9
        assert res.containing_cell.row == 5
        assert res.containing_elevation_m is None
        assert res.status == CoverageStatus.NODATA_COLLAR


def test_synthetic_raster_valid_column_zero(synthetic_dem_file):
    """
    Tests col=0, row=5 which is valid (matching Jezero pattern where col 0 rows 1..5065 are valid).
    """
    with rasterio.open(synthetic_dem_file) as ds:
        tf = DEMTransformer.from_dataset(ds)

        lon_deg, lat_deg = tf.pixel_to_geographic(0.5, 5.5)
        res = tf.transform_coordinate(lon_deg, lat_deg)

        assert res.geometric_coverage is True
        assert res.elevation_valid is True
        assert res.containing_cell.col == 0
        assert res.containing_cell.row == 5
        assert res.containing_elevation_m is not None
        assert res.status == CoverageStatus.VALID


def test_synthetic_raster_near_boundary_pixel(synthetic_dem_file):
    """
    Tests continuous coordinate (col_cont=9.999, row_cont=9.999).
    Geometric coverage: True (within [0, 10) x [0, 10)).
    Containing cell: (9, 9) which is NoData.
    Elevation valid: False.
    """
    with rasterio.open(synthetic_dem_file) as ds:
        tf = DEMTransformer.from_dataset(ds)

        lon_deg, lat_deg = tf.pixel_to_geographic(9.999, 9.999)
        res = tf.transform_coordinate(lon_deg, lat_deg)

        assert res.geometric_coverage is True
        assert res.elevation_valid is False
        assert res.containing_cell is not None
        assert res.containing_cell.col == 9
        assert res.containing_cell.row == 9
        assert res.containing_elevation_m is None
        assert res.status == CoverageStatus.NODATA_COLLAR


def test_synthetic_raster_out_of_bounds(synthetic_dem_file):
    """
    Tests coordinates that fall outside the raster geometry.
    """
    with rasterio.open(synthetic_dem_file) as ds:
        tf = DEMTransformer.from_dataset(ds)

        # Coordinate past right edge (col 10.5)
        lon_deg, lat_deg = tf.pixel_to_geographic(10.5, 5.0)
        res = tf.transform_coordinate(lon_deg, lat_deg)

        assert res.geometric_coverage is False
        assert res.elevation_valid is False
        assert res.containing_cell is None
        assert res.containing_elevation_m is None
        assert res.status == CoverageStatus.OUT_OF_BOUNDS


# ---------------------------------------------------------------------------
# Suite E: Real DEM Integration Tests (Optional, File-Gated)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not REAL_DEM_PATH.exists(), reason="Jezero DEM file not present")
def test_real_jezero_dem_t1_1_control_point():
    """
    Verifies T1.1 control point against the actual 86 MB Jezero CTX DEM:
    lon = 77.45 deg E, lat = 18.45 deg N.
    """
    with rasterio.open(REAL_DEM_PATH) as ds:
        tf = DEMTransformer.from_dataset(ds)
        res = tf.transform_coordinate(77.45, 18.45)

        # Verified projected coordinates
        assert pytest.approx(res.projected.x_m, abs=0.01) == 4354444.29
        assert pytest.approx(res.projected.y_m, abs=0.01) == 1093618.17

        # Continuous pixel coordinates
        assert pytest.approx(res.pixel_cont.col_cont, abs=0.01) == 1272.21
        assert pytest.approx(res.pixel_cont.row_cont, abs=0.01) == 2490.09

        # Containing cell
        assert res.containing_cell is not None
        assert res.containing_cell.col == 1272
        assert res.containing_cell.row == 2490

        # Coverage and elevation
        assert res.geometric_coverage is True
        assert res.elevation_valid is True
        assert res.status == CoverageStatus.VALID
        assert res.containing_elevation_m is not None
        # Elevation at cell (1272, 2490) is ~ -2571.12 m
        assert -2600.0 < res.containing_elevation_m < -2500.0
        assert res.bilinear_elevation_m is None


@pytest.mark.skipif(not REAL_DEM_PATH.exists(), reason="Jezero DEM file not present")
def test_real_jezero_dem_boundary_nodata_pattern():
    """
    Verifies the confirmed NoData pattern on the actual Jezero DEM:
    - (col=5, row=0): NoData collar
    - (col=4455, row=5): NoData collar
    - (col=0, row=5): Valid elevation
    - (col_cont=4455.999, row_cont=5066.999): Geometric True, Elevation False
    """
    with rasterio.open(REAL_DEM_PATH) as ds:
        tf = DEMTransformer.from_dataset(ds)

        # 1. Top border (col=5, row=0)
        lon_1, lat_1 = tf.pixel_to_geographic(5.5, 0.5)
        res_1 = tf.transform_coordinate(lon_1, lat_1)
        assert res_1.geometric_coverage is True
        assert res_1.elevation_valid is False
        assert res_1.status == CoverageStatus.NODATA_COLLAR

        # 2. Right border (col=4455, row=5)
        lon_2, lat_2 = tf.pixel_to_geographic(4455.5, 5.5)
        res_2 = tf.transform_coordinate(lon_2, lat_2)
        assert res_2.geometric_coverage is True
        assert res_2.elevation_valid is False
        assert res_2.status == CoverageStatus.NODATA_COLLAR

        # 3. Col 0, row 5 (valid)
        lon_3, lat_3 = tf.pixel_to_geographic(0.5, 5.5)
        res_3 = tf.transform_coordinate(lon_3, lat_3)
        assert res_3.geometric_coverage is True
        assert res_3.elevation_valid is True
        assert res_3.status == CoverageStatus.VALID
        assert res_3.containing_elevation_m is not None

        # 4. Near boundary (col_cont=4455.999, row_cont=5066.999)
        lon_4, lat_4 = tf.pixel_to_geographic(4455.999, 5066.999)
        res_4 = tf.transform_coordinate(lon_4, lat_4)
        assert res_4.geometric_coverage is True
        assert res_4.elevation_valid is False
        assert res_4.containing_cell.col == 4455
        assert res_4.containing_cell.row == 5066
        assert res_4.status == CoverageStatus.NODATA_COLLAR


# ---------------------------------------------------------------------------
# Suite F: Metadata, State & Coordinate Validation Tests
# ---------------------------------------------------------------------------

def test_geometric_transformer_elevation_unavailable(geometric_transformer):
    """
    Verifies that when no dataset is attached, points inside geometric bounds
    are explicitly classified as ELEVATION_UNAVAILABLE (not VALID or NODATA_COLLAR).
    """
    res = geometric_transformer.transform_coordinate(77.45, 18.45)
    assert res.geometric_coverage is True
    assert res.elevation_valid is False
    assert res.containing_elevation_m is None
    assert res.bilinear_elevation_m is None
    assert res.status == CoverageStatus.ELEVATION_UNAVAILABLE
    assert res.containing_cell is not None
    assert res.containing_cell.col == 1272
    assert res.containing_cell.row == 2490


def test_metadata_validation_in_init(jezero_crs):
    """
    Verifies strict validation of CRS, affine transform, and dimensions in __init__.
    """
    import affine

    valid_transform = from_origin(4329000.0, 1143420.0, 20.0, 20.0)

    # Invalid CRS
    with pytest.raises(ValueError, match="Raster CRS"):
        DEMTransformer(crs=None, transform=valid_transform, width=10, height=10)
    with pytest.raises(ValueError, match="Raster CRS"):
        DEMTransformer(crs="not_a_crs", transform=valid_transform, width=10, height=10)

    # Degenerate affine transform
    degenerate_transform = affine.Affine(0, 0, 0, 0, 0, 0)
    with pytest.raises(ValueError, match="degenerate"):
        DEMTransformer(crs=jezero_crs, transform=degenerate_transform, width=10, height=10)
    with pytest.raises(ValueError, match="Raster transform"):
        DEMTransformer(crs=jezero_crs, transform=None, width=10, height=10)

    # Non-positive or boolean dimensions
    with pytest.raises(ValueError, match="width"):
        DEMTransformer(crs=jezero_crs, transform=valid_transform, width=0, height=10)
    with pytest.raises(ValueError, match="width"):
        DEMTransformer(crs=jezero_crs, transform=valid_transform, width=-5, height=10)
    with pytest.raises(ValueError, match="width"):
        DEMTransformer(crs=jezero_crs, transform=valid_transform, width=True, height=10)
    with pytest.raises(ValueError, match="height"):
        DEMTransformer(crs=jezero_crs, transform=valid_transform, width=10, height=0)
    with pytest.raises(ValueError, match="height"):
        DEMTransformer(crs=jezero_crs, transform=valid_transform, width=10, height=-10)
    with pytest.raises(ValueError, match="height"):
        DEMTransformer(crs=jezero_crs, transform=valid_transform, width=10, height=False)


def test_dataset_ownership_and_state(synthetic_dem_file):
    """
    Verifies that dataset ownership remains with the caller when from_dataset()
    receives an open dataset, and that closed datasets are rejected.
    """
    ds = rasterio.open(synthetic_dem_file)
    try:
        tf = DEMTransformer.from_dataset(ds)
        # Verify transformer operates normally
        res = tf.transform_coordinate(77.0, 18.0)
        assert isinstance(res, DEMCoordinateResult)
        # Ownership invariant: dataset remains open in caller's control
        assert not ds.closed
    finally:
        ds.close()

    assert ds.closed

    # Passing closed dataset to from_dataset must raise ValueError
    with pytest.raises(ValueError, match="closed"):
        DEMTransformer.from_dataset(ds)


def test_geographic_coordinate_validation_rejection(geometric_transformer):
    """
    Verifies that validate_coordinates() is actively used and rejects booleans,
    non-finite values, and out-of-range coordinates.
    """
    # Booleans rejected
    with pytest.raises(ValueError, match="Latitude"):
        geometric_transformer.transform_coordinate(77.45, True)
    with pytest.raises(ValueError, match="Latitude"):
        geometric_transformer.transform_coordinate(77.45, False)
    with pytest.raises(ValueError, match="Longitude"):
        geometric_transformer.transform_coordinate(True, 18.45)
    with pytest.raises(ValueError, match="Longitude"):
        geometric_transformer.transform_coordinate(False, 18.45)

    # Non-finite rejected
    with pytest.raises(ValueError, match="Latitude"):
        geometric_transformer.transform_coordinate(77.45, float("nan"))
    with pytest.raises(ValueError, match="Latitude"):
        geometric_transformer.transform_coordinate(77.45, float("inf"))
    with pytest.raises(ValueError, match="Longitude"):
        geometric_transformer.transform_coordinate(float("nan"), 18.45)
    with pytest.raises(ValueError, match="Longitude"):
        geometric_transformer.transform_coordinate(float("-inf"), 18.45)

    # Out-of-range rejected
    with pytest.raises(ValueError, match="Latitude"):
        geometric_transformer.transform_coordinate(77.45, 90.1)
    with pytest.raises(ValueError, match="Latitude"):
        geometric_transformer.transform_coordinate(77.45, -90.1)
    with pytest.raises(ValueError, match="Longitude"):
        geometric_transformer.transform_coordinate(180.1, 18.45)
    with pytest.raises(ValueError, match="Longitude"):
        geometric_transformer.transform_coordinate(-180.1, 18.45)


def test_nan_inf_and_bool_in_geometric_coverage(geometric_transformer):
    """
    Verifies that is_geometrically_covered and is_four_neighbor_eligible_geometric
    explicitly reject Booleans, NaN, and positive/negative infinity by returning False.
    """
    # NaN and Inf in is_geometrically_covered
    assert geometric_transformer.is_geometrically_covered(float("nan"), 100.0) is False
    assert geometric_transformer.is_geometrically_covered(100.0, float("nan")) is False
    assert geometric_transformer.is_geometrically_covered(float("inf"), 100.0) is False
    assert geometric_transformer.is_geometrically_covered(100.0, float("inf")) is False
    assert geometric_transformer.is_geometrically_covered(float("-inf"), 100.0) is False
    assert geometric_transformer.is_geometrically_covered(100.0, float("-inf")) is False

    # Booleans in is_geometrically_covered
    assert geometric_transformer.is_geometrically_covered(True, 100.0) is False
    assert geometric_transformer.is_geometrically_covered(100.0, False) is False
    assert geometric_transformer.is_geometrically_covered(True, False) is False

    # NaN, Inf, and Booleans in is_four_neighbor_eligible_geometric
    assert geometric_transformer.is_four_neighbor_eligible_geometric(float("nan"), 100.0) is False
    assert geometric_transformer.is_four_neighbor_eligible_geometric(100.0, float("inf")) is False
    assert geometric_transformer.is_four_neighbor_eligible_geometric(True, 100.0) is False
    assert geometric_transformer.is_four_neighbor_eligible_geometric(100.0, False) is False

    # get_containing_cell returns None for NaN, Inf, and Booleans
    assert geometric_transformer.get_containing_cell(float("nan"), 100.0) is None
    assert geometric_transformer.get_containing_cell(True, 100.0) is None


def test_projected_coordinate_validation(geometric_transformer):
    """
    Verifies that projected_to_geographic and projected_to_pixel reject
    Boolean and non-finite X/Y coordinates with clear ValueError exceptions.
    """
    # projected_to_geographic
    with pytest.raises(ValueError, match="Projected X"):
        geometric_transformer.projected_to_geographic(float("nan"), 1000.0)
    with pytest.raises(ValueError, match="Projected X"):
        geometric_transformer.projected_to_geographic(float("inf"), 1000.0)
    with pytest.raises(ValueError, match="Projected X"):
        geometric_transformer.projected_to_geographic(True, 1000.0)
    with pytest.raises(ValueError, match="Projected Y"):
        geometric_transformer.projected_to_geographic(1000.0, float("-inf"))
    with pytest.raises(ValueError, match="Projected Y"):
        geometric_transformer.projected_to_geographic(1000.0, False)

    # projected_to_pixel
    with pytest.raises(ValueError, match="Projected X"):
        geometric_transformer.projected_to_pixel(float("nan"), 1000.0)
    with pytest.raises(ValueError, match="Projected X"):
        geometric_transformer.projected_to_pixel(float("-inf"), 1000.0)
    with pytest.raises(ValueError, match="Projected X"):
        geometric_transformer.projected_to_pixel(False, 1000.0)
    with pytest.raises(ValueError, match="Projected Y"):
        geometric_transformer.projected_to_pixel(1000.0, float("inf"))
    with pytest.raises(ValueError, match="Projected Y"):
        geometric_transformer.projected_to_pixel(1000.0, True)


def test_pixel_to_projected_and_geographic_validation(geometric_transformer):
    """
    Verifies that pixel_to_projected and pixel_to_geographic reject
    Boolean and non-finite pixel coordinates with clear ValueError exceptions.
    """
    # pixel_to_projected
    with pytest.raises(ValueError, match="Continuous column"):
        geometric_transformer.pixel_to_projected(float("nan"), 10.0)
    with pytest.raises(ValueError, match="Continuous column"):
        geometric_transformer.pixel_to_projected(True, 10.0)
    with pytest.raises(ValueError, match="Continuous row"):
        geometric_transformer.pixel_to_projected(10.0, float("inf"))
    with pytest.raises(ValueError, match="Continuous row"):
        geometric_transformer.pixel_to_projected(10.0, False)

    # pixel_to_geographic
    with pytest.raises(ValueError, match="Continuous column"):
        geometric_transformer.pixel_to_geographic(float("-inf"), 10.0)
    with pytest.raises(ValueError, match="Continuous column"):
        geometric_transformer.pixel_to_geographic(False, 10.0)
    with pytest.raises(ValueError, match="Continuous row"):
        geometric_transformer.pixel_to_geographic(10.0, float("nan"))
    with pytest.raises(ValueError, match="Continuous row"):
        geometric_transformer.pixel_to_geographic(10.0, True)


def test_pydantic_rejection_of_non_finite_coordinates():
    """
    Verifies that Pydantic models explicitly reject non-finite and Boolean coordinate inputs.
    """
    from pydantic import ValidationError
    from app.scientific.dem.models import (
        ProjectedPoint,
        ContinuousPixelPoint,
        ContainingCell,
    )

    # ProjectedPoint
    with pytest.raises(ValidationError):
        ProjectedPoint(x_m=float("nan"), y_m=10.0)
    with pytest.raises(ValidationError):
        ProjectedPoint(x_m=10.0, y_m=float("inf"))
    with pytest.raises(ValidationError):
        ProjectedPoint(x_m=True, y_m=10.0)

    # ContinuousPixelPoint
    with pytest.raises(ValidationError):
        ContinuousPixelPoint(col_cont=float("nan"), row_cont=10.0)
    with pytest.raises(ValidationError):
        ContinuousPixelPoint(col_cont=10.0, row_cont=float("-inf"))
    with pytest.raises(ValidationError):
        ContinuousPixelPoint(col_cont=False, row_cont=10.0)

    # ContainingCell
    with pytest.raises(ValidationError):
        ContainingCell(col=True, row=10)
    with pytest.raises(ValidationError):
        ContainingCell(col=10, row=False)
    with pytest.raises(ValidationError):
        ContainingCell(col=10.5, row=5)  # non-integer


def test_from_file_lifecycle_and_context_manager(synthetic_dem_file):
    """
    Verifies that from_file() opens and owns the dataset, close() shuts it down,
    and context manager handles cleanup automatically.
    """
    # 1. Manual close()
    tf = DEMTransformer.from_file(synthetic_dem_file)
    assert tf._owns_dataset is True
    assert not tf.is_closed
    assert not tf.dataset.closed

    tf.close()
    assert tf.is_closed is True
    assert tf.dataset.closed is True

    # Subsequent transform_coordinate raises RuntimeError
    with pytest.raises(RuntimeError, match="closed"):
        tf.transform_coordinate(77.0, 18.0)

    # 2. Context manager
    with DEMTransformer.from_file(synthetic_dem_file) as tf_ctx:
        assert not tf_ctx.is_closed
        assert not tf_ctx.dataset.closed
        res = tf_ctx.transform_coordinate(77.0, 18.0)
        assert isinstance(res, DEMCoordinateResult)

    assert tf_ctx.is_closed is True
    assert tf_ctx.dataset.closed is True


def test_from_dataset_close_does_not_close_caller_dataset(synthetic_dem_file):
    """
    Verifies that closing a transformer created via from_dataset() marks the
    transformer as closed but does NOT close the caller-owned dataset.
    """
    ds = rasterio.open(synthetic_dem_file)
    try:
        tf = DEMTransformer.from_dataset(ds)
        assert tf._owns_dataset is False
        assert not tf.is_closed
        assert not ds.closed

        # Closing transformer
        tf.close()
        assert tf.is_closed is True

        # Caller-owned dataset remains OPEN and usable by caller
        assert not ds.closed
        sample = ds.read(1, window=((0, 1), (0, 1)))
        assert sample is not None
    finally:
        ds.close()

    assert ds.closed
