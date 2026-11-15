from __future__ import annotations

import heapq
import math
from dataclasses import dataclass

from app.scientific.dem.cost_grid import TerrainCostGrid


class RouteNotFoundError(RuntimeError):
    """Raised when no traversable path connects the requested cells."""


@dataclass(frozen=True)
class AStarPath:
    cells: list[tuple[int, int]]
    distance_m: float
    total_cost: float


def astar_search(
    grid: TerrainCostGrid,
    start: tuple[int, int],
    goal: tuple[int, int],
) -> AStarPath:
    """
    Find a minimum-relative-cost path through a terrain cost grid.

    Coordinates are (row, column).
    Diagonal corner-cutting is prohibited.
    """

    rows, cols = grid.traversable.shape

    if grid.cost.shape != (rows, cols):
        raise ValueError("Cost and traversability arrays must have equal shapes.")

    if grid.traversable.shape != grid.elevation.shape:
        raise ValueError("Elevation and traversability arrays must have equal shapes.")

    if (
        not math.isfinite(grid.resolution_x_m)
        or not math.isfinite(grid.resolution_y_m)
        or grid.resolution_x_m <= 0
        or grid.resolution_y_m <= 0
    ):
        raise ValueError("Grid resolutions must be finite and positive.")

    def validate_cell(cell: tuple[int, int], name: str) -> None:
        if (
            not isinstance(cell, tuple)
            or len(cell) != 2
            or any(isinstance(v, bool) or not isinstance(v, int) for v in cell)
        ):
            raise ValueError(f"{name} must be a (row, column) integer tuple.")

        row, col = cell
        if not (0 <= row < rows and 0 <= col < cols):
            raise ValueError(f"{name} lies outside the terrain grid.")

        if not grid.traversable[row, col]:
            raise RouteNotFoundError(f"{name} is not traversable.")

        if not math.isfinite(float(grid.cost[row, col])) or grid.cost[row, col] <= 0:
            raise ValueError(f"{name} has an invalid terrain cost.")

    validate_cell(start, "Start")
    validate_cell(goal, "Goal")

    if start == goal:
        return AStarPath(cells=[start], distance_m=0.0, total_cost=0.0)

    traversable_costs = grid.cost[grid.traversable]
    if traversable_costs.size == 0:
        raise RouteNotFoundError("The terrain grid has no traversable cells.")

    minimum_cost = float(traversable_costs.min())

    def heuristic(cell: tuple[int, int]) -> float:
        dr = abs(goal[0] - cell[0]) * grid.resolution_y_m
        dc = abs(goal[1] - cell[1]) * grid.resolution_x_m
        return math.hypot(dr, dc) * minimum_cost

    # Eight possible moves: row offset, column offset.
    directions = (
        (-1, 0),
        (1, 0),
        (0, -1),
        (0, 1),
        (-1, -1),
        (-1, 1),
        (1, -1),
        (1, 1),
    )

    frontier: list[tuple[float, float, int, int]] = []
    heapq.heappush(frontier, (heuristic(start), 0.0, start[0], start[1]))

    came_from: dict[tuple[int, int], tuple[int, int]] = {}
    best_cost = {start: 0.0}
    closed: set[tuple[int, int]] = set()

    while frontier:
        _, current_cost, row, col = heapq.heappop(frontier)
        current = (row, col)

        if current in closed:
            continue

        if current_cost > best_cost.get(current, math.inf):
            continue

        if current == goal:
            cells = [goal]
            while cells[-1] != start:
                cells.append(came_from[cells[-1]])
            cells.reverse()

            distance = 0.0
            for first, second in zip(cells, cells[1:]):
                dr = abs(second[0] - first[0]) * grid.resolution_y_m
                dc = abs(second[1] - first[1]) * grid.resolution_x_m
                distance += math.hypot(dr, dc)

            return AStarPath(
                cells=cells,
                distance_m=distance,
                total_cost=best_cost[goal],
            )

        closed.add(current)

        for dr, dc in directions:
            next_cell = (row + dr, col + dc)
            nr, nc = next_cell

            if not (0 <= nr < rows and 0 <= nc < cols):
                continue

            if next_cell in closed or not grid.traversable[nr, nc]:
                continue

            diagonal = dr != 0 and dc != 0

            # A diagonal move is allowed only when both adjacent
            # orthogonal cells are traversable.
            if diagonal:
                if (
                    not grid.traversable[row + dr, col]
                    or not grid.traversable[row, col + dc]
                ):
                    continue

            step_y = abs(dr) * grid.resolution_y_m
            step_x = abs(dc) * grid.resolution_x_m
            step_distance = math.hypot(step_x, step_y)

            average_terrain_cost = (
                float(grid.cost[row, col]) + float(grid.cost[nr, nc])
            ) / 2.0

            tentative_cost = (
                current_cost + step_distance * average_terrain_cost
            )

            if tentative_cost >= best_cost.get(next_cell, math.inf):
                continue

            came_from[next_cell] = current
            best_cost[next_cell] = tentative_cost

            heapq.heappush(
                frontier,
                (
                    tentative_cost + heuristic(next_cell),
                    tentative_cost,
                    nr,
                    nc,
                ),
            )

    raise RouteNotFoundError("No traversable path connects the selected cells.")