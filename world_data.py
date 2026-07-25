import pygame
import math
import random
from typing import List, Tuple, Optional, Dict
from enum import Enum, auto


class Relation(Enum):
    WAR = auto()
    NEUTRAL = auto()
    FRIENDLY = auto()
    ALLIANCE = auto()


class RegionType(Enum):
    VILLAGE = auto()
    CITY = auto()
    CAPITAL = auto()


class Nation:
    def __init__(self, name: str, color: Tuple[int, int, int],
                 light_color: Tuple[int, int, int]):
        self.name = name
        self.color = color
        self.light_color = light_color
        self.gold = 500


class Province:
    def __init__(self, name: str, owner: str, region_type: RegionType,
                 polygon: List[Tuple[int, int]], neighbors: List[str] = None):
        self.name = name
        self.owner = owner
        self.region_type = region_type
        self.polygon = polygon
        self.neighbors = neighbors or []
        self.troops = 0
        self._centroid = None

    @property
    def centroid(self) -> Tuple[int, int]:
        if self._centroid is None:
            n = len(self.polygon)
            cx = sum(p[0] for p in self.polygon) // n
            cy = sum(p[1] for p in self.polygon) // n
            self._centroid = (cx, cy)
        return self._centroid

    def contains_point(self, px: int, py: int) -> bool:
        n = len(self.polygon)
        inside = False
        j = n - 1
        for i in range(n):
            xi, yi = self.polygon[i]
            xj, yj = self.polygon[j]
            if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
                inside = not inside
            j = i
        return inside


class Region:
    def __init__(self, name: str, region_type: RegionType,
                 col: int, row: int, owner: str):
        self.name = name
        self.region_type = region_type
        self.col = col
        self.row = row
        self.owner = owner
        self.troops = 0

    @property
    def x(self):
        return self.col * CELL_SIZE + CELL_SIZE // 2

    @property
    def y(self):
        return self.row * CELL_SIZE + CELL_SIZE // 2


class General:
    def __init__(self, name: str, nation: str, province_idx: int,
                 troops: int = 1000):
        self.name = name
        self.nation = nation
        self.province_idx = province_idx
        self.troops = troops
        self.max_troops = 3000
        self.moved = False
        self.health = 100

    @property
    def x(self) -> int:
        return WORLD_PROVINCES[self.province_idx].centroid[0]

    @property
    def y(self) -> int:
        return WORLD_PROVINCES[self.province_idx].centroid[1]

    def distance_to(self, other: "General") -> float:
        return math.hypot(self.x - other.x, self.y - other.y)

    def distance_to_province(self, province: Province) -> float:
        return math.hypot(self.x - province.centroid[0],
                          self.y - province.centroid[1])


CELL_SIZE = 32
MAP_COLS = 50
MAP_ROWS = 30
SCREEN_WIDTH = 1600
SCREEN_HEIGHT = 1040

T_WATER = 0
T_LAND = 1
T_RIVER = 2
T_BRIDGE = 3

WORLD_MAP = []

NATION_ID = {"red": 1, "blue": 2, "green": 3}

COLOR_OCEAN = (40, 70, 120)
COLOR_OCEAN_LIGHT = (50, 85, 140)
COLOR_LAND = (160, 150, 120)
COLOR_RIVER = (50, 100, 170)
COLOR_BRIDGE = (200, 180, 60)
COLOR_NEUTRAL = (120, 115, 105)
COLOR_PROVINCE_BORDER = (80, 75, 65)

COLOR_NATION_RED = (170, 45, 40)
COLOR_NATION_RED_LIGHT = (190, 65, 60)
COLOR_NATION_BLUE = (50, 80, 160)
COLOR_NATION_BLUE_LIGHT = (70, 100, 180)
COLOR_NATION_GREEN = (50, 130, 70)
COLOR_NATION_GREEN_LIGHT = (70, 150, 90)

COLOR_HUD_BG = (40, 35, 30)
COLOR_HUD_TEXT = (220, 210, 190)
COLOR_HUD_TEXT_DIM = (160, 150, 130)
COLOR_WHITE = (255, 255, 255)
COLOR_BLACK = (0, 0, 0)

COLOR_GENERAL_SELECTED = (255, 255, 100)
COLOR_GENERAL_MOVABLE = (100, 255, 100)
COLOR_GENERAL_DONE = (150, 150, 150)

WORLD_NATIONS = {
    "red": Nation("Red Legion", COLOR_NATION_RED, COLOR_NATION_RED_LIGHT),
    "blue": Nation("Blue Alliance", COLOR_NATION_BLUE, COLOR_NATION_BLUE_LIGHT),
    "green": Nation("Green Dominion", COLOR_NATION_GREEN, COLOR_NATION_GREEN_LIGHT),
}

PLAYER_NATION = "blue"


def _perturb(p1, p2, jitter=12):
    mx = (p1[0] + p2[0]) // 2 + random.randint(-jitter, jitter)
    my = (p1[1] + p2[1]) // 2 + random.randint(-jitter, jitter)
    return (mx, my)


random.seed(42)

W0 = (0, 0)
W1 = (94, 8)
W2 = (188, 0)
W3 = (282, 10)
W4 = (376, 0)
W5 = (470, 5)
WM0 = (0, 480)
WM1 = (92, 488)
WM2 = (190, 475)
WM3 = (280, 492)
WM4 = (378, 478)
WM5 = (470, 485)
WB0 = (0, 960)
WB1 = (96, 955)
WB2 = (186, 960)
WB3 = (284, 958)
WB4 = (374, 960)
WB5 = (470, 958)

CW0 = (500, 0)
CW1 = (618, 6)
CW2 = (736, 0)
CW3 = (854, 8)
CW4 = (972, 0)
CW5 = (1090, 3)
CR1_0 = (500, 192)
CR1_1 = (620, 200)
CR1_2 = (732, 188)
CR1_3 = (856, 196)
CR1_4 = (968, 190)
CR1_5 = (1090, 194)
CR2_0 = (500, 384)
CR2_1 = (616, 378)
CR2_2 = (738, 390)
CR2_3 = (852, 382)
CR2_4 = (974, 386)
CR2_5 = (1090, 388)
CR3_0 = (500, 576)
CR3_1 = (622, 582)
CR3_2 = (734, 570)
CR3_3 = (858, 578)
CR3_4 = (970, 574)
CR3_5 = (1090, 576)
CR4_0 = (500, 768)
CR4_1 = (618, 762)
CR4_2 = (736, 776)
CR4_3 = (854, 768)
CR4_4 = (976, 772)
CR4_5 = (1090, 770)
CB0 = (500, 960)
CB1 = (620, 958)
CB2 = (734, 960)
CB3 = (856, 956)
CB4 = (972, 960)
CB5 = (1090, 958)

EW0 = (1120, 0)
EW1 = (1224, 7)
EW2 = (1328, 0)
EW3 = (1432, 5)
EW4 = (1536, 0)
EW5 = (1600, 2)
EM0 = (1120, 320)
EM1 = (1226, 328)
EM2 = (1330, 318)
EM3 = (1434, 326)
EM4 = (1538, 322)
EM5 = (1600, 320)
EB0 = (1120, 640)
EB1 = (1222, 636)
EB2 = (1328, 644)
EB3 = (1430, 638)
EB4 = (1536, 642)
EB5 = (1600, 640)
EE0 = (1120, 960)
EE1 = (1226, 956)
EE2 = (1326, 960)
EE3 = (1434, 958)
EE4 = (1534, 960)
EE5 = (1600, 958)

WORLD_PROVINCES = [
    Province("Frosthollow", "neutral", RegionType.VILLAGE,
             [W0, W1, WM1, WM0]),
    Province("Icewind", "neutral", RegionType.VILLAGE,
             [W1, W2, WM2, WM1]),
    Province("Snowmere", "neutral", RegionType.VILLAGE,
             [W2, W3, WM3, WM2]),
    Province("Greyvale", "neutral", RegionType.VILLAGE,
             [W3, W4, WM4, WM3]),
    Province("Stoneford", "neutral", RegionType.VILLAGE,
             [W4, W5, WM5, WM4]),
    Province("Dustkeep", "neutral", RegionType.VILLAGE,
             [WM0, WM1, WB1, WB0]),
    Province("Ashgate", "neutral", RegionType.VILLAGE,
             [WM1, WM2, WB2, WB1]),
    Province("Boneyard", "neutral", RegionType.VILLAGE,
             [WM2, WM3, WB3, WB2]),
    Province("Ironvale", "neutral", RegionType.VILLAGE,
             [WM3, WM4, WB4, WB3]),
    Province("Wolfden", "neutral", RegionType.VILLAGE,
             [WM4, WM5, WB5, WB4]),

    Province("Ironhold", "red", RegionType.CAPITAL,
             [CW0, CW1, CR1_1, CR1_0]),
    Province("Northwall", "red", RegionType.VILLAGE,
             [CW1, CW2, CR1_2, CR1_1]),
    Province("Warfield", "red", RegionType.CITY,
             [CW2, CW3, CR1_3, CR1_2]),
    Province("Bloodkeep", "red", RegionType.VILLAGE,
             [CW3, CW4, CR1_4, CR1_3]),
    Province("Windswept", "neutral", RegionType.VILLAGE,
             [CW4, CW5, CR1_5, CR1_4]),

    Province("Scarforge", "red", RegionType.VILLAGE,
             [CR1_0, CR1_1, CR2_1, CR2_0]),
    Province("Razorspine", "red", RegionType.CITY,
             [CR1_1, CR1_2, CR2_2, CR2_1]),
    Province("Embercrest", "red", RegionType.VILLAGE,
             [CR1_2, CR1_3, CR2_3, CR2_2]),
    Province("Crossroads", "neutral", RegionType.VILLAGE,
             [CR1_3, CR1_4, CR2_4, CR2_3]),
    Province("Midway", "neutral", RegionType.CITY,
             [CR1_4, CR1_5, CR2_5, CR2_4]),

    Province("Stonebar", "neutral", RegionType.VILLAGE,
             [CR2_0, CR2_1, CR3_1, CR3_0]),
    Province("Eastreach", "neutral", RegionType.VILLAGE,
             [CR2_1, CR2_2, CR3_2, CR3_1]),
    Province("Fords", "neutral", RegionType.VILLAGE,
             [CR2_2, CR2_3, CR3_3, CR3_2]),
    Province("Clearfield", "neutral", RegionType.CITY,
             [CR2_3, CR2_4, CR3_4, CR3_3]),
    Province("Dirtford", "neutral", RegionType.VILLAGE,
             [CR2_4, CR2_5, CR3_5, CR3_4]),

    Province("Barrowfield", "neutral", RegionType.VILLAGE,
             [CR3_0, CR3_1, CR4_1, CR4_0]),
    Province("Marshpoint", "blue", RegionType.VILLAGE,
             [CR3_1, CR3_2, CR4_2, CR4_1]),
    Province("Ravengate", "blue", RegionType.VILLAGE,
             [CR3_2, CR3_3, CR4_3, CR4_2]),
    Province("Oldgate", "blue", RegionType.CITY,
             [CR3_3, CR3_4, CR4_4, CR4_3]),
    Province("Westmere", "blue", RegionType.VILLAGE,
             [CR3_4, CR3_5, CR4_5, CR4_4]),

    Province("Dawnreach", "blue", RegionType.VILLAGE,
             [CR4_0, CR4_1, CB1, CB0]),
    Province("Starport", "blue", RegionType.VILLAGE,
             [CR4_1, CR4_2, CB2, CB1]),
    Province("Silverhold", "blue", RegionType.CAPITAL,
             [CR4_2, CR4_3, CB3, CB2]),
    Province("Dusthollow", "neutral", RegionType.VILLAGE,
             [CR4_3, CR4_4, CB4, CB3]),
    Province("Greywatch", "neutral", RegionType.VILLAGE,
             [CR4_4, CR4_5, CB5, CB4]),

    Province("Dawnmere", "neutral", RegionType.VILLAGE,
             [EW0, EW1, EM1, EM0]),
    Province("Highpeak", "neutral", RegionType.VILLAGE,
             [EW1, EW2, EM2, EM1]),
    Province("Windrift", "neutral", RegionType.VILLAGE,
             [EW2, EW3, EM3, EM2]),
    Province("Skyfall", "neutral", RegionType.VILLAGE,
             [EW3, EW4, EM4, EM3]),
    Province("Lightvale", "neutral", RegionType.VILLAGE,
             [EW4, EW5, EM5, EM4]),

    Province("Leafguard", "green", RegionType.VILLAGE,
             [EM0, EM1, EB1, EB0]),
    Province("Verdant", "green", RegionType.CITY,
             [EM1, EM2, EB2, EB1]),
    Province("Greenvale", "green", RegionType.CAPITAL,
             [EM2, EM3, EB3, EB2]),
    Province("Mosshollow", "green", RegionType.CITY,
             [EM3, EM4, EB4, EB3]),
    Province("Thornridge", "green", RegionType.VILLAGE,
             [EM4, EM5, EB5, EB4]),

    Province("Brightwood", "green", RegionType.VILLAGE,
             [EB0, EB1, EE1, EE0]),
    Province("Sunward", "green", RegionType.VILLAGE,
             [EB1, EB2, EE2, EE1]),
    Province("Goldkeep", "neutral", RegionType.VILLAGE,
             [EB2, EB3, EE3, EE2]),
    Province("Emberford", "neutral", RegionType.VILLAGE,
             [EB3, EB4, EE4, EE3]),
    Province("Starwatch", "neutral", RegionType.VILLAGE,
             [EB4, EB5, EE5, EE4]),
]

WORLD_REGIONS = [Region(p.name, p.region_type, 0, 0, p.owner)
                 for p in WORLD_PROVINCES]

PROVINCE_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),
    (5, 6), (6, 7), (7, 8), (8, 9),
    (0, 5), (1, 6), (2, 7), (3, 8), (4, 9),

    (10, 11), (11, 12), (12, 13), (13, 14),
    (15, 16), (16, 17), (17, 18), (18, 19),
    (20, 21), (21, 22), (22, 23), (23, 24),
    (25, 26), (26, 27), (27, 28), (28, 29),
    (30, 31), (31, 32), (32, 33), (33, 34),

    (10, 15), (15, 20), (20, 25), (25, 30),
    (11, 16), (16, 21), (21, 26), (26, 31),
    (12, 17), (17, 22), (22, 27), (27, 32),
    (13, 18), (18, 23), (23, 28), (28, 33),
    (14, 19), (19, 24), (24, 29), (29, 34),

    (35, 36), (36, 37), (37, 38), (38, 39),
    (40, 41), (41, 42), (42, 43), (43, 44),
    (45, 46), (46, 47), (47, 48), (48, 49),

    (35, 40), (40, 45),
    (36, 41), (41, 46),
    (37, 42), (42, 47),
    (38, 43), (43, 48),
    (39, 44), (44, 49),

    (4, 10), (7, 20), (9, 30),
    (14, 35), (24, 40), (34, 45),
]

BRIDGE_CONNECTIONS = [
    (4, 10), (7, 20), (9, 30),
    (14, 35), (24, 40), (34, 45),
]

RIVER_WEST_X = 485
RIVER_EAST_X = 1105

WORLD_GENERALS = [
    General("Volkov", "red", 10, 1200),
    General("Korzh", "red", 11, 800),
    General("Aldric", "blue", 32, 1100),
    General("Brenna", "blue", 31, 900),
    General("Theron", "green", 42, 1000),
    General("Lyra", "green", 41, 800),
]
