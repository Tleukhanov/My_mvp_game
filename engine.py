import pygame
import sys
import math
from typing import Optional, List, Tuple, Dict
from config import (
    SCREEN_WIDTH, SCREEN_HEIGHT, HUD_HEIGHT, CELL_SIZE,
    MAP_COLS, MAP_ROWS, FPS, Team, UnitType, CommandMode,
    COLOR_HUD_BG, COLOR_HUD_TEXT, COLOR_HUD_TEXT_DIM,
    COLOR_WHITE, COLOR_BLACK, COLOR_BLUE, COLOR_RED,
    FONT_NAME, FONT_SIZE_HUD, FONT_SIZE_TITLE,
    COLOR_MOVE_RANGE, COLOR_ATTACK_RANGE,
    COLOR_SELECT_RECT, COLOR_SELECT_RECT_BORDER, COLOR_QUEUE_MARKER,
    MAX_SELECTION, SELECT_CLICK_RADIUS,
    ORDER_QUEUE_LIMIT, DOUBLE_CLICK_SLOP, DOUBLE_CLICK_MS,
    ATTACK_MOVE_LEASH, DEFEND_LEASH,
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

#: Насколько далеко от клетки клика искать место для строя. Радиус нужен не для
#: «красивого» отступа, а для гор и рек: клик часто приходится на непроходимую
#: клетку, и строй должен встать рядом, а не отменяться.
FORMATION_RING_LIMIT = 6

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
#: Подпись текущего режима в HUD: имя и клавиши рядом с ним. Отдельная
#: таблица, а не условия в рендере, потому что подпись должна совпадать с тем,
#: что реально обрабатывает KEYDOWN, — иначе игрок читает одно, а играет другое.
_MODE_HINTS = {
    CommandMode.ATTACK_MOVE: "A:A-MOVE G:ATTACK F:DEFEND H:HOLD S:STOP",
    CommandMode.ATTACK: "G:ATTACK  A:A-MOVE F:DEFEND H:HOLD S:STOP",
    CommandMode.HOLD: "H:HOLD  A:A-MOVE G:ATTACK F:DEFEND S:STOP",
    CommandMode.DEFEND: "F:DEFEND  A:A-MOVE G:ATTACK H:HOLD S:STOP",
}

_MODE_COLORS = {
    CommandMode.ATTACK_MOVE: (230, 150, 90),
    CommandMode.ATTACK: COLOR_ATTACK_RANGE,
    CommandMode.HOLD: COLOR_MOVE_RANGE,
    CommandMode.DEFEND: (180, 180, 100),
}


def _mode_color(mode: CommandMode):
    return _MODE_COLORS[mode]


def _ring_offsets(radius: int) -> List[Tuple[int, int]]:
    """Смещения клеток кольца заданного радиуса в фиксированном порядке.

    Порядок не «случайный», а задан сортировкой: сначала та же колонка ниже
    цели, потом остальные. Он общий и для расстановки войск при старте боя, и
    для построения строя по правому клику — иначе строй вставал бы вверх-влево
    от препятствия, а гарнизон уезжал бы в угол вместо того, чтобы стоять
    напротив своих.
    """
    ring = [(dcol, drow)
            for dcol in range(-radius, radius + 1)
            for drow in range(-radius, radius + 1)
            if max(abs(dcol), abs(drow)) == radius]
    ring.sort(key=lambda d: (-d[1], d[0]))
    return ring


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
        self._last_click_time = 0
        self._last_click_pos: Optional[Tuple[int, int]] = None

        # Отряды игрока: Ctrl+цифра кладёт сюда ссылки на юнитов, цифра — возвращает
        # выделение. Ссылки, а не номера: состав боя меняется (кто-то погиб, кто-то
        # завербован), и отряд «2» иначе молча превратился бы в чужой.
        self._control_groups: Dict[int, List[Unit]] = {}
        # Очередь приказов на юнита: id(unit) -> список ещё не начатых приказов.
        # Живёт в движке, а не в юните: приказ — понятие боя, а юниту о нём
        # знать незачем (в units.py добавлено только read-only ``is_moving``).
        self._order_queue: Dict[int, List[dict]] = {}
        #: Текущий (не исполненный) приказ юнита: id(unit) -> приказ.
        self._current_order: Dict[int, dict] = {}
        #: Посты обороны: id(unit) -> точка, которую юнит обязан держать.
        self._defend_posts: Dict[int, Tuple[int, int]] = {}
        self._message = ""
        self._message_timer = 0.0

        self._blue_food = FOOD_MAX
        self._red_food = FOOD_MAX
        self._recruit_timer = 0.0

        # По умолчанию — атака-марш, как в Warcraft 3: правый клик по земле в
        # бою почти всегда означает «идти и бить по дороге», а не «идти мимо».
        self._command_mode = CommandMode.ATTACK_MOVE
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

        # На поле выходят РАВНЫЕ отряды (battle_units = min(сторон)), а перевес
        # выражается прочностью каждого отряда. Иначе армия в 1200 против
        # 300 выставляла 9 отрядов против трёх: меньшая армия выглядела
        # разобранной, хотя на самом деле её просто срезал потолок.
        # Разница остаётся читаемой через полоски здоровья и числа в HUD.
        n = self.session.battle_units
        def_troops = self.session.defender_troops
        if def_troops is None:
            def_troops = self.session.defender_units * TROOPS_PER_TACTICAL_UNIT

        blue_scale = self._troops_per_unit_scale(self.session.troops_committed, n)
        red_scale = self._troops_per_unit_scale(def_troops, n)

        blue_cells = self._spawn_cells(Team.BLUE, n)
        for cell in blue_cells:
            unit = self._make_warrior(UnitType.INFANTRY, Team.BLUE, cell,
                                      hp_bonus * blue_scale, dmg_bonus)
            self.blue_units.append(unit)
            self.all_units.append(unit)

        red_cells = self._spawn_cells(Team.RED, n)
        for cell in red_cells:
            unit = self._make_warrior(UnitType.INFANTRY, Team.RED, cell,
                                      hp_bonus * red_scale, dmg_bonus)
            self.red_units.append(unit)
            self.all_units.append(unit)

    @staticmethod
    def _troops_per_unit_scale(troops: object, units: int) -> float:
        """Во сколько раз крепче должен быть отряд из-за числа солдат.

        Один отряд = ``TROOPS_PER_TACTICAL_UNIT`` солдат. Если сторона
        выставила 3000 солдат девятью отрядами, за каждым стоит 333
        солдата, и отряд должен быть втрое живучее эталонного, а не
        равным. При штатном левейсе множитель равен 1.0 и ничего не меняет.
        """
        try:
            raw = max(0, int(troops))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 1.0
        n = max(1, int(units))
        return max(1.0, (raw / n) / float(TROOPS_PER_TACTICAL_UNIT))

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
            for dcol, drow in _ring_offsets(radius):
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
                keys = pygame.key.get_pressed()
                ctrl = keys[pygame.K_LCTRL] or keys[pygame.K_RCTRL]
                if event.key == pygame.K_ESCAPE:
                    if self.selected_units:
                        self._clear_selection()
                    else:
                        self.running = False
                elif event.key == pygame.K_SPACE:
                    self._toggle_orders()
                elif event.key == pygame.K_r:
                    self._restart()
                elif event.key == pygame.K_a:
                    # A — атака-марш, как в Warcraft 3. «Выделить всех» сюда же
                    # раньше было только потому, что команд не было вовсе; теперь
                    # это Ctrl+A, как в самой WC3 и в Total War.
                    if ctrl:
                        self._select_all_blue()
                    else:
                        self._command_mode = CommandMode.ATTACK_MOVE
                elif event.key == pygame.K_s:
                    self._stop_selection()
                elif event.key == pygame.K_h:
                    self._command_mode = CommandMode.HOLD
                elif event.key == pygame.K_f:
                    self._command_mode = CommandMode.DEFEND
                elif event.key == pygame.K_g:
                    self._command_mode = CommandMode.ATTACK
                elif pygame.K_0 <= event.key <= pygame.K_9:
                    slot = event.key - pygame.K_0
                    if slot == 0:
                        # Ctrl+0 — забыть отряды (как на мировой карте). Без
                        # Ctrl цифра 0 ничего не значит: ноль в WC3 отрядом не
                        # является, и занимать его «сбросом выделения» значило бы
                        # отдавать клавишу двум разным смыслам.
                        if ctrl:
                            self._control_groups.clear()
                            self._show_msg("Отряды забыты")
                    elif ctrl:
                        self._store_control_group(slot)
                    else:
                        self._recall_control_group(slot)

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
                    keys = pygame.key.get_pressed()
                    queue = keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT]
                    self._handle_right_click(mx, my, queue=queue)

            elif event.type == pygame.MOUSEBUTTONUP:
                mx, my = event.pos
                if event.button == 1:
                    if self._drag_start is not None:
                        dx = mx - self._drag_start[0]
                        dy = my - self._drag_start[1]
                        if abs(dx) > 5 or abs(dy) > 5:
                            self._box_select(self._drag_start[0], self._drag_start[1], mx, my)
                        else:
                            self._click_select(mx, my)
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

    def _click_select(self, mx: int, my: int):
        """Левый клик без рамки: одиночный или двойной.

        Двойной клик — «выбрать все такие же», как в WC3. Он ловится здесь, а не
        в ``MOUSEBUTTONDOWN``: два нажатия подряд различаются только временем и
        позицией, и держать это состояние приходится до отпускания кнопки.
        """
        now = pygame.time.get_ticks()
        last_t, last_p = self._last_click_time, self._last_click_pos
        self._last_click_time = now
        self._last_click_pos = (mx, my)
        is_double = (
            last_p is not None
            and (now - last_t) <= DOUBLE_CLICK_MS
            and math.hypot(mx - last_p[0], my - last_p[1]) <= DOUBLE_CLICK_SLOP
        )
        if is_double:
            self._double_click_select(mx, my)
        else:
            self._single_click_select(mx, my)

    def _double_click_select(self, mx: int, my: int):
        """Выделить все живые юниты того же типа, что и тот, под которым кликнули.

        Клик по пустому месту снимает выделение — иначе «выделить всех пехотинцев»
        было бы невозможно отменить одним и тем же жестом.
        """
        unit = self._blue_unit_at(mx, my)
        if unit is None:
            self._clear_selection()
            return
        same = [u for u in self.blue_units
                if u.alive and u.unit_type is unit.unit_type]
        self._set_selection(same[:MAX_SELECTION])

    def _blue_unit_at(self, mx: int, my: int) -> Optional[Unit]:
        """Ближайший свой живой юнит под курсором или ``None``."""
        best: Optional[Unit] = None
        best_d = SELECT_CLICK_RADIUS
        for unit in self.blue_units:
            if not unit.alive:
                continue
            d = unit.distance_to_point(mx, my)
            if d < best_d:
                best, best_d = unit, d
        return best

    def _clear_selection(self):
        for u in self.selected_units:
            u.selected = False
        self.selected_units.clear()

    def _set_selection(self, units: List[Unit]):
        self._clear_selection()
        for unit in units:
            if len(self.selected_units) >= MAX_SELECTION:
                break
            unit.selected = True
            self.selected_units.append(unit)

    def _single_click_select(self, mx: int, my: int):
        self._clear_selection()
        unit = self._blue_unit_at(mx, my)
        if unit is not None:
            unit.selected = True
            self.selected_units.append(unit)

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
        self._clear_selection()

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
        """Ctrl+A: вся армия на поле.

        Старый ``A`` делал ровно это, но одной клавишей нельзя и выделить всех, и
        отдать атаку-марш: в WC3 это разные клавиши, и так сделано здесь.
        """
        self._set_selection([u for u in self.blue_units if u.alive])

    # ---------------- отряды (Ctrl+1..9 / 1..9) ----------------

    def _store_control_group(self, slot: int):
        """Ctrl + цифра: запомнить выделение под номером."""
        if not self.selected_units:
            self._show_msg("Отряд не задан: ничего не выбрано")
            return
        self._control_groups[slot] = list(self.selected_units)
        self._show_msg(f"Отряд {slot}: {len(self.selected_units)}")

    def _recall_control_group(self, slot: int) -> bool:
        """Цифра: вернуть выделение отряда.

        Погибших из отряда молча выбрасываем: иначе пришлось бы вручную
        пересобирать отряд после каждой потери, а «отряд 3 из трёх человек»
        после смерти одного — это нормальная ситуация боя, не ошибка игрока.
        Если не осталось никого — сообщаем прямо и слот освобождаем, иначе
        нажатие цифры молча ничего не делало бы.
        """
        group = self._control_groups.get(slot)
        if not group:
            self._show_msg(f"Отряд {slot} пуст")
            return False
        alive = [u for u in group if u.alive]
        if not alive:
            self._control_groups.pop(slot, None)
            self._show_msg(f"Отряд {slot}: все погибли")
            return False
        self._set_selection(alive)
        lost = len(group) - len(alive)
        suffix = f" (погибло {lost})" if lost else ""
        self._show_msg(f"Отряд {slot}: {len(alive)}{suffix}")
        return True

    def _show_msg(self, msg: str):
        self._message = msg
        self._message_timer = 2.5

    # ---------------- приказы ----------------

    def _stop_selection(self):
        """S: снять все приказы и очередь выделенной группы.

        Очередь снимается вместе с текущим приказом намеренно: в WC3 «Stop»
        тоже обнуляет всю очередь, и оставить заранее назначенные точки было бы
        способом отменить стоп через две секунды, ничего не понимая.
        """
        if not self.selected_units:
            for unit in self.blue_units:
                unit.clear_orders()
            self._order_queue.clear()
            self._current_order.clear()
            self._defend_posts.clear()
            self._show_msg("Все приказы сняты")
            return
        stopped = 0
        for su in self.selected_units:
            if not su.alive:
                continue
            queued = len(self._order_queue.get(id(su), ()))
            su.clear_orders()
            self._order_queue.pop(id(su), None)
            self._current_order.pop(id(su), None)
            self._defend_posts.pop(id(su), None)
            stopped += 1 + queued
        self._show_msg(f"Стоп: снято приказов — {stopped}")

    def _handle_right_click(self, mx: int, my: int, queue: bool = False):
        """Правый клик: приказ всей группе.

        ``queue`` — это Shift: приказ не отменяет текущий, а встаёт в конец
        очереди юнита.
        """
        units = [u for u in self.selected_units if u.alive]
        if not units:
            return

        target_unit = None
        best_d = CELL_SIZE
        for unit in self.red_units:
            if not unit.alive:
                continue
            d = unit.distance_to_point(mx, my)
            if d < best_d:
                target_unit, best_d = unit, d

        if target_unit is not None and self._command_mode != CommandMode.HOLD:
            # Клик по врагу в любом режиме, кроме «стоять», — это атака именно
            # его. В том числе в атаки-марше: точка отступления здесь не нужна,
            # враг и есть цель.
            for su in units:
                self._push_order(su, {"kind": "attack", "target": target_unit,
                                      "point": None}, queue)
            return

        kind = {
            CommandMode.ATTACK: "move",
            CommandMode.ATTACK_MOVE: "attack_move",
            CommandMode.HOLD: "hold",
            CommandMode.DEFEND: "defend",
        }[self._command_mode]

        points = [self.game_map.grid_to_pixel_center(*cell)
                 for cell in self._formation_cells(mx, my, len(units))]
        issued = 0
        for su, (tx, ty) in zip(units, points):
            if self._push_order(su, {"kind": kind, "target": None,
                                     "point": (tx, ty)}, queue):
                issued += 1
        if not issued:
            self._show_msg("Приказ не выполнен: пути нет")

    def _formation_cells(self, mx: int, my: int, count: int) -> List[Tuple[int, int]]:
        """Развести ``count`` юнитов по РАЗНЫМ клеткам вокруг точки клика.

        Раньше строй считался в пикселях со смещением на ``FORMATION_SPACING``,
        и две проблемы вылезали сразу: клетки уезжали за край карты (клик у
        правой кромки давал цели в off-grid пикселях, путь не находился) и
        раскладывались только сеткой 3 в ряд, то есть девять юнитов выстраивались
        тремя полосами далеко за точкой клика. Теперь клетки настоящие: берём
        клик, а если он непроходим — ближайшую проходимую, и кладём строй
        расширяющимися кольцами.
        """
        base = (int(mx) // CELL_SIZE, int(my) // CELL_SIZE)
        if not (self.game_map.in_bounds(*base) and self.game_map.is_passable(*base)):
            base = self._nearest_passable(*base)

        cells: List[Tuple[int, int]] = [base]
        taken = {base}
        # первым идёт сам клик, кольца — только добирать недостающие клетки
        for radius in range(1, FORMATION_RING_LIMIT + 1):
            for dcol, drow in _ring_offsets(radius):
                cand = (base[0] + dcol, base[1] + drow)
                if cand in taken:
                    continue
                if not self.game_map.in_bounds(*cand):
                    continue
                if not self.game_map.is_passable(*cand):
                    continue
                taken.add(cand)
                cells.append(cand)
                if len(cells) >= count:
                    return cells
        # кольца кончились (например, клик у стены из гор): отдаём что есть,
        # лишние юниты получат точку клика и встанут впритык
        while len(cells) < count:
            cells.append(cells[-1] if cells else base)
        return cells

    def _nearest_passable(self, col: int, row: int) -> Tuple[int, int]:
        """Ближайшая проходимая клетка к ``(col, row)`` в границах карты."""
        for radius in range(1, FORMATION_RING_LIMIT + 1):
            for dcol, drow in _ring_offsets(radius):
                cand = (col + dcol, row + drow)
                if (self.game_map.in_bounds(*cand)
                        and self.game_map.is_passable(*cand)):
                    return cand
        return (col, row)

    def _push_order(self, unit: Unit, order: dict, queue: bool) -> bool:
        """Отдать приказ юниту: в очередь или немедленно.

        ``False`` — приказ не выполнен (нет пути). Очередь при этом тоже
        остаётся нетронутой: сломанный Shift-приказ не должен стирать то, что
        юнит уже обещал сделать.
        """
        if queue:
            pending = self._order_queue.setdefault(id(unit), [])
            if len(pending) >= ORDER_QUEUE_LIMIT:
                self._show_msg(f"Очередь переполнена ({ORDER_QUEUE_LIMIT})")
                return False
            pending.append(order)
            if not self._current_order.get(id(unit)):
                return self._start_order(unit, pending.pop(0))
            return True

        self._order_queue.pop(id(unit), None)
        return self._start_order(unit, order)

    def _start_order(self, unit: Unit, order: dict) -> bool:
        """Начать приказ: снять прежние и поставить новый.

        Все режимы, кроме атаки, в итоге дают юниту маршрут; различаются они
        тем, что движок делает сверх маршрута — бьёт ли по дороге и куда имеет
        право отойти (см. ``_service_order``).
        """
        if not unit.alive:
            return False
        unit.clear_orders()
        # пост обороны снимается ЛЮБЫМ новым приказом: оставить его значило бы
        # отправить юнита на новую точку и тут же вернуть на старую
        self._defend_posts.pop(id(unit), None)
        self._current_order[id(unit)] = dict(order)

        if order["kind"] == "attack":
            if order["target"] is None or not order["target"].alive:
                self._current_order.pop(id(unit), None)
                return False
            unit.set_attack_target(order["target"])
            return True

        path = self._find_path(unit, order["point"])
        if not path:
            self._current_order.pop(id(unit), None)
            return False
        unit.set_move_path(path)
        return True

    def _find_path(self, unit: Unit, point: Optional[Tuple[int, int]]):
        if point is None:
            return None
        return self.pathfinder.find_path_pixels(unit.x, unit.y, point[0], point[1])

    def _update_orders(self):
        """Обслужить текущие приказы и выдать следующие из очереди.

        Каждый вид приказа сам решает, когда он выполнен: «прибыл на точку»,
        «враг убит», «дошёл и никого не встретил». Универсального признака
        «юнит свободен» нет — у обороны приказ не заканчивается, пока его не
        сменят, и у атаки-марша выполнение откладывается, пока в радиусе кто-то
        живой.
        """
        for unit in list(self.blue_units):
            if not unit.alive:
                self._current_order.pop(id(unit), None)
                self._order_queue.pop(id(unit), None)
                self._defend_posts.pop(id(unit), None)
                continue
            order = self._current_order.get(id(unit))
            if order is not None and self._service_order(unit, order):
                continue
            if order is not None and order["kind"] == "defend":
                # дошли до поста: приказ превращается в постоянную стойку
                self._defend_posts[id(unit)] = order["point"]
            self._current_order.pop(id(unit), None)
            self._start_queued(unit)

    def _start_queued(self, unit: Unit):
        """Выдать юниту следующий приказ из очереди, пропуская невыполнимые.

        Невыполнимый приказ (пути нет) не должен молча съедать очередь и не
        должен обрывать её: пропускаем и идём дальше, а если выполнить нечего —
        снимаем приказ совсем.
        """
        pending = self._order_queue.get(id(unit))
        while pending:
            nxt = pending.pop(0)
            if not pending:
                self._order_queue.pop(id(unit), None)
            if self._start_order(unit, nxt):
                return
        self._current_order.pop(id(unit), None)

    def _service_order(self, unit: Unit, order: dict) -> bool:
        """Один шаг текущего приказа. ``True`` — приказ ещё в силе.

        «Занят» определяется через ``is_moving``: юнит с непроходимым маршрутом
        или живой целью занят, и следующий приказ из очереди ждёт.
        """
        kind = order["kind"]

        if kind == "attack":
            target = order["target"]
            if target is None or not target.alive:
                return False
            if unit._attack_target is not target:
                # цель перехватили извне — возвращаем свою, иначе приказ «бить
                # этого» тихо превратился бы в «бить кого попало»
                unit.set_attack_target(target)
            return True

        target = unit._attack_target
        if target is not None:
            if not target.alive:
                unit.clear_orders()
            elif kind == "attack_move" and self._beyond_leash(unit, order, ATTACK_MOVE_LEASH):
                # враг ушёл слишком далеко от назначенной точки: атака-марш
                # жертвует погоней ради маршрута, иначе «идти к ферме» превратилось
                # бы в «погнаться за первым встречным через всю карту»
                unit.clear_orders()
            else:
                return True

        if kind == "attack_move":
            # бой по дороге проверяется ДО ``is_moving``: иначе отряд прошёл бы
            # сквозь врага в двух шагах, не заметив его. На точке с живым врагом
            # приказ тоже не считается выполненным — как в WC3, атака-марш
            # достреливает перед тем, как доложить о выполнении.
            #
            # Leash'ом отмеряется только уже начатый бой (см. выше): новую цель
            # подбирает кто угодно в радиусе атаки, расстояние до точки
            # назначения тут ни при чём — иначе отряд, которому назначили точку
            # через полкарты, вообще не вступал бы в бой по дороге.
            enemy = self._nearest_enemy_in_range(unit)
            if enemy is not None:
                unit.set_attack_target(enemy)
                return True

        if unit.is_moving:
            return True

        point = order["point"]
        at_point = (point is not None
                    and math.hypot(unit.x - point[0], unit.y - point[1])
                    <= CELL_SIZE)
        if at_point:
            return False
        path = self._find_path(unit, point)
        if path:
            unit.set_move_path(path)
            return True
        # пути больше нет и до цели не дошли: приказ невыполним, снимаем его
        # молча — игрок увидит, что отряд стоит, а счётчик отказов в ``_show_msg``
        # уже занят очередью
        return False

    def _beyond_leash(self, unit: Unit, order: dict, leash: float) -> bool:
        point = order["point"]
        return (point is not None
                and math.hypot(unit.x - point[0], unit.y - point[1]) > leash)

    def _update_defenders(self):
        """Посты обороны: держать точку и бить всё, что подошло.

        Отдельный проход от ``_service_order``: у arrived-обороны больше нет
        маршрута, и «занят ли юнит» решает не он, а наличие цели. Отсюда же
        ``DEFEND_LEASH`` — оборона вступает в бой с подошедшим, но не уходит от
        поста, иначе «держать деревню» означало бы «погнаться за первым, кто
        подошёл», и пост остался бы пустым.
        """
        for unit in self.blue_units:
            point = self._defend_posts.get(id(unit))
            if point is None:
                continue
            if not unit.alive:
                self._defend_posts.pop(id(unit), None)
                continue
            target = unit._attack_target
            if target is not None and not target.alive:
                target = None
                unit.clear_orders()
            if target is not None:
                if self._beyond_leash(unit, {"point": point}, DEFEND_LEASH):
                    unit.clear_orders()
                continue
            enemy = self._nearest_enemy_in_range(unit)
            if enemy is not None:
                unit.set_attack_target(enemy)
            elif not unit.is_moving and math.hypot(
                    unit.x - point[0], unit.y - point[1]) > CELL_SIZE:
                # столкновения или отход с пути сбили с поста — вернуться
                path = self._find_path(unit, point)
                if path:
                    unit.set_move_path(path)

    def _nearest_enemy_in_range(self, unit: Unit) -> Optional[Unit]:
        best: Optional[Unit] = None
        best_d = unit.attack_range
        for enemy in self.red_units:
            if not enemy.alive:
                continue
            d = unit.distance_to(enemy)
            if d <= best_d:
                best, best_d = enemy, d
        return best

    def _queue_len(self, unit: Unit) -> int:
        return len(self._order_queue.get(id(unit), ()))

    def _toggle_orders(self):
        self._show_orders = not self._show_orders

    def _restart(self):
        self._game_over = False
        self._winner = None
        self._clear_selection()
        self.all_units.clear()
        self.blue_units.clear()
        self.red_units.clear()
        self._blue_food = FOOD_MAX
        self._red_food = FOOD_MAX
        self._recruit_timer = 0.0
        # отряды и очереди приказов ссылаются на юнитов прошлого боя, поэтому
        # после перезапуска они указывали бы на мёртвые объекты
        self._control_groups.clear()
        self._order_queue.clear()
        self._current_order.clear()
        self._defend_posts.clear()
        self._message = ""
        self._message_timer = 0.0
        self._command_mode = CommandMode.ATTACK_MOVE
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

        # приказы обслуживаются ПОСЛЕ движения юнитов и ИИ: «занято ли» решается
        # по тому, куда юниты доехали в этом кадре, а не по прошлому
        self._update_orders()
        self._update_defenders()
        if self._message_timer > 0:
            self._message_timer -= dt

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
            self._render_queue_markers()

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

    def _war_banner_text(self):
        """Строка плашки: сырые войска и выставленные отряды.

        Показываем СЫРЫЕ войска обеих сторон рядом с числом отрядов. Отряды
        у сторон равные (``WarSession.battle_units``), поэтому перевес виден
        только по людям: без «1200 lev -> 9 u vs 3000 lev -> 9 u» игрок видел
        бы симметричное поле и не понимал, откуда взялся перевес.
        """
        ws = self.session
        if ws is None:
            return ""
        def_troops = ws.defender_troops
        def_txt = (f"{def_troops}" if def_troops is not None
                   else f"{ws.defender_units * TROOPS_PER_TACTICAL_UNIT}")
        return (f"WORLD WAR #{ws.match_id}: {ws.general_name} "
                f"{ws.troops_committed} lev -> {ws.battle_units} u "
                f"(q{clamp_quality(ws.quality)}, {TROOPS_PER_TACTICAL_UNIT}/u) "
                f"vs {def_txt} lev -> {ws.battle_units} u "
                f"[{ws.attacker_nation} vs {ws.defender_nation}]")

    def _render_war_banner(self):
        """Плашка «этот бой вырос из мира» поверх верхнего края карты.

        Игрок обязан видеть, ЧТО он привёл на эту карту: имя генерала, сколько
        левейса ушло в бой и какой выучки войска. Без этого отряд из девяти
        юнитов выглядит как обычная тренировка, а итог боя на карте мира
        оказывается неожиданным.

        Плашка рисуется НЕ в HUD: полоса снизу высотой 64 px занята тремя
        рядами подписей. Сверху карты места нет, поэтому полоса с тёмной
        подложкой читается как заголовок миссии и ничего не перекрывает.
        """
        ws = self.session
        if ws is None:
            return
        text = self._war_banner_text()
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

        # Три фиксированных ряда: ни одна подпись не заезжает на соседнюю.
        row1 = hud_y + 2
        row2 = hud_y + 22
        row3 = hud_y + 42

        blue_text = self.font_hud.render(
            f"BLUE: {blue_alive} | HP:{total_blue} | Food:{int(self._blue_food)}", True, COLOR_BLUE
        )
        red_text = self.font_hud.render(
            f"RED: {red_alive} | HP:{total_red} | Food:{int(self._red_food)}", True, COLOR_RED
        )
        self.screen.blit(blue_text, (12, row2))
        self.screen.blit(red_text, (SCREEN_WIDTH - red_text.get_width() - 12, row2))

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
        self.screen.blit(v_text, (SCREEN_WIDTH // 2 - v_text.get_width() // 2, row1))

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
            self.screen.blit(info_text, (SCREEN_WIDTH // 2 - info_text.get_width() // 2, row2))

        cmd_text = self.font_hud.render(
            f"[{_MODE_HINTS[self._command_mode]}]", True, _mode_color(self._command_mode)
        )
        self.screen.blit(cmd_text, (SCREEN_WIDTH - cmd_text.get_width() - 12, row1))

        controls = self.font_hud.render(
            "LMB select | Shift+LMB add | dbl-click type | Ctrl+1-9 /1-9 group | "
            "RMB order (Shift=queue) | A atk-move | S stop | ESC quit",
            True, COLOR_HUD_TEXT_DIM,
        )
        self.screen.blit(controls, (SCREEN_WIDTH // 2 - controls.get_width() // 2, row3))

        # Сообщение занимает ту же строку подсказок, пока жив таймер: полоса HUD
        # рассчитана ровно на три ряда, а четвёртый ряд перекрыл бы нижний ряд
        # карты. Поэтому подсказка исчезает на пару секунд и возвращается.
        if self._message_timer > 0 and self._message:
            msg = self.font_hud.render(self._message, True, COLOR_HUD_TEXT)
            self.screen.blit(msg, (SCREEN_WIDTH // 2 - msg.get_width() // 2, row3))

    def _render_queue_markers(self):
        """Показать очередь приказов на карте: куда юнит пойдёт дальше.

        Метки рисуются только для выделенных юнитов и только когда видны
        приказы (``_show_orders``): иначе поле превращалось бы в россыпь точек
        от тех, кого игрок уже отпустил.
        """
        if not self._show_orders:
            return
        marker = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT - HUD_HEIGHT),
                                pygame.SRCALPHA)
        for unit in self.selected_units:
            if not unit.alive:
                continue
            for order in self._order_queue.get(id(unit), []):
                point = order.get("point")
                if point is None:
                    # приказ-атака: помечаем клетку цели. Мёртвую цель не
                    # помечаем — приказ всё равно будет снят, когда дойдёт
                    target = order.get("target")
                    if target is None or not target.alive:
                        continue
                    point = (target.x, target.y)
                pygame.draw.circle(marker, COLOR_QUEUE_MARKER,
                                   (int(point[0]), int(point[1])), 5, 2)
        self.screen.blit(marker, (0, 0))

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
