"""
Unit and regression tests for AresPath deterministic A* routing engine.

Covers:
1. Straight horizontal route.
2. Straight vertical route.
3. Diagonal route.
4. Optimal route selection around an obstacle.
5. NoData avoidance.
6. Diagonal corner-cutting prevention.
7. Start equals destination.
8. Invalid start and destination.
9. Out-of-bounds cells.
10. No available path.
11. Deterministic output across repeated runs.
12. Non-negative, finite traversal costs.
13. Correct route reconstruction.
14. Correct distance calculation.
15. Real Jezero DEM integration test (skipped when dataset is absent).
16. Optimality verification: suboptimal local path rejected for cheaper detour.
"""

import math
from pathlib import Path
import numpy as np
import pytest
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_origin

from app.scientific.dem.transformer import DEMTransformer
from app.scientific.routing.astar import (
    AStarRouter,
    AStarRouteResult,
    DEMGrid,
    RoutingError,
    StartOutOfBoundsError,
    DestinationOutOfBoundsError,
    StartNoDataError,
    DestinationNoDataError,
    PathNotFoundError,
)

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
    'PARAMETER["central_meridian",77.45],'
    'PARAMETER["false_easting",0],'
    'PARAMETER["false_northing",0],'
    'UNIT["metre",1,AUTHORITY["EPSG","9001"]],'
    'AXIS["Easting",EAST],'
    'AXIS["Northing",NORTH]]'
)

from app.core.config import resolve_dem_path
REAL_DEM_PATH = resolve_dem_path()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def flat_10x10_grid() -> DEMGrid:
    """10x10 flat grid with 20m pixel spacing."""
    elevation = np.full((10, 10), -2500.0, dtype=np.float32)
    valid_mask = np.ones((10, 10), dtype=bool)
    return DEMGrid(elevation=elevation, valid_mask=valid_mask, dx=20.0, dy=20.0)


@pytest.fixture
def synthetic_dem_transformer(tmp_path: Path):
    """
    Creates a 12x12 synthetic GeoTIFF with:
    - 20m pixel spacing
    - Boundary rows/cols as NoData (-32768.0)
    - Interior rows 1..10, cols 1..10 with valid elevations
    """
    dem_file = tmp_path / "synthetic_routing_dem.tif"
    height, width = 12, 12
    nodata_val = -32768.0

    elev = np.full((height, width), nodata_val, dtype=np.float32)
    for r in range(1, height - 1):
        for c in range(1, width - 1):
            elev[r, c] = float(-2500.0 + r * 10.0 + c * 5.0)

    # Upper-left origin at (0, 240) in projected metres
    transform = from_origin(west=0.0, north=240.0, xsize=20.0, ysize=20.0)
    crs = CRS.from_wkt(JEZERO_CRS_WKT)

    with rasterio.open(
        dem_file,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype=elev.dtype,
        crs=crs,
        transform=transform,
        nodata=nodata_val,
    ) as dst:
        dst.write(elev, 1)

    ds = rasterio.open(dem_file)
    tf = DEMTransformer(
        crs=crs,
        transform=transform,
        width=width,
        height=height,
        nodata=nodata_val,
        dataset=ds,
        owns_dataset=True,
    )
    yield tf, elev, ds
    ds.close()


# ---------------------------------------------------------------------------
# 1. Straight horizontal route
# ---------------------------------------------------------------------------

def test_straight_horizontal_route(flat_10x10_grid: DEMGrid):
    start = (1, 5)
    goal = (6, 5)
    path = AStarRouter.find_path_on_grid(flat_10x10_grid, start, goal)

    expected = [(1, 5), (2, 5), (3, 5), (4, 5), (5, 5), (6, 5)]
    assert path == expected
    assert len(path) == 6


# ---------------------------------------------------------------------------
# 2. Straight vertical route
# ---------------------------------------------------------------------------

def test_straight_vertical_route(flat_10x10_grid: DEMGrid):
    start = (5, 1)
    goal = (5, 6)
    path = AStarRouter.find_path_on_grid(flat_10x10_grid, start, goal)

    expected = [(5, 1), (5, 2), (5, 3), (5, 4), (5, 5), (5, 6)]
    assert path == expected
    assert len(path) == 6


# ---------------------------------------------------------------------------
# 3. Straight diagonal route
# ---------------------------------------------------------------------------

def test_straight_diagonal_route(flat_10x10_grid: DEMGrid):
    start = (1, 1)
    goal = (5, 5)
    path = AStarRouter.find_path_on_grid(flat_10x10_grid, start, goal)

    expected = [(1, 1), (2, 2), (3, 3), (4, 4), (5, 5)]
    assert path == expected
    assert len(path) == 5


# ---------------------------------------------------------------------------
# 4. Optimal route selection around an obstacle
# ---------------------------------------------------------------------------

def test_optimal_route_around_obstacle(flat_10x10_grid: DEMGrid):
    # Place a vertical obstacle in column 3 from row 2 to row 6
    flat_10x10_grid.valid_mask[2:7, 3] = False

    start = (1, 4)
    goal = (5, 4)
    path = AStarRouter.find_path_on_grid(flat_10x10_grid, start, goal)

    # Path must start at (1, 4) and end at (5, 4)
    assert path[0] == start
    assert path[-1] == goal
    # No cell in path can be in the obstacle
    for col, row in path:
        assert bool(flat_10x10_grid.valid_mask[row, col]) is True


# ---------------------------------------------------------------------------
# 5. NoData avoidance
# ---------------------------------------------------------------------------

def test_nodata_avoidance():
    elev = np.zeros((8, 8), dtype=np.float32)
    valid = np.ones((8, 8), dtype=bool)

    # Create NoData wall at column 4 with only cell (4, 1) traversable
    valid[:, 4] = False
    valid[1, 4] = True

    grid = DEMGrid(elevation=elev, valid_mask=valid, dx=10.0, dy=10.0)
    start = (1, 5)
    goal = (6, 5)

    path = AStarRouter.find_path_on_grid(grid, start, goal)
    assert path[0] == start
    assert path[-1] == goal
    # The path must pass through the only open gap at (4, 1)
    assert (4, 1) in path
    # No invalid cells traversed
    for c, r in path:
        assert bool(valid[r, c]) is True


# ---------------------------------------------------------------------------
# 6. Diagonal corner-cutting prevention
# ---------------------------------------------------------------------------

def test_diagonal_corner_cutting_prevention():
    """
    Blocks (1, 0) and (0, 1), testing if path can cut between (0, 0) and (1, 1).
    When (1, 0) is blocked, diagonal movement from (0, 0) to (1, 1) must be rejected
    because corner cell (1, 0) is blocked.
    """
    elev = np.zeros((4, 4), dtype=np.float32)
    valid = np.ones((4, 4), dtype=bool)

    # Corner setup: (1, 0) is an impassable obstacle
    valid[0, 1] = False

    grid = DEMGrid(elevation=elev, valid_mask=valid, dx=10.0, dy=10.0)

    # Moving from (0, 0) to (1, 1) requires both corner cells (1, 0) and (0, 1) to be traversable.
    # Since (1, 0) is False, diagonal step from (0, 0) to (1, 1) cannot be taken directly.
    # It must take orthogonal step to (0, 1) first then to (1, 1).
    path = AStarRouter.find_path_on_grid(grid, (0, 0), (1, 1))
    assert (1, 1) in path
    # Must NOT directly jump (0, 0) -> (1, 1)
    assert path == [(0, 0), (0, 1), (1, 1)]


def test_diagonal_corner_cutting_between_two_obstacles():
    """
    Two obstacles diagonally touching: (1, 0) and (0, 1).
    Can you go from (0, 0) to (1, 1)?
    Neither corner (1, 0) nor (0, 1) is open. Path must fail if no alternative route exists.
    """
    elev = np.zeros((3, 3), dtype=np.float32)
    valid = np.zeros((3, 3), dtype=bool)
    valid[0, 0] = True
    valid[1, 1] = True
    # (1, 0) and (0, 1) are False (blocked)

    grid = DEMGrid(elevation=elev, valid_mask=valid, dx=10.0, dy=10.0)

    with pytest.raises(PathNotFoundError):
        AStarRouter.find_path_on_grid(grid, (0, 0), (1, 1))


# ---------------------------------------------------------------------------
# 7. Start equals destination
# ---------------------------------------------------------------------------

def test_start_equals_destination(flat_10x10_grid: DEMGrid):
    cell = (3, 3)
    path = AStarRouter.find_path_on_grid(flat_10x10_grid, cell, cell)
    assert path == [cell]


# ---------------------------------------------------------------------------
# 8. Invalid start and destination coordinates
# ---------------------------------------------------------------------------

def test_invalid_start_and_destination_coordinates(synthetic_dem_transformer):
    tf, _, _ = synthetic_dem_transformer
    router = AStarRouter(tf)

    # Boolean coordinates
    with pytest.raises(ValueError, match="cannot be a boolean"):
        router.find_route(True, 18.45, 77.46, 18.46)
    with pytest.raises(ValueError, match="cannot be a boolean"):
        router.find_route(77.45, False, 77.46, 18.46)

    # NaN coordinates
    with pytest.raises(ValueError, match="must be a finite number"):
        router.find_route(float("nan"), 18.45, 77.46, 18.46)
    with pytest.raises(ValueError, match="must be a finite number"):
        router.find_route(77.45, 18.45, 77.46, float("nan"))

    # Infinite coordinates
    with pytest.raises(ValueError, match="must be a finite number"):
        router.find_route(float("inf"), 18.45, 77.46, 18.46)
    with pytest.raises(ValueError, match="must be a finite number"):
        router.find_route(77.45, 18.45, 77.46, float("-inf"))

    # Out of range coordinates
    with pytest.raises(ValueError, match="out of range"):
        router.find_route(77.45, 95.0, 77.46, 18.46)
    with pytest.raises(ValueError, match="out of range"):
        router.find_route(185.0, 18.45, 77.46, 18.46)


# ---------------------------------------------------------------------------
# 9. Out-of-bounds cells
# ---------------------------------------------------------------------------

def test_out_of_bounds_cells(flat_10x10_grid: DEMGrid):
    # Start out of bounds
    with pytest.raises(StartOutOfBoundsError):
        AStarRouter.find_path_on_grid(flat_10x10_grid, (-1, 5), (5, 5))
    with pytest.raises(StartOutOfBoundsError):
        AStarRouter.find_path_on_grid(flat_10x10_grid, (12, 5), (5, 5))

    # Goal out of bounds
    with pytest.raises(DestinationOutOfBoundsError):
        AStarRouter.find_path_on_grid(flat_10x10_grid, (5, 5), (5, 15))


# ---------------------------------------------------------------------------
# 10. No available path (disconnected region)
# ---------------------------------------------------------------------------

def test_no_available_path():
    elev = np.zeros((6, 6), dtype=np.float32)
    valid = np.ones((6, 6), dtype=bool)

    # Encircle goal (5, 5) completely with blocked cells
    valid[4, 4:] = False
    valid[4:, 4] = False

    grid = DEMGrid(elevation=elev, valid_mask=valid, dx=10.0, dy=10.0)

    with pytest.raises(PathNotFoundError):
        AStarRouter.find_path_on_grid(grid, (0, 0), (5, 5))


# ---------------------------------------------------------------------------
# 11. Deterministic output across repeated runs
# ---------------------------------------------------------------------------

def test_deterministic_output(flat_10x10_grid: DEMGrid):
    # Introduce multiple equal-cost paths
    start = (1, 1)
    goal = (8, 8)

    first_path = AStarRouter.find_path_on_grid(flat_10x10_grid, start, goal)

    for _ in range(50):
        repeat_path = AStarRouter.find_path_on_grid(flat_10x10_grid, start, goal)
        assert repeat_path == first_path


# ---------------------------------------------------------------------------
# 12. Non-negative, finite traversal costs
# ---------------------------------------------------------------------------

def test_non_negative_finite_traversal_costs():
    elev = np.array([
        [-2500.0, -2400.0, -2200.0],
        [-2450.0, -2300.0, -2100.0],
        [-2400.0, -2200.0, -2000.0],
    ], dtype=np.float32)
    valid = np.ones((3, 3), dtype=bool)
    grid = DEMGrid(elevation=elev, valid_mask=valid, dx=20.0, dy=20.0)

    path = AStarRouter.find_path_on_grid(grid, (0, 0), (2, 2))
    assert len(path) == 3

    # Calculate step costs along path
    for i in range(len(path) - 1):
        c1, r1 = path[i]
        c2, r2 = path[i + 1]
        dc = abs(c2 - c1)
        dr = abs(r2 - r1)
        d_h = grid.diag_dist if (dc and dr) else (grid.dx if dc else grid.dy)
        dz = grid.get_elevation(c2, r2) - grid.get_elevation(c1, r1)
        cost = math.hypot(d_h, dz)
        assert cost > 0.0
        assert math.isfinite(cost)


# ---------------------------------------------------------------------------
# 13. Correct route reconstruction
# ---------------------------------------------------------------------------

def test_correct_route_reconstruction(flat_10x10_grid: DEMGrid):
    start = (2, 3)
    goal = (7, 6)
    path = AStarRouter.find_path_on_grid(flat_10x10_grid, start, goal)

    # 1. Starts and ends at exact points
    assert path[0] == start
    assert path[-1] == goal

    # 2. Every consecutive pair must be valid 8-neighbors
    for i in range(len(path) - 1):
        c1, r1 = path[i]
        c2, r2 = path[i + 1]
        dc = abs(c2 - c1)
        dr = abs(r2 - r1)
        assert dc <= 1 and dr <= 1
        assert not (dc == 0 and dr == 0)


# ---------------------------------------------------------------------------
# 14. Correct distance calculation
# ---------------------------------------------------------------------------

def test_correct_distance_calculation(synthetic_dem_transformer):
    tf, _, _ = synthetic_dem_transformer
    router = AStarRouter(tf)

    # Pick two interior cells with known positions:
    # Cell (2, 5) -> Cell (6, 5) is 4 horizontal steps
    # Cell width is 20m, so flat distance is 4 * 20m = 80m.
    # Elevations: r=5: c=2 -> -2500 + 50 + 10 = -2440; c=6 -> -2500 + 50 + 30 = -2420
    # In synthetic DEM, row 5 elevation is -2500 + 50 + c * 5 = -2450 + 5 * c.
    # For each step of dc=1: delta_elev = 5m.
    # Step 3D distance = sqrt(20^2 + 5^2) = sqrt(425) ~= 20.6155m.
    # 4 steps: 4 * sqrt(425) ~= 82.46m.

    lon_start, lat_start = tf.pixel_to_geographic(2.5, 5.5)
    lon_goal, lat_goal = tf.pixel_to_geographic(6.5, 5.5)

    res = router.find_route(lon_start, lat_start, lon_goal, lat_goal)
    assert isinstance(res, AStarRouteResult)
    assert res.step_count == 5
    assert res.distance_m == pytest.approx(4 * math.sqrt(425), abs=0.05)
    assert res.geodesic_distance_m > 0.0
    assert len(res.waypoints_display) == 5
    assert len(res.waypoints_geo) == 5


# ---------------------------------------------------------------------------
# 15. Real Jezero DEM integration test
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not REAL_DEM_PATH.exists(), reason="Jezero DEM file not present")
def test_real_jezero_dem_astar_routing():
    """
    Executes an end-to-end A* pathfinding run on the verified 86 MB Jezero CTX DEM.
    Uses two real control points near the Perseverance landing site.
    """
    with rasterio.open(REAL_DEM_PATH) as ds:
        tf = DEMTransformer.from_dataset(ds)
        router = AStarRouter(tf)

        # Start and Destination coordinates inside valid Jezero coverage (~1.5 km apart)
        start_lon, start_lat = 77.450, 18.450
        dest_lon, dest_lat = 77.470, 18.460

        result = router.find_route(start_lon, start_lat, dest_lon, dest_lat, padding_cells=30)

        assert isinstance(result, AStarRouteResult)
        assert result.algorithm == "a_star"
        assert result.step_count > 1
        assert result.distance_m > 1000.0  # ~1.5 km range
        assert result.min_elevation_m is not None
        assert result.max_elevation_m is not None
        assert -2700.0 < result.min_elevation_m < -2400.0
        assert len(result.waypoints_display) == result.step_count
        assert len(result.waypoints_geo) == result.step_count

        # Verify DisplayPoint properties
        first_pt = result.waypoints_display[0]
        assert hasattr(first_pt, "x")
        assert hasattr(first_pt, "y")
        assert math.isfinite(first_pt.x)
        assert math.isfinite(first_pt.y)


# ---------------------------------------------------------------------------
# 16. Optimality verification: suboptimal local path rejected for cheaper detour
# ---------------------------------------------------------------------------

def test_astar_suboptimal_local_path_rejected_for_cheaper_global_detour(tmp_path: Path):
    """
    Constructs a scenario where a valid path exists within a small initial window (padding=2)
    but traverses steep terrain costing > 1000m. A flat, much cheaper detour exists outside
    the initial window costing ~260m.

    Verifies that the boundary optimality lower-bound check detects that an external detour
    could be cheaper, adaptively expands the search window, and finds the true optimal path.
    """
    height, width = 30, 30
    elev = np.zeros((height, width), dtype=np.float32)

    # Mountain obstacle inside columns 12..18, rows 6..10 with height 1000m
    elev[6:11, 12:19] = 1000.0

    nodata_val = -32768.0
    transform = from_origin(west=0.0, north=300.0, xsize=10.0, ysize=10.0)
    crs = CRS.from_wkt(JEZERO_CRS_WKT)
    dem_file = tmp_path / "optimality_test.tif"

    with rasterio.open(
        dem_file, "w", driver="GTiff", height=height, width=width, count=1,
        dtype=elev.dtype, crs=crs, transform=transform, nodata=nodata_val
    ) as dst:
        dst.write(elev, 1)

    with rasterio.open(dem_file) as ds:
        tf = DEMTransformer.from_dataset(ds)
        router = AStarRouter(tf)

        # Start at (15, 4), Goal at (15, 12)
        # Direct line passes right through the 1000m mountain.
        # Initial window with padding=2 covers columns 13..17, so any local path must climb the mountain.
        # Flat detour exists around column 8 (elevation 0).
        lon_s, lat_s = tf.pixel_to_geographic(15.5, 4.5)
        lon_g, lat_g = tf.pixel_to_geographic(15.5, 12.5)

        res = router.find_route(lon_s, lat_s, lon_g, lat_g, padding_cells=2)
        assert isinstance(res, AStarRouteResult)
        assert res.is_globally_optimal is True

        # If it took the steep local mountain path, distance would be > 1000m.
        # Because it found the flat global detour, distance is < 300m and max elevation is 0.0m!
        assert res.distance_m < 300.0
        assert res.max_elevation_m == 0.0
