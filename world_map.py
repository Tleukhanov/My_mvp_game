import pygame
import sys
import math
from typing import Optional, List, Tuple, Dict
from sim.rng import NamedStreams, new_streams
from war import (
    WarSession, WORLD_BATTLE_STREAM, WORLD_BATTLE_SALT_BASE,
    WORLD_SESSION_SALT_BASE, WORLD_STREAM_SEED,
    quality_from_roll, apply_deltas_to_screen,
)
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
from textures import (TextureManager, GeneralIcon, RiverRenderer, LandMask,
                     build_map_frame, land_surface, zoomed_surface,
                     display_ready)
from states import (
    build_default_hierarchy, TitleRank, CONTRACT_LEVELS,
    # приказы (этап 1.2 в states.py) — правила и статусы
    OrderKind, OrderStatus, COMMAND_MIN_RANK,
    ORDERS_ISSUED_PER_TURN, ORDER_DEADLINE_TURNS, REFUSED_WEIGHT, order_weight,
    # цены и потолки трат: в интерфейсе НИ ОДНОГО числа не хардкодится,
    # всё берётся отсюда, иначе UI разъедется с правилами после правки
    GIFT_COST, GIFT_OPINION_BY_COUNT, GIFT_LOYALTY_BY_COUNT, gift_gain,
    COUNCIL_INFLUENCE, COUNCIL_LOYALTY,
    LEVY_COST_PER_BLOCK, LEVY_BLOCK_TROOPS,
    DEV_COST_BASE, DEV_COST_STEP, DEVELOPMENT_MAX, development_upgrade_cost,
    CROWN_COST, CROWN_PRESTIGE_COST, MAX_CROWN_AUTHORITY,
    MERC_COST_PER_BLOCK, MERC_BLOCK_TROOPS, MERC_MAX_BLOCKS_PER_TURN,
    GARRISON_RECRUIT_COST_PER_100, GARRISON_CAP_PER_FORT,
    TAX_POLICY_MIN, TAX_POLICY_MAX, TAX_POLICY_CROWN_AUTHORITY,
)

# Базовые цвета границ по владельцу. Вынесены на уровень модуля, чтобы
# палитру ранга можно было применять поверх, не трогая саму карту.
OWNER_BORDER = {
    "neutral": (195, 180, 140),
    "red": (185, 90, 75),
    "blue": (95, 135, 205),
    "green": (95, 175, 105),
}

# Границы владений по толщине и контрасту. Раньше все провинции обводились
# одной и той же линией в цвет владельца, и по карте было нельзя понять,
# где своя территория, а где чужая, — приходилось читать цвет заливки.
# Теперь толщина и вид несут смысл, а цвет только подсказывает, чья это
# граница.
#: Шов внутри одной нации: тонкая чернильная линия. Бледная линия на
#: оливковом фоне читалась как царапина, а не как граница провинции —
#: особенно на длинных горизонтальных швах между рядами, которые тянулись
#: через полкарты.
BORDER_INTERNAL = (34, 30, 18, 170)
#: Нейтральная земля: то же, но пунктиром и чуть жирнее. Видна, но не
#: выглядит захваченной — раньше нейтральные провинции не отличались от
#: своих.
BORDER_NEUTRAL = (52, 46, 30, 215)
#: Между державами: жирная тёмная краска плюс светлая сердцевина. Сердцевина
#: не цветом державы, а костяной: смесь цветов двух соседей симметрична,
#: поэтому шов смотрится одинаково с обеих сторон и не «прыгает», когда доли
#: соседей меняются местами.
BORDER_FOREIGN_INK = (30, 26, 17, 240)
BORDER_FOREIGN_CORE = (226, 214, 176, 205)

#: Плёнка владения поверх рельефа — RGBA на державу. Цвета НЕ приглушены:
#: смешивание с поверхностью работает только добавлением, поэтому приглушённый
#: синий на хаки-фоне даёт серо-голубой, а не синий, и державы переставали
#: отличаться друг от друга.
#:
#: Плотность у каждой своя, и это не украшение: синий — самый «холодный» цвет
#: по отношению к оливково-хаки под ним, и ему нужно больше доли, чтобы вообще
#: стать синим. Красный и зелёный от приглушённой плёнки только сереют.
OWNER_PAINT = {
    "neutral": None,
    "blue": (26, 104, 255, 108),
    "red": (240, 34, 22, 92),
    "green": (46, 214, 78, 92),
}

#: Ступени поселений. Индекс — уровень подписи: столица, город, деревня.
#: Заодно это порядок приоритета при наложении подписей.
_PLACE_TIERS = {RegionType.CAPITAL: 0, RegionType.CITY: 1, RegionType.VILLAGE: 2}
#: Радиус кружка поселения, px. Тот же порядок, что и у шрифта.
_PLACE_RADIUS = (8, 5, 3)
#: Подпись — светлый шрифт с тёмной обводкой, как на референсе. Раньше было
#: наоборот (тёмный шрифт, светлая обводка), и на среднем тоне рельефа
#: подпись выглядела меловой чертой, а не как надпись на карте.
_PLACE_INK = (240, 233, 212)
_PLACE_HALO = (24, 20, 13)
#: Ниже этого зума деревни не подписываются: на 0.6 все 50 названий
#: сливаются в мелкую рябь и мешают читать города.
_PLACE_VILLAGE_MIN_ZOOM = 1.0
#: Границы подписи: сколько места она может занимать и сколько ей нужно,
#: чтобы вообще что-то сказать. Порог считается от кегля: обрезанное до
#: двух-трёх букв название («Sta…») читается хуже, чем отсутствие названия,
#: поэтому такую подпись не рисуем вовсе — кружок на месте.
_PLACE_LABEL_MAX_W = 220
_PLACE_LABEL_MIN_W = 44
_PLACE_LABEL_MIN_CHARS_PER_LINE = 3.5
#: Запас вокруг силуэта суши под тень и обводку берега, в мировых px.
_FRAME_PAD = 6

#: Сторона клетки сетки занятых прямоугольников подписей.
_LABEL_GRID_CELL = 64


class _RectGrid:
    """Кто уже занял место на карте — сеткой клеток, а не перебором всех.

    Проверка «подпись ни на что не налезает» сама по себе копеечная, но при
    50 подписях против 66 занятых прямоугольников это 3300 вызовов
    ``colliderect`` на кадр, и третья по стоимости статья рендера после
    блитов и рек. Сетка отсекает почти всё: у подписи проверяются только
    клетки, которые она правда перекрывает.
    """

    __slots__ = ("cell", "buckets")

    def __init__(self, cell: int = _LABEL_GRID_CELL):
        self.cell = cell
        self.buckets: Dict[Tuple[int, int], List[pygame.Rect]] = {}

    def add(self, rect: pygame.Rect) -> None:
        c = self.cell
        for gy in range(rect.top // c, (rect.bottom - 1) // c + 1):
            for gx in range(rect.left // c, (rect.right - 1) // c + 1):
                self.buckets.setdefault((gx, gy), []).append(rect)

    def hits(self, rect: pygame.Rect) -> bool:
        c = self.cell
        for gy in range(rect.top // c, (rect.bottom - 1) // c + 1):
            for gx in range(rect.left // c, (rect.right - 1) // c + 1):
                for other in self.buckets.get((gx, gy), ()):
                    if rect.colliderect(other):
                        return True
        return False


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

# Высота строки-кнопки (приказ, трата, кнопки графства). Равна шагу строки
# персонажей: шрифт строки — 12 px, и на 11 px текст прижимался к рамке.
MOVE_ORDER_STUCK_TURNS = 3
#: Ниже одного полка (100 солдат) армия считается разбитой: осколки не
#: держат провинцию и только бесконечно бьются в стену.
MIN_ARMY_TROOPS = 100
_PANEL_ACT_H = 13
# Отступ между блоками правого столбца (приказы под списком двора)
_PANEL_BLOCK_GAP = 8

# Цвета блока приказов и трат. Доступное действие — обычный тон панели,
# заблокированное (нет золота, потолок, лимит) — приглушённый серый: игрок
# видит недоступность ДО клика, а не по факту отказа.
_ACT_OK = (205, 195, 160)
_ACT_OFF = (118, 112, 100)
_ACT_HEAD = (220, 200, 160)
_ORDER_STATUS_COLOR = {
    OrderStatus.PENDING: (235, 215, 165),
    OrderStatus.ACCEPTED: (150, 205, 150),
    OrderStatus.REFUSED: (215, 110, 100),
    OrderStatus.FULFILLED: (150, 200, 210),
    OrderStatus.PUNISHED: (205, 130, 200),
}

# Подпись статуса приказа по-русски. states отдаёт английские .value, но весь
# остальной интерфейс панели русский, поэтому переводим здесь, а не в двух
# строках кода поперёк.
_ORDER_STATUS_TEXT = {
    OrderStatus.PENDING: "ждёт решения вассала",
    OrderStatus.ACCEPTED: "принят, ждёт исполнения",
    OrderStatus.REFUSED: "отказ",
    OrderStatus.FULFILLED: "исполнен",
    OrderStatus.PUNISHED: "наказан за неисполнение",
}

# Виды приказов в порядке блока «ПРИКАЗЫ». Порядок НЕ влияет на правила, он
# только разметка: тяжёлые (отзыв земли, левейс) вниз, чтобы верх панели
# показывал то, что нужно чаще всего.
_ORDER_ROWS: Tuple[Tuple[OrderKind, str], ...] = (
    (OrderKind.SUMMON_COUNCIL, "совет"),
    (OrderKind.GIFT, "подарок"),
    (OrderKind.SET_CONTRACT, "контракт+1"),
    (OrderKind.RAISE_LEVY, "левейс+1"),
    (OrderKind.GRANT_FIEF, "выдать землю"),
    (OrderKind.REVOKE_FIEF, "отозвать"),
    (OrderKind.DEVELOP_COUNTY, "застройка"),
)

# Привязка клавиш 1..4 в открытой панели. Выбор — четыре самых частых
# действия, и выбор этот не магический: это ровно те строки блока, у которых
# НЕТ обязательных аргументов от игрока (никакой «выбери графство» перед
# нажатием), поэтому действие выполняется сразу.
#
#   1 — ПОДАРОК: самый дешёвый рычаг на мнение и лояльность, вес приказа 1
#       (см. states.ORDER_WEIGHTS), поэтому его чаще всего исполняют, а не
#       отклоняют;
#   2 — СОВЕТ: тоже вес 1 и БЕСПЛАТЕН (states.COUNCIL_* — это прибавки, не
#       цена), то есть единственное действие без цены вообще;
#   3 — КОНТРАКТ+1: единственный приказ, который сам по себе даёт доход
#       (налог/левейс из states.CONTRACT_LEVELS), то есть платит самому себе;
#   4 — ЛЕВЕЙС+1: главная кнопка войны states.raise_levy, самая частая трата
#       казны после наема наёмников.
#
# Формат: (клавиша pygame, действие). Действие — "order:<OrderKind.value>"
# или "spend:<метод states>". Разбор строки — в _panel_run_action.
_PANEL_HOTKEYS: Tuple[Tuple[int, str], ...] = (
    (pygame.K_1, f"order:{OrderKind.GIFT.value}"),
    (pygame.K_2, f"order:{OrderKind.SUMMON_COUNCIL.value}"),
    (pygame.K_3, f"order:{OrderKind.SET_CONTRACT.value}"),
    (pygame.K_4, f"spend:{OrderKind.RAISE_LEVY.value}"),
)

# Траты королевства: шапка панели. Порядок как в _ORDER_ROWS — от дешёвого к
# дорогому. Числа цен берутся из states, здесь только имена действий, и они
# совпадают с именами методов states.Hierarchy — вызов идёт по этому же ключу.
_SPEND_ROWS: Tuple[Tuple[str, str], ...] = (
    ("raise_levy", "левейс"),
    ("raise_crown_authority", "корона"),
    ("hire_mercenaries", "наёмники"),
    ("set_tax_policy", "налог"),
)

# Траты графства: под строкой графства. Ключи — ветки обработчика, а не имена
# методов states: застройка и гарнизон бьют по ПРОВИНЦИИ, а не по королевству.
_COUNTY_SPEND_ROWS: Tuple[Tuple[str, str], ...] = (
    ("develop", "застройка"),
    ("garrison", "гарнизон"),
)

# Текст подсказки. Сам формат задан константой, чтобы длина строки не «поехала»
# вместе с содержимым: горячие клавиши и ESC-переходы дописываются к нему.
_PANEL_HINT_OWN = "Q/E нация · ↑↓ двор · 1-4 приказ · ESC снять выбор · V закрыть"
_PANEL_HINT_FOREIGN = "Q/E нация · ↑↓ двор · чужая держава: только чтение · V закрыть"

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
_TC_REALM_LEVY = "realm_levy"
_TC_FREE_COUNTY = "free_county"


class WorldMapScreen:
    def __init__(self, hierarchy=None, generals=None, streams=None):
        """Экран мировой карты.

        Три необязательных параметра — не украшение, а способ не терять мир
        между экранами. Раньше объект строился целиком заново при каждом
        входе в карту, и захваченные провинции, потраченное золото и левейс
        генералов начинали с нуля.

        * ``hierarchy`` — готовая иерархия владений (``states.Hierarchy``).
          Иерархия привязана к СВОЕМУ списку провинций, поэтому её можно
          передать только вместе с этим же экраном: ``main.py`` держит один
          объект карты и заходит на него снова после боя;
        * ``generals`` — готовый список генералов (с их левейсом);
        * ``streams`` — готовый набор именованных потоков ГПСЧ.

        Без аргументов поведение прежнее: карта строится с нуля. На этом
        построении завязан тест ``TestWorldMapInit``.
        """
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
        # Рамка выделения левой кнопкой (как в WC3): зажал и потянул — выделил
        # всё, что попало в прямоугольник. Порог в 6 px отделяет «рамка» от
        # «клик», иначе микросдвиг мыши при обычном клике сбрасывал бы выбор.
        self._lmb_down_pos: Optional[Tuple[int, int]] = None
        self._lmb_rect: Optional[pygame.Rect] = None
        self._SELECT_DRAG_PX = 6
        # Двойной клик по поселению выбирает всю гарнизон, а не одну армию:
        # иначе в провинции с тремя отрядами игрок кликает трижды в одну точку.
        self._last_click_ms = 0
        self._last_click_pos = (0, 0)
        self._DOUBLE_CLICK_MS = 350
        self._hover_province = None
        # Сколько подписей поселений реально легло на карту в последнем кадре.
        # Считается ради проверки «названия не молчат»: часть имён молчала,
        # и это было видно только по коду.
        self._label_blits = 0
        # Подписи поселений: три ступени, как на референсе. Раньше шрифтов
        # было два, и города со столицами печатались одним и тем же кеглем,
        # а деревни не подписывались вовсе — из 50 провинций игрок видел
        # несколько названий и не знал, что находится в остальных.
        # Кегли подняты до «карточных»: на референсе название столицы —
        # это заметная надпись, а не подпись 12 px, и при 1600 px ширины
        # экрана 27/18/13 читаются как имена, а не как штрих.
        try:
            self._place_fonts = (
                pygame.font.SysFont("serif", 27),
                pygame.font.SysFont("serif", 18),
                pygame.font.SysFont("serif", 13),
            )
        except Exception:
            self._place_fonts = (
                pygame.font.SysFont(None, 27),
                pygame.font.SysFont(None, 18),
                pygame.font.SysFont(None, 13),
            )

        self.diplomacy = DiplomacyManager()
        self.provinces: List[Province] = [Province(p.name, p.owner, p.region_type,
                                                    list(p.polygon), list(p.neighbors))
                                           for p in WORLD_PROVINCES]
        # иерархия владений поверх тех же провинций: графство = провинция,
        # поле owner не трогаем, чтобы старые механики и тесты не сломались
        self.hierarchy = hierarchy if hierarchy is not None \
            else build_default_hierarchy(self.provinces)
        for _realm in self.hierarchy.realms.values():
            _realm.is_player = (_realm.nation == PLAYER_NATION)

        if generals is not None:
            self.generals: List[General] = generals
        else:
            self.generals = [General(g.name, g.nation, g.province_idx, g.troops)
                             for g in WORLD_GENERALS]
            for orig, copy in zip(WORLD_GENERALS, self.generals):
                copy.health = orig.health

        self.connections: List[Tuple[int, int]] = list(PROVINCE_CONNECTIONS)
        self._build_connection_index()

        self.selected_general: Optional[General] = None
        #: Выделение армий. ``selected_general`` — всегда ПЕРВАЯ в этом списке
        #: (или ``None``), и именно к нему относятся все панели и подсказки.
        #: Остальные элементы работают только на приказы: рамкой выделяют
        #: группу, а правый клик ведёт её к цели, как в Warcraft 3.
        self.selected_generals: List[General] = []
        #: Отряды игрока, попавшие в рамку выделения: под номером 1..9 хранится
        #: состав (ссылки на армии), а не номер в списке.
        self._control_groups: Dict[int, List[General]] = {}
        #: Приказы движения: у каждой армии своя цель. Раньше приказ был один
        #: на весь экран, поэтому за ход можно было вести только одну армию,
        #: а остальные приходилось кликать по очереди — группа в один клик
        #: работать не могла. Каждый приказ выполняется по одному шагу за ход,
        #: и маршрут может быть длиннее одного соседства провинции.
        self._orders: List[Dict] = []
        #: Очередь приказов, накопленная Shift-правым кликом: приказ не
        #: отменяет предыдущий, а встаёт в конец. В Warcraft 3 Shift-клик
        #: именно так и добавляет действия в очередь.
        self._queued_orders: List[Dict] = []
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
        # последняя причина отказа от действия панели (приказ/трата). Показывается
        # под блоком, чтобы игрок видел не «клик ничего не сделал», а причину.
        # Обнуляется каждым успешным действием.
        self._panel_notice: Optional[str] = None
        self._game_over = False
        self._winner: Optional[str] = None
        self._message: Optional[str] = None
        self._message_timer = 0.0

        # ---- мост в тактический слой (war.py) ----
        # нации отданы наружу: war.py раздаёт добычу по этому же словарю
        self.nations = WORLD_NATIONS
        # именованные потоки ГПСЧ: ни одного глобального random на карте
        self.streams: NamedStreams = streams if streams is not None \
            else new_streams(WORLD_STREAM_SEED)
        # билет в тактический бой, который запустил игрок (см. run())
        self.pending_session: Optional[WarSession] = None
        # счётчики солей: match_id растёт по сессиям, _battle_seq — по мгновенным
        # боям бота, поэтому поток «world:battle» не переигрывается по кругу
        self._match_seq = 0
        self._battle_seq = 0
        # True, пока идёт ход ИИ: в нём бой остаётся мгновенным, тактику
        # запускать изнутри хода ИИ нельзя (см. _start_tactical_session)
        self._ai_turn_active = False

        self.tex_manager = TextureManager()
        self._build_province_offsets()
        self._build_static_surfaces()
        self._build_world_bounds()
        # Порядок отрисовки подписей: важное раньше неважного. Список
        # статичен, меняется только вынос провинции под курсором вперёд,
        # поэтому сортировка не повторяется каждый кадр.
        self._place_order = sorted(
            range(len(self.provinces)),
            key=lambda i: (_PLACE_TIERS.get(self.provinces[i].region_type, 2), i))

    @property
    def is_finished(self) -> bool:
        """Партия на карте окончена (победа или поражение королевства)."""
        return bool(self._game_over)

    def _nation_object(self, nation_key: str):
        """Объект нации по id или ``None`` — то, что читает HUD."""
        return self.nations.get(nation_key)

    def reopen(self):
        """Поднять экран после тактического боя и войти в карту заново.

        Сбрасывается только состояние прогона (был закрыт / шёл финальный
        бой), но НЕ состояние мира: казна, провинции и генералы остаются теми
        же объектами, что были до боя.
        """
        self.pending_session = None
        self._game_over = False
        self._winner = None
        self._battle_result = None
        self._battle_timer = 0.0
        self.selected_general = None
        self.running = True
        self._invalidate_panel()

    def apply_outcome(self, deltas: Dict[str, object]) -> None:
        """Применить дельты боя к живому миру (см. ``war.outcome_to_world``).

        Разбор дельт живёт в ``war.py``: список полей — это контракт
        ``outcome_to_world``, и держать его в двух местах значит однажды
        забыть про новое поле. Здесь только передача своего состояния.
        """
        apply_deltas_to_screen(self, deltas)

    def _battle_rng(self, salt: int):
        """Ветка именованного потока ``world:battle`` под целочисленной солью.

        Отдельная ветка на каждое применение: бой бота и сессия игрока больше
        не зависят от того, кто первый позвал ``stream()``, и реплей мира
        воспроизводится целиком.
        """
        return self.streams.derive(WORLD_BATTLE_STREAM, int(salt))

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
        # Окантовка карты (тень, плёнка владений, берег, границы) целиком в
        # одной поверхности мировых размеров. Собирается один раз на зум и на
        # раскладку владений и в кадре уходит ровно на один блит.
        self._frame: Optional[pygame.Surface] = None
        self._frame_key: Optional[Tuple] = None
        # Рельеф суши — одна непрерывная поверхность на весь мир плюс её
        # масштабированные копии по зумам. Раньше здесь было пятьдесят
        # прямоугольных текстур по одной на провинцию, и карта читалась как
        # таблица; теперь местность одна, а провинция возникает поверх неё
        # швом границы. Кэш зумов с потолком: поверхность мира — 1.6 Мпикс,
        # и на 2.5x она уже десять мегапикселей.
        self._land: Optional[pygame.Surface] = None
        self._land_zoom_cache: Dict[float, pygame.Surface] = {}
        # Подписи поселений с обводкой и уже обрезанные по ширине: обе
        # карты живут отдельно от _text_cache, потому что у подписи своя
        # форма (с обводкой) и свой ключ (исходная строка + лимит ширины).
        self._label_cache: Dict[Tuple, pygame.Surface] = {}
        self._fit_cache: Dict[Tuple[str, int, int], str] = {}

    def _build_world_bounds(self):
        """Габариты суши в мировых координатах + запас под окантовку.

        Поверхность окантовки должна быть чуть больше самой суши: тень уходит
        вниз-вправо на несколько пикселей, а обводка берега — наружу от
        контура, и без запаса они бы срезались краем поверхности.
        """
        xs = [x for prov in self.provinces for x, _ in prov.polygon]
        ys = [y for prov in self.provinces for _, y in prov.polygon]
        min_x, min_y = min(xs), min(ys)
        self._frame_origin = (min_x - _FRAME_PAD, min_y - _FRAME_PAD)
        self._frame_size = ((max(xs) - min_x) + _FRAME_PAD * 2,
                            (max(ys) - min_y) + _FRAME_PAD * 2)
        # Маска суши для рек: без неё они уходили в открытое море
        self._land_mask = LandMask([p.polygon for p in self.provinces],
                                   (min_x, min_y))
        # Рельеф суши. Строится один раз (в текстурах он кэшируется и в
        # памяти, и на диске) и дальше только блитится.
        self._land = land_surface([p.polygon for p in self.provinces],
                                  self._frame_origin, self._frame_size)

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
        return sorted(self._conn_by_province.get(idx, set()))

    def _province_occupant(self, idx: int) -> Optional[General]:
        """Генерал, стоящий в провинции, или ``None``."""
        for gen in self.generals:
            if gen.province_idx == idx:
                return gen
        return None

    def _is_passable_for(self, idx: int, mover: General,
                         blocked: set) -> bool:
        """Может ли ``mover`` пройти через провинцию ``idx`` как промежуточную.

        Свои армии **не** преграда: несколько генералов одной державы в одной
        провинции — штатная стойка, и `_move_general_to_province` их штабелирует.
        Чужие мирные армии — преграда для промежуточной клетки (заходить туда
        нельзя вовсе, это показано в ``_ai_can_enter``), а вражеские в
        промежуточной клетке допустимы: с ними просто случается бой.

        Именно эта разница даёт «обход своей армии» вместо тупика.
        """
        if idx in blocked:
            return False
        other = self._province_occupant(idx)
        if other is not None and other is not mover:
            if other.nation == mover.nation:
                return True  # своя армия — проходим, встаём рядом
            return False     # любой чужой генерал — мимо; зайти к нему в
            # клетку можно только как к цели (её find_province_path
            # проверяет отдельно, минуя этот метод)
        # Земля дружественной/нейтральной державы проходима: армия идёт
        # сквозь неё, не задерживаясь. Иначе одна союзная провинция на пути
        # блокировала весь поход — «соперник стоит и не идёт».
        return True

    def find_province_path(self, start: int, goal: int, mover: General) -> List[int]:
        """Кратчайший путь по провинциям ``[start, ..., goal]`` или ``[]``.

        Поиск в ширину по графу ``PROVINCE_CONNECTIONS`` — на карте 50 вершин,
        поэтому очередь с приоритетом по расстоянию избыточна. Обход идёт в
        отсортированном порядке, поэтому путь детерминирован: при двух
        равных маршрутах всегда выбирается один и тот же, иначе реплей боя и
        сетевой рассинхрон.

        Чужие дружественные армии помечены непроходимыми: армия не должна
        упираться в союзников, которые встали между ней и целью.
        """
        if start == goal:
            return [start]
        seen = {start}
        queue: List[Tuple[int, List[int]]] = [(start, [start])]
        while queue:
            node, path = queue.pop(0)
            for nxt in self._adjacent_provinces(node):
                if nxt in seen:
                    continue
                if nxt != goal and not self._is_passable_for(nxt, mover, set()):
                    continue
                seen.add(nxt)
                new_path = path + [nxt]
                if nxt == goal:
                    return new_path
                queue.append((nxt, new_path))
        return []

    def _path_preview(self, start: int, goal: int, mover: General) -> List[int]:
        """Путь без стартовой вершины — так его удобнее рисовать."""
        path = self.find_province_path(start, goal, mover)
        return path[1:] if len(path) > 1 else []

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

    def run(self):
        """Цикл карты до выхода.

        Возвращает :class:`war.WarSession`, если игрок нажал на чужого генерала
        или на чужую провинцию с войсками (см. ``_start_tactical_session``), и
        ``None`` во всех остальных случаях — включая победу и поражение
        королевства. Игровой цикл в ``main.py`` трактует это так: сессия —
        значит запустить тактику и вернуться сюда же, ``None`` — уйти в меню.

        Раньше здесь возвращался ``self._winner``. Этот атрибут жив (на нём
        держится финальный экран карты), но наружу больше не отдаётся: иначе
        маршрут «мир -> тактика -> мир» пришлось бы различать по строке
        ``"VICTORY"``, а сессия и победа — принципиально разные вещи.
        """
        while self.running:
            dt = self.clock.tick(60) / 1000.0
            self._handle_events()
            self._update(dt)
            self._render()
        return self.pending_session

    def _handle_events(self):
        for event in pygame.event.get():
            sel_before = self.selected_general
            if event.type == pygame.QUIT:
                self.running = False

            elif event.type == pygame.KEYDOWN:
                self._keys_held.add(event.key)
                if event.key == pygame.K_ESCAPE:
                    if self._show_ownership:
                        # ESC двухуровневый: сначала снимает выбор персонажа
                        # или графства, и только потом закрывает панель. Раньше
                        # один ESC закрывал всё разом, и ошибочно снять выбор
                        # было нельзя — приходилось закрывать и открывать панель.
                        if self._sel_character_id is not None \
                                or self._sel_county_idx is not None:
                            self._reset_ownership_selection()
                            self._invalidate_panel()
                        else:
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
                elif event.key in (pygame.K_s, pygame.K_h):
                    # S/H — стоп и удержание: маршруты выделенной группы
                    # отменяются, армии остаются на месте. На мировой карте
                    # «стой» и «держать позицию» — одно и то же действие.
                    self._stop_selection()
                elif (pygame.K_0 <= event.key <= pygame.K_9
                        and not self._show_ownership
                        and not self._show_diplomacy):
                    # Цифры — только когда не открыта панель владений или
                    # дипломатия: там те же клавиши означают строки панели.
                    slot = event.key - pygame.K_0
                    keys = pygame.key.get_pressed()
                    ctrl = keys[pygame.K_LCTRL] or keys[pygame.K_RCTRL]
                    if slot == 0:
                        if ctrl:
                            self._control_groups.clear()
                            self._show_msg("Отряды забыты")
                        else:
                            self.zoom = 1.0
                            self.cam_x, self.cam_y = 0, 0
                            self._clamp_camera()
                    elif ctrl:
                        self._store_control_group(slot)
                    else:
                        self._recall_control_group(slot)
                elif event.key in (pygame.K_PLUS, pygame.K_EQUALS, pygame.K_KP_PLUS):
                    self._zoom_at(SCREEN_WIDTH // 2, (SCREEN_HEIGHT - 80) // 2, 1.2)
                elif event.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                    self._zoom_at(SCREEN_WIDTH // 2, (SCREEN_HEIGHT - 80) // 2, 1 / 1.2)
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
                    # двигают курсор по списку персонажей
                    if event.key in (pygame.K_q, pygame.K_LEFT):
                        self._cycle_ownership_nation(-1)
                    elif event.key in (pygame.K_e, pygame.K_RIGHT):
                        self._cycle_ownership_nation(1)
                    elif event.key in (pygame.K_UP, pygame.K_DOWN):
                        self._move_vassal_cursor(-1 if event.key == pygame.K_UP else 1)
                    else:
                        # ветка проглатывает ВСЁ, что не Q/E и не стрелки, поэтому
                        # 1..4 приходится ловить здесь: без этого хоткеты панели
                        # не достанутся никогда
                        action = self._panel_hotkey_action(event.key)
                        if action is not None:
                            self._panel_run_action(action)
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
                    self._lmb_down_pos = (mx, my)
                    self._lmb_rect = None
                    # панель лежит поверх карты: клик по её строке — это
                    # выбор в панели, а не выбор генерала под ней
                    if self._panel_hit(mx, my) is not None:
                        self._handle_panel_click(mx, my)
                        self._lmb_down_pos = None
                    elif my < SCREEN_HEIGHT - 80:
                        self._lmb_rect = pygame.Rect(mx, my, 0, 0)

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
                            if self.selected_generals:
                                self._handle_map_click(mx, my, via_right=True)
                            else:
                                self._select_only([])
                elif event.button == 1:
                    down = self._lmb_down_pos
                    self._lmb_down_pos = None
                    rect = self._lmb_rect
                    self._lmb_rect = None
                    if down is None:
                        continue          # клик ушёл в панель, карта его не ждёт
                    mx, my = event.pos
                    keys = pygame.key.get_pressed()
                    shift = keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT]
                    if rect is not None and (abs(mx - down[0]) >= self._SELECT_DRAG_PX
                                             or abs(my - down[1]) >= self._SELECT_DRAG_PX):
                        self._select_by_box(rect, shift=shift)
                    elif my < SCREEN_HEIGHT - 80:
                        self._handle_left_click(mx, my)

            elif event.type == pygame.MOUSEMOTION:
                self._mouse_pos = event.pos
                if self._lmb_down_pos and self._lmb_rect is not None:
                    # рамка растёт от точки нажатия, а не от текущей позиции
                    x0 = self._lmb_down_pos[0]
                    y0 = self._lmb_down_pos[1]
                    self._lmb_rect = pygame.Rect(
                        min(x0, event.pos[0]), min(y0, event.pos[1]),
                        abs(event.pos[0] - x0), abs(event.pos[1] - y0))
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

    # --- приказы: список внутри, одиночный вид снаружи -------------------
    # Выделение — тоже список, но наружу по-прежнему отдаётся один
    # ``selected_general``: на него ссылаются панели, подсказки и все прежние
    # проверки. Это ПЕРВАЯ армия в группе, и всё, что спрашивает «кого сейчас
    # показывать», продолжает получать осмысленный ответ.

    @property
    def selected_general(self) -> Optional[General]:
        """Первая армия выделения, ради совместимости с одиночным выбором."""
        return self.selected_generals[0] if self.selected_generals else None

    @selected_general.setter
    def selected_general(self, value: Optional[General]):
        self.selected_generals = [value] if value is not None else []

    def _select_only(self, generals: List[General]):
        self.selected_generals = list(generals)
        self._invalidate_panel()

    def _add_to_selection(self, generals: List[General]):
        """Shift-клик: добавить к выделению, не снимая прежнее."""
        for g in generals:
            if g not in self.selected_generals:
                self.selected_generals.append(g)
        self._invalidate_panel()

    def _toggle_selection(self, general: General):
        if general in self.selected_generals:
            self.selected_generals = [g for g in self.selected_generals
                                      if g is not general]
        else:
            self.selected_generals.append(general)
        self._invalidate_panel()

    def _player_armies(self) -> List[General]:
        """Свои армии, которыми можно командовать (в бой уже ушедшие — нет)."""
        return [g for g in self.generals if g.nation == PLAYER_NATION]

    def _player_armies_in_rect(self, rect: pygame.Rect) -> List[General]:
        """Свои армии, чей флаг попал в рамку выделения.

        Проверяются две точки — над провинцией (куда рисуется флаг) и её центр.
        Только по флагу рамка должна была угадать с координатой «на 18 px
        выше центра», и выбор рамкой отваливался у нижней кромки отряда.
        """
        picked: List[General] = []
        for g in self._player_armies():
            if g.province_idx is None:
                continue
            cx, cy = self.provinces[g.province_idx].centroid
            banner = self._world_to_screen(cx, cy - 18)
            centre = self._world_to_screen(cx, cy)
            if (rect.collidepoint(int(banner[0]), int(banner[1]))
                    or rect.collidepoint(int(centre[0]), int(centre[1]))):
                picked.append(g)
        return picked

    def _store_control_group(self, slot: int):
        """Ctrl + цифра: запомнить текущее выделение под номером."""
        if not self.selected_generals:
            return
        self._control_groups[slot] = list(self.selected_generals)
        self._show_msg(f"Отряд {slot}: {len(self.selected_generals)}")

    def _recall_control_group(self, slot: int) -> bool:
        """Цифра: вернуть выделение отряда.

        Хранятся ССЫЛКИ на армии, а не номера в списке: нумерация сдвигается
        при любом перестроении мира, и отряд «2» молча превратился бы в чужой.
        Отряд считается пустым, только если все его армии действительно ушли
        с поля — тогда про него честно сообщают, а не выделяют случайных.
        """
        group = self._control_groups.get(slot)
        if not group:
            return False
        alive = [g for g in group if g in self.generals]
        if not alive:
            self._show_msg(f"Отряд {slot} пуст — все армии погибли")
            return False
        self._select_only(alive)
        self._show_msg(f"Отряд {slot}: {len(alive)}")
        return True

    # --- приказы: список внутри, одиночный вид снаружи -------------------
    # Раньше приказ был один на весь экран, и всё, что о нём знал, —
    # ``_move_order`` / ``_move_path`` / ``_move_stuck``. Теперь приказов
    # много, но эти три имени по-прежнему отвечают на вопрос «что исполняется
    # прямо сейчас», то есть показывают ПЕРВЫЙ приказ в очереди. Поэтому всё,
    # что ими пользуется (подсказка, превью маршрута, тесты), продолжает
    # работать без правок, а групповые приказы просто перестают быть
    # невозможными.

    @property
    def _move_order(self) -> Optional[Tuple[General, int]]:
        """Приказ, который исполняется сейчас: (генерал, провинция)."""
        if not self._orders:
            return None
        first = self._orders[0]
        return (first["general"], first["goal"])

    @property
    def _move_path(self) -> List[int]:
        """Остаток маршрута первого приказа."""
        return self._orders[0]["path"] if self._orders else []

    @property
    def _move_stuck(self) -> int:
        """Сколько ходов подряд приказ не продвигается."""
        return self._orders[0]["stuck"] if self._orders else 0

    def _cancel_move_order(self):
        """Снять ВСЕ приказы: выполнены, армии не стало или сменился выбор."""
        self._orders = []
        self._queued_orders = []

    def _issue_move_order(self, general: General, goal_idx: int) -> bool:
        """Приказ одной армии идти в дальнюю провинцию. ``False``, если пути нет."""
        return self._issue_orders([general], goal_idx) > 0

    def _issue_orders(self, generals: List[General], goal_idx: int,
                      queue: bool = False) -> int:
        """Приказ группе армий идти к одной цели. Возвращает число принятых.

        Часть армий может быть без пути (например, отрезаны после чужого
        захвата) — тогда приказ получает только она, а остальные получают
        честное сообщение. Молча выдавать половине группы приказ и прятать
        вторую половину хуже, чем сказать, кто остался на месте.
        """
        if not generals or goal_idx is None:
            return 0
        target = self.provinces[goal_idx].name
        issued, refused = 0, []
        fresh: List[Dict] = []
        for g in generals:
            # `moved` НЕ проверяем: приказ — это «куда идти дальше», а не
            # «пошли сейчас». Армия, уже сходившая в этом ходу, вправе получить
            # маршрут на следующий, иначе после одного хода в провинции
            # нельзя было бы запланировать ничего.
            if g.province_idx is None or g not in self.generals:
                refused.append(g)
                continue
            path = self.find_province_path(g.province_idx, goal_idx, g)
            if len(path) < 2:
                refused.append(g)
                continue
            fresh.append({"general": g, "goal": goal_idx,
                          "path": path[1:], "stuck": 0})
            issued += 1
        if fresh:
            if queue:
                # Shift-клик не отменяет текущие приказы, а дописывает в конец
                self._queued_orders.extend(fresh)
            else:
                self._orders = fresh
                self._queued_orders = []
        elif not queue:
            # приказ невозможен — старый маршрут тоже сбрасываем, иначе игрок
            # видит «пути нет» и продолжает смотреть на маршрут вчерашнего дня
            self._cancel_move_order()
        if refused:
            self._show_msg(
                f"{len(refused)} не могут идти к {target}: путь перекрыт")
        if issued:
            lead = fresh[0]["general"]
            extra = f" (+ещё {issued - 1})" if issued > 1 else ""
            self._show_msg(f"{lead.name}{extra} → {target}")
        return issued

    def _advance_move_order(self) -> bool:
        """По одному шагу каждой армии с приказом. ``True``, если кто-то сдвинулся.

        Если у одной армии подряд ``MOVE_ORDER_STUCK_TURNS`` ходов продвижения
        нет (она отбивается и откатывается), приказ снимается с честным
        сообщением. Без этого приказ в запертой провинции перебивался вечно:
        генерал бился о противника, отступал, бился снова — и выглядело это как
        «соперник стоит и ничего не делает», хотя стоял и стоял наш.
        """
        if not self._orders:
            if self._queued_orders:
                self._orders = self._queued_orders
                self._queued_orders = []
            else:
                return False
        moved_any = False
        alive: List[Dict] = []
        for order in self._orders:
            general, goal = order["general"], order["goal"]
            if general not in self.generals or general.moved:
                continue                      # армии нет — приказ отпадает
            if general.province_idx == goal:
                continue                      # дошли
            path = self.find_province_path(general.province_idx, goal, general)
            if len(path) < 2:
                self._show_msg(f"{general.name}: путь перекрыт")
                continue
            order["path"] = path[1:]
            before = general.province_idx
            self._move_general_to_province(general, path[1])
            moved = general.province_idx != before
            if general.province_idx == goal:
                self._show_msg(f"{general.name} занял {self.provinces[goal].name}")
                continue
            if moved:
                order["stuck"] = 0
                moved_any = True
            else:
                order["stuck"] += 1
                if order["stuck"] >= MOVE_ORDER_STUCK_TURNS:
                    self._show_msg(
                        f"{general.name}: путь блокируют, приказ снят")
                    continue
            alive.append(order)
        self._orders = alive
        return moved_any

    def _stop_selection(self):
        """Отменить маршруты выделенной группы, оставив армии на месте."""
        stopped = set(id(g) for g in self.selected_generals)
        if not stopped:
            if self._orders or self._queued_orders:
                self._cancel_move_order()
                self._show_msg("Все приказы сняты")
            return
        keep_q = [o for o in self._queued_orders
                  if id(o["general"]) not in stopped]
        keep = [o for o in self._orders if id(o["general"]) not in stopped]
        count = (len(self._orders) + len(self._queued_orders)) - len(keep) - len(keep_q)
        self._orders = keep
        self._queued_orders = keep_q
        self._show_msg(f"Стоп: снято приказов — {count}")

    def _render_selection(self):
        """Рамка выделения и подсветка всей выбранной группы.

        Раньше выделение могло быть только одно, и игрок не видел, что
        приказ уйдёт всем: флаг подсвечивался у одной армии, а двигались
        две. Теперь видно каждую.
        """
        for g in self.selected_generals:
            if g.province_idx is None:
                continue
            cx, cy = self.provinces[g.province_idx].centroid
            x, y = self._world_to_screen(cx, cy)
            pulse = abs(math.sin(pygame.time.get_ticks() * 0.005)) * 0.35 + 0.65
            col = (int(255 * pulse), int(240 * pulse), int(120 * pulse))
            pygame.draw.circle(self.screen, col, (int(x), int(y)),
                               max(12, int(15 * self.zoom)), 2)
        if self._lmb_rect is not None and self._lmb_down_pos is not None:
            r = self._lmb_rect
            if r.width > 0 and r.height > 0:
                fill = pygame.Surface(r.size, pygame.SRCALPHA)
                fill.fill((255, 236, 170, 38))
                self.screen.blit(fill, r.topleft)
                pygame.draw.rect(self.screen, (255, 236, 170), r, 1)

    def _select_by_box(self, rect: pygame.Rect, shift: bool = False):
        """Рамка выделения: все свои армии, чей флаг попал в прямоугольник.

        Пустая рамка — щелчок по пустому полю — снимает выделение, если Shift
        не зажат. Иначе игрок не мог «снять всё», не имея под рукой пустой
        провинции, а одиночный клик по своей же земле сбивал выбор неожиданно.
        """
        picked = self._player_armies_in_rect(rect)
        if not picked:
            if not shift:
                self._select_only([])
                self._show_msg("Никого не выбрано")
            return
        if shift:
            self._add_to_selection(picked)
        else:
            self._select_only(picked)
        self._show_msg(f"Выбрано армий: {len(self.selected_generals)}")

    def _handle_left_click(self, mx: int, my: int):
        """Левый клик: выбор, двойной — вся гарнизон, Ctrl — переключение.

        Раньше левый клик всегда и только выбирал одну армию, а при отсутствии
        выделения клик по своей провинции запускал поход на врага. Второе
        поведение осталось только для клика по ЧУЖОЙ земле: выделение не
        сбивает приказ игрока, который он уже отдал.
        """
        keys = pygame.key.get_pressed()
        ctrl = keys[pygame.K_LCTRL] or keys[pygame.K_RCTRL]
        wx, wy = self._screen_to_world(mx, my)
        idx = next((i for i, p in enumerate(self.provinces)
                    if p.contains_point(wx, wy)), None)
        if idx is None:
            if not ctrl:
                self._select_only([])
            return

        now = pygame.time.get_ticks()
        near = (abs(mx - self._last_click_pos[0]) < 8
                and abs(my - self._last_click_pos[1]) < 8)
        dbl = now - self._last_click_ms <= self._DOUBLE_CLICK_MS and near
        self._last_click_ms, self._last_click_pos = now, (mx, my)

        garrison = [g for g in self._player_armies() if g.province_idx == idx]
        if dbl and garrison:
            # двойной клик — весь гарнизон поселения, как «выбрать всех»
            self._select_only(garrison)
            self._show_msg(f"{self.provinces[idx].name}: "
                           f"{len(garrison)} армий")
            return
        if not garrison:
            # своей армии тут нет: клик по своей земле просто снимает выбор,
            # а по чужой — отдаёт приказ ближайшей своей армии
            if not ctrl and not keys[pygame.K_LSHIFT]:
                if self.selected_generals:
                    self._select_only([])
                elif self.provinces[idx].owner != PLAYER_NATION:
                    self._auto_attack_order(idx)
            return
        target = garrison[0]
        if ctrl:
            self._toggle_selection(target)
        elif keys[pygame.K_LSHIFT]:
            self._add_to_selection([target])
        else:
            self._select_only([target])

    def _handle_map_click(self, mx: int, my: int, via_right: bool = False):
        if my >= SCREEN_HEIGHT - 80:
            return

        if not via_right:
            # Левая кнопка больше не «выбирает и сразу двигает»: выбор, рамка и
            # двойной клик живут в _handle_left_click, а приказ — только правой.
            # Смешивать их в одной функции было причиной того, что клик по своей
            # же провинции неожиданно сбрасывал выделение.
            self._handle_left_click(mx, my)
            return

        wx, wy = self._screen_to_world(mx, my)
        target = next((i for i, prov in enumerate(self.provinces)
                       if prov.contains_point(wx, wy)), None)
        if target is None:
            return

        keys = pygame.key.get_pressed()
        queue = keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT]
        army = self.selected_generals
        if not army:
            self._auto_attack_order(target)
            return

        # Правый клик по своей армии — это выбор, а не приказ самому себе.
        here = [g for g in army if g.province_idx == target]
        if len(here) == len(army):
            self._select_only(here)
            self._show_msg(f"{self.provinces[target].name}: "
                           f"{len(here)} армий")
            return

        stepped, marchers = [], []
        for g in army:
            if g.province_idx is None or g.province_idx == target:
                continue
            if target in self._adjacent_provinces(g.province_idx):
                self._move_general_to_province(g, target)
                stepped.append(g)
            else:
                marchers.append(g)

        name = self.provinces[target].name
        if marchers:
            # Далёкая цель: маршрут на несколько ходов. Группа получает приказ
            # одним действием, а не по клику на каждую армию.
            self._issue_orders(marchers, target, queue=queue)
        elif stepped:
            verb = "поставлены" if len(stepped) > 1 else "встал"
            self._show_msg(f"{name}: {verb} на месте "
                           f"{', '.join(g.name for g in stepped)}")
        if stepped:
            self._cancel_move_order()
        # Выделение НЕ снимаем: в Warcraft 3 после приказа армия остаётся
        # выбранной, иначе группу нельзя переставить одним движением, а
        # отменять приказ, случайно ткнув в соседнюю провинцию, нечем.

    def _auto_attack_order(self, target_idx: int) -> bool:
        """Отдать приказ напасть на чужую провинцию без ручного выбора армии.

        Берётся ближайшая по числу шагов своя армия, способная дойти (а не
        та, что просто ближе в пикселях), и ей выдаётся маршрут. Если враг
        стоит в соседней провинции, шаг делается сразу — приказ не нужен.
        """
        prov = self.provinces[target_idx]
        owner = getattr(prov, "owner", "neutral")
        if owner == PLAYER_NATION:
            return False
        if owner != "neutral" and not self.diplomacy.is_enemy(PLAYER_NATION, owner):
            self._show_msg("Туда нельзя: нет войны")
            return False

        best_gen: Optional[General] = None
        best_len = None
        for gen in self.generals:
            if gen.nation != PLAYER_NATION or gen.moved or gen.province_idx is None:
                continue
            path = self.find_province_path(gen.province_idx, target_idx, gen)
            length = len(path) - 1
            if not path or length <= 0:
                continue
            if best_len is None or length < best_len:
                best_len = length
                best_gen = gen
        if best_gen is None:
            self._show_msg("Нет армии, способной дойти")
            return False

        if best_len == 1:
            self._move_general_to_province(best_gen, target_idx)
            self._cancel_move_order()
            return True
        issued = self._issue_move_order(best_gen, target_idx)
        if issued:
            self._show_msg(f"{best_gen.name} идёт на {prov.name}")
        return issued

    def _general_character(self, general):
        """Персонаж иерархии, соответствующий генералу, или ``None``.

        Генералы мира (``world_data.General``) и персонажи иерархии
        (``states.Character``) — разные сущности: у первых есть число
        солдат, у вторых ранг, мнение и земля.

        Сверка идёт по паре (имя, нация), а не только по имени: имена
        переиспользуются в разных державах (генерал синей армии Aldric и
        красный герцог duke_aldric — разные люди), и сверка только по имени
        отдала бы синюю провинцию красному персонажу вместе с его контрактом.
        """
        for ch in self.hierarchy.characters.values():
            if ch.name == general.name and ch.nation == general.nation:
                return ch
        return None

    def _take_county(self, target_idx: int, general, *, cause: str) -> None:
        """Передача графства нации генерала через иерархию.

        Единственная точка смены владельца на мировой карте: прямая запись
        ``province.owner = ...`` оставляла ``Character.province_idx``,
        ``contracts[...].liege_id`` и де-факто держателя герцогства в
        неведении, из-за чего доход провинции засчитывался дважды.
        """
        character = self._general_character(general)
        new_holder = character.id if character is not None else None
        events = self.hierarchy.transfer_county(
            target_idx, general.nation, new_holder, cause=cause)
        # Физическое положение армии обновляется ВСЕГДА, даже если у генерала
        # нет пары-персонажа в иерархии: раньше условие связывало это с
        # ``new_holder``, и генерал без персонажа (Theron, Aldric) захватывал
        # провинцию, но оставался на месте — выглядело как «соперник стоит
        # и ничего не делает», хотя владение менялось.
        general.province_idx = target_idx
        if character is not None and new_holder:
            character.province_idx = target_idx
        for message in events:
            self._show_msg(message)

    def _move_general_to_province(self, general: General, target_idx: int,
                                  player_initiated: Optional[bool] = None):
        """Перевести генерала в соседнюю провинцию.

        ``player_initiated`` разделяет два принципиально разных случая, и
        поэтому это не украшение: игрок нажал на врага — идём в тактику
        (``_start_tactical_session``), а ход ИИ проглатывается мгновенным
        расчётом (``_start_battle``). Запускать тактический экран изнутри хода
        ИИ нельзя: он блокирующий и вернул бы управление игроку посреди
        чужого хода, а «триггер боя» у бота в этом этапе нет.

        По умолчанию (``None``) источник определяется флагом ``_ai_turn_active``,
        который ставит ``_ai_turn``. Явный параметр нужен для проверок и для
        будущего «игрок отдаёт приказ генералу из панели владений».
        """
        if player_initiated is None:
            player_initiated = not self._ai_turn_active

        target = self.provinces[target_idx]
        # откуда пришли: нужно для отступления при проигранном бою
        origin_idx = general.province_idx

        for other in self.generals:
            if other is not general and other.province_idx == target_idx:
                if self.diplomacy.is_enemy(general.nation, other.nation):
                    if player_initiated:
                        self._start_tactical_session(general, defender_nation=other.nation,
                                                     province_idx=target_idx)
                    else:
                        self._start_battle(general, other,
                                           retreat_to=origin_idx,
                                           capture_idx=target_idx)
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
                    elif self.diplomacy.is_enemy(general.nation, other.nation):
                        # враждебный генерал в той же провиннице — бой
                        if player_initiated:
                            self._start_tactical_session(
                                general, defender_nation=other.nation,
                                province_idx=target_idx)
                        else:
                            self._start_battle(
                                general, other, retreat_to=origin_idx,
                                capture_idx=target_idx)
                        general.moved = True
                        return
                    else:
                        # нейтральная держава: армия проходит, но не задерживается
                        general.province_idx = target_idx
                        general.moved = True
                        self._show_msg(
                            f"{general.name} проходит через {target.name}")
                        return

        if target.owner == "neutral":
            self._take_county(target_idx, general, cause="захват")
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
                    self._take_county(target_idx, general, cause="захват")
                    target.troops = 0
                    general.moved = True
                    self._invalidate_panel()
                    self._show_msg(f"{target.name} захвачена!")
                else:
                    if player_initiated:
                        self._start_tactical_session(general, defender_nation=target.owner,
                                                     province_idx=target_idx)
                    else:
                        self._start_battle_with_region(general, target)
                    general.moved = True
            else:
                # дружественная или нейтральная земля: проходим насквозь,
                # владение не трогаем. Раньше тут был отказ, и любая
                # союзная провинция на пути намертво блокировала армию —
                # бот стоял и «ничего не делал» именно из-за этого.
                general.province_idx = target_idx
                general.moved = True
                self._show_msg(f"{general.name} проходит через {target.name}")
            return

    def _defender_strength(self, nation: str, province_idx: int) -> int:
        """Сколько солдат реально может выставить защитник.

        Порядок источников: генерал в целевой провинции + гарнизон самой
        провинции; если генерала нет — только гарнизон; если и гарнизона
        нет — треть левейса нации (оборона без войск всё же должна что-то
        значить, иначе игрок выигрывает бой об чужую провинцию в одиночку).

        Именно это число едет в ``WarSession.defender_troops``: раньше там
        стояло ``own // 2``, из-за чего метрика войск соперника не имела
        никакого значения — против 1200 он всегда получал вдвое меньше.
        """
        troops = 0
        for gen in self.generals:
            if gen.nation == nation and gen.province_idx == province_idx:
                troops += max(0, int(getattr(gen, "troops", 0)))
        prov = self.provinces[province_idx]
        troops += max(0, int(getattr(prov, "troops", 0)))
        if troops <= 0:
            realm = self._realm_of_nation(nation)
            if realm is not None:
                troops = max(1, self.hierarchy.realm_levy(realm.id) // 3)
        return max(0, troops)

    def _start_tactical_session(self, general: General, defender_nation: str,
                                province_idx: int) -> WarSession:
        """Завести билет в тактический бой и выйти из карты.

        Левейс генерала при этом НЕ трогается: он уходит в бой целиком, а
        вернётся вместе с трофеями через ``outcome_to_world``. Так потери
        считаются один раз и по результату боя, а не до него.

        Качество войск и зерно боя берутся из именованного потока
        ``world:battle`` под солью ``match_id`` — целое число, поэтому
        последовательность боёв воспроизводится при любом порядке вызовов.
        """
        self._match_seq += 1
        match_id = self._match_seq
        # соль из СВОЕГО диапазона (WORLD_SESSION_SALT_BASE), иначе сессия делила
        # бы генератор с мгновенными боями и качество зависело от ходов ИИ
        rnd = self._battle_rng(WORLD_SESSION_SALT_BASE + match_id)

        session = WarSession(
            match_id=match_id,
            attacker_nation=general.nation,
            defender_nation=defender_nation,
            province_idx=int(province_idx),
            general_name=general.name,
            troops_committed=int(general.troops),
            defender_troops=self._defender_strength(defender_nation, province_idx),
            quality=quality_from_roll(rnd.randrange(100)),
            seed=rnd.getrandbits(32),
            player_attacker=(general.nation == PLAYER_NATION),
        )

        self.pending_session = session
        self._battle_result = None
        self._battle_timer = 0.0
        # карта отдаёт управление: цикл в main.py увидит pending_session,
        # запустит тактику и вернёт нас сюда же через reopen()
        self.running = False
        return session

    def _start_battle(self, attacker: General, defender: General,
                       retreat_to: Optional[int] = None,
                       capture_idx: Optional[int] = None):
        """Мгновенный бой генералов. Остаётся для ходов ИИ.

        Формула и пороги не тронуты — переехали только броски: вместо
        глобального ``random.uniform`` берётся ветка именованного потока под
        солью счётчика боёв. Иначе одна партия мира не была бы повторяемой.

        При поражении атакующий **отступает** в ``retreat_to``. Раньше он
        оставался стоять на месте боя, и приказ «идти к врагу» намертво
        заклинивал: армия четыре хода подряд билась об одну и ту же
        провинцию и не двигалась — выглядело как «соперник стоит и ничего
        не делает», только стоял уже наш генерал.
        """
        rnd = self._battle_rng(self._next_battle_salt())
        a_power = attacker.troops * (attacker.health / 100)
        d_power = defender.troops * (defender.health / 100)
        a_roll = a_power * rnd.uniform(0.7, 1.3)
        d_roll = d_power * rnd.uniform(0.7, 1.3)
        defender_destroyed = False

        if a_roll > d_roll:
            ratio = d_roll / a_roll if a_roll > 0 else 0
            losses = int(attacker.troops * ratio * 0.3)
            attacker.troops = max(MIN_ARMY_TROOPS, attacker.troops - losses)
            defender.troops = max(0, defender.troops - int(defender.troops * 0.7))
            if defender.troops < MIN_ARMY_TROOPS:
                # меньше одного вьюч-полка (TROOPS_PER_TACTICAL_UNIT = 100)
                # это уже не армия, а осколки: держать такую стойку бессмысленно,
                # она вечно стояла и вечно билась в стену
                self.generals.remove(defender)
                self._battle_result = f"{attacker.name} победил {defender.name}!"
                defender_destroyed = True
            else:
                self._battle_result = f"{attacker.name} отбит, потеряно {losses}"
            defender.health = max(0, defender.health - 20)
            # провинцию занимает победитель только если враг из неё ушёл:
            # иначе победитель и выживший защитник оказывались в одной
            # провинции, что не имеет смысла и ломало расчёт сил
            if (capture_idx is not None and attacker.troops > 0
                    and defender_destroyed):
                attacker.province_idx = capture_idx
                self.provinces[capture_idx].troops = 0
        else:
            losses = int(attacker.troops * 0.5)
            attacker.troops = max(0, attacker.troops - losses)
            if attacker.troops < MIN_ARMY_TROOPS:
                self.generals.remove(attacker)
                self._battle_result = f"{defender.name} уничтожил {attacker.name}!"
            else:
                self._battle_result = f"{attacker.name} отступил, потеряно {losses}"
                # отступление: возвращаемся туда, откуда пришли, иначе
                # приказ движения заклинивает на провинции противника
                self._retreat(attacker, retreat_to)
        self._battle_timer = 3.0

    def _retreat(self, general: General, retreat_to: Optional[int]) -> None:
        """Отвести разбитую армию назад.

        Сначала пробуем провинцию, откуда пришли. Если там уже кто-то есть
        (в том числе противник, погнавшийся за отступлением) — ищем любую
        соседнюю провинцию своей державы. Если и такой нет — стоим там, где
        стояли: выдумывать «телепорт» в никуда нельзя.
        """
        occupied = {g.province_idx for g in self.generals if g is not general}

        def free(idx):
            if idx is None or idx in occupied:
                return False
            return getattr(self.provinces[idx], "owner", "neutral") == general.nation

        if free(retreat_to):
            general.province_idx = retreat_to
            return
        for adj in self._adjacent_provinces(general.province_idx):
            if free(adj):
                general.province_idx = adj
                return

    def _start_battle_with_region(self, general: General, region: Province):
        """Мгновенный штурм провинции. Остаётся для ходов ИИ.

        Как и в ``_start_battle``, формула старая, поменялся только источник
        бросков (см. ``_battle_rng``).
        """
        rnd = self._battle_rng(self._next_battle_salt())
        a_power = general.troops * (general.health / 100)
        d_power = region.troops
        a_roll = a_power * rnd.uniform(0.7, 1.3)
        d_roll = d_power * rnd.uniform(0.7, 1.3)

        if a_roll > d_roll:
            losses = int(general.troops * 0.2)
            general.troops = max(100, general.troops - losses)
            idx = self.provinces.index(region)
            self._take_county(idx, general, cause="битва")
            region.troops = 0
            self._invalidate_panel()
            self._battle_result = f"{general.name} захватил {region.name}!"
        else:
            losses = int(general.troops * 0.4)
            general.troops = max(0, general.troops - losses)
            region.troops = max(0, region.troops - int(region.troops * 0.3))
            self._battle_result = f"{general.name} отбит от {region.name}!"
        self._invalidate_panel()
        self._battle_timer = 3.0

    def _next_battle_salt(self) -> int:
        """Следующая целочисленная соль для мгновенного боя.

        Счётчик, а не номер хода: соль должна быть уникальной на КАЖДЫЙ бросок,
        иначе второй бой за ход получил бы ту же ветку потока и повторил
        первый результат. Диапазон отделён от сессий (см.
        ``WORLD_BATTLE_SALT_BASE``).
        """
        self._battle_seq += 1
        return WORLD_BATTLE_SALT_BASE + self._battle_seq

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
        # приказ игрока: один шаг маршрута ДО хода бота, иначе бот может
        # перехватить цель на полпути и приказ зависнет
        self._advance_move_order()
        self._ai_turn()
        self._tick_ownership()
        if self._move_order is not None:
            general, goal = self._move_order
            if general not in self.generals or general.province_idx == goal:
                self._cancel_move_order()
        # и сброс кэшей: изменились ход, владения, приказы
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
        # флаг поднимается на весь ход ИИ: пока он стоит, любой вызов
        # _move_general_to_province считается ходом бота и оставляет бой
        # мгновенным (см. _move_general_to_province)
        self._ai_turn_active = True
        try:
            # копия: _start_battle удаляет проигравшего генерала из списка,
            # и обход живого списка пропускал бы ход следующему за ним
            for g in list(self.generals):
                if g.nation != PLAYER_NATION and not g.moved:
                    self._ai_move_general(g)
        finally:
            self._ai_turn_active = False

    def _ai_can_enter(self, idx: int, general: General) -> bool:
        """Имеет ли смысл ставить ``idx`` целью похода.

        Через дружественную и нейтральную землю армия проходит насквозь
        (см. ``_move_general_to_province``), поэтому такие провинции годятся
        и целью — иначе бот не пошёл бы к врагу за спиной у союзника.
        Зато цель, где стоит чужой мирный генерал, бесполезна: туда не
        войти, и бот стоял бы перед ней все ходы.
        """
        if idx == general.province_idx:
            return True
        occupant = self._province_occupant(idx)
        if occupant is not None and occupant is not general:
            if occupant.nation == general.nation:
                return True
            return self.diplomacy.is_enemy(general.nation, occupant.nation)
        return True

    def _ai_target(self, general: General,
                   skip: Optional[set] = None) -> Optional[int]:
        """Куда идти: ближайшая по числу шагов достижимая цель.

        Приоритеты: вражеский генерал, нейтральная провинция, вражеская
        провинция без гарнизона, вражевая с гарнизоном (дороже всего — с ней
        бот сначала уходит крепость осаждать силой).

        Сравнение по длине пути, а не по расстоянию в пикселях: пиксельное
        расстояние игнорирует рельеф (реки, чужие стойки), и одна армия
        «вроде ближе» до враждебной в линии, но с другой стороны карты.

        ``skip`` — цели, уже отвергнутые в этом ходу (см. ``_ai_move_general``):
        одна заблокированная цель не должна отравлять весь ход бота.
        """
        g_idx = general.province_idx
        skip = skip or set()
        best: Optional[Tuple[int, int, int]] = None
        best_idx: Optional[int] = None

        def consider(idx: int, rank: int):
            nonlocal best, best_idx
            if idx == g_idx or idx in skip:
                return
            if not self._ai_can_enter(idx, general):
                return
            path = self.find_province_path(g_idx, idx, general)
            length = len(path) - 1
            if not path or length <= 0:
                return
            # ранг цели, затем длина пути; при равенстве — индекс,
            # чтобы выбор был детерминированным
            key = (rank, length, idx)
            if best is None or key < best:
                best = key
                best_idx = idx

        for other in self.generals:
            if other is general or other.nation == general.nation:
                continue
            if self.diplomacy.is_enemy(general.nation, other.nation):
                consider(other.province_idx, 0)

        for idx, prov in enumerate(self.provinces):
            owner = getattr(prov, "owner", "neutral")
            if owner == general.nation:
                continue
            if owner == "neutral":
                consider(idx, 2)
                continue
            if self.diplomacy.get_relation(general.nation, owner) != Relation.WAR:
                continue
            # чужая провинция: без гарнизона — легко, с гарнизоном — риск
            consider(idx, 3 if prov.troops <= 0 else 5)

        return best_idx

    def _ai_move_general(self, general: General):
        """Один ход бота: шаг к выбранной цели по найденному пути.

        Раньше бот смотрел только на соседние провинции и на врагов в радиусе
        200 пикселей, поэтому он стоял столбом, когда рядом не было ни врага,
        ни нейтральной земли, и упирался в союзную армию, вставшую на пути.
        Теперь цель ищется по всему графу, а путь — в ширину, с обходом.

        Если шаг отклонён (например, в провинции стоит нейтральный генерал, в
        который нельзя войти), цель отбрасывается и выбирается следующая — за
        один ход генерал делает один шаг, но не обязан стоять из-за первой
        неудачной цели.
        """
        if general.province_idx is None:
            return
        skip: set = set()
        for _attempt in range(4):
            goal = self._ai_target(general, skip=skip)
            if goal is None:
                return
            path = self.find_province_path(general.province_idx, goal, general)
            if len(path) < 2:
                skip.add(goal)
                continue
            before = general.province_idx
            step = path[1]
            self._move_general_to_province(general, step, player_initiated=False)
            if general.province_idx != before or general.moved:
                return
            # шаг не состоялся — цель недостижима на практике, ищем другую
            skip.add(goal)
        general.moved = True

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

    def _border_style(self, idx: int, peer: int):
        """Как рисовать границу между двумя провинциями: (цвет, цвет, px, пунктир).

        Три случая, и различать их — смысл всей правки: игрок должен за
        секунду видеть «это моё / это чужое».

        * одна нация (включая пару нейтральных) — 1 px мягкий шов: он не
          должен спорить с границей державы, иначе внутренние перегородки
          снова съедают всю карту;
        * разные державы — жирная тёмная краска плюс светлая сердцевина.
          Сердцевина одна на все швы, а не смесь цветов держав: смесь
          симметрична и не «прыгает», когда доли соседей меняются местами, но
          на цветном фоне она даёт грязь, а костяная нить на тёмной краске
          читается как переговорная линия на карте;
        * нейтральная земля — 2 px заметно темнее и пунктиром: её видно, но
          она не выглядит захваченной.

        Толщина в мировых координатах масштабируется зумом, поэтому на 0.6x
        границы не сходятся в нить, а на 1.8x не превращаются в забор.
        """
        a, b = self.provinces[idx], self.provinces[peer]
        z = self.zoom
        if a.owner == b.owner:
            if a.owner == "neutral":
                return (BORDER_NEUTRAL, None, max(1, min(2, int(round(1.4 * z)))), True)
            return (BORDER_INTERNAL, None, max(1, min(2, int(round(z)))), False)
        if "neutral" in (a.owner, b.owner):
            return (BORDER_NEUTRAL, None, max(1, min(3, int(round(2 * z)))), True)
        return (BORDER_FOREIGN_INK, BORDER_FOREIGN_CORE,
                max(2, min(4, int(round(3 * z)))), False)

    @staticmethod
    def _owner_tint_map():
        """Плёнка владений для окантовки: держава -> готовая RGBA-заливка."""
        return {nation: rgba for nation, rgba in OWNER_PAINT.items()
                if rgba is not None}

    def _ownership_signature(self) -> Tuple:
        """Отпечаток раскладки владений для кэша окантовки.

        Границы зависят и от владельца, и от ранга держателя (см.
        ``_border_color``), а ранг меняется не только при захвате, но и при
        смерти короля. Без ранга в ключе карта показывала бы прежние
        границы до перезахода в экран.
        """
        sig = []
        for prov in self.provinces:
            rank = None
            duchy_id = getattr(prov, "duchy_id", None)
            if duchy_id and prov.owner != "neutral":
                holder = self._holder_of_duchy(duchy_id)
                rank = getattr(getattr(holder, "rank", None), "value", None)
            sig.append((prov.owner, rank))
        return tuple(sig)

    def _map_frame(self) -> pygame.Surface:
        """Кэшированный слой местности: рельеф + плёнка владений + берег + границы.

        Пересобирается только когда сменился зум или раскладка владений.
        Камера, панель и время на неё не влияют, поэтому при обычном панорамировании
        это просто блит готовой поверхности.
        """
        key = (round(self.zoom, 2), self._ownership_signature())
        if self._frame is not None and self._frame_key == key:
            return self._frame
        raw = build_map_frame(
            [p.polygon for p in self.provinces],
            [p.owner for p in self.provinces],
            self._frame_origin, self._frame_size,
            self.zoom, self._border_style,
            owner_tint=self._owner_tint_map())
        # Рельеф и окантовка склеиваются в один слой. Оба занимают весь
        # bounding box мира, и в кадре это были два больших блита по 1.6 Мпикс
        # с альфой — почти половина бюджета кадра. Склейка стоит одной копии и
        # одного блита, но только при смене зума или раскладки владений.
        layer = self._land_layer().copy()
        layer.blit(raw, (0, 0))
        # Ключ кэша — без зума и без раскладки: держать сконвертированную копию
        # слоя на каждый зум, который игрок прокрутил, нельзя (на 2.2x это
        # 30 Мпикс), а слой в каждый момент существует ровно один.
        self._frame = display_ready(layer, ("frame",))
        self._frame_key = key
        return self._frame

    def _land_layer(self) -> pygame.Surface:
        """Рельеф текущего зума. Один кэшированный блит вместо пятидесяти."""
        return zoomed_surface(self._land, self.zoom, self._land_zoom_cache)

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

    def _cached_label(self, font, text: str) -> pygame.Surface:
        """Подпись поселения с тёмной обводкой, готовая к блиту.

        Обводка рисуется восемью смещёнными копиями глифа ПОВЕРХ кэшируемой
        поверхности, а не в кадре: иначе пятьдесят подписей стоили бы
        четырёхсот блитов вместо пятидесяти. Светлый глиф поверх тёмной
        обводки — как на референсе; раньше было наоборот, и на среднем тоне
        рельефа подпись выглядела меловой чертой.

        У крупных кеглей обводка на пиксель шире: у 13 px один пиксель съедает
        треть буквы, а у 27 px — уже нет, и одинаковая обводка делала бы
        столицу контрастнее деревни не по смыслу, а по кеглю.
        """
        key = (text, font.get_point_size(), _PLACE_INK, _PLACE_HALO)
        surf = self._label_cache.get(key)
        if surf is not None:
            return surf
        pad = 2 if font.get_point_size() >= 20 else 1
        raw = font.render(text, True, _PLACE_INK)
        surf = pygame.Surface((raw.get_width() + pad * 2, raw.get_height() + pad * 2),
                              pygame.SRCALPHA)
        halo = font.render(text, True, _PLACE_HALO)
        steps = ((0, 0), (1, 0), (0, 1), (1, 1),
                 (1, -1), (-1, 1), (-1, 0), (0, -1))
        if pad > 1:
            steps = steps + ((2, 0), (-2, 0), (0, 2), (0, -2),
                             (2, 1), (1, 2), (-2, 1), (-1, 2),
                             (2, -1), (1, -2), (-2, -1), (-1, -2),
                             (2, 2), (-2, -2), (2, -2), (-2, 2))
        for dx, dy in steps:
            surf.blit(halo, (pad + dx, pad + dy))
        surf.blit(raw, (pad, pad))
        if len(self._label_cache) >= _TEXT_CACHE_LIMIT:
            self._label_cache.clear()
        self._label_cache[key] = surf
        return surf

    def _fit_place_name(self, font, text: str, max_w: int) -> str:
        """Обрезать название поселения по ширине, вручную добавив многоточие.

        ``pygame.font`` не умеет многоточие, а встроить его в имя нельзя:
        подпись должна говорить, что название не поместилось, а не молчать.
        Режем по символам (названия графств — одно слово, резать по словам
        тут нечего) и обязательно оставляем многоточие. Результат кэшируется:
        подпись не меняется, а пересчёт ширины в кадре — работа напрасная.
        """
        if max_w <= 0:
            return ""
        key = (text, font.get_point_size(), int(max_w))
        fit = self._fit_cache.get(key)
        if fit is not None:
            return fit
        low, high, best = 1, len(text), ""
        if font.size(text)[0] <= max_w:
            # Название помещается целиком — многоточие тут было бы враньём,
            # оно читается как «дальше есть название, которое не влезло».
            best = text
        else:
            while low <= high:
                mid = (low + high) // 2
                cut = text[:mid] + "…"
                if font.size(cut)[0] <= max_w:
                    best, low = cut, mid + 1
                else:
                    high = mid - 1
        if len(self._fit_cache) >= _TEXT_CACHE_LIMIT:
            self._fit_cache.clear()
        self._fit_cache[key] = best
        return best

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

    def _render_move_route(self):
        """Маршрут приказной армии: пунктир через центроиды провинций.

        Без него игрок не видит, куда идёт армия и где цель — маршрут
        пропадал бы между ходами, и движение выглядело бы «само по себе».
        """
        order = self._move_order
        if order is None:
            return
        general, goal = order
        if general.province_idx is None or general not in self.generals:
            return
        path = self.find_province_path(general.province_idx, goal, general)
        if len(path) < 2:
            return
        pts = []
        for idx in path:
            cx, cy = self.provinces[idx].centroid
            sx, sy = self._world_to_screen(cx, cy)
            pts.append((sx, sy))
        pulse = 0.55 + 0.45 * abs(math.sin(pygame.time.get_ticks() * 0.004))
        col = (int(255 * pulse), int(210 * pulse), int(80 * pulse))
        for i in range(len(pts) - 1):
            x1, y1 = pts[i]
            x2, y2 = pts[i + 1]
            # пунктир: рисуем через один, иначе линия сплошная и сливается
            # с границей провинции
            steps = max(2, int(math.hypot(x2 - x1, y2 - y1) / 9))
            for s in range(0, steps, 2):
                a = s / steps
                b = min(1.0, (s + 1) / steps)
                pygame.draw.line(
                    self.screen, col,
                    (int(x1 + (x2 - x1) * a), int(y1 + (y2 - y1) * a)),
                    (int(x1 + (x2 - x1) * b), int(y1 + (y2 - y1) * b)), 2)
        gx, gy = pts[-1]
        pygame.draw.circle(self.screen, (255, 240, 150), (gx, gy), 7, 2)

    def _render(self):
        view_h = SCREEN_HEIGHT - 80
        # Море готовится один раз и блитится как есть. Раньше здесь стоял
        # pygame.transform.scale в тот же размер — то есть 4 мс на кадр
        # на ровно ничего, кроме лишней копии 1.6 млн пикселей.
        self.screen.blit(self.tex_manager.get_ocean_texture(SCREEN_WIDTH, view_h), (0, 0))

        # Местность и окантовка — одним блитом кэшированного слоя. Раньше это были
        # два больших слоя (рельеф и окантовка), и каждый стоил отдельный
        # полноэкранный блит с альфой.
        self.screen.blit(self._map_frame(), self._frame_origin_screen())

        if self._hover_province is not None:
            prov = self.provinces[self._hover_province]
            screen_poly = [self._world_to_screen(x, y) for x, y in prov.polygon]
            try:
                # Подсветка под курсором — два контура, а не заливка всей
                # провинции: полноэкранная SRCALPHA-поверхность на каждый кадр
                # стоила бы больше, чем весь остальной кадр вместе взятый.
                w_out = max(2, int(3.4 * self.zoom))
                w_in = max(1, int(1.4 * self.zoom))
                pygame.draw.polygon(self.screen, (28, 24, 14), screen_poly, w_out)
                pygame.draw.polygon(self.screen, (250, 238, 190), screen_poly, w_in)
            except Exception:
                pass

        self._render_rivers()
        self._render_settlements()
        self._render_selection()
        self._render_move_route()

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

    def _frame_origin_screen(self) -> Tuple[int, int]:
        """Левый верхний угол поверхности окантовки на экране."""
        return (int((self._frame_origin[0] - self.cam_x) * self.zoom),
                int((self._frame_origin[1] - self.cam_y) * self.zoom))

    def _render_settlements(self):
        """Кружки поселений, значки гарнизонов и подписи названий.

        Самое заметное, чего не хватало карте: подписано ВСЁ поселение, а не
        только города. Из пятидесяти провинций игрок видел единицы названий и
        не знал, что находится в остальных сорока девяти.

        Кружки рисуются всем и всегда — они мелкие и не спорят друг с другом.
        Подписи не помещаются все сразу, поэтому у каждой есть прямоугольник
        и шесть мест, куда она может встать; подпись, столкнувшаяся со всем,
        просто не рисуется. Приоритет: провинция под курсором, потом столица,
        город, деревня.

        Подпись не должна вылезать за КРАЙ КАРТЫ, а не только за край экрана:
        последние владения у обоих обрезов стоят вплотную к окантовке, и
        «Lightvale» или «Thornridge» уезжали за неё последними буквами. Поэтому
        прямоугольник каждой подписи прижимается к видимой части окантовки.

        Точка привязки подписи — центроид провинции, тот же, по которому
        клик и ховер ищут провинцию. Смещается только сама надпись, и только
        в свободную сторону, поэтому клик по названию всегда попадает в ту же
        провинцию.
        """
        view_h = SCREEN_HEIGHT - 80
        self._label_blits = 0
        # Видимая часть окантовки карты на экране: подписи не должны вылезать
        # за неё, но за пределы экрана тем более.
        bounds = self._visible_map_rect(view_h)
        dots: Dict[int, Tuple[int, int, int]] = {}
        for i, prov in enumerate(self.provinces):
            tier = _PLACE_TIERS.get(prov.region_type, 2)
            cx, cy = prov.centroid
            sx, sy = self._world_to_screen(cx, cy)
            if sx < -80 or sx > SCREEN_WIDTH + 80 or sy < -40 or sy > view_h + 40:
                continue
            r = _PLACE_RADIUS[tier]
            self._draw_settlement_mark(sx, sy, r, tier)
            self._draw_garrison_mark(sx, sy, r, prov)
            dots[i] = (sx, sy, r)

# Кружки и таблички знамён занимают место первыми: подпись, севшая на
        # соседний город или под табличку армии, читается хуже, чем подпись,
        # которую можно сдвинуть. Знамя рисуется ПОСЛЕ подписей, поэтому
        # подпись под ним не просто налезает — её разрезает пополам.
        dot_rects: Dict[int, List[pygame.Rect]] = {0: [], 1: [], 2: []}
        for i, (sx, sy, r) in dots.items():
            dot_rects[_PLACE_TIERS.get(self.provinces[i].region_type, 2)].append(
                pygame.Rect(sx - r - 1, sy - r - 1, r * 2 + 2, r * 2 + 2))
        plate_by_province: Dict[int, pygame.Rect] = {}
        for g in self.generals:
            if g.province_idx is None or g.province_idx >= len(self.provinces):
                continue
            cx, cy = self.provinces[g.province_idx].centroid
            gx, gy = self._world_to_screen(cx, cy - 18)
            plate = GeneralIcon._label_plate(f"{g.name} {g.troops}",
                                            max(10, int(12 * self.zoom)))
            rect = plate.get_rect()
            rect.midtop = (int(gx), int(gy) + int(12 * self.zoom))
            plate_by_province.setdefault(g.province_idx, rect)

        # Сеток столько же, сколько ступеней: grids[t] — это «занято для
        # подписи ступени t». Таблички и кружки попадают во все сетки от
        # своей ступени и выше, потому что подписи младших ступеней держат
        # расстояние от важных знаков; уже нарисованная подпись — во все.
        grids = [_RectGrid() for _ in range(len(dot_rects))]
        for rect in plate_by_province.values():
            for grid in grids:
                grid.add(rect)
        for tier, rects in dot_rects.items():
            for grid in grids[tier:]:
                for rect in rects:
                    grid.add(rect)

        order = self._place_order
        hover = self._hover_province
        if hover is not None:
            order = [hover] + [i for i in order if i != hover]
        for i in order:
            tier = _PLACE_TIERS.get(self.provinces[i].region_type, 2)
            if tier == 2 and self.zoom < _PLACE_VILLAGE_MIN_ZOOM and i != hover:
                continue
            dot = dots.get(i)
            if dot is None:
                continue
            sx, sy, r = dot
            font = self._place_fonts[tier]
            # Подпись справа от кружка — обычное место, но на этой карте
            # половина поселений стоит впритык к соседнему, и двух вариантов
            # (слева/справа) не хватало: часть названий молча пропадала. Теперь
            # мест шесть — справа, слева, сверху и снизу (по два уровня) — и
            # берётся первое свободное.
            need = max(_PLACE_LABEL_MIN_W,
                       int(font.get_height() * _PLACE_LABEL_MIN_CHARS_PER_LINE))
            own_plate = plate_by_province.get(i)
            if own_plate is not None:
                left_x, right_x = own_plate.left - 5, own_plate.right + 5
                top_y = own_plate.top - 3
            else:
                left_x, right_x = sx - r - 5, sx + r + 5
                top_y = sy - r - 4
            fh = font.get_height()
            candidates = (
                (right_x, 0, 0),
                (left_x, 1, 0),
                (top_y, 2, 1),
                (top_y - fh - 2, 2, 1),
                (top_y + 2 * fh, 3, 1),
                (top_y + 3 * fh, 3, 1),
            )
            grid = grids[tier]
            for anchor, mode, centred in candidates:
                if mode <= 1:
                    # Место считается до КРАЯ КАРТЫ, а не края экрана: иначе
                    # подпись у обреза влезает по ширине и уезжает за
                    # окантовку последними буквами.
                    room = (bounds.right - anchor - 4 if mode == 0
                            else anchor - bounds.left - 4)
                else:
                    room = _PLACE_LABEL_MAX_W
                max_w = min(_PLACE_LABEL_MAX_W, room)
                if max_w < need:
                    continue
                name = self._fit_place_name(font, self.provinces[i].name, max_w)
                if not name:
                    continue
                surf = self._cached_label(font, name)
                rect = surf.get_rect()
                if mode == 0:
                    rect.left = anchor
                    rect.top = sy - surf.get_height() // 2
                elif mode == 1:
                    rect.right = anchor
                    rect.top = sy - surf.get_height() // 2
                elif mode == 2:
                    rect.midtop = (int(sx), int(anchor))
                else:
                    rect.midbottom = (int(sx), int(anchor))
                # Прижим к видимой части окантовки — ПОСЛЕ расстановки и ДО
                # проверки наложений, иначе подпись, сдвинутая прижимом, могла
                # бы наехать на уже нарисованную и проверка это не увидела бы.
                if rect.width > bounds.width or rect.height > bounds.height:
                    continue
                rect.clamp_ip(bounds)
                if grid.hits(rect):
                    continue
                for each in grids:
                    each.add(rect)
                self.screen.blit(surf, rect.topleft)
                self._label_blits += 1
                break

    def _visible_map_rect(self, view_h: int) -> pygame.Rect:
        """Видимая часть окантовки карты на экране.

        Это и есть область, внутри которой обязаны целиком помещаться подписи
        поселений: за её правым и верхним краем карты просто нет, и буквы,
        выехавшие туда, обрезались краем кадра.
        """
        ox, oy = self._frame_origin_screen()
        w = int(round(self._frame_size[0] * self.zoom))
        h = int(round(self._frame_size[1] * self.zoom))
        rect = pygame.Rect(ox, oy, max(1, w), max(1, h))
        rect = rect.clip(pygame.Rect(2, 2, SCREEN_WIDTH - 4, max(1, view_h - 4)))
        return rect

    def _draw_settlement_mark(self, sx: int, sy: int, r: int, tier: int):
        """Кружок поселения: тёмный круг в светлой обводке, как на референсе.

        Размер по типу: столица — с точкой посередине и двойным кольцом,
        город — просто кольцо, деревня — мелкая точка. Размеры взяты из
        одного места (``_PLACE_RADIUS``) вместе с кеглем подписи, иначе
        столица могла бы оказаться мельче деревни.
        """
        pygame.draw.circle(self.screen, _PLACE_HALO, (sx, sy), r + 1)
        pygame.draw.circle(self.screen, _PLACE_INK, (sx, sy), max(1, r))
        if tier == 0:
            pygame.draw.circle(self.screen, _PLACE_HALO, (sx, sy), 3)
            pygame.draw.circle(self.screen, _PLACE_INK, (sx, sy), 2)
        elif tier == 1:
            pygame.draw.circle(self.screen, _PLACE_HALO, (sx, sy), 1)

    def _draw_garrison_mark(self, sx: int, sy: int, r: int, prov):
        """Значок башни у провинции с гарнизоном.

        Без него игрок не видел, где держава уже закрепилась: владение на
        карте выглядело писем на паузе — цвет есть, а защиты не видно.
        """
        if int(getattr(prov, "garrison", 0) or 0) <= 0:
            return
        tx = sx + r + 3
        ty = sy - r - 2
        pygame.draw.rect(self.screen, _PLACE_INK, (tx, ty, 4, 6))
        pygame.draw.rect(self.screen, _PLACE_INK, (tx - 1, ty - 1, 6, 1))
        pygame.draw.line(self.screen, _PLACE_HALO, (tx + 1, ty + 1), (tx + 1, ty + 4))


    def _render_rivers(self):
        t = pygame.time.get_ticks()

        for river_x in [RIVER_WEST_X, RIVER_EAST_X]:
            RiverRenderer.draw_river(self.screen, river_x, self.cam_x, self.cam_y,
                                     SCREEN_HEIGHT, t, zoom=self.zoom,
                                     land=self._land_mask)

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
        # Полоса под картой — не чёрная плашка, а часть карты: тёмный
        # пергамент с золотой нитью сверху. Раньше это был плоской заливкой
        # COLOR_HUD_BG, и он выглядел как чужое окно поверх рисунка.
        bar = pygame.Surface((SCREEN_WIDTH, 80), pygame.SRCALPHA)
        bar.fill((26, 23, 17, 236))
        bar.fill((96, 82, 46, 90), (0, 0, SCREEN_WIDTH, 2))
        bar.fill((58, 48, 26, 120), (0, 2, SCREEN_WIDTH, 1))
        self.screen.blit(bar, (0, hud_y))
        del bar

        turn_text = self._cached_text(
            self.font_hud,
            f"Turn: {self._turn} | LMB: select (drag-box, dbl=гарнизон) | "
            f"RMB: move/attack (Shift=queue) | Ctrl+1..9 /1..9: отряды | "
            f"S: стоп | Wheel:+/-: zoom | WASD: pan | SPACE: turn | TAB: dipl | "
            f"V: holdings | 0: reset",
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
            bg = pygame.Surface((tw + 10, th + 8), pygame.SRCALPHA)
            bg.fill((20, 18, 12, 214))
            pygame.draw.rect(bg, (176, 158, 104, 210), bg.get_rect(), 1)
            self.screen.blit(bg, (tx - 5, ty - 4))
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

    # ---------------- приказы и траты (этап 1.3b) ----------------
    #
    # Правила живут в states.py, здесь только их показ и вызов. Три правила,
    # которые блокируют всё остальное:
    #
    # * приказы выдаёт только СВОЙ король и только СВОЕМУ персонажу
    #   (_panel_allows_orders + _command_refusal в states);
    # * тратит казну только правитель королевства (_command_ruler в states);
    # * чужая держава — read-only.

    def _kingdom_realm(self):
        """Королевство игрока: единственное, чьими командами можно что-то делать."""
        return self._realm_of_nation(PLAYER_NATION)

    def _kingdom_ruler(self):
        """Живой король игрока — издатель всех приказов и плательщик всех трат.

        Король берётся из ``Realm.ruler_id``, а не «первым KING в
        ``hierarchy.characters``»: это ровно тот персонаж, которому states
        доверяет распоряжаться казной (``_command_ruler``).
        """
        realm = self._kingdom_realm()
        if realm is None or not realm.ruler_id:
            return None
        ruler = self.hierarchy.characters.get(realm.ruler_id)
        if ruler is None or not ruler.alive:
            return None
        return ruler

    def _selected_character(self):
        """Выбранный в панели персонаж или ``None``."""
        if not self._sel_character_id:
            return None
        return self.hierarchy.characters.get(self._sel_character_id)

    def _command_refusal_text(self, issuer, target) -> Optional[str]:
        """Почему сюзерен НЕ вправе приказать цели (``None`` — вправе).

        Повторяет публичные правила states (``COMMAND_MIN_RANK`` + сюзеренство),
        а НЕ лезет в приватный ``_command_refusal``: нужно не то, как states
        откажет, а то, что панель покажет ДО клика. Причина отказа states
        недоступна извне, поэтому формулировка здесь, а не выдумывается.
        """
        if issuer is None or not issuer.alive:
            return "король мёртв или не найден"
        if target is None or not target.alive:
            return "персонаж мёртв или не найден"
        required = COMMAND_MIN_RANK.get(target.rank)
        if required is None:
            return "королю не подчиняется никто"
        if issuer.tier < required:
            return f"{issuer.name}: не сюзерен {target.name}"
        liege = self.hierarchy.liege_of(target.id)
        if liege is None or liege.id != issuer.id:
            return f"{issuer.name}: не сюзерен {target.name}"
        return None

    def _order_issuer(self, target):
        """Кто выдаёт приказ ``target``.

        Обычно это король, но баронов states считает вассалами ГЕРЦОГА
        (``build_default_hierarchy``: сюзерен барона — держатель дукции), и
        ``_command_refusal`` откажет королю. Поэтому издатель — непосредственный
        сюзерен цели, а если им оказался король — он и есть. Это не обход
        правил, а их чтение: приказ должен выдать тот, кто вправе.
        """
        ruler = self._kingdom_ruler()
        liege = self.hierarchy.liege_of(target.id) if target is not None else None
        if liege is not None and liege.alive:
            return liege
        return ruler

    def _order_of(self, target_id: Optional[str]):
        """Последний приказ, ВИДЯЩИЙся в панели — включая закрытые.

        ``states.Hierarchy.order_of`` отдаёт только живой приказ
        (``PENDING``/``ACCEPTED``), а игроку нужно видеть и ``REFUSED``
        с причиной: отказ — это событие, а не отсутствие события. Поэтому
        берём его, а если живого нет — ищем последний закрытый по ``id``
        (порядок тот же детерминированный, что и в states).
        """
        if not target_id:
            return None
        live = self.hierarchy.order_of(target_id)
        if live is not None:
            return live
        closed = [o for o in self.hierarchy.orders.values()
                  if o.target_id == target_id]
        if not closed:
            return None
        return max(closed, key=lambda o: o.id)

    def _free_county_of(self, realm) -> Optional[int]:
        """Первое по номеру графство королевства, которым ещё не пожаловали.

        Нужна цель для приказов «выдать землю» и «застроить»: сам игрок её не
        выбирает, поэтому берётся первая свободная, а её номер показывается в
        строке приказа — приказ не выдаётся «в никуда».
        """
        if realm is None:
            return None
        return self._turn_cached(
            (_TC_FREE_COUNTY, realm.id),
            lambda: self._scan_free_county(realm.nation))

    def _scan_free_county(self, nation: str) -> Optional[int]:
        """Собственный поиск свободного графства — один раз на ход."""
        held = {ch.province_idx for ch in self.hierarchy.characters.values()
                if ch.province_idx is not None}
        for idx, prov in enumerate(self.provinces):
            if idx not in held and prov.owner == nation:
                return idx
        return None

    def _order_specs(self, target, realm) -> List[Dict]:
        """Строки блока «ПРИКАЗЫ» для выбранного персонажа.

        Каждая строка — словарь ``kind``/``text``/``color``/``enabled``/
        ``args``/``order_kind``. ``enabled=False`` означает «серым ДО клика», а
        не отказ по факту; ``args`` уходит в ``states.issue_order``.

        Виды отбираются по правилам, а не по вкусу: цель обязана быть живым
        вассалом издателя (``COMMAND_MIN_RANK``), а у каждого вида — своя
        осмысленность аргументов (см. ``_order_args_refusal`` в states).
        """
        specs: List[Dict] = []
        issuer = self._order_issuer(target)
        refusal = self._command_refusal_text(issuer, target)
        # левейс/застройку исполняет realm ИЗДАТЕЛЯ приказа (states._apply_order
        # берёт realm правителя), поэтому деньги и цена считаются от realm'а
        # издателя, а не от realm'а цели
        purse = self._issuer_realm(issuer)
        # корона нужна и тяжёлому налогу, поэтому её лимит — общий с приказом
        crown = purse.crown_authority if purse is not None else 0

        for kind, label in _ORDER_ROWS:
            row = self._order_row(kind, target, realm, issuer, purse, crown)
            if row is None:
                continue
            # применимый вид гасим не только по деньгам: строка недоступна
            # также тогда, когда издатель вообще не вправе командовать целью
            enabled = bool(row["enabled"]) and refusal is None
            specs.append({
                "kind": "order",
                "order_kind": kind,
                "label": label,
                "char_id": target.id,
                "text": self._order_row_text(label, row["note"], row["cost"]),
                "color": _ACT_OK if enabled else _ACT_OFF,
                "enabled": enabled,
                "args": row["args"],
                "refusal": refusal,
                "why": row["why"] if row["why"] is not None else refusal,
            })
        return specs

    def _issuer_realm(self, issuer):
        """Королевство, из казны которого идёт приказ издателя.

        У короля оно своё (``Realm.ruler_id``), у герцога — realm его нации.
        Ровно то же, что считает states (см. ``_realm_of_actor``), но своими
        словами: приватный метод иерархии из UI звать нельзя.
        """
        if issuer is None:
            return None
        if issuer.rank is TitleRank.KING:
            realm = self.hierarchy.realms.get(issuer.realm_id or "")
            if realm is not None:
                return realm
        for realm_id in sorted(self.hierarchy.realms):
            realm = self.hierarchy.realms[realm_id]
            if realm.nation == issuer.nation:
                return realm
        return None

    def _order_row(self, kind: OrderKind, target, realm, issuer,
                   purse, crown) -> Optional[Dict]:
        """Одна строка приказа или ``None``, если вид к этой цели неприменим.

        Разница двух исходов принципиальна и потому вынесена в тип возврата:

        * ``None`` — вид неприменим ВООБЩЕ (королю нельзя приказать, у цели
          нет ранга, для которого вид существует). Такую строку панель не
          показывает: она была бы шумом;
        * ``enabled=False`` — вид применим, но сейчас нельзя (нет золота,
          потолок исчерпан, лимит хода). Такая строка ВИДНА и серым, потому
          что игрок должен видеть недоступность до клика.
        """
        if target is None:
            return None

        # ---- SUMMON_COUNCIL: аргументов нет, единственное действие без цены ----
        if kind is OrderKind.SUMMON_COUNCIL:
            return {
                "args": None, "cost": None, "enabled": True, "why": None,
                "note": f"+{COUNCIL_INFLUENCE} влияния "
                        f"+{COUNCIL_LOYALTY} лояльности, бесплатно",
            }

        # ---- GIFT: цена платится ИЗ КОШЕЛЯ СЮЗЕРЕНА (states.purse_of) ----
        if kind is OrderKind.GIFT:
            effect = self._gift_effect(target)
            has = issuer is not None and self.hierarchy.purse_of(issuer) >= GIFT_COST
            enabled = has and effect is not None
            return {
                "args": None, "cost": GIFT_COST, "enabled": enabled,
                "why": None if enabled else ("не хватает золота" if not has
                                             else "отдача от подарков иссякла"),
                "note": effect or "подарки больше не дают ничего",
            }

        # ---- SET_CONTRACT: единственный приказ, который сам платит королю ----
        if kind is OrderKind.SET_CONTRACT:
            level = self._next_contract_level(target)
            if level is None:
                return {
                    "args": None, "cost": None, "enabled": False,
                    "why": f"высший контракт "
                           f"({CONTRACT_LEVELS[target.contract_level]['name']})",
                    "note": "выше уровня нет",
                }
            spec = CONTRACT_LEVELS[level]
            return {
                "args": {"level": level}, "cost": None, "enabled": True, "why": None,
                "note": f"{spec['name']}: налог{spec['tax']}% "
                        f"левейс{spec['levy']}% тир+{spec['tyranny']}",
            }

        # ---- REVOKE_FIEF: применять имеет смысл, только если земля есть ----
        if kind is OrderKind.REVOKE_FIEF:
            if target.province_idx is None:
                return {"args": None, "cost": None, "enabled": False,
                        "why": "у него нет земли", "note": "отзывать нечего"}
            return {
                "args": None, "cost": None, "enabled": True, "why": None,
                "note": f"отзыв #{target.province_idx} "
                        f"{self.provinces[target.province_idx].name}: "
                        f"−{self._order_penalty(kind)} мнения, земля отнимается",
            }

        # ---- GRANT_FIEF: земля должна быть СВОБОДНОЙ (обмен только через отзыв,
        #      см. states._grant_fief_refusal), поэтому у уже держащего барона
        #      вида нет вовсе, а не «есть, но серый» ----
        if kind is OrderKind.GRANT_FIEF:
            if target.province_idx is not None:
                return None
            idx = self._free_county_of(purse)
            if idx is None:
                return {"args": None, "cost": None, "enabled": False,
                        "why": "нет свободного графства", "note": "земли нет"}
            return {
                "args": {"province_idx": idx}, "cost": None, "enabled": True,
                "why": None,
                "note": f"выдать #{idx} {self.provinces[idx].name}",
            }

        # ---- RAISE_LEVY: левейс поднимает ТОЛЬКО король (states._realm_of_ruler
        #      возвращает realm только у KING), поэтому герцогу вид недоступен ----
        if kind is OrderKind.RAISE_LEVY:
            if purse is None or issuer is None or issuer.rank is not TitleRank.KING:
                return {"args": None, "cost": None, "enabled": False,
                        "why": "левейс поднимает только король",
                        "note": "только королю"}
            cost = LEVY_COST_PER_BLOCK
            cap = self._turn_cached((_TC_REALM_LEVY, purse.id),
                                    lambda: self.hierarchy.realm_levy(purse.id))
            raised = int(getattr(purse, "raised_levy", 0))
            gold = self._gold_left(purse)
            why = None
            if gold < cost:
                why = f"не хватает золота ({gold}/{cost})"
            elif raised + LEVY_BLOCK_TROOPS > int(cap):
                why = f"левейс исчерпан ({raised}/{int(cap)})"
            return {
                "args": {"blocks": 1, "realm_id": purse.id}, "cost": cost,
                "enabled": why is None, "why": why,
                "note": f"+{LEVY_BLOCK_TROOPS} солдат, всего {raised}/{int(cap)}",
            }

        # ---- DEVELOP_COUNTY: states требует realm.ruler_id == actor.id, то есть
        #      заказывает и платит правитель realm'а, то есть король ----
        if kind is OrderKind.DEVELOP_COUNTY:
            if purse is None or issuer is None or issuer.rank is not TitleRank.KING:
                return {"args": None, "cost": None, "enabled": False,
                        "why": "застройку заказывает и оплачивает король",
                        "note": "только королю"}
            idx = self._free_county_of(purse)
            if idx is None:
                return {"args": None, "cost": None, "enabled": False,
                        "why": "нет своего графства", "note": "земли нет"}
            prov = self.provinces[idx]
            dev = int(getattr(prov, "development", 1) or 1)
            if dev >= DEVELOPMENT_MAX:
                return {"args": None, "cost": None, "enabled": False,
                        "why": f"застроен максимум ({DEVELOPMENT_MAX})",
                        "note": "потолок"}
            cost = development_upgrade_cost(dev)
            gold = self._gold_left(purse)
            why = None if gold >= cost else f"не хватает золота ({gold}/{cost})"
            return {
                "args": {"province_idx": idx}, "cost": cost,
                "enabled": why is None, "why": why,
                "note": f"#{idx} {prov.name}: застройка {dev}→{dev + 1}",
            }
        return None

    def _next_contract_level(self, target) -> Optional[int]:
        """Следующий уровень контракта или ``None``, если уже высший."""
        level = int(getattr(target, "contract_level", 0)) + 1
        if level > len(CONTRACT_LEVELS) - 1:
            return None
        return level

    def _gift_effect(self, target) -> Optional[str]:
        """Реальная отдача подарка ЭТОМУ персонажу или ``None``, если иссякла.

        Отдача падает по числу подарков за ЖИЗНЬ (``gifts_received``), поэтому
        считается по счётчику цели, а не «вообще +15/+10»: иначе панель
        обещала бы игроку прибавку, которой не будет.
        """
        got = int(getattr(target, "gifts_received", 0))
        opinion = gift_gain(got, GIFT_OPINION_BY_COUNT)
        loyalty = gift_gain(got, GIFT_LOYALTY_BY_COUNT)
        if opinion <= 0 and loyalty <= 0:
            return None
        return f"+{opinion} мнения +{loyalty} лояльности"

    def _order_row_text(self, label: str, note: Optional[str],
                        cost: Optional[int]) -> str:
        """Текст строки приказа: вид · цена · последствия.

        Короткие подписи не случайны: правый столбец панели — 268 px, и
        длинная расшифровка последствий съедала бы соседние строки (проверка
        по ширине в _blit_panel_text — страховка, а не основной механизм).
        """
        parts = [label]
        if cost is not None:
            parts.append(f"{cost}з")
        if note:
            parts.append(note)
        return " · ".join(parts)

    def _order_penalty(self, kind: OrderKind) -> int:
        """На сколько мнения просядет вассал, ОТКАЗАВШИсь от приказа этого вида.

        Ровно то, что states посчитает в ``resolve_orders`` (``Order.
        refusal_penalty``), но без создания приказа: панель показывает цену
        отказа ДО выдачи, иначе игрок узнаёт о ней задним числом.
        """
        return REFUSED_WEIGHT * order_weight(kind)

    def _gold_left(self, purse) -> int:
        """Сколько золота осталось у королевства."""
        return int(getattr(purse, "gold", 0)) if purse is not None else 0

    def _spend_specs(self, realm) -> List[Dict]:
        """Строки блока «ТРАТЫ» в шапке королевства.

        Цена и текущее значение показываются ДО клика и всегда из констант
        states. Недоступное гасится серым: ``enabled`` — это «золота хватает и
        потолок не исчерпан», а не «команда вообще существует».
        """
        specs: List[Dict] = []
        if realm is None:
            return specs
        gold = int(getattr(realm, "gold", 0))
        prestige = int(getattr(realm, "prestige", 0))

        # левейс: цена блока и потолок всего левейса realm'а
        levy_cap = self._turn_cached((_TC_REALM_LEVY, realm.id),
                                     lambda: self.hierarchy.realm_levy(realm.id))
        raised = int(getattr(realm, "raised_levy", 0))
        levy_ok = gold >= LEVY_COST_PER_BLOCK \
            and raised + LEVY_BLOCK_TROOPS <= int(levy_cap)
        specs.append({
            "kind": "spend", "action": "raise_levy", "label": "левейс",
            "text": f"левейс {LEVY_COST_PER_BLOCK}з · поднято {raised}/{int(levy_cap)}",
            "cost": LEVY_COST_PER_BLOCK,
            "enabled": levy_ok,
            "why": None if levy_ok else ("не хватает золота" if gold < LEVY_COST_PER_BLOCK
                                         else "левейс исчерпан"),
        })

        # корона: платится золотом И престижем, поэтому гасится по обоим
        crown_ok = gold >= CROWN_COST and prestige >= CROWN_PRESTIGE_COST
        crown_full = int(getattr(realm, "crown_authority", 0)) >= MAX_CROWN_AUTHORITY
        specs.append({
            "kind": "spend", "action": "raise_crown_authority", "label": "корона",
            "text": (f"корона {CROWN_COST}з+{CROWN_PRESTIGE_COST}прест · "
                     f"власть {int(getattr(realm, 'crown_authority', 0))}/{MAX_CROWN_AUTHORITY}"),
            "cost": CROWN_COST,
            "enabled": crown_ok and not crown_full,
            "why": ("власть короны предельна" if crown_full else
                    (None if crown_ok else "не хватает золота или престижа")),
        })

        # наёмники: цена за блок, тиры видны только ПОСЛЕ найма (states так
        # решил), поэтому здесь показывается их количество, а не качество
        tiers = list(getattr(realm, "mercenary_tiers", []) or [])
        merc_ok = gold >= MERC_COST_PER_BLOCK
        specs.append({
            "kind": "spend", "action": "hire_mercenaries", "label": "наёмники",
            "text": (f"наёмники {MERC_COST_PER_BLOCK}з/блок по {MERC_BLOCK_TROOPS} · "
                     f"наймлено {len(tiers)} блоков, лимит {MERC_MAX_BLOCKS_PER_TURN}/ход"),
            "cost": MERC_COST_PER_BLOCK,
            "enabled": merc_ok,
            "why": None if merc_ok else "не хватает золота",
        })

        # налог: значение 0..TAX_POLICY_MAX, тяжёлый только при короне
        policy = int(getattr(realm, "tax_policy", 0))
        crown = int(getattr(realm, "crown_authority", 0))
        # кнопка переключает политику туда-обратно, поэтому «доступно» означает
        # «можно переключить»: значение отличается от текущего И (если оно
        # тяжёлое) корона дотягивает
        nxt = TAX_POLICY_MIN if policy != TAX_POLICY_MIN else TAX_POLICY_MAX
        tax_ok = nxt != policy and (nxt <= 0 or crown >= TAX_POLICY_CROWN_AUTHORITY)
        specs.append({
            "kind": "spend", "action": "set_tax_policy", "label": "налог",
            "text": f"налог {policy}→{nxt} из {TAX_POLICY_MIN}..{TAX_POLICY_MAX} · "
                    f"корона {crown}/{TAX_POLICY_CROWN_AUTHORITY}",
            "cost": 0,
            "enabled": tax_ok,
            "why": None if tax_ok else "тяжёлый налог требует короны",
        })
        for spec in specs:
            spec["color"] = _ACT_OK if spec["enabled"] else _ACT_OFF
            spec["char_id"] = None
            spec["county_idx"] = None
        return specs

    def _county_spend_specs(self, idx: int, realm) -> List[Dict]:
        """Две кнопки под строкой графства: застройка и гарнизон.

        Платит казна того королевства, которое ФАКТИЧЕСКИ владеет провинцией
        (так же, как в states), поэтому ``realm`` здесь может быть и чужим для
        панели — но кнопки кликабельны только у своей нации.

        Порядок кнопок задан ``_COUNTY_SPEND_ROWS``, а не порядком расчёта,
        чтобы перестановка в коде не тасовала их на экране.
        """
        specs: List[Dict] = []
        prov = self.provinces[idx]
        gold = int(getattr(realm, "gold", 0)) if realm is not None else 0
        owned = realm is not None and prov.owner == realm.nation

        dev = int(getattr(prov, "development", 1) or 1)
        dev_cost = development_upgrade_cost(dev)
        dev_why = None
        if not owned:
            dev_why = "не наша земля"
        elif gold < dev_cost:
            dev_why = f"не хватает золота ({gold}/{dev_cost})"
        elif dev >= DEVELOPMENT_MAX:
            dev_why = f"застроен максимум ({DEVELOPMENT_MAX})"

        cap = self.hierarchy.garrison_cap(idx)
        garrison = int(getattr(prov, "garrison", 0) or 0)
        take = min(GARRISON_CAP_PER_FORT, max(0, int(cap) - garrison))
        gar_cost = take * GARRISON_RECRUIT_COST_PER_100 // 100
        gar_why = None
        if not owned:
            gar_why = "не наша земля"
        elif take <= 0:
            gar_why = f"гарнизон полон ({garrison}/{int(cap)})"
        elif gold < gar_cost:
            gar_why = f"не хватает золота ({gold}/{gar_cost})"

        built = {
            "develop": {
                "kind": "county_spend", "action": "develop", "label": "застройка",
                "county_idx": idx, "char_id": None,
                "text": f"застройка {dev}→{dev + 1} {dev_cost}з",
                "cost": dev_cost, "enabled": dev_why is None, "why": dev_why,
            },
            "garrison": {
                "kind": "county_spend", "action": "garrison", "label": "гарнизон",
                "county_idx": idx, "char_id": None,
                "text": f"гарнизон +{take} {gar_cost}з",
                "cost": gar_cost, "enabled": gar_why is None, "why": gar_why,
            },
        }
        for action, label in _COUNTY_SPEND_ROWS:
            spec = built[action]
            spec["color"] = _ACT_OK if spec["enabled"] else _ACT_OFF
            specs.append(spec)
        return specs

    def _panel_hotkey_action(self, key: int) -> Optional[str]:
        """Действие панели по клавише или ``None``, если эта клавиша не ours."""
        for hot, action in _PANEL_HOTKEYS:
            if hot == key:
                return action
        return None

    def _panel_run_action(self, action: str, county_idx: Optional[int] = None):
        """Выполнить действие панели по строке ``order:<вид>`` / ``spend:<метод>``.

        Разбор строки вместо трёх словарей: подсказка в панели, хоткей и клик
        по строке идут через ОДНО и то же значение, поэтому они не могут
        разойтись (см. ``_PANEL_HOTKEYS``). Перед «:» — ЧТО делаем, после — чем:
        ``order`` — вид приказа, ``spend`` — команда траты королевства,
        ``county`` — команда траты провинции (ей нужен номер графства).
        """
        scope, _, name = action.partition(":")
        if scope == "order":
            self._issue_order_to_selection(name)
        elif scope == "spend":
            self._spend_kingdom(name)
        elif scope == "county":
            self._spend_county(county_idx, name)

    def _issue_order_to_selection(self, kind_name: str):
        """Выдать приказ ``kind_name`` выбранному персонажу от его сюзерена.

        Клик по строке приказа и хоткей приводят сюда же. Аргументы берутся из
        той же раскладки, что нарисована на экране: пересборка «на всякий случай»
        дала бы шанс выдать другой номер графства, чем показано в строке.

        Отказ states возвращает ``None`` БЕЗ причины (``issue_order`` молчит),
        поэтому текст формируется здесь: сначала своя проверка прав (её текст
        настоящий), а если права были и всё равно ``None`` — честное «правила
        отклонили, причина недоступна», без выдуманной причины.
        """
        if not self._panel_allows_orders():
            self._panel_notice = "чужая держава: приказы только своей нации"
            self._invalidate_panel()
            return
        target = self._selected_character()
        issuer = self._order_issuer(target)
        refusal = self._command_refusal_text(issuer, target)
        if refusal is not None:
            self._panel_notice = f"приказ не выдан: {refusal}"
            self._invalidate_panel()
            return
        specs = self._order_specs(target, self._kingdom_realm())
        match = next((s for s in specs if s["order_kind"].value == kind_name), None)
        if match is None:
            self._panel_notice = f"вид приказа «{kind_name}» неприменим к этой цели"
            self._invalidate_panel()
            return
        if not match["enabled"]:
            self._panel_notice = f"приказ не выдан: {match['why'] or 'недоступно'}"
            self._invalidate_panel()
            return
        order = self.hierarchy.issue_order(issuer.id, kind_name, target.id,
                                           match["args"])
        if order is None:
            self._panel_notice = (f"правила иерархии отклонили приказ "
                                 f"(вид «{kind_name}»), причина недоступна")
        else:
            self._panel_notice = (f"приказ «{match['label']}» выдан {target.name}: "
                                 f"{_ORDER_STATUS_TEXT.get(order.status, 'выдан')}")
        self._invalidate_panel()

    def _punish_order_of_selection(self):
        """Наказать вассала за неисполненный (ACCEPTED) приказ."""
        if not self._panel_allows_orders():
            self._panel_notice = "чужая держава: наказание только своей нации"
            self._invalidate_panel()
            return
        target = self._selected_character()
        order = self._order_of(target.id if target is not None else None)
        if order is None:
            self._panel_notice = "наказывать нечего: приказа нет"
            self._invalidate_panel()
            return
        if order.status is not OrderStatus.ACCEPTED:
            self._panel_notice = (f"наказать можно только ACCEPTED, "
                                 f"у приказа «{order.status.value}»")
            self._invalidate_panel()
            return
        ruler = self._kingdom_ruler()
        issuer = self._order_issuer(target) or ruler
        events = self.hierarchy.punish_order(order.id, by_actor=issuer.id)
        self._panel_notice = events[0] if events else "наказать не вышло"
        self._invalidate_panel()

    def _spend_kingdom(self, action: str):
        """Трата казны королевства по имени метода states.

        Сигнатуры команд в states разные (``realm_id, blocks`` / ``realm_id`` /
        ``realm_id, policy``), поэтому аргументы собираются здесь, по имени
        действия из ``_SPEND_ROWS``. Актора передавать не нужно: ``raise_levy``,
        ``raise_crown_authority``, ``hire_mercenaries`` и ``set_tax_policy``
        берут правителя сами (``_command_ruler``), то есть короля. Для
        команд ПРОВИНЦИИ (``develop_county``, ``hire_garrison``) актор —
        обязательный второй позиционный, и там передаётся ``ruler.id``.
        """
        if not self._panel_allows_orders():
            self._panel_notice = "чужая держава: траты только своей нации"
            self._invalidate_panel()
            return
        realm = self._kingdom_realm()
        if realm is None:
            self._panel_notice = "королевство не найдено"
            self._invalidate_panel()
            return
        method = getattr(self.hierarchy, action, None)
        if method is None:
            self._panel_notice = f"команда {action} недоступна"
            self._invalidate_panel()
            return
        if action == "raise_levy":
            events = method(realm.id, 1)
        elif action == "raise_crown_authority":
            events = method(realm.id)
        elif action == "hire_mercenaries":
            events = method(realm.id, 1)
        elif action == "set_tax_policy":
            # кнопка переключает политику туда-обратно между крайними
            # значениями states (TAX_POLICY_MIN..TAX_POLICY_MAX)
            current = int(getattr(realm, "tax_policy", 0))
            nxt = TAX_POLICY_MIN if current != TAX_POLICY_MIN else TAX_POLICY_MAX
            events = method(realm.id, nxt)
        else:
            self._panel_notice = f"команда {action} не подключена к панели"
            self._invalidate_panel()
            return
        if not events:
            self._panel_notice = f"{action}: отказ без сообщения (причина недоступна)"
        else:
            self._panel_notice = events[0]
        self._invalidate_panel()

    def _spend_county(self, idx: int, action: str):
        """Трата по провинции: застройка или гарнизон, от лица короля.

        Актор передаётся явно: ``develop_county``/``hire_garrison`` платят из
        казны того realm'а, который ФАКТИЧЕСКИ владеет провинцией, и требуют
        правителя именно его (``_command_ruler(realm_id, actor_id)``).
        """
        if not self._panel_allows_orders():
            self._panel_notice = "чужая держава: траты только своей нации"
            self._invalidate_panel()
            return
        if not isinstance(idx, int) or not 0 <= idx < len(self.provinces):
            self._panel_notice = "графство не выбрано"
            self._invalidate_panel()
            return
        ruler = self._kingdom_ruler()
        if ruler is None:
            self._panel_notice = "король мёртв: тратить нечем"
            self._invalidate_panel()
            return
        if action == "develop":
            events = self.hierarchy.develop_county(idx, ruler.id)
        elif action == "garrison":
            # нанимаем ровно на одну сотню (GARRISON_CAP_PER_FORT): states
            # обрезает по потолку стен, поэтому «побольше» означало бы лишь
            # переплату без солдат
            cap = self.hierarchy.garrison_cap(idx)
            garrison = int(getattr(self.provinces[idx], "garrison", 0) or 0)
            take = min(GARRISON_CAP_PER_FORT, max(0, int(cap) - garrison))
            events = self.hierarchy.hire_garrison(idx, take, ruler.id)
        else:
            self._panel_notice = f"трата графства {action} не подключена"
            self._invalidate_panel()
            return
        self._panel_notice = events[0] if events else f"{action}: отказ без сообщения"
        self._invalidate_panel()

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
        ``panel``        — прямоугольник панели на экране;
        ``title``        — заголовок, ``nation`` — строка нации;
        ``realm``        — шапка королевства или None;
        ``duchies``      — строки герцогств, ``contracts`` — строки контрактов;
        ``counties``     — строки графств (province_idx);
        ``spends``       — блок «ТРАТЫ» шапки королевства (левейс/корона/…);
        ``county_spends``— кнопки «застройка»/«гарнизон» под строкой графства;
        ``vassals``      — правый столбец: живые персонажи нации (char_id);
        ``orders``       — блок «ПРИКАЗЫ» выбранному персонажу;
        ``order_status`` — строка статуса текущего приказа (или None);
        ``order_punish`` — кнопка «наказать» (или None);
        ``notice``       — последняя причина отказа/событие (или None);
        ``vassal_box``   — прямоугольник всего правого столбца;
        ``hint``         — строка подсказки, ``notes`` — служебные пояснения.

        Каждая строка — это dict с ключами ``kind`` (``realm``/``duchy``/
        ``contract``/``county``/``vassal``/``spend``/``county_spend``/``order``/
        ``punish``), ``rect`` (экранный прямоугольник), ``text``, ``color``,
        ``font`` и идентификатором: ``char_id`` персонажа, ``duchy_id``
        герцогства, ``county_idx`` провинции, ``action``/``order_kind`` — что
        действие делает. Одну и ту же раскладку читают и отрисовка, и
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
                "text": "COURT", "color": _ACT_HEAD, "font": self.font_small,
            },
            "hint": {
                "kind": "hint",
                "rect": R(_PANEL_PAD, _PANEL_HINT_Y, _PANEL_TREE_W, _PANEL_ROW_H + 2),
                # подсказка с хоткеями: текст собирается из _PANEL_HOTKEYS, иначе
                # привязку и надпись правили бы в двух местах
                "text": self._panel_hint_text(),
                "color": (170, 155, 130), "font": self.font_small,
            },
            "realm": None,
            "duchies": [],
            "contracts": [],
            "counties": [],
            "vassals": [],
            "spends": [],
            "county_spends": [],
            "orders": [],
            "order_head": None,
            "order_status": None,
            "order_punish": None,
            "notice": None,
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

            # ---- блок «ТРАТЫ» в шапке королевства ----
            # Траты своей нации кликабельны, чужой — серые и с подписью: чужая
            # держава read-only (см. _panel_allows_orders).
            for action, label in _SPEND_ROWS:
                if y > max_y:
                    break
                spec = next((s for s in self._spend_specs(realm)
                             if s["action"] == action), None)
                if spec is None:
                    continue
                row = dict(spec)
                # action сразу с префиксом области: обработчик клика и хоткей
                # разбирают одну и ту же строку и не должны знать, откуда она
                row["action"] = f"spend:{spec['action']}"
                # selectable = own И enabled: серая кнопка обязана быть и
                # некликабельной, иначе клик уводил бы в states, где причина
                # отказа появится только постфактум — ровно то, чего блок
                # «доступно до клика» и добивается
                row["selectable"] = own and bool(spec["enabled"])
                if not own:
                    # приглушаем строку; текст не выдумывается — у чужой нации
                    # кнопок нет вовсе, и это правда
                    row["color"] = _ACT_OFF
                    row["text"] = f"{label}: только чтение"
                row["rect"] = R(x + 14, y, _PANEL_TREE_W - 14, _PANEL_ACT_H)
                row["font"] = self.font_small
                lay["spends"].append(row)
                y += _PANEL_ACT_H
            # Правило цены застройки — единственное, что игрок не угадывает из
            # самой суммы: показываем формулу из констант states, а не число.
            if y + _PANEL_ACT_H <= max_y:
                lay["notes"].append({
                    "kind": "note",
                    "rect": R(x + 14, y, _PANEL_TREE_W - 14, _PANEL_ACT_H),
                    "text": f"застройка: {DEV_COST_BASE}+{DEV_COST_STEP}×уровень",
                    "color": COLOR_HUD_TEXT_DIM, "font": self.font_small,
                })
                y += _PANEL_ACT_H

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

                    # ---- две кнопки под графством: застройка и гарнизон ----
                    # Ровно одна строка на оба действия: под каждым графством
                    # их по две, а высота дерева ограничена, поэтому две строки
                    # съели бы половину панели.
                    if y + _PANEL_ACT_H <= max_y:
                        half = (_PANEL_TREE_W - 28) // 2
                        for slot, spec in enumerate(self._county_spend_specs(i, realm)):
                            row = dict(spec)
                            row["action"] = f"county:{spec['action']}"
                            row["selectable"] = own and bool(spec["enabled"])
                            if not own:
                                row["color"] = _ACT_OFF
                                row["text"] = f"{spec['label']}: только чтение"
                            row["rect"] = R(x + 28 + slot * half, y, half, _PANEL_ACT_H)
                            row["font"] = self.font_small
                            lay["county_spends"].append(row)
                        y += _PANEL_ACT_H

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

        # ---- блоки «ПРИКАЗЫ» и статус приказа ----
        # Живут под списком двора в том же столбце: он короче дерева владений,
        # и блок приказов относится к выбранному персонажу, а не к земле.
        self._layout_order_block(lay, R, vy, max_y)

        # ---- строка последнего события панели ----
        if self._panel_notice:
            lay["notice"] = {
                "kind": "notice",
                "rect": R(_PANEL_PAD, _PANEL_HINT_Y - _PANEL_ROW_H - 2,
                          _PANEL_W - 2 * _PANEL_PAD, _PANEL_ROW_H + 2),
                "text": self._panel_notice,
                "color": (235, 200, 140), "font": self.font_small,
            }
        return lay

    def _layout_order_block(self, lay: Dict, R, vy: int, max_y: int):
        """Разложить блок «ПРИКАЗЫ», статус приказа и кнопку «наказать».

        Отдельный метод, а не хвост ``_build_panel_layout``: блок sizeable
        (до семи строк приказов плюс статус и наказание) и не должен
        раздувать тело раскладки, где идёт дерево владений.
        """
        target = self._selected_character()
        own = self._panel_allows_orders()
        y = vy + _PANEL_BLOCK_GAP

        if not own:
            lay["notes"].append({
                "kind": "note",
                "rect": R(_PANEL_COL2_X, y, _PANEL_COL2_W, _PANEL_ROW_H),
                "text": "Приказы и траты — только своей нации",
                "color": COLOR_HUD_TEXT_DIM, "font": self.font_small,
            })
            return
        if target is None:
            lay["notes"].append({
                "kind": "note",
                "rect": R(_PANEL_COL2_X, y, _PANEL_COL2_W, _PANEL_ROW_H),
                "text": "Выберите персонажа (клик или ↑↓)",
                "color": COLOR_HUD_TEXT_DIM, "font": self.font_small,
            })
            return
        if target.rank is TitleRank.KING:
            lay["notes"].append({
                "kind": "note",
                "rect": R(_PANEL_COL2_X, y, _PANEL_COL2_W, _PANEL_ROW_H),
                "text": f"{target.name}: королю приказы не выдают",
                "color": COLOR_HUD_TEXT_DIM, "font": self.font_small,
            })
            return

        # заголовок блока со сроком и лимитом из states — игрок видит, что
        # приказ не вечен и что за ход их выдаётся не больше ORDERS_ISSUED_PER_TURN
        lay["order_head"] = {
            "kind": "order_head",
            "rect": R(_PANEL_COL2_X, y, _PANEL_COL2_W, _PANEL_ROW_H),
            "text": f"ПРИКАЗЫ: {target.name} ({ORDERS_ISSUED_PER_TURN}/ход, "
                    f"срок {ORDER_DEADLINE_TURNS})",
            "color": _ACT_HEAD, "font": self.font_small,
        }
        y += _PANEL_ROW_H

        for spec in self._order_specs(target, self._kingdom_realm()):
            if y > max_y:
                break
            row = dict(spec)
            row["action"] = f"order:{spec['order_kind'].value}"
            row["selectable"] = bool(spec["enabled"])
            row["rect"] = R(_PANEL_COL2_X, y, _PANEL_COL2_W, _PANEL_ACT_H)
            row["font"] = self.font_small
            lay["orders"].append(row)
            y += _PANEL_ACT_H

        # строка статуса: показывает, что висит за целью прямо сейчас
        order = self._order_of(target.id)
        if order is not None and y <= max_y:
            status_text = _ORDER_STATUS_TEXT.get(order.status, order.status.value)
            lay["order_status"] = {
                "kind": "order_status",
                "rect": R(_PANEL_COL2_X, y, _PANEL_COL2_W, _PANEL_ACT_H),
                "char_id": target.id, "county_idx": None, "duchy_id": None,
                "index": None, "selectable": False,
                "text": f"{order.id}: {status_text} (ход {order.turn_issued}) "
                        f"— {order.message}",
                "color": _ORDER_STATUS_COLOR.get(order.status, COLOR_HUD_TEXT),
                "font": self.font_small,
            }
            y += _PANEL_ACT_H
            # наказать можно ТОЛЬКО принятый и не исполненный приказ: отказ не
            # обещал ничего, а исполненный уже нечего взыскивать
            if order.status is OrderStatus.ACCEPTED and y <= max_y:
                lay["order_punish"] = {
                    "kind": "punish",
                    "rect": R(_PANEL_COL2_X, y, _PANEL_COL2_W, _PANEL_ACT_H),
                    "char_id": target.id, "county_idx": None, "duchy_id": None,
                    "index": None, "order_id": order.id, "selectable": True,
                    "text": "наказать за неисполнение (клик)",
                    "color": _ACT_OK, "font": self.font_small,
                }
                y += _PANEL_ACT_H

    def _panel_hint_text(self) -> str:
        """Строка подсказки: хоткеи названы своими именами, а не «1-4».

        Собирается из ``_PANEL_HOTKEYS``, поэтому надпись и привязка не могут
        разойтись: переименовали действие — надпись поехала за ним сама.
        """
        labels = dict(_ORDER_ROWS)
        spend_labels = dict(_SPEND_ROWS)
        keys = []
        for hot, action in _PANEL_HOTKEYS:
            scope, _, name = action.partition(":")
            if scope == "order":
                keys.append(f"{pygame.key.name(hot)}:{labels.get(OrderKind(name), name)}")
            else:
                keys.append(f"{pygame.key.name(hot)}:{spend_labels.get(name, name)}")
        base = _PANEL_HINT_OWN if self._panel_allows_orders() else _PANEL_HINT_FOREIGN
        return f"{base} · {' '.join(keys)}"

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
        # ПОРЯДОК ГРУПП ВАЖЕН, а не «неважен», как было раньше: строки графства и
        # кнопки трат под ними НЕ пересекаются, но блок приказов стоит под
        # списком двора в том же столбце, и при обратном порядке клик по приказу
        # уезжал бы в строку персонажа на 13 px выше.
        for key in ("orders", "spends", "county_spends", "counties",
                    "contracts", "duchies", "vassals"):
            for row in lay[key]:
                if row["rect"].collidepoint(mx, my):
                    return row
        # одиночные строки: статус приказа, кнопка «наказать», событие панели
        for key in ("order_punish", "order_status", "notice", "order_head",
                    "vassal_head"):
            row = lay.get(key)
            if row is not None and row["rect"].collidepoint(mx, my):
                return row
        realm = lay["realm"]
        if realm is not None and realm["rect"].collidepoint(mx, my):
            return realm
        box = lay["vassal_box"]
        if box.collidepoint(mx, my):
            return {"kind": "vassal_box", "rect": box.copy()}
        return {"kind": "panel", "rect": lay["panel"].copy()}

    def _handle_panel_click(self, mx: int, my: int):
        """Клик по панели владений: выбор строки и КНОПКИ действий.

        Клавиатура и мышь идут через один и тот же ``action``, поэтому
        «1 — подарок» и клик по строке «подарок» физически не могут разойтись
        (см. ``_PANEL_HOTKEYS``).

        Персонаж выбирается только у своей нации: дерево чужих держав
        показывается, но строки в нём не активируются, и блок приказов для
        чужой нации вообще не строится.
        """
        hit = self._panel_hit(mx, my)
        if hit is None:
            return
        kind = hit.get("kind")

        # ---- кнопки действий ----
        # selectable=False означает «серым и не кликабельно»: клик по такой
        # строке должен сказать ПОЧЕМУ, а не молча ничего не сделать.
        if kind in ("order", "spend", "county_spend", "punish"):
            if kind == "punish":
                self._punish_order_of_selection()
                return
            if not hit.get("selectable"):
                self._panel_notice = self._blocked_reason(hit)
                self._invalidate_panel()
                return
            self._panel_run_action(hit["action"], hit.get("county_idx"))
            return

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
        elif kind in ("order_status", "order_head", "vassal_head", "notice"):
            # заголовки и статусы — не кликабельны, но и выбор не сбрасывают
            return
        else:
            # пустое место панели — снять выбор
            self._sel_character_id = None
            self._sel_county_idx = None
            self._own_mode = "browse"
        self._invalidate_panel()

    def _blocked_reason(self, row: Dict) -> str:
        """Почему кнопка панели серая — текст берётся из самой строки.

        Причина уже посчитана в раскладке (``why``), потому что там же
        сравнивалось золото с ценой: пересчитывать значило бы получить второй
        источник правды о доступности.
        """
        label = row.get("label") or row.get("action") or "действие"
        why = row.get("why")
        if not why:
            return f"{label}: недоступно"
        return f"{label}: {why}"

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
        # ``_panel_notice`` добавлен в сверку: строка события меняется сама по
        # себе после клика, и без неё панель осталась бы со старым текстом.
        prev = self._panel_state
        if (self._panel_dirty or prev is None
                or prev[0] != self._turn
                or prev[1] != self._ownership_nation
                or prev[2] is not self.selected_general
                or prev[3] != self._sel_character_id
                or prev[4] != self._sel_county_idx
                or prev[5] != self._vassal_cursor
                or prev[6] != self._own_mode
                or prev[7] != self._panel_notice):
            self._paint_ownership_panel()
            self._panel_dirty = False
            self._panel_state = (self._turn, self._ownership_nation, self.selected_general,
                                 self._sel_character_id, self._sel_county_idx,
                                 self._vassal_cursor, self._own_mode,
                                 self._panel_notice)

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

        # служебные пояснения («нет владений», «выберите персонажа» и т.п.) —
        # не строки выбора
        for note in lay["notes"]:
            self._blit_panel_text(surface, note, ox, oy)

        if lay["realm"] is not None:
            self._blit_panel_text(surface, lay["realm"], ox, oy)

        head = lay["vassal_head"]
        surface.blit(self._cached_text(head["font"], head["text"], head["color"]),
                     head["rect"].move(-ox, -oy).topleft)

        # блоки ТРАТЫ и ПРИКАЗЫ рисуются рамкой: по ней видно, где кончается
        # читаемая строка и начинается кнопка, даже если она серая
        for group in (lay["spends"], lay["orders"]):
            for row in group:
                self._paint_action_row(surface, row, ox, oy)

        for group in (lay["duchies"], lay["contracts"], lay["counties"],
                      lay["vassals"]):
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

        for row in lay["county_spends"]:
            self._paint_action_row(surface, row, ox, oy)

        # одиночные строки блока приказов: заголовок, статус и наказание
        for key in ("order_head", "order_status", "order_punish"):
            row = lay.get(key)
            if row is not None:
                if row["kind"] == "punish":
                    self._paint_action_row(surface, row, ox, oy)
                else:
                    self._blit_panel_text(surface, row, ox, oy)

        notice = lay.get("notice")
        if notice is not None:
            self._blit_panel_text(surface, notice, ox, oy)

        hint = lay["hint"]
        surface.blit(self._cached_text(hint["font"], hint["text"], hint["color"]),
                     hint["rect"].move(-ox, -oy).topleft)

    def _paint_action_row(self, surface, row, ox: int, oy: int):
        """Одна кнопка панели: рамка + текст.

        Рамка рисуется ВСЕГДА, даже у серой строки: серый цвет сам по себе
        читается как «выключено», а рамка показывает, что это кнопка, которую
        можно нажать и узнать причину. Заливки под рукой нет намеренно — панель
        не должна мигать при каждом пересчёте доступности.
        """
        local = row["rect"].move(-ox, -oy)
        border = (150, 140, 115) if row.get("selectable") else (92, 86, 74)
        pygame.draw.rect(surface, border, local, 1, border_radius=3)
        self._blit_panel_text(surface, row, ox, oy)

    def _panel_row_selected(self, row) -> bool:
        """Отмечена ли строка панели текущим выбором.

        По персонажу отмечаются все строки, где он встречается (строка
        герцогства, контракт и строка двора): выбор одного и того же лица
        должен выглядеть одинаково в обеих колонках.

        Кнопки приказов и трат НЕ отмечаются никогда, хотя несут ``char_id``
        выбранного: иначе подсветкой залило бы весь блок «ПРИКАЗЫ» целиком, и
        выбор стал бы неотличим от обычного фона строк.
        """
        kind = row["kind"]
        if kind in ("order", "order_status", "punish", "spend", "county_spend"):
            return False
        if kind == "county":
            return self._sel_county_idx is not None and \
                self._sel_county_idx == row["county_idx"]
        char_id = row.get("char_id")
        return char_id is not None and self._sel_character_id == char_id

    def _blit_panel_text(self, surface, row, ox: int, oy: int):
        """Текст строки панели из кэша шрифтов — с учётом выделения.

        Ширина строки не гарантирована: подписи приказов и кнопок графств
        собираются из данных (имена провинций, цены, статусы) и могут стать
        длиннее столбца. Поэтому текст ужимается по ширине строки — иначе он
        вылезал бы за панель и перекрывал соседние кнопки. Ужимание идёт
        через тот же кэш строк, то есть лишних font.render не добавляет.
        """
        color = row["color"]
        if self._panel_row_selected(row):
            color = _PANEL_SEL_TEXT
        font = row["font"]
        text = row["text"]
        surf = self._cached_text(font, text, color)
        if surf.get_width() > row["rect"].width:
            text = self._fit_panel_text(font, text, color, row["rect"].width)
            surf = self._cached_text(font, text, color)
        surface.blit(surf, row["rect"].move(-ox, -oy).topleft)

    def _fit_panel_text(self, font, text: str, color, max_w: int) -> str:
        """Обрезать строку по ширине, дорезая по словам.

        Слова, а не символы: обрезанное посреди слова («наёмни…») читается как
        ошибка, а усечённая строка — как не поместившаяся подпись. Метрики
        берутся у уже закэшированных строк, поэтому цикл почти ничего не стоит
        (шрифт не перерисовывается).
        """
        if max_w <= 0:
            return ""
        if len(text) <= 2:
            return text
        low, high = 0, len(text)
        best = ""
        while low <= high:
            mid = (low + high) // 2
            # режем по последнему пробелу: хвост после него — неполное слово
            cut = text[:mid].rstrip()
            if " " in cut:
                cut = cut[:cut.rfind(" ")]
            cut = (cut + "…") if cut else "…"
            if self._cached_text(font, cut, color).get_width() <= max_w:
                best = cut
                low = mid + 1
            else:
                high = mid - 1
        return best or "…"


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
