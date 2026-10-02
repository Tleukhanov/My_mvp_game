import hashlib
import os
import pygame
import math
import random
from typing import Dict, Optional, Tuple, List


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


#: Радиусы пятен леса в промежуточном разрешении. Текстура потом
#: растягивается в ``PROVINCE_DETAIL`` раз, поэтому на карте пятно выходит
#: 2-6 px — ровно тот «мелкий тёмный ритм», который читается как лес.
#: Тройки нет намеренно: на 1.8x пятно радиусом 3 превращается в 11 px и
#: клякса съедает промежутки, радиусом набора у леса быть не может.
FOREST_DOT_RADII = (1, 1, 1, 2, 2)


def _paint_forest(surf: pygame.Surface, seed: int, w: int, h: int):
    """Лес как ритм мелких пятен, а не как круглая тень.

    Раньше здесь было три шара радиусом 6-16 пикселей, которые после
    сглаживания сливались в одно бурое пятно — на карте это читалось не как
    лес, а как грязь или пролитый кофе. Теперь каждый массив состоит из
    10-24 мелких пятен, разбросанных по эллипсу: у массива появляется
    неровный край, а между пятнами остаётся бумага, и глаз читает не
    «дыру в пергаменте», а древесину с высоты.

    Всё детерминировано от ``seed`` (индекса провинции): перезапуск игры
    даёт ту же карту, а текстура остаётся кэшируемой на диск.
    """
    if w <= 2 or h <= 2:
        return
    rng = random.Random((seed * 7919) ^ 0x5EED)
    short = max(4, min(w, h))
    clusters = 2 + rng.randint(0, 2)
    for _ in range(clusters):
        ccx = rng.randint(0, w - 1)
        ccy = rng.randint(0, h - 1)
        # массив может быть вытянутым: так лес тянется вдоль реки или дороги
        stretch = 0.6 + 1.1 * rng.random()
        spread_x = short * (0.10 + 0.12 * rng.random()) * stretch
        spread_y = short * (0.10 + 0.12 * rng.random()) / stretch
        col = FOREST_COLORS[rng.randrange(len(FOREST_COLORS))]
        alpha = 84 + rng.randint(0, 44)
        for _ in range(10 + rng.randint(0, 14)):
            ang = rng.random() * math.tau
            # корень куста ближе к центру массива, крона — по краю
            rad = 0.3 + 0.7 * rng.random()
            px = int(ccx + math.cos(ang) * spread_x * rad)
            py = int(ccy + math.sin(ang) * spread_y * rad)
            if px < 0 or py < 0 or px >= w or py >= h:
                continue
            r = FOREST_DOT_RADII[rng.randrange(len(FOREST_DOT_RADII))]
            pygame.draw.circle(surf, (col[0], col[1], col[2], alpha), (px, py), r)


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

#: Доля цвета нации в текстуре провинции. При 0.18 державы были
#: визуально неразличимы — «где моя территория» не читалось вообще.
OWNER_TINT_MIX = 0.42

# Вода. Раньше море было того же оливково-хаки оттенка, что и пергамент, и
# отличалось от суши только на 25 единиц яркости: суша выглядела вырезанной
# и наклеенной. Теперь вода ушла в приглушённый сине-стальной, как и реки
# на карте, — и по тону, и по светлоте её сразу видно.
WATER_DEEP = (32, 52, 66)
WATER_MID = (53, 76, 88)
WATER_LIGHT = (78, 104, 114)
WATER_FOAM = (160, 185, 195)

RIVER_COLOR = (120, 140, 170)
RIVER_DARK = (90, 110, 145)
RIVER_LIGHT = (165, 185, 210)


#: Кэш шрифтов модульного уровня. SysFont на каждого генерала каждый кадр —
#: это 2-6 мс чистого пересоздания одних и тех же объектов Font.
_FONT_CACHE: Dict[Tuple[object, int], pygame.font.Font] = {}


def _cached_font(name, size: int) -> pygame.font.Font:
    """Шрифт из кэша по паре (имя, размер).

    Готовый объект Font переиспользуется, поэтому подписи генералов больше не
    пересоздают шрифт каждый кадр. Если pygame.font ещё не инициализирован —
    инициализируем на лету. Если системного шрифта с таким именем нет,
    результат отката (шрифт по умолчанию) тоже кэшируется, чтобы не повторять
    исключение каждый кадр.
    """
    key = (name, int(size))
    font = _FONT_CACHE.get(key)
    if font is not None:
        return font
    if not pygame.font.get_init():
        pygame.font.init()
    try:
        font = pygame.font.SysFont(name, int(size))
    except Exception:
        font = pygame.font.SysFont(None, int(size))
    _FONT_CACHE[key] = font
    return font


#: Текстуры провинций рисуются в уменьшенном разрешении и растягиваются.
#: Пергамент — фон под подписями, детализация ему не нужна, а экономия
#: в 4 раза по пикселям превращает минуту ожидания в пару секунд.
PROVINCE_DETAIL = 2
PROVINCE_PAD = 4

#: Версия рисунка базовой текстуры. Входит в имя файла кэша, поэтому любая
#: правка палитры или леса перестаёт быть невидимой: старые файлы просто
#: перестают совпадать по имени и перегенерируются. Без этой константы
#: правка палитры молча читала бы старый PNG и выглядела бы как «ничего
#: не изменилось».
PROVINCE_TEX_VERSION = 2


class TextureManager:
    def __init__(self):
        self._province_cache: Dict[tuple, pygame.Surface] = {}
        self._province_base_cache: Dict[int, pygame.Surface] = {}
        self._water_surface: pygame.Surface = None
        self._water_size: Tuple[int, int] = (0, 0)
        self._ocean_cache: pygame.Surface = None
        self._ocean_size: Tuple[int, int] = (0, 0)

    def _tint_factor(self, owner: str) -> Tuple[int, int, int]:
        """Множитель цвета владельца: ``OWNER_TINT_MIX`` пергамента + доля цвета нации.

        Доля подобрана экспериментально: при 18% три державы на карте были
        визуально неотличимы — игрок не мог за секунду сказать, где его
        территория, хотя счётчики в HUD показывали 7/7/7. Сейчас
        ``OWNER_TINT_MIX = 0.42``: пергамент и рельеф всё ещё читаются,
        но цвет нации определяет провинцию с одного взгляда.

        Считается так, что обычный ``BLEND_RGB_MULT`` даёт ровно нужную
        примесь — поэтому перекраска провинции при захвате стоит один
        быстрый блит, а не перегенерацию текстуры попиксельно.
        """
        tint = OWNER_TINT.get(owner)
        base = (1.0 - OWNER_TINT_MIX) * 255
        if tint is None:
            v = int(base)
            return (v, v, v)
        mix = OWNER_TINT_MIX
        return (
            min(255, int(base + mix * tint[0])),
            min(255, int(base + mix * tint[1])),
            min(255, int(base + mix * tint[2])),
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

        Хеш геометрии и версия рисунка входят в имя: если границы провинции
        изменились ИЛИ палитра с рисунком леса поменялась, старый файл просто
        не найдётся и текстура перегенерируется. Без этого перегенерация всех
        50 провинций занимала бы 15 секунд при каждом входе в мировую карту.
        """
        digest = hashlib.md5(repr(tuple(polygon)).encode("utf-8")).hexdigest()[:10]
        return os.path.join(
            ASSETS_DIR,
            f"base_{province_idx:02d}_{digest}_v{PROVINCE_TEX_VERSION}.png")

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

                dv = int((n - 0.5) * 16 + grain * 10)
                col = (
                    max(0, min(255, col[0] + dv)),
                    max(0, min(255, col[1] + dv)),
                    max(0, min(255, col[2] + dv)),
                )
                surf.set_at((px, py), col)

        # Лес рисуется ПОСЛЕ пергамента и ДО обрезки по маске: массивы,
        # вышедшие за границу провинции, срезаются краем владения — так
        # лес выглядит обрезанным границей, а не наложенным поверх неё.
        _paint_forest(surf, province_idx, size[0], size[1])

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
        """Море: пологий градиент + шум + виньетка по краю кадра.

        Раньше это была плоская заливка одного блока шума на весь экран, и
        суша на её фоне выглядела вырезанной и наклеенной. Теперь поверх
        шума идёт вертикальный градиент (у горизонта светлее, к нижнему
        краю глуше) и мягкая виньетка, и вода читается как среда вокруг
        бумажной карты, а не как фон.

        Всё считается один раз в половинном разрешении и растягивается
        один раз: попиксельная работа не попадает в кадр вообще, наружу
        уходит ровно один непрозрачный блит.
        """
        size = (max(2, int(w)), max(2, int(h)))
        if self._ocean_cache is not None and self._ocean_size == size:
            return self._ocean_cache

        hw, hh = max(2, size[0] // 2), max(2, size[1] // 2)
        small = pygame.Surface((hw, hh))
        # Блок 2 px в половинном разрешении даёт 4 px на экране: крупнее
        # шум читался бы как шахматная доска, а не как вода.
        step = 2
        # Шум считается на разреженной сетке и добирается интерполяцией.
        # Считать fbm на каждый блок смысла нет: блоки всё равно размываются
        # растягиванием, а 96 тысяч вызовов fbm съедали 1.4 с холодного
        # старта — больше, чем весь океан стоит.
        grid = 9
        gw, gh = hw // grid + 2, hh // grid + 2
        noise = [[_fbm(gx * 0.008 * grid, gy * 0.008 * grid, 3, 42)
                  for gx in range(gw)] for gy in range(gh)]
        cx, cy = hw * 0.5, hh * 0.5
        # радиус, за которым виньетка выходит на максимум
        inv_r = 1.0 / max(1.0, math.hypot(cx, cy))
        inv_grid = 1.0 / grid
        for y in range(0, hh, step):
            row_t = y / float(hh - 1)
            fy = y * inv_grid
            gy0 = int(fy)
            ty = fy - gy0
            row_a, row_b = noise[gy0], noise[min(gy0 + 1, gh - 1)]
            for x in range(0, hw, step):
                fx = x * inv_grid
                gx0 = int(fx)
                gx1 = min(gx0 + 1, gw - 1)
                tx = fx - gx0
                n = ((row_a[gx0] * (1.0 - tx) + row_a[gx1] * tx) * (1.0 - ty)
                     + (row_b[gx0] * (1.0 - tx) + row_b[gx1] * tx) * ty)
                # к горизонту вода светлеет, к нижнему краю — глуше.
                # Растяжка в три ступени, а не в две: между «глубокой» и
                # «мелкой» водой пропадает полутон, и море читается
                # двухполосным.
                t = 0.20 + 0.42 * n + 0.26 * (1.0 - row_t)
                if t <= 0.5:
                    col = _blend_color(WATER_DEEP, WATER_MID, t * 2.0)
                else:
                    col = _blend_color(WATER_MID, WATER_LIGHT, (t - 0.5) * 2.0)
                # виньетка: 0 в центре, 0.24 в углах. Дальше не надо —
                # карта перестанет читаться по краям экрана
                d = math.hypot(x - cx, y - cy) * inv_r
                vig = max(0.0, (d - 0.5) * 2.0) ** 1.7
                f = 1.0 - 0.24 * vig
                grain = int((_hash_noise(x, y, 7) - 0.5) * 7)
                pygame.draw.rect(small, (
                    max(0, min(255, int(col[0] * f) + grain)),
                    max(0, min(255, int(col[1] * f) + grain)),
                    max(0, min(255, int(col[2] * f) + grain)),
                ), (x, y, step, step))

        try:
            surf = pygame.transform.smoothscale(small, size)
        except Exception:
            surf = small
        self._ocean_cache = surf
        self._ocean_size = size
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


#: Палитра «рамки» карты. Раньше у границ был один цвет на всех, и по
#: карте нельзя было за секунду отличить своё от чужого: все линии шли
#: одинаковой толщиной и одинаковой контрастностью.
COAST_INK = (44, 41, 26)          # тёмный берег
COAST_LIGHT = (228, 218, 180)      # светлая губа бумаги на северном склоне
FRAME_SHADOW_FAR = 96             # дальняя тень под сушей
FRAME_SHADOW_NEAR = 56            # ближняя, плотнее
#: Щели пунктира у границ с нейтралами, в мировых координатах.
NEUTRAL_DASH_ON = 8
NEUTRAL_DASH_OFF = 5


def _outward_normal(a: Tuple[int, int], b: Tuple[int, int],
                    center: Tuple[float, float]) -> Tuple[float, float]:
    """Единичная нормаль ребра, направленная ОТ центра полигона.

    Обход полигона может быть любой ориентации, поэтому «наружу» определяется
    не знаком площади, а тем, с какой стороны ребра лежит центр. Иначе
    светлая губа тиснения рисувалась бы то с внешней, то с внутренней
    стороны берега.
    """
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    length = math.hypot(dx, dy)
    if length < 1e-6:
        return 0.0, 0.0
    nx, ny = dy / length, -dx / length
    if (a[0] - center[0]) * nx + (a[1] - center[1]) * ny < 0:
        nx, ny = -nx, -ny
    return nx, ny


def _edge_index(polygons: List[List[Tuple[int, int]]]) -> Dict[tuple, List[int]]:
    """Кто с кем делит ребро: ключ ребра -> индексы соседних провинций.

    Ключ — пара вершин в отсортированном порядке, поэтому ребро, разделяющее
    две клетки, находится по одному и тому же ключу с обеих сторон.
    """
    index: Dict[tuple, List[int]] = {}
    for idx, poly in enumerate(polygons):
        for a, b in zip(poly, poly[1:] + poly[:1]):
            key = (a, b) if a <= b else (b, a)
            bucket = index.get(key)
            if bucket is None:
                index[key] = [idx]
            elif idx not in bucket:
                bucket.append(idx)
    return index


def _border_runs(poly: List[Tuple[int, int]], edge_index: Dict[tuple, List[int]],
                 idx: int):
    """Ломаная из рёбер с ОДНИМ И ТЕМ ЖЕ соседом.

    Группировка нужна для двух вещей: во-первых, 16 рёбер клетки рисуются
    как 4 отрезка, а не как 16 штрихов; во-вторых, пунктир не «рвётся» на
    каждом стыке. Возвращает ``(точки, индекс соседа)``, где сосед ``None`` —
    это берег, а не граница владений.
    """
    pts = list(poly) + [poly[0]]
    run_pts: Optional[List[Tuple[int, int]]] = None
    run_peer = False
    for a, b in zip(pts, pts[1:]):
        key = (a, b) if a <= b else (b, a)
        peer = None
        for other in edge_index.get(key, ()):
            if other != idx:
                peer = other
                break
        if run_pts is not None and run_peer == peer and run_pts[-1] == a:
            run_pts.append(b)
            continue
        if run_pts is not None:
            yield run_pts, (None if run_peer is False else run_peer)
        run_pts, run_peer = [a, b], peer
    if run_pts is not None:
        yield run_pts, (None if run_peer is False else run_peer)


def _draw_dashed(surface: pygame.Surface, pts: List[Tuple[int, int]],
                 color: Tuple[int, int, int], width: int,
                 on: int, off: int):
    """Пунктир по ломаной с общей фазой.

    Фаза считается по длине всей ломаной, а не заново на каждом отрезке:
    иначе рисунок начинается заново на стыке и штрихи выглядят неровными.
    """
    period = float(on + off)
    if period <= 0:
        return
    phase = 0.0
    for a, b in zip(pts, pts[1:]):
        seg = math.hypot(b[0] - a[0], b[1] - a[1])
        if seg < 1e-6:
            continue
        t = 0.0
        while t < seg - 1e-9:
            drawing = phase < on
            step = min(seg - t, (on if drawing else period) - phase)
            if drawing and step > 0:
                f0 = t / seg
                f1 = (t + step) / seg
                pygame.draw.line(surface, color,
                                 (int(a[0] + (b[0] - a[0]) * f0),
                                  int(a[1] + (b[1] - a[1]) * f0)),
                                 (int(a[0] + (b[0] - a[0]) * f1),
                                  int(a[1] + (b[1] - a[1]) * f1)),
                                 width)
            t += step
            phase = (phase + step) % period


def build_map_frame(polygons: List[List[Tuple[int, int]]], owners: List[str],
                    origin: Tuple[int, int], size: Tuple[int, int],
                    zoom: float, border_style) -> pygame.Surface:
    """Одна поверхность со всей «окантовкой» карты: тень, берег, границы.

    Собирается один раз и блитится одним куском, поэтому в кадре не остаётся
    ни одной попиксельной работы. Четыре составляющие, по порядку наложения:

    * тень под сушей — силуэт, сдвинутый на 1-2 px и 3-4 px, из которого
      вычтен силуэт на месте. Остаётся серп вокруг суши, и потому слой
      можно класть ПОВЕРХ текстур: внутри суши он всё равно прозрачен;
    * светлая губа на северных склонах берега — имитация тиснения бумаги;
    * тёмный берег;
    * границы владений: ``border_style`` решает, тонкая это линия внутри
      нации, жирная контрастная между нациями или бледный пунктир у
      нейтралов.

    Поверхность строится УЖЕ В ЭКРАННЫХ координатах текущего зума, а её левый
    верхний угол при блите совпадает с углом мира под камерой. Это не
    украшение: поверхность в мировых координатах пришлось бы масштабировать
    при каждом кадре, а масштабирование убивает волосяные линии (на 0.6x
    однопиксельный шов превращается в еле заметную кашу), и вдобавок съедает
    4-10 мс на кадр. Здесь зум — множитель координат, поэтому границы
    остаются резкими при любом зуме, а пересборка случается только при его
    смене.
    """
    w = max(1, int(round(size[0] * zoom)))
    h = max(1, int(round(size[1] * zoom)))
    ox, oy = int(origin[0]), int(origin[1])
    local = [[(int(round((x - ox) * zoom)), int(round((y - oy) * zoom)))
              for x, y in poly] for poly in polygons]
    edge_index = _edge_index(local)
    frame = pygame.Surface((w, h), pygame.SRCALPHA)

    # --- 1. тень под сушей -------------------------------------------------
    sil = pygame.Surface((w, h), pygame.SRCALPHA)
    for alpha, shift in ((FRAME_SHADOW_FAR, (3, 4)),
                         (FRAME_SHADOW_NEAR, (1, 2))):
        sil.fill((0, 0, 0, 0))
        for poly in local:
            pygame.draw.polygon(sil, (0, 0, 0, alpha), poly)
        frame.blit(sil, shift)
        # вычитаем силуэт на месте: серп остаётся только вокруг суши
        frame.blit(sil, (0, 0), special_flags=pygame.BLEND_RGBA_SUB)
    del sil

    # --- 2. берег и тиснение ----------------------------------------------
    # Обводка рисуется ДО вычитания силуэта, поэтому внутренние швы провинций
    # съедаются и остаётся ровно контур суши — вместе с тонкой светлой губой
    # на северной стороне.
    coast = pygame.Surface((w, h), pygame.SRCALPHA)
    # Губа шире линии берега: после вычитания силуэта от обводки остаётся
    # только ВНЕШНЯЯ половина, то есть ровно светлая кромка над тёмной чертой.
    lip_w, ink_w = 6, 2
    for idx, poly in enumerate(local):
        n = float(len(poly))
        center = (sum(p[0] for p in poly) / n, sum(p[1] for p in poly) / n)
        for a, b in zip(poly, poly[1:] + poly[:1]):
            key = (a, b) if a <= b else (b, a)
            if any(o != idx for o in edge_index.get(key, ())):
                continue                      # внутренний шов, не берег
            _, ny = _outward_normal(a, b, center)
            if ny < -0.25:                   # склон смотрит на север
                pygame.draw.line(coast, COAST_LIGHT + (150,), a, b, lip_w)
    for poly in local:
        pygame.draw.polygon(coast, COAST_INK + (255,), poly, ink_w)
    # Силуэт суши ВЫЧИТАЕТСЯ из обводки: внутри контура обводки не должно
    # быть, иначе тёмная краска берега залила бы все провинции целиком.
    # Именно вычитание, а не MIN: MIN двух непрозрачных пикселей даёт
    # непрозрачный пиксель и ничего не стирает.
    land = pygame.Surface((w, h), pygame.SRCALPHA)
    for poly in local:
        pygame.draw.polygon(land, (255, 255, 255, 255), poly)
    coast.blit(land, (0, 0), special_flags=pygame.BLEND_RGBA_SUB)
    del land
    frame.blit(coast, (0, 0))

    # --- 3. границы владений ----------------------------------------------
    # ``border_style(idx, peer)`` возвращает (краска, сердцевина, толщина,
    # пунктир) либо None, если линию рисовать не нужно. Сердцевина — тонкая
    # цветная нить поверх тёмной краски: сама краска отвечает за контраст,
    # а цвет за то, ЧЕЙ это шов.
    for idx, poly in enumerate(local):
        for run, peer in _border_runs(poly, edge_index, idx):
            if peer is None:
                continue                      # берег уже нарисован выше
            style = border_style(idx, peer)
            if style is None:
                continue
            color, core, width, dashed = style
            if dashed:
                _draw_dashed(frame, run, color, width,
                             NEUTRAL_DASH_ON, NEUTRAL_DASH_OFF)
            else:
                for a, b in zip(run, run[1:]):
                    pygame.draw.line(frame, color, a, b, width)
                if core is not None and width > 1:
                    core_w = max(1, width - 2)
                    for a, b in zip(run, run[1:]):
                        pygame.draw.line(frame, core, a, b, core_w)
    return frame


class GeneralIcon:
    #: Подписи под знамёнами кэшируются целиком: раньше ``font.render`` +
    #: две аллокации поверхности повторялись для каждого генерала в каждом
    #: кадре, хотя строка и кегль меняются только при смене зума.
    _LABEL_CACHE: Dict[tuple, pygame.Surface] = {}
    _LABEL_CACHE_LIMIT = 256

    @staticmethod
    def _label_plate(label: str, size: int) -> pygame.Surface:
        """Табличка «имя + число» под знаменем, готовая к блиту.

        Фон и текст склеиваются в одну поверхность заранее: в кадре остаётся
        ровно один блит вместо рендера шрифта и двух поверхностей.
        """
        key = (label, int(size))
        plate = GeneralIcon._LABEL_CACHE.get(key)
        if plate is not None:
            return plate
        font = _cached_font("serif", size)
        txt = font.render(label, True, (240, 230, 200))
        plate = pygame.Surface((txt.get_width() + 6, txt.get_height() + 2),
                               pygame.SRCALPHA)
        plate.fill((20, 18, 12, 190))
        plate.blit(txt, (3, 1))
        if len(GeneralIcon._LABEL_CACHE) >= GeneralIcon._LABEL_CACHE_LIMIT:
            GeneralIcon._LABEL_CACHE.clear()
        GeneralIcon._LABEL_CACHE[key] = plate
        return plate

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
            plate = GeneralIcon._label_plate(label, max(10, int(12 * s)))
            surface.blit(plate, (x - plate.get_width() // 2, y + 12 * s))


class LandMask:
    """Грубая карта «здесь суша» для отсечения рек и мостов.

    Реки рисуются вертикальными экранными линиями через всю высоту кадра,
    поэтому они продолжались и по морю — стоило сделать воду различимой,
    и river «выпадал» в открытое море ниже южного берега. Проверять каждую
    точку по полигонам в кадре нельзя (50 полигонов × 16 рёбер на сегмент),
    поэтому берётся дешёвая сетка: 8 мировых пикселей на ячейку, хранение —
    один ``bytes``, доступ — индекс в него.

    Маска нарочно «толще» суши на :data:`DILATE_CELLS` ячеек: сами провинции
    разведены проливами шириной 18-41 px, и без расширения река внутри
    пролива считалась бы морем и обрывалась на две несвязанные нитки.
    """

    CELL = 8
    #: Насколько шире суши считать «ещё сушей». 3 ячейки = 24 px, этого
    #: хватает на самый широкий пролив (41 px) с запасом.
    DILATE_CELLS = 3

    def __init__(self, polygons, origin):
        xs = [x for poly in polygons for x, _ in poly]
        ys = [y for poly in polygons for _, y in poly]
        min_x, min_y = min(xs), min(ys)
        self.ox, self.oy = int(origin[0]), int(origin[1])
        self.cw = (max(xs) - min_x) // self.CELL + 2
        self.ch = (max(ys) - min_y) // self.CELL + 2
        surf = pygame.Surface((self.cw, self.ch), pygame.SRCALPHA)
        cells = [[((x - min_x) // self.CELL, (y - min_y) // self.CELL)
                  for x, y in poly] for poly in polygons]
        for poly in cells:
            pygame.draw.polygon(surf, (255, 255, 255, 255), poly)
        # обводка наружу и есть расширение маски
        wide = self.DILATE_CELLS * 2 + 1
        for poly in cells:
            pygame.draw.polygon(surf, (255, 255, 255, 255), poly, wide)
        # tobytes — современное имя (tostring с 2.3.0 ругается предупреждением),
        # но на старом pygame остаётся только tostring
        tobytes = getattr(pygame.image, "tobytes", None) or pygame.image.tostring
        self.data = tobytes(surf, "RGB")
        del surf

    def covers(self, wx: int, wy: int) -> bool:
        gx = (int(wx) - self.ox) // self.CELL
        gy = (int(wy) - self.oy) // self.CELL
        if gx < 0 or gy < 0 or gx >= self.cw or gy >= self.ch:
            return False
        return self.data[(gy * self.cw + gx) * 3] > 127


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
                   screen_h: int, time_ticks: float, zoom: float = 1.0,
                   land: Optional["LandMask"] = None):
        pts = RiverRenderer.river_points(river_x, cam_y, screen_h, time_ticks, seed=river_x)
        if len(pts) < 2:
            return
        if land is not None:
            # Воду не режет: река там, где суши нет, не нужна
            pts = [pts[0]] + [p for p in pts[1:]
                               if land.covers((p[0] + p[2]) // 2, p[2])]
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
