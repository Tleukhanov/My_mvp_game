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

COLOR_PARCHMENT = (222, 204, 170)
COLOR_PARCHMENT_DARK = (200, 180, 148)
COLOR_GRID_LINE = (180, 165, 135)
COLOR_MOUNTAIN = (120, 110, 100)
COLOR_MOUNTAIN_PEAK = (90, 80, 75)
COLOR_RIVER = (100, 145, 190)
COLOR_RIVER_DARK = (75, 120, 165)
COLOR_BRIDGE = (160, 130, 90)
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
