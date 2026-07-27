import pygame
import math
import random
from typing import Dict, Tuple, List


def _hash_noise(x: int, y: int, seed: int = 0) -> float:
    n = x * 374761393 + y * 668265263 + seed
    n = (n ^ (n >> 13)) * 1274126177
    n = n ^ (n >> 16)
    return (n & 0x7FFFFFFF) / 0x7FFFFFFF


def _smooth_noise(x: float, y: float, seed: int = 0) -> float:
    ix = int(math.floor(x))
    iy = int(math.floor(y))
    fx = x - ix
    fy = y - iy
    fx = fx * fx * (3 - 2 * fx)
    fy = fy * fy * (3 - 2 * fy)
    v00 = _hash_noise(ix, iy, seed)
    v10 = _hash_noise(ix + 1, iy, seed)
    v01 = _hash_noise(ix, iy + 1, seed)
    v11 = _hash_noise(ix + 1, iy + 1, seed)
    return (v00 * (1 - fx) + v10 * fx) * (1 - fy) + (v01 * (1 - fx) + v11 * fx) * fy


def _fbm(x: float, y: float, octaves: int = 4, seed: int = 0) -> float:
    val = 0.0
    amp = 0.5
    freq = 1.0
    for i in range(octaves):
        val += amp * _smooth_noise(x * freq, y * freq, seed + i * 31337)
        amp *= 0.5
        freq *= 2.0
    return val


def _blend_color(c1: Tuple[int, ...], c2: Tuple[int, ...], t: float) -> Tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    return (
        int(c1[0] + (c2[0] - c1[0]) * t),
        int(c1[1] + (c2[1] - c1[1]) * t),
        int(c1[2] + (c2[2] - c1[2]) * t),
    )


GRASS_COLORS = [
    (75, 120, 50), (85, 130, 55), (65, 110, 45),
    (90, 135, 60), (70, 115, 48), (80, 125, 52),
]

FOREST_COLORS = [
    (40, 90, 35), (50, 100, 40), (35, 85, 30),
    (45, 95, 38), (55, 105, 42),
]

MOUNTAIN_COLORS = [
    (120, 115, 105), (135, 128, 118), (110, 105, 95),
    (145, 140, 130), (100, 95, 85),
]

NEUTRAL_COLORS = [
    (110, 105, 95), (120, 115, 100), (100, 98, 88),
    (115, 110, 98), (105, 100, 90),
]

WATER_DEEP = (30, 55, 100)
WATER_MID = (40, 70, 120)
WATER_LIGHT = (55, 90, 145)
WATER_FOAM = (140, 170, 200)


class TextureManager:
    def __init__(self):
        self._province_cache: Dict[int, pygame.Surface] = {}
        self._water_surface: pygame.Surface = None
        self._water_size: Tuple[int, int] = (0, 0)
        self._ocean_cache: pygame.Surface = None
        self._ocean_size: Tuple[int, int] = (0, 0)

    def get_province_texture(self, province_idx: int, polygon: List[Tuple[int, int]],
                             owner: str, region_type, screen_w: int, screen_h: int) -> pygame.Surface:
        if province_idx in self._province_cache:
            return self._province_cache[province_idx]

        min_x = min(p[0] for p in polygon)
        min_y = min(p[1] for p in polygon)
        max_x = max(p[0] for p in polygon)
        max_y = max(p[1] for p in polygon)
        w = max_x - min_x
        h = max_y - min_y
        if w <= 0 or h <= 0:
            surf = pygame.Surface((1, 1), pygame.SRCALPHA)
            self._province_cache[province_idx] = surf
            return surf

        pad = 4
        surf = pygame.Surface((w + pad * 2, h + pad * 2), pygame.SRCALPHA)

        mask_surf = pygame.Surface((w + pad * 2, h + pad * 2), pygame.SRCALPHA)
        local_poly = [(x - min_x + pad, y - min_y + pad) for x, y in polygon]
        pygame.draw.polygon(mask_surf, (255, 255, 255, 255), local_poly)

        seed_val = province_idx * 7919

        if owner == "neutral":
            base_colors = NEUTRAL_COLORS
            noise_scale = 0.08
            variation = 15
        elif owner == "red":
            base_colors = [(140 + c[0] // 4, 40 + c[1] // 6, 35 + c[2] // 6) for c in GRASS_COLORS]
            noise_scale = 0.07
            variation = 12
        elif owner == "blue":
            base_colors = [(40 + c[0] // 6, 70 + c[1] // 4, 140 + c[2] // 4) for c in GRASS_COLORS]
            noise_scale = 0.07
            variation = 12
        elif owner == "green":
            base_colors = [(35 + c[0] // 6, 110 + c[1] // 4, 55 + c[2] // 5) for c in GRASS_COLORS]
            noise_scale = 0.06
            variation = 14
        else:
            base_colors = GRASS_COLORS
            noise_scale = 0.08
            variation = 15

        for py in range(h + pad * 2):
            for px in range(w + pad * 2):
                if mask_surf.get_at((px, py)).a < 128:
                    continue
                nx = (min_x + px - pad) * noise_scale
                ny = (min_y + py - pad) * noise_scale
                n = _fbm(nx, ny, 3, seed_val)

                tree_n = _fbm(nx * 2.5, ny * 2.5, 2, seed_val + 50000)
                if tree_n > 0.62 and owner != "neutral":
                    col = FOREST_COLORS[int(tree_n * 100) % len(FOREST_COLORS)]
                else:
                    ci = int(n * len(base_colors)) % len(base_colors)
                    col = base_colors[ci]

                dv = int((n - 0.5) * variation)
                col = (
                    max(0, min(255, col[0] + dv)),
                    max(0, min(255, col[1] + dv)),
                    max(0, min(255, col[2] + dv)),
                )

                edge_dist = min(
                    abs(px - pad), abs(px - w - pad),
                    abs(py - pad), abs(py - h - pad)
                )
                if edge_dist < 3:
                    dark = max(0, 1.0 - edge_dist / 3.0) * 0.3
                    col = (int(col[0] * (1 - dark)), int(col[1] * (1 - dark)), int(col[2] * (1 - dark)))

                surf.set_at((px, py), col)

        surf.blit(mask_surf, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        surf.set_colorkey(None)

        final = pygame.Surface((w + pad * 2, h + pad * 2), pygame.SRCALPHA)
        final.blit(surf, (0, 0))
        final.blit(mask_surf, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)

        self._province_cache[province_idx] = final
        return final

    def get_ocean_texture(self, w: int, h: int) -> pygame.Surface:
        if self._ocean_cache and self._ocean_size == (w, h):
            return self._ocean_cache

        surf = pygame.Surface((w, h))
        for y in range(0, h, 3):
            for x in range(0, w, 3):
                n = _fbm(x * 0.003, y * 0.003, 3, 42)
                col = _blend_color(WATER_DEEP, WATER_MID, n)
                dv = int((n - 0.5) * 15)
                col = (
                    max(0, min(255, col[0] + dv)),
                    max(0, min(255, col[1] + dv)),
                    max(0, min(255, col[2] + dv)),
                )
                pygame.draw.rect(surf, col, (x, y, 3, 3))
        self._ocean_cache = surf
        self._ocean_size = (w, h)
        return surf

    def invalidate(self):
        self._province_cache.clear()
        self._ocean_cache = None


class GeneralIcon:
    @staticmethod
    def draw_shield(surface: pygame.Surface, x: int, y: int, color: Tuple[int, int, int],
                    selected: bool = False, moved: bool = False, scale: float = 1.0):
        s = scale
        shield_pts = [
            (x, int(y - 14 * s)),
            (int(x + 11 * s), int(y - 8 * s)),
            (int(x + 10 * s), int(y + 4 * s)),
            (x, int(y + 12 * s)),
            (int(x - 10 * s), int(y + 4 * s)),
            (int(x - 11 * s), int(y - 8 * s)),
        ]

        if selected:
            glow_col = (255, 255, 100)
            for offset in [(0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)]:
                glow_pts = [(p[0] + offset[0], p[1] + offset[1]) for p in shield_pts]
                pygame.draw.polygon(surface, glow_col, glow_pts, 2)
        elif not moved:
            pygame.draw.polygon(surface, (100, 255, 100), shield_pts, 2)
        else:
            pygame.draw.polygon(surface, (120, 120, 120), shield_pts, 2)

        dark_col = (max(0, color[0] - 40), max(0, color[1] - 40), max(0, color[2] - 40))
        pygame.draw.polygon(surface, dark_col, shield_pts)

        inner_pts = [
            (x, int(y - 10 * s)),
            (int(x + 7 * s), int(y - 5 * s)),
            (int(x + 6 * s), int(y + 2 * s)),
            (x, int(y + 8 * s)),
            (int(x - 6 * s), int(y + 2 * s)),
            (int(x - 7 * s), int(y - 5 * s)),
        ]
        pygame.draw.polygon(surface, color, inner_pts)

        highlight_pts = [
            (x, int(y - 8 * s)),
            (int(x + 5 * s), int(y - 4 * s)),
            (int(x + 4 * s), int(y)),
            (x, int(y + 2 * s)),
        ]
        hl_col = (min(255, color[0] + 50), min(255, color[1] + 50), min(255, color[2] + 50))
        pygame.draw.polygon(surface, hl_col, highlight_pts)

        sword_len = int(10 * s)
        pygame.draw.line(surface, (200, 200, 210), (x, int(y - 6 * s)), (x, int(y + 6 * s)), max(1, int(2 * s)))
        cross_w = int(4 * s)
        pygame.draw.line(surface, (180, 160, 80), (x - cross_w, int(y - 2 * s)), (x + cross_w, int(y - 2 * s)), max(1, int(2 * s)))
        pygame.draw.circle(surface, (200, 200, 210), (x, int(y - 6 * s)), max(1, int(2 * s)))

        pygame.draw.polygon(surface, (255, 255, 255), shield_pts, 1)


class RiverRenderer:
    @staticmethod
    def draw_river(surface: pygame.Surface, river_x: int, cam_x: int, cam_y: int,
                   screen_h: int, time_ticks: float):
        t = time_ticks * 0.003
        points = []
        for y in range(-20, screen_h - 60, 3):
            wy = y + cam_y
            wave1 = math.sin(wy * 0.008 + t) * 14
            wave2 = math.sin(wy * 0.015 + t * 1.3) * 6
            wave3 = math.sin(wy * 0.025 + t * 0.7) * 3
            sx = river_x + wave1 + wave2 + wave3 - cam_x
            points.append((sx, y))

        if len(points) < 2:
            return

        for i in range(len(points) - 1):
            x1, y1 = points[i]
            x2, y2 = points[i + 1]
            wy = y1 + cam_y
            wave_val = math.sin(wy * 0.01 + t) * 0.5 + 0.5
            width = int(18 + wave_val * 10)

            base_col = _blend_color(WATER_DEEP, WATER_MID, wave_val)
            pygame.draw.line(surface, base_col, (int(x1), int(y1)), (int(x2), int(y2)), width)

            if random.random() < 0.08:
                sparkle_x = int(x1 + random.randint(-3, 3))
                sparkle_y = int(y1)
                sparkle_size = random.randint(1, 2)
                pygame.draw.circle(surface, WATER_FOAM, (sparkle_x, sparkle_y), sparkle_size)

        for i in range(0, len(points) - 1, 8):
            x1, y1 = points[i]
            wy = y1 + cam_y
            foam_wave = math.sin(wy * 0.02 + t * 1.5)
            if foam_wave > 0.3:
                foam_x = int(x1 + foam_wave * 4)
                foam_y = int(y1)
                pygame.draw.circle(surface, WATER_FOAM, (foam_x, foam_y), 2)

    @staticmethod
    def draw_bridge(surface: pygame.Surface, river_x: int, bridge_y: int,
                    cam_x: int, cam_y: int):
        sx = river_x - cam_x
        sy = bridge_y - cam_y
        bw, bh = 36, 16

        pygame.draw.rect(surface, (100, 80, 50),
                         (sx - bw // 2, sy - bh // 2, bw, bh))
        pygame.draw.rect(surface, (140, 115, 70),
                         (sx - bw // 2 + 2, sy - bh // 2 + 2, bw - 4, bh - 4))

        for k in range(4):
            lx = sx - bw // 2 + 5 + k * (bw // 4)
            pygame.draw.line(surface, (80, 65, 40),
                             (lx, sy - bh // 2), (lx, sy + bh // 2), 2)

        pygame.draw.line(surface, (60, 50, 35),
                         (sx - bw // 2, sy - bh // 2),
                         (sx + bw // 2, sy - bh // 2), 3)
        pygame.draw.line(surface, (60, 50, 35),
                         (sx - bw // 2, sy + bh // 2),
                         (sx + bw // 2, sy + bh // 2), 3)

        pygame.draw.rect(surface, (160, 130, 80),
                         (sx - bw // 2, sy - bh // 2, bw, bh), 1)
