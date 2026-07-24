import pygame
import math
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
    def __init__(self, name: str, nation: str, col: int, row: int,
                 troops: int = 1000):
        self.name = name
        self.nation = nation
        self.col = col
        self.row = row
        self.troops = troops
        self.max_troops = 3000
        self.moved = False
        self.health = 100

    @property
    def x(self):
        return self.col * CELL_SIZE + CELL_SIZE // 2

    @property
    def y(self):
        return self.row * CELL_SIZE + CELL_SIZE // 2

    def distance_to(self, other: "General") -> float:
        return math.hypot(self.col - other.col, self.row - other.row)

    def distance_to_region(self, region: Region) -> float:
        return math.hypot(self.col - region.col, self.row - region.row)


CELL_SIZE = 32
MAP_COLS = 50
MAP_ROWS = 30
SCREEN_WIDTH = MAP_COLS * CELL_SIZE
SCREEN_HEIGHT = MAP_ROWS * CELL_SIZE + 80

T_WATER = 0
T_LAND = 1
T_RIVER = 2
T_BRIDGE = 3

WORLD_MAP = []

def _build_map():
    grid = [[T_WATER] * MAP_COLS for _ in range(MAP_ROWS)]

    for row in range(1, MAP_ROWS - 1):
        for col in range(1, 13):
            grid[row][col] = T_LAND
    for row in range(1, MAP_ROWS - 1):
        grid[row][13] = T_RIVER
    for row in range(1, MAP_ROWS - 1):
        for col in range(14, 38):
            grid[row][col] = T_LAND
    for row in range(1, MAP_ROWS - 1):
        grid[row][38] = T_RIVER
    for row in range(1, MAP_ROWS - 1):
        for col in range(39, MAP_COLS - 1):
            grid[row][col] = T_LAND

    bridges_west = [8, 15, 24]
    bridges_east = [10, 18, 25]
    for b in bridges_west:
        grid[b][13] = T_BRIDGE
    for b in bridges_east:
        grid[b][38] = T_BRIDGE

    return grid

WORLD_MAP = _build_map()

RIVER_WEST = [(13, r) for r in range(1, MAP_ROWS - 1)]
RIVER_EAST = [(38, r) for r in range(1, MAP_ROWS - 1)]
BRIDGES = [(13, 8), (13, 15), (13, 24), (38, 10), (38, 18), (38, 25)]

NATION_ID = {"red": 1, "blue": 2, "green": 3}

WORLD_REGIONS = [
    Region("Frosthollow", RegionType.VILLAGE, 3, 7, "neutral"),
    Region("Icewind", RegionType.VILLAGE, 7, 7, "neutral"),
    Region("Snowmere", RegionType.VILLAGE, 10, 7, "neutral"),
    Region("Greyvale", RegionType.VILLAGE, 5, 12, "neutral"),
    Region("Stoneford", RegionType.VILLAGE, 3, 22, "neutral"),
    Region("Dustkeep", RegionType.VILLAGE, 7, 22, "neutral"),
    Region("Ashgate", RegionType.VILLAGE, 10, 22, "neutral"),
    Region("Boneyard", RegionType.VILLAGE, 5, 17, "neutral"),

    Region("Ironhold", RegionType.CAPITAL, 20, 4, "red"),
    Region("Northwall", RegionType.VILLAGE, 24, 4, "red"),
    Region("Warfield", RegionType.VILLAGE, 28, 4, "red"),
    Region("Bloodkeep", RegionType.CITY, 20, 10, "red"),
    Region("Scarforge", RegionType.VILLAGE, 24, 10, "red"),
    Region("Razorspine", RegionType.VILLAGE, 28, 10, "red"),

    Region("Crossroads", RegionType.VILLAGE, 16, 14, "neutral"),
    Region("Midway", RegionType.CITY, 20, 14, "neutral"),
    Region("Stonebar", RegionType.VILLAGE, 24, 14, "neutral"),
    Region("Eastreach", RegionType.VILLAGE, 28, 14, "neutral"),
    Region("Windswept", RegionType.VILLAGE, 32, 14, "neutral"),
    Region("Fords", RegionType.VILLAGE, 16, 18, "neutral"),
    Region("Clearfield", RegionType.VILLAGE, 20, 18, "neutral"),
    Region("Dirtford", RegionType.VILLAGE, 24, 18, "neutral"),
    Region("Marshpoint", RegionType.VILLAGE, 28, 18, "neutral"),
    Region("Ravengate", RegionType.VILLAGE, 32, 18, "neutral"),
    Region("Barrowfield", RegionType.VILLAGE, 16, 21, "neutral"),
    Region("Oldgate", RegionType.VILLAGE, 20, 21, "neutral"),
    Region("Westmere", RegionType.VILLAGE, 24, 21, "neutral"),
    Region("Dusthollow", RegionType.VILLAGE, 28, 21, "neutral"),
    Region("Greywatch", RegionType.VILLAGE, 32, 21, "neutral"),

    Region("Silverhold", RegionType.CAPITAL, 20, 24, "blue"),
    Region("Dawnreach", RegionType.VILLAGE, 24, 24, "blue"),
    Region("Starport", RegionType.VILLAGE, 28, 24, "blue"),
    Region("Tidewall", RegionType.CITY, 20, 28, "blue"),
    Region("Mistwood", RegionType.VILLAGE, 24, 28, "blue"),
    Region("Frostgate", RegionType.VILLAGE, 28, 28, "blue"),

    Region("Verdant", RegionType.CAPITAL, 42, 10, "green"),
    Region("Leafguard", RegionType.VILLAGE, 44, 10, "green"),
    Region("Greenvale", RegionType.VILLAGE, 46, 10, "green"),
    Region("Mosshollow", RegionType.CITY, 42, 20, "green"),
    Region("Thornridge", RegionType.VILLAGE, 44, 20, "green"),
    Region("Brightwood", RegionType.VILLAGE, 46, 20, "green"),

    Region("Dawnmere", RegionType.VILLAGE, 42, 6, "neutral"),
    Region("Sunward", RegionType.VILLAGE, 44, 6, "neutral"),
    Region("Highpeak", RegionType.VILLAGE, 46, 6, "neutral"),
    Region("Windrift", RegionType.VILLAGE, 42, 14, "neutral"),
    Region("Skyfall", RegionType.VILLAGE, 44, 14, "neutral"),
    Region("Lightvale", RegionType.VILLAGE, 46, 14, "neutral"),
    Region("Goldkeep", RegionType.VILLAGE, 42, 25, "neutral"),
    Region("Emberford", RegionType.VILLAGE, 44, 25, "neutral"),
    Region("Starwatch", RegionType.VILLAGE, 46, 25, "neutral"),
    Region("Brightgate", RegionType.VILLAGE, 48, 15, "neutral"),
]

WORLD_GENERALS = [
    General("Volkov", "red", 20, 4, 1200),
    General("Korzh", "red", 24, 4, 800),
    General("Aldric", "blue", 20, 24, 1100),
    General("Brenna", "blue", 24, 24, 900),
    General("Theron", "green", 42, 10, 1000),
    General("Lyra", "green", 44, 10, 800),
]

PLAYER_NATION = "blue"

COLOR_OCEAN = (40, 70, 120)
COLOR_OCEAN_LIGHT = (50, 85, 140)
COLOR_LAND = (160, 150, 120)
COLOR_RIVER = (50, 100, 170)
COLOR_BRIDGE = (200, 180, 60)
COLOR_NEUTRAL = (120, 115, 105)

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

PROVINCE_CONNECTIONS = [
    (0, 1), (1, 2), (0, 3), (1, 3), (2, 3),
    (4, 5), (5, 6), (4, 7), (5, 7), (6, 7),
    (0, 4), (1, 5), (2, 6), (3, 7),

    (8, 9), (9, 10), (8, 11), (9, 12), (10, 13),
    (11, 12), (12, 13),

    (14, 15), (15, 16), (16, 17), (17, 18), (18, 19),
    (14, 17), (15, 18), (16, 19),
    (20, 21), (21, 22), (22, 23), (23, 24),
    (20, 23), (21, 24),

    (32, 33), (33, 34), (34, 35), (35, 36),
    (32, 35), (33, 36),

    (37, 38), (38, 39), (39, 40), (40, 41),
    (37, 40), (38, 41),

    (11, 14), (11, 20), (12, 15), (13, 16),
    (23, 32), (24, 33),

    (3, 8), (7, 11),
    (19, 26), (24, 31),

    (39, 42), (40, 43), (41, 44),
    (39, 46), (40, 47), (41, 48),
]
