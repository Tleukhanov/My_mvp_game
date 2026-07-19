import heapq
from typing import List, Tuple, Optional, Dict
from config import TerrainType, TERRAIN_MOVE_COST, CELL_SIZE


class Pathfinder:
    def __init__(self, game_map):
        self.game_map = game_map
        self._neighbors_cache: Dict[Tuple[int, int], List[Tuple[int, int]]] = {}

    def _heuristic(self, a: Tuple[int, int], b: Tuple[int, int]) -> float:
        return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5

    def _get_neighbors(self, node: Tuple[int, int]) -> List[Tuple[int, int]]:
        if node in self._neighbors_cache:
            return self._neighbors_cache[node]

        col, row = node
        neighbors = []
        for dc, dr in [(-1, 0), (1, 0), (0, -1), (0, 1),
                        (-1, -1), (1, -1), (-1, 1), (1, 1)]:
            nc, nr = col + dc, row + dr
            if self.game_map.in_bounds(nc, nr):
                terrain = self.game_map.get_terrain(nc, nr)
                if terrain not in {TerrainType.MOUNTAIN}:
                    if dc != 0 and dr != 0:
                        adj1 = self.game_map.get_terrain(col + dc, row)
                        adj2 = self.game_map.get_terrain(col, row + dr)
                        if TerrainType.MOUNTAIN in (adj1, adj2):
                            continue
                    neighbors.append((nc, nr))

        self._neighbors_cache[node] = neighbors
        return neighbors

    def find_path(
        self,
        start: Tuple[int, int],
        goal: Tuple[int, int],
        max_cost: float = 500.0,
    ) -> Optional[List[Tuple[int, int]]]:
        if not self.game_map.in_bounds(*goal):
            return None
        if not self.game_map.is_passable(*goal):
            return None

        start = (start[0], start[1])
        goal = (goal[0], goal[1])

        if start == goal:
            return [start]

        open_set = []
        heapq.heappush(open_set, (0, start))

        came_from: Dict[Tuple[int, int], Tuple[int, int]] = {}
        g_score: Dict[Tuple[int, int], float] = {start: 0.0}
        closed = set()

        while open_set:
            _, current = heapq.heappop(open_set)

            if current == goal:
                return self._reconstruct(came_from, current)

            if current in closed:
                continue
            closed.add(current)

            for neighbor in self._get_neighbors(current):
                if neighbor in closed:
                    continue

                terrain = self.game_map.get_terrain(*neighbor)
                move_cost = TERRAIN_MOVE_COST.get(terrain, 1.0)

                dc = abs(neighbor[0] - current[0])
                dr = abs(neighbor[1] - current[1])
                step_cost = (1.414 if (dc + dr == 2) else 1.0) * move_cost

                tentative_g = g_score[current] + step_cost

                if tentative_g > max_cost:
                    continue

                if tentative_g < g_score.get(neighbor, float("inf")):
                    came_from[neighbor] = current
                    g_score[neighbor] = tentative_g
                    f = tentative_g + self._heuristic(neighbor, goal)
                    heapq.heappush(open_set, (f, neighbor))

        return None

    def _reconstruct(
        self,
        came_from: Dict[Tuple[int, int], Tuple[int, int]],
        current: Tuple[int, int],
    ) -> List[Tuple[int, int]]:
        path = [current]
        while current in came_from:
            current = came_from[current]
            path.append(current)
        path.reverse()
        return path

    def grid_to_pixel_path(
        self, grid_path: List[Tuple[int, int]]
    ) -> List[Tuple[float, float]]:
        return [
            (col * CELL_SIZE + CELL_SIZE / 2, row * CELL_SIZE + CELL_SIZE / 2)
            for col, row in grid_path
        ]

    def find_path_pixels(
        self,
        start_px: float,
        start_py: float,
        goal_px: float,
        goal_py: float,
        max_cost: float = 500.0,
    ) -> Optional[List[Tuple[float, float]]]:
        start_grid = (int(start_px) // CELL_SIZE, int(start_py) // CELL_SIZE)
        goal_grid = (int(goal_px) // CELL_SIZE, int(goal_py) // CELL_SIZE)

        grid_path = self.find_path(start_grid, goal_grid, max_cost)
        if grid_path is None:
            return None
        return self.grid_to_pixel_path(grid_path)
