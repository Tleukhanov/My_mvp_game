import pygame
import random
from typing import List, Tuple, Optional
from config import (
    TerrainType, CELL_SIZE, MAP_COLS, MAP_ROWS,
    COLOR_PARCHMENT, COLOR_PARCHMENT_DARK, COLOR_GRID_LINE,
    COLOR_MOUNTAIN, COLOR_MOUNTAIN_PEAK,
    COLOR_RIVER, COLOR_RIVER_DARK, COLOR_BRIDGE,
    TERRAIN_IMPASSABLE,
    COLOR_GRASS_1, COLOR_GRASS_2, COLOR_GRASS_3, COLOR_GRASS_DARK,
    COLOR_RIVER_LIGHT, COLOR_RIVER_FLOW,
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
        self._precompute_grass_variants()
        self._river_anim_offset = 0.0

    def _precompute_rects(self):
        self._rects = {}
        for row in range(self.rows):
            for col in range(self.cols):
                self._rects[(col, row)] = pygame.Rect(
                    col * CELL_SIZE, row * CELL_SIZE, CELL_SIZE, CELL_SIZE
                )

    def _precompute_grass_variants(self):
        self._grass_seed = random.Random(42)
        self._grass_variants = {}
        for row in range(self.rows):
            for col in range(self.cols):
                if self.grid[row][col] == TerrainType.PLAIN:
                    self._grass_variants[(col, row)] = self._grass_seed.choice(
                        [COLOR_GRASS_1, COLOR_GRASS_2, COLOR_GRASS_3, COLOR_GRASS_DARK]
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
        surface.fill(COLOR_GRASS_1)

        for row in range(self.rows):
            for col in range(self.cols):
                terrain = self.grid[row][col]
                rect = self._rects[(col, row)]

                if terrain == TerrainType.PLAIN:
                    grass_color = self._grass_variants.get((col, row), COLOR_GRASS_1)
                    pygame.draw.rect(surface, grass_color, rect)
                    rng = random.Random(col * 1000 + row * 7)
                    if rng.random() < 0.15:
                        gx = rect.x + rng.randint(4, CELL_SIZE - 4)
                        gy = rect.y + rng.randint(4, CELL_SIZE - 4)
                        blade_color = (grass_color[0] - 10, grass_color[1] + 8, grass_color[2] - 5)
                        blade_color = tuple(max(0, min(255, c)) for c in blade_color)
                        pygame.draw.line(surface, blade_color, (gx, gy), (gx + 1, gy - 3), 1)
                    if rng.random() < 0.08:
                        fx = rect.x + rng.randint(2, CELL_SIZE - 2)
                        fy = rect.y + rng.randint(2, CELL_SIZE - 2)
                        flower_color = rng.choice([(220, 210, 80), (240, 240, 200), (200, 180, 220)])
                        pygame.draw.circle(surface, flower_color, (fx, fy), 1)

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
                    shadow_points = [
                        (cx, cy - CELL_SIZE // 2 + 2),
                        (cx + CELL_SIZE // 3, cy + CELL_SIZE // 3),
                        (cx, cy + CELL_SIZE // 3),
                    ]
                    shadow_color = (100, 90, 80)
                    pygame.draw.polygon(surface, shadow_color, shadow_points)

                elif terrain == TerrainType.RIVER:
                    pygame.draw.rect(surface, COLOR_RIVER, rect)
                    rng = random.Random(col * 200 + row * 13)
                    for s in range(3):
                        sx = rect.x + rng.randint(2, CELL_SIZE - 4)
                        sy = rect.y + rng.randint(0, CELL_SIZE - 2)
                        sl = rng.randint(3, 7)
                        pygame.draw.line(
                            surface, COLOR_RIVER_LIGHT,
                            (sx, sy), (sx + sl, sy - 1), 1
                        )
                    bx = rect.x + rng.randint(3, CELL_SIZE - 6)
                    pygame.draw.line(
                        surface, COLOR_RIVER_DARK,
                        (bx, rect.y), (bx + 3, rect.bottom), 2
                    )
                    wave_y = rect.y + (int(self._river_anim_offset * 2 + col * 7) % CELL_SIZE)
                    if rect.y <= wave_y <= rect.bottom:
                        pygame.draw.line(
                            surface, COLOR_RIVER_FLOW,
                            (rect.x + 2, wave_y), (rect.right - 2, wave_y), 1
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

        self._river_anim_offset = (self._river_anim_offset + 0.5) % CELL_SIZE
