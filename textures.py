import hashlib
import os
import pygame
import math
import random
from typing import Dict, Tuple, List


#: Каталог для кэша сгенерированных текстур — рядом с этим модулем.
ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


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


# Наполеоновский пергамент: оливково-хаки база как на референсе
PARCHMENT_BASE = [
    (118, 114, 72), (112, 108, 68), (124, 119, 76),
    (106, 102, 64), (115, 111, 70), (121, 116, 74),
]
PARCHMENT_DARK = (88, 86, 54)
PARCHMENT_LIGHT = (138, 133, 88)

GRASS_COLORS = PARCHMENT_BASE

FOREST_COLORS = [
    (58, 62, 34), (66, 70, 38), (52, 56, 30),
    (72, 74, 42), (60, 64, 36),
]

FIELD_COLORS = [
    (130, 124, 80), (104, 100, 62), (136, 130, 84),
    (96, 94, 58),
]

MOUNTAIN_COLORS = [
    (120, 115, 105), (135, 128, 118), (110, 105, 95),
    (145, 140, 130), (100, 95, 85),
]

NEUTRAL_COLORS = PARCHMENT_BASE

# приглушённые оттенки владельцев — только лёгкий налёт поверх пергамента
OWNER_TINT = {
    "neutral": None,
    "red": (150, 70, 55),
    "blue": (80, 100, 150),
    "green": (80, 125, 75),
}

WATER_DEEP = (52, 58, 44)
WATER_MID = (72, 74, 56)
WATER_LIGHT = (96, 96, 72)
WATER_FOAM = (160, 155, 125)

RIVER_COLOR = (120, 140, 170)
RIVER_DARK = (90, 110, 145)
RIVER_LIGHT = (165, 185, 210)


#: Текстуры провинций рисуются в уменьшенном разрешении и растягиваются.
#: Пергамент — фон под подписями, детализация ему не нужна, а экономия
#: в 4 раза по пикселям превращает минуту ожидания в пару секунд.
PROVINCE_DETAIL = 2
PROVINCE_PAD = 4


class TextureManager:
    def __init__(self):
        self._province_cache: Dict[tuple, pygame.Surface] = {}
        self._province_base_cache: Dict[int, pygame.Surface] = {}
        self._water_surface: pygame.Surface = None
        self._water_size: Tuple[int, int] = (0, 0)
        self._ocean_cache: pygame.Surface = None
        self._ocean_size: Tuple[int, int] = (0, 0)

    def _tint_factor(self, owner: str) -> Tuple[int, int, int]:
        """Множитель цвета владельца: 82% пергамента + 18% цвета нации.

        Считается так, что обычный ``BLEND_RGB_MULT`` даёт ровно нужную
        примесь — поэтому перекраска провинции при захвате стоит один
        быстрый блит, а не перегенерацию текстуры попиксельно.
        """
        tint = OWNER_TINT.get(owner)
        base = 0.82 * 255
        if tint is None:
            v = int(base)
            return (v, v, v)
        return (
            min(255, int(base + 0.18 * tint[0])),
            min(255, int(base + 0.18 * tint[1])),
            min(255, int(base + 0.18 * tint[2])),
        )

    def get_province_texture(self, province_idx: int, polygon: List[Tuple[int, int]],
                             owner: str, region_type, screen_w: int, screen_h: int) -> pygame.Surface:
        # ключ включает владельца — иначе захват не меняет цвет
        key = (province_idx, owner)
        if key in self._province_cache:
            return self._province_cache[key]

        base = self._get_province_base(province_idx, polygon)
        tinted = base.copy()
        factor = self._tint_factor(owner)
        if factor != (208, 208, 208):
            tinted.fill(factor, special_flags=pygame.BLEND_RGB_MULT)

        # чистим старый цвет той же провинции, чтобы не рос кэш
        for k in [k for k in self._province_cache if k[0] == province_idx]:
            self._province_cache.pop(k, None)
        self._province_cache[key] = tinted
        return tinted

    def _base_cache_path(self, province_idx: int, polygon: List[Tuple[int, int]]) -> str:
        """Путь к файлу базовой текстуры.

        Хеш геометрии входит в имя: если границы провинции изменились,
        старый файл просто не найдётся и текстура перегенерируется.
        Без этого перегенерация всех 50 провинций занимала бы 15 секунд
        при каждом входе в мировую карту.
        """
        digest = hashlib.md5(repr(tuple(polygon)).encode("utf-8")).hexdigest()[:10]
        return os.path.join(ASSETS_DIR, f"base_{province_idx:02d}_{digest}.png")

    def _get_province_base(self, province_idx: int,
                           polygon: List[Tuple[int, int]]) -> pygame.Surface:
        """Пергамент провинции без цвета владельца.

        Кэшируется дважды: в памяти и на диске. Файл валиден, только если
        в его имени совпадает хеш геометрии.
        """
        if province_idx in self._province_base_cache:
            return self._province_base_cache[province_idx]

        path = self._base_cache_path(province_idx, polygon)
        final = None
        if os.path.isfile(path):
            try:
                loaded = pygame.image.load(path)
                if (loaded.get_width(), loaded.get_height()) == self._base_size(polygon):
                    final = loaded.convert_alpha()
            except Exception:
                final = None

        if final is None:
            final = self._render_province_base(province_idx, polygon)
            try:
                os.makedirs(ASSETS_DIR, exist_ok=True)
                pygame.image.save(final, path)
            except Exception:
                pass

        self._province_base_cache[province_idx] = final
        return final

    def _base_size(self, polygon: List[Tuple[int, int]]) -> Tuple[int, int]:
        xs = [p[0] for p in polygon]
        ys = [p[1] for p in polygon]
        return ((max(xs) - min(xs)) + PROVINCE_PAD * 2,
                (max(ys) - min(ys)) + PROVINCE_PAD * 2)

    def _render_province_base(self, province_idx: int,
                              polygon: List[Tuple[int, int]]) -> pygame.Surface:
        """Пергамент провинции без цвета владельца. Генерируется один раз."""
        if province_idx in self._province_base_cache:
            return self._province_base_cache[province_idx]

        min_x = min(p[0] for p in polygon)
        min_y = min(p[1] for p in polygon)
        max_x = max(p[0] for p in polygon)
        max_y = max(p[1] for p in polygon)
        full_w = max_x - min_x
        full_h = max_y - min_y
        if full_w <= 0 or full_h <= 0:
            surf = pygame.Surface((1, 1), pygame.SRCALPHA)
            self._province_base_cache[province_idx] = surf
            return surf

        out_w = full_w + PROVINCE_PAD * 2
        out_h = full_h + PROVINCE_PAD * 2

        detail = PROVINCE_DETAIL
        work_w = max(1, full_w // detail)
        work_h = max(1, full_h // detail)
        wpad = 1
        size = (work_w + wpad * 2, work_h + wpad * 2)

        surf = pygame.Surface(size, pygame.SRCALPHA)
        mask_surf = pygame.Surface(size, pygame.SRCALPHA)
        local_poly = [((x - min_x) // detail + wpad, (y - min_y) // detail + wpad)
                      for x, y in polygon]
        pygame.draw.polygon(mask_surf, (255, 255, 255, 255), local_poly)

        seed_val = province_idx * 7919
        base_colors = PARCHMENT_BASE
        noise_scale = 0.02

        # тёмные пятна-леса для этой провинции (как тени на референсе)
        rng = random.Random(seed_val)
        blobs = [(rng.randint(0, work_w), rng.randint(0, work_h),
                  max(3, rng.randint(6, 16)))
                 for _ in range(3)]

        for py in range(size[1]):
            for px in range(size[0]):
                if mask_surf.get_at((px, py)).a < 128:
                    continue
                wx = min_x + (px - wpad) * detail
                wy = min_y + (py - wpad) * detail
                n = _fbm(wx * noise_scale, wy * noise_scale, 3, seed_val)
                grain = _hash_noise(px, py, seed_val) - 0.5

                # лоскутные поля как на скриншоте
                field_n = _fbm(wx * 0.008, wy * 0.008, 1, seed_val + 999)
                if 0.52 < field_n < 0.60:
                    col = FIELD_COLORS[int(field_n * 100) % len(FIELD_COLORS)]
                else:
                    ci = int(n * len(base_colors)) % len(base_colors)
                    col = base_colors[ci]

                # лес-тень
                for bx, by, br in blobs:
                    d2 = (px - bx) ** 2 + (py - by) ** 2
                    if d2 < br * br:
                        k = 1.0 - (d2 / (br * br)) ** 0.5
                        col = (int(col[0] * (1 - 0.35 * k)),
                               int(col[1] * (1 - 0.35 * k)),
                               int(col[2] * (1 - 0.30 * k)))
                        break

                dv = int((n - 0.5) * 16 + grain * 10)
                col = (
                    max(0, min(255, col[0] + dv)),
                    max(0, min(255, col[1] + dv)),
                    max(0, min(255, col[2] + dv)),
                )
                surf.set_at((px, py), col)

        # растягиваем до рабочего размера с отступами
        if size != (out_w, out_h):
            try:
                surf = pygame.transform.smoothscale(surf, (out_w, out_h))
                mask_surf = pygame.transform.smoothscale(mask_surf, (out_w, out_h))
            except Exception:
                pass

        surf.blit(mask_surf, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        surf.set_colorkey(None)

        final = pygame.Surface((out_w, out_h), pygame.SRCALPHA)
        final.blit(surf, (0, 0))
        final.blit(mask_surf, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)

        self._province_base_cache[province_idx] = final
        return final

    def get_ocean_texture(self, w: int, h: int) -> pygame.Surface:
        if self._ocean_cache and self._ocean_size == (w, h):
            return self._ocean_cache

        surf = pygame.Surface((w, h))
        for y in range(0, h, 4):
            for x in range(0, w, 4):
                n = _fbm(x * 0.004, y * 0.004, 3, 42)
                col = _blend_color(WATER_DEEP, WATER_MID, n)
                grain = int((_hash_noise(x, y, 7) - 0.5) * 8)
                col = (
                    max(0, min(255, col[0] + grain)),
                    max(0, min(255, col[1] + grain)),
                    max(0, min(255, col[2] + grain)),
                )
                pygame.draw.rect(surf, col, (x, y, 4, 4))
        self._ocean_cache = surf
        self._ocean_size = (w, h)
        return surf

    def invalidate(self, province_idx: int = None, owner: str = None):
        """Сброс кэша. Без аргументов — весь; иначе по провинции и/или владельцу."""
        if province_idx is None:
            self._province_cache.clear()
            self._province_base_cache.clear()
            return
        for k in [k for k in self._province_cache
                  if k[0] == province_idx and (owner is None or k[1] == owner)]:
            self._province_cache.pop(k, None)
        if owner is None:
            self._province_base_cache.pop(province_idx, None)
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

    @staticmethod
    def draw_banner(surface: pygame.Surface, x: int, y: int, color: Tuple[int, int, int],
                    selected: bool = False, moved: bool = False, scale: float = 1.0,
                    label: str = ""):
        """Наполеоновский флажок-баннер как на референсе: древко + знамя."""
        s = scale
        pole_h = int(30 * s)
        # тень
        pygame.draw.ellipse(surface, (0, 0, 0, 90),
                            (int(x - 10 * s), int(y + 12 * s), int(20 * s), int(6 * s)))
        # древко
        pygame.draw.line(surface, (45, 35, 25), (x, y - pole_h * s), (x, y + 12 * s), max(1, int(2 * s)))
        pygame.draw.circle(surface, (190, 170, 100), (x, int(y - pole_h * s)), max(2, int(3 * s)))
        # знамя
        fw, fh = int(30 * s), int(20 * s)
        top = int(y - pole_h * s)
        flag = [(x, top), (x + fw, top + 2), (x + fw, top + fh), (x, top + fh - 2)]
        dark = (max(0, color[0] - 50), max(0, color[1] - 50), max(0, color[2] - 50))
        pygame.draw.polygon(surface, dark, [(p[0] + 1, p[1] + 1) for p in flag])
        pygame.draw.polygon(surface, (235, 225, 200), flag)
        inner = [(x + 2, top + 2), (x + fw - 2, top + 4), (x + fw - 2, top + fh - 2), (x + 2, top + fh - 4)]
        pygame.draw.polygon(surface, color, inner)
        # крест/полоса по центру как у корпусных знамён
        pygame.draw.line(surface, (235, 225, 200),
                         (x + fw // 2, top + 3), (x + fw // 2, top + fh - 3), 2)
        pygame.draw.line(surface, (235, 225, 200),
                         (x + 3, top + fh // 2), (x + fw - 3, top + fh // 2 + 1), 1)
        # обводка статуса
        if selected:
            pygame.draw.polygon(surface, (255, 255, 120), flag, 2)
        elif not moved:
            pygame.draw.polygon(surface, (140, 255, 140), flag, 1)
        else:
            pygame.draw.polygon(surface, (150, 145, 130), flag, 1)
        # табличка с именем под флагом
        if label:
            try:
                f = pygame.font.SysFont("serif", max(10, int(12 * s)))
            except Exception:
                f = pygame.font.SysFont(None, max(10, int(12 * s)))
            txt = f.render(label, True, (240, 230, 200))
            bg = pygame.Surface((txt.get_width() + 6, txt.get_height() + 2), pygame.SRCALPHA)
            bg.fill((20, 18, 12, 190))
            surface.blit(bg, (x - bg.get_width() // 2, y + 12 * s))
            surface.blit(txt, (x - txt.get_width() // 2, y + 12 * s + 1))


class RiverRenderer:
    @staticmethod
    def river_points(river_x: int, cam_y: int, screen_h: int, time_ticks: float, seed: int = 0):
        t = time_ticks * 0.0006
        points = []
        for y in range(-20, screen_h - 60, 4):
            wy = y + cam_y
            wave1 = math.sin(wy * 0.008 + seed + t) * 16
            wave2 = math.sin(wy * 0.017 + seed * 2 + t * 1.2) * 8
            wave3 = math.sin(wy * 0.033 + seed * 3) * 4
            points.append((river_x + wave1 + wave2 + wave3, y, wy))
        return points

    @staticmethod
    def draw_river(surface: pygame.Surface, river_x: int, cam_x: int, cam_y: int,
                   screen_h: int, time_ticks: float, zoom: float = 1.0):
        pts = RiverRenderer.river_points(river_x, cam_y, screen_h, time_ticks, seed=river_x)
        if len(pts) < 2:
            return
        w_outer = max(2, int(5 * zoom))
        w_inner = max(1, int(2 * zoom))
        for i in range(len(pts) - 1):
            x1, y1, _ = pts[i]
            x2, y2, _ = pts[i + 1]
            sx1, sx2 = int((x1 - cam_x) * zoom), int((x2 - cam_x) * zoom)
            sy1, sy2 = int(y1 * zoom), int(y2 * zoom)
            pygame.draw.line(surface, RIVER_DARK, (sx1, sy1), (sx2, sy2), w_outer)
        for i in range(len(pts) - 1):
            x1, y1, _ = pts[i]
            x2, y2, _ = pts[i + 1]
            sx1, sx2 = int((x1 - cam_x) * zoom), int((x2 - cam_x) * zoom)
            sy1, sy2 = int(y1 * zoom), int(y2 * zoom)
            pygame.draw.line(surface, RIVER_COLOR, (sx1, sy1), (sx2, sy2), w_inner)
        # редкие блики — детерминированные, без мерцания random каждый кадр
        t = int(time_ticks // 500)
        for i in range(0, len(pts) - 1, 24):
            x1, y1, wy = pts[(i + t) % (len(pts) - 1)]
            sx = int((x1 - cam_x) * zoom)
            sy = int(y1 * zoom)
            pygame.draw.circle(surface, RIVER_LIGHT, (sx, sy), max(1, int(1 * zoom)))

    @staticmethod
    def draw_bridge(surface: pygame.Surface, river_x: int, bridge_y: int,
                    cam_x: int, cam_y: int, zoom: float = 1.0):
        sx = int((river_x - cam_x) * zoom)
        sy = int((bridge_y - cam_y) * zoom)
        bw, bh = int(36 * zoom), int(16 * zoom)

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
