from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
from pyproj import CRS, Transformer
from rasterio.windows import Window

from app.scientific.dem.astar import (
    AStarPath,
    RouteNotFoundError,
    astar_search,
)
from app.scientific.dem.cost_grid import build_terrain_cost_grid


# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------

DEM_PATH = (
    Path(__file__).resolve().parents[3]
    / "data"
    / "jezero"
    / "jezero_ctx_dem_20m.tif"
)

MARS_RADIUS_M = 3_396_190.0

MAX_WINDOW_CELLS = 1_500_000

DEFAULT_GRADIENT_WEIGHT = 20.0


# ---------------------------------------------------------------------
# Exceptions and result models
# ---------------------------------------------------------------------

class RoutingDataError(RuntimeError):
    """Raised when a route cannot be computed from available terrain data."""


@dataclass(frozen=True)
class TerrainRoute:
    path: AStarPath

    # Coordinates in the DEM's native projected CRS.
    projected_points: list[tuple[float, float]]

    # Global DEM pixel coordinates: (row, column).
    start_pixel: tuple[int, int]
    destination_pixel: tuple[int, int]

    # Dimensions of the raster window used for routing.
    window_shape: tuple[int, int]

    # DEM pixel resolution in horizontal metres.
    resolution_x_m: float
    resolution_y_m: float

    # Explicitly identify the coordinate space.
    coordinate_space: str = "jezero_dem_native_projected_crs"

    # Vertical units are not verified in the supplied DEM metadata.
    vertical_units: str = "unverified"


# ---------------------------------------------------------------------
# Jezero routing service
# ---------------------------------------------------------------------

class JezeroRoutingService:
    """
    A* route planner using the real Jezero CTX DEM.

    Input:
        Mars planetocentric latitude in degrees.
        Mars positive-east longitude in degrees.

    Output:
        A* path and projected pixel-centre coordinates in the
        DEM's native projected CRS.

    Scientific limitations:
        - Elevation vertical units are not verified.
        - Returned coordinates are not frontend display coordinates.
        - The route is a terrain-cost path, not a certified astronaut
          safety route.
        - Routing is limited to a bounded raster window.
    """

    def __init__(
        self,
        dem_path: Path = DEM_PATH,
        max_window_cells: int = MAX_WINDOW_CELLS,
    ) -> None:

        self.dem_path = Path(dem_path)
        self.max_window_cells = int(max_window_cells)

        if self.max_window_cells <= 0:
            raise ValueError("max_window_cells must be positive.")

        if not self.dem_path.is_file():
            raise RoutingDataError(
                f"Jezero DEM file not found: {self.dem_path}"
            )

    # -----------------------------------------------------------------
    # CRS helpers
    # -----------------------------------------------------------------

    @staticmethod
    def _make_transformer(
        dem_crs_input,
    ) -> Transformer:
        """
        Construct a Mars geographic CRS using the Mars sphere
        and transform into the DEM's native projected CRS.

        This avoids passing terrestrial OGC:CRS84 as the source CRS.
        """

        dem_crs = CRS.from_user_input(dem_crs_input)

        mars_geographic_crs = CRS.from_proj4(
            f"+proj=longlat "
            f"+a={MARS_RADIUS_M} "
            f"+b={MARS_RADIUS_M} "
            f"+no_defs "
            f"+type=crs"
        )

        try:
            return Transformer.from_crs(
                mars_geographic_crs,
                dem_crs,
                always_xy=True,
                allow_ballpark=True,
            )
        except Exception as exc:
            raise RoutingDataError(
                "Could not construct a Mars geographic-to-DEM "
                f"coordinate transformation: {exc}"
            ) from exc

    # -----------------------------------------------------------------
    # Coordinate conversion
    # -----------------------------------------------------------------

    @staticmethod
    def _validate_coordinate(
        latitude: float,
        longitude: float,
        name: str,
    ) -> None:

        if isinstance(latitude, bool) or isinstance(longitude, bool):
            raise ValueError(f"{name} coordinates cannot be booleans.")

        if not np.isfinite(latitude) or not np.isfinite(longitude):
            raise ValueError(f"{name} coordinates must be finite.")

        if not -90.0 <= latitude <= 90.0:
            raise ValueError(f"{name} latitude must be between -90 and 90.")

        if not -180.0 <= longitude <= 180.0:
            raise ValueError(
                f"{name} longitude must be between -180 and 180."
            )

    @staticmethod
    def _projected_to_pixel(
        transform,
        x: float,
        y: float,
    ) -> tuple[int, int]:

        col_float, row_float = (~transform) @ (x, y)

        return (
            int(np.floor(row_float)),
            int(np.floor(col_float)),
        )

    # -----------------------------------------------------------------
    # Window creation
    # -----------------------------------------------------------------

    def _create_window(
        self,
        start_row: int,
        start_col: int,
        goal_row: int,
        goal_col: int,
        raster_height: int,
        raster_width: int,
    ) -> tuple[Window, int, int]:

        row_span = abs(goal_row - start_row)
        col_span = abs(goal_col - start_col)

        buffer_size = max(
            64,
            int(max(row_span, col_span) * 0.20),
        )

        row_min = max(
            0,
            min(start_row, goal_row) - buffer_size,
        )

        row_max = min(
            raster_height,
            max(start_row, goal_row) + buffer_size + 1,
        )

        col_min = max(
            0,
            min(start_col, goal_col) - buffer_size,
        )

        col_max = min(
            raster_width,
            max(start_col, goal_col) + buffer_size + 1,
        )

        height = row_max - row_min
        width = col_max - col_min

        if height <= 0 or width <= 0:
            raise RoutingDataError("Invalid terrain window.")

        if height * width > self.max_window_cells:
            raise RoutingDataError(
                "Requested route covers too large a terrain area. "
                "Choose closer waypoints or use a hierarchical planner."
            )

        return (
            Window(
                col_off=col_min,
                row_off=row_min,
                width=width,
                height=height,
            ),
            row_min,
            col_min,
        )

    # -----------------------------------------------------------------
    # Main routing operation
    # -----------------------------------------------------------------

    def compute_route(
        self,
        start_latitude: float,
        start_longitude: float,
        destination_latitude: float,
        destination_longitude: float,
        gradient_weight: float = DEFAULT_GRADIENT_WEIGHT,
    ) -> TerrainRoute:

        self._validate_coordinate(
            start_latitude,
            start_longitude,
            "Start",
        )

        self._validate_coordinate(
            destination_latitude,
            destination_longitude,
            "Destination",
        )

        if (
            isinstance(gradient_weight, bool)
            or not np.isfinite(gradient_weight)
            or gradient_weight < 0
        ):
            raise ValueError(
                "gradient_weight must be a finite non-negative number."
            )

        # -------------------------------------------------------------
        # Open DEM
        # -------------------------------------------------------------

        try:
            dataset_context = rasterio.open(self.dem_path)
        except Exception as exc:
            raise RoutingDataError(
                f"Could not open Jezero DEM: {exc}"
            ) from exc

        with dataset_context as dataset:

            if dataset.crs is None:
                raise RoutingDataError(
                    "Jezero DEM does not declare a CRS."
                )

            if dataset.count < 1:
                raise RoutingDataError(
                    "Jezero DEM contains no raster bands."
                )

            transform = dataset.transform

            # This router currently supports north-up rasters only.
            if (
                abs(transform.b) > 1e-9
                or abs(transform.d) > 1e-9
            ):
                raise RoutingDataError(
                    "Rotated DEM grids are not supported."
                )

            resolution_x = abs(float(transform.a))
            resolution_y = abs(float(transform.e))

            if (
                not np.isfinite(resolution_x)
                or not np.isfinite(resolution_y)
                or resolution_x <= 0
                or resolution_y <= 0
            ):
                raise RoutingDataError(
                    "DEM has invalid horizontal pixel resolution."
                )

            # ---------------------------------------------------------
            # Convert Mars geographic coordinates into DEM CRS
            # ---------------------------------------------------------

            transformer = self._make_transformer(dataset.crs)

            try:
                start_x, start_y = transformer.transform(
                    start_longitude,
                    start_latitude,
                    errcheck=True,
                )

                goal_x, goal_y = transformer.transform(
                    destination_longitude,
                    destination_latitude,
                    errcheck=True,
                )
            except Exception as exc:
                raise RoutingDataError(
                    f"Mars coordinate transformation failed: {exc}"
                ) from exc

            projected_values = (
                start_x,
                start_y,
                goal_x,
                goal_y,
            )

            if not all(np.isfinite(v) for v in projected_values):
                raise RoutingDataError(
                    "Coordinate transformation returned invalid values."
                )

            # ---------------------------------------------------------
            # Convert projected coordinates into global DEM pixels
            # ---------------------------------------------------------

            start_row, start_col = self._projected_to_pixel(
                transform,
                start_x,
                start_y,
            )

            goal_row, goal_col = self._projected_to_pixel(
                transform,
                goal_x,
                goal_y,
            )

            for name, row, col in (
                ("Start", start_row, start_col),
                ("Destination", goal_row, goal_col),
            ):
                if not (
                    0 <= row < dataset.height
                    and 0 <= col < dataset.width
                ):
                    raise RoutingDataError(
                        f"{name} point is outside Jezero DEM coverage."
                    )

            # ---------------------------------------------------------
            # Read only the bounded local terrain window
            # ---------------------------------------------------------

            window, row_min, col_min = self._create_window(
                start_row=start_row,
                start_col=start_col,
                goal_row=goal_row,
                goal_col=goal_col,
                raster_height=dataset.height,
                raster_width=dataset.width,
            )

            try:
                masked_elevation = dataset.read(
                    1,
                    window=window,
                    masked=True,
                )
            except Exception as exc:
                raise RoutingDataError(
                    f"Could not read DEM terrain window: {exc}"
                ) from exc

            elevation = np.asarray(
                masked_elevation.filled(np.nan),
                dtype=np.float32,
            )

            if elevation.ndim != 2:
                raise RoutingDataError(
                    "Unexpected DEM window dimensions."
                )

            # ---------------------------------------------------------
            # Build terrain cost grid
            # ---------------------------------------------------------

            terrain_grid = build_terrain_cost_grid(
                elevation=elevation,
                resolution_x_m=resolution_x,
                resolution_y_m=resolution_y,
                gradient_weight=float(gradient_weight),
            )

            local_start = (
                start_row - row_min,
                start_col - col_min,
            )

            local_goal = (
                goal_row - row_min,
                goal_col - col_min,
            )

            # ---------------------------------------------------------
            # Run A*
            # ---------------------------------------------------------

            try:
                path = astar_search(
                    terrain_grid,
                    local_start,
                    local_goal,
                )
            except RouteNotFoundError as exc:
                raise RoutingDataError(
                    f"No traversable route found: {exc}"
                ) from exc

            # ---------------------------------------------------------
            # Convert path cells to DEM-native projected coordinates
            # ---------------------------------------------------------

            projected_points: list[tuple[float, float]] = []

            for local_row, local_col in path.cells:

                global_row = row_min + local_row
                global_col = col_min + local_col

                x, y = transform @ (
                    global_col + 0.5,
                    global_row + 0.5,
                )

                projected_points.append(
                    (float(x), float(y))
                )

            return TerrainRoute(
                path=path,
                projected_points=projected_points,
                start_pixel=(start_row, start_col),
                destination_pixel=(goal_row, goal_col),
                window_shape=(
                    int(window.height),
                    int(window.width),
                ),
                resolution_x_m=resolution_x,
                resolution_y_m=resolution_y,
            )


# ---------------------------------------------------------------------
# Shared service instance
# ---------------------------------------------------------------------

jezero_routing_service = JezeroRoutingService()