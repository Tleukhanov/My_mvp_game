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
    FORTRESS = auto()
    CAPITAL = auto()


class Nation:
    def __init__(self, name: str, color: Tuple[int, int, int],
                 light_color: Tuple[int, int, int]):
        self.name = name
        self.color = color
        self.light_color = light_color
        self.gold = 500
        self.army_size = 0


class Region:
    def __init__(self, name: str, region_type: RegionType,
                 col: int, row: int, owner: str):
        self.name = name
        self.region_type = region_type
        self.col = col
        self.row = row
        self.owner = owner
        self.troops = 0
        self.fortification = 0

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


COLOR_OCEAN = (40, 70, 120)
COLOR_OCEAN_LIGHT = (50, 85, 140)
COLOR_LAND = (160, 150, 120)
COLOR_LAND_DARK = (140, 130, 100)
COLOR_BORDER = (200, 190, 170)
COLOR_GRID = (150, 140, 115)

COLOR_NATION_1 = (50, 80, 160)
COLOR_NATION_1_LIGHT = (70, 100, 180)
COLOR_NATION_2 = (170, 45, 40)
COLOR_NATION_2_LIGHT = (190, 65, 60)
COLOR_NATION_3 = (50, 130, 70)
COLOR_NATION_3_LIGHT = (70, 150, 90)

COLOR_NEUTRAL_REGION = (160, 150, 120)
COLOR_FORTRESS = (180, 170, 150)
COLOR_CAPITAL = (220, 200, 160)

COLOR_GENERAL_SELECTED = (255, 255, 100)
COLOR_GENERAL_MOVABLE = (100, 255, 100)
COLOR_GENERAL_DONE = (150, 150, 150)

COLOR_HUD_BG = (40, 35, 30)
COLOR_HUD_TEXT = (220, 210, 190)
COLOR_HUD_TEXT_DIM = (160, 150, 130)
COLOR_WHITE = (255, 255, 255)
COLOR_BLACK = (0, 0, 0)

COLOR_MENU_BG = (30, 25, 20)
COLOR_MENU_TITLE = (220, 200, 160)
COLOR_MENU_BUTTON = (80, 70, 55)
COLOR_MENU_BUTTON_HOVER = (110, 95, 70)
COLOR_MENU_BUTTON_TEXT = (230, 220, 200)
COLOR_MENU_SUBTITLE = (170, 155, 130)


WORLD_NATIONS = {
    "nordheim": Nation("Nordheim", COLOR_NATION_1, COLOR_NATION_1_LIGHT),
    "valoria": Nation("Valoria", COLOR_NATION_2, COLOR_NATION_2_LIGHT),
    "drakoria": Nation("Drakoria", COLOR_NATION_3, COLOR_NATION_3_LIGHT),
}


WORLD_REGIONS = [
    Region("Frosthelm", RegionType.CAPITAL, 4, 2, "nordheim"),
    Region("Ironvale", RegionType.CITY, 6, 3, "nordheim"),
    Region("Snowmere", RegionType.VILLAGE, 3, 4, "nordheim"),
    Region("Wolfstead", RegionType.VILLAGE, 7, 1, "nordheim"),
    Region("Dawnport", RegionType.FORTRESS, 5, 5, "nordheim"),
    Region("Glacier Keep", RegionType.FORTRESS, 2, 3, "nordheim"),

    Region("Solis", RegionType.CAPITAL, 18, 11, "valoria"),
    Region("Ember Keep", RegionType.CITY, 16, 12, "valoria"),
    Region("Sandrift", RegionType.VILLAGE, 19, 13, "valoria"),
    Region("Firewatch", RegionType.VILLAGE, 20, 10, "valoria"),
    Region("Burning Gate", RegionType.FORTRESS, 17, 10, "valoria"),
    Region("Ashford", RegionType.FORTRESS, 15, 11, "valoria"),

    Region("Drakenholm", RegionType.CAPITAL, 11, 13, "drakoria"),
    Region("Greenmire", RegionType.CITY, 9, 12, "drakoria"),
    Region("Thornwall", RegionType.VILLAGE, 12, 14, "drakoria"),
    Region("Mosshaven", RegionType.VILLAGE, 10, 14, "drakoria"),
    Region("Dragon's Tooth", RegionType.FORTRESS, 8, 13, "drakoria"),
    Region("Bogward", RegionType.FORTRESS, 13, 12, "drakoria"),
]

WORLD_GENERALS = [
    General("Gustav", "nordheim", 5, 3, 1200),
    General("Bjorn", "nordheim", 4, 5, 800),
    General("Marcus", "valoria", 18, 12, 1100),
    General("Helena", "valoria", 17, 11, 900),
    General("Aldric", "drakoria", 11, 13, 1000),
    General("Brenna", "drakoria", 10, 13, 700),
]

PLAYER_NATION = "nordheim"
