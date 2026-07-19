import pygame
import random
from typing import List, Tuple, Optional
from config import (
    TerrainType, CELL_SIZE, MAP_COLS, MAP_ROWS,
    COLOR_PARCHMENT, COLOR_PARCHMENT_DARK, COLOR_GRID_LINE,
    COLOR_MOUNTAIN, COLOR_MOUNTAIN_PEAK,
    COLOR_RIVER, COLOR_RIVER_DARK, COLOR_BRIDGE,
    TERRAIN_IMPASSABLE,
)


class TacticalMap:
    def __init__(self, grid: Optional[List[List[TerrainType]]] = None):
        if grid is not None:
            self.grid = grid
            self.rows = len(grid)
            self.cols = len(grid[0]) if self.rows > 0 else 0
        else:
            self.cols = MAP_COLS
            self.rows = MAP_ROWS
            self.grid = self._generate_default_map()
        self._precompute_rects()

    def _precompute_rects(self):
        self._rects = {}
        for row in range(self.rows):
            for col in range(self.cols):
                self._rects[(col, row)] = pygame.Rect(
                    col * CELL_SIZE, row * CELL_SIZE, CELL_SIZE, CELL_SIZE
                )

    def _generate_default_map(self) -> List[List[TerrainType]]:
        grid = [[TerrainType.PLAIN for _ in range(self.cols)] for _ in range(self.rows)]

        mountain_ranges = [
            ((18, 0), (22, 0)),
            ((17, 1), (23, 1)),
            ((17, 2), (23, 2)),
            ((18, 3), (22, 3)),
            ((19, 4), (21, 4)),
        ]
        for (c1, r1), (c2, r2) in mountain_ranges:
            for c in range(c1, c2 + 1):
                for r in range(r1, r2 + 1):
                    if 0 <= c < self.cols and 0 <= r < self.rows:
                        grid[r][c] = TerrainType.MOUNTAIN

        river_cols = [12, 13, 14]
        for r in range(self.rows):
            for c in river_cols:
                if 0 <= c < self.cols and 0 <= r < self.rows:
                    grid[r][c] = TerrainType.RIVER

        bridges = [(13, 8), (13, 9), (13, 10), (13, 13), (13, 14), (13, 15)]
        for c, r in bridges:
            if 0 <= c < self.cols and 0 <= r < self.rows:
                grid[r][c] = TerrainType.BRIDGE

        second_river = [28, 29]
        for r in range(6, 18):
            for c in second_river:
                if 0 <= c < self.cols and 0 <= r < self.rows:
                    grid[r][c] = TerrainType.RIVER

        extra_bridges = [(28, 10), (28, 11), (28, 12)]
        for c, r in extra_bridges:
            if 0 <= c < self.cols and 0 <= r < self.rows:
                grid[r][c] = TerrainType.BRIDGE

        sparse_mountains = [
            (5, 5), (6, 5), (5, 6),
            (34, 4), (35, 4), (35, 5),
            (6, 16), (7, 16), (7, 17),
            (33, 16), (34, 16), (34, 17),
        ]
        for c, r in sparse_mountains:
            if 0 <= c < self.cols and 0 <= r < self.rows:
                grid[r][c] = TerrainType.MOUNTAIN

        return grid

    def in_bounds(self, col: int, row: int) -> bool:
        return 0 <= col < self.cols and 0 <= row < self.rows

    def get_terrain(self, col: int, row: int) -> TerrainType:
        if not self.in_bounds(col, row):
            return TerrainType.MOUNTAIN
        return self.grid[row][col]

    def is_passable(self, col: int, row: int) -> bool:
        return self.get_terrain(col, row) not in TERRAIN_IMPASSABLE

    def pixel_to_grid(self, px: int, py: int) -> Tuple[int, int]:
        return px // CELL_SIZE, py // CELL_SIZE

    def grid_to_pixel_center(self, col: int, row: int) -> Tuple[float, float]:
        return col * CELL_SIZE + CELL_SIZE / 2, row * CELL_SIZE + CELL_SIZE / 2

    def render(self, surface: pygame.Surface):
        surface.fill(COLOR_PARCHMENT)

        for row in range(self.rows):
            for col in range(self.cols):
                terrain = self.grid[row][col]
                rect = self._rects[(col, row)]

                if terrain == TerrainType.PLAIN:
                    pygame.draw.rect(surface, COLOR_PARCHMENT, rect)
                    if (col + row) % 3 == 0:
                        pygame.draw.rect(surface, COLOR_PARCHMENT_DARK, rect)

                elif terrain == TerrainType.MOUNTAIN:
                    pygame.draw.rect(surface, COLOR_MOUNTAIN, rect)
                    cx = col * CELL_SIZE + CELL_SIZE // 2
                    cy = row * CELL_SIZE + CELL_SIZE // 2
                    peak_points = [
                        (cx, cy - CELL_SIZE // 2 + 2),
                        (cx - CELL_SIZE // 3, cy + CELL_SIZE // 3),
                        (cx + CELL_SIZE // 3, cy + CELL_SIZE // 3),
                    ]
                    pygame.draw.polygon(surface, COLOR_MOUNTAIN_PEAK, peak_points)
                    pygame.draw.polygon(surface, COLOR_PARCHMENT, peak_points, 1)

                elif terrain == TerrainType.RIVER:
                    pygame.draw.rect(surface, COLOR_RIVER, rect)
                    rx = rect.x + random.Random(col * 100 + row).randint(4, 10)
                    pygame.draw.line(
                        surface, COLOR_RIVER_DARK,
                        (rx, rect.y), (rx + 5, rect.bottom), 2
                    )

                elif terrain == TerrainType.BRIDGE:
                    pygame.draw.rect(surface, COLOR_RIVER, rect)
                    bx1 = rect.x + 2
                    bx2 = rect.right - 2
                    by1 = rect.y + 4
                    by2 = rect.bottom - 4
                    pygame.draw.line(surface, COLOR_BRIDGE, (bx1, by1), (bx1, by2), 3)
                    pygame.draw.line(surface, COLOR_BRIDGE, (bx2, by1), (bx2, by2), 3)
                    for i in range(3):
                        my = rect.y + 5 + i * 8
                        pygame.draw.line(surface, COLOR_BRIDGE, (bx1, my), (bx2, my), 2)

                pygame.draw.rect(surface, COLOR_GRID_LINE, rect, 1)
