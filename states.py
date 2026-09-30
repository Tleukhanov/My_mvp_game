"""Средневековая иерархия владений: Kingdom -> Duchy -> County.

Референсы механик: Crusader Kings III (вассальные контракты, мнение,
титульные ожидания) и Mount & Blade: Bannerlord (экономика владений,
лояльность как множитель налога, деревни привязаны к графству).

Модуль намеренно чистый: только стандартная библиотека, без ``pygame``
и без импортов ``world_data``. Он оперирует любым объектом-провинцией,
у которого есть ``name``, ``owner`` и ``troops``, поэтому его можно
перенести в отдельный серверный процесс без правок.

Ключевые решения:

* **Графство = существующая провинция.** Новых геометрических сущностей
  не заводим, поэтому карта и её тесты не ломаются.
* **Герцогство = группа провинций** (de jure), по 5 штук на карте.
* **Расхождение de jure и de facto** — источник контента: нация может
  владеть частью чужого герцогства, и это видно игроку.
* Числа целочисленные либо из конечного набора уровней — чтобы
  :func:`sim.hashing.state_hash` не «дрожал» из-за плавающей точки.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


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
ROYAL_COURT_COST = 30

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
    """

    def __init__(
        self,
        provinces: Sequence,
        duchies: Optional[Dict[str, Duchy]] = None,
        realms: Optional[Dict[str, Realm]] = None,
        characters: Optional[Dict[str, Character]] = None,
        contracts: Optional[Dict[str, VassalContract]] = None,
    ):
        self.provinces = provinces
        self.duchies: Dict[str, Duchy] = duchies if duchies is not None else {}
        self.realms: Dict[str, Realm] = realms if realms is not None else {}
        self.characters: Dict[str, Character] = characters if characters is not None else {}
        #: ключ — id вассала, значение — контракт с сюзереном.
        self.contracts: Dict[str, VassalContract] = contracts if contracts is not None else {}
        self.turn: int = 1
        self.log: List[str] = []
        self._province_duchy: Dict[int, str] = {}
        self._rebuild_province_index()

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
        100. Поэтому гарнизон стоит денег, а его отсутствие не убивает
        поселение, но лишает его полного дохода.
        """
        events: List[str] = []
        for idx, p in enumerate(self.provinces):
            loyalty = getattr(p, "loyalty", 70)
            garrison = getattr(p, "garrison", 0)
            prosperity = getattr(p, "prosperity", 0)
            security = getattr(p, "security", 10)

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
        """Содержание королевства: левейс на стену, двор вассалов, резиденция."""
        realm = self.realms[realm_id]
        upkeep = self.realm_levy(realm_id) // LEVY_UPKEEP_DIVISOR
        ruler = realm.ruler_id
        if ruler:
            upkeep += COURT_COST_PER_VASSAL * len(self.vassals_of(ruler))
        return upkeep + ROYAL_COURT_COST

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
        """Один ход экономики. Порядок фиксирован — детерминизм для онлайна."""
        events: List[str] = []
        events += self.tick_counties()
        events += self.tick_vassals()
        events += self.tick_realms()
        self.turn += 1
        self.log.extend(events)
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


def _duchy_province_map() -> Dict[int, str]:
    """Индекс провинции -> id герцогства (de jure)."""
    mapping: Dict[int, str] = {}
    for duchy_id, _name, provs in DUCHY_DEFS:
        for idx in provs:
            mapping[idx] = duchy_id
    return mapping


def build_default_hierarchy(provinces: Sequence) -> Hierarchy:
    """Строит иерархию по текущей карте: 3 королевства, 6 герцогов, 12 баронов.

    Провинции получают ``duchy_id``, ``hearths``, ``prosperity``, ``loyalty``,
    ``security``, ``development``, ``garrison`` и ``villages`` с дефолтами —
    старые тесты, читающие ``owner``/``region_type``, продолжают работать.
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

    return Hierarchy(provinces, duchies, realms, characters, contracts)


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
