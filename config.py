from enum import Enum, auto


class TerrainType(Enum):
    PLAIN = auto()
    MOUNTAIN = auto()
    RIVER = auto()
    BRIDGE = auto()
    VILLAGE = auto()


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
    CAPTURE = auto()
    GROUP_UP = auto()
    HOLD = auto()
    FLANK = auto()
    RETREAT = auto()


class CommandMode(Enum):
    #: обычная атака: клик по врагу — бить именно его, клик по земле — идти
    #: строем и врагов по дороге НЕ трогать (прежнее поведение по ``G``)
    ATTACK = auto()
    #: атака-марш: идти строем, но встретившегося по дороге врага бить, не
    #: отвлекаясь от точки назначения. Клавиша ``A``, как в Warcraft 3
    ATTACK_MOVE = auto()
    #: стой: дойти до точки и стоять, врагам не отвечать даже под курсором
    HOLD = auto()
    #: держать строй: дойти до точки и бить всё, что подошло, не отходя
    DEFEND = auto()


CELL_SIZE = 32
MAP_COLS = 40
MAP_ROWS = 22
HUD_HEIGHT = 64
SCREEN_WIDTH = MAP_COLS * CELL_SIZE
SCREEN_HEIGHT = MAP_ROWS * CELL_SIZE + HUD_HEIGHT
FPS = 60

#: Потолок выделения. В Warcraft 3 его нет вовсе, и здесь ставить шесть было
#: тем хуже, что в бою из мира на поле выходит до ``TACTICS_UNIT_CAP`` (9)
#: отрядов — то есть треть армии не помещалась в выделение. Двадцать четыре
#: перекрывают любой реальный состав с запасом, но всё же ограничивают: иначе
#: рамка по всей карте выделила бы полсотни юнитов, приказ пошёл бы от всех и
#: строй рассыпался бы в кашу из толпы на одной клетке.
MAX_SELECTION = 24

#: Сколько заказов может ждать в очереди у одного юнита. Очередь без предела
#: означала бы «кликнули пятнадцать раз подряд» — игрок не помнит, куда в итоге
#: пошла армия, а снять очередь можно только одним снятием всех приказов.
ORDER_QUEUE_LIMIT = 6

#: Два клика ближе этого расстояния и за этот срок считаются двойным кликом
#: (выделение всех однотипных юнитов, как в Warcraft 3).
DOUBLE_CLICK_SLOP = 6
DOUBLE_CLICK_MS = 350

#: Насколько далеко отряд в режиме атаки-марша готов отойти от назначенной
#: точки, прежде чем вернуться на маршрут. Без leash'а преследование уводило
#: бы атаку-марш через всю карту, и приказ «дойти и ударить по дороге» превращался
#: в «погнаться за первым встречным».
ATTACK_MOVE_LEASH = CELL_SIZE * 6

#: Радиус, который «держащий строй» юнит готов покинуть от назначенной точки.
#: Меньше, чем у атаки-марша: оборона по определению не должна превращаться в
#: погоню, иначе отряд, поставленный «держать деревню», ушёл бы за карту.
DEFEND_LEASH = CELL_SIZE * 2.5

FOOD_MAX = 1000
FOOD_PER_UNIT_PER_SEC = 5
FOOD_PER_VILLAGE_PER_SEC = 20
RECRUIT_INTERVAL = 180.0

SELECT_CLICK_RADIUS = CELL_SIZE * 0.9

COLOR_PARCHMENT = (90, 130, 60)
COLOR_PARCHMENT_DARK = (75, 115, 50)
COLOR_GRID_LINE = (70, 105, 45)
COLOR_GRASS_1 = (90, 130, 60)
COLOR_GRASS_2 = (82, 122, 55)
COLOR_GRASS_3 = (95, 135, 65)
COLOR_GRASS_DARK = (68, 100, 42)
COLOR_MOUNTAIN = (96, 88, 76)
COLOR_MOUNTAIN_PEAK = (126, 116, 100)
COLOR_RIVER = (55, 120, 180)
COLOR_RIVER_LIGHT = (80, 150, 210)
COLOR_RIVER_DARK = (40, 95, 150)
COLOR_RIVER_FLOW = (100, 170, 230)
COLOR_BRIDGE = (140, 110, 70)
COLOR_PLAIN = COLOR_PARCHMENT

COLOR_VILLAGE_NEUTRAL = (160, 140, 100)
COLOR_VILLAGE_BLUE = (70, 100, 170)
COLOR_VILLAGE_RED = (180, 65, 55)
COLOR_VILLAGE_ROOF = (120, 80, 50)
COLOR_VILLAGE_WINDOW = (200, 190, 140)

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
COLOR_SELECT_RECT = (100, 180, 255, 80)
COLOR_SELECT_RECT_BORDER = (100, 180, 255, 200)
COLOR_QUEUE_MARKER = (255, 214, 102, 230)

FONT_NAME = None
FONT_SIZE_HUD = 16
FONT_SIZE_UNIT = 12
FONT_SIZE_TITLE = 24

TERRAIN_MOVE_COST = {
    TerrainType.PLAIN: 1.0,
    TerrainType.MOUNTAIN: float("inf"),
    TerrainType.RIVER: 5.0,
    TerrainType.BRIDGE: 1.0,
    TerrainType.VILLAGE: 1.2,
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
