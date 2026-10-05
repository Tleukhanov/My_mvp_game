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


# ===========================================================================
# РЕЛЬЕФ: одна непрерывная поверхность на всю карту
# ===========================================================================
# Прежняя карта собиралась из пятидесяти отдельных прямоугольных текстур, по
# одной на провинцию, и у каждой был свой шум. На экране это читалось как
# таблица, а не как местность: видно швы, рельеф обрывается на границе
# владения, а одинаковые куски соседних провинций не продолжают друг друга.
#
# Теперь рельеф один на весь мир. Высота и влажность считаются в МИРОВЫХ
# координатах, поэтому соседние провинции продолжают друг друга и карта
# становится одной местностью; провинция возникает поверх неё только швом
# границы. Рисунок статичен, поэтому он кэшируется — на диск и в память — и
# в кадре попадает одним блитом.

#: Опоры «высота -> цвет»: пойма, луга, пашня, сухая степь, предгорья, камень.
#: Одна шкала на всю карту, иначе половина материка была бы зелёной, а
#: половина — оранжевой, и рельеф переставал бы читаться как рельеф.
#:
#: Шкала намеренно тёмная и в нижней половине: на референсе карта держится в
#: глубоких оливково-зелёных тонах, и светлота приходит рельефом (свет с
#: северо-запада), а не высотой яркости. Светлая шкала давала выцветшую
#: пастель, поверх которой любой цвет державы читался как фломастер.
LAND_RAMP = (
    (0.00, (44, 66, 40)),
    (0.16, (58, 82, 44)),
    (0.32, (76, 98, 48)),
    (0.46, (102, 116, 58)),
    (0.58, (128, 130, 70)),
    (0.70, (140, 126, 80)),
    (0.82, (124, 110, 90)),
    (0.92, (138, 132, 122)),
    (1.00, (168, 166, 160)),
)

#: Сетка шума, px в половинном разрешении. fbm считается раз в этот шаг и
#: добирается билинейной интерполяцией: на 400 тысяч пикселей карты это
#: ~16 тысяч вычислений вместо полутора миллионов, а разницы на экране нет —
#: поле всё равно потом растягивается и сглаживается.
LAND_NOISE_CELL = 6
#: Шаг уменьшения при рисовании рельефа.
LAND_STEP = 2
#: Сид рельефа. Зашит константой, а не берётся из ГПСЧ партии: карта обязана
#: выглядеть одинаково при каждом запуске и на каждом скриншоте.
LAND_SEED = 0x5EA51E
#: Насколько крутизна рельефа превращается в яркость. Свет идёт с
#: северо-запада, поэтому ярче тот склон, который спускается к северу и западу:
#: там, где высота растёт к северо-востоку.
LAND_RELIEF = 88.0
#: Сколько низин против вершин. Больше единицы прижимает материк к
#: зелёным низинам и уводит вершины в узкую полосу скал.
LAND_BIAS = 1.22
#: Зерно бумаги, в единицах яркости на пиксель.
GRAIN_MAX = 3
#: Разгон контраста рельефа вокруг опорного тона. Без него поверхность
#: читалась как ровная заливка: тёмное и светлое отличались на два-три десятых
#: тона, и глаз не находил на карте ни холма, ни долины. Сжатие контраста
#: плёнкой владения поверх только усиливало этот эффект.
LAND_CONTRAST = 1.22
LAND_PIVOT = 112.0
#: Насколько сильно влажность сдвигает тон в зелень.
LAND_WET_GAIN = 1.0
#: Цвета лесных массивов. Тёмный хвойный и тёмный лиственный — лес на
#: карте должен читаться пятном, а не россыпью точек.
LAND_FOREST_COLORS = (
    (44, 60, 34),
    (52, 68, 38),
    (38, 54, 30),
    (60, 74, 42),
)
#: Версия рисунка рельефа. Входит в имя файла кэша на диске: любая правка
#: палитры или света перестаёт быть невидимой.
LAND_TEX_VERSION = 4
#: Сколько зумов рельефа держим в памяти одновременно. Поверхность мира —
#: это 1.6 Мпикс, и на 2.5x она уже 10 Мпикс, так что кэш без потолка
#: съедал бы память целиком.
LAND_ZOOM_CACHE_LIMIT = 3


def _ramp_sample(stops, t: float):
    """Цвет по опорам LAND_RAMP с линейной интерполяцией."""
    if t <= stops[0][0]:
        return stops[0][1]
    for i in range(len(stops) - 1):
        t0, c0 = stops[i]
        t1, c1 = stops[i + 1]
        if t <= t1:
            k = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
            return (c0[0] + (c1[0] - c0[0]) * k,
                    c0[1] + (c1[1] - c0[1]) * k,
                    c0[2] + (c1[2] - c0[2]) * k)
    return stops[-1][1]


def _coarse_field(w: int, h: int, cell: int, fn) -> List[float]:
    """Поле из разреженной сетки, развёрнутое билинейно до ``w x h``.

    Вычисление ``fn`` вызывается только в узлах сетки (шаг ``cell``), а
    остальное добирается интерполяцией — на порядок дешевле полного fbm на
    каждый пиксель, и глаз разницы не находит.
    """
    gw = w // cell + 2
    gh = h // cell + 2
    raw = [fn(gx * cell, gy * cell) for gy in range(gh) for gx in range(gw)]
    out = [0.0] * (w * h)
    inv = 1.0 / cell
    last_gx = gw - 1
    last_gy = gh - 1
    for y in range(h):
        fy = y * inv
        gy0 = int(fy)
        if gy0 > last_gy:
            gy0 = last_gy
        ty = fy - gy0
        r0 = gy0 * gw
        r1 = (gy0 + 1 if gy0 < last_gy else last_gy) * gw
        o = y * w
        for x in range(w):
            fx = x * inv
            gx0 = int(fx)
            if gx0 > last_gx:
                gx0 = last_gx
            gx1 = gx0 + 1 if gx0 < last_gx else last_gx
            tx = fx - gx0
            a = raw[r0 + gx0]
            v0 = a + (raw[r0 + gx1] - a) * tx
            b = raw[r1 + gx0]
            v1 = b + (raw[r1 + gx1] - b) * tx
            out[o + x] = v0 + (v1 - v0) * ty
    return out


def _field_at(field: List[float], cell: int, x: int, y: int, w: int, h: int) -> float:
    """Значение разреженного поля в произвольной точке (грубая выборка)."""
    gx = x // cell
    gy = y // cell
    if gx < 0 or gy < 0 or gx >= w or gy >= h:
        return 0.0
    return field[gy * w + gx]


_FOREST_DOT_CACHE: Dict[tuple, pygame.Surface] = {}


def _forest_dot(radius: int, color: Tuple[int, int, int],
                strength: int = 238) -> pygame.Surface:
    """Мягкое пятно леса с затуханием к краю.

    Раньше лес рисовался кружком с постоянной альфой прямо на поверхности с
    альфой, и ``pygame.draw`` не смешивает, а ЗАПИСЫВАЕТ цвет: каждое пятно
    выбивало дырку в бумаге, и сквозь неё просвечивало море — лес читался как
    россыпь синих блёсток. Здесь пятно заранее собрано в спрайт с мягким
    краем, и обычный блит смешивает его как полагается.

    ``strength`` — потолок альфы: подстилка леса кладётся слабым пятном, а
    крона — плотным, и только так массив перестаёт быть россыпью кружков.
    """
    key = (int(radius), color, int(strength))
    dot = _FOREST_DOT_CACHE.get(key)
    if dot is not None:
        return dot
    r = max(1, int(radius))
    d = r * 2 + 1
    dot = pygame.Surface((d, d), pygame.SRCALPHA)
    for y in range(d):
        dy = (y - r) / (r + 0.5)
        for x in range(d):
            dx = (x - r) / (r + 0.5)
            dist = math.hypot(dx, dy)
            if dist >= 1.0:
                continue
            a = int(strength * (1.0 - dist) ** 1.25)
            if a > 2:
                dot.set_at((x, y), (color[0], color[1], color[2], a))
    if len(_FOREST_DOT_CACHE) < 64:
        _FOREST_DOT_CACHE[key] = dot
    return dot


def _land_grain_tile(seed: int, size: int = 192) -> pygame.Surface:
    """Плитка бумажного зерна: значения 0..GRAIN_MAX, добавляются на карту.

    Именно 24-битная плитка и ``BLEND_RGB_ADD``, а не SRCALPHA с
    ``BLEND_RGBA_ADD``: SDL в режиме ``SDL_BLENDA_ADD`` складывает
    *цвет источника*, не глядя на его альфу. Плитка «белый с альфой 1»
    поэтому заливала всю карту чистым белым, а нетронутые пиксели оставались
    цвета земли — карта выходила как мелкое сито из белого по хаки.
    """
    rng = random.Random(seed ^ 0x9E3779B9)
    tile = pygame.Surface((size, size))
    for y in range(size):
        for x in range(size):
            tile.set_at((x, y), (rng.randrange(GRAIN_MAX + 1),) * 3)
    # редкие волокна бумаги — короткие светлые штрихи, они ловят взгляд и
    # поверхность перестаёт выглядеть цифровым градиентом
    for _ in range(size // 8):
        px, py = rng.randrange(size), rng.randrange(size)
        length = rng.randint(3, 11)
        horizontal = rng.random() < 0.5
        k0 = rng.randrange(GRAIN_MAX + 2)
        for k in range(length):
            qx = px + (k if horizontal else 0)
            qy = py + (0 if horizontal else k)
            if 0 <= qx < size and 0 <= qy < size:
                tile.set_at((qx, qy), (k0, k0, k0))
    return tile


def build_land_surface(polygons: List[List[Tuple[int, int]]],
                       origin: Tuple[int, int],
                       size: Tuple[int, int],
                       seed: int = LAND_SEED) -> pygame.Surface:
    """Рельеф всей суши одной поверхностью мирового размера.

    Поверхность непрозрачна там, где есть суша, и полностью прозрачна в море,
    поэтому её можно класть прямо на океан. Собирается один раз и кэшируется
    дважды: в памяти процесса (несколько экранов карты подряд) и на диске
    (чтобы не платить генерацию при каждом запуске).

    Порядок наложения, снизу вверх:

    1. **рельеф** — высота из гребневого шума, свет с северо-запада, тон по
       высоте, зелень по влажности;
    2. **унастье земли** — крупная сетка лоскутов, слегка сдвигающая высоту.
       Это те самые светлые поля на референсе: они дают карте ритм и
       убирают ощущение единой заливки;
    3. **лес** — мягкие пятна там, где влажно и невысоко;
    4. **тон провинции** — едва заметная подсветка каждого владения, чтобы
       соседние провинции одной нации различались, а не сливались в пятно;
    5. **зерно бумаги**;
    6. **затемнение к берегу и к краю карты** — мягкое, множителем;
    7. **маска суши** по полигонам: всё, что вне владений, становится морем.
    """
    w = max(2, int(size[0]))
    h = max(2, int(size[1]))
    hw = max(2, w // LAND_STEP)
    hh = max(2, h // LAND_STEP)
    cell = LAND_NOISE_CELL
    gw = hw // cell + 2
    gh = hh // cell + 2

    def _elev(x: int, y: int) -> float:
        base = _fbm(x * 0.0026, y * 0.0026, 4, seed)
        # гребневой шум: |2n-1| обращает холмы в хребты, и на карте появляются
        # читаемые горные цепи вместо равномерной бугристой каши
        ridge = 1.0 - abs(2.0 * _fbm(x * 0.0017, y * 0.0017, 3, seed + 313) - 1.0)
        return base * 0.42 + (ridge ** 1.7) * 0.58

    elev = _coarse_field(hw, hh, cell, _elev)
    moist = _coarse_field(hw, hh, cell,
                          lambda x, y: _fbm(x * 0.0044, y * 0.0044, 3, seed + 7919))
    parcel = _coarse_field(hw, hh, cell,
                           lambda x, y: _fbm(x * 0.0068, y * 0.0068, 2, seed + 104729))
    # Поле высоты нормализуется по собственному размаху. Гребневой шум сильно
    # смещён вверх (среднее около 0.66), и без нормализации вся карта уезжала
    # в сухую степь и скалы: зелёных низин на ней не оставалось вовсе. Размах
    # берётся от самого поля, а не константой, поэтому правка шума не ломает
    # вид карты.
    lo = min(elev)
    inv = 255.0 / max(1e-6, max(elev) - lo)

    shape = [(i / 255.0) ** LAND_BIAS for i in range(256)]
    lut = [_ramp_sample(LAND_RAMP, i / 255.0) for i in range(256)]
    # Буфер собирается сразу в RGBA: 255 в альфе — это «здесь суша, поверх
    # непрозрачна». Прозрачность появится только на последнем шаге, когда
    # ляжет маска берега. Конвертировать поверхность под формат экрана нельзя
    # — смена видеорежима делает такую поверхность недействительной, а
    # кэш рельефа общий у всех экранов карты.
    buf = bytearray(hw * hh * 4)
    relief = LAND_RELIEF
    i4 = 0
    for y in range(hh):
        row = y * hw
        row_up = row - hw if y else row
        for x in range(hw):
            i = row + x
            e = elev[i]
            # Свет с северо-запада: склон ярче там, где местность идёт ВНИЗ к
            # западу и к северу, то есть где высота растёт к северо-востоку.
            sl = ((e - elev[row + (x - 1 if x else 0)])
                  + (e - elev[row_up + x]))
            sh = 1.0 + relief * sl
            if sh < 0.62:
                sh = 0.62
            elif sh > 1.32:
                sh = 1.32
            t = shape[int((e - lo) * inv)] + (parcel[i] - 0.5) * 0.14
            if t <= 0.0:
                ci = 0
            elif t >= 1.0:
                ci = 255
            else:
                ci = int(t * 255.0)
            r, g, b = lut[ci]
            wet = (moist[i] - 0.5) * LAND_WET_GAIN
            r += wet * -26.0
            g += wet * 24.0
            b += wet * -16.0
            r = (r - LAND_PIVOT) * LAND_CONTRAST + LAND_PIVOT
            g = (g - LAND_PIVOT) * LAND_CONTRAST + LAND_PIVOT
            b = (b - LAND_PIVOT) * LAND_CONTRAST + LAND_PIVOT
            r *= sh
            g *= sh
            b *= sh
            buf[i4] = 0 if r < 0 else (255 if r > 255 else int(r))
            buf[i4 + 1] = 0 if g < 0 else (255 if g > 255 else int(g))
            buf[i4 + 2] = 0 if b < 0 else (255 if b > 255 else int(b))
            buf[i4 + 3] = 255
            i4 += 4

    base = pygame.image.frombuffer(bytes(buf), (hw, hh), "RGBA")
    del buf
    if (hw, hh) != (w, h):
        try:
            base = pygame.transform.smoothscale(base, (w, h))
        except Exception:
            base = pygame.transform.scale(base, (w, h))

    # --- 2. лоскутки полей поверх общего тона -----------------------------
    # Те самые светлые поля на референсе. Раньше это были прямоугольники со
    # скруглением и альфой 26 — они читались не как поля, а как панели
    # интерфейса, наложенные на карту. Теперь это неровные клочья в 5-7 вершин
    # под альфой 12-16, и рисуются они втрое мельче с растягиванием: прямые
    # края на полной величине выдавали рисунок сразу.
    pw3, ph3 = 29, 22
    parcels = pygame.Surface((max(8, w // 3), max(8, h // 3)), pygame.SRCALPHA)
    row_idx = -1
    for gy in range(-ph3, h // 3 + ph3, ph3):
        for gx in range(-pw3, w // 3 + pw3, pw3):
            row_idx += 1
            r2 = random.Random(seed * 131 + row_idx * 977)
            warm = r2.random()
            if warm < 0.30:
                col = (188, 176, 104, 22)       # ячменное поле
            elif warm < 0.58:
                col = (162, 164, 92, 20)       # злаковое
            elif warm < 0.82:
                col = (88, 110, 56, 20)        # луг
            else:
                col = (52, 66, 38, 20)         # залежь
            bwid = pw3 * (0.45 + 0.55 * r2.random())
            bhei = ph3 * (0.45 + 0.55 * r2.random())
            cx = gx / 3.0 + r2.randint(-5, 5)
            cy = gy / 3.0 + r2.randint(-4, 4)
            pts = []
            for k in range(r2.randint(5, 7)):
                ang = math.tau * k / 5.0
                # клочок не круглый: углы растянуты по двум осям и сбиты
                rx = bwid * 0.5 * (0.72 + 0.4 * r2.random())
                ry = bhei * 0.5 * (0.72 + 0.4 * r2.random())
                pts.append((cx + math.cos(ang) * rx, cy + math.sin(ang) * ry))
            pygame.draw.polygon(parcels, col, pts)
    # Второй, мелкий масштаб: одними крупными клочьями карта остаётся
    # однообразной — вблизи не видно, что земля вообще из чего-то состоит.
    fine_idx = -1
    for gy in range(-11, h // 3 + 11, 11):
        for gx in range(-13, w // 3 + 13, 13):
            fine_idx += 1
            r3 = random.Random(seed * 71 + fine_idx * 613)
            pick = r3.random()
            if pick < 0.5:
                col = (198, 190, 132, 16)
            else:
                col = (46, 58, 34, 16)
            cx = gx / 3.0 + r3.randint(-3, 3)
            cy = gy / 3.0 + r3.randint(-3, 3)
            rx = 4 + r3.random() * 7
            ry = 2.5 + r3.random() * 5
            pygame.draw.polygon(parcels, col, [
                (cx - rx, cy - ry), (cx + rx * 0.8, cy - ry * 1.1),
                (cx + rx, cy + ry * 0.7), (cx - rx * 0.7, cy + ry)])
    try:
        parcels = pygame.transform.smoothscale(parcels, (w, h))
    except Exception:
        pass
    base.blit(parcels, (0, 0))
    del parcels

    # --- 2b. мазок местности ---------------------------------------------
    # Клочья полей дают ритм, но между ними всё ещё ровная заливка, и глаз
    # читает её как заливку, а не как нарисованную местность. Мягкие вытянутые
    # мазки по случайным углам — это ровно то, что делает референс похожим на
    # референс, а не на диаграмму.
    #
    # Рисуются вчетверо мельче и растягиваются: с жёсткими краями мазки
    # читались как светлые и тёмные осколки, разложенные по карте. После
    # растягивания край уходит в мягкое пятно — ровно то, что нужно мазку.
    k5 = 5.0
    sw5, sh5 = max(8, int(w / k5)), max(8, int(h / k5))
    strokes = pygame.Surface((sw5, sh5), pygame.SRCALPHA)
    r4 = random.Random(seed ^ 0x57A0)
    for _ in range((w * h) // 3600):
        ang = r4.random() * math.tau
        length = (20 + r4.random() * 52) / k5
        thick = (6 + r4.random() * 18) / k5
        cx = r4.uniform(-60, w + 60) / k5
        cy = r4.uniform(-60, h + 60) / k5
        ux, uy = math.cos(ang), math.sin(ang)
        vx, vy = -uy, ux
        if r4.random() < 0.5:
            col = (226, 218, 172, 26)
        else:
            col = (38, 46, 26, 26)
        pygame.draw.polygon(strokes, col, [
            (cx - ux * length * 0.5 - vx * thick,
             cy - uy * length * 0.5 - vy * thick),
            (cx + ux * length * 0.5 - vx * thick * 0.4,
             cy + uy * length * 0.5 - vy * thick * 0.4),
            (cx + ux * length * 0.5 + vx * thick,
             cy + uy * length * 0.5 + vy * thick),
            (cx - ux * length * 0.5 + vx * thick * 0.4,
             cy - uy * length * 0.5 + vy * thick * 0.4),
        ])
    try:
        strokes = pygame.transform.smoothscale(strokes, (w, h))
    except Exception:
        pass
    base.blit(strokes, (0, 0))
    del strokes

    # --- 3. лес -----------------------------------------------------------
    _paint_land_forest(base, seed, w, h, cell, moist, gw, gh)

    # --- 4. тон провинции -------------------------------------------------
    # Соседние владения одной державы не должны сливаться в одно пятно, но и
    # не должны выглядеть разноцветной мозаикой: подсветка едва различима,
    # её роль — дать глазу границу там, где шов тонкий.
    #
    # Заливка идёт в два прохода: сначала все полигоны ОБВОДКОЙ, потом все
    # полигоны заливкой. Так земля доходит до середины узкого водного
    # промежутка (его замыкает соседняя провинция), но ни одна заливка не
    # наползает на соседа: всякая точная заливка стирает любой обводочный
    # вылет, потому что проходит после всех обводок.
    local_polys = [[(x - origin[0], y - origin[1]) for x, y in poly]
                   for poly in polygons]
    tint = pygame.Surface((w, h), pygame.SRCALPHA)
    for idx, local in enumerate(local_polys):
        r3 = random.Random(seed * 8191 + idx)
        col = (236, 226, 186, 16) if r3.random() < 0.5 else (48, 46, 30, 16)
        pygame.draw.polygon(tint, col, local, LAND_CHANNEL_PAD * 2)
    for idx, local in enumerate(local_polys):
        r3 = random.Random(seed * 8191 + idx)
        col = (236, 226, 186, 16) if r3.random() < 0.5 else (48, 46, 30, 16)
        pygame.draw.polygon(tint, col, local)
    base.blit(tint, (0, 0))
    del tint

    # --- 5. зерно бумаги ---------------------------------------------------
    grain = _land_grain_tile(seed)
    gw_t, gh_t = grain.get_width(), grain.get_height()
    for gy in range(0, h, gh_t):
        for gx in range(0, w, gw_t):
            base.blit(grain, (gx, gy), special_flags=pygame.BLEND_RGB_ADD)

    # --- 6. притемнение к берегу и к краю карты ---------------------------
    # Мягкое поле «насколько глубоко внутри суши мы находимся»: маска
    # уменьшается и размывается увеличением обратно. Домножаем рисунок на
    # него — и кромка суши темнеет, а середина материка остаётся светлой.
    # Сюда же добавлено притемнение к краям кадра: карта дышит по центру и
    # не спорит с рамкой HUD.
    mask = pygame.Surface((w, h), pygame.SRCALPHA)
    for local in local_polys:
        pygame.draw.polygon(mask, (255, 255, 255, 255), local)
    # Узкие водные промежутки замыкаем землёй: по ним идут реки, а сквозь
    # них был виден океан, и река читалась как тёмный коридор шириной в
    # три раза больше самой реки. Настоящее море у края материка остаётся.
    _close_narrow_channels(mask, local_polys)
    sw = max(8, w // 6)
    sh = max(8, h // 6)
    # Маска рисуется СРАЗУ в мелком разрешении, а не уменьшается готовой.
    # smoothscale в 6 раз на альфа-канале не усредняет площадь, а выбирает
    # значение в одной точке: море и суша превращались в блоки 6x6, и после
    # обратного растяжения по карте шла решётка жёстких прямоугольных швов —
    # именно они читались как царапины и рваные полосы. Заливка полигонов в
    # маленькую поверхность даёт честную долю покрытия на пиксель.
    fall = pygame.Surface((sw, sh), pygame.SRCALPHA)
    kx = sw / float(w)
    ky = sh / float(h)
    lo_polys = [[(x * kx, y * ky) for x, y in lp] for lp in local_polys]
    for lo in lo_polys:
        pygame.draw.polygon(fall, (255, 255, 255, 255), lo)
    _close_narrow_channels(fall, lo_polys)
    tobytes = getattr(pygame.image, "tobytes", None) or pygame.image.tostring
    raw = tobytes(fall, "RGBA")
    del fall
    dbuf = bytearray(sw * sh * 3)
    j = 0
    inv_x = 1.0 / max(1.0, sw * 0.5)
    inv_y = 1.0 / max(1.0, sh * 0.5)
    for y in range(sh):
        ey = min(y, sh - 1 - y) * inv_y
        for x in range(sw):
            a = raw[(y * sw + x) * 4 + 3]
            k = 202 + (a * 53) // 255        # 0.79 у кромки -> 1.0 в глубине
            ex = min(x, sw - 1 - x) * inv_x
            edge = ex if ex < ey else ey
            if edge < 0.46:
                k = int(k * (0.80 + 0.20 * (edge / 0.46)))
            if k > 255:
                k = 255
            dbuf[j] = k
            dbuf[j + 1] = k
            dbuf[j + 2] = k
            j += 3
    del raw
    dim = pygame.image.frombuffer(bytes(dbuf), (sw, sh), "RGB")
    del dbuf
    dim = pygame.transform.smoothscale(dim, (w, h))
    base.blit(dim, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    del dim

    # --- 7. маска суши -----------------------------------------------------
    base.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
    return base


def _paint_land_forest(surf: pygame.Surface, seed: int, w: int, h: int,
                       cell: int, moist: List[float], gw: int, gh: int):
    """Лес по всей суше: мягкие пятна во влажных низинах.

    Массивы не привязаны к провинциям: лес переходит через границу владения,
    как на настоящей карте, иначе граница читалась бы стеной.

    Пятна намеренно крупные и идут внахлёст. Прежние двадцать точек радиусом
    3-6 на массив давали россыпь отдельных кружков — на карте это читалось как
    брызги, а не как древесина. Массив получается, когда точек много, они
    крупные и половина из них ложится поверх предыдущих.
    """
    rng = random.Random(seed ^ 0xF0E57)
    clusters = max(14, (w * h) // 34000)
    tries = 0
    placed = 0
    canopy = (3, 4, 5, 6, 7)
    under = (9, 12, 15, 18)
    while placed < clusters and tries < clusters * 14:
        tries += 1
        cx = rng.randrange(-60, w + 60)
        cy = rng.randrange(-60, h + 60)
        wet = _field_at(moist, cell, cx // LAND_STEP, cy // LAND_STEP, gw, gh)
        if wet < 0.525:
            continue
        placed += 1
        spread_x = rng.uniform(30, 84)
        spread_y = rng.uniform(24, 62)
        col = LAND_FOREST_COLORS[rng.randrange(len(LAND_FOREST_COLORS))]
        # подстилка: несколько крупных слабых пятен. Именно она делает
        # массив массивом — без неё точки остаются россыпью.
        for _ in range(rng.randint(7, 13)):
            ang = rng.random() * math.tau
            rad = 0.2 + 0.8 * rng.random()
            px = int(cx + math.cos(ang) * spread_x * rad)
            py = int(cy + math.sin(ang) * spread_y * rad)
            if px < 0 or py < 0 or px >= w or py >= h:
                continue
            r = under[rng.randrange(len(under))]
            surf.blit(_forest_dot(r, col, 96), (px - r, py - r))
        # крона: плотная куча тёмных пятен поверх подстилки
        for _ in range(rng.randint(34, 58)):
            ang = rng.random() * math.tau
            rad = 0.15 + 0.85 * rng.random()
            px = int(cx + math.cos(ang) * spread_x * rad)
            py = int(cy + math.sin(ang) * spread_y * rad)
            if px < 0 or py < 0 or px >= w or py >= h:
                continue
            r = canopy[rng.randrange(len(canopy))]
            shade = col
            if rng.random() < 0.35:
                shade = LAND_FOREST_COLORS[rng.randrange(len(LAND_FOREST_COLORS))]
            # Сила пятна гуляет: одинаковая альфа у всех точек массива давала
            # край «пузырями», и лес читался как гроздь шариков.
            strength = 150 + rng.randrange(80)
            surf.blit(_forest_dot(r, shade, strength), (px - r, py - r))


#: Мемо поверхностей суши на уровне модуля. Экраны карты создаются десятками
#: (тесты, переходы), и пересобирать 1.6 Мпикс рельефа на каждый — значит
#: платить по полтора-две секунды на экран.
_LAND_MEMO: Dict[tuple, pygame.Surface] = {}


# ===========================================================================
# БЛИТ В ФОРМАТЕ ЭКРАНА
# ===========================================================================
# Блит поверхности, которая лежит в чужом пиксельном формате, идёт через
# конвертацию каждого пикселя: три больших слоя (океан, рельеф, окантовка) на
# 1.6 Мпикс каждый превращались в 100 мс на кадр вместо полутора. Поэтому
# статичные слои один раз переводятся в формат экрана.
#
# Кэш общий на процесс и сам себя чинит: `convert_alpha` в pygame даёт
# поверхность, которая умирает при смене видеорежима, а экраны карты создаются
# по одному на каждый вход в игру и на каждый тест. Поэтому ключ включает
# подпись текущего видеорежима — как только режим сменился, кэш выбрасывается.
_CONVERT_CACHE: Dict[tuple, pygame.Surface] = {}
_CONVERT_SIG: Optional[tuple] = None


def _display_signature():
    disp = pygame.display.get_surface()
    if disp is None:
        return None
    return (id(disp), disp.get_size(), disp.get_flags())


def display_ready(surf: pygame.Surface, key) -> pygame.Surface:
    """Копия статичной поверхности в формате экрана — ради быстрого блита.

    Отдельно от ``convert_alpha`` потому, что результат нельзя хранить вечно:
    pygame инвалидирует сконвертированные поверхности при смене видеорежима, а
    кэш рельефа и окантовки живёт дольше одного режима. Как только подпись
    режима не совпала, кэш выбрасывается целиком.
    """
    global _CONVERT_SIG
    sig = _display_signature()
    if sig != _CONVERT_SIG:
        _CONVERT_CACHE.clear()
        _CONVERT_SIG = sig
    out = _CONVERT_CACHE.get(key)
    if out is not None:
        return out
    try:
        out = surf.convert_alpha()
    except Exception:
        out = surf
    if len(_CONVERT_CACHE) > 64:
        _CONVERT_CACHE.clear()
    _CONVERT_CACHE[key] = out
    return out


def _land_cache_path(digest: str, size: Tuple[int, int]) -> str:
    return os.path.join(
        ASSETS_DIR,
        f"land_{digest}_{size[0]}x{size[1]}_v{LAND_TEX_VERSION}.png")


# ===========================================================================
# УЗКИЕ ВОДНЫЕ ПРОМЕЖУТКИ МЕЖДУ ПРОВИНЦИЯМИ
# ===========================================================================
# Провинции разведены не вплотную, а водными промежутками шириной 32-42 px, и
# по этим промежуткам идут обе реки карты. Проверка «у этого ребра есть сосед» их
# не ловит: соседа нет, ребро формально берег — и по обеим стенкам промежутка
# рисовался берег: тёмная черта, светлая губа и отмель. В итоге река читалась не
# как вода, а как тёмный коридор шириной в два с половиной раза больше самой
# реки, прорезанный в карте.
#
# Помощники ниже отличают УЗКИЙ промежуток (его замыкает земля, река рисуется
# поверх) от ОТКРЫТОГО моря (настоящий берег остаётся).

#: Шаг сетки «есть ли здесь суша», px. Восемь пикселей — с запасом: каналы от
#: 32 px, а берег мы ищем с точностью до половины шага.
LAND_GRID_CELL = 8
#: Промежуток уже этого размера считается рекой, а не морем, px.
LAND_CHANNEL_MAX = 128
#: Насколько шире самой земли рисуется заливка промежутка, px. Запас нужен,
#: потому что границы провинций нарисованы с независимым дрожанием вершин и
#: их ломаные не совпадают ни на пиксель.
LAND_CHANNEL_PAD = 10


def _land_grid(polygons_local, w: int, h: int, cell: int = LAND_GRID_CELL):
    """Грубая сетка «здесь суша» и её размеры.

    Рисуется самим pygame в уменьшенном виде и читается байтами — это дешевле
    и надёжнее, чем проверять каждую ячейку по полигонам. Нужен именно ответ
    «есть ли тут земля», а не её контур, поэтому сглаживание не важно.
    """
    gw = max(1, w // cell)
    gh = max(1, h // cell)
    surf = pygame.Surface((gw, gh), pygame.SRCALPHA)
    for poly in polygons_local:
        pygame.draw.polygon(surf, (255, 255, 255, 255),
                            [(x / cell, y / cell) for x, y in poly])
    tobytes = getattr(pygame.image, "tobytes", None) or pygame.image.tostring
    raw = tobytes(surf, "RGBA")
    grid = bytearray(gw * gh)
    for i in range(gw * gh):
        if raw[i * 4 + 3] > 127:
            grid[i] = 1
    del surf
    return grid, gw, gh


def _narrow_gap(grid, gw: int, gh: int, mx: float, my: float,
                nx: float, ny: float, limit: int = LAND_CHANNEL_MAX):
    """Ширина узкого водного промежутка напротив ребра, либо ``None``.

    Идём от ребра наружу по нормали и смотрим, есть ли земля в пределах
    ``limit`` px. Есть — значит промежуток узкий и это река: земля замыкает
    его, берег рисовать нельзя. Нет — перед нами настоящее море.
    """
    cell = LAND_GRID_CELL
    max_c = max(1, int(limit // cell))
    for k in range(1, max_c + 1):
        px = int((mx + nx * cell * k) // cell)
        py = int((my + ny * cell * k) // cell)
        if px < 0 or py < 0 or px >= gw or py >= gh:
            return None
        if grid[py * gw + px]:
            return cell * k
    return None


def coast_segments(polygons_local, w: int, h: int):
    """Настоящий берег: отрезки, за которыми открытое море, а не промежуток.

    Отдаёт для каждой провинции список ``(a, b, nx, ny)`` — ребро и нормаль
    наружу. Ребро считается берегом только если за ним в пределах
    :data:`LAND_CHANNEL_MAX` px не нашлось земли, то есть это не узкий
    водный промежуток между провинциями.
    """
    grid, gw, gh = _land_grid(polygons_local, w, h)
    index: Dict[tuple, List[int]] = {}
    for idx, poly in enumerate(polygons_local):
        for a, b in zip(poly, poly[1:] + poly[:1]):
            key = (a, b) if a <= b else (b, a)
            index.setdefault(key, []).append(idx)
    out: List[List[Tuple[Tuple[int, int], Tuple[int, int], float, float]]] = []
    for idx, poly in enumerate(polygons_local):
        n = float(len(poly))
        center = (sum(p[0] for p in poly) / n, sum(p[1] for p in poly) / n)
        runs = []
        for a, b in zip(poly, poly[1:] + poly[:1]):
            key = (a, b) if a <= b else (b, a)
            if any(o != idx for o in index.get(key, ())):
                continue                      # ребро общее с соседом
            nx, ny = _outward_normal(a, b, center)
            if nx == 0.0 and ny == 0.0:
                continue
            mx = (a[0] + b[0]) * 0.5
            my = (a[1] + b[1]) * 0.5
            if _narrow_gap(grid, gw, gh, mx, my, nx, ny) is not None:
                continue                      # узкий промежуток, это река
            runs.append((a, b, nx, ny))
        out.append(runs)
    return out


def _channel_runs(polygons_local, w: int, h: int, grid, gw: int, gh: int):
    """Рёбра, за которыми узкий водный промежуток, вместе с его шириной."""
    index: Dict[tuple, List[int]] = {}
    for idx, poly in enumerate(polygons_local):
        for a, b in zip(poly, poly[1:] + poly[:1]):
            key = (a, b) if a <= b else (b, a)
            index.setdefault(key, []).append(idx)
    out: List[List[Tuple[Tuple[int, int], Tuple[int, int], float, float, int]]] = []
    for idx, poly in enumerate(polygons_local):
        n = float(len(poly))
        center = (sum(p[0] for p in poly) / n, sum(p[1] for p in poly) / n)
        runs = []
        for a, b in zip(poly, poly[1:] + poly[:1]):
            key = (a, b) if a <= b else (b, a)
            if any(o != idx for o in index.get(key, ())):
                continue
            nx, ny = _outward_normal(a, b, center)
            if nx == 0.0 and ny == 0.0:
                continue
            depth = _narrow_gap(grid, gw, gh, (a[0] + b[0]) * 0.5,
                                (a[1] + b[1]) * 0.5, nx, ny)
            if depth is not None:
                runs.append((a, b, nx, ny, depth))
        out.append(runs)
    return out


def channel_fill_polys(polygons_local, w: int, h: int,
                       span_mul: float = 1.0, pad: int = LAND_CHANNEL_PAD):
    """Четырёхугольники, закрывающие узкие водные промежутки, по провинциям.

    Отдаёт ``[[quad, ...], ...]`` в локальных координатах поверхности. Одну и ту
    же геометрию используют три места: маска суши, силуэт для тени и плёнка
    владений. Если они разойдутся хотя бы на пиксель, промежуток снова
    появится — и снова станет тёмным коридором.

    ``span_mul`` и ``pad`` решают, насколько далеко заливка заходит за свой
    берег. Маске нужно перекрыть промежуток целиком (с запасом), а плёнке
    владений — только половину: иначе окраска переваливала бы через весь
    промежуток и залезала на соседнее владение твёрдой полосой.
    """
    grid, gw, gh = _land_grid(polygons_local, w, h)
    out = []
    for runs in _channel_runs(polygons_local, w, h, grid, gw, gh):
        quads = []
        for a, b, nx, ny, depth in runs:
            span = depth * span_mul + pad
            quads.append([
                (a[0] + nx * 3, a[1] + ny * 3),
                (b[0] + nx * 3, b[1] + ny * 3),
                (b[0] + nx * span, b[1] + ny * span),
                (a[0] + nx * span, a[1] + ny * span),
            ])
        out.append(quads)
    return out


def _close_narrow_channels(mask: pygame.Surface, polygons_local):
    """Замыкает землёй узкие водные промежутки между провинциями."""
    w, h = mask.get_size()
    for quads in channel_fill_polys(polygons_local, w, h):
        for quad in quads:
            pygame.draw.polygon(mask, (255, 255, 255, 255), quad)


def land_surface(polygons: List[List[Tuple[int, int]]], origin: Tuple[int, int],
                 size: Tuple[int, int], seed: int = LAND_SEED) -> pygame.Surface:
    """Кэшированная поверхность суши. Строится один раз, отдаётся блитом."""
    digest = hashlib.md5(
        (repr(tuple(origin)) + repr(tuple(size)) + repr(seed) + str(len(polygons))).encode("utf-8")
    ).hexdigest()[:10]
    key = (digest, int(size[0]), int(size[1]))
    surf = _LAND_MEMO.get(key)
    if surf is not None:
        return surf

    path = _land_cache_path(digest, size)
    surf = None
    if os.path.isfile(path):
        try:
            loaded = pygame.image.load(path)
            if (loaded.get_width(), loaded.get_height()) == (int(size[0]), int(size[1])):
                surf = loaded.convert_alpha()
        except Exception:
            surf = None
    if surf is None:
        surf = build_land_surface(polygons, origin, size, seed)
        try:
            os.makedirs(ASSETS_DIR, exist_ok=True)
            pygame.image.save(surf, path)
        except Exception:
            pass
    _LAND_MEMO[key] = surf
    return surf


def zoomed_surface(base: pygame.Surface, zoom: float,
                   cache: Dict[float, pygame.Surface],
                   limit: int = LAND_ZOOM_CACHE_LIMIT) -> pygame.Surface:
    """Масштабированная копия статичной поверхности с потолком на кэш.

    То же, что делал экран раньше с пятьюдесятью текстурами провинций, но для
    одного куска: зум — множитель кегля кэша, поэтому в кадре остаётся ровно
    один блит и ни одного пикселя пересчёта. Копия сразу переводится в формат
    экрана — иначе блит миллиона пикселей идёт через конвертацию.
    """
    zr = round(zoom, 1)
    if zr < 0.05:
        zr = 0.05
    hit = cache.get(zr)
    if hit is not None:
        return hit
    if abs(zr - 1.0) < 0.05:
        out = display_ready(base, ("land", id(base)))
    else:
        w = max(1, int(round(base.get_width() * zoom)))
        h = max(1, int(round(base.get_height() * zoom)))
        try:
            scaled = pygame.transform.smoothscale(base, (w, h))
        except Exception:
            scaled = pygame.transform.scale(base, (w, h))
        out = display_ready(scaled, ("land", id(base), zr))
    if len(cache) >= limit:
        # выкидываем самый старый: порядок вставки и есть порядок обхода
        for old in list(cache.keys()):
            if old != zr:
                cache.pop(old, None)
                break
    cache[zr] = out
    return out


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
WATER_DEEP = (20, 36, 52)
WATER_MID = (36, 58, 76)
WATER_LIGHT = (62, 90, 106)
WATER_FOAM = (150, 178, 190)
#: Отмель у берега: три концентрические полосы, которые кладутся ПОД тёмный
#: берег и после вычитания силуэта остаются наружу. Без них суша выглядит
#: вырезанной и наклеенной на воду — на малом зуме, где видно всю карту
#: целиком, это бросается в глаза сильнее всего.
SHELF_COLOR = (126, 166, 184)
SHELF_RINGS = ((16, 26), (11, 42), (7, 66))

#: Реки. На референсе это тихие лавандовые нити, а на карте они были самым
#: ярким объектом: синий кабель поверх хаки-рельефа, и взгляд уходил не туда.
#: Отсюда узкая нить, слабый контраст и почти полное отсутствие бликов.
#: Тон светлее фона рельефа и ярче прежнего тёмного: «тонкая синяя нить» должна
#: читаться как вода, а тёмная линия на светлой земле читалась как трещина.
RIVER_COLOR = (74, 116, 166)
RIVER_DARK = (44, 74, 116)
RIVER_LIGHT = (140, 178, 214)
#: Ширина русла. Раньше внешняя черта была 2.6 px, а внутренняя 1 px — при
#: зуме 1 это нормально, но тёмная подложка рядом с тёмной рекой съевала
#: полосу земли по обе стороны и река читалась шире, чем нарисована.
RIVER_W_OUTER = 3
RIVER_W_INNER = 2
#: Сколько точек подряд (точка == 4 px) маска суши может оборвать, и русло
#: всё равно считается непрерывным. Маска клеточная, с шагом 8, и без этого
#: река рассыпалась на десятки коротких кусков.
RIVER_GAP_BRIDGE = 8


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
        # Второе, мелкое поле — рябь. Без неё море было ровной заливкой с
        # пятнами в сто метров, и на зуме 0.6, где в кадр входит вся карта,
        # вода читалась как пустая серая плоскость.
        rgrid = 5
        rgw, rgh = hw // rgrid + 2, hh // rgrid + 2
        ripple = [[_fbm(gx * 0.021 * rgrid, gy * 0.021 * rgrid, 2, 4211)
                   for gx in range(rgw)] for gy in range(rgh)]
        cx, cy = hw * 0.5, hh * 0.5
        # радиус, за которым виньетка выходит на максимум
        inv_r = 1.0 / max(1.0, math.hypot(cx, cy))
        inv_grid = 1.0 / grid
        inv_rg = 1.0 / rgrid
        for y in range(0, hh, step):
            row_t = y / float(hh - 1)
            fy = y * inv_grid
            gy0 = int(fy)
            ty = fy - gy0
            row_a, row_b = noise[gy0], noise[min(gy0 + 1, gh - 1)]
            ry = y * inv_rg
            rgy0 = int(ry)
            rty = ry - rgy0
            rrow_a = ripple[rgy0]
            rrow_b = ripple[min(rgy0 + 1, rgh - 1)]
            for x in range(0, hw, step):
                fx = x * inv_grid
                gx0 = int(fx)
                gx1 = min(gx0 + 1, gw - 1)
                tx = fx - gx0
                n = ((row_a[gx0] * (1.0 - tx) + row_a[gx1] * tx) * (1.0 - ty)
                     + (row_b[gx0] * (1.0 - tx) + row_b[gx1] * tx) * ty)
                rx = x * inv_rg
                rgx0 = int(rx)
                rgx1 = min(rgx0 + 1, rgw - 1)
                rtx = rx - rgx0
                rp = ((rrow_a[rgx0] * (1.0 - rtx) + rrow_a[rgx1] * rtx) * (1.0 - rty)
                      + (rrow_b[rgx0] * (1.0 - rtx) + rrow_b[rgx1] * rtx) * rty)
                # к горизонту вода светлеет, к нижнему краю — глуше.
                # Растяжка в три ступени, а не в две: между «глубокой» и
                # «мелкой» водой пропадает полутон, и море читается
                # двухполосным.
                t = 0.16 + 0.40 * n + 0.22 * (1.0 - row_t) + 0.16 * rp
                if t <= 0.5:
                    col = _blend_color(WATER_DEEP, WATER_MID, t * 2.0)
                else:
                    col = _blend_color(WATER_MID, WATER_LIGHT, (t - 0.5) * 2.0)
                # виньетка: 0 в центре, 0.30 в углах. Дальше не надо —
                # карта перестанет читаться по краям экрана
                d = math.hypot(x - cx, y - cy) * inv_r
                vig = max(0.0, (d - 0.46) * 2.0) ** 1.7
                f = 1.0 - 0.30 * vig
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
        # В формате экрана: океан — полноэкранный слой под всем остальным, и
        # блит в чужом формате на 1.5 Мпикс стоит десятки миллисекунд.
        self._ocean_cache = display_ready(surf, ("ocean", size))
        self._ocean_size = size
        return self._ocean_cache

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
NEUTRAL_DASH_ON = 9
NEUTRAL_DASH_OFF = 6
#: Подложка пунктира. Без неё в разрывах штрихов проступал цвет владения, и
#: граница с державой читалась как яркая зелёная (или красная) пунктирная
#: линия — то есть не линия, а россыпь пятен на фоне заливки. Тёмная
#: подложка под всем швом превращает разрывы в промежутки линии.
NEUTRAL_DASH_BED_ALPHA = 152
NEUTRAL_DASH_BED_EXTRA = 2
#: Насколько широко плёнка владения убирается из-под шва, сверх его толщины.
#: Граница должна лежать на голой земле, а не поверх заливки, иначе штрихи
#: пунктира тонут в цвете державы и линия рассыпается.
TINT_GUTTER_PAD = 4


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


def _border_paths(run: List[Tuple[int, int]], chunk: int = 5,
                  samples: int = 8):
    """Две формы одной границы: как в данных и как на карте.

    Первая — вершины, выстроенные вдоль преобладающей оси шва. Данные описывают
    границу слева направо (сверху вниз у вертикальных швов), а кольцо
    полигона их просто переставляет: общая граница Highpeak—Verdant приходит
    вершинами 1343 → 1265 → 1291 → 1316 → 1240, то есть дважды возвращается
    назад. Рисовать это «честно» нельзя — на карте ветки и кольца, будто линия
    порвана. Сортировка убирает самопересечение.

    Вторая — та же цепочка, ведомая квадратичными кривыми по четыре вершины
    через среднее внутренних точек: такая кривая между двумя концами с одним
    управляющим pointом не пересекает сама себя и читается как проведённая
    рукой линия.

    Обе соприкасающиеся провинции получают одну и ту же кривую: набор вершин
    после сортировки одинаков, поэтому обход в обратную сторону даёт ту же
    линию с точностью до порядка точек.
    """
    pts = list(run)
    if len(pts) < 3:
        return pts, [(float(p[0]), float(p[1])) for p in pts]
    span_x = max(p[0] for p in pts) - min(p[0] for p in pts)
    span_y = max(p[1] for p in pts) - min(p[1] for p in pts)
    axis = 0 if span_x >= span_y else 1
    ordered = sorted(pts, key=lambda p: p[axis])
    smooth = [(float(ordered[0][0]), float(ordered[0][1]))]
    n = len(ordered) - 1
    i = 0
    while i < n:
        j = min(i + chunk, n)
        ax, ay = ordered[i]
        bx, by = ordered[j]
        if j - i < 2:
            smooth.append((float(bx), float(by)))
        else:
            inner = ordered[i + 1:j]
            cx = sum(p[0] for p in inner) / len(inner)
            cy = sum(p[1] for p in inner) / len(inner)
            for k in range(1, samples + 1):
                t = k / samples
                m = 1.0 - t
                smooth.append((m * m * ax + 2 * m * t * cx + t * t * bx,
                               m * m * ay + 2 * m * t * cy + t * t * by))
        i = j
    return ordered, smooth


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
                    zoom: float, border_style,
                    owner_tint=None) -> pygame.Surface:
    """Одна поверхность со всей «окантовкой» карты: тень, тон владений, берег,
    границы.

    Собирается один раз и блитится одним куском, поэтому в кадре не остаётся
    ни одной попиксельной работы. Пять составляющих, по порядку наложения:

    * тень под сушей — силуэт, сдвинутый на 1-2 px и 3-4 px, из которого
      вычтен силуэт на месте. Остаётся серп вокруг суши, и потому слой
      можно класть ПОВЕРХ рельефа: внутри суши он всё равно прозрачен;
    * **тон владений** — полупрозрачная заливка полигонов цветом державы
      (``owner_tint``: держава -> готовый RGBA). Раньше цвет нации жил в
      текстуре самой провинции, и окраска была неотделима от рисунка
      местности: перекраска стоила перегенерации текстуры, а сквозь
      полупрозрачные пятна леса просвечивало море. Теперь это отдельный слой
      поверх рельефа — захват провинции перекрашивает ровно один
      многоугольник;
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
    # Настоящий берег — только тот, за которым открытое море. Ребра, за
    # которыми узкий водный промежуток между провинциями (а это ровно русла
    # обеих рек карты), берегом не считаются: раньше по их стенкам рисовались
    # тёмная черта, светлая губа и отмель, и река выглядела тёмным коридором
    # шириной в три раза больше самой реки.
    coasts = coast_segments(local, w, h)
    # Тот же набор заливок, что и в маске суши: тень должна падать от внешнего
    # контура материка, а не от стенок речных промежутков. Иначе в промежутке
    # остаётся тёмная полоса шириной с саму реку.
    channels = channel_fill_polys(local, w, h)
    # Плёнке владений достаётся только половина промежутка: обе стенки красят
    # навстречу друг другу и встречаются посередине, где и проходит река. Если
    # красить целиком, окраска перевалила бы через весь промежуток и легла
    # твёрдой полосой на соседнее владение.
    tint_channels = channel_fill_polys(local, w, h, span_mul=0.5, pad=0)
    frame = pygame.Surface((w, h), pygame.SRCALPHA)

    # --- 1. тень под сушей -------------------------------------------------
    sil = pygame.Surface((w, h), pygame.SRCALPHA)
    for alpha, shift in ((FRAME_SHADOW_FAR, (3, 4)),
                         (FRAME_SHADOW_NEAR, (1, 2))):
        sil.fill((0, 0, 0, 0))
        for poly in local:
            pygame.draw.polygon(sil, (0, 0, 0, alpha), poly)
        for quads in channels:
            for quad in quads:
                pygame.draw.polygon(sil, (0, 0, 0, alpha), quad)
        frame.blit(sil, shift)
        # вычитаем силуэт на месте: серп остаётся только вокруг суши
        frame.blit(sil, (0, 0), special_flags=pygame.BLEND_RGBA_SUB)
    del sil

    # --- 2. тон владений ----------------------------------------------------
    # Плёнка собирается на отдельной поверхности, а не сразу на карте: только
    # так её можно вычистить вдоль швов (шаг ниже). Писать прямо на карту
    # нельзя — там под плёнкой рельеф, и «чистка» пробила бы дыру до океана.
    tint_surf = pygame.Surface((w, h), pygame.SRCALPHA)
    if owner_tint:
        # Заливка не должна наползать на воду, поэтому у прибрежных провинций
        # полигон вырезается из маски соседей. У inland-провинций вырезать
        # нечего — и для них заливка идёт прямоугольником, без всякой маски.
        # Это не мелочь: поверхность на весь bbox создавалась для каждой из
        # пятидесяти провинций, то есть 300 МБ лишних аллокаций на каждое
        # изменение зума или раскладки владений.
        clip = None
        for idx, poly in enumerate(local):
            col = owner_tint.get(owners[idx]) if idx < len(owners) else None
            if col is None:
                continue
            if not coasts[idx]:
                pygame.draw.polygon(tint_surf, col, poly)  # суша со всех сторон
                continue
            peers = set()
            for a, b, _nx, _ny in coasts[idx]:
                key = (a, b) if a <= b else (b, a)
                for other in edge_index.get(key, ()):
                    if other != idx:
                        peers.add(other)
            if clip is None:
                clip = pygame.Surface((w, h), pygame.SRCALPHA)
            xs = [p[0] for p in poly]
            ys = [p[1] for p in poly]
            box = pygame.Rect(min(xs) - 1, min(ys) - 1,
                              max(xs) - min(xs) + 3, max(ys) - min(ys) + 3)
            box.clamp_ip(pygame.Rect(0, 0, w, h))
            if box.width < 1 or box.height < 1:
                continue
            clip.fill((0, 0, 0, 0), box)
            # Полигон рисуется ЦЕЛИКОМ: отбрасывание вершин за пределы bbox
            # не обрезает фигуру, а ломает её — провинция превращалась в
            # зелёную кляксу с полосами соседей. pygame и сам обрезает по
            # экрану, а лишнее за bbox всё равно не блитится.
            pygame.draw.polygon(clip, col, poly)
            for other in peers:
                if other >= len(local):
                    continue
                pygame.draw.polygon(clip, (0, 0, 0, 0), local[other])
            # Третий аргумент blit — кусок ИСТОЧНИКА, поэтому адрес назначения
            # обязан быть углом box, а не (0, 0): иначе все заливки владений
            # складывались в левый верхний угол карты.
            tint_surf.blit(clip, box.topleft, box)
        del clip
        # Промежутки между провинциями — тоже земля, и окраска должна доходить
        # до их середины, иначе внутри владения идёт нейтральная полоса.
        for idx, quads in enumerate(tint_channels):
            col = owner_tint.get(owners[idx]) if idx < len(owners) else None
            if col is None:
                continue
            for quad in quads:
                pygame.draw.polygon(tint_surf, col, quad)

    # Плёнка убирается из-под швов. Иначе граница с державой выглядит не
    # линией, а россыпью пятен заливки: у пунктира в разрывах проступал цвет
    # владения, и «зелёная» граница выглядела как зелёный пунктир. Убирать
    # плёнку можно только на отдельной поверхности — на самой карте под ней
    # рельеф, и чистка пробила бы дыру до океана.
    #
    # Снимается ровно то, что попадает под шов: клин между границей владения
    # (по которой идёт плёнка) и сглаженной линией (по которой рисуется шов),
    # плюс узкая полоса под саму линию. Раньше линия уходила внутрь
    # многоугольника, и в образовавшемся зазоре оставались зелёные кляксы.
    for idx, poly in enumerate(local):
        for run, peer in _border_runs(poly, edge_index, idx):
            if peer is None:
                continue
            style = border_style(idx, peer)
            if style is None:
                continue
            ordered, smooth = _border_paths(run)
            pygame.draw.polygon(tint_surf, (0, 0, 0, 0),
                                [(float(x), float(y)) for x, y in ordered]
                                + list(reversed(smooth)))
            bed_w = int(style[2]) + TINT_GUTTER_PAD
            for a, b in zip(smooth, smooth[1:]):
                pygame.draw.line(tint_surf, (0, 0, 0, 0),
                                 (int(round(a[0])), int(round(a[1]))),
                                 (int(round(b[0])), int(round(b[1]))), bed_w)
    frame.blit(tint_surf, (0, 0))
    del tint_surf

    # --- 3. берег и тиснение ----------------------------------------------
    # Каждая черта сдвинута НАРУЖУ от кромки на половину своей толщины
    # (минус пиксель, чтобы шов смыкался с землёй). Раньше черты рисовались по
    # кромке, а силуэт суши потом ВЫЧИТАЛСЯ из них: это стоило двух полноэкранных
    # поверхностей на каждый кадр и, что важнее, съедало берег в узких водных
    # промежутках — там силуэт проходил вплотную к кромке, и от края не
    # оставалось ничего. Сдвиг наружу даёт тот же рисунок без вычитания.
    coast = pygame.Surface((w, h), pygame.SRCALPHA)
    for runs in coasts:
        for a, b, nx, ny in runs:
            # Отмель: широкие бледные полосы вдоль контура суши, то есть мягкая
            # светлая кромка воды.
            for width, alpha in SHELF_RINGS:
                off = width * 0.5 - 1
                pygame.draw.line(coast, SHELF_COLOR + (alpha,),
                                 (a[0] + nx * off, a[1] + ny * off),
                                 (b[0] + nx * off, b[1] + ny * off), width)
            # Губа на северных склонах — имитация тиснения бумаги.
            if ny < -0.25:
                off = 3.0 - 1
                pygame.draw.line(coast, COAST_LIGHT + (150,),
                                 (a[0] + nx * off, a[1] + ny * off),
                                 (b[0] + nx * off, b[1] + ny * off), 6)
    # Тёмный берег — тонкая черта точно по кромке.
    for runs in coasts:
        for a, b, nx, ny in runs:
            pygame.draw.line(coast, COAST_INK + (255,),
                             (a[0] + nx * 0.5, a[1] + ny * 0.5),
                             (b[0] + nx * 0.5, b[1] + ny * 0.5), 2)
    frame.blit(coast, (0, 0))
    del coast

    # --- 4. границы владений ----------------------------------------------
    # ``border_style(idx, peer)`` возвращает (краска, сердцевина, толщина,
    # пунктир) либо None, если линию рисовать не нужно. Сердцевина — тонкая
    # светлая нить поверх тёмной краски: сама краска отвечает за контраст,
    # а нить — за то, что шов переговорный.
    #
    # Ломаная сначала выстраивается вдоль своей оси и сглаживается (данные о
    # границе приходят в перепутанном порядке и местами пересекают сами себя,
    # а «честная» линия выходит рваной, как трещина). Шов рисуется ОДИН раз:
    # обе соприкасающиеся провинции обходят его в противоположных
    # направлениях, и при пунктире это давало два несовпадающих рисунка
    # штрихов — на вид рваные ветки. Если стиль с двух сторон разный (такого
    # сейчас нет, но вызов может вернуть), шов рисуется с обеих сторон.
    for idx, poly in enumerate(local):
        for run, peer in _border_runs(poly, edge_index, idx):
            if peer is None:
                continue                      # берег уже нарисован выше
            style = border_style(idx, peer)
            if style is None:
                continue
            other_style = (border_style(peer, idx)
                           if 0 <= peer < len(local) else None)
            if idx > peer and other_style == style:
                continue                      # этот шов уже нарисован иначе
            _ordered, curve = _border_paths(run)
            smooth = [(int(round(x)), int(round(y))) for x, y in curve]
            color, core, width, dashed = style
            if dashed:
                # сплошная тёмная подложка по всему шву, поверх неё — штрихи
                bed = (color[0], color[1], color[2], NEUTRAL_DASH_BED_ALPHA)
                for a, b in zip(smooth, smooth[1:]):
                    pygame.draw.line(frame, bed, a, b,
                                     width + NEUTRAL_DASH_BED_EXTRA)
                _draw_dashed(frame, smooth, color, width,
                             NEUTRAL_DASH_ON, NEUTRAL_DASH_OFF)
            else:
                for a, b in zip(smooth, smooth[1:]):
                    pygame.draw.line(frame, color, a, b, width)
                if core is not None and width > 1:
                    core_w = max(1, width - 2)
                    for a, b in zip(smooth, smooth[1:]):
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

        Табличка пергаментная, а не чёрная: чёрный прямоугольник на хаки-карте
        читается как чужое окно, а нарисованная на пергаменте табличка
        выглядит частью росписи. Поверх — тонкая тёмная обводка и кромка
        цвета знамени, чтобы знамя было узнаваемо и без самого знамени.
        """
        key = (label, int(size))
        plate = GeneralIcon._LABEL_CACHE.get(key)
        if plate is not None:
            return plate
        font = _cached_font("serif", size)
        txt = font.render(label, True, (26, 22, 14))
        w = txt.get_width() + 10
        h = txt.get_height() + 6
        plate = pygame.Surface((w, h), pygame.SRCALPHA)
        plate.fill((228, 219, 190, 236))
        plate.fill((150, 128, 74, 236), (0, 0, w, 2))
        plate.fill((96, 80, 44, 236), (0, h - 2, w, 2))
        pygame.draw.rect(plate, (34, 28, 16, 235), plate.get_rect(), 1)
        plate.blit(txt, (5, 3))
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
        # Шаг 4 px: точки режется насколько хочется, но каждая точка — это
        # вызовы отрисовки, а на реке их выходило по две тысячи на кадр.
        # Сам расчёт тоже держим на списковых включениях: эта функция зовётся
        # дважды на КАЖДЫЙ кадр, и наивный вложенный цикл усреднения съедал
        # пятую часть бюджета кадра.
        ys = list(range(-20, screen_h - 60, 4))
        p1 = seed + t
        p2 = seed * 2 + t * 1.2
        p3 = seed * 3
        sin = math.sin
        raw = [river_x
               + 15.0 * sin((y + cam_y) * 0.0092 + p1)
               + 7.0 * sin((y + cam_y) * 0.0171 + p2)
               + 3.0 * sin((y + cam_y) * 0.0290 + p3)
               for y in ys]
        n = len(raw)
        if n < 5:
            return [(x, y, y + cam_y) for x, y in zip(raw, ys)]
        # Усреднение по биномиальному ядру 1-2-3-2-1: пила из отрезков по 4 px
        # читалась как кабель, уложенный зигзагом. Плюс огрызки по краям.
        head = [(2.0 * raw[0] + 3.0 * raw[1] + raw[2]) / 6.0]
        body = [(raw[k - 2] + 2.0 * raw[k - 1] + 3.0 * raw[k]
                 + 2.0 * raw[k + 1] + raw[k + 2]) / 9.0
                for k in range(2, n - 2)]
        tail = [(raw[n - 3] + 3.0 * raw[n - 2] + 2.0 * raw[n - 1]) / 6.0]
        sm = head + body + tail
        return [(x, y, y + cam_y) for x, y in zip(sm, ys)]

    @staticmethod
    def draw_river(surface: pygame.Surface, river_x: int, cam_x: int, cam_y: int,
                   screen_h: int, time_ticks: float, zoom: float = 1.0,
                   land: Optional["LandMask"] = None):
        pts = RiverRenderer.river_points(river_x, cam_y, screen_h, time_ticks, seed=river_x)
        if len(pts) < 2:
            return
        runs: List[List[Tuple[int, int, int]]] = []
        if land is None:
            runs = [pts]
        else:
            # Русло режется маской суши не по точкам, а НА ПРОБЕГИ. Прежде
            # непроходимые точки просто выбрасывались, и река соединяла
            # оставшиеся куски длинной прямой — по карте это читалось как
            # трещина в стекле, а не как течение.
            ok = [land.covers((p[0] + p[2]) // 2, p[2]) for p in pts]
            # Маска суши клеточная (8 px), и русло начинало мигать на её
            # границах: река рассыпалась на десятки коротких отрезков. Короткие
            # разрывы просто затыкаются — на карте их и не видно, зато течение
            # снова непрерывное.
            gap = RIVER_GAP_BRIDGE
            i = 0
            n_ok = len(ok)
            while i < n_ok:
                if ok[i]:
                    i += 1
                    continue
                j = i
                while j < n_ok and not ok[j]:
                    j += 1
                if j - i <= gap:
                    for k in range(i, j):
                        ok[k] = True
                i = j
            run: List[Tuple[int, int, int]] = []
            for p, good in zip(pts, ok):
                if good:
                    run.append(p)
                elif run:
                    runs.append(run)
                    run = []
            if run:
                runs.append(run)
        w_outer = max(2, int(RIVER_W_OUTER * zoom))
        w_inner = max(1, int(RIVER_W_INNER * zoom))
        for chain in runs:
            if len(chain) < 2:
                continue
            # ОДНИМ pygame.draw.lines на проход, а не по вызову на сегмент.
            # Две тысячи отдельных draw.line стоили 6 мс кадра — шестую часть
            # бюджета на две нитки, которые рисуются поверх карты.
            screen_pts = [(int((p[0] - cam_x) * zoom), int(p[1] * zoom))
                          for p in chain]
            pygame.draw.lines(surface, RIVER_DARK, False, screen_pts, w_outer)
            pygame.draw.lines(surface, RIVER_COLOR, False, screen_pts, w_inner)
        # редкие блики — детерминированные, без мерцания random каждый кадр
        t = int(time_ticks // 700)
        for chain in runs:
            for i in range(0, len(chain) - 1, 40):
                x1, y1, _ = chain[(i + t) % (len(chain) - 1)]
                sx = int((x1 - cam_x) * zoom)
                sy = int(y1 * zoom)
                pygame.draw.circle(surface, RIVER_LIGHT, (sx, sy), max(1, int(1 * zoom)))

    @staticmethod
    def draw_bridge(surface: pygame.Surface, river_x: int, bridge_y: int,
                    cam_x: int, cam_y: int, zoom: float = 1.0):
        """Каменный мост: низкая арка с перилами.

        Раньше здесь был тёмно-коричневый прямоугольник с четырьмя
        вертикальными полосами — на хаки-карте он читался как приставленная
        лестница. Арка с двумя устоями выглядит мостом и не спорит с рекой.
        """
        sx = int((river_x - cam_x) * zoom)
        sy = int((bridge_y - cam_y) * zoom)
        bw, bh = int(26 * zoom), int(9 * zoom)
        if bw < 4 or bh < 3:
            return
        top = sy - bh // 2
        pygame.draw.rect(surface, (58, 48, 34), (sx - bw // 2, top, bw, bh))
        pygame.draw.rect(surface, (146, 128, 92), (sx - bw // 2 + 1, top + 1,
                                                    bw - 2, bh - 2))
        # пролёт арки — тёмный вырез посередине
        pygame.draw.rect(surface, (44, 44, 34),
                         (sx - bw // 4, top + bh // 2, bw // 2, bh // 2))
        # перила
        pygame.draw.line(surface, (170, 152, 112),
                         (sx - bw // 2, top + 1), (sx + bw // 2, top + 1),
                         max(1, int(zoom)))
        for px in (sx - bw // 2, sx + bw // 2 - max(1, int(zoom))):
            pygame.draw.line(surface, (120, 104, 74), (px, top), (px, top + bh),
                             max(1, int(zoom)))
