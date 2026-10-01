"""Средневековая иерархия владений: Kingdom -> Duchy -> County.

Референсы механик: Crusader Kings III (вассальные контракты, мнение,
титульные ожидания) и Mount & Blade: Bannerlord (экономика владений,
лояльность как множитель налога, деревни привязаны к графству).

Модуль чистый в смысле слоёв: без ``pygame`` и без импортов ``world_data``.
Он оперирует любым объектом-провинцией, у которого есть ``name``,
``owner`` и ``troops``, поэтому его можно перенести в отдельный серверный
процесс без правок. Единственная внешняя зависимость — пакет ``sim``,
который сам по себе состоит только из стандартной библиотеки и потому
не создаёт цикла импортов (``sim/__init__.py`` импортирует лишь свои
собственные подмодули и ничего из корня проекта).

Ключевые решения:

* **Графство = существующая провинция.** Новых геометрических сущностей
  не заводим, поэтому карта и её тесты не ломаются.
* **Герцогство = группа провинций** (de jure), по 5 штук на карте.
* **Расхождение de jure и de facto** — источник контента: нация может
  владеть частью чужого герцогства, и это видно игроку.
* Числа целочисленные либо из конечного набора уровней — чтобы
  :func:`sim.hashing.state_hash` не «дрожал» из-за плавающей точки.

Хеширование состояния
---------------------

**Хешировать надо :meth:`Hierarchy.to_state`, а не сам объект.**

``Hierarchy`` — обычный класс, а не dataclass, поэтому
:func:`sim.hashing.canonical` доходит до ветки ``return repr(obj)``, а
``repr`` экземпляра содержит адрес памяти. Два одинаковых мира давали бы
разные хеши, а ``sim.serialization.to_jsonable`` схлопывал бы иерархию в
строку ``'<states.Hierarchy object at 0x...>'`` — то есть в потерю всего
состояния. Правильный путь один: получить plain-dict через ``to_state()``
и уже его хешировать. Штатная точка входа — :meth:`state_fingerprint`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from sim.hashing import state_hash
from sim.rng import NamedStreams, new_streams
from sim.serialization import register_enum


class Tier(IntEnum):
    """Ранг владения. Больше — выше."""

    COUNTY = 1
    DUCHY = 2
    REALM = 3


class TitleRank(Enum):
    """Ранг персонажа в иерархии."""

    BARON = "baron"
    DUKE = "duke"
    KING = "king"


#: Пять уровней феодального контракта: доля налогов, доля левейсов,
#: накопленная тирания. Как в CK3 — повышение контракта даёт штраф
#: мнения всем вассалам.
CONTRACT_LEVELS: Tuple[Dict[str, int], ...] = (
    {"name": "Нулевой", "tax": 0, "levy": 0, "tyranny": 0},
    {"name": "Малый", "tax": 20, "levy": 10, "tyranny": 0},
    {"name": "Обычный", "tax": 40, "levy": 25, "tyranny": 0},
    {"name": "Сильный", "tax": 60, "levy": 45, "tyranny": 2},
    {"name": "Разорительный", "tax": 80, "levy": 65, "tyranny": 6},
)

#: Множитель налога от лояльности поселения (формула Bannerlord):
#: +20% при полной лояльности, обнуление дохода при полном разорении.
LOYALTY_TAX_BREAK = 50
LOYALTY_TAX_MULTIPLIER = 20
LOYALTY_COLLAPSE = 25
LOYALTY_TAX_FLOOR = 0.2

#: Порог лояльности поселения, ниже которого возможен мятеж.
REBELLION_LOYALTY = 25

#: Порог лояльности ПЕРСОНАЖА, ниже которого он готовит мятеж.
#: Отдельная константа от REBELLION_LOYALTY, чтобы правка одного порога
#: не рассинхронизировала другую систему.
VASSAL_REBELLION_LOYALTY = 15

#: Сколько ходов без земли персонаж теряет мнение.
LANDLESS_OPINION_DECAY = 2

#: Множитель налога от стойкости (security): 0..20 -> 0.5..1.5
SECURITY_TAX_DIVISOR = 20

#: Множитель налога от застройки (development): 1..10 -> 0.6..1.5
DEVELOPMENT_BASE = 0.5
DEVELOPMENT_STEP = 0.1

#: Содержание: левейса делим на столько, плюс двор на каждого вассала
#: и постоянные расходы королевского дома. Без них казна растёт
#: бесконечно и экономика теряет смысл.
LEVY_UPKEEP_DIVISOR = 6
COURT_COST_PER_VASSAL = 10
ROYAL_COURT_BASE_COST = 30
#: Содержание двора растёт с престижем: блестящий двор дороже кормить.
#: Престиж копится в ``tick_realms`` и больше нигде не тратился, то есть
#: был мёртвым числом; теперь он — реальный сток, а не украшение UI.
ROYAL_COURT_PRESTIGE_DIVISOR = 10

#: Золота за ход за каждые 100 солдат гарнизона. До этапа 0.4 гарнизон не
#: списывался НИГДЕ, при этом давал +2 лояльности и +1 безопасности за ход,
#: то есть поднимал доход поселения примерно с 7 до 48 — «трата на гарнизон»
#: была фиктивной кнопкой. Теперь гарнизон стоит денег.
GARRISON_UPKEEP_PER_100 = 10

#: Солдат гарнизона гниёт за ход, если казна не тянет содержание.
#: 40 — примерно половина деревянной стоты: без денег гарнизон рассыпается
#: быстро, но не мгновенно, чтобы игрок видел последствия, а не откат.
GARRISON_ATTRITION = 40

#: Потолок гарнизона на каждую ступень укреплений: ``garrison <= fort_level
#: * GARRISON_CAP_PER_FORT``. Даёт смысл полю ``fort_level``, которое до сих
#: пор читалось только при инициализации: деревня 0, город 100, столица 200.
GARRISON_CAP_PER_FORT = 100

#: Сколько солдат в гарнизоне содержится бесплатно. Сознательно 0: стартовые
#: гарнизоны платные сразу. Альтернатива (сделать старт бесплатным и брать
#: деньги только с добавленных солдат) раздувала бы стартовый баланс на
#: ~30-40 золота в ход и отдавала игроку бесплатный доход в первые ходы.
#: Порог оставлен как «живой» параметр на будущую настройку.
GARRISON_IS_FREE_THRESHOLD = 0

#: Версия снапшота состояния. Рост числа означает смену формата; старые
#: снапшоты читаются через ``.get(field, default)`` и потому не ломаются.
STATE_VERSION = 1

#: Сколько записей журнала уезжает в снапшот. Длинный лог — это данные для
#: отладки, а не состояние мира, поэтому в провод он попадает урезанным.
LOG_KEEP = 50

#: Зерно дефолтных потоков ГПСЧ. Ноль выбран как «нейтральное» значение:
#: с ним и без явного зерна воспроизводимая симуляция остаётся
#: воспроизводимой. Тики ГПСЧ НЕ трогают (см. ``Hierarchy.streams``).
HIERARCHY_DEFAULT_SEED = 0

#: Девять полей поселения, которые иерархия действительно знает. Всё
#: остальное у провинции — геометрия и данные мирового слоя, сюда не входит.
COUNTY_FIELD_DEFAULTS: Dict[str, object] = {
    "duchy_id": None,
    "hearths": 0,
    "prosperity": 0,
    "loyalty": 0,
    "security": 0,
    "development": 1,
    "fort_level": 0,
    "garrison": 0,
    "villages": 0,
}
COUNTY_FIELDS: Tuple[str, ...] = tuple(COUNTY_FIELD_DEFAULTS)

#: Население поселений (hearths). Масштаб подобран так, чтобы доход
#: с одного графства был единицами, а не сотнями — иначе казна
#: королевства уходит в инфляцию за первые десятки ходов.
HEARTHS_VILLAGE = 150
HEARTHS_CITY = 260
HEARTHS_CAPITAL = 400


def loyalty_tax_multiplier(loyalty: int) -> float:
    """Множитель налога от лояльности поселения.

    Непрерывная кривая: ниже ``LOYALTY_COLLAPSE`` доход обрывается в ноль,
    от порога разорения до ``LOYALTY_TAX_BREAK`` линейно растёт от
    ``LOYALTY_TAX_FLOOR`` до 1.0, выше — плавно доходит до 1.2 («+20%»
    по Bannerlord) на полной лояльности.
    """
    if loyalty < LOYALTY_COLLAPSE:
        return 0.0
    if loyalty < LOYALTY_TAX_BREAK:
        span = float(LOYALTY_TAX_BREAK - LOYALTY_COLLAPSE)
        ratio = (loyalty - LOYALTY_COLLAPSE) / span
        return LOYALTY_TAX_FLOOR + (1.0 - LOYALTY_TAX_FLOOR) * ratio
    return 1.0 + (LOYALTY_TAX_MULTIPLIER / 100.0) * (loyalty - LOYALTY_TAX_BREAK) / 50.0


def security_tax_multiplier(security: int) -> float:
    """Множитель налога от стойкости поселения: 0.5..1.5."""
    return 0.5 + min(20, max(0, security)) / SECURITY_TAX_DIVISOR


def prosperity_tax_multiplier(prosperity: int) -> float:
    """Множитель налога от процветания: 0.5..2.0."""
    return max(0.5, min(2.0, prosperity / 50.0))


def development_tax_multiplier(development: int) -> float:
    """Множитель налога от застройки: 0.6..1.5."""
    return DEVELOPMENT_BASE + min(10, max(1, development)) * DEVELOPMENT_STEP


@dataclass
class Character:
    """Персонаж: барон, герцог или король.

    Намеренно «тощий» — без родословной и характера. Три навыка
    вместо системы черт, потому что полноценные персонажи тянут за собой
    диалоги и скрытую информацию, а это нечитаемо в 2D без сервера.
    """

    id: str
    name: str
    nation: str
    rank: TitleRank
    realm_id: Optional[str] = None
    duchy_id: Optional[str] = None
    province_idx: Optional[int] = None
    gold: int = 0
    influence: int = 10
    loyalty: int = 70
    opinion_of_liege: int = 20
    contract_level: int = 2
    martial: int = 5
    stewardship: int = 5
    diplomacy: int = 5
    age: int = 30
    alive: bool = True
    traits: Tuple[str, ...] = ()
    heir: Optional[str] = None
    landless_turns: int = 0

    @property
    def tier(self) -> Tier:
        return _RANK_TO_TIER[self.rank]

    @property
    def is_ruler(self) -> bool:
        """Держит ли земли (у короля это всё королевство)."""
        if self.rank is TitleRank.KING:
            return self.realm_id is not None
        if self.rank is TitleRank.DUKE:
            return self.duchy_id is not None
        return self.province_idx is not None

    def troops_hint(self) -> int:
        """Лёгкая привязка силы к войскам, если персонаж связан с генералом."""
        general = getattr(self, "linked_general", None)
        if general is None:
            return 0
        return int(getattr(general, "troops", 0)) // 100


_RANK_TO_TIER = {
    TitleRank.BARON: Tier.COUNTY,
    TitleRank.DUKE: Tier.DUCHY,
    TitleRank.KING: Tier.REALM,
}

#: Регистрируем Enum'ы в реестре ``sim.serialization`` на уровне модуля.
#: ``register_enum`` идемпотентен (обычная запись в dict), поэтому повторный
#: импорт states.py ничего не ломает. Без регистрации ``from_jsonable``
#: не смогла бы отличить ``TitleRank`` от любого другого Enum и вернула бы
#: голую строку вместо члена перечисления.
#:
#: Обратите внимание: ``from_state`` перечисления восстанавливает ЯВНО
#: (``TitleRank(...)`` / ``Tier(...)``), а не через реестр. Реестр нужен
#: для внешних потребителей (``sim.loads``), а не для нас — так версия
#: формата не зависит от того, успел ли кто-то импортировать states.
register_enum(TitleRank)
register_enum(Tier)


@dataclass
class Realm:
    """Королевство — верхний уровень иерархии."""

    id: str
    name: str
    nation: str
    ruler_id: Optional[str] = None
    capital_idx: Optional[int] = None
    gold: int = 500
    prestige: int = 0
    stability: int = 100
    #: 0..3 — королевская власть; ниже = слабее контроль над вассалами.
    crown_authority: int = 2
    tax_policy: int = 0
    is_player: bool = False

    @property
    def capital_name(self) -> str:
        return f"county#{self.capital_idx}" if self.capital_idx is not None else "—"


@dataclass
class Duchy:
    """Герцогство: de jure группа провинций и его текущий держатель."""

    id: str
    name: str
    de_jure_provinces: Tuple[int, ...]
    holder_id: Optional[str] = None
    realm_id: Optional[str] = None
    development: int = 1
    siege_safety: int = 0


@dataclass
class VassalContract:
    """Феодальный контракт между сюзереном и вассалом."""

    liege_id: str
    vassal_id: str
    level: int = 2

    @property
    def spec(self) -> Dict[str, int]:
        return CONTRACT_LEVELS[self.level]

    @property
    def tax_percent(self) -> int:
        return self.spec["tax"]

    @property
    def levy_percent(self) -> int:
        return self.spec["levy"]

    @property
    def tyranny(self) -> int:
        return self.spec["tyranny"]


# --------------------------------------------------------------------------
# Разметка герцогств
# --------------------------------------------------------------------------

#: Десять герцогств по пять провинций — границы совпадают с естественными
#: рядами сетки провинций, поэтому границы выглядят ровно и читаемо.
DUCHY_DEFS: Tuple[Tuple[str, str, Tuple[int, ...]], ...] = (
    ("northmark", "Northmark", (0, 1, 2, 3, 4)),
    ("southmarch", "Southmarch", (5, 6, 7, 8, 9)),
    ("ravenhold", "Ravenhold", (10, 11, 12, 13, 14)),
    ("blackridge", "Blackridge", (15, 16, 17, 18, 19)),
    ("stonewaste", "Stonewaste", (20, 21, 22, 23, 24)),
    ("emberfall", "Emberfall", (25, 26, 27, 28, 29)),
    ("dawnmarch", "Dawnmarch", (30, 31, 32, 33, 34)),
    ("greymoor", "Greymoor", (35, 36, 37, 38, 39)),
    ("leafguard", "Leafguard", (40, 41, 42, 43, 44)),
    ("goldfield", "Goldfield", (45, 46, 47, 48, 49)),
)

#: Королевства: id, название, нация, столица (индекс провинции).
REALM_DEFS: Tuple[Tuple[str, str, str, int], ...] = (
    ("kingdom_ember", "Kingdom of Ember", "red", 10),
    ("kingdom_riven", "Kingdom of Riven", "blue", 32),
    ("kingdom_thorn", "Kingdom of Thorn", "green", 42),
)

#: Герцоги: id, имя, нация, duchy_id, владение (индексы провинций).
DUKE_DEFS: Tuple[Tuple[str, str, str, str, Tuple[int, ...]], ...] = (
    ("duke_aldric", "Aldric", "red", "ravenhold", (10, 11, 12, 13, 14)),
    ("duke_vasya", "Vasya", "red", "blackridge", (15, 16, 17, 18, 19)),
    ("duke_brenna", "Brenna", "blue", "emberfall", (25, 26, 27, 28, 29)),
    ("duke_theon", "Theon", "blue", "dawnmarch", (30, 31, 32, 33, 34)),
    ("duke_lyra", "Lyra", "green", "leafguard", (40, 41, 42, 43, 44)),
    ("duke_orso", "Orso", "green", "greymoor", (35, 36, 37, 38, 39)),
)

#: Бароны: id, имя, нация, duchy_id (внутри), провинция, стартовые деньги.
BARON_DEFS: Tuple[Tuple[str, str, str, str, int], ...] = (
    ("baron_volkov", "Volkov", "red", "ravenhold", 11),
    ("baron_korzh", "Korzh", "red", "ravenhold", 12),
    ("baron_scar", "Scar", "red", "blackridge", 16),
    ("baron_ember", "Ember", "red", "blackridge", 17),
    ("baron_marsh", "Marsh", "blue", "emberfall", 27),
    ("baron_gate", "Gate", "blue", "emberfall", 28),
    ("baron_dawn", "Dawn", "blue", "dawnmarch", 31),
    ("baron_ray", "Ray", "blue", "dawnmarch", 33),
    ("baron_thorn", "Thorn", "green", "leafguard", 41),
    ("baron_moss", "Moss", "green", "leafguard", 43),
    ("baron_gray", "Gray", "green", "greymoor", 36),
    ("baron_wolf", "Wolf", "green", "greymoor", 38),
)

#: Короли: id, имя, нация, realm_id.
KING_DEFS: Tuple[Tuple[str, str, str, str], ...] = (
    ("king_erik", "Erik", "red", "kingdom_ember"),
    ("king_rurik", "Rurik", "blue", "kingdom_riven"),
    ("king_sigurd", "Sigurd", "green", "kingdom_thorn"),
)


class Hierarchy:
    """Менеджер владений: экономика, контракты, мнение, конец хода.

    Работает со списком провинций-объектов (duck typing) и с тремя
    словарями-реестрами. Ничего не знает про pygame и про отрисовку.

    Про ГПСЧ. Потоки лежат на объекте, но **до этапа 3 ни один тик их не
    трогает**: ни ``tick_counties``, ни ``tick_vassals``, ни ``tick_realms``,
    ни ``end_turn`` не делают ни одного броска. Это осознанное ограничение,
    а не забывчивость — иначе семь тестов детерминизма разошлись бы по
    хешу. Броски допускаются только в новых явных методах-командах
    («нанять гарнизон», «разорить провинцию» и т.п.), где игрок задал
    случайность явно. Поэтому ``streams`` можно не передавать: дефолтный
    набор потоков не влияет на состояние мира.
    """

    def __init__(
        self,
        provinces: Sequence,
        duchies: Optional[Dict[str, Duchy]] = None,
        realms: Optional[Dict[str, Realm]] = None,
        characters: Optional[Dict[str, Character]] = None,
        contracts: Optional[Dict[str, VassalContract]] = None,
        streams: Optional[NamedStreams] = None,
    ):
        self.provinces = provinces
        self.duchies: Dict[str, Duchy] = duchies if duchies is not None else {}
        self.realms: Dict[str, Realm] = realms if realms is not None else {}
        self.characters: Dict[str, Character] = characters if characters is not None else {}
        #: ключ — id вассала, значение — контракт с сюзереном.
        self.contracts: Dict[str, VassalContract] = contracts if contracts is not None else {}
        #: именованные потоки ГПСЧ. ВНЕШНИЙ источник энтропии: снапшот
        #: его не содержит (см. ``to_state``), при восстановлении потоки
        #: задаются заново конструктором.
        self.streams: NamedStreams = streams if streams is not None else new_streams(
            HIERARCHY_DEFAULT_SEED)
        self.turn: int = 1
        self.log: List[str] = []
        #: True, если журнал хоть раз упирался в ``LOG_KEEP``. Хранится в
        #: состоянии, а не вычисляется по ``len(self.log)``, иначе снапшот
        #: после round-trip выглядел бы иначе, чем до него.
        self.log_truncated: bool = False
        self._province_duchy: Dict[int, str] = {}
        self._rebuild_province_index()

    # ---------------- журнал ----------------

    def _append_log(self, entries: Sequence[str]) -> None:
        """Дописать события в журнал, подрезав его до ``LOG_KEEP``."""
        self.log.extend(entries)
        if len(self.log) > LOG_KEEP:
            del self.log[:len(self.log) - LOG_KEEP]
            self.log_truncated = True

    # ---------------- индексы и доступ ----------------

    def _rebuild_province_index(self):
        self._province_duchy.clear()
        for d in self.duchies.values():
            for idx in d.de_jure_provinces:
                self._province_duchy[idx] = d.id

    def province(self, idx: int):
        return self.provinces[idx]

    def duchy_of(self, province_idx: int) -> Optional[str]:
        """De jure герцогство провинции."""
        return self._province_duchy.get(province_idx)

    def counties_of_duchy(self, duchy_id: str) -> List[int]:
        d = self.duchies.get(duchy_id)
        return list(d.de_jure_provinces) if d else []

    def provinces_of_realm(self, realm_id: str) -> List[int]:
        """Фактические владения королевства — по владельцу провинции."""
        nation = self.realms[realm_id].nation
        return [i for i, p in enumerate(self.provinces) if getattr(p, "owner", "neutral") == nation]

    def holder_of_duchy(self, duchy_id: str) -> Optional[Character]:
        d = self.duchies.get(duchy_id)
        if d and d.holder_id:
            return self.characters.get(d.holder_id)
        return None

    def liege_of(self, character_id: str) -> Optional[Character]:
        """Сюзерен персонажа: король для герцога, герцог для барона."""
        ch = self.characters.get(character_id)
        if ch is None:
            return None
        if ch.rank is TitleRank.KING:
            return None
        if ch.rank is TitleRank.DUKE:
            realm = self.realms.get(ch.realm_id or "")
            return self.characters.get(realm.ruler_id) if realm else None
        if ch.duchy_id:
            holder = self.holder_of_duchy(ch.duchy_id)
            if holder and holder.id != ch.id:
                return holder
        return None

    def vassals_of(self, character_id: str) -> List[Character]:
        liege = self.characters.get(character_id)
        out: List[Character] = []
        for ch in self.characters.values():
            if ch.id == character_id or not ch.alive:
                continue
            if self.liege_of(ch.id) and self.liege_of(ch.id).id == character_id:
                out.append(ch)
        out.sort(key=lambda c: c.id)
        return out

    def powerful_vassals(self, realm_id: str, county_threshold: int = 2,
                         duchy_threshold: int = 1, kingdom_threshold: int = 5
                         ) -> List[Character]:
        """Сильные вассалы по размеру (по аналогии с CK3).

        Считаются только герцоги: король — не вассал самому себе. Порог
        по умолчанию снижен до двух графств, потому что на текущей карте
        в герцогстве всего два барона (масштаб CK3 — десятки графств).
        ``kingdom_threshold`` оставлен для будущих сценариев, где могущество
        считается по числу герцогств.
        """
        out: List[Character] = []
        for ch in self.characters.values():
            if not ch.alive or ch.realm_id != realm_id:
                continue
            if ch.rank is TitleRank.DUKE and self._baron_count(ch) >= county_threshold:
                out.append(ch)
        out.sort(key=lambda c: (-self.vassal_power(c), c.id))
        return out

    def _baron_count(self, ch: Character) -> int:
        """Сколько графств держит герцог/король (для герцога — его бароны)."""
        if ch.rank is TitleRank.KING:
            return len(self.provinces_of_realm(ch.realm_id or ""))
        if ch.rank is TitleRank.DUKE and ch.duchy_id:
            holder = self.holder_of_duchy(ch.duchy_id)
            if holder and holder.id != ch.id:
                return 0
            return sum(1 for b in self.characters.values()
                       if b.rank is TitleRank.BARON and b.duchy_id == ch.duchy_id and b.alive)
        return 1

    def vassal_power(self, ch: Character) -> int:
        """«Сеньоритет» — сводная сила персонажа. Единственное число в UI короля."""
        if not ch.alive:
            return 0
        return self._baron_count(ch) * 10 + ch.influence + ch.martial * 2 + ch.troops_hint()

    def liege_authority(self, character_id: str) -> int:
        """Королевская власть (0..3) над персонажем. Ниже — слабее контроль.

        Поднимается по всей цепочке сюзеренов до корня: авторитет короля
        распространяется и на герцога, и на его баронов.
        """
        ch = self.characters.get(character_id)
        if ch is None:
            return 0
        node: Optional[Character] = ch
        seen = set()
        while node is not None and node.id not in seen:
            seen.add(node.id)
            if node.rank is TitleRank.KING:
                realm = self.realms.get(node.realm_id or "")
                if realm is None:
                    return 0
                return max(0, min(3, int(realm.crown_authority)))
            node = self.liege_of(node.id)
        return 0

    # ---------------- экономика графства ----------------

    def county_income(self, province_idx: int) -> int:
        """Доход графства за ход: 35% hearths с множителями."""
        p = self.province(province_idx)
        hearths = getattr(p, "hearths", 0)
        if hearths <= 0:
            return 0
        mult = (prosperity_tax_multiplier(getattr(p, "prosperity", 0))
                * loyalty_tax_multiplier(getattr(p, "loyalty", 70))
                * security_tax_multiplier(getattr(p, "security", 10))
                * development_tax_multiplier(getattr(p, "development", 1)))
        return int(hearths * 35 // 100 * mult)

    def county_levy(self, province_idx: int) -> int:
        p = self.province(province_idx)
        dev = getattr(p, "development", 1)
        base = getattr(p, "hearths", 0) // 2
        return max(0, int(base * development_tax_multiplier(dev)))

    def garrison_cap(self, province_idx: int) -> int:
        """Потолок гарнизона: ``(fort_level + 1) * GARRISON_CAP_PER_FORT``.

        Даёт ``fort_level`` смысл: деревня держит сотню, город — две,
        крепость-столица — три. Без стен гарнизон всё равно держать
        можно, но дороже и меньше.

        ВАЖНО: потолок НЕ применяется автоматически в тиках. Причина
        чистая: существующие тесты (``test_loyalty_rises_with_garrison``)
        ставят гарнизон в деревню и ждут от него роста лояльности — то
        есть «нелегальный» гарнизон должен продолжать работать. Сжимать
        гарнизон до потолка будет команда найма (этап 3), где игрок
        задаёт число солдат явно; до тех пор порог только спрашивается,
        но не принуждает.
        """
        fort = max(0, int(getattr(self.province(province_idx), "fort_level", 0)))
        return (fort + 1) * GARRISON_CAP_PER_FORT

    def garrison_upkeep(self, realm_id: str) -> int:
        """Содержание гарнизонов королевства за ход, в золоте.

        Считается **только по провинциям ЭТОГО realm'а** — гарнизоны
        нейтральных и чужих земель никто не кормит. Первые
        ``GARRISON_IS_FREE_THRESHOLD`` солдат на провинцию бесплатны
        (сейчас это ноль, то есть платный весь гарнизон).
        """
        total = 0
        for idx in self.provinces_of_realm(realm_id):
            billable = max(0, int(getattr(self.province(idx), "garrison", 0))
                           - GARRISON_IS_FREE_THRESHOLD)
            # пропорционально, а не «по сотням»: иначе гарнизон в 99 солдат
            # бесплатен, а разорённое королевство стягивает войска до 99
            # и больше не платит ничего (обход содержания)
            total += billable * GARRISON_UPKEEP_PER_100 // 100
        return total

    def duchy_income(self, duchy_id: str) -> int:
        return sum(self.county_income(i) for i in self.counties_of_duchy(duchy_id))

    def duchy_levy(self, duchy_id: str) -> int:
        return sum(self.county_levy(i) for i in self.counties_of_duchy(duchy_id))

    def realm_income(self, realm_id: str) -> int:
        """Фактический доход королевства: то, что платят его владения."""
        nation = self.realms[realm_id].nation
        total = 0
        for idx, p in enumerate(self.provinces):
            if getattr(p, "owner", "neutral") != nation:
                continue
            total += self.county_income(idx)
        return total

    def realm_levy(self, realm_id: str) -> int:
        nation = self.realms[realm_id].nation
        return sum(self.county_levy(i) for i, p in enumerate(self.provinces)
                   if getattr(p, "owner", "neutral") == nation)

    # ---------------- контракты и мнение ----------------

    def contract_of(self, vassal_id: str) -> Optional[VassalContract]:
        return self.contracts.get(vassal_id)

    def set_contract(self, vassal_id: str, level: int) -> List[str]:
        """Смена уровня контракта. Повышение копит тиранию и режет мнение."""
        level = max(0, min(len(CONTRACT_LEVELS) - 1, int(level)))
        ch = self.characters.get(vassal_id)
        if ch is None:
            return []
        old = self.contracts.get(vassal_id)
        old_level = old.level if old is not None else level
        if old is not None and old_level == level:
            return [f"{ch.name}: контракт уже {CONTRACT_LEVELS[level]['name']}"]
        liege = self.liege_of(vassal_id)
        self.contracts[vassal_id] = VassalContract(
            liege_id=liege.id if liege else "",
            vassal_id=vassal_id, level=level)
        events: List[str] = []
        if old is None or level > old_level:
            delta = -10 if (old and level > old_level) else -5
            ch.opinion_of_liege = max(-100, ch.opinion_of_liege + delta)
            events.append(f"{ch.name}: контракт повышен, мнение {ch.opinion_of_liege}")
        else:
            ch.opinion_of_liege = min(100, ch.opinion_of_liege + 5)
            events.append(f"{ch.name}: контракт ослаблен, мнение {ch.opinion_of_liege}")
        return events

    def can_accept_order(self, vassal_id: str, order: str) -> bool:
        """Может ли вассал выполнить приказ сюзерена (CK3-порог)."""
        ch = self.characters.get(vassal_id)
        if ch is None or not ch.alive:
            return False
        if ch.opinion_of_liege >= 0:
            return True
        # при глубокой ненависти выручает только абсолютная королевская власть
        return self.liege_authority(vassal_id) >= 3 and ch.opinion_of_liege > -60

    def grant_fief(self, province_idx: int, baron_id: str) -> List[str]:
        """Передать графство барону. Главный способ снизить мятеж.

        ``duchy_id`` пересчитывается всегда: иначе барон, получивший землю
        в чужом герцогстве, остался бы вассалом прежнего сюзерена.
        """
        ch = self.characters.get(baron_id)
        if ch is None:
            return []
        events: List[str] = []
        was_landless = not ch.is_ruler
        ch.province_idx = province_idx
        new_duchy = self.duchy_of(province_idx)
        if new_duchy is not None:
            ch.duchy_id = new_duchy
        ch.landless_turns = 0
        if was_landless:
            ch.opinion_of_liege = min(100, ch.opinion_of_liege + 20)
            ch.loyalty = min(100, ch.loyalty + 10)
            events.append(f"{ch.name} получил землю, мнение {ch.opinion_of_liege}")
        return events

    def revoke_fief(self, baron_id: str) -> List[str]:
        """Отозвать графство: снять владение, лояльность и доход поселения."""
        ch = self.characters.get(baron_id)
        if ch is None:
            return []
        ch.province_idx = None
        ch.landless_turns = 0
        ch.opinion_of_liege = max(-100, ch.opinion_of_liege - 20)
        ch.loyalty = max(0, ch.loyalty - 20)
        return [f"{ch.name} лишён земли, мнение {ch.opinion_of_liege}"]

    # ---------------- конец хода ----------------

    def prosperity_cap(self, province_idx: int) -> int:
        """Потолок процветания: богатое поселение растёт до большего предела."""
        p = self.province(province_idx)
        return min(100, 20 + max(0, getattr(p, "hearths", 0)) // 20)

    def tick_counties(self) -> List[str]:
        """Лояльность поселений: гарнизон и налоги давят, мир поднимает.

        Равновесие без гарнизона — около 55 лояльности (поселение не
        умирает, но и не процветает); с гарнизоном лояльность растёт до
        100. Поэтому гарнизон стоит денег (см. ``garrison_upkeep``), а его
        отсутствие не убивает поселение, но лишает его полного дохода.

        Здесь же — атриция гарнизонов. Проверка «может ли королевство
        заплатить» делается по золоту, которое доступно **на момент входа
        в фазу**: порядок ``end_turn`` такой (``tick_counties`` ->
        ``tick_vassals`` -> ``tick_realms``), поэтому здесь видно золото
        ПРОШЛОГО хода, а текущий доход ещё не начислен. Это нормально и
        полностью детерминировано — простое сравнение с золотом после
        начисления зависело бы от ``tick_realms``, который ещё не шёл.
        """
        events: List[str] = []
        # индекс нация -> королевство: иначе на каждую провинцию пришлось бы
        # перебирать все realm'ы. Строится заново каждый тик, чтобы внешний
        # код мог спокойно перекрашивать карту между ходами.
        realm_of_nation = {realm.nation: realm_id for realm_id, realm in self.realms.items()}
        # казна прошлого хода: не хватило — гарнизон гниёт
        broke = {realm_id for realm_id in self.realms
                 if self.realms[realm_id].gold < self.garrison_upkeep(realm_id)}
        for idx, p in enumerate(self.provinces):
            loyalty = getattr(p, "loyalty", 70)
            garrison = getattr(p, "garrison", 0)
            prosperity = getattr(p, "prosperity", 0)
            security = getattr(p, "security", 10)

            # атриция: казна не тянет содержание — гарнизон рассыпается
            realm_id = realm_of_nation.get(getattr(p, "owner", None))
            if garrison > 0 and realm_id is not None and realm_id in broke:
                garrison = max(0, garrison - GARRISON_ATTRITION)
                p.garrison = garrison
                if garrison == 0:
                    events.append(f"Гарнизон #{idx} рассыпался: казна пуста")

            if garrison > 0:
                loyalty += 2
            elif loyalty > 55:
                loyalty -= 2
            else:
                # крестьяне сами возвращаются к хозяйству, если не давить
                loyalty += 1

            # высокие налоги (королевская политика) давят на populous county
            for realm in self.realms.values():
                if realm.tax_policy > 0 and getattr(p, "owner", None) == realm.nation:
                    loyalty -= 2
            loyalty = max(0, min(100, loyalty))

            # процветание упирается в население, иначе экономика уходит в инфляцию
            cap = self.prosperity_cap(idx)
            if prosperity < cap:
                prosperity += 1 if loyalty >= 60 else -1
            prosperity = max(0, min(cap, prosperity))
            security = max(0, min(20, security + (1 if garrison > 0 else -1)))

            if loyalty < REBELLION_LOYALTY:
                events.append(f"Мятеж в #{idx}: лояльность {loyalty}")

            p.loyalty = loyalty
            p.prosperity = prosperity
            p.security = security
            # застройка растёт только при образцовом порядке
            if loyalty >= 80 and getattr(p, "development", 1) < 5:
                p.development = getattr(p, "development", 1) + 1
            elif loyalty < 40 and getattr(p, "development", 1) > 1:
                p.development = getattr(p, "development", 1) - 1
        return events

    def tick_vassals(self) -> List[str]:
        """Мнение, лояльность, тирания, накопление недовольства."""
        events: List[str] = []
        for ch in sorted(self.characters.values(), key=lambda c: c.id):
            if not ch.alive:
                continue
            contract = self.contracts.get(ch.id)
            liege = self.liege_of(ch.id)
            if liege is None:
                continue

            if ch.is_ruler:
                ch.landless_turns = 0
            else:
                ch.landless_turns += 1
                ch.opinion_of_liege = max(-100, ch.opinion_of_liege - LANDLESS_OPINION_DECAY)

            if contract:
                ch.opinion_of_liege = max(
                    -100, ch.opinion_of_liege - contract.spec["tyranny"] // 2)

            # лояльность = мнение + авторитет сюзерена + личная преданность
            authority = self.liege_authority(ch.id)
            target = 30 + authority * 15 + ch.opinion_of_liege // 2
            if ch.loyalty < target:
                ch.loyalty = min(100, ch.loyalty + 3)
            else:
                ch.loyalty = max(0, ch.loyalty - 2)

            if ch.loyalty < VASSAL_REBELLION_LOYALTY:
                events.append(f"{ch.name} (лояльность {ch.loyalty}) готовит мятеж")
        return events

    def realm_upkeep(self, realm_id: str) -> int:
        """Содержание королевства: левейс на стену, двор вассалов, гарнизоны.

        Из чего складывается:

        * левейс realm'а, делённый на ``LEVY_UPKEEP_DIVISOR``;
        * ``COURT_COST_PER_VASSAL`` за каждого прямого вассала правителя;
        * содержание гарнизонов **этого** королевства (см.
          ``garrison_upkeep``) — гарнизон больше не бесплатный;
        * ``ROYAL_COURT_BASE_COST`` плюс ``престиж // 10`` — блестящий
          двор дороже содержать, поэтому престиж стал стоком, а не
          мёртвым числом.
        """
        realm = self.realms[realm_id]
        upkeep = self.realm_levy(realm_id) // LEVY_UPKEEP_DIVISOR
        ruler = realm.ruler_id
        if ruler:
            upkeep += COURT_COST_PER_VASSAL * len(self.vassals_of(ruler))
        upkeep += self.garrison_upkeep(realm_id)
        return upkeep + ROYAL_COURT_BASE_COST + max(0, realm.prestige) // \
            ROYAL_COURT_PRESTIGE_DIVISOR

    def tick_realms(self) -> List[str]:
        """Казна королевств: доход минус содержание левейса и двора."""
        events: List[str] = []
        for realm in sorted(self.realms.values(), key=lambda r: r.id):
            income = self.realm_income(realm.id)
            upkeep = self.realm_upkeep(realm.id)
            realm.gold = max(0, realm.gold + income - upkeep)
            if income < upkeep:
                realm.stability = max(0, realm.stability - 2)
            # престиж растёт от владений и падает от пустого королевства
            held = len(self.provinces_of_realm(realm.id))
            if held >= 5:
                realm.prestige = min(100, realm.prestige + 1)
            elif held == 0:
                realm.prestige = max(0, realm.prestige - 2)
            # низкая стабильность от слишком высоких налогов
            if realm.tax_policy > 0:
                realm.stability = max(0, realm.stability - 2)
            else:
                realm.stability = min(100, realm.stability + 1)
        return events

    def end_turn(self) -> List[str]:
        """Один ход экономики. Порядок фиксирован — детерминизм для онлайна.

        Ни одна из фаз не обращается к ``self.streams``: ход — чистая
        функция состояния, поэтому хеш мира не «дрожит» от того, откуда
        взялись случайные числа. Броски живут только в командах.
        """
        events: List[str] = []
        events += self.tick_counties()
        events += self.tick_vassals()
        events += self.tick_realms()
        self.turn += 1
        self._append_log(events)
        return events

    def rebellions(self) -> List[str]:
        """Кто реально может поднять мятеж (лояльность < порога)."""
        out: List[str] = []
        for ch in sorted(self.characters.values(), key=lambda c: c.id):
            if ch.alive and ch.rank is not TitleRank.KING and ch.loyalty < VASSAL_REBELLION_LOYALTY:
                out.append(ch.id)
        return out

    def summary(self) -> Dict[str, object]:
        """Компактный слепок состояния — для UI, логов и хеша."""
        return {
            "turn": self.turn,
            "realms": {r.id: {"gold": r.gold, "prestige": r.prestige,
                              "stability": r.stability, "held": len(self.provinces_of_realm(r.id))}
                       for r in sorted(self.realms.values(), key=lambda x: x.id)},
            "duchies": {d.id: {"holder": d.holder_id, "income": self.duchy_income(d.id)}
                        for d in sorted(self.duchies.values(), key=lambda x: x.id)},
            "characters": {c.id: {"rank": c.rank.value, "loyalty": c.loyalty,
                                  "opinion": c.opinion_of_liege, "gold": c.gold}
                           for c in sorted(self.characters.values(), key=lambda x: x.id)},
        }

    # ---------------- сериализация состояния ----------------

    def to_state(self) -> Dict[str, object]:
        """Снапшот состояния в виде plain-dict, пригодный для хеша и JSON.

        Возвращаемый словарь — единственный честный представитель мира:
        ``sim.hashing.state_hash`` и ``sim.serialization.to_jsonable`` умеют
        канонизировать dict, но не класс ``Hierarchy``.

        Что внутри: ``version``, ``turn``, урезанный ``log`` с признаком
        усечения, все поля ``Realm``/``Duchy``/``Character``, контракты
        (только ``liege_id``/``vassal_id``/``level``) и девять полей
        поселения по каждой провинции.

        Чего здесь НЕТ и почему:

        * ``self.provinces`` целиком. Геометрия (полигоны, центроиды, имена
          соседей, ``troops``) принадлежит мировому слою; ``states.py`` по
          контракту о ней не знает и оперирует любым duck-объектом. Если бы
          мы тащили геометрию в снапшот, иерархия перестала бы переноситься
          в отдельный серверный процесс, а карта и её 149 тестов зависели бы
          от порядка сохранения. Провинции приходят в ``from_state`` параметром.
        * ``_province_duchy``. Производный кэш «индекс провинции -> герцогство»,
          целиком восстанавливается вызовом ``_rebuild_province_index()`` в
          конструкторе. Хранить его — значило бы хранить redundancy, которая
          может разойтись с ``duchies``.
        * ``streams``. ГПСЧ — внешний источник энтропии, а не состояние мира:
          его положение нужно только для продолжения бросков. При загрузке
          чужого снапшота «продолжить броски» всё равно бессмысленно, поэтому
          потоки задаются конструктором.
        * ``linked_general``. Внешняя ссылка на объект из другого слоя
          (генерал армии), которая к тому же меняется каждый ход. Сериализовать
          её нельзя — сломается контракт изоляции модуля.
        * Ничего из ``sim/``. Фолбэк ``repr`` в ``sim/serialization.py``
          закреплён тестами ``test_sim.py``, и править его отсюда нельзя.

        Порядок ключей детерминирован (реестры — по отсортированным id),
        так что ``state_hash`` от двух одинаковых миров совпадает.
        """
        state: Dict[str, object] = {
            "version": STATE_VERSION,
            "turn": self.turn,
            "log": list(self.log[-LOG_KEEP:]),
            "log_truncated": self.log_truncated or len(self.log) > LOG_KEEP,
            "realms": {r.id: {
                "id": r.id,
                "name": r.name,
                "nation": r.nation,
                "ruler_id": r.ruler_id,
                "capital_idx": r.capital_idx,
                "gold": r.gold,
                "prestige": r.prestige,
                "stability": r.stability,
                "crown_authority": r.crown_authority,
                "tax_policy": r.tax_policy,
                "is_player": r.is_player,
            } for r in sorted(self.realms.values(), key=lambda x: x.id)},
            "duchies": {d.id: {
                "id": d.id,
                "name": d.name,
                # de_jure_provinces — tuple: иначе JSON вернул бы список
                # и round-trip тихо сменил бы тип поля.
                "de_jure_provinces": tuple(d.de_jure_provinces),
                "holder_id": d.holder_id,
                "realm_id": d.realm_id,
                "development": d.development,
                "siege_safety": d.siege_safety,
            } for d in sorted(self.duchies.values(), key=lambda x: x.id)},
            "characters": {c.id: {
                "id": c.id,
                "name": c.name,
                "nation": c.nation,
                # enum как его собственное имя: не полагаемся на реестр
                # register_enum и не тащим служебные теги в формат.
                "rank": c.rank.name,
                "realm_id": c.realm_id,
                "duchy_id": c.duchy_id,
                "province_idx": c.province_idx,
                "gold": c.gold,
                "influence": c.influence,
                "loyalty": c.loyalty,
                "opinion_of_liege": c.opinion_of_liege,
                "contract_level": c.contract_level,
                "martial": c.martial,
                "stewardship": c.stewardship,
                "diplomacy": c.diplomacy,
                "age": c.age,
                "alive": c.alive,
                "traits": tuple(c.traits),
                "heir": c.heir,
                "landless_turns": c.landless_turns,
            } for c in sorted(self.characters.values(), key=lambda x: x.id)},
            "contracts": {vassal_id: {
                "liege_id": c.liege_id,
                "vassal_id": c.vassal_id,
                "level": c.level,
            } for vassal_id, c in sorted(self.contracts.items())},
            "counties": {
                idx: {name: getattr(p, name, default)
                      for name, default in COUNTY_FIELD_DEFAULTS.items()}
                for idx, p in enumerate(self.provinces)
            },
        }
        return state

    def state_fingerprint(self) -> str:
        """Хеш состояния мира. Единственная точка хеширования иерархии.

        Именно ``state_hash(self.to_state())``, а НЕ ``state_hash(self)``:
        ``Hierarchy`` не dataclass, поэтому ``canonical`` уходит в
        ``repr(obj)``, а ``repr`` содержит адрес памяти — два одинаковых
        мира получили бы разные хеши. См. докстринг модуля.
        """
        return state_hash(self.to_state())

    @staticmethod
    def from_state(state: Dict[str, object], provinces: Sequence,
                   streams: Optional[NamedStreams] = None) -> "Hierarchy":
        """Восстановить иерархию из снапшота ``to_state()``.

        ``provinces`` — внешний мир: список тех же duck-объектов, что и при
        сохранении. Иерархия не создаёт и не копирует провинции, а только
        переносит на них девять полей поселения. Геометрия, владельцы и
        войска остаются такими, какими были в мировом слое.

        Все поля читаются через ``.get(field, default)``: старый или
        частично заполненный снапшот обязан загружаться, а не падать. Отсюда
        же дефолты берутся у самих dataclass — источник правды один.

        enum'ы восстанавливаются ЯВНО (``TitleRank(...)`` / ``Tier(...)``), а
        не через реестр ``sim.serialization``: так восстановление не зависит
        от того, был ли импортирован модуль с ``register_enum``. Ключи
        ``counties`` приходят из JSON строками — приводим к ``int``.
        """
        realms: Dict[str, Realm] = {}
        for realm_id, data in dict(state.get("realms") or {}).items():
            data = dict(data)
            realms[realm_id] = Realm(
                id=data.get("id", realm_id),
                name=data.get("name", realm_id),
                nation=data.get("nation", "neutral"),
                ruler_id=data.get("ruler_id"),
                capital_idx=data.get("capital_idx"),
                gold=data.get("gold", 500),
                prestige=data.get("prestige", 0),
                stability=data.get("stability", 100),
                crown_authority=data.get("crown_authority", 2),
                tax_policy=data.get("tax_policy", 0),
                is_player=bool(data.get("is_player", False)),
            )

        duchies: Dict[str, Duchy] = {}
        for duchy_id, data in dict(state.get("duchies") or {}).items():
            data = dict(data)
            duchies[duchy_id] = Duchy(
                id=data.get("id", duchy_id),
                name=data.get("name", duchy_id),
                # обратно в tuple: JSON отдаёт list
                de_jure_provinces=tuple(data.get("de_jure_provinces") or ()),
                holder_id=data.get("holder_id"),
                realm_id=data.get("realm_id"),
                development=data.get("development", 1),
                siege_safety=data.get("siege_safety", 0),
            )

        characters: Dict[str, Character] = {}
        for ch_id, data in dict(state.get("characters") or {}).items():
            data = dict(data)
            raw_rank = data.get("rank", TitleRank.BARON.name)
            if isinstance(raw_rank, TitleRank):
                rank = raw_rank
            else:
                try:
                    rank = TitleRank[raw_rank]
                except KeyError:
                    try:
                        rank = TitleRank(raw_rank)
                    except ValueError:
                        rank = TitleRank.BARON
            traits = data.get("traits") or ()
            if isinstance(traits, str):
                traits = (traits,)
            characters[ch_id] = Character(
                id=data.get("id", ch_id),
                name=data.get("name", ch_id),
                nation=data.get("nation", "neutral"),
                rank=rank,
                realm_id=data.get("realm_id"),
                duchy_id=data.get("duchy_id"),
                province_idx=data.get("province_idx"),
                gold=data.get("gold", 0),
                influence=data.get("influence", 10),
                loyalty=data.get("loyalty", 70),
                opinion_of_liege=data.get("opinion_of_liege", 20),
                contract_level=data.get("contract_level", 2),
                martial=data.get("martial", 5),
                stewardship=data.get("stewardship", 5),
                diplomacy=data.get("diplomacy", 5),
                age=data.get("age", 30),
                alive=bool(data.get("alive", True)),
                # обратно в tuple: JSON отдаёт list
                traits=tuple(traits),
                heir=data.get("heir"),
                landless_turns=data.get("landless_turns", 0),
            )

        contracts: Dict[str, VassalContract] = {}
        for vassal_id, data in dict(state.get("contracts") or {}).items():
            data = dict(data)
            contracts[vassal_id] = VassalContract(
                liege_id=data.get("liege_id", ""),
                vassal_id=data.get("vassal_id", vassal_id),
                level=data.get("level", 2),
            )

        hierarchy = Hierarchy(provinces, duchies, realms, characters, contracts,
                              streams=streams)

        for raw_idx, data in dict(state.get("counties") or {}).items():
            try:
                idx = int(raw_idx)
            except (TypeError, ValueError):
                continue
            if not 0 <= idx < len(provinces):
                continue
            province = provinces[idx]
            # только белый список полей: битый снапшот не должен уметь
            # дописать в провинцию произвольный атрибут
            for name, default in COUNTY_FIELD_DEFAULTS.items():
                setattr(province, name, dict(data).get(name, default))

        hierarchy.turn = int(state.get("turn", 1))
        log = state.get("log") or []
        hierarchy.log = list(log)
        # признак усечения берём из снапшота, а не вычисляем заново:
        # иначе состояние, обрезанное при сохранении, после round-trip
        # выглядело бы полным и отличалось хешем от исходного.
        hierarchy.log_truncated = bool(state.get("log_truncated", False))
        return hierarchy


def _duchy_province_map() -> Dict[int, str]:
    """Индекс провинции -> id герцогства (de jure)."""
    mapping: Dict[int, str] = {}
    for duchy_id, _name, provs in DUCHY_DEFS:
        for idx in provs:
            mapping[idx] = duchy_id
    return mapping


def build_default_hierarchy(provinces: Sequence,
                           streams: Optional[NamedStreams] = None) -> Hierarchy:
    """Строит иерархию по текущей карте: 3 королевства, 6 герцогов, 12 баронов.

    Провинции получают ``duchy_id``, ``hearths``, ``prosperity``, ``loyalty``,
    ``security``, ``development``, ``fort_level``, ``garrison`` и ``villages``
    с дефолтами — старые тесты, читающие ``owner``/``region_type``,
    продолжают работать.

    ``fort_level`` выставляется как 0/1/2 (деревня/город/столица), и именно
    он задаёт потолок гарнизона в ``garrison_cap``: до этапа 0.4 поле было
    заполнено, но не читалось нигде, то есть было мёртвым. Стартовый
    гарнизон (0/100/200) ровно упирается в этот потолок.

    ``streams`` — симметрично конструктору ``Hierarchy``: ``None`` означает
    ``new_streams(HIERARCHY_DEFAULT_SEED)``. Параметр нужен для явной
    фиксации зерна в тестах и реплеях; на стартовое состояние он не влияет,
    потому что ни одна фаза хода ГПСЧ не трогает.
    """
    duchies: Dict[str, Duchy] = {}
    realms: Dict[str, Realm] = {}
    characters: Dict[str, Character] = {}
    contracts: Dict[str, VassalContract] = {}

    for realm_id, realm_name, nation, capital in REALM_DEFS:
        realms[realm_id] = Realm(id=realm_id, name=realm_name, nation=nation,
                                 capital_idx=capital, is_player=(nation == "blue"))

    for duchy_id, duchy_name, provs in DUCHY_DEFS:
        holder = next((d[0] for d in DUKE_DEFS if d[3] == duchy_id), None)
        nation = next((d[2] for d in DUKE_DEFS if d[3] == duchy_id), "neutral")
        realm_id = next((r.id for r in realms.values() if r.nation == nation), None)
        duchies[duchy_id] = Duchy(id=duchy_id, name=duchy_name,
                                  de_jure_provinces=tuple(provs),
                                  holder_id=holder, realm_id=realm_id)

    for king_id, name, nation, realm_id in KING_DEFS:
        characters[king_id] = Character(id=king_id, name=name, nation=nation,
                                        rank=TitleRank.KING, realm_id=realm_id,
                                        gold=400, influence=40, age=44)
        realms[realm_id].ruler_id = king_id

    for duke_id, name, nation, duchy_id, provs in DUKE_DEFS:
        realm_id = next(r.id for r in realms.values() if r.nation == nation)
        characters[duke_id] = Character(id=duke_id, name=name, nation=nation,
                                        rank=TitleRank.DUKE, realm_id=realm_id,
                                        duchy_id=duchy_id, gold=150, influence=25, age=38)
        # сюзерен герцога — король ИМЕННО ЕГО королевства
        liege_id = realms[realm_id].ruler_id or ""
        contracts[duke_id] = VassalContract(liege_id=liege_id, vassal_id=duke_id, level=2)

    for baron_id, name, nation, duchy_id, prov_idx in BARON_DEFS:
        duke = characters.get(next((d[0] for d in DUKE_DEFS if d[3] == duchy_id), ""))
        characters[baron_id] = Character(id=baron_id, name=name, nation=nation,
                                         rank=TitleRank.BARON, duchy_id=duchy_id,
                                         province_idx=prov_idx, gold=50, influence=10,
                                         age=30)
        if duke:
            contracts[baron_id] = VassalContract(liege_id=duke.id, vassal_id=baron_id,
                                                 level=2)

    # инициализация поселений: население и лояльность зависят от типа
    duchy_of_province = _duchy_province_map()
    for idx, p in enumerate(provinces):
        defaults = {
            "duchy_id": duchy_of_province.get(idx),
            "hearths": HEARTHS_VILLAGE,
            "prosperity": 20,
            "loyalty": 70,
            "security": 10,
            "development": 1,
            "fort_level": 0,
            "garrison": 0,
            "villages": 2,
        }
        for field_name, value in defaults.items():
            if not hasattr(p, field_name):
                setattr(p, field_name, value)
        p.duchy_id = duchy_of_province.get(idx)
        # столицы и города богаче и лучше защищены
        region_type = getattr(p, "region_type", None)
        tier_name = getattr(region_type, "name", "")
        if tier_name == "CAPITAL":
            p.hearths = max(p.hearths, HEARTHS_CAPITAL)
            p.prosperity = max(p.prosperity, 35)
            p.fort_level = 2
            p.garrison = 200
        elif tier_name == "CITY":
            p.hearths = max(p.hearths, HEARTHS_CITY)
            p.prosperity = max(p.prosperity, 25)
            p.fort_level = 1
            p.garrison = 100

    return Hierarchy(provinces, duchies, realms, characters, contracts, streams=streams)


def auto_inherit(hierarchy: Hierarchy) -> List[str]:
    """Простейшее наследование: умерший правитель передаёт титул наследнику.

    Правило намеренно простое — самый лояльный живой персонаж того же
    владения. Полноценная родословная отложена: она тянет за собой UI и
    скрытую информацию, которые в 2D без сервера нечитаемы.
    """
    events: List[str] = []
    for ch in sorted(hierarchy.characters.values(), key=lambda c: c.id):
        if ch.alive or ch.rank is TitleRank.KING:
            continue
        if ch.duchy_id is None:
            continue
        # наследник — любой живой персонаж этого герцогства, ранг ниже не важен,
        # иначе титул герцога переходил бы только к другому герцогу (их нет)
        heirs = [c for c in hierarchy.characters.values()
                 if c.alive and c.duchy_id == ch.duchy_id and c.id != ch.id]
        heirs.sort(key=lambda c: (-c.loyalty, c.id))
        if not heirs:
            continue
        heir = heirs[0]
        if ch.rank is TitleRank.DUKE:
            heir.duchy_id = ch.duchy_id
            heir.realm_id = ch.realm_id
            hierarchy.duchies[ch.duchy_id].holder_id = heir.id
            events.append(f"{ch.name} погиб: герцогство {ch.duchy_id} → {heir.name}")
        if ch.province_idx is not None:
            heir.province_idx = ch.province_idx
            events.append(f"{heir.name} унаследовал #{ch.province_idx}")
        ch.duchy_id = None
    return events
