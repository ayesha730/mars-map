"""
Deterministic A* surface pathfinding over Mars DEM raster grids.

Implements 8-connected grid search with:
- Strict diagonal corner-cutting prevention.
- NoData and masked collar rejection.
- Monotonic, admissible Euclidean distance heuristic.
- Deterministic canonical tie-breaking.
- Exact 3D Euclidean traversal cost model based on verified elevations.
- Explicit distinction between pixel indices, geographic coordinates,
  and arespath_display_v1 projected coordinates.
"""

from __future__ import annotations

from dataclasses import dataclass
import heapq
import math
from typing import Dict, List, Optional, Set, Tuple

import numpy as np
from rasterio.windows import Window

from app.models.schemas import DisplayPoint
from app.scientific.dem.models import CoverageStatus
from app.scientific.dem.transformer import DEMTransformer
from app.scientific.geodesy import haversine_distance, validate_coordinates


# ---------------------------------------------------------------------------
# Routing domain exceptions
# ---------------------------------------------------------------------------

class RoutingError(Exception):
    """Base exception for all AresPath routing failures."""
    pass


class StartOutOfBoundsError(RoutingError):
    """Raised when start coordinates lie outside raster bounds."""
    pass


class DestinationOutOfBoundsError(RoutingError):
    """Raised when destination coordinates lie outside raster bounds."""
    pass


class StartNoDataError(RoutingError):
    """Raised when start cell falls on NoData or masked collar terrain."""
    pass


class DestinationNoDataError(RoutingError):
    """Raised when destination cell falls on NoData or masked collar terrain."""
    pass


class PathNotFoundError(RoutingError):
    """Raised when no traversable route connects start and destination."""
    pass


# ---------------------------------------------------------------------------
# Routing result
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AStarRouteResult:
    """
    Immutable structured result of a completed A* route computation.
    """
    path_cells: List[Tuple[int, int]]
    waypoints_geo: List[Tuple[float, float]]
    waypoints_display: List[DisplayPoint]
    distance_m: float
    geodesic_distance_m: float
    min_elevation_m: Optional[float]
    max_elevation_m: Optional[float]
    step_count: int
    algorithm: str = "a_star"
    routing_domain: str = "full_raster"
    is_globally_optimal: bool = True


# ---------------------------------------------------------------------------
# Grid abstraction
# ---------------------------------------------------------------------------

class DEMGrid:
    """
    In-memory 2D terrain elevation and traversability grid.
    Supports both sub-window slices of large DEMs and direct synthetic arrays.
    """

    def __init__(
        self,
        elevation: np.ndarray,
        valid_mask: np.ndarray,
        dx: float,
        dy: float,
        origin_col: int = 0,
        origin_row: int = 0,
    ) -> None:
        if elevation.shape != valid_mask.shape:
            raise ValueError(
                f"Elevation shape {elevation.shape} must match mask shape {valid_mask.shape}"
            )
        if dx <= 0.0 or dy <= 0.0 or not math.isfinite(dx) or not math.isfinite(dy):
            raise ValueError(f"Grid resolutions dx={dx}, dy={dy} must be positive finite numbers")

        self.elevation = elevation
        self.valid_mask = valid_mask
        self.height, self.width = elevation.shape
        self.dx = float(dx)
        self.dy = float(dy)
        self.diag_dist = math.hypot(self.dx, self.dy)
        self.origin_col = origin_col
        self.origin_row = origin_row

    def is_in_bounds(self, c: int, r: int) -> bool:
        """Returns True if local grid cell (c, r) is inside bounds."""
        return 0 <= c < self.width and 0 <= r < self.height

    def is_traversable(self, c: int, r: int) -> bool:
        """Returns True if local grid cell (c, r) is in bounds, valid, and not masked."""
        if not self.is_in_bounds(c, r):
            return False
        return bool(self.valid_mask[r, c])

    def get_elevation(self, c: int, r: int) -> float:
        """Returns elevation in metres for local grid cell (c, r)."""
        return float(self.elevation[r, c])


# ---------------------------------------------------------------------------
# Deterministic A* Router
# ---------------------------------------------------------------------------

class AStarRouter:
    """
    Deterministic A* pathfinding engine over Martian elevation grids.
    """

    # 8-connected relative offsets: (dc, dr)
    # Ordered canonically: orthogonal first (E, W, S, N), then diagonal (SE, SW, NE, NW)
    NEIGHBORS_8: Tuple[Tuple[int, int], ...] = (
        (1, 0),   # East
        (-1, 0),  # West
        (0, 1),   # South
        (0, -1),  # North
        (1, 1),   # South-East
        (-1, 1),  # South-West
        (1, -1),  # North-East
        (-1, -1), # North-West
    )

    def __init__(self, transformer: Optional[DEMTransformer] = None) -> None:
        self.transformer = transformer

    @staticmethod
    def _compute_open_boundary_lower_bound(
        col_min: int,
        col_max: int,
        row_min: int,
        row_max: int,
        raster_width: int,
        raster_height: int,
        s_col: int,
        s_row: int,
        d_col: int,
        d_row: int,
        dx: float,
        dy: float,
    ) -> float:
        """
        Computes the minimum theoretical 2D Euclidean distance from start to goal
        through any open boundary cell of the current sub-grid window.

        An edge of the window is 'open' if it does not coincide with the physical
        boundary of the full regional raster. If all edges coincide with the raster
        boundary (full raster), returns float('inf').
        """
        has_open_left = (col_min > 0)
        has_open_right = (col_max < raster_width)
        has_open_top = (row_min > 0)
        has_open_bottom = (row_max < raster_height)

        if not (has_open_left or has_open_right or has_open_top or has_open_bottom):
            return float("inf")

        min_bound = float("inf")

        # Vertical open edges
        for r in range(row_min, row_max):
            if has_open_left:
                d = math.hypot((r - s_row) * dy, (col_min - s_col) * dx) + \
                    math.hypot((r - d_row) * dy, (col_min - d_col) * dx)
                if d < min_bound:
                    min_bound = d
            if has_open_right:
                d = math.hypot((r - s_row) * dy, ((col_max - 1) - s_col) * dx) + \
                    math.hypot((r - d_row) * dy, ((col_max - 1) - d_col) * dx)
                if d < min_bound:
                    min_bound = d

        # Horizontal open edges
        for c in range(col_min, col_max):
            if has_open_top:
                d = math.hypot((row_min - s_row) * dy, (c - s_col) * dx) + \
                    math.hypot((row_min - d_row) * dy, (c - d_col) * dx)
                if d < min_bound:
                    min_bound = d
            if has_open_bottom:
                d = math.hypot(((row_max - 1) - s_row) * dy, (c - s_col) * dx) + \
                    math.hypot(((row_max - 1) - d_row) * dy, (c - d_col) * dx)
                if d < min_bound:
                    min_bound = d

        return min_bound

    @staticmethod
    def _heuristic(c: int, r: int, goal_c: int, goal_r: int, dx: float, dy: float) -> float:
        """
        Admissible Euclidean distance heuristic in horizontal metres.
        Guaranteed to never overestimate remaining 3D path distance.
        """
        delta_x = (goal_c - c) * dx
        delta_y = (goal_r - r) * dy
        return math.hypot(delta_x, delta_y)

    @classmethod
    def find_path_on_grid(
        cls,
        grid: DEMGrid,
        start_cell: Tuple[int, int],
        goal_cell: Tuple[int, int],
    ) -> List[Tuple[int, int]]:
        """
        Executes deterministic A* on an in-memory DEMGrid.

        Args:
            grid: In-memory DEMGrid containing elevation, mask, and resolution.
            start_cell: (col, row) local coordinates.
            goal_cell: (col, row) local coordinates.

        Returns:
            Ordered list of (col, row) cells from start to goal inclusive.

        Raises:
            StartOutOfBoundsError: If start is out of grid bounds.
            DestinationOutOfBoundsError: If goal is out of grid bounds.
            StartNoDataError: If start is on NoData or masked terrain.
            DestinationNoDataError: If goal is on NoData or masked terrain.
            PathNotFoundError: If no valid traversable path connects start and goal.
        """
        start_c, start_r = start_cell
        goal_c, goal_r = goal_cell

        # 1. Bounds checks
        if not grid.is_in_bounds(start_c, start_r):
            raise StartOutOfBoundsError(
                f"Start cell ({start_c}, {start_r}) is outside grid dimensions ({grid.width}, {grid.height})"
            )
        if not grid.is_in_bounds(goal_c, goal_r):
            raise DestinationOutOfBoundsError(
                f"Destination cell ({goal_c}, {goal_r}) is outside grid dimensions ({grid.width}, {grid.height})"
            )

        # 2. NoData checks
        if not grid.is_traversable(start_c, start_r):
            raise StartNoDataError(
                f"Start cell ({start_c}, {start_r}) is on NoData or impassable terrain"
            )
        if not grid.is_traversable(goal_c, goal_r):
            raise DestinationNoDataError(
                f"Destination cell ({goal_c}, {goal_r}) is on NoData or impassable terrain"
            )

        # 3. Trivial path: start equals goal
        if start_cell == goal_cell:
            return [start_cell]

        # 4. A* Search Data Structures
        # Priority queue entries: (f_score, -g_score, row, col)
        # Using -g_score prioritizes nodes closer to goal on equal f_score.
        # Canonical (row, col) ties break deterministically.
        start_h = cls._heuristic(start_c, start_r, goal_c, goal_r, grid.dx, grid.dy)
        open_heap: List[Tuple[float, float, int, int]] = []
        heapq.heappush(open_heap, (start_h, 0.0, start_r, start_c))

        came_from: Dict[Tuple[int, int], Tuple[int, int]] = {}
        g_scores: Dict[Tuple[int, int], float] = {start_cell: 0.0}
        closed_set: Set[Tuple[int, int]] = set()

        while open_heap:
            _, _, curr_r, curr_c = heapq.heappop(open_heap)
            curr = (curr_c, curr_r)

            if curr in closed_set:
                continue
            closed_set.add(curr)

            # Reached goal
            if curr == goal_cell:
                # Reconstruct path
                path = [curr]
                while curr in came_from:
                    curr = came_from[curr]
                    path.append(curr)
                path.reverse()
                return path

            curr_g = g_scores[curr]
            curr_z = grid.get_elevation(curr_c, curr_r)

            for dc, dr in cls.NEIGHBORS_8:
                nbr_c = curr_c + dc
                nbr_r = curr_r + dr
                nbr = (nbr_c, nbr_r)

                if nbr in closed_set:
                    continue

                # Target must be traversable
                if not grid.is_traversable(nbr_c, nbr_r):
                    continue

                # Strict diagonal corner-cutting prevention
                if dc != 0 and dr != 0:
                    corner_1 = (curr_c + dc, curr_r)
                    corner_2 = (curr_c, curr_r + dr)
                    if not grid.is_traversable(corner_1[0], corner_1[1]) or not grid.is_traversable(corner_2[0], corner_2[1]):
                        continue
                    d_horiz = grid.diag_dist
                elif dc != 0:
                    d_horiz = grid.dx
                else:
                    d_horiz = grid.dy

                nbr_z = grid.get_elevation(nbr_c, nbr_r)
                dz = nbr_z - curr_z

                # 3D Euclidean traversal cost (strictly positive and finite)
                step_cost = math.hypot(d_horiz, dz)
                tentative_g = curr_g + step_cost

                if tentative_g < g_scores.get(nbr, float("inf")):
                    came_from[nbr] = curr
                    g_scores[nbr] = tentative_g
                    h_score = cls._heuristic(nbr_c, nbr_r, goal_c, goal_r, grid.dx, grid.dy)
                    f_score = tentative_g + h_score
                    heapq.heappush(open_heap, (f_score, -tentative_g, nbr_r, nbr_c))

        raise PathNotFoundError(
            f"No traversable route found between start {start_cell} and destination {goal_cell}"
        )

    def find_route(
        self,
        start_lon: float,
        start_lat: float,
        dest_lon: float,
        dest_lat: float,
        padding_cells: int = 50,
    ) -> AStarRouteResult:
        """
        Computes an optimal deterministic surface route between two Mars geographic points.

        Args:
            start_lon: Positive-east longitude [-180, 180] of start.
            start_lat: Planetocentric latitude [-90, 90] of start.
            dest_lon: Positive-east longitude [-180, 180] of destination.
            dest_lat: Planetocentric latitude [-90, 90] of destination.
            padding_cells: Cell buffer around start/dest bounding box for sub-grid extraction.

        Returns:
            AStarRouteResult with path waypoints, metrics, and distance.
        """
        if self.transformer is None:
            raise RoutingError("Cannot compute route: DEMTransformer is not attached to AStarRouter")
        if self.transformer.is_closed:
            raise RuntimeError("Cannot compute route: DEMTransformer is closed")
        if self.transformer.dataset is None:
            raise RoutingError("Cannot compute route: DEMTransformer has no active raster dataset")

        # 1. Validate geographic coordinates
        validate_coordinates(lat=start_lat, lon=start_lon, lon_domain="[-180, 180]")
        validate_coordinates(lat=dest_lat, lon=dest_lon, lon_domain="[-180, 180]")

        # 2. Transform start and destination coordinates
        start_res = self.transformer.transform_coordinate(lon_deg=start_lon, lat_deg=start_lat)
        dest_res = self.transformer.transform_coordinate(lon_deg=dest_lon, lat_deg=dest_lat)

        if start_res.status == CoverageStatus.OUT_OF_BOUNDS or start_res.containing_cell is None:
            raise StartOutOfBoundsError(
                f"Start coordinate ({start_lon}, {start_lat}) lies outside the DEM raster coverage"
            )
        if dest_res.status == CoverageStatus.OUT_OF_BOUNDS or dest_res.containing_cell is None:
            raise DestinationOutOfBoundsError(
                f"Destination coordinate ({dest_lon}, {dest_lat}) lies outside the DEM raster coverage"
            )

        if start_res.status == CoverageStatus.NODATA_COLLAR or not start_res.elevation_valid:
            raise StartNoDataError(
                f"Start coordinate ({start_lon}, {start_lat}) lies in a NoData or masked collar region"
            )
        if dest_res.status == CoverageStatus.NODATA_COLLAR or not dest_res.elevation_valid:
            raise DestinationNoDataError(
                f"Destination coordinate ({dest_lon}, {dest_lat}) lies in a NoData or masked collar region"
            )

        s_col = start_res.containing_cell.col
        s_row = start_res.containing_cell.row
        d_col = dest_res.containing_cell.col
        d_row = dest_res.containing_cell.row

        # 3. Adaptive search window loop:
        # Starts with padding_cells (default 50).
        # If PathNotFoundError is encountered due to local boundary obstacles,
        # the window expands adaptively until a path is found or the entire regional
        # raster bounds [0, width) x [0, height) have been exhausted.
        current_padding = padding_cells
        max_dim = max(self.transformer.width, self.transformer.height)
        ds = self.transformer.dataset
        dx = abs(self.transformer.transform.a)
        dy = abs(self.transformer.transform.e)

        local_path: List[Tuple[int, int]] = []
        chosen_col_min = 0
        chosen_row_min = 0
        chosen_elev_arr: Optional[np.ndarray] = None

        while True:
            col_min = max(0, min(s_col, d_col) - current_padding)
            col_max = min(self.transformer.width, max(s_col, d_col) + current_padding + 1)
            row_min = max(0, min(s_row, d_row) - current_padding)
            row_max = min(self.transformer.height, max(s_row, d_row) + current_padding + 1)

            win_w = col_max - col_min
            win_h = row_max - row_min
            window = Window(col_min, row_min, win_w, win_h)

            elev_arr = ds.read(1, window=window).astype(np.float32)
            mask_arr = ds.read_masks(1, window=window)

            valid_mask = (mask_arr != 0) & np.isfinite(elev_arr)
            if self.transformer.nodata is not None:
                valid_mask &= (elev_arr != self.transformer.nodata)

            grid = DEMGrid(
                elevation=elev_arr,
                valid_mask=valid_mask,
                dx=dx,
                dy=dy,
                origin_col=col_min,
                origin_row=row_min,
            )

            local_start = (s_col - col_min, s_row - row_min)
            local_goal = (d_col - col_min, d_row - row_min)

            try:
                candidate_path = self.find_path_on_grid(grid, local_start, local_goal)

                # Calculate candidate path 3D cost
                candidate_cost = 0.0
                for i in range(len(candidate_path) - 1):
                    c1, r1 = candidate_path[i]
                    c2, r2 = candidate_path[i + 1]
                    dc = abs(c2 - c1)
                    dr = abs(r2 - r1)
                    step_h = grid.diag_dist if (dc and dr) else (grid.dx if dc else grid.dy)
                    dz = float(elev_arr[r2, c2]) - float(elev_arr[r1, c1])
                    candidate_cost += math.hypot(step_h, dz)

                # Compute lower bound on any path crossing open boundaries
                open_bound = self._compute_open_boundary_lower_bound(
                    col_min=col_min,
                    col_max=col_max,
                    row_min=row_min,
                    row_max=row_max,
                    raster_width=self.transformer.width,
                    raster_height=self.transformer.height,
                    s_col=s_col,
                    s_row=s_row,
                    d_col=d_col,
                    d_row=d_row,
                    dx=dx,
                    dy=dy,
                )

                # Check if current window already encompasses the entire regional raster
                is_full_raster = (
                    col_min == 0
                    and col_max == self.transformer.width
                    and row_min == 0
                    and row_max == self.transformer.height
                )

                # Optimality verification:
                # If candidate cost <= open_bound, no path that crosses an open boundary can be cheaper!
                # Or if window is already full raster, candidate path is optimal over the full raster!
                if candidate_cost <= open_bound or is_full_raster or current_padding >= max_dim:
                    local_path = candidate_path
                    chosen_col_min = col_min
                    chosen_row_min = row_min
                    chosen_elev_arr = elev_arr
                    break
                else:
                    # A cheaper detour outside the current window is theoretically possible:
                    # expand window geometrically and re-evaluate
                    current_padding = min(current_padding * 3, max_dim)

            except PathNotFoundError:
                # Check if current window already encompasses the entire regional raster
                is_full_raster = (
                    col_min == 0
                    and col_max == self.transformer.width
                    and row_min == 0
                    and row_max == self.transformer.height
                )
                if is_full_raster or current_padding >= max_dim:
                    raise PathNotFoundError(
                        f"No traversable route connects start ({start_lon}, {start_lat}) "
                        f"and destination ({dest_lon}, {dest_lat}) across the entire regional raster."
                    )
                # Expand search padding geometrically (tripling each step)
                current_padding = min(current_padding * 3, max_dim)

        assert chosen_elev_arr is not None

        # 4. Reconstruct path in global coordinates
        global_cells: List[Tuple[int, int]] = []
        waypoints_geo: List[Tuple[float, float]] = []
        waypoints_display: List[DisplayPoint] = []
        elevations: List[float] = []

        for lc, lr in local_path:
            gc = lc + chosen_col_min
            gr = lr + chosen_row_min
            global_cells.append((gc, gr))

            # Sample cell center continuous coordinates
            cont_c = gc + 0.5
            cont_r = gr + 0.5

            # Display coordinates: projected metres (Easting, Northing)
            x_m, y_m = self.transformer.pixel_to_projected(cont_c, cont_r)
            waypoints_display.append(DisplayPoint(x=round(x_m, 2), y=round(y_m, 2)))

            # Geographic coordinates (lon_deg, lat_deg)
            lon_deg, lat_deg = self.transformer.pixel_to_geographic(cont_c, cont_r)
            waypoints_geo.append((lon_deg, lat_deg))

            elev = float(chosen_elev_arr[lr, lc])
            elevations.append(elev)

        # 6. Calculate total 3D traversal distance along the reconstructed polyline
        total_3d_dist = 0.0
        total_geo_dist = 0.0

        for i in range(len(global_cells) - 1):
            c1, r1 = global_cells[i]
            c2, r2 = global_cells[i + 1]
            z1 = elevations[i]
            z2 = elevations[i + 1]

            dc = abs(c2 - c1)
            dr = abs(r2 - r1)
            if dc != 0 and dr != 0:
                step_h = grid.diag_dist
            elif dc != 0:
                step_h = grid.dx
            else:
                step_h = grid.dy

            step_3d = math.hypot(step_h, z2 - z1)
            total_3d_dist += step_3d

            lon1, lat1 = waypoints_geo[i]
            lon2, lat2 = waypoints_geo[i + 1]
            total_geo_dist += haversine_distance(lat1, lon1, lat2, lon2)

        min_elev = min(elevations) if elevations else None
        max_elev = max(elevations) if elevations else None

        return AStarRouteResult(
            path_cells=global_cells,
            waypoints_geo=waypoints_geo,
            waypoints_display=waypoints_display,
            distance_m=round(total_3d_dist, 2),
            geodesic_distance_m=round(total_geo_dist, 2),
            min_elevation_m=round(min_elev, 2) if min_elev is not None else None,
            max_elevation_m=round(max_elev, 2) if max_elev is not None else None,
            step_count=len(global_cells),
            algorithm="a_star",
        )
