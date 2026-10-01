import pygame
import sys
import math
import random
from typing import Optional, List, Tuple, Dict
from world_data import (
    SCREEN_WIDTH, SCREEN_HEIGHT,
    COLOR_OCEAN, COLOR_OCEAN_LIGHT, COLOR_LAND, COLOR_RIVER,
    COLOR_BRIDGE, COLOR_NEUTRAL, COLOR_PROVINCE_BORDER,
    COLOR_HUD_BG, COLOR_HUD_TEXT, COLOR_HUD_TEXT_DIM,
    COLOR_WHITE, COLOR_BLACK,
    COLOR_GENERAL_SELECTED, COLOR_GENERAL_MOVABLE, COLOR_GENERAL_DONE,
    WORLD_NATIONS, WORLD_PROVINCES, PLAYER_NATION, WORLD_GENERALS,
    RegionType, Province, General,
    PROVINCE_CONNECTIONS, BRIDGE_CONNECTIONS,
    RIVER_WEST_X, RIVER_EAST_X,
)
from diplomacy import DiplomacyManager, Relation
from textures import TextureManager, GeneralIcon, RiverRenderer
from states import build_default_hierarchy, TitleRank, CONTRACT_LEVELS

# Базовые цвета границ по владельцу. Вынесены на уровень модуля, чтобы
# палитру ранга можно было применять поверх, не трогая саму карту.
OWNER_BORDER = {
    "neutral": (195, 180, 140),
    "red": (185, 90, 75),
    "blue": (95, 135, 205),
    "green": (95, 175, 105),
}

# Палитра границ провинций по рангу держателя. Базовые цвета — по владельцу,
# оттенки ранга добавляются поверх: король насыщеннее, герцог светлее.
# Ключ — ранг из states.TitleRank; отсутствие ключа оставляет базовый цвет,
# поэтому нейтральные провинции выглядят ровно как раньше.
_RANK_TINT = {
    TitleRank.KING: (60, 48, 24),
    TitleRank.DUKE: (70, 68, 48),
    TitleRank.BARON: None,
}

# Нации в порядке показа в панели владений: игрок всегда первый.
_PANEL_NATION_ORDER = ("blue", "red", "green")

# Порядок персонажей в списке двора: король -> герцоги -> бароны.
_RANK_ORDER = {
    TitleRank.KING: 0,
    TitleRank.DUKE: 1,
    TitleRank.BARON: 2,
}

# Цвет строки персонажа по рангу: король ярче, герцог средне, барон туше.
_VASSAL_COLOR = {
    TitleRank.KING: (235, 215, 165),
    TitleRank.DUKE: (205, 190, 155),
    TitleRank.BARON: (175, 165, 140),
}

# Тот же цвет для чужой державы, но сильно приглушённый: дерево владений
# показывается всем, а вот выбрать персонажа чужой нации нельзя.
_VASSAL_COLOR_FOREIGN = {
    TitleRank.KING: (135, 125, 105),
    TitleRank.DUKE: (120, 112, 96),
    TitleRank.BARON: (105, 100, 88),
}

# Подсветка выбранной строки панели: заливка, рамка и яркость текста.
_PANEL_SEL_FILL = (255, 230, 150, 55)
_PANEL_SEL_BORDER = (255, 226, 150)
_PANEL_SEL_TEXT = (255, 236, 190)

# Размер панели владений. Задаётся один раз, потому что панель рисуется
# в собственную поверхность этого размера.
_PANEL_W, _PANEL_H = 700, 560

# Внутренняя раскладка панели владений. Все координаты локальные, относительно
# левого верхнего угла _panel_surface; экранные получаются прибавлением origin
# из _panel_layout. Контент дерева занимает ~360 px из 700, поэтому правый
# столбец (персонажи) поместился без изменения _PANEL_W/_PANEL_H — на них
# завязаны _panel_surface и хит-тесты, их трогать нельзя.
_PANEL_PAD = 20                     # поле слева и справа
_PANEL_TREE_W = 372                 # ширина левого столбца (дерево владений)
_PANEL_COL2_X = 412                 # левый край правого столбца (персонажи)
_PANEL_COL2_W = _PANEL_W - _PANEL_COL2_X - _PANEL_PAD
_PANEL_TREE_Y = 68                  # верх дерева владений и шапки столбцов
_PANEL_LINE_H = 16                  # шаг строки дерева
_PANEL_ROW_H = 13                   # шаг строки списка персонажей
_PANEL_MAX_Y = _PANEL_H - 40        # ниже этого дерево не рисуется
_PANEL_HINT_Y = _PANEL_H - 25       # строка подсказки

# Потолок кэша строк: заполненный кэш сбрасывается целиком, иначе он
# рос бы бесконечно при смене чисел в хинтах и тултипах.
_TEXT_CACHE_LIMIT = 2000

# Маркер «в кэше ничего нет» — им кэшируются и значения None.
_MISSING = object()

# Ключи кэша вычислений: (метка, аргумент) -> значение.
_TC_DUCHIES = "duchies"
_TC_HOLDER = "holder"
_TC_CONTRACT = "contract"
_TC_COUNTY_INCOME = "county_income"
_TC_DUCHY_INCOME = "duchy_income"
_TC_DUCHY_LEVY = "duchy_levy"
_TC_VASSALS = "vassals"


class WorldMapScreen:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("Tactic Battle - World Map")
        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        self.clock = pygame.time.Clock()
        self.running = True

        self.font_hud = pygame.font.SysFont(None, 16)
        self.font_title = pygame.font.SysFont(None, 24, bold=True)
        self.font_small = pygame.font.SysFont(None, 12)
        self.font_region = pygame.font.SysFont(None, 11)
        self.font_troops = pygame.font.SysFont(None, 14, bold=True)

        self.cam_x = 0
        self.cam_y = 0
        self.zoom = 1.0
        self._zoom_min, self._zoom_max = 0.5, 2.5
        self._scroll_speed = 500
        self._dragging = False
        self._drag_start = (0, 0)
        self._cam_start = (0, 0)
        self._rmb_dragging = False
        self._rmb_start = (0, 0)
        self._rmb_cam_start = (0, 0)
        self._rmb_moved = False
        self._keys_held = set()
        self._mouse_pos = (0, 0)
        self._hover_province = None
        self._zoom_cache = {}
        # serif для подписей городов как на референсе
        try:
            self.font_city = pygame.font.SysFont("serif", 22)
            self.font_city_small = pygame.font.SysFont("serif", 15)
        except Exception:
            self.font_city = pygame.font.SysFont(None, 22)
            self.font_city_small = pygame.font.SysFont(None, 15)

        self.diplomacy = DiplomacyManager()
        self.provinces: List[Province] = [Province(p.name, p.owner, p.region_type,
                                                    list(p.polygon), list(p.neighbors))
                                           for p in WORLD_PROVINCES]
        # иерархия владений поверх тех же провинций: графство = провинция,
        # поле owner не трогаем, чтобы старые механики и тесты не сломались
        self.hierarchy = build_default_hierarchy(self.provinces)
        for _realm in self.hierarchy.realms.values():
            _realm.is_player = (_realm.nation == PLAYER_NATION)

        self.generals: List[General] = [General(g.name, g.nation, g.province_idx, g.troops)
                                         for g in WORLD_GENERALS]
        for orig, copy in zip(WORLD_GENERALS, self.generals):
            copy.health = orig.health

        self.connections: List[Tuple[int, int]] = list(PROVINCE_CONNECTIONS)
        self._build_connection_index()

        self.selected_general: Optional[General] = None
        self._turn = 1
        self._show_diplomacy = False
        self._diplomacy_target: Optional[str] = None
        self._battle_result: Optional[str] = None
        self._battle_timer = 0.0
        self._show_ownership = False
        self._ownership_nation: str = PLAYER_NATION
        # выбор внутри панели владений: персонаж и графство
        self._sel_character_id: Optional[str] = None
        self._sel_county_idx: Optional[int] = None
        # режим панели; пока один, задел на кнопки приказов королю
        self._own_mode: str = "browse"
        # курсор по списку персонажей правого столбца (Up/Down)
        self._vassal_cursor: int = 0
        self._game_over = False
        self._winner: Optional[str] = None
        self._message: Optional[str] = None
        self._message_timer = 0.0

        self.tex_manager = TextureManager()
        self._build_province_offsets()
        self._build_static_surfaces()

    def _build_static_surfaces(self):
        """Поверхности, которые больше не меняются: затемнения и панель владений.

        Затемнение раньше создавалось заново в каждом кадре: это ~6.7 МБ
        аллокации плюс fill и blit на 1.66 млн пикселей — 8-16 мс на кадр.
        Теперь оно готовится один раз после set_mode и просто блитится.
        """
        def _dim(alpha: int) -> pygame.Surface:
            surf = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
            surf.fill((0, 0, 0, alpha))
            return surf

        # общее затемнение панелей владений и дипломатии
        self._dim_surface = _dim(120)
        # затемнение финала партии
        self._dim_surface_strong = _dim(150)
        # мягкое затемнение под всплывающим текстом
        self._dim_surface_soft = _dim(80)
        # панель владений рисуется один раз и копируется на экран целиком
        self._panel_surface = pygame.Surface((_PANEL_W, _PANEL_H), pygame.SRCALPHA)
        self._panel_dirty = True
        # раскладка панели: общая для отрисовки и для хит-тестов, поэтому
        # картинка и клик не могут разойтись. Пересобирается вместе с панелью
        self._panel_layout: Optional[Dict] = None
        self._panel_layout_turn: Optional[int] = None
        # под что именно нарисована панель: (ход, нация, выделение на карте,
        # выбор персонажа, выбор графства, курсор, режим)
        self._panel_state: Optional[Tuple] = None
        # кэш отрендеренных строк: ключ — (текст, размер шрифта, bold, цвет)
        self._text_cache: Dict[Tuple[str, int, bool, Tuple[int, int, int]],
                               pygame.Surface] = {}
        # ленивый кэш вычислений, привязанный к номеру хода
        self._turn_cache: Dict[Tuple[str, object], object] = {}
        self._turn_cache_turn: Optional[int] = None

    def _build_connection_index(self):
        self._conn_by_province = {}
        for a, b in self.connections:
            self._conn_by_province.setdefault(a, set()).add(b)
            self._conn_by_province.setdefault(b, set()).add(a)

    def _build_province_offsets(self):
        self._prov_offsets = []
        for prov in self.provinces:
            poly = prov.polygon
            min_x = min(p[0] for p in poly)
            min_y = min(p[1] for p in poly)
            self._prov_offsets.append((min_x, min_y))

    def _adjacent_provinces(self, idx: int) -> List[int]:
        return list(self._conn_by_province.get(idx, set()))

    def _clamp_camera(self):
        map_w, map_h = SCREEN_WIDTH, SCREEN_HEIGHT - 80
        vis_w, vis_h = SCREEN_WIDTH / self.zoom, (SCREEN_HEIGHT - 80) / self.zoom
        max_x = max(0, map_w - vis_w)
        max_y = max(0, map_h - vis_h)
        self.cam_x = max(0, min(self.cam_x, max_x))
        self.cam_y = max(0, min(self.cam_y, max_y))

    def _screen_to_world(self, sx: int, sy: int) -> Tuple[int, int]:
        return int(sx / self.zoom + self.cam_x), int(sy / self.zoom + self.cam_y)

    def _world_to_screen(self, wx: int, wy: int) -> Tuple[int, int]:
        return int((wx - self.cam_x) * self.zoom), int((wy - self.cam_y) * self.zoom)

    def _zoom_at(self, sx: int, sy: int, factor: float):
        old_zoom = self.zoom
        new_zoom = max(self._zoom_min, min(self._zoom_max, old_zoom * factor))
        if abs(new_zoom - old_zoom) < 1e-4:
            return
        # точка под курсором остаётся на месте
        wx, wy = self._screen_to_world(sx, sy)
        self.zoom = new_zoom
        self.cam_x = wx - sx / new_zoom
        self.cam_y = wy - sy / new_zoom
        self._clamp_camera()

    def run(self) -> Optional[str]:
        while self.running:
            dt = self.clock.tick(60) / 1000.0
            self._handle_events()
            self._update(dt)
            self._render()
        return self._winner

    def _handle_events(self):
        for event in pygame.event.get():
            sel_before = self.selected_general
            if event.type == pygame.QUIT:
                self.running = False

            elif event.type == pygame.KEYDOWN:
                self._keys_held.add(event.key)
                if event.key == pygame.K_ESCAPE:
                    if self._show_ownership:
                        self._close_ownership_panel()
                    elif self._show_diplomacy:
                        self._show_diplomacy = False
                        self._diplomacy_target = None
                    elif self.selected_general:
                        self.selected_general = None
                    else:
                        self.running = False
                elif event.key == pygame.K_SPACE:
                    self._end_turn()
                elif event.key in (pygame.K_PLUS, pygame.K_EQUALS, pygame.K_KP_PLUS):
                    self._zoom_at(SCREEN_WIDTH // 2, (SCREEN_HEIGHT - 80) // 2, 1.2)
                elif event.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                    self._zoom_at(SCREEN_WIDTH // 2, (SCREEN_HEIGHT - 80) // 2, 1 / 1.2)
                elif event.key == pygame.K_0:
                    self.zoom = 1.0
                    self.cam_x, self.cam_y = 0, 0
                    self._clamp_camera()
                elif event.key in (pygame.K_v, pygame.K_c):
                    if self._show_ownership:
                        self._close_ownership_panel()
                    else:
                        self._show_ownership = True
                        # открыли панель — содержимое рисуется заново
                        self._invalidate_panel()
                elif event.key == pygame.K_TAB:
                    self._show_diplomacy = not self._show_diplomacy
                elif self._show_ownership:
                    # Q/E и стрелки вбок листают нации, стрелки вверх/вниз
                    # двигают курсор по списку персонажей (задел на приказы)
                    if event.key in (pygame.K_q, pygame.K_LEFT):
                        self._cycle_ownership_nation(-1)
                    elif event.key in (pygame.K_e, pygame.K_RIGHT):
                        self._cycle_ownership_nation(1)
                    elif event.key in (pygame.K_UP, pygame.K_DOWN):
                        self._move_vassal_cursor(-1 if event.key == pygame.K_UP else 1)
                elif event.key == pygame.K_n and self._show_diplomacy:
                    self._cycle_diplomacy_target(1)
                elif event.key == pygame.K_p and self._show_diplomacy:
                    self._cycle_diplomacy_target(-1)
                elif self._show_diplomacy:
                    if event.key == pygame.K_1:
                        self._diplomacy_action(Relation.WAR)
                    elif event.key == pygame.K_2:
                        self._diplomacy_action(Relation.NEUTRAL)
                    elif event.key == pygame.K_3:
                        self._diplomacy_action(Relation.FRIENDLY)
                    elif event.key == pygame.K_4:
                        self._diplomacy_action(Relation.ALLIANCE)

            elif event.type == pygame.KEYUP:
                self._keys_held.discard(event.key)

            elif event.type == pygame.MOUSEWHEEL:
                mx, my = pygame.mouse.get_pos()
                # колесо — зум к курсору (как в Total War), с Shift — вертикальный скролл
                keys = pygame.key.get_pressed()
                if keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT]:
                    self.cam_y -= event.y * 40 / self.zoom
                    self._clamp_camera()
                else:
                    self._zoom_at(mx, my, 1.1 if event.y > 0 else 1 / 1.1)

            elif event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 2:
                    self._dragging = True
                    self._drag_start = event.pos
                    self._cam_start = (self.cam_x, self.cam_y)
                elif event.button == 3:
                    self._rmb_dragging = True
                    self._rmb_start = event.pos
                    self._rmb_cam_start = (self.cam_x, self.cam_y)
                    self._rmb_moved = False
                elif event.button == 1:
                    mx, my = event.pos
                    # панель лежит поверх карты: клик по её строке — это
                    # выбор в панели, а не выбор генерала под ней
                    if self._panel_hit(mx, my) is not None:
                        self._handle_panel_click(mx, my)
                    elif my < SCREEN_HEIGHT - 80:
                        self._handle_map_click(mx, my)

            elif event.type == pygame.MOUSEBUTTONUP:
                if event.button == 2:
                    self._dragging = False
                elif event.button == 3:
                    was_drag = self._rmb_moved
                    self._rmb_dragging = False
                    if not was_drag:
                        # правый клик без драга — приказ / снять выделение (RTS-стиль)
                        mx, my = event.pos
                        if self._panel_hit(mx, my) is not None:
                            self._handle_panel_click(mx, my)
                        elif my < SCREEN_HEIGHT - 80:
                            if self.selected_general:
                                self._handle_map_click(mx, my, via_right=True)
                            else:
                                self.selected_general = None

            elif event.type == pygame.MOUSEMOTION:
                self._mouse_pos = event.pos
                if self._dragging:
                    dx = (event.pos[0] - self._drag_start[0]) / self.zoom
                    dy = (event.pos[1] - self._drag_start[1]) / self.zoom
                    self.cam_x = self._cam_start[0] - dx
                    self.cam_y = self._cam_start[1] - dy
                    self._clamp_camera()
                if self._rmb_dragging:
                    dx = (event.pos[0] - self._rmb_start[0]) / self.zoom
                    dy = (event.pos[1] - self._rmb_start[1]) / self.zoom
                    if abs(dx) + abs(dy) > 5:
                        self._rmb_moved = True
                    if self._rmb_moved:
                        self.cam_x = self._rmb_cam_start[0] - dx
                        self.cam_y = self._rmb_cam_start[1] - dy
                        self._clamp_camera()

            if self.selected_general is not sel_before:
                # смена выделения тоже считается поводом перерисовать панель
                self._invalidate_panel()

    def _handle_map_click(self, mx: int, my: int, via_right: bool = False):
        if my >= SCREEN_HEIGHT - 80:
            return

        wx, wy = self._screen_to_world(mx, my)

        clicked_province = None
        for i, prov in enumerate(self.provinces):
            if prov.contains_point(wx, wy):
                clicked_province = i
                break

        if self.selected_general:
            g = self.selected_general
            g_prov = g.province_idx

            if clicked_province is not None and clicked_province != g_prov:
                adj = self._adjacent_provinces(g_prov)
                if clicked_province in adj:
                    self._move_general_to_province(g, clicked_province)
                    self.selected_general = None
                    return

            if clicked_province is not None:
                for gen in self.generals:
                    if gen.nation == PLAYER_NATION and not gen.moved:
                        if gen.province_idx == clicked_province:
                            self.selected_general = gen
                            return
            self.selected_general = None
        else:
            if clicked_province is not None:
                for gen in self.generals:
                    if gen.nation == PLAYER_NATION and not gen.moved:
                        if gen.province_idx == clicked_province:
                            self.selected_general = gen
                            return

    def _move_general_to_province(self, general: General, target_idx: int):
        target = self.provinces[target_idx]

        for other in self.generals:
            if other is not general and other.province_idx == target_idx:
                if self.diplomacy.is_enemy(general.nation, other.nation):
                    self._start_battle(general, other)
                    general.moved = True
                    return
                elif general.nation != other.nation:
                    rel = self.diplomacy.get_relation(general.nation, other.nation)
                    if rel in (Relation.FRIENDLY, Relation.ALLIANCE):
                        other.troops += general.troops
                        self.generals.remove(general)
                        general.moved = True
                        self._show_msg("Армии объединены!")
                        return
                    else:
                        self._show_msg("Нельзя войти на чужую территорию!")
                        return

        if target.owner == "neutral":
            target.owner = general.nation
            general.province_idx = target_idx
            general.moved = True
            self._invalidate_panel()
            self._show_msg(f"{target.name} захвачена!")
        elif target.owner == general.nation:
            target.troops += general.troops // 10
            general.province_idx = target_idx
            general.moved = True
            self._invalidate_panel()
        else:
            rel = self.diplomacy.get_relation(general.nation, target.owner)
            if rel == Relation.WAR:
                if target.troops <= 0:
                    target.owner = general.nation
                    target.troops = 0
                    general.province_idx = target_idx
                    general.moved = True
                    self._invalidate_panel()
                    self._show_msg(f"{target.name} захвачена!")
                else:
                    self._start_battle_with_region(general, target)
                    general.moved = True
            else:
                self._show_msg("Нельзя войти на чужую территорию!")
                return

    def _start_battle(self, attacker: General, defender: General):
        a_power = attacker.troops * (attacker.health / 100)
        d_power = defender.troops * (defender.health / 100)
        a_roll = a_power * random.uniform(0.7, 1.3)
        d_roll = d_power * random.uniform(0.7, 1.3)

        if a_roll > d_roll:
            ratio = d_roll / a_roll if a_roll > 0 else 0
            losses = int(attacker.troops * ratio * 0.3)
            attacker.troops = max(100, attacker.troops - losses)
            defender.troops = max(0, defender.troops - int(defender.troops * 0.7))
            if defender.troops <= 0:
                self.generals.remove(defender)
                self._battle_result = f"{attacker.name} победил {defender.name}!"
            else:
                self._battle_result = f"{attacker.name} отбит, потеряно {losses}"
            defender.health = max(0, defender.health - 20)
        else:
            losses = int(attacker.troops * 0.5)
            attacker.troops = max(0, attacker.troops - losses)
            if attacker.troops <= 0:
                self.generals.remove(attacker)
                self._battle_result = f"{defender.name} уничтожил {attacker.name}!"
            else:
                self._battle_result = f"{attacker.name} отступил, потеряно {losses}"
        self._battle_timer = 3.0

    def _start_battle_with_region(self, general: General, region: Province):
        a_power = general.troops * (general.health / 100)
        d_power = region.troops
        a_roll = a_power * random.uniform(0.7, 1.3)
        d_roll = d_power * random.uniform(0.7, 1.3)

        if a_roll > d_roll:
            losses = int(general.troops * 0.2)
            general.troops = max(100, general.troops - losses)
            region.owner = general.nation
            region.troops = 0
            general.province_idx = self.provinces.index(region)
            self._battle_result = f"{general.name} захватил {region.name}!"
        else:
            losses = int(general.troops * 0.4)
            general.troops = max(0, general.troops - losses)
            region.troops = max(0, region.troops - int(region.troops * 0.3))
            self._battle_result = f"{general.name} отбит от {region.name}!"
        self._invalidate_panel()
        self._battle_timer = 3.0

    def _show_msg(self, msg: str):
        self._message = msg
        self._message_timer = 2.0

    def _cycle_diplomacy_target(self, direction: int):
        nations = [n for n in WORLD_NATIONS if n != PLAYER_NATION]
        if not nations:
            return
        if self._diplomacy_target is None:
            self._diplomacy_target = nations[0]
        else:
            idx = nations.index(self._diplomacy_target) if self._diplomacy_target in nations else 0
            idx = (idx + direction) % len(nations)
            self._diplomacy_target = nations[idx]

    def _ownership_nations(self) -> List[str]:
        """Нации для панели владений: сначала игрок, потом остальные по карте."""
        ordered = [n for n in _PANEL_NATION_ORDER if n in WORLD_NATIONS]
        for n in WORLD_NATIONS:
            if n not in ordered:
                ordered.append(n)
        return ordered

    def _cycle_ownership_nation(self, direction: int):
        nations = self._ownership_nations()
        if not nations:
            return
        if self._ownership_nation not in nations:
            self._ownership_nation = nations[0]
            self._reset_ownership_selection()
            self._invalidate_panel()
            return
        idx = nations.index(self._ownership_nation)
        self._ownership_nation = nations[(idx + direction) % len(nations)]
        # смена нации сбрасывает выбор и курсор: иначе выбранным остался бы
        # персонаж чужой державы, и будущий приказ королю ушёл бы не туда
        self._reset_ownership_selection()
        self._invalidate_panel()

    def _close_ownership_panel(self):
        """Закрыть панель владений и сбросить её выбор (ESC или V).

        Сброс обязателен: без него после закрытия остался бы «призрачный»
        выбранный персонаж, и на следующем открытии панель подсветила бы
        строку, по которой уже никто не кликал.
        """
        self._show_ownership = False
        self._reset_ownership_selection()
        self._invalidate_panel()

    def _reset_ownership_selection(self):
        """Снять выбор панели: персонажа, графство, режим и курсор."""
        self._sel_character_id = None
        self._sel_county_idx = None
        self._own_mode = "browse"
        self._vassal_cursor = 0

    def _panel_allows_orders(self) -> bool:
        """Можно ли выбирать персонажа в панели — только у своей нации.

        Дерево владений показывается всем державам, а вот приказы королю
        (следующий этап) должны доставаться только своим. Правило одно и
        здесь, и в раскладке панели, и в _move_vassal_cursor.
        """
        return self._ownership_nation == PLAYER_NATION

    def _move_vassal_cursor(self, direction: int):
        """Сдвиг курсора по списку персонажей (Up/Down).

        Курсор и выбор ходят вместе: в режиме просмотра это всё, что нужно,
        а на этапе с приказами курсор станет целью приказа королю. У края
        списка курсор стоит на месте.
        """
        vassals = self._vassals_of_nation(self._ownership_nation)
        if not vassals:
            return
        idx = max(0, min(self._vassal_cursor, len(vassals) - 1))
        self._vassal_cursor = max(0, min(idx + direction, len(vassals) - 1))
        if self._panel_allows_orders():
            self._sel_character_id = vassals[self._vassal_cursor].id
            self._sel_county_idx = None
        self._invalidate_panel()

    def _diplomacy_action(self, relation: Relation):
        if not self._diplomacy_target:
            return
        success, msg = self.diplomacy.propose(
            PLAYER_NATION, self._diplomacy_target, relation
        )
        self._show_msg(msg)

    def _end_turn(self):
        self._turn += 1
        for g in self.generals:
            g.moved = False
        self._ai_turn()
        self._tick_ownership()
        # ход сменился: кэш вычислений и панель владений больше не действительны
        self._invalidate_panel()

    def _tick_ownership(self):
        """Экономика владений за ход. В лог идёт всё, на экран — только важное."""
        events = self.hierarchy.end_turn()
        if not events:
            return

        rebellions = [e for e in events if e.startswith("Мятеж")]
        loyalty = [e for e in events if "лояльность" in e and not e.startswith("Мятеж")]

        if rebellions:
            self._show_msg(f"Мятеж! {rebellions[0]}"
                           + (f" (+{len(rebellions) - 1})" if len(rebellions) > 1 else ""))
        elif loyalty:
            self._show_msg(f"Лояльность вассалов падает: {loyalty[0]}"
                           + (f" (+{len(loyalty) - 1})" if len(loyalty) > 1 else ""))

    def _ai_turn(self):
        for g in self.generals:
            if g.nation != PLAYER_NATION and not g.moved:
                self._ai_move_general(g)

    def _ai_move_general(self, general: General):
        g_idx = general.province_idx

        enemies = []
        for e in self.generals:
            if e.nation != general.nation and self.diplomacy.is_enemy(general.nation, e.nation):
                enemies.append(e)

        if enemies:
            nearest = min(enemies, key=lambda e: general.distance_to(e))
            if general.distance_to(nearest) <= 200:
                for adj in self._adjacent_provinces(g_idx):
                    for e in self.generals:
                        if e is nearest and e.province_idx == adj:
                            self._move_general_to_province(general, adj)
                            general.moved = True
                            return

        neutral_targets = []
        for adj in self._adjacent_provinces(g_idx):
            if self.provinces[adj].owner == "neutral":
                neutral_targets.append(adj)

        if neutral_targets:
            target_idx = random.choice(neutral_targets)
            self._move_general_to_province(general, target_idx)
            general.moved = True
            return

        for adj in self._adjacent_provinces(g_idx):
            prov = self.provinces[adj]
            if prov.owner != general.nation and prov.owner != "neutral":
                rel = self.diplomacy.get_relation(general.nation, prov.owner)
                if rel == Relation.WAR and prov.troops <= 0:
                    self._move_general_to_province(general, adj)
                    general.moved = True
                    return

    def _update(self, dt: float):
        if not self._show_diplomacy and not self._show_ownership:
            scroll = self._scroll_speed * dt / self.zoom
            if pygame.K_w in self._keys_held or pygame.K_UP in self._keys_held:
                self.cam_y -= scroll
            if pygame.K_s in self._keys_held or pygame.K_DOWN in self._keys_held:
                self.cam_y += scroll
            if pygame.K_a in self._keys_held or pygame.K_LEFT in self._keys_held:
                self.cam_x -= scroll
            if pygame.K_d in self._keys_held or pygame.K_RIGHT in self._keys_held:
                self.cam_x += scroll
            self._clamp_camera()

        # ховер провинции для подсветки + тултипа
        try:
            mx, my = self._mouse_pos
            if my < SCREEN_HEIGHT - 80:
                wx, wy = self._screen_to_world(mx, my)
                self._hover_province = None
                for i, prov in enumerate(self.provinces):
                    if prov.contains_point(wx, wy):
                        self._hover_province = i
                        break
            else:
                self._hover_province = None
        except Exception:
            self._hover_province = None

        if self._battle_timer > 0:
            self._battle_timer -= dt
            if self._battle_timer <= 0:
                self._battle_result = None

        if self._message_timer > 0:
            self._message_timer -= dt
            if self._message_timer <= 0:
                self._message = None

        blue_alive = any(g.nation == PLAYER_NATION for g in self.generals)
        other_alive = [g for g in self.generals if g.nation != PLAYER_NATION]
        if not blue_alive and other_alive:
            self._game_over = True
            self._winner = "DEFEAT"
        elif blue_alive and not other_alive:
            self._game_over = True
            self._winner = "VICTORY"

    #: ссылка на палитру уровня модуля (оставлена для совместимости)
    _OWNER_BORDER = OWNER_BORDER

    def _border_color(self, idx: int, prov) -> Tuple[int, int, int]:
        """Цвет границы провинции: базовый по владельцу + оттенок ранга.

        Ранг берём у de jure герцогства: если провинцию держит персонаж,
        граница подсвечивается сильнее у короля и мягче у герцога. У
        нейтральных провинций и у владений без персонажа остаётся базовый
        цвет, поэтому вид карты не меняется.
        """
        base = OWNER_BORDER.get(prov.owner, COLOR_PROVINCE_BORDER)
        duchy_id = getattr(prov, "duchy_id", None)
        if not duchy_id or prov.owner == "neutral":
            return base
        holder = self.hierarchy.holder_of_duchy(duchy_id)
        if holder is None:
            return base
        tint = _RANK_TINT.get(holder.rank)
        if tint is None:
            return base
        return (
            min(255, base[0] + tint[0]),
            min(255, base[1] + tint[1]),
            min(255, base[2] + tint[2]),
        )

    def _get_scaled_tex(self, i, tex):
        zr = round(self.zoom, 1)
        key = (i, zr, tex.get_width(), tex.get_height())
        # кэш с привязкой к объекту текстуры (владелец уже в ключе менеджера)
        ckey = (i, id(tex), zr)
        if ckey in self._zoom_cache:
            return self._zoom_cache[ckey]
        if abs(self.zoom - 1.0) < 0.02:
            self._zoom_cache[ckey] = tex
            return tex
        nw = max(1, int(tex.get_width() * self.zoom))
        nh = max(1, int(tex.get_height() * self.zoom))
        try:
            scaled = pygame.transform.smoothscale(tex, (nw, nh))
        except Exception:
            scaled = pygame.transform.scale(tex, (nw, nh))
        # чистим старые зумы той же провинции
        for k in [k for k in self._zoom_cache if k[0] == i and k[2] != zr]:
            self._zoom_cache.pop(k, None)
        self._zoom_cache[ckey] = scaled
        return scaled

    # ---------------- кэши ----------------

    def _cached_text(self, font, text: str, color) -> pygame.Surface:
        """Отрисованная строка из кэша.

        Ключ — (текст, размер шрифта, bold, цвет). Шрифты экрана создаются
        один раз в __init__ и больше не меняются, поэтому такая четвёрка
        однозначно задаёт картинку: заголовки, хинты и подписи городов
        перестают прогоняться через font.render каждый кадр.
        """
        try:
            size = font.get_point_size()
        except Exception:
            size = font.get_height()
        key = (text, size, bool(font.get_bold()), tuple(color))
        surf = self._text_cache.get(key)
        if surf is None:
            if len(self._text_cache) >= _TEXT_CACHE_LIMIT:
                # дешевле сбросить целиком, чем следить за устаревшими ключами
                self._text_cache.clear()
            surf = font.render(text, True, color)
            self._text_cache[key] = surf
        return surf

    def _invalidate_panel(self):
        """Сбросить кэш вычислений и пометить панель владений на перерисовку.

        Раскладка сбрасывается здесь же: она считается вместе с картинкой,
        и любое изменение выбора/курсора обязано проходить через этот метод,
        иначе панель продолжит показывать старое состояние.
        """
        self._turn_cache = {}
        self._turn_cache_turn = None
        self._panel_dirty = True
        self._panel_layout = None

    def _turn_cached(self, key: Tuple[str, object], compute):
        """Ленивый кэш, живущий один ход.

        Владения нации, доходы и levy между ходами не меняются, но считались
        заново каждый кадр. Кэш живёт до смены номера хода или явного сброса
        (захват провинции, смена нации панели).
        """
        if self._turn_cache_turn != self._turn:
            self._turn_cache = {}
            self._turn_cache_turn = self._turn
        val = self._turn_cache.get(key, _MISSING)
        if val is _MISSING:
            # маркер нужен, чтобы кэшировать и None — «без держателя» и т.п.
            val = compute()
            self._turn_cache[key] = val
        return val

    def _county_income(self, idx: int) -> int:
        return self._turn_cached((_TC_COUNTY_INCOME, idx),
                                 lambda: self.hierarchy.county_income(idx))

    def _duchy_income(self, duchy_id: str) -> int:
        return self._turn_cached((_TC_DUCHY_INCOME, duchy_id),
                                 lambda: self.hierarchy.duchy_income(duchy_id))

    def _duchy_levy(self, duchy_id: str) -> int:
        return self._turn_cached((_TC_DUCHY_LEVY, duchy_id),
                                 lambda: self.hierarchy.duchy_levy(duchy_id))

    def _holder_of_duchy(self, duchy_id: str):
        return self._turn_cached((_TC_HOLDER, duchy_id),
                                 lambda: self.hierarchy.holder_of_duchy(duchy_id))

    def _contract_of(self, vassal_id: str):
        return self._turn_cached((_TC_CONTRACT, vassal_id),
                                 lambda: self.hierarchy.contract_of(vassal_id))

    def _render(self):
        view_h = SCREEN_HEIGHT - 80
        ocean = self.tex_manager.get_ocean_texture(SCREEN_WIDTH, view_h)
        if abs(self.zoom - 1.0) > 0.02:
            try:
                ocean = pygame.transform.scale(ocean, (SCREEN_WIDTH, view_h))
            except Exception:
                pass
        self.screen.blit(ocean, (0, 0))

        for i, prov in enumerate(self.provinces):
            xs = [p[0] for p in prov.polygon]
            ys = [p[1] for p in prov.polygon]
            min_x, min_y = min(xs), min(ys)
            tex = self.tex_manager.get_province_texture(
                i, prov.polygon, prov.owner, prov.region_type,
                SCREEN_WIDTH, SCREEN_HEIGHT
            )
            stex = self._get_scaled_tex(i, tex)
            sx = int((min_x - self.cam_x) * self.zoom - 4 * self.zoom)
            sy = int((min_y - self.cam_y) * self.zoom - 4 * self.zoom)
            self.screen.blit(stex, (sx, sy))

            screen_poly = [self._world_to_screen(x, y) for x, y in prov.polygon]
            border_col = self._border_color(i, prov)
            try:
                pygame.draw.polygon(self.screen, border_col, screen_poly, max(1, int(2 * self.zoom)))
            except Exception:
                pass
            if i == self._hover_province:
                try:
                    pygame.draw.polygon(self.screen, (255, 250, 220), screen_poly, max(1, int(1 * self.zoom)))
                except Exception:
                    pass

        self._render_rivers()
        self._render_city_labels()

        for general in self.generals:
            self._render_general(general)

        if self.selected_general:
            g_idx = self.selected_general.province_idx
            adj = self._adjacent_provinces(g_idx)
            for ai in adj:
                prov = self.provinces[ai]
                cx, cy = prov.centroid
                sx, sy = self._world_to_screen(cx, cy)
                pulse = abs(math.sin(pygame.time.get_ticks() * 0.004)) * 0.4 + 0.6
                col = (int(255 * pulse), int(255 * pulse), int(80 * pulse))
                try:
                    pygame.draw.circle(self.screen, col, (sx, sy), int(22 * self.zoom), 2)
                except Exception:
                    pass

        self._render_hud()

        if self._show_diplomacy:
            self._render_diplomacy_panel()

        if self._show_ownership:
            self._render_ownership_panel()

        if self._battle_result:
            self._render_overlay_text(self._battle_result)

        if self._message:
            self._render_overlay_text(self._message)

        if self._game_over:
            self._render_game_over()

        pygame.display.flip()

    def _render_city_labels(self):
        # подписи как на референсе: точка + serif-название
        from world_data import RegionType
        for i, prov in enumerate(self.provinces):
            cx, cy = prov.centroid
            sx, sy = self._world_to_screen(cx, cy)
            if sx < -100 or sx > SCREEN_WIDTH + 100 or sy < -50 or sy > SCREEN_HEIGHT:
                continue
            is_city = prov.region_type in (RegionType.CITY, RegionType.CAPITAL)
            if not is_city and self.zoom < 1.2 and i != self._hover_province:
                continue
            font = self.font_city if is_city else self.font_city_small
            # точка города
            if is_city:
                pygame.draw.circle(self.screen, (20, 18, 12), (sx, sy), 5)
                pygame.draw.circle(self.screen, (240, 235, 215), (sx, sy), 4)
                pygame.draw.circle(self.screen, (20, 18, 12), (sx, sy), 2)
            name = prov.name
            # тень + светлый текст (строки из кэша — подписи не меняются)
            shadow = self._cached_text(font, name, (25, 22, 12))
            text = self._cached_text(font, name, (242, 236, 214))
            self.screen.blit(shadow, (sx + 8 + 1, sy - 12 + 1))
            self.screen.blit(text, (sx + 8, sy - 12))

    def _render_rivers(self):
        t = pygame.time.get_ticks()

        for river_x in [RIVER_WEST_X, RIVER_EAST_X]:
            RiverRenderer.draw_river(self.screen, river_x, self.cam_x, self.cam_y,
                                     SCREEN_HEIGHT, t, zoom=self.zoom)

            bridge_indices = []
            for a, b in BRIDGE_CONNECTIONS:
                pa = self.provinces[a]
                pb = self.provinces[b]
                cx_a, cy_a = pa.centroid
                cx_b, cy_b = pb.centroid
                if abs(cx_a - river_x) < 60 or abs(cx_b - river_x) < 60:
                    bridge_y = (cy_a + cy_b) // 2
                    bridge_indices.append(bridge_y)

            for by in bridge_indices:
                RiverRenderer.draw_bridge(self.screen, river_x, by, self.cam_x, self.cam_y, zoom=self.zoom)

    def _render_general(self, general: General):
        prov = self.provinces[general.province_idx]
        cx, cy = prov.centroid
        # флаг чуть выше центра, чтобы не закрывать подпись города
        cy -= 18
        x, y = self._world_to_screen(cx, cy)

        if x < -60 or x > SCREEN_WIDTH + 60 or y < -60 or y > SCREEN_HEIGHT + 60:
            return

        nation = WORLD_NATIONS.get(general.nation)
        color = nation.color if nation else (150, 150, 150)

        is_selected = general is self.selected_general
        GeneralIcon.draw_banner(self.screen, int(x), int(y), color,
                                selected=is_selected, moved=general.moved,
                                scale=self.zoom,
                                label=f"{general.name} {general.troops}")

    def _render_hud(self):
        hud_y = SCREEN_HEIGHT - 80
        pygame.draw.rect(self.screen, COLOR_HUD_BG, (0, hud_y, SCREEN_WIDTH, 80))

        turn_text = self._cached_text(
            self.font_hud,
            f"Turn: {self._turn} | LMB/RMB: select+move | Wheel:+/-: zoom | WASD: pan | SPACE: turn | TAB: dipl | V: holdings | 0: reset",
            COLOR_HUD_TEXT
        )
        self.screen.blit(turn_text, (12, hud_y + 4))
        # тултип ховера
        if self._hover_province is not None:
            lines = self._hover_tip_lines(self._hover_province)
            tips = [self._cached_text(self.font_hud, t, (245, 238, 218)) for t in lines]
            tw = max(t.get_width() for t in tips)
            th = sum(t.get_height() for t in tips)
            tx = min(max(self._mouse_pos[0] + 14, 4), SCREEN_WIDTH - tw - 8)
            ty = max(self._mouse_pos[1] - 22, 4)
            bg = pygame.Surface((tw + 8, th + 4), pygame.SRCALPHA)
            bg.fill((20, 18, 12, 200))
            self.screen.blit(bg, (tx - 4, ty - 2))
            cy = ty
            for t in tips:
                self.screen.blit(t, (tx, cy))
                cy += t.get_height()

        nation = WORLD_NATIONS[PLAYER_NATION]
        info = self._cached_text(
            self.font_hud,
            f"{nation.name} | Gold: {nation.gold}",
            nation.color
        )
        self.screen.blit(info, (12, hud_y + 22))

        generals_info = [f"{g.name}({g.troops})" for g in self.generals
                         if g.nation == PLAYER_NATION]
        gen_text = self._cached_text(
            self.font_hud,
            f"Generals: {', '.join(generals_info)}",
            COLOR_HUD_TEXT_DIM
        )
        self.screen.blit(gen_text, (12, hud_y + 40))

        provinces_count = {}
        for p in self.provinces:
            provinces_count[p.owner] = provinces_count.get(p.owner, 0) + 1
        rx = SCREEN_WIDTH - 12
        for nation_key in ["red", "blue", "green"]:
            count = provinces_count.get(nation_key, 0)
            n = WORLD_NATIONS[nation_key]
            rt = self._cached_text(self.font_hud, f"{n.name}: {count}", n.color)
            rx -= rt.get_width() + 16
            self.screen.blit(rt, (rx, hud_y + 4))

        if self.selected_general:
            sel = self.selected_general
            adj = self._adjacent_provinces(sel.province_idx)
            adj_names = [self.provinces[i].name[:8] for i in adj[:5]]
            sel_text = self._cached_text(
                self.font_hud,
                f"Selected: {sel.name} | Adjacent: {', '.join(adj_names)}",
                COLOR_GENERAL_SELECTED
            )
            self.screen.blit(sel_text, (SCREEN_WIDTH // 2 - sel_text.get_width() // 2, hud_y + 60))

    def _hover_tip_lines(self, idx: int) -> List[str]:
        """Строки тултипа провинции. Первая строка — старая, без изменений."""
        prov = self.provinces[idx]
        lines = [f"{prov.name} [{prov.owner}] troops:{prov.troops}"]

        duchy_id = getattr(prov, "duchy_id", None)
        if duchy_id:
            duchy = self.hierarchy.duchies.get(duchy_id)
            duchy_name = duchy.name if duchy else duchy_id
            holder = self.hierarchy.holder_of_duchy(duchy_id)
            if holder is not None:
                lines.append(f"{duchy_name}: {holder.name} ({holder.rank.value})")
            else:
                lines.append(f"{duchy_name}: без держателя")

        lines.append(
            f"hearths:{getattr(prov, 'hearths', 0)} "
            f"loy:{getattr(prov, 'loyalty', 0)} "
            f"gar:{getattr(prov, 'garrison', 0)}"
        )
        return lines

    def _realm_of_nation(self, nation: str):
        """Королевство нации, если оно есть в иерархии."""
        for realm in self.hierarchy.realms.values():
            if realm.nation == nation:
                return realm
        return None

    def _duchies_of_nation(self, nation: str) -> List:
        """Герцогства, реально принадлежащие нации (de facto, не de jure)."""
        cached = self._turn_cached((_TC_DUCHIES, nation),
                                   lambda: self._scan_duchies_of_nation(nation))
        return list(cached)

    def _scan_duchies_of_nation(self, nation: str) -> Tuple:
        """Собственно поиск владений нации — вызывается один раз на ход."""
        owned = {i for i, p in enumerate(self.provinces) if p.owner == nation}
        out = []
        for duchy in sorted(self.hierarchy.duchies.values(), key=lambda d: d.name):
            if owned & set(duchy.de_jure_provinces):
                out.append(duchy)
        return tuple(out)

    def _vassals_of_nation(self, nation: str) -> List:
        """Живые персонажи нации: король, потом герцоги, потом бароны.

        Внутри ранга сортировка по id, чтобы порядок был детерминированным
        и курсор по списку не прыгал между перерисовками.
        """
        cached = self._turn_cached((_TC_VASSALS, nation),
                                   lambda: self._scan_vassals_of_nation(nation))
        return list(cached)

    def _scan_vassals_of_nation(self, nation: str) -> Tuple:
        """Собственный поиск персонажей нации — вызывается один раз на ход."""
        out = [ch for ch in self.hierarchy.characters.values()
               if ch.nation == nation and ch.alive]
        out.sort(key=lambda ch: (_RANK_ORDER.get(ch.rank, 9), ch.id))
        return tuple(out)

    def _panel_layout_get(self) -> Dict:
        """Раскладка панели владений (с кэшем на ход).

        Кэш живёт до _invalidate_panel(), как и сама картинка. Повторный
        запрос ничего не считает, поэтому хит-тест мыши дёшево.
        """
        lay = self._panel_layout
        if lay is not None and self._panel_layout_turn == self._turn:
            return lay
        lay = self._build_panel_layout()
        self._panel_layout = lay
        self._panel_layout_turn = self._turn
        return lay

    def _build_panel_layout(self) -> Dict:
        """Раскладка панели в экранных координатах — единственный источник геометрии.

        Словарь на выходе:
        ``panel``       — прямоугольник панели на экране;
        ``title``       — заголовок, ``nation`` — строка нации;
        ``realm``       — шапка королевства или None;
        ``duchies``     — строки герцогств, ``contracts`` — строки контрактов;
        ``counties``    — строки графств (province_idx);
        ``vassals``     — правый столбец: живые персонажи нации (char_id);
        ``vassal_box``  — прямоугольник всего правого столбца;
        ``hint``        — строка подсказки, ``notes`` — служебные пояснения.

        Каждая строка — это dict с ключами ``kind`` (``realm``/``duchy``/
        ``contract``/``county``/``vassal``), ``rect`` (экранный прямоугольник),
        ``text``, ``color``, ``font`` и идентификатором: ``char_id`` персонажа,
        ``duchy_id`` герцогства, ``county_idx`` провинции, ``index`` для
        строки персонажей. Одну и ту же раскладку читают и отрисовка, и
        _panel_hit, поэтому клик по строке попадает ровно туда же, куда нарисовано.
        """
        px = SCREEN_WIDTH // 2 - _PANEL_W // 2
        py = SCREEN_HEIGHT // 2 - _PANEL_H // 2

        def R(x: int, y: int, w: int, h: int) -> pygame.Rect:
            """Локальный прямоугольник панели -> экранный."""
            return pygame.Rect(px + x, py + y, w, h)

        nation = self._ownership_nation
        nation_obj = WORLD_NATIONS.get(nation)
        realm = self._realm_of_nation(nation)
        nation_color = nation_obj.color if nation_obj else COLOR_WHITE
        # приказы королю имеет смысл отдавать только своей нации: дерево чужих
        # держав читается, но персонажи в нём некликабельны (см. selectable)
        own = self._panel_allows_orders()

        lay: Dict = {
            "origin": (px, py),
            "panel": R(0, 0, _PANEL_W, _PANEL_H),
            "title": R(0, 8, _PANEL_W, 20),
            "nation": R(_PANEL_PAD, 42, _PANEL_TREE_W, _PANEL_LINE_H),
            "divider": R(_PANEL_COL2_X - _PANEL_PAD, _PANEL_TREE_Y - 6, 1,
                         _PANEL_MAX_Y - _PANEL_TREE_Y),
            "vassal_box": R(_PANEL_COL2_X, _PANEL_TREE_Y, _PANEL_COL2_W, 0),
            "vassal_head": {
                "kind": "vassal_head",
                "rect": R(_PANEL_COL2_X, _PANEL_TREE_Y, _PANEL_COL2_W, _PANEL_LINE_H),
                "text": "COURT", "color": (220, 200, 160), "font": self.font_small,
            },
            "hint": {
                "kind": "hint",
                "rect": R(_PANEL_PAD, _PANEL_HINT_Y, _PANEL_TREE_W, _PANEL_ROW_H + 2),
                "text": "Q/E/Left/Right: nation | Up/Down: court | V: close",
                "color": (170, 155, 130), "font": self.font_small,
            },
            "realm": None,
            "duchies": [],
            "contracts": [],
            "counties": [],
            "vassals": [],
            "notes": [],
        }

        x = _PANEL_PAD
        y = _PANEL_TREE_Y
        line_h = _PANEL_LINE_H
        max_y = _PANEL_MAX_Y

        if realm is None:
            lay["notes"].append({
                "kind": "note", "rect": R(x, y, _PANEL_TREE_W, line_h),
                "text": "Королевство не учтено", "color": COLOR_HUD_TEXT_DIM,
                "font": self.font_hud,
            })
        else:
            ruler = self.hierarchy.characters.get(realm.ruler_id)
            ruler_name = ruler.name if ruler else "—"
            lay["realm"] = {
                "kind": "realm", "rect": R(x, y, _PANEL_TREE_W, line_h),
                "realm_id": realm.id, "duchy_id": None, "county_idx": None,
                "char_id": None, "index": None,
                "text": f"{realm.name}  gold:{realm.gold}  prestige:{realm.prestige}  "
                        f"stability:{realm.stability}  crown:{realm.crown_authority}  "
                        f"({ruler_name})",
                "color": nation_color, "font": self.font_hud,
            }
            y += line_h + 2

            duchies = self._duchies_of_nation(nation)
            if not duchies:
                lay["notes"].append({
                    "kind": "note", "rect": R(x + 14, y, _PANEL_TREE_W - 14, line_h),
                    "text": "нет владений", "color": COLOR_HUD_TEXT_DIM,
                    "font": self.font_small,
                })
                y += line_h
            for duchy in duchies:
                if y > max_y:
                    break
                holder = self._holder_of_duchy(duchy.id)
                if holder is None:
                    holder_text = "без держателя"
                else:
                    holder_text = f"{holder.name}, {holder.rank.value}"
                lay["duchies"].append({
                    "kind": "duchy", "rect": R(x + 14, y, _PANEL_TREE_W - 14, line_h),
                    "duchy_id": duchy.id, "county_idx": None, "index": None,
                    "char_id": holder.id if holder is not None else None,
                    "selectable": own,
                    "text": f"└ Duchy {duchy.name} ({holder_text}) "
                            f"income:{self._duchy_income(duchy.id)} "
                            f"levy:{self._duchy_levy(duchy.id)}",
                    "color": (205, 190, 155), "font": self.font_hud,
                })
                y += line_h

                # контракт и мнение персонажа, если они есть
                if holder is not None:
                    contract = self._contract_of(holder.id)
                    if contract is not None:
                        spec = CONTRACT_LEVELS[contract.level]
                        lay["contracts"].append({
                            "kind": "contract", "rect": R(x + 28, y, _PANEL_TREE_W - 28,
                                                          line_h - 2),
                            "duchy_id": duchy.id, "county_idx": None, "index": None,
                            "char_id": holder.id, "selectable": own,
                            "text": f"   contract: {spec['name']} tax{spec['tax']}%/"
                                    f"levy{spec['levy']}% "
                                    f"opinion:{holder.opinion_of_liege} "
                                    f"loyalty:{holder.loyalty}",
                            "color": (170, 155, 130), "font": self.font_small,
                        })
                        y += line_h - 2

                for i in self.hierarchy.counties_of_duchy(duchy.id):
                    if y > max_y:
                        break
                    prov = self.provinces[i]
                    col = (150, 200, 150) if prov.owner == nation else COLOR_HUD_TEXT_DIM
                    lay["counties"].append({
                        "kind": "county", "rect": R(x + 28, y, _PANEL_TREE_W - 28,
                                                     line_h - 3),
                        "county_idx": i, "duchy_id": duchy.id, "char_id": None,
                        "index": None, "selectable": True,
                        "text": f"├ #{i} {prov.name}  owner:{prov.owner} "
                                f"hearths:{getattr(prov, 'hearths', 0)} "
                                f"inc:{self._county_income(i)} "
                                f"loy:{getattr(prov, 'loyalty', 0)} "
                                f"gar:{getattr(prov, 'garrison', 0)}",
                        "color": col, "font": self.font_small,
                    })
                    y += line_h - 3

        # правый столбец: живые персонажи нации. Персонажи чужой державы
        # показываются тусклыми и выбирать их нельзя
        palette = _VASSAL_COLOR if own else _VASSAL_COLOR_FOREIGN
        if not own:
            lay["vassal_head"]["text"] = "COURT (только чтение)"
            lay["vassal_head"]["color"] = COLOR_HUD_TEXT_DIM
        vy = _PANEL_TREE_Y + line_h + 2
        for i, ch in enumerate(self._vassals_of_nation(nation)):
            if vy > max_y:
                break
            lay["vassals"].append({
                "kind": "vassal", "rect": R(_PANEL_COL2_X, vy, _PANEL_COL2_W, _PANEL_ROW_H),
                "char_id": ch.id, "duchy_id": ch.duchy_id, "county_idx": ch.province_idx,
                "index": i, "rank": ch.rank.value, "selectable": own,
                # слева от имени место под маркер курсора
                "text": f"  {ch.name} ({ch.rank.value}) loy:{ch.loyalty} "
                        f"op:{ch.opinion_of_liege}",
                "color": palette.get(ch.rank, (180, 170, 145)),
                "font": self.font_small,
            })
            vy += _PANEL_ROW_H
        lay["vassal_box"] = R(_PANEL_COL2_X, _PANEL_TREE_Y, _PANEL_COL2_W,
                              max(0, vy - _PANEL_TREE_Y))
        return lay

    def _panel_hit(self, mx: int, my: int) -> Optional[Dict]:
        """Что под курсором в панели владений.

        None — курсор мимо панели, событие можно отдавать карте. Иначе строка
        (dict с kind/rect/идентификатором) либо kind="vassal_box"/"panel" для
        пустого места внутри панели. Панель занимает середину экрана, а
        фильтр кликов смотрит только на нижнюю полосу HUD, поэтому без этой
        проверки клик по строке уезжал бы в _handle_map_click и выбирал
        генерала, оказавшегося под панелью.
        """
        if not self._show_ownership:
            return None
        lay = self._panel_layout_get()
        if not lay["panel"].collidepoint(mx, my):
            return None
        # строки не пересекаются, порядок групп неважен
        for key in ("vassals", "counties", "contracts", "duchies"):
            for row in lay[key]:
                if row["rect"].collidepoint(mx, my):
                    return row
        realm = lay["realm"]
        if realm is not None and realm["rect"].collidepoint(mx, my):
            return realm
        box = lay["vassal_box"]
        if box.collidepoint(mx, my):
            return {"kind": "vassal_box", "rect": box.copy()}
        return {"kind": "panel", "rect": lay["panel"].copy()}

    def _handle_panel_click(self, mx: int, my: int):
        """Клик по панели владений: пока только выбор и подсветка строки.

        Персонаж выбирается только у своей нации: дерево чужих держав
        показывается, но строки в нём не активируются. Это защита от ошибки
        следующего этапа, где у короля появятся приказы — приказ чужому
        вассалу отдать уже не получится.
        """
        hit = self._panel_hit(mx, my)
        if hit is None:
            return
        kind = hit.get("kind")
        if kind in ("vassal", "duchy", "contract"):
            char_id = hit.get("char_id")
            # selectable = False у чужой нации: строка видна, но не выбирается
            if not char_id or not hit.get("selectable"):
                return
            if hit.get("index") is not None:
                self._vassal_cursor = hit["index"]
            self._sel_character_id = char_id
            self._sel_county_idx = None
            self._own_mode = "browse"
        elif kind == "county":
            self._sel_county_idx = hit.get("county_idx")
            self._sel_character_id = None
            self._own_mode = "browse"
        else:
            # пустое место панели — снять выбор
            self._sel_character_id = None
            self._sel_county_idx = None
            self._own_mode = "browse"
        self._invalidate_panel()

    def _render_ownership_panel(self):
        """Панель владений: Kingdom -> Duchy -> County + список персонажей.

        Панель статична между ходами, поэтому она рисуется в свою поверхность
        один раз и дальше только копируется на экран одним блитом. Геометрия
        берётся из _panel_layout — той же, что использует _panel_hit.
        """
        self.screen.blit(self._dim_surface, (0, 0))

        # Панель перерисовывается либо по флажку (сменились данные владений),
        # либо если разошлось состояние: ход, нация, выделение на карте или
        # выбор в панели. Проверка состояния страхует от забытого сброса.
        prev = self._panel_state
        if (self._panel_dirty or prev is None
                or prev[0] != self._turn
                or prev[1] != self._ownership_nation
                or prev[2] is not self.selected_general
                or prev[3] != self._sel_character_id
                or prev[4] != self._sel_county_idx
                or prev[5] != self._vassal_cursor
                or prev[6] != self._own_mode):
            self._paint_ownership_panel()
            self._panel_dirty = False
            self._panel_state = (self._turn, self._ownership_nation, self.selected_general,
                                 self._sel_character_id, self._sel_county_idx,
                                 self._vassal_cursor, self._own_mode)

        px, py = self._panel_layout_get()["origin"]
        self.screen.blit(self._panel_surface, (px, py))

    def _paint_ownership_panel(self):
        """Отрисовка панели владений в _panel_surface (координаты локальные).

        Раскладка строк берётся из _panel_layout, поэтому нарисованное и
        проверяемое кликом всегда совпадают.
        """
        surface = self._panel_surface
        pw, ph = _PANEL_W, _PANEL_H
        lay = self._panel_layout_get()
        ox, oy = lay["origin"]
        surface.fill((0, 0, 0, 0))

        pygame.draw.rect(surface, (40, 35, 30), (0, 0, pw, ph), border_radius=8)
        pygame.draw.rect(surface, COLOR_WHITE, (0, 0, pw, ph), 2, border_radius=8)
        pygame.draw.rect(surface, (90, 80, 66), lay["divider"].move(-ox, -oy))

        title = self._cached_text(self.font_title, "OWNERSHIP", (220, 200, 160))
        surface.blit(title, (pw // 2 - title.get_width() // 2, 10))

        nation_obj = WORLD_NATIONS.get(self._ownership_nation)
        if nation_obj is not None:
            label = self._cached_text(self.font_hud, f"Nation: {nation_obj.name}",
                                      nation_obj.color)
            surface.blit(label, lay["nation"].move(-ox, -oy).topleft)

        # служебные пояснения («нет владений» и т.п.) — не строки выбора
        for note in lay["notes"]:
            self._blit_panel_text(surface, note, ox, oy)

        if lay["realm"] is not None:
            self._blit_panel_text(surface, lay["realm"], ox, oy)

        head = lay["vassal_head"]
        surface.blit(self._cached_text(head["font"], head["text"], head["color"]),
                     head["rect"].move(-ox, -oy).topleft)

        for group in (lay["duchies"], lay["contracts"], lay["counties"], lay["vassals"]):
            for row in group:
                local = row["rect"].move(-ox, -oy)
                if row["kind"] == "vassal" and row.get("index") == self._vassal_cursor:
                    mark = _PANEL_SEL_BORDER if row.get("selectable") else (120, 112, 96)
                    surface.blit(self._cached_text(self.font_small, ">", mark),
                                 local.topleft)
                if self._panel_row_selected(row):
                    hl = pygame.Surface(local.size, pygame.SRCALPHA)
                    hl.fill(_PANEL_SEL_FILL)
                    surface.blit(hl, local.topleft)
                    pygame.draw.rect(surface, _PANEL_SEL_BORDER, local, 1)
                self._blit_panel_text(surface, row, ox, oy)

        hint = lay["hint"]
        surface.blit(self._cached_text(hint["font"], hint["text"], hint["color"]),
                     hint["rect"].move(-ox, -oy).topleft)

    def _panel_row_selected(self, row) -> bool:
        """Отмечена ли строка панели текущим выбором.

        По персонажу отмечаются все строки, где он встречается (строка
        герцогства, контракт и строка двора): выбор одного и того же лица
        должен выглядеть одинаково в обеих колонках.
        """
        if row["kind"] == "county":
            return self._sel_county_idx is not None and \
                self._sel_county_idx == row["county_idx"]
        char_id = row.get("char_id")
        return char_id is not None and self._sel_character_id == char_id

    def _blit_panel_text(self, surface, row, ox: int, oy: int):
        """Текст строки панели из кэша шрифтов — с учётом выделения."""
        color = row["color"]
        if self._panel_row_selected(row):
            color = _PANEL_SEL_TEXT
        text = self._cached_text(row["font"], row["text"], color)
        surface.blit(text, row["rect"].move(-ox, -oy).topleft)


    def _render_diplomacy_panel(self):
        self.screen.blit(self._dim_surface, (0, 0))

        pw, ph = 450, 320
        px = SCREEN_WIDTH // 2 - pw // 2
        py = SCREEN_HEIGHT // 2 - ph // 2
        pygame.draw.rect(self.screen, (40, 35, 30), (px, py, pw, ph), border_radius=8)
        pygame.draw.rect(self.screen, COLOR_WHITE, (px, py, pw, ph), 2, border_radius=8)

        title = self._cached_text(self.font_title, "DIPLOMACY", (220, 200, 160))
        self.screen.blit(title, (px + pw // 2 - title.get_width() // 2, py + 10))

        if self._diplomacy_target:
            target_nation = WORLD_NATIONS[self._diplomacy_target]
            current = self.diplomacy.get_relation(PLAYER_NATION, self._diplomacy_target)
            rel_name = self.diplomacy.get_relation_name(PLAYER_NATION, self._diplomacy_target)
            rel_color = self.diplomacy.get_relation_color(PLAYER_NATION, self._diplomacy_target)

            target_text = self._cached_text(
                self.font_hud, f"Target: {target_nation.name}", target_nation.color
            )
            self.screen.blit(target_text, (px + 20, py + 45))

            current_text = self._cached_text(
                self.font_hud, f"Current: {rel_name}", rel_color
            )
            self.screen.blit(current_text, (px + 20, py + 68))

            actions = [
                ("1", "Declare WAR", (200, 60, 60)),
                ("2", "Propose NEUTRAL", (180, 170, 150)),
                ("3", "Propose FRIENDLY", (80, 180, 80)),
                ("4", "Propose ALLIANCE", (60, 120, 220)),
            ]
            for i, (key, text, color) in enumerate(actions):
                ay = py + 100 + i * 32
                key_text = self._cached_text(self.font_hud, f"[{key}]", COLOR_HUD_TEXT_DIM)
                act_text = self._cached_text(self.font_hud, text, color)
                self.screen.blit(key_text, (px + 30, ay))
                self.screen.blit(act_text, (px + 70, ay))
        else:
            no_target = self._cached_text(self.font_hud, "Press N/P to select target",
                                          COLOR_HUD_TEXT_DIM)
            self.screen.blit(no_target, (px + 20, py + 55))

        hint = self._cached_text(self.font_small,
                                 "N: next | P: prev | 1-4: action | ESC: close",
                                 (170, 155, 130))
        self.screen.blit(hint, (px + 20, py + ph - 25))

    def _render_overlay_text(self, text: str):
        self.screen.blit(self._dim_surface_soft, (0, 0))

        rendered = self._cached_text(self.font_title, text, COLOR_WHITE)
        tx = SCREEN_WIDTH // 2 - rendered.get_width() // 2
        ty = 30
        bg = pygame.Surface((rendered.get_width() + 20, rendered.get_height() + 10), pygame.SRCALPHA)
        bg.fill((0, 0, 0, 180))
        self.screen.blit(bg, (tx - 10, ty - 5))
        self.screen.blit(rendered, (tx, ty))

    def _render_game_over(self):
        self.screen.blit(self._dim_surface_strong, (0, 0))

        color = COLOR_GENERAL_MOVABLE if self._winner == "VICTORY" else (200, 60, 60)
        text = self._cached_text(self.font_title, self._winner, color)
        tx = SCREEN_WIDTH // 2 - text.get_width() // 2
        ty = SCREEN_HEIGHT // 2 - text.get_height() // 2
        self.screen.blit(text, (tx, ty))

        hint = self._cached_text(self.font_hud, "Press ESC to quit", COLOR_WHITE)
        self.screen.blit(hint, (SCREEN_WIDTH // 2 - hint.get_width() // 2, ty + 40))
