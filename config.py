from enum import Enum, auto


class TerrainType(Enum):
    PLAIN = auto()
    MOUNTAIN = auto()
    RIVER = auto()
    BRIDGE = auto()


class UnitType(Enum):
    INFANTRY = "infantry"
    CAVALRY = "cavalry"
    ARCHER = "archer"


class Team(Enum):
    BLUE = "blue"
    RED = "red"


class AIState(Enum):
    IDLE = auto()
    MOVE = auto()
    ATTACK = auto()


CELL_SIZE = 32
MAP_COLS = 40
MAP_ROWS = 22
SCREEN_WIDTH = MAP_COLS * CELL_SIZE
SCREEN_HEIGHT = MAP_ROWS * CELL_SIZE + 48
HUD_HEIGHT = 48
FPS = 60

COLOR_PARCHMENT = (90, 130, 60)
COLOR_PARCHMENT_DARK = (75, 115, 50)
COLOR_GRID_LINE = (70, 105, 45)
COLOR_GRASS_1 = (90, 130, 60)
COLOR_GRASS_2 = (82, 122, 55)
COLOR_GRASS_3 = (95, 135, 65)
COLOR_GRASS_DARK = (68, 100, 42)
COLOR_MOUNTAIN = (130, 120, 110)
COLOR_MOUNTAIN_PEAK = (160, 155, 148)
COLOR_RIVER = (55, 120, 180)
COLOR_RIVER_LIGHT = (80, 150, 210)
COLOR_RIVER_DARK = (40, 95, 150)
COLOR_RIVER_FLOW = (100, 170, 230)
COLOR_BRIDGE = (140, 110, 70)
COLOR_PLAIN = COLOR_PARCHMENT

COLOR_BLUE = (50, 80, 160)
COLOR_BLUE_LIGHT = (80, 110, 190)
COLOR_BLUE_SELECTED = (100, 180, 255)
COLOR_RED = (170, 45, 40)
COLOR_RED_LIGHT = (200, 70, 65)
COLOR_RED_SELECTED = (255, 100, 90)

COLOR_HUD_BG = (50, 45, 40)
COLOR_HUD_TEXT = (220, 210, 190)
COLOR_HUD_TEXT_DIM = (160, 150, 130)
COLOR_HEALTH_BAR_BG = (60, 55, 50)
COLOR_HEALTH_BAR_GREEN = (80, 170, 80)
COLOR_HEALTH_BAR_YELLOW = (200, 180, 60)
COLOR_HEALTH_BAR_RED = (200, 60, 50)

COLOR_WHITE = (255, 255, 255)
COLOR_BLACK = (0, 0, 0)
COLOR_MOVE_RANGE = (100, 200, 100, 60)
COLOR_ATTACK_RANGE = (200, 80, 80, 40)

FONT_NAME = None
FONT_SIZE_HUD = 16
FONT_SIZE_UNIT = 12
FONT_SIZE_TITLE = 24

TERRAIN_MOVE_COST = {
    TerrainType.PLAIN: 1.0,
    TerrainType.MOUNTAIN: float("inf"),
    TerrainType.RIVER: 5.0,
    TerrainType.BRIDGE: 1.0,
}

TERRAIN_IMPASSABLE = {TerrainType.MOUNTAIN}

UNIT_STATS = {
    UnitType.INFANTRY: {
        "max_health": 500,
        "speed": 1.8,
        "damage": 8,
        "attack_range": CELL_SIZE * 1.2,
        "attack_speed": 0.8,
    },
    UnitType.CAVALRY: {
        "max_health": 350,
        "speed": 3.2,
        "damage": 14,
        "attack_range": CELL_SIZE * 1.4,
        "attack_speed": 0.6,
    },
    UnitType.ARCHER: {
        "max_health": 280,
        "speed": 1.5,
        "damage": 6,
        "attack_range": CELL_SIZE * 5.0,
        "attack_speed": 1.2,
    },
}

COMBAT_ADVANTAGE = {
    (UnitType.INFANTRY, UnitType.CAVALRY): 0.8,
    (UnitType.INFANTRY, UnitType.INFANTRY): 1.0,
    (UnitType.INFANTRY, UnitType.ARCHER): 1.1,
    (UnitType.CAVALRY, UnitType.INFANTRY): 1.2,
    (UnitType.CAVALRY, UnitType.CAVALRY): 1.0,
    (UnitType.CAVALRY, UnitType.ARCHER): 1.5,
    (UnitType.ARCHER, UnitType.INFANTRY): 0.9,
    (UnitType.ARCHER, UnitType.CAVALRY): 0.6,
    (UnitType.ARCHER, UnitType.ARCHER): 1.0,
}

SELECTED_BORDER_WIDTH = 3
UNIT_OUTLINE_WIDTH = 2

COLOR_MENU_BG = (30, 25, 20)
COLOR_MENU_TITLE = (220, 200, 160)
COLOR_MENU_BUTTON = (80, 70, 55)
COLOR_MENU_BUTTON_HOVER = (110, 95, 70)
COLOR_MENU_BUTTON_TEXT = (230, 220, 200)
COLOR_MENU_BUTTON_LOCKED = (60, 55, 45)
COLOR_MENU_BUTTON_LOCKED_TEXT = (130, 120, 100)
COLOR_MENU_SUBTITLE = (170, 155, 130)
