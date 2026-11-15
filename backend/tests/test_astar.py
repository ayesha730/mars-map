import numpy as np
import pytest

from app.scientific.dem.cost_grid import build_terrain_cost_grid
from app.scientific.dem.astar import (
    RouteNotFoundError,
    astar_search,
)


def make_grid(size=9):
    elevation = np.zeros((size, size), dtype=float)
    return build_terrain_cost_grid(elevation, 20.0, 20.0)


def test_astar_finds_path_on_flat_grid():
    grid = make_grid()

    result = astar_search(grid, (2, 2), (6, 6))

    assert result.cells[0] == (2, 2)
    assert result.cells[-1] == (6, 6)
    assert result.distance_m > 0
    assert result.total_cost > 0


def test_astar_uses_diagonal_distance():
    grid = make_grid()

    result = astar_search(grid, (2, 2), (4, 4))

    assert result.distance_m == pytest.approx(
        2 * np.sqrt(20.0**2 + 20.0**2)
    )


def test_astar_rejects_non_traversable_start():
    grid = make_grid()

    with pytest.raises(RouteNotFoundError):
        astar_search(grid, (0, 0), (6, 6))


def test_astar_rejects_out_of_bounds_start():
    grid = make_grid()

    with pytest.raises(ValueError):
        astar_search(grid, (-1, 2), (6, 6))


def test_astar_rejects_disconnected_regions():
    elevation = np.zeros((9, 9), dtype=float)
    grid = build_terrain_cost_grid(elevation, 20.0, 20.0)

    # A complete blocked row separates the two sides.
    grid.traversable[4, :] = False
    grid.cost[4, :] = np.inf

    with pytest.raises(RouteNotFoundError):
        astar_search(grid, (2, 2), (6, 6))


def test_astar_does_not_cut_diagonal_corners():
    grid = make_grid()

    # Block both orthogonal neighbors of a diagonal transition.
    grid.traversable[2, 3] = False
    grid.traversable[3, 2] = False
    grid.cost[2, 3] = np.inf
    grid.cost[3, 2] = np.inf

    result = astar_search(grid, (2, 2), (3, 3))

    assert result.cells[0] == (2, 2)
    assert result.cells[-1] == (3, 3)
    assert (2, 3) not in result.cells
    assert (3, 2) not in result.cells


def test_astar_same_start_and_goal():
    grid = make_grid()

    result = astar_search(grid, (3, 3), (3, 3))

    assert result.cells == [(3, 3)]
    assert result.distance_m == 0
    assert result.total_cost == 0