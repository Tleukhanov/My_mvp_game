import pygame
import sys
import math
from typing import Optional, List, Tuple, Set
from config import (
    SCREEN_WIDTH, SCREEN_HEIGHT, HUD_HEIGHT, CELL_SIZE,
    MAP_COLS, MAP_ROWS, FPS, Team, UnitType, CommandMode,
    COLOR_HUD_BG, COLOR_HUD_TEXT, COLOR_HUD_TEXT_DIM,
    COLOR_WHITE, COLOR_BLACK, COLOR_BLUE, COLOR_RED,
    FONT_NAME, FONT_SIZE_HUD, FONT_SIZE_TITLE,
    COLOR_MOVE_RANGE, COLOR_ATTACK_RANGE,
    COLOR_SELECT_RECT, COLOR_SELECT_RECT_BORDER,
    MAX_SELECTION, SELECT_CLICK_RADIUS,
    FOOD_MAX, FOOD_PER_UNIT_PER_SEC, FOOD_PER_VILLAGE_PER_SEC,
    RECRUIT_INTERVAL, TerrainType,
)
from map import TacticalMap
from units import Unit
from pathfinding import Pathfinder
from ai import AIController
from war import (
    BattleOutcome, WarSession,
    TROOPS_PER_TACTICAL_UNIT, clamp_quality, quality_bonuses,
)

UNIT_TYPE_MAP = {
    "infantry": UnitType.INFANTRY,
    "cavalry": UnitType.CAVALRY,
    "archer": UnitType.ARCHER,
}

FORMATION_SPACING = CELL_SIZE * 1.2

#: Первая строка и шаг строя для войск, пришедших из мира. Слева (синие) и
#: справа (красные) от центра, чтобы колонны не наезжали друг на друга.
SESSION_SPAWN_FIRST_ROW = 4
SESSION_SPAWN_ROW_STEP = 2
SESSION_SPAWN_COLS = 4
#: Насколько далеко от идеальной клетки искать свободную. Карты кампаний
#: местами засыпаны горами (миссия 2 — почти целиком), а на тренировочной
#: карте в углах стоят отдельные клочья гор, поэтому «поставить в строй по
#: сетке» нельзя: юнит на горе не сойдёт с места.
SESSION_SPAWN_SEARCH = 8

#: Геометрия карты для боя, выросшего из мировой карты (см.
#: ``_make_world_war_map``). Всё симметрично относительно вертикали: иначе
#: одна сторона получала бы и реку, и деревни.
_WAR_RIVER_COLS = (19, 20)
_WAR_BRIDGES = ((19, 4), (19, 5), (19, 12), (19, 13))
_WAR_VILLAGES = ((10, 6), (10, 15), (29, 6), (29, 15))
_WAR_MOUNTAINS = ((14, 0, 17, 3), (22, 0, 25, 3),
                  (14, 18, 17, 21), (22, 18, 25, 21))


def _make_world_war_map():
    """Собрать карту для боя, выросшего из мировой карты.

    Своя карта, а не тренировочная, потому что у ``TacticalMap()`` без сетки
    ДЕРЕВЕНЬ НЕТ ВООБЩЕ. А именно деревни в конце боя превращаются в добычу на
    мировой карте: ``PRESTIGE_PER_VILLAGE`` и ``villages_delta`` в
    ``war.outcome_to_world`` считаются от них. На тренировочной карте мост был бы
    наполовину холостым: золото за уцелевших капало бы, а престиж и деревни никогда.

    Четыре деревни, по две у каждого фланга и на равном расстоянии от центра:
    симметрия нужна, чтобы исход не решался тем, что «у синих деревни ближе».
    Горы стоят четырьмя клиньями в глубине карты — они не мешают строю войск
    по краям (колонки 2..5 и 34..37, строки 4..8).
    """
    grid = [[TerrainType.PLAIN for _ in range(MAP_COLS)]
            for _ in range(MAP_ROWS)]

    for row in range(MAP_ROWS):
        for col in _WAR_RIVER_COLS:
            grid[row][col] = TerrainType.RIVER
    for col, row in _WAR_BRIDGES:
        if 0 <= row < MAP_ROWS and 0 <= col < MAP_COLS:
            grid[row][col] = TerrainType.BRIDGE
    for c1, r1, c2, r2 in _WAR_MOUNTAINS:
        for row in range(r1, r2 + 1):
            for col in range(c1, c2 + 1):
                if 0 <= row < MAP_ROWS and 0 <= col < MAP_COLS:
                    grid[row][col] = TerrainType.MOUNTAIN
    for col, row in _WAR_VILLAGES:
        if 0 <= row < MAP_ROWS and 0 <= col < MAP_COLS:
            grid[row][col] = TerrainType.VILLAGE

    return grid, list(_WAR_VILLAGES)


class GameEngine:
    def __init__(self, mission: Optional[int] = None,
                 session: Optional[WarSession] = None):
        """Тактический бой.

        Два необязательных параметра задают, откуда взялись войска и куда
        уйдёт результат:

        * ``mission`` — номер миссии кампании (как раньше);
        * ``session`` — билет из ``war.py``, если бой вырос из мировой карты.

        Обратная совместимость ``run()`` сохранена полностью: он по-прежнему
        возвращает ``Optional[int]`` — номер следующей миссии. Исход боя по
        сессии лежит в отдельном атрибуте ``outcome`` и добирается методом
        ``build_outcome()``: смешивать «номер миссии» и «исход боя» в одном
        возвращаемом значении значило бы заставить ``main.py`` угадывать по
        типу, а два разных вопроса должны иметь два разных ответа.
        """
        pygame.init()
        self.mission = mission
        self.session = session
        # квитанция для мира; заполняется один раз в конце боя по сессии
        self.outcome: Optional[BattleOutcome] = None
        pygame.display.set_caption("Tactic Battle - Napoleonic Simulator")
        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        self.clock = pygame.time.Clock()
        self.running = True

        self._setup_map()
        self.pathfinder = Pathfinder(self.game_map)
        self.ai_controller = AIController(self.pathfinder)

        self.all_units: List[Unit] = []
        self.blue_units: List[Unit] = []
        self.red_units: List[Unit] = []
        self.selected_units: List[Unit] = []

        self._setup_units()

        # снимок стартового состава: по нему считаются потери для квитанции
        # (world -> тактика), и без него «сколько юнитов погибло» пришлось бы
        # угадывать по позициям на экране
        self._start_blue_count = len(self.blue_units)
        self._start_red_count = len(self.red_units)

        self.font_hud = pygame.font.SysFont(FONT_NAME, FONT_SIZE_HUD)
        self.font_title = pygame.font.SysFont(FONT_NAME, FONT_SIZE_TITLE, bold=True)

        self._show_orders = True
        self._game_over = False
        self._winner: Optional[str] = None

        self._drag_start: Optional[Tuple[int, int]] = None
        self._drag_end: Optional[Tuple[int, int]] = None
        self._dragging = False

        self._blue_food = FOOD_MAX
        self._red_food = FOOD_MAX
        self._recruit_timer = 0.0

        self._command_mode = CommandMode.ATTACK
        self._victory_next_mission: Optional[int] = None

    def _setup_map(self):
        if self.mission:
            from campaigns import MISSIONS
            mission_fn = MISSIONS.get(self.mission)
            if mission_fn:
                config = mission_fn()
                self.game_map = TacticalMap(config.grid, config.villages)
                self._mission_config = config
                return
        if self.session is not None:
            # бой из мира: своя симметричная карта с четырьмя деревнями,
            # иначе трофея за деревни взять было бы негде (см. _make_world_war_map)
            grid, villages = _make_world_war_map()
            self.game_map = TacticalMap(grid, villages)
            self._mission_config = None
            return
        self.game_map = TacticalMap()
        self._mission_config = None

    def _setup_units(self):
        if self._mission_config:
            self._setup_campaign_units()
        else:
            self._setup_skirmish_units()

        for unit in self.all_units:
            unit._pathfinder = self.pathfinder

        for unit in self.red_units:
            self.ai_controller.register_unit(unit)

    def _setup_campaign_units(self):
        for type_str, col, row in self._mission_config.blue_units:
            ut = UNIT_TYPE_MAP[type_str]
            x = col * CELL_SIZE + CELL_SIZE / 2
            y = row * CELL_SIZE + CELL_SIZE / 2
            self.blue_units.append(Unit(ut, Team.BLUE, x, y))

        for type_str, col, row in self._mission_config.red_units:
            ut = UNIT_TYPE_MAP[type_str]
            x = col * CELL_SIZE + CELL_SIZE / 2
            y = row * CELL_SIZE + CELL_SIZE / 2
            self.red_units.append(Unit(ut, Team.RED, x, y))

        self.all_units = self.blue_units + self.red_units

        # К миссии, выросшей из мира, добавляется левейс генерала. Именно
        # добавляется, а не заменяет: у миссии есть собственный сценарий с
        # заранее расставленными войсками, и стирать их было бы потерей
        # уровня, а не честным мостом.
        self._add_session_warriors()

    def _setup_skirmish_units(self):
        # Без сессии — демонстрационный набор, каким он и был.
        if self.session is None:
            blue_infantry = Unit(UnitType.INFANTRY, Team.BLUE, 3 * CELL_SIZE + CELL_SIZE / 2, 8 * CELL_SIZE + CELL_SIZE / 2)
            blue_infantry2 = Unit(UnitType.INFANTRY, Team.BLUE, 4 * CELL_SIZE + CELL_SIZE / 2, 10 * CELL_SIZE + CELL_SIZE / 2)
            blue_cavalry = Unit(UnitType.CAVALRY, Team.BLUE, 5 * CELL_SIZE + CELL_SIZE / 2, 12 * CELL_SIZE + CELL_SIZE / 2)
            blue_archer = Unit(UnitType.ARCHER, Team.BLUE, 2 * CELL_SIZE + CELL_SIZE / 2, 14 * CELL_SIZE + CELL_SIZE / 2)

            red_infantry = Unit(UnitType.INFANTRY, Team.RED, 36 * CELL_SIZE + CELL_SIZE / 2, 8 * CELL_SIZE + CELL_SIZE / 2)
            red_infantry2 = Unit(UnitType.INFANTRY, Team.RED, 37 * CELL_SIZE + CELL_SIZE / 2, 10 * CELL_SIZE + CELL_SIZE / 2)
            red_cavalry = Unit(UnitType.CAVALRY, Team.RED, 35 * CELL_SIZE + CELL_SIZE / 2, 12 * CELL_SIZE + CELL_SIZE / 2)
            red_archer = Unit(UnitType.ARCHER, Team.RED, 38 * CELL_SIZE + CELL_SIZE / 2, 14 * CELL_SIZE + CELL_SIZE / 2)

            self.blue_units = [blue_infantry, blue_infantry2, blue_cavalry, blue_archer]
            self.red_units = [red_infantry, red_infantry2, red_cavalry, red_archer]
            self.all_units = self.blue_units + self.red_units
            return

        # Сессия ЗАМЕЩАЕТ демонстрационный набор. Набор из четырёх юнитов ни на
        # что в мире не опирается: если оставить его рядом с левейсом генерала,
        # игрок получил бы четыре бесплатных отряда в каждом походе, и весь
        # смысл «золото и левейс -> войска» исчез бы. В бою по сессии на поле
        # выходят ровно те, за кого заплатили в мире, и ровно те, кто защищает
        # атакованную провинцию.
        self.blue_units = []
        self.red_units = []
        self.all_units = []
        self._add_session_warriors()

    # ---------------- войска из мира ----------------

    def _add_session_warriors(self):
        """Поставить на карту армии из ``session`` и защитника.

        Синим ставится левейс генерала: ``session.tactical_units`` юнитов
        (по ``TROOPS_PER_TACTICAL_UNIT`` солдат на юнит, не больше
        ``TACTICS_UNIT_CAP``). Качество сессии — это «выучка» одной и той же
        пехоты, поэтому тип юнита не меняется, а множатся здоровье и урон
        (см. ``war.quality_bonuses``).

        Красным ставится гарнизон атакованной провинции: у обороняющейся
        стороны своего левейса в мире нет, поэтому состав берётся из
        ``war.defender_units_for``.
        """
        if self.session is None:
            return

        hp_bonus, dmg_bonus = quality_bonuses(self.session.quality)

        blue_cells = self._spawn_cells(Team.BLUE, self.session.tactical_units)
        for i, cell in enumerate(blue_cells):
            unit = self._make_warrior(UnitType.INFANTRY, Team.BLUE, cell,
                                      hp_bonus, dmg_bonus)
            self.blue_units.append(unit)
            self.all_units.append(unit)

        red_cells = self._spawn_cells(Team.RED, self.session.defender_units)
        for cell in red_cells:
            unit = self._make_warrior(UnitType.INFANTRY, Team.RED, cell)
            self.red_units.append(unit)
            self.all_units.append(unit)

    def _make_warrior(self, unit_type: UnitType, team: Team, cell: Tuple[int, int],
                      hp_bonus: float = 1.0, dmg_bonus: float = 1.0) -> Unit:
        """Создать юнита с бонусами качества.

        ``Unit`` принимает только ``health``, а качество меняет ещё и
        ``max_health`` (иначе полоска здоровья и death-check поехали бы вниз
        относительно полоски) и ``damage``. Поэтому множители применяются
        здесь, а не в конструкторе: трогать ``units.py`` в этом этапе нельзя.
        """
        col, row = cell
        x = col * CELL_SIZE + CELL_SIZE / 2
        y = row * CELL_SIZE + CELL_SIZE / 2
        unit = Unit(unit_type, team, x, y)
        if hp_bonus != 1.0:
            unit.max_health = max(1, int(round(unit.max_health * hp_bonus)))
            unit.health = unit.max_health
        if dmg_bonus != 1.0:
            unit.damage = max(1, int(round(unit.damage * dmg_bonus)))
        return unit

    def _spawn_cells(self, team: Team, count: int) -> List[Tuple[int, int]]:
        """Клетки строя для ``count`` юнитов, с проверкой проходимости.

        Идеальные клетки — колонна у края карты (синие слева, красные
        справа). Если там гора или уже стоит чужой юнит, ищется ближайшая
        свободная клетка по расширяющимся кольцам: карты кампаний местами
        засыпаны горами, и юнит, поставленный на гору, просто застрянет.
        """
        count = max(0, int(count))
        base_col = 2 if team is Team.BLUE else MAP_COLS - 2 - SESSION_SPAWN_COLS
        cells: List[Tuple[int, int]] = []
        for i in range(count):
            col = base_col + (i % SESSION_SPAWN_COLS)
            row = SESSION_SPAWN_FIRST_ROW + (i // SESSION_SPAWN_COLS) * SESSION_SPAWN_ROW_STEP
            cells.append(self._free_cell_near(team, col, row))
        return cells

    def _free_cell_near(self, team: Team, col: int, row: int) -> Tuple[int, int]:
        """Ближайшая свободная клетка к ``(col, row)`` или сама ``(col, row)``.

        Кольца просматриваются по возрастанию радиуса, а внутри кольца клетки
        идут в фиксированном порядке: сначала та же колонка ниже цели, потом
        остальные. Порядок не «случайный», а задан сортировкой — иначе строй
        вставал бы вверх-влево от препятствия, и на тренировочной карте
        гарнизон уезжал бы в угол вместо того, чтобы стоять напротив своих.

        Отступать дальше, чем на ``SESSION_SPAWN_SEARCH`` клеток, незачем:
        это уже другая часть карты, и «поиск удобного места» превратился бы в
        телепорт армии к флангу.
        """
        if self._cell_is_free(team, col, row):
            return (col, row)
        for radius in range(1, SESSION_SPAWN_SEARCH + 1):
            ring = [(dcol, drow)
                    for dcol in range(-radius, radius + 1)
                    for drow in range(-radius, radius + 1)
                    if max(abs(dcol), abs(drow)) == radius]
            # ниже цели — раньше, в той же колонке — раньше остального
            ring.sort(key=lambda d: (-d[1], d[0]))
            for dcol, drow in ring:
                cand = (col + dcol, row + drow)
                if self._cell_is_free(team, cand[0], cand[1]):
                    return cand
        return (col, row)

    def _cell_is_free(self, team: Team, col: int, row: int) -> bool:
        """Клетка в границах карты, проходимая и не занятая ничьим войском.

        Проверяются ВСЕ юниты, а не только свои: в миссии сценарий уже расставил
        своих, и новый отряд, вставший поверх чужого, выглядел бы как ошибка
        позиционирования. Параметр ``team`` оставлен, чтобы вызов читался
        однозначно и его можно было сузить, если понадобится.
        """
        if not self.game_map.in_bounds(col, row):
            return False
        if not self.game_map.is_passable(col, row):
            return False
        px = col * CELL_SIZE + CELL_SIZE / 2
        py = row * CELL_SIZE + CELL_SIZE / 2
        for unit in self.all_units:
            if abs(unit.x - px) < 1 and abs(unit.y - py) < 1:
                return False
        return True

    def run(self):
        while self.running:
            dt = self.clock.tick(FPS) / 1000.0
            self._handle_events()
            if not self._game_over:
                self._update(dt)
            self._render()
        # НЕ вызываем pygame.quit() здесь: тактический экран открывается
        # СВЕРХ мировой карты, и после боя игрок возвращается в тот же
        # WorldMapScreen. Уничтожение видеорежима оставляло его `self.screen`
        # мёртвой поверхностью — возврат в глобалку падал или давал чёрный
        # экран. Ресурсы освобождает pygame при выходе из процесса, а
        # `main()` вызывает pygame.quit() последним действием.
        return self._victory_next_mission

    def _handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    if self.selected_units:
                        for u in self.selected_units:
                            u.selected = False
                        self.selected_units.clear()
                    else:
                        self.running = False
                elif event.key == pygame.K_SPACE:
                    self._toggle_orders()
                elif event.key == pygame.K_r:
                    self._restart()
                elif event.key == pygame.K_a:
                    self._select_all_blue()
                elif event.key == pygame.K_h:
                    self._command_mode = CommandMode.HOLD
                elif event.key == pygame.K_f:
                    self._command_mode = CommandMode.DEFEND
                elif event.key == pygame.K_g:
                    self._command_mode = CommandMode.ATTACK

            elif event.type == pygame.MOUSEBUTTONDOWN:
                mx, my = event.pos
                if my >= SCREEN_HEIGHT - HUD_HEIGHT:
                    continue

                if event.button == 1:
                    keys = pygame.key.get_pressed()
                    if keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT]:
                        self._shift_click_select(mx, my)
                    else:
                        self._drag_start = (mx, my)
                        self._dragging = False
                elif event.button == 3:
                    self._handle_right_click(mx, my)

            elif event.type == pygame.MOUSEBUTTONUP:
                mx, my = event.pos
                if event.button == 1:
                    if self._drag_start is not None:
                        dx = mx - self._drag_start[0]
                        dy = my - self._drag_start[1]
                        if abs(dx) > 5 or abs(dy) > 5:
                            self._box_select(self._drag_start[0], self._drag_start[1], mx, my)
                        else:
                            self._single_click_select(mx, my)
                        self._drag_start = None
                        self._dragging = False

            elif event.type == pygame.MOUSEMOTION:
                if self._drag_start is not None:
                    mx, my = event.pos
                    dx = mx - self._drag_start[0]
                    dy = my - self._drag_start[1]
                    if abs(dx) > 5 or abs(dy) > 5:
                        self._dragging = True
                        self._drag_end = (mx, my)

    def _single_click_select(self, mx: int, my: int):
        for u in self.selected_units:
            u.selected = False
        self.selected_units.clear()

        for unit in self.blue_units:
            if not unit.alive:
                continue
            if unit.distance_to_point(mx, my) < SELECT_CLICK_RADIUS:
                unit.selected = True
                self.selected_units.append(unit)
                return

    def _shift_click_select(self, mx: int, my: int):
        for unit in self.blue_units:
            if not unit.alive:
                continue
            if unit.distance_to_point(mx, my) < SELECT_CLICK_RADIUS:
                if unit in self.selected_units:
                    unit.selected = False
                    self.selected_units.remove(unit)
                elif len(self.selected_units) < MAX_SELECTION:
                    unit.selected = True
                    self.selected_units.append(unit)
                return

    def _box_select(self, x1: int, y1: int, x2: int, y2: int):
        for u in self.selected_units:
            u.selected = False
        self.selected_units.clear()

        left = min(x1, x2)
        right = max(x1, x2)
        top = min(y1, y2)
        bottom = max(y1, y2)

        for unit in self.blue_units:
            if not unit.alive:
                continue
            if left <= unit.x <= right and top <= unit.y <= bottom:
                if len(self.selected_units) < MAX_SELECTION:
                    unit.selected = True
                    self.selected_units.append(unit)

    def _select_all_blue(self):
        for u in self.selected_units:
            u.selected = False
        self.selected_units.clear()
        for unit in self.blue_units:
            if unit.alive and len(self.selected_units) < MAX_SELECTION:
                unit.selected = True
                self.selected_units.append(unit)

    def _handle_right_click(self, mx: int, my: int):
        if not self.selected_units:
            return

        target_unit = None
        for unit in self.red_units:
            if unit.alive and unit.distance_to_point(mx, my) < CELL_SIZE:
                target_unit = unit
                break

        if target_unit:
            self._issue_attack_order(target_unit)
        elif self.selected_units:
            self._issue_formation_move(mx, my)

    def _issue_attack_order(self, target: Unit):
        if self._command_mode == CommandMode.HOLD:
            for su in self.selected_units:
                if su.alive:
                    su.clear_orders()
                    su.set_attack_target(target)
            return

        if self._command_mode == CommandMode.DEFEND:
            for su in self.selected_units:
                if su.alive:
                    su.clear_orders()
                    su.set_attack_target(target)
            return

        for su in self.selected_units:
            if su.alive:
                su.clear_orders()
                su.set_attack_target(target)

    def _issue_formation_move(self, mx: int, my: int):
        n = len(self.selected_units)
        if n == 0:
            return

        if n == 1:
            su = self.selected_units[0]
            if su.alive:
                pixel_path = self.pathfinder.find_path_pixels(su.x, su.y, mx, my)
                if pixel_path:
                    su.clear_orders()
                    if self._command_mode == CommandMode.HOLD:
                        su.set_move_path(pixel_path)
                    elif self._command_mode == CommandMode.DEFEND:
                        su.set_move_path(pixel_path)
                    else:
                        su.set_move_path(pixel_path)
            return

        angle = 0
        cols = min(n, 3)
        for i, su in enumerate(self.selected_units):
            if not su.alive:
                continue
            row_idx = i // cols
            col_idx = i % cols
            offset_x = (col_idx - (cols - 1) / 2) * FORMATION_SPACING
            offset_y = row_idx * FORMATION_SPACING
            tx = mx + offset_x
            ty = my + offset_y

            pixel_path = self.pathfinder.find_path_pixels(su.x, su.y, tx, ty)
            if pixel_path:
                su.clear_orders()
                if self._command_mode == CommandMode.HOLD:
                    su.set_move_path(pixel_path)
                elif self._command_mode == CommandMode.DEFEND:
                    su.set_move_path(pixel_path)
                else:
                    su.set_move_path(pixel_path)

    def _toggle_orders(self):
        self._show_orders = not self._show_orders

    def _restart(self):
        self._game_over = False
        self._winner = None
        self.selected_units.clear()
        self.all_units.clear()
        self.blue_units.clear()
        self.red_units.clear()
        self._blue_food = FOOD_MAX
        self._red_food = FOOD_MAX
        self._recruit_timer = 0.0
        self._command_mode = CommandMode.ATTACK
        self._setup_map()
        self.pathfinder = Pathfinder(self.game_map)
        self.ai_controller = AIController(self.pathfinder)
        self._setup_units()
        # перезапуск возвращает бою исходный состав, поэтому и счётчики
        # потерь, и квитанция прежнего боя больше не годятся
        self._start_blue_count = len(self.blue_units)
        self._start_red_count = len(self.red_units)
        self.outcome = None

    def _update(self, dt: float):
        for unit in self.all_units:
            unit.update(dt, self.game_map, self.all_units)

        villages = self.game_map.get_all_villages()
        v_owners = self.game_map.village_owners

        self.ai_controller.update(
            dt,
            [u for u in self.blue_units if u.alive],
            villages, v_owners
        )
        self.ai_controller.remove_dead()

        self._update_villages(dt)
        self._update_food(dt)
        self._update_recruit(dt)
        self._check_game_over()

    def _update_villages(self, dt: float):
        for col, row in self.game_map.get_all_villages():
            owner = self.game_map.get_village_owner(col, row)
            tx = col * CELL_SIZE + CELL_SIZE / 2
            ty = row * CELL_SIZE + CELL_SIZE / 2
            controlling_unit = None
            for unit in self.all_units:
                if not unit.alive:
                    continue
                dist = math.hypot(unit.x - tx, unit.y - ty)
                if dist < CELL_SIZE * 1.2:
                    controlling_unit = unit
                    break
            if controlling_unit:
                new_owner = controlling_unit.team.value
                if owner != new_owner:
                    self.game_map.set_village_owner(col, row, new_owner)

    def _update_food(self, dt: float):
        blue_count = sum(1 for u in self.blue_units if u.alive)
        red_count = sum(1 for u in self.red_units if u.alive)
        self._blue_food -= blue_count * FOOD_PER_UNIT_PER_SEC * dt
        self._red_food -= red_count * FOOD_PER_UNIT_PER_SEC * dt

        for col, row in self.game_map.get_all_villages():
            owner = self.game_map.get_village_owner(col, row)
            if owner == "blue":
                self._blue_food += FOOD_PER_VILLAGE_PER_SEC * dt
            elif owner == "red":
                self._red_food += FOOD_PER_VILLAGE_PER_SEC * dt

        self._blue_food = max(0, min(FOOD_MAX, self._blue_food))
        self._red_food = max(0, min(FOOD_MAX, self._red_food))

    def _update_recruit(self, dt: float):
        # В бою по сессии авто-вербовки нет НИКАКОЙ. Левейс генерала уже
        # выведен из мира и учтён в WarSession, а вербовка за еду выдавала бы
        # бесплатные войска сверх него — то есть сессия ничего не решала бы, а
        # мир бесконечно печатал бы отряды из ниоткуда. Плюс к тому еда тут не
        # ограничивает: деревня даёт +20/с, а расход равен -5/юнит/с, поэтому
        # «попытка ограничить вербовку едой» в текущей экономике не работает.
        if self.session is not None:
            return

        self._recruit_timer += dt
        if self._recruit_timer >= RECRUIT_INTERVAL:
            self._recruit_timer -= RECRUIT_INTERVAL
            self._recruit_unit("blue")
            self._recruit_unit("red")

    def _recruit_unit(self, team_str: str,
                      unit_type: UnitType = UnitType.INFANTRY,
                      health: Optional[int] = None,
                      hp_bonus: float = 1.0,
                      dmg_bonus: float = 1.0) -> Optional[Unit]:
        """Вырастить юнита в своей деревне за еду.

        Раньше здесь стоял хардкод ``Unit(UnitType.INFANTRY, ..., health=500)``:
        ни тип, ни здоровье, ни урон настроить было нельзя, поэтому качество
        левейса из мира (см. ``war.QUALITY_BONUS``) физически некуда было
        применить. Теперь параметры открыты, а поведение по умолчанию ровно
        прежнее — вызов без аргументов даёт того же пехотинца с 500 HP.

        Возвращает созданного юнита или ``None``, если вербовать не из чего
        (нет еды или нет своей деревни).
        """
        food = self._blue_food if team_str == "blue" else self._red_food
        if food <= 0:
            return None

        team = Team.BLUE if team_str == "blue" else Team.RED
        units = self.blue_units if team_str == "blue" else self.red_units
        villages = [
            (c, r) for c, r in self.game_map.get_all_villages()
            if self.game_map.get_village_owner(c, r) == team_str
        ]
        if not villages:
            return None

        spawn_col, spawn_row = villages[0]
        sx = spawn_col * CELL_SIZE + CELL_SIZE / 2
        sy = spawn_row * CELL_SIZE + CELL_SIZE / 2

        offset_x = (len(units) % 3) * CELL_SIZE
        offset_y = (len(units) // 3) * CELL_SIZE
        sx += offset_x - CELL_SIZE
        sy += offset_y - CELL_SIZE

        new_unit = Unit(unit_type, team, sx, sy, health=health)
        if hp_bonus != 1.0 or dmg_bonus != 1.0:
            new_unit.max_health = max(1, int(round(new_unit.max_health * hp_bonus)))
            new_unit.health = min(new_unit.health, new_unit.max_health)
            if dmg_bonus != 1.0:
                new_unit.damage = max(1, int(round(new_unit.damage * dmg_bonus)))
        new_unit._pathfinder = self.pathfinder
        units.append(new_unit)
        self.all_units.append(new_unit)

        if team == Team.RED:
            self.ai_controller.register_unit(new_unit)
        return new_unit

    def _check_game_over(self):
        blue_alive = any(u.alive for u in self.blue_units)
        red_alive = any(u.alive for u in self.red_units)

        if not blue_alive and not red_alive:
            self._game_over = True
            self._winner = "DRAW"
        elif not red_alive:
            self._game_over = True
            self._winner = "BLUE WINS"
            if self.mission and self.mission < 4:
                self._victory_next_mission = self.mission + 1
        elif not blue_alive:
            self._game_over = True
            self._winner = "RED WINS"

        # Квитанция для мира собирается один раз — в тот кадр, когда стало
        # понятно, чем кончился бой. Идемпотентно: _check_game_over зовётся
        # каждый тик, а пересчитывать потери после конца партии незачем.
        if self._game_over and self.outcome is None:
            self.outcome = self.build_outcome()

        for su in list(self.selected_units):
            if not su.alive:
                su.selected = False
                self.selected_units.remove(su)

    # ---------------- квитанция для мира (war.py) ----------------

    def build_outcome(self, winner_nation: Optional[str] = None) -> Optional[BattleOutcome]:
        """Собрать :class:`war.BattleOutcome` для текущего состояния боя.

        ``None``, если бой не вырос из мировой карты (``session is None``):
        обычный тренировочный и миссионный бой никому ничего не должен.

        ``winner_nation`` переопределяет победителя. Нужен ровно для одного
        случая — игрок закрыл бой через ESC, не доиграв: тогда ``self._winner``
        пуст, и подставляется честное «никто не победил» (в мире это читается
        как отступление без награды, а потери считаются).

        Поля квитанции:

        * ``blue_surviving`` — сколько синих юнитов дожило;
        * ``blue_losses`` / ``red_losses`` — потери от СТАРТОВОГО состава;
        * ``captured_villages`` — число деревень под синим контролем к концу
          боя. Именно они становятся добычей в мире.
        """
        if self.session is None:
            return None

        if winner_nation is None:
            if self._winner == "BLUE WINS":
                winner_nation = "blue"
            elif self._winner == "RED WINS":
                winner_nation = "red"
            else:
                # DRAW или бой не доигран: награды нет, но потери считаются
                winner_nation = ""

        blue_surviving = sum(1 for u in self.blue_units if u.alive)
        red_surviving = sum(1 for u in self.red_units if u.alive)

        return BattleOutcome(
            match_id=int(self.session.match_id),
            winner_nation=str(winner_nation),
            blue_surviving=blue_surviving,
            blue_losses=max(0, self._start_blue_count - blue_surviving),
            red_losses=max(0, self._start_red_count - red_surviving),
            captured_villages=self._count_blue_villages(),
        )

    def _count_blue_villages(self) -> int:
        """Сколько деревней карты сейчас под синим контролем."""
        owners = self.game_map.village_owners
        return sum(1 for cell in self.game_map.get_all_villages()
                   if owners.get(cell) == "blue")

    def _render(self):
        self.game_map.render(self.screen)

        if self._show_orders and self.selected_units:
            self._render_move_indicators()

        if self._dragging and self._drag_start and self._drag_end:
            self._render_selection_rect()

        for unit in self.all_units:
            unit.render(self.screen)

        self._render_hud()

        # плашка «бой из мира» идёт последней, чтобы лежать поверх карты и HUD
        if self.session is not None:
            self._render_war_banner()

        if self._game_over:
            self._render_game_over()

        pygame.display.flip()

    def _render_selection_rect(self):
        x1, y1 = self._drag_start
        x2, y2 = self._drag_end
        rect = pygame.Rect(min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1))
        sel_surface = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        sel_surface.fill(COLOR_SELECT_RECT)
        pygame.draw.rect(sel_surface, COLOR_SELECT_RECT_BORDER, sel_surface.get_rect(), 2)
        self.screen.blit(sel_surface, rect.topleft)

    def _render_move_indicators(self):
        indicator_surface = pygame.Surface(
            (SCREEN_WIDTH, SCREEN_HEIGHT - HUD_HEIGHT), pygame.SRCALPHA
        )
        for unit in self.selected_units:
            if not unit.alive:
                continue
            range_r = int(unit.attack_range)
            if range_r > 0:
                pygame.draw.circle(
                    indicator_surface, COLOR_ATTACK_RANGE,
                    (int(unit.x), int(unit.y)), range_r, 2
                )
            move_range = int(unit.speed * CELL_SIZE * 10)
            pygame.draw.circle(
                indicator_surface, COLOR_MOVE_RANGE,
                (int(unit.x), int(unit.y)), move_range, 1
            )
        self.screen.blit(indicator_surface, (0, 0))

    def _render_war_banner(self):
        """Плашка «этот бой вырос из мира» поверх верхнего края карты.

        Игрок обязан видеть, ЧТО он привёл на эту карту: имя генерала, сколько
        левейса ушло в бой и какой выучки войска. Без этого отряд из девяти
        юнитов выглядит как обычная тренировка, а итог боя на карте мира
        оказывается неожиданным.

        Плашка рисуется НЕ в HUD: полоса снизу высотой 48 px уже занята
        пятью строками, и шестая наезжала бы на счётчик деревень. Сверху
        карты места нет, поэтому полоса с тёмной подложкой читается как
        заголовок миссии и ничего не перекрывает.
        """
        ws = self.session
        if ws is None:
            return
        text = (f"WORLD WAR #{ws.match_id}: {ws.general_name} "
                f"{ws.troops_committed} lev -> {ws.tactical_units} u "
                f"(q{clamp_quality(ws.quality)}, {TROOPS_PER_TACTICAL_UNIT}/u) "
                f"vs {ws.defender_units} garrison "
                f"[{ws.attacker_nation} vs {ws.defender_nation}]")
        banner = self.font_hud.render(text, True, COLOR_WHITE)
        bar = pygame.Surface((SCREEN_WIDTH, banner.get_height() + 4), pygame.SRCALPHA)
        bar.fill((0, 0, 0, 170))
        self.screen.blit(bar, (0, 0))
        self.screen.blit(banner, (SCREEN_WIDTH // 2 - banner.get_width() // 2, 2))

    def _render_hud(self):
        hud_y = SCREEN_HEIGHT - HUD_HEIGHT
        pygame.draw.rect(self.screen, COLOR_HUD_BG, (0, hud_y, SCREEN_WIDTH, HUD_HEIGHT))

        if self._mission_config:
            mission_text = self.font_hud.render(
                f"MISSION: {self._mission_config.name}", True, COLOR_HUD_TEXT
            )
            self.screen.blit(mission_text, (12, hud_y + 2))

        total_blue = sum(u.health for u in self.blue_units if u.alive)
        total_red = sum(u.health for u in self.red_units if u.alive)
        blue_alive = sum(1 for u in self.blue_units if u.alive)
        red_alive = sum(1 for u in self.red_units if u.alive)

        blue_text = self.font_hud.render(
            f"BLUE: {blue_alive} | HP:{total_blue} | Food:{int(self._blue_food)}", True, COLOR_BLUE
        )
        red_text = self.font_hud.render(
            f"RED: {red_alive} | HP:{total_red} | Food:{int(self._red_food)}", True, COLOR_RED
        )
        y_off = 20 if self._mission_config else 6
        self.screen.blit(blue_text, (12, hud_y + y_off))
        self.screen.blit(red_text, (SCREEN_WIDTH - red_text.get_width() - 12, hud_y + y_off))

        villages_info = []
        for col, row in self.game_map.get_all_villages():
            owner = self.game_map.get_village_owner(col, row)
            if owner:
                villages_info.append(owner)
        blue_v = villages_info.count("blue")
        red_v = villages_info.count("red")
        v_text = self.font_hud.render(
            f"Villages: B:{blue_v} R:{red_v}", True, COLOR_HUD_TEXT_DIM
        )
        self.screen.blit(v_text, (SCREEN_WIDTH // 2 - v_text.get_width() // 2, hud_y + 2))

        if self.selected_units:
            if len(self.selected_units) == 1:
                u = self.selected_units[0]
                info = (
                    f"SEL: {u.unit_type.value.upper()} | "
                    f"HP: {u.health}/{u.max_health} | "
                    f"DMG: {u.damage}"
                )
            else:
                types_count = {}
                for su in self.selected_units:
                    t = su.unit_type.value
                    types_count[t] = types_count.get(t, 0) + 1
                parts = [f"{v}x{k}" for k, v in types_count.items()]
                info = f"SELECTED: {len(self.selected_units)} units ({', '.join(parts)})"
            info_text = self.font_hud.render(info, True, COLOR_HUD_TEXT)
            self.screen.blit(info_text, (SCREEN_WIDTH // 2 - info_text.get_width() // 2, hud_y + 6))

        cmd_name = self._command_mode.name
        cmd_color = COLOR_ATTACK_RANGE if self._command_mode == CommandMode.ATTACK else (
            COLOR_MOVE_RANGE if self._command_mode == CommandMode.HOLD else (180, 180, 100)
        )
        cmd_text = self.font_hud.render(
            f"[{cmd_name}] G:Attack H:Hold F:Defend", True, cmd_color
        )
        self.screen.blit(cmd_text, (SCREEN_WIDTH - cmd_text.get_width() - 12, hud_y + 2))

        controls = self.font_hud.render(
            "LMB: Select | Shift+LMB: Multi | Drag: Box | RMB: Move/Attack | A: All | ESC: Quit",
            True, COLOR_HUD_TEXT_DIM,
        )
        self.screen.blit(controls, (SCREEN_WIDTH // 2 - controls.get_width() // 2, hud_y + 28))

    def _render_game_over(self):
        overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 120))
        self.screen.blit(overlay, (0, 0))

        if self._winner == "BLUE WINS":
            color = COLOR_BLUE
        elif self._winner == "RED WINS":
            color = COLOR_RED
        else:
            color = COLOR_WHITE

        title = self.font_title.render(self._winner, True, color)
        tx = SCREEN_WIDTH // 2 - title.get_width() // 2
        ty = SCREEN_HEIGHT // 2 - title.get_height() // 2 - 40
        self.screen.blit(title, (tx, ty))

        if self._winner == "BLUE WINS" and self.mission and self.mission < 4:
            next_text = self.font_hud.render(
                f"Press N for next mission (Mission {self.mission + 1}) | R: Restart | ESC: Menu",
                True, COLOR_WHITE
            )
        elif self._winner == "BLUE WINS" and self.mission == 4:
            next_text = self.font_hud.render(
                "CAMPAIGN COMPLETE! Press R: Restart | ESC: Menu",
                True, COLOR_WHITE
            )
        else:
            next_text = self.font_hud.render(
                "Press R to restart | ESC to quit",
                True, COLOR_WHITE
            )
        rx = SCREEN_WIDTH // 2 - next_text.get_width() // 2
        ry = ty + title.get_height() + 16
        self.screen.blit(next_text, (rx, ry))

        self._handle_game_over_keys()

    def _handle_game_over_keys(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_r:
                    self._restart()
                elif event.key == pygame.K_ESCAPE:
                    self.running = False
                elif event.key == pygame.K_n:
                    if self._winner == "BLUE WINS" and self._victory_next_mission:
                        self.running = False
