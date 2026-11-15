from dataclasses import dataclass

import numpy as np


@dataclass
class TerrainCostGrid:
    elevation: np.ndarray
    gradient: np.ndarray
    traversable: np.ndarray
    cost: np.ndarray
    resolution_x_m: float
    resolution_y_m: float


def build_terrain_cost_grid(
    elevation: np.ndarray,
    resolution_x_m: float,
    resolution_y_m: float,
    gradient_weight: float = 20.0,
) -> TerrainCostGrid:
    """
    Build a relative terrain-cost grid from a DEM array.

    Gradient is calculated with Horn's 3x3 method.
    NoData cells and cells without a complete valid neighborhood
    are marked non-traversable.

    Gradient units remain raw elevation units per horizontal metre
    until the DEM's vertical units are verified.
    """

    if elevation.ndim != 2:
        raise ValueError("Elevation data must be a 2D array.")

    if elevation.shape[0] < 3 or elevation.shape[1] < 3:
        raise ValueError("Elevation grid must be at least 3x3.")

    if resolution_x_m <= 0 or resolution_y_m <= 0:
        raise ValueError("Pixel resolutions must be positive.")

    if gradient_weight < 0:
        raise ValueError("Gradient weight cannot be negative.")

    values = np.asarray(elevation, dtype=np.float64)
    valid = np.isfinite(values)

    # Interior cells only: each needs a complete 3x3 neighborhood.
    center_valid = valid[1:-1, 1:-1]

    neighborhood_valid = (
        valid[:-2, :-2]
        & valid[:-2, 1:-1]
        & valid[:-2, 2:]
        & valid[1:-1, :-2]
        & valid[1:-1, 1:-1]
        & valid[1:-1, 2:]
        & valid[2:, :-2]
        & valid[2:, 1:-1]
        & valid[2:, 2:]
    )

    z1 = values[:-2, :-2]
    z2 = values[:-2, 1:-1]
    z3 = values[:-2, 2:]
    z4 = values[1:-1, :-2]
    z6 = values[1:-1, 2:]
    z7 = values[2:, :-2]
    z8 = values[2:, 1:-1]
    z9 = values[2:, 2:]

    dz_dx = (
        (z3 + 2 * z6 + z9) - (z1 + 2 * z4 + z7)
    ) / (8.0 * resolution_x_m)

    dz_dy = (
        (z1 + 2 * z2 + z3) - (z7 + 2 * z8 + z9)
    ) / (8.0 * resolution_y_m)

    gradient_inner = np.hypot(dz_dx, dz_dy)

    gradient = np.full(values.shape, np.nan, dtype=np.float64)
    gradient[1:-1, 1:-1] = gradient_inner

    traversable = np.zeros(values.shape, dtype=bool)
    traversable[1:-1, 1:-1] = center_valid & neighborhood_valid

    # Relative cost: 1.0 base movement cost plus a gradient penalty.
    cost = np.full(values.shape, np.inf, dtype=np.float64)
    cost[traversable] = (
        1.0 + gradient_weight * gradient[traversable]
    )

    return TerrainCostGrid(
        elevation=values,
        gradient=gradient,
        traversable=traversable,
        cost=cost,
        resolution_x_m=float(resolution_x_m),
        resolution_y_m=float(resolution_y_m),
    )