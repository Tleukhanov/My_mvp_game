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


CELL_SIZE = 48
MAP_COLS = 24
MAP_ROWS = 16
SCREEN_WIDTH = MAP_COLS * CELL_SIZE
SCREEN_HEIGHT = MAP_ROWS * CELL_SIZE + 80

T_WATER = 0
T_LAND = 1
T_RIVER = 2
T_BRIDGE = 3

WORLD_MAP = [
    [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
    [0,1,1,1,1,2,0,0,0,0,0,0,0,0,0,0,0,2,0,0,0,0,0,0],
    [0,1,1,1,1,2,0,0,0,0,1,1,1,1,1,0,0,2,0,0,0,0,0,0],
    [0,1,1,1,1,2,0,0,0,1,1,1,1,1,1,0,0,0,2,0,0,0,0,0],
    [0,1,1,1,1,3,0,0,1,1,1,1,1,1,0,0,0,0,3,0,0,0,0,0],
    [0,0,1,1,1,2,0,0,0,1,1,1,1,0,0,0,0,0,0,2,0,0,0,0],
    [0,0,0,0,0,0,2,0,0,1,1,1,1,1,1,0,0,0,0,2,0,0,0,0],
    [0,0,0,0,0,0,2,0,0,1,1,1,1,1,1,1,0,0,0,0,2,0,0,0],
    [0,0,0,0,0,0,0,3,1,1,1,1,1,1,1,0,0,0,0,0,2,0,0,0],
    [0,0,0,0,0,0,0,2,1,1,1,1,1,1,1,0,0,0,0,0,2,0,0,0],
    [0,0,0,0,0,0,0,0,2,0,0,0,0,0,0,0,1,1,1,1,1,2,0,0],
    [0,1,1,1,1,1,0,0,2,0,0,0,0,0,0,0,0,1,1,1,3,2,0,0],
    [0,1,1,1,1,0,0,0,2,0,0,0,0,0,0,0,0,0,1,1,0,2,0,0],
    [0,1,1,1,0,0,0,0,3,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
    [0,0,1,1,0,0,0,0,2,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
    [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
]

RIVER_WEST = [
    (5,1),(5,2),(5,3),(5,4),(5,5),
    (6,6),(6,7),
    (7,8),(7,9),
    (8,10),(8,11),(8,12),(8,13),(8,14),
]
RIVER_EAST = [
    (17,1),(17,2),
    (18,3),(18,4),
    (19,5),(19,6),
    (20,7),(20,8),(20,9),
    (21,10),(21,11),(21,12),
]

BRIDGES = [
    (5,4),
    (7,8),
    (8,13),
    (18,4),
    (20,11),
]

NATION_TERRITORY = [
    [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
    [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
    [0,0,0,0,0,0,0,0,0,0,1,1,1,1,1,0,0,0,0,0,0,0,0,0],
    [0,0,0,0,0,0,0,0,0,1,1,1,1,1,1,0,0,0,0,0,0,0,0,0],
    [0,0,0,0,0,0,0,0,1,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0],
    [0,0,0,0,0,0,0,0,0,1,1,1,1,0,0,0,0,0,0,0,0,0,0,0],
    [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
    [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
    [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
    [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
    [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,3,3,3,3,3,0,0],
    [0,2,2,2,2,2,0,0,0,0,0,0,0,0,0,0,0,0,3,3,3,3,0,0],
    [0,2,2,2,2,0,0,0,0,0,0,0,0,0,0,0,0,0,0,3,3,0,0,0],
    [0,2,2,2,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
    [0,0,2,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
    [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
]

NATION_ID = {"red": 1, "blue": 2, "green": 3}

WORLD_REGIONS = [
    Region("Ironhold", RegionType.CAPITAL, 11, 3, "red"),
    Region("Northwall", RegionType.VILLAGE, 10, 2, "red"),
    Region("Warfield", RegionType.VILLAGE, 12, 2, "red"),
    Region("Bloodkeep", RegionType.CITY, 10, 4, "red"),
    Region("Scarforge", RegionType.VILLAGE, 13, 4, "red"),

    Region("Silverhold", RegionType.CAPITAL, 3, 12, "blue"),
    Region("Dawnreach", RegionType.VILLAGE, 2, 11, "blue"),
    Region("Starport", RegionType.VILLAGE, 4, 11, "blue"),
    Region("Tidewall", RegionType.CITY, 2, 12, "blue"),
    Region("Mistwood", RegionType.VILLAGE, 3, 13, "blue"),
    Region("Frostgate", RegionType.VILLAGE, 4, 12, "blue"),

    Region("Verdant", RegionType.CAPITAL, 20, 10, "green"),
    Region("Leafguard", RegionType.VILLAGE, 17, 10, "green"),
    Region("Greenvale", RegionType.VILLAGE, 18, 10, "green"),
    Region("Mosshollow", RegionType.CITY, 19, 11, "green"),
    Region("Thornridge", RegionType.VILLAGE, 19, 12, "green"),

    Region("Westmere", RegionType.VILLAGE, 2, 3, "neutral"),
    Region("Ashford", RegionType.VILLAGE, 3, 5, "neutral"),
    Region("Greywatch", RegionType.VILLAGE, 4, 2, "neutral"),
    Region("Crossroads", RegionType.CITY, 3, 4, "neutral"),
    Region("Oldgate", RegionType.VILLAGE, 2, 5, "neutral"),
    Region("Ruinhold", RegionType.VILLAGE, 1, 3, "neutral"),
    Region("Dusthollow", RegionType.VILLAGE, 4, 3, "neutral"),
    Region("Barrowfield", RegionType.VILLAGE, 1, 4, "neutral"),

    Region("Midway", RegionType.CITY, 9, 7, "neutral"),
    Region("Fords", RegionType.VILLAGE, 8, 9, "neutral"),
    Region("Clearfield", RegionType.VILLAGE, 10, 6, "neutral"),
    Region("Stonebar", RegionType.VILLAGE, 12, 7, "neutral"),
    Region("Eastreach", RegionType.VILLAGE, 14, 8, "neutral"),
    Region("Marshpoint", RegionType.VILLAGE, 11, 9, "neutral"),
    Region("Dirtford", RegionType.VILLAGE, 13, 6, "neutral"),
    Region("Windswept", RegionType.VILLAGE, 15, 7, "neutral"),
]

WORLD_GENERALS = [
    General("Volkov", "red", 11, 3, 1200),
    General("Korzh", "red", 12, 4, 800),
    General("Aldric", "blue", 3, 12, 1100),
    General("Brenna", "blue", 2, 12, 900),
    General("Theron", "green", 20, 10, 1000),
    General("Lyra", "green", 19, 10, 800),
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
