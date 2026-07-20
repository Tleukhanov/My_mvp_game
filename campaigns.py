from typing import List, Tuple
from config import TerrainType, MAP_COLS, MAP_ROWS


def _make_empty(rows: int = MAP_ROWS, cols: int = MAP_COLS) -> List[List[TerrainType]]:
    return [[TerrainType.PLAIN for _ in range(cols)] for _ in range(rows)]


def _fill_rect(grid: List[List[TerrainType]], c1: int, r1: int, c2: int, r2: int, t: TerrainType):
    for r in range(r1, r2 + 1):
        for c in range(c1, c2 + 1):
            if 0 <= r < len(grid) and 0 <= c < len(grid[0]):
                grid[r][c] = t


class MissionConfig:
    def __init__(
        self,
        name: str,
        description: str,
        grid: List[List[TerrainType]],
        blue_units: List[Tuple[str, int, int]],
        red_units: List[Tuple[str, int, int]],
    ):
        self.name = name
        self.description = description
        self.grid = grid
        self.blue_units = blue_units
        self.red_units = red_units


def get_mission_1() -> MissionConfig:
    grid = _make_empty()
    cols = len(grid[0])
    rows = len(grid)

    river_cols = [18, 19, 20]
    for r in range(rows):
        for c in river_cols:
            grid[r][c] = TerrainType.RIVER

    bridges = [(19, 4), (19, 5), (19, 10), (19, 11), (19, 16), (19, 17)]
    for c, r in bridges:
        if 0 <= c < cols and 0 <= r < rows:
            grid[r][c] = TerrainType.BRIDGE

    _fill_rect(grid, 8, 0, 9, 3, TerrainType.MOUNTAIN)
    _fill_rect(grid, 28, 0, 30, 3, TerrainType.MOUNTAIN)
    _fill_rect(grid, 8, 18, 9, 21, TerrainType.MOUNTAIN)
    _fill_rect(grid, 28, 18, 30, 21, TerrainType.MOUNTAIN)

    _fill_rect(grid, 13, 6, 14, 8, TerrainType.MOUNTAIN)
    _fill_rect(grid, 23, 6, 24, 8, TerrainType.MOUNTAIN)
    _fill_rect(grid, 13, 13, 14, 15, TerrainType.MOUNTAIN)
    _fill_rect(grid, 23, 13, 24, 15, TerrainType.MOUNTAIN)

    sparse = [(5, 3), (6, 3), (33, 3), (34, 3),
              (5, 18), (6, 18), (33, 18), (34, 18)]
    for c, r in sparse:
        if 0 <= c < cols and 0 <= r < rows:
            grid[r][c] = TerrainType.MOUNTAIN

    return MissionConfig(
        name="Битва у моста",
        description="Удержите стратегический мост через реку",
        grid=grid,
        blue_units=[
            ("infantry", 3, 8), ("infantry", 4, 10),
            ("cavalry", 5, 12), ("archer", 2, 14),
            ("infantry", 6, 6),
        ],
        red_units=[
            ("infantry", 35, 8), ("infantry", 36, 10),
            ("cavalry", 34, 12), ("archer", 37, 14),
            ("infantry", 33, 6),
        ],
    )


def get_mission_2() -> MissionConfig:
    grid = _make_empty()
    cols = len(grid[0])
    rows = len(grid)

    for r in range(rows):
        for c in range(cols):
            if c < 14 + (r % 4) - 1 or c > 25 - (r % 4) + 1:
                grid[r][c] = TerrainType.MOUNTAIN

    _fill_rect(grid, 16, 3, 18, 5, TerrainType.PLAIN)
    _fill_rect(grid, 20, 7, 22, 9, TerrainType.PLAIN)
    _fill_rect(grid, 15, 11, 17, 13, TerrainType.PLAIN)
    _fill_rect(grid, 21, 15, 23, 17, TerrainType.PLAIN)
    _fill_rect(grid, 17, 19, 19, 20, TerrainType.PLAIN)

    small_rivers = [(18, 6), (19, 6), (20, 10), (21, 10), (18, 14), (19, 14)]
    for c, r in small_rivers:
        if 0 <= c < cols and 0 <= r < rows:
            grid[r][c] = TerrainType.RIVER

    bridges_r2 = [(19, 6), (21, 10), (19, 14)]
    for c, r in bridges_r2:
        if 0 <= c < cols and 0 <= r < rows:
            grid[r][c] = TerrainType.BRIDGE

    return MissionConfig(
        name="Ущелье смерти",
        description="Пройдите через узкое горное ущелье",
        grid=grid,
        blue_units=[
            ("infantry", 17, 18), ("infantry", 21, 19),
            ("cavalry", 19, 20), ("archer", 19, 17),
        ],
        red_units=[
            ("infantry", 19, 2), ("infantry", 20, 3),
            ("cavalry", 18, 1), ("archer", 21, 2),
        ],
    )


def get_mission_3() -> MissionConfig:
    grid = _make_empty()
    cols = len(grid[0])
    rows = len(grid)

    for r in range(rows):
        for c in range(cols):
            if 10 <= c <= 12:
                grid[r][c] = TerrainType.RIVER

    bridges_3 = [(11, 5), (11, 6), (11, 15), (11, 16)]
    for c, r in bridges_3:
        if 0 <= c < cols and 0 <= r < rows:
            grid[r][c] = TerrainType.BRIDGE

    _fill_rect(grid, 25, 5, 28, 9, TerrainType.MOUNTAIN)
    _fill_rect(grid, 25, 13, 28, 17, TerrainType.MOUNTAIN)
    _fill_rect(grid, 30, 7, 31, 8, TerrainType.MOUNTAIN)
    _fill_rect(grid, 30, 14, 31, 15, TerrainType.MOUNTAIN)

    fortress = [(29, 10), (29, 11), (29, 12),
                (30, 10), (30, 11), (30, 12),
                (31, 10), (31, 11), (31, 12)]
    for c, r in fortress:
        if 0 <= c < cols and 0 <= r < rows:
            grid[r][c] = TerrainType.MOUNTAIN

    grid[11][29] = TerrainType.BRIDGE
    grid[11][30] = TerrainType.PLAIN
    grid[11][31] = TerrainType.MOUNTAIN

    sparse_3 = [(5, 2), (6, 2), (7, 2),
                (5, 19), (6, 19), (7, 19),
                (15, 4), (16, 4), (17, 4),
                (15, 17), (16, 17), (17, 17)]
    for c, r in sparse_3:
        if 0 <= c < cols and 0 <= r < rows:
            grid[r][c] = TerrainType.MOUNTAIN

    return MissionConfig(
        name="Речная крепость",
        description="Штурмуйте вражескую крепость у реки",
        grid=grid,
        blue_units=[
            ("infantry", 3, 8), ("infantry", 4, 10),
            ("cavalry", 5, 12), ("archer", 2, 14),
            ("infantry", 3, 6), ("cavalry", 6, 11),
        ],
        red_units=[
            ("infantry", 33, 10), ("infantry", 33, 12),
            ("cavalry", 35, 11), ("archer", 36, 9),
            ("infantry", 32, 8), ("archer", 36, 14),
        ],
    )


MISSIONS = {
    1: get_mission_1,
    2: get_mission_2,
    3: get_mission_3,
}
