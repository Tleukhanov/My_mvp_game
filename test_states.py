"""Тесты модуля ``states`` — средневековая иерархия владений Kingdom -> Duchy -> County.

Здесь проверяются четыре контракта, на которых держится вся feudal-механика:

* **Вассальные контракты** — пять уровней, клампинг, отдача налогов/левейсов/тирании.
* **Иерархия владений** — 10 герцогств, 3 королевства, 21 персонаж, 18 контрактов.
* **Экономика графств** — доход как функция hearths/prosperity/loyalty/security/development.
* **Детерминизм** — ``sim.state_hash`` от ``summary()`` обязан совпадать у двух
  независимых симуляций, прошедших одинаковое число ходов.

Отдельный акцент сделан на **обратной совместимости**: ``build_default_hierarchy``
обязан НЕ трогать ``owner``/``region_type``/``troops`` провинций, иначе рассыпаются
старые 149 тестов карты и тактики.

Все фикстуры строят провинции через ``copy.deepcopy(WORLD_PROVINCES)`` — тесты
не мутируют глобальное состояние ``world_data`` и не зависят от порядка прогона.
"""

from __future__ import annotations

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import collections
import copy
import dataclasses
import random
from typing import Dict, List, Optional, Sequence, Tuple

import pytest

from sim import dumps, from_jsonable, loads, new_streams, register_enum, state_hash, to_jsonable
from states import (
    CHARACTERS_AGE_PER_TURN,
    CHARACTERS_DEATH_AGE_SPREAD,
    CHARACTER_DEATH_AGE,
    COMMAND_MIN_RANK,
    CONTRACT_CHANGES_PER_TURN,
    CONTRACT_LEVELS,
    COUNCIL_INFLUENCE,
    COUNCIL_LOYALTY,
    COUNTY_FIELDS,
    COURT_COST_PER_VASSAL,
    CROWN_COST,
    CROWN_PRESTIGE_COST,
    CROWN_RAISES_PER_TURN,
    DEATH_CAUSE_AGE,
    DEATH_CAUSE_KILLED,
    DEVELOPMENTS_PER_TURN,
    DEVELOPMENT_MAX,
    DEV_COST_BASE,
    DEV_COST_STEP,
    DUCHY_DEFS,
    GARRISON_ATTRITION,
    GARRISON_CAP_PER_FORT,
    GARRISON_HIRES_PER_TURN,
    GARRISON_IS_FREE_THRESHOLD,
    GARRISON_RECRUIT_COST_PER_100,
    GARRISON_UPKEEP_PER_100,
    GIFTS_PER_TURN,
    GIFT_COST,
    GIFT_LOYALTY,
    GIFT_LOYALTY_BY_COUNT,
    GIFT_OPINION,
    GIFT_OPINION_BY_COUNT,
    HIERARCHY_DEFAULT_SEED,
    LANDLESS_OPINION_DECAY,
    LEVY_BLOCK_TROOPS,
    LEVY_COST_PER_BLOCK,
    LEVY_RAISES_PER_TURN,
    LEVY_UPKEEP_DIVISOR,
    LOG_KEEP,
    LOYALTY_COLLAPSE,
    LOYALTY_TAX_BREAK,
    LOYALTY_TAX_FLOOR,
    MAX_CROWN_AUTHORITY,
    MERC_BLOCK_TROOPS,
    MERC_COST_PER_BLOCK,
    MERC_HIRES_PER_TURN,
    MERC_MAX_BLOCKS_PER_TURN,
    MERC_QUALITY_STREAM,
    MERC_SALT_STRIDE,
    MERC_TIER_THRESHOLDS,
    NEUTRAL_NATION,
    ORDER_DEADLINE_TURNS,
    ORDER_DEFAULT_WEIGHT,
    ORDER_REFUSAL_FLOOR,
    ORDER_REFUSAL_STEP,
    ORDERS_ISSUED_PER_TURN,
    ORDER_WEIGHTS,
    PUNISHED_LOYALTY,
    PUNISHED_OPINION,
    RAISED_LEVY_UPKEEP_DIVISOR,
    REBELLION_LOYALTY,
    REFUSED_WEIGHT,
    ROYAL_COURT_BASE_COST,
    ROYAL_COURT_PRESTIGE_DIVISOR,
    STATE_VERSION,
    SUCCESSION_CRISIS_TURNS,
    TAX_POLICY_CROWN_AUTHORITY,
    TAX_POLICY_MAX,
    TAX_POLICY_MIN,
    VASSAL_REBELLION_LOYALTY,
    Character,
    Hierarchy,
    Order,
    OrderKind,
    OrderStatus,
    SuccessionCrisis,
    Tier,
    TitleRank,
    VassalContract,
    as_int,
    auto_inherit,
    build_default_hierarchy,
    character_death_age,
    clean_mercenary_tiers,
    clean_order_args,
    development_tax_multiplier,
    development_upgrade_cost,
    gift_gain,
    loyalty_tax_multiplier,
    mercenary_salt,
    mercenary_tier,
    order_kind_of,
    order_refusal_threshold,
    order_weight,
    prosperity_tax_multiplier,
    security_tax_multiplier,
)
from world_data import RegionType, WORLD_PROVINCES

#: Стартовая раскладка владельцев на карте — её обязан уважать states.py.
EXPECTED_OWNERS: Dict[str, int] = {"red": 7, "blue": 7, "green": 7, "neutral": 29}

#: Ожидаемый стартовый состав иерархии.
EXPECTED_DUCHY_COUNT = 10
EXPECTED_REALM_COUNT = 3
EXPECTED_CHARACTER_COUNT = 21
EXPECTED_CONTRACT_COUNT = 18
EXPECTED_RANKS: Dict[TitleRank, int] = {TitleRank.KING: 3, TitleRank.DUKE: 6, TitleRank.BARON: 12}

#: Индексы столиц на текущей карте (RegionType.CAPITAL).
CAPITAL_INDICES: Tuple[int, ...] = (10, 32, 42)

#: Ключи, которых в снапшоте быть НЕ должно ни на каком уровне вложенности.
#: Геометрия — мирового слоя, ``_province_duchy`` — производный кэш,
#: ``streams`` — внешний ГПСЧ, ``linked_general`` — внешняя ссылка.
FORBIDDEN_STATE_KEYS: Tuple[str, ...] = (
    "provinces", "polygon", "_centroid", "streams", "linked_general",
)

#: Точный набор ВЕРХНЕУРОВНЕВЫХ ключей снапшота. Жёстко зафиксирован, потому
#: что это весь контракт ``to_state``: лишний ключ — это либо мусор в хеше, либо
#: обещание, которого ``from_state`` не сдержит. Вынесено в одну константу,
#: потому что проверяется в четырёх местах, и раньше эти места уже разошлись бы
#: при добавлении поля. ``orders`` добавлен этапом 1.2: у приказа есть срок
#: и последствия, поэтому это состояние, а не история. ``succession_crises``
#: добавлен этапом 4: пустой трон — это тоже состояние, а не строчка в журнале.
SNAPSHOT_KEYS = {
    "version", "turn", "log", "log_truncated",
    "realms", "duchies", "characters", "contracts", "orders",
    "succession_crises", "counties",
}

#: Герцогства, у которых на текущей карте есть de-факто держатель (этап 2):
#: нация владеет строгим большинством de jure провинций. Карта зафиксирована в
#: ``world_data.py``, и таблица ниже — её проверка на владение: если параллельный
#: агент перекрасит провинцию, тест упадёт с понятным сообщением, а не
#: «доход герцогства неожиданно изменился».
EXPECTED_DE_FACTO_HOLDERS: Dict[str, str] = {
    "ravenhold": "duke_aldric",    # red 4:1
    "blackridge": "duke_vasya",    # red 3:2
    "emberfall": "duke_brenna",    # blue 4:1
    "dawnmarch": "duke_theon",     # blue 3:2
    "leafguard": "duke_lyra",      # green 5:0
}

#: Герцогства без de-факто держателя: большинства нет (ничья или полный
#: нейтралитет). ``goldfield`` здесь — важный случай: 2 зелёные из 5, то есть
#: ровно НЕ большинство, поэтому герцогства нет, хотя нация там что-то имеет.
NEUTRAL_DUCHIES: Tuple[str, ...] = (
    "northmark", "southmarch", "stonewaste", "greymoor", "goldfield",
)


# --------------------------------------------------------------------------
# Фикстуры и хелперы
# --------------------------------------------------------------------------


def copy_provinces() -> List:
    """Глубокая копия карты: тесты не имеют права мутировать WORLD_PROVINCES."""
    return copy.deepcopy(WORLD_PROVINCES)


def make_hierarchy() -> Hierarchy:
    """Иерархия на свежей копии карты — изолированный мир для одного теста."""
    return build_default_hierarchy(copy_provinces())


def owner_counts(provinces: Sequence) -> Dict[str, int]:
    return dict(collections.Counter(p.owner for p in provinces))


def characters_by_rank(h: Hierarchy, rank: TitleRank) -> List[Character]:
    return [c for c in h.characters.values() if c.rank is rank]


def set_settlement(p, *, hearths: int, prosperity: int, loyalty: int,
                   security: int, development: int) -> None:
    """Явно выставить все поля поселения, влияющие на доход."""
    p.hearths = hearths
    p.prosperity = prosperity
    p.loyalty = loyalty
    p.security = security
    p.development = development


def income_with(h: Hierarchy, idx: int, **fields) -> int:
    """Доход графства при заданных полях поселения (остальное — дефолт)."""
    set_settlement(h.provinces[idx], **fields)
    return h.county_income(idx)


@pytest.fixture
def provinces() -> List:
    """Копия провинций без иерархии — для тестов на саму разметку."""
    return copy_provinces()


@pytest.fixture
def h() -> Hierarchy:
    """Готовая иерархия на свежей копии карты."""
    return make_hierarchy()


@pytest.fixture
def twin_hierarchies() -> Tuple[Hierarchy, Hierarchy]:
    """Две независимые копии мира — база для проверок детерминизма."""
    return make_hierarchy(), make_hierarchy()


# --------------------------------------------------------------------------
# Контракты
# --------------------------------------------------------------------------


class TestContractLevels:
    """Пять уровней феодального контракта и их клампинг."""

    def setup_method(self):
        self.h = make_hierarchy()
        self.baron = "baron_volkov"

    # --- форма набора уровней ---

    def test_exactly_five_levels(self):
        assert len(CONTRACT_LEVELS) == 5

    def test_every_level_has_tax_levy_and_tyranny(self):
        for level, spec in enumerate(CONTRACT_LEVELS):
            assert "tax" in spec, level
            assert "levy" in spec, level
            assert "tyranny" in spec, level
            assert "name" in spec, level

    def test_tax_strictly_increases_with_level(self):
        taxes = [spec["tax"] for spec in CONTRACT_LEVELS]
        assert taxes == sorted(taxes)
        assert all(b > a for a, b in zip(taxes, taxes[1:]))

    def test_levy_strictly_increases_with_level(self):
        levies = [spec["levy"] for spec in CONTRACT_LEVELS]
        assert levies == sorted(levies)
        assert all(b > a for a, b in zip(levies, levies[1:]))

    def test_tyranny_only_on_harsh_levels(self):
        # тирания копится только на верхних уровнях и не убывает
        tyrannies = [spec["tyranny"] for spec in CONTRACT_LEVELS]
        assert all(b >= a for a, b in zip(tyrannies, tyrannies[1:]))
        assert CONTRACT_LEVELS[0]["tyranny"] == 0
        assert CONTRACT_LEVELS[-1]["tyranny"] > 0

    def test_tax_and_levy_are_bounded(self):
        for spec in CONTRACT_LEVELS:
            assert 0 <= spec["tax"] <= 100
            assert 0 <= spec["levy"] <= 100
        # налог всегда не меньше левейса — иначе логика доминирования ломается
        for spec in CONTRACT_LEVELS:
            assert spec["tax"] >= spec["levy"]

    # --- клампинг в Hierarchy.set_contract ---

    def test_level_above_max_is_clamped(self):
        self.h.set_contract(self.baron, len(CONTRACT_LEVELS) + 17)
        assert self.h.contracts[self.baron].level == len(CONTRACT_LEVELS) - 1

    def test_level_below_min_is_clamped_to_zero(self):
        self.h.set_contract(self.baron, -25)
        assert self.h.contracts[self.baron].level == 0

    def test_clamping_survives_float_input(self):
        self.h.set_contract(self.baron, 3.9)
        assert self.h.contracts[self.baron].level == 3
        self.h.set_contract(self.baron, 2.1)
        assert self.h.contracts[self.baron].level == 2

    def test_set_contract_on_unknown_vassal_is_noop(self):
        assert self.h.set_contract("baron_who_is_not_here", 4) == []
        assert "baron_who_is_not_here" not in self.h.contracts

    def test_set_contract_keeps_vassal_id_and_finds_liege(self):
        self.h.set_contract(self.baron, 3)
        contract = self.h.contracts[self.baron]
        assert contract.vassal_id == self.baron
        assert contract.liege_id == "duke_aldric"

    # --- VassalContract как вью над уровнем ---

    def test_contract_reports_tax_levy_and_tyranny_per_level(self):
        for level, spec in enumerate(CONTRACT_LEVELS):
            contract = VassalContract(liege_id="king_erik", vassal_id="duke_aldric",
                                      level=level)
            assert contract.spec == spec
            assert contract.tax_percent == spec["tax"]
            assert contract.levy_percent == spec["levy"]
            assert contract.tyranny == spec["tyranny"]

    def test_contract_of_returns_contract_by_vassal_id(self):
        contract = self.h.contract_of(self.baron)
        assert isinstance(contract, VassalContract)
        assert contract.vassal_id == self.baron
        assert self.h.contract_of("nobody") is None

    def test_hierarchy_contracts_cover_dukes_and_barons(self):
        expected = {c.id for c in self.h.characters.values() if c.rank is not TitleRank.KING}
        assert set(self.h.contracts) == expected
        assert len(self.h.contracts) == EXPECTED_CONTRACT_COUNT


# --------------------------------------------------------------------------
# Построение иерархии
# --------------------------------------------------------------------------


class TestHierarchyBuild:
    """``build_default_hierarchy`` строит ожидаемую карту и не портит старую."""

    def setup_method(self):
        self.provinces = copy_provinces()
        self.owners_before = owner_counts(self.provinces)
        self.region_types_before = [p.region_type for p in self.provinces]
        self.h = build_default_hierarchy(self.provinces)

    # --- размеры и состав ---

    def test_ten_duchies(self):
        assert len(self.h.duchies) == EXPECTED_DUCHY_COUNT
        assert len(DUCHY_DEFS) == EXPECTED_DUCHY_COUNT

    def test_three_realms(self):
        assert len(self.h.realms) == EXPECTED_REALM_COUNT
        assert {r.nation for r in self.h.realms.values()} == {"red", "blue", "green"}

    def test_twenty_one_characters(self):
        assert len(self.h.characters) == EXPECTED_CHARACTER_COUNT

    def test_eighteen_contracts(self):
        assert len(self.h.contracts) == EXPECTED_CONTRACT_COUNT

    def test_three_kings_six_dukes_twelve_barons(self):
        for rank, expected in EXPECTED_RANKS.items():
            assert len(characters_by_rank(self.h, rank)) == expected, rank

    def test_every_realm_has_a_ruler(self):
        for realm in self.h.realms.values():
            assert realm.ruler_id in self.h.characters
            assert self.h.characters[realm.ruler_id].rank is TitleRank.KING

    def test_turn_starts_at_one_and_log_is_empty(self):
        assert self.h.turn == 1
        assert self.h.log == []

    # --- разметка de jure ---

    def test_every_province_has_duchy_id(self):
        for idx, p in enumerate(self.provinces):
            assert p.duchy_id is not None, idx
            assert p.duchy_id in self.h.duchies, idx

    def test_duchy_of_matches_province_attribute(self):
        for idx, p in enumerate(self.provinces):
            assert self.h.duchy_of(idx) == p.duchy_id, idx

    def test_duchy_of_unknown_province_is_none(self):
        assert self.h.duchy_of(999) is None
        assert self.h.duchy_of(-1) is None

    def test_duchies_cover_all_provinces_without_gaps_or_duplicates(self):
        covered: List[int] = []
        for duchy in self.h.duchies.values():
            covered.extend(duchy.de_jure_provinces)
        assert len(covered) == len(self.provinces)
        assert len(set(covered)) == len(covered), "провинция попала в два герцогства"
        assert sorted(covered) == list(range(len(self.provinces)))

    def test_counties_of_duchy_returns_de_jure_list(self):
        for duchy in self.h.duchies.values():
            assert self.h.counties_of_duchy(duchy.id) == list(duchy.de_jure_provinces)
        assert self.h.counties_of_duchy("no_such_duchy") == []

    # --- держатели герцогств ---

    def test_every_duke_holds_his_duchy(self):
        for duke in characters_by_rank(self.h, TitleRank.DUKE):
            duchy = self.h.duchies[duke.duchy_id]
            assert duchy.holder_id == duke.id, duke.id

    def test_holder_id_points_to_existing_character(self):
        for duchy in self.h.duchies.values():
            if duchy.holder_id is None:
                continue
            holder = self.h.characters[duchy.holder_id]
            assert holder.rank is TitleRank.DUKE
            assert holder.duchy_id == duchy.id
            assert self.h.holder_of_duchy(duchy.id) is holder

    def test_holder_of_empty_duchy_is_none(self):
        assert self.h.holder_of_duchy("northmark") is None
        assert self.h.holder_of_duchy("nope") is None

    def test_duchy_realm_id_matches_holder_nation(self):
        for duchy in self.h.duchies.values():
            if duchy.holder_id is None:
                assert duchy.realm_id is None
                continue
            nation = self.h.characters[duchy.holder_id].nation
            assert self.h.realms[duchy.realm_id].nation == nation

    # --- ОБРАТНАЯ СОВМЕСТИМОСТЬ: owner/region_type не трогаем ---

    def test_owner_field_unchanged(self):
        # legacy-контракт: старые 149 тестов карты читают owner как есть
        assert owner_counts(self.provinces) == EXPECTED_OWNERS
        assert owner_counts(self.provinces) == self.owners_before

    def test_region_type_and_troops_unchanged(self):
        assert [p.region_type for p in self.provinces] == self.region_types_before
        assert all(p.troops == 0 for p in self.provinces)
        assert [p.name for p in self.provinces] == [p.name for p in WORLD_PROVINCES]

    def test_global_world_provinces_untouched(self):
        # фикстуры не должны оставлять мусор в глобальном world_data
        assert owner_counts(WORLD_PROVINCES) == EXPECTED_OWNERS
        for p in WORLD_PROVINCES:
            assert not hasattr(p, "duchy_id")
            assert not hasattr(p, "hearths")

    # --- инициализация поселений ---

    def test_capitals_are_bigger_and_more_fortified(self):
        capitals = [self.provinces[i] for i in CAPITAL_INDICES]
        villages = [p for p in self.provinces if p.region_type is RegionType.VILLAGE]
        assert all(p.region_type is RegionType.CAPITAL for p in capitals)
        assert min(p.hearths for p in capitals) > max(p.hearths for p in villages)
        assert min(p.fort_level for p in capitals) > max(p.fort_level for p in villages)
        assert min(p.garrison for p in capitals) > max(p.garrison for p in villages)
        assert min(p.prosperity for p in capitals) > max(p.prosperity for p in villages)

    def test_every_settlement_gets_economic_fields(self):
        for p in self.provinces:
            assert p.hearths > 0
            assert 0 <= p.prosperity <= 100
            assert 0 <= p.loyalty <= 100
            assert 0 <= p.security <= 20
            assert 1 <= p.development <= 10
            assert p.villages >= 0

    # --- ранги ---

    def test_tier_follows_rank(self):
        expected = {
            TitleRank.KING: Tier.REALM,
            TitleRank.DUKE: Tier.DUCHY,
            TitleRank.BARON: Tier.COUNTY,
        }
        for ch in self.h.characters.values():
            assert ch.tier is expected[ch.rank], ch.id

    def test_tier_ordering_is_strict(self):
        assert Tier.COUNTY < Tier.DUCHY < Tier.REALM

    def test_is_ruler_reflects_land_holding(self):
        for ch in characters_by_rank(self.h, TitleRank.BARON):
            assert ch.is_ruler == (ch.province_idx is not None)
        for ch in characters_by_rank(self.h, TitleRank.DUKE):
            assert ch.is_ruler == (ch.duchy_id is not None)
        for ch in characters_by_rank(self.h, TitleRank.KING):
            assert ch.is_ruler == (ch.realm_id is not None)

    def test_province_accessor_and_len(self):
        assert self.h.province(0) is self.provinces[0]
        assert len(self.h.provinces) == 50

    def test_hierarchy_works_on_duck_typed_provinces(self, provinces):
        # states.py обещает не знать про world_data: достаточно name/owner/troops
        class Bare:
            def __init__(self, name: str, owner: str):
                self.name = name
                self.owner = owner
                self.troops = 0

        bare = [Bare(f"p{i}", "neutral") for i in range(len(provinces))]
        h = build_default_hierarchy(bare)
        assert h.province(0) is bare[0]
        assert h.duchy_of(0) == "northmark"
        assert h.county_income(0) > 0, "дефолтные hearths должны давать доход"
        assert h.realm_income("kingdom_ember") == 0, "у голых провинций нет владельцев"
        assert h.provinces_of_realm("kingdom_ember") == []


# --------------------------------------------------------------------------
# Цепочка сюзеренов
# --------------------------------------------------------------------------


class TestLiegeChain:
    """Кто кому сюзерен и как королевская власть распространяется вниз."""

    def setup_method(self):
        self.h = make_hierarchy()

    def test_baron_liege_is_holder_of_his_duchy(self):
        for baron in characters_by_rank(self.h, TitleRank.BARON):
            liege = self.h.liege_of(baron.id)
            assert liege is not None, baron.id
            assert liege.rank is TitleRank.DUKE
            assert liege.duchy_id == baron.duchy_id

    def test_duke_liege_is_king_of_his_realm(self):
        for duke in characters_by_rank(self.h, TitleRank.DUKE):
            liege = self.h.liege_of(duke.id)
            assert liege is not None, duke.id
            assert liege.rank is TitleRank.KING
            assert liege.realm_id == duke.realm_id
            assert liege.nation == duke.nation

    def test_king_has_no_liege(self):
        for king in characters_by_rank(self.h, TitleRank.KING):
            assert self.h.liege_of(king.id) is None

    def test_liege_of_unknown_character_is_none(self):
        assert self.h.liege_of("nobody") is None

    def test_vassals_of_king_are_dukes_of_his_nation(self):
        for king in characters_by_rank(self.h, TitleRank.KING):
            vassals = self.h.vassals_of(king.id)
            assert vassals, king.id
            assert len(vassals) == 2, king.id
            for duke in vassals:
                assert duke.rank is TitleRank.DUKE
                assert duke.nation == king.nation
                assert self.h.liege_of(duke.id) is king

    def test_vassals_of_duke_are_barons_of_his_duchy(self):
        for duke in characters_by_rank(self.h, TitleRank.DUKE):
            vassals = self.h.vassals_of(duke.id)
            assert len(vassals) == 2, duke.id
            for baron in vassals:
                assert baron.rank is TitleRank.BARON
                assert baron.duchy_id == duke.duchy_id

    def test_vassals_of_baron_is_empty(self):
        for baron in characters_by_rank(self.h, TitleRank.BARON):
            assert self.h.vassals_of(baron.id) == []

    def test_vassals_skip_dead_and_sorted_by_id(self):
        self.h.characters["baron_korzh"].alive = False
        ids = [c.id for c in self.h.vassals_of("duke_aldric")]
        assert ids == ["baron_volkov"]
        self.h.characters["king_erik"].alive = False
        assert [c.id for c in self.h.vassals_of("king_erik")] == ["duke_aldric", "duke_vasya"]

    def test_authority_reaches_baron_through_whole_chain(self):
        for king in characters_by_rank(self.h, TitleRank.KING):
            self.h.realms[king.realm_id].crown_authority = 3
        for ch in self.h.characters.values():
            if ch.rank is TitleRank.KING:
                continue
            assert self.h.liege_authority(ch.id) == 3, ch.id

    def test_authority_zero_when_crown_authority_zero(self):
        for realm in self.h.realms.values():
            realm.crown_authority = 0
        for ch in self.h.characters.values():
            assert self.h.liege_authority(ch.id) == 0, ch.id

    def test_authority_always_inside_zero_three(self):
        for crown in (-5, 0, 1, 2, 3, 9):
            for realm in self.h.realms.values():
                realm.crown_authority = crown
            for ch in self.h.characters.values():
                assert 0 <= self.h.liege_authority(ch.id) <= 3, (crown, ch.id)

    def test_authority_of_unknown_character_is_zero(self):
        assert self.h.liege_authority("nobody") == 0

    def test_no_infinite_loop_when_duchy_holds_itself(self):
        # испорченный граф: держатель герцогства — сам барон этого герцогства
        self.h.duchies["ravenhold"].holder_id = "baron_volkov"
        assert self.h.liege_of("baron_volkov") is None
        assert self.h.liege_authority("baron_volkov") == 0
        assert isinstance(self.h.vassals_of("baron_volkov"), list)

    def test_no_infinite_loop_on_mutual_holder_cycle(self):
        # настоящий цикл: два барона держат герцогства друг друга
        self.h.duchies["ravenhold"].holder_id = "baron_gray"
        self.h.duchies["greymoor"].holder_id = "baron_volkov"
        assert self.h.liege_of("baron_volkov") is self.h.characters["baron_gray"]
        assert self.h.liege_of("baron_gray") is self.h.characters["baron_volkov"]
        assert self.h.liege_authority("baron_volkov") == 0
        assert self.h.liege_authority("baron_gray") == 0
        self.h.end_turn()  # тики тоже не должны зависнуть

    def test_vassal_power_is_positive_for_living_rulers(self):
        king = self.h.characters["king_erik"]
        assert self.h.vassal_power(king) > 0
        king.alive = False
        assert self.h.vassal_power(king) == 0

    def test_powerful_vassals_belong_to_realm_and_are_not_kings(self):
        for realm_id in self.h.realms:
            strong = self.h.powerful_vassals(realm_id)
            assert strong, realm_id
            for ch in strong:
                assert ch.realm_id == realm_id
                assert ch.rank is not TitleRank.KING
            assert [c.id for c in strong] == sorted([c.id for c in strong],
                                                    key=lambda i: (-self.h.vassal_power(
                                                        self.h.characters[i]), i))


# --------------------------------------------------------------------------
# Экономика
# --------------------------------------------------------------------------


class TestEconomy:
    """Доход графств, герцогств и королевств."""

    def setup_method(self):
        self.h = make_hierarchy()

    # --- формула графства ---

    def test_income_is_zero_without_hearths(self):
        for idx in (0, 10, 25, 49):
            assert income_with(self.h, idx, hearths=0, prosperity=100, loyalty=100,
                               security=20, development=10) == 0

    def test_income_grows_with_prosperity(self):
        incomes = [income_with(self.h, 0, hearths=10000, prosperity=prosperity,
                               loyalty=100, security=20, development=10)
                   for prosperity in (25, 50, 75, 100)]
        assert all(b > a for a, b in zip(incomes, incomes[1:]))

    def test_income_grows_with_loyalty(self):
        incomes = [income_with(self.h, 0, hearths=10000, prosperity=100, loyalty=loyalty,
                               security=20, development=10)
                   for loyalty in (50, 60, 70, 80, 100)]
        assert all(b > a for a, b in zip(incomes, incomes[1:]))

    def test_income_grows_with_security(self):
        incomes = [income_with(self.h, 0, hearths=10000, prosperity=100, loyalty=100,
                               security=security, development=10)
                   for security in (0, 5, 10, 15, 20)]
        assert all(b > a for a, b in zip(incomes, incomes[1:]))

    def test_income_grows_with_development(self):
        incomes = [income_with(self.h, 0, hearths=10000, prosperity=100, loyalty=100,
                               security=20, development=development)
                   for development in (1, 3, 5, 7, 10)]
        assert all(b > a for a, b in zip(incomes, incomes[1:]))

    def test_income_grows_with_hearths(self):
        incomes = [income_with(self.h, 0, hearths=hearths, prosperity=50, loyalty=100,
                               security=20, development=5)
                   for hearths in (100, 500, 1000, 2000)]
        assert all(b > a for a, b in zip(incomes, incomes[1:]))

    def test_levy_grows_with_hearths_and_development(self):
        p = self.h.provinces[0]
        p.hearths = 1000
        p.development = 1
        low = self.h.county_levy(0)
        p.development = 10
        high = self.h.county_levy(0)
        assert high > low >= 0
        p.hearths = 0
        assert self.h.county_levy(0) == 0

    # --- множители ---

    def test_loyalty_tax_multiplier_zero_below_collapse(self):
        for loyalty in (0, 1, LOYALTY_COLLAPSE - 1):
            assert loyalty_tax_multiplier(loyalty) == 0.0, loyalty

    def test_loyalty_tax_multiplier_above_one_when_loyal(self):
        # точка нейтралитета — LOYALTY_TAX_BREAK (50), а не порог разорения
        assert loyalty_tax_multiplier(LOYALTY_TAX_BREAK) == 1.0
        assert loyalty_tax_multiplier(80) > 1.0
        assert loyalty_tax_multiplier(100) > loyalty_tax_multiplier(80)
        # максимум по замыслу «+20% при полной лояльности», а не x11
        assert loyalty_tax_multiplier(100) <= 1.2

    def test_loyalty_tax_multiplier_degrades_gradually(self):
        # между разорением и нейтралителю доход падает плавно, с полом
        assert loyalty_tax_multiplier(LOYALTY_COLLAPSE) == LOYALTY_TAX_FLOOR
        mid = loyalty_tax_multiplier(LOYALTY_COLLAPSE + 5)
        assert LOYALTY_TAX_FLOOR < mid < 1.0

    def test_development_tax_multiplier_in_range(self):
        for dev in range(-5, 20):
            assert 0.6 <= development_tax_multiplier(dev) <= 1.5, dev
        values = [development_tax_multiplier(d) for d in range(1, 11)]
        assert all(b > a for a, b in zip(values, values[1:]))

    def test_vassal_rebellion_threshold_is_separate_from_county(self):
        # пороги сознательно разные: посёлок и персонаж — разные сущности
        assert VASSAL_REBELLION_LOYALTY == 15
        assert REBELLION_LOYALTY == 25

    def test_loyalty_tax_multiplier_monotonic_above_collapse(self):
        values = [loyalty_tax_multiplier(x) for x in range(LOYALTY_COLLAPSE, 101)]
        assert all(b >= a for a, b in zip(values, values[1:]))

    def test_security_tax_multiplier_in_range(self):
        for security in range(-50, 121):
            assert 0.5 <= security_tax_multiplier(security) <= 1.5, security

    def test_security_tax_multiplier_is_monotonic(self):
        values = [security_tax_multiplier(x) for x in range(0, 25)]
        assert all(b >= a for a, b in zip(values, values[1:]))
        assert security_tax_multiplier(0) < security_tax_multiplier(20)

    def test_prosperity_tax_multiplier_clamped(self):
        assert 0.5 <= prosperity_tax_multiplier(0) <= 2.0
        assert 0.5 <= prosperity_tax_multiplier(100) <= 2.0
        assert 0.5 <= prosperity_tax_multiplier(1000) <= 2.0
        assert prosperity_tax_multiplier(100) >= prosperity_tax_multiplier(25)

    # --- агрегаты ---

    def test_duchy_income_counts_only_provinces_of_the_de_facto_nation(self):
        """Этап 2. Прежний тест жёстко закреплял ДВОЙНОЙ ДОХОД и был багом.

        Старое поведение было таким: ``duchy_income`` суммировал ``county_income``
        по ВСЕМ de jure провинциям герцогства, не глядя на ``province.owner``.
        То есть завоёванное иностранное графство платило и завоевателю
        (``realm_income`` считается по ``owner``), и прежнему герцогу (здесь — по
        титулу): одна и та же деревня засчитывалась в доход дважды, и
        ``summary()`` показывал игроку сумму, которую никто не получал.

        Правильная семантика: платит нация de-факто держателя и только те
        графства, которые реально её. Поэтому проверка идёт не по de jure, а по
        ``counties_factually_held``.
        """
        for duchy in self.h.duchies.values():
            holder = self.h.de_facto_holder_of_duchy(duchy.id)
            if holder is None:
                assert self.h.duchy_income(duchy.id) == 0, duchy.id
                continue
            owned = self.h.counties_factually_held(duchy.id, holder.nation)
            expected = sum(self.h.county_income(i) for i in owned)
            assert self.h.duchy_income(duchy.id) == expected, duchy.id
            assert owned, f"{duchy.id}: у держателя нет ни одного графства"

    def test_duchy_levy_counts_only_provinces_of_the_de_facto_nation(self):
        """Тот же контракт для левейса (был суммой по всем de jure провинциям)."""
        for duchy in self.h.duchies.values():
            holder = self.h.de_facto_holder_of_duchy(duchy.id)
            if holder is None:
                assert self.h.duchy_levy(duchy.id) == 0, duchy.id
                continue
            owned = self.h.counties_factually_held(duchy.id, holder.nation)
            expected = sum(self.h.county_levy(i) for i in owned)
            assert self.h.duchy_levy(duchy.id) == expected, duchy.id

    def test_random_world_income_is_still_consistent(self):
        # те же случайные поселения, но сверка идёт по правильной семантике:
        # по de jure сумма уже не равна дукционному доходу, и это НЕ баг
        rng = random.Random(12345)
        for idx in range(50):
            p = self.h.provinces[idx]
            p.hearths = rng.randint(0, 2000)
            p.security = rng.randint(0, 20)
        for duchy in self.h.duchies.values():
            holder = self.h.de_facto_holder_of_duchy(duchy.id)
            if holder is None:
                assert self.h.duchy_income(duchy.id) == 0
                continue
            assert self.h.duchy_income(duchy.id) == sum(
                self.h.county_income(i)
                for i in self.h.counties_factually_held(duchy.id, holder.nation))

    def test_duchy_income_does_not_double_count_a_conquered_county(self):
        """ГЛАВНЫЙ тест этапа 2: одна провинция платит ровно один раз.

        Захватываем чужое графство и проверяем, что прежний герцог перестаёт его
        видеть в своём доходе, а завоеватель платит за него один раз — в сумме
        по realm'ам, а не дважды поrealm'ам.
        """
        # Завоёвываем emberfall (25-29) нации red. De jure герцог — duke_brenna из
        # blue: его титул захват не отбирает.
        for idx in (25, 26, 27, 28, 29):
            self.h.transfer_county(idx, "red", None, cause="захват")
        emberfall = self.h.duchies["emberfall"]
        assert emberfall.holder_id == "duke_brenna", "de jure титул не отбирается"
        assert self.h.majority_nation_of_duchy("emberfall") == "red"
        # де-факто правителем становится КОРОЛЬ red: держателя дукции у red в
        # этом герцогстве нет, и страна правит своей областью через трон
        assert emberfall.de_facto_holder_id == "king_erik"
        assert self.h.de_facto_holder_of_duchy("emberfall") is \
            self.h.characters["king_erik"]
        owned_by_red = self.h.counties_factually_held("emberfall", "red")
        assert owned_by_red == [25, 26, 27, 28, 29]
        assert self.h.duchy_income("emberfall") == sum(
            self.h.county_income(i) for i in owned_by_red)
        # прежний герцог blue больше не получает дохода за эти графства
        assert self.h.counties_factually_held("emberfall", "blue") == []
        # и ни одно графство не платит дважды: сумма по realm'ам равна сумме
        # по фактическим владельцам провинций
        total = sum(self.h.realm_income(r) for r in self.h.realms)
        by_nation = sum(self.h.county_income(i) for i, p in enumerate(self.h.provinces)
                        if p.owner != "neutral")
        assert total == by_nation, "ни одно графство не должно платить дважды"

    def test_neutral_duchy_pays_nobody(self):
        for duchy_id in NEUTRAL_DUCHIES:
            assert self.h.de_facto_holder_of_duchy(duchy_id) is None, duchy_id
            assert self.h.majority_nation_of_duchy(duchy_id) is None, duchy_id
            assert self.h.duchy_income(duchy_id) == 0, duchy_id

    def test_realm_income_counts_only_own_provinces(self):
        for realm in self.h.realms.values():
            owned = [i for i, p in enumerate(self.h.provinces) if p.owner == realm.nation]
            assert owned == self.h.provinces_of_realm(realm.id)
            assert self.h.realm_income(realm.id) == sum(
                self.h.county_income(i) for i in owned)

    def test_realm_income_is_split_between_realms(self):
        total = sum(self.h.county_income(i) for i in range(50))
        by_realm = sum(self.h.realm_income(r) for r in self.h.realms)
        # нейтральные земли не платят ни одному королевству
        assert 0 < by_realm < total

    def test_realm_levy_matches_owned_provinces(self):
        for realm in self.h.realms.values():
            owned = self.h.provinces_of_realm(realm.id)
            assert self.h.realm_levy(realm.id) == sum(self.h.county_levy(i) for i in owned)

    def test_income_never_negative_on_random_valid_settlements(self):
        rng = random.Random(12345)
        for idx in range(50):
            set_settlement(
                self.h.provinces[idx],
                hearths=rng.randint(0, 2000),
                prosperity=rng.randint(0, 100),
                loyalty=rng.randint(0, 100),
                security=rng.randint(0, 20),
                development=rng.randint(1, 10),
            )
            assert self.h.county_income(idx) >= 0, idx
            assert self.h.county_levy(idx) >= 0, idx


# --------------------------------------------------------------------------
# Мнение, лояльность, мятежи
# --------------------------------------------------------------------------


class TestOpinionAndLoyalty:
    """Передача владений, контракты и последствия для мнения."""

    def setup_method(self):
        self.h = make_hierarchy()
        self.baron = self.h.characters["baron_wolf"]

    def test_grant_fief_raises_opinion_for_landless_vassal(self):
        self.h.revoke_fief("baron_wolf")
        before = self.baron.opinion_of_liege
        events = self.h.grant_fief(47, "baron_wolf")
        assert self.baron.opinion_of_liege > before
        assert self.baron.opinion_of_liege <= 100
        assert events, "выдача земли обязана попасть в лог"

    def test_grant_fief_clears_landless_and_sets_ownership(self):
        # свежий барон-новичок: duchy_id ещё None — grant_fief обязан его выставить
        self.baron.province_idx = None
        self.baron.duchy_id = None
        self.assert_landless("baron_wolf")
        self.h.grant_fief(47, "baron_wolf")
        assert self.baron.province_idx == 47
        assert self.baron.landless_turns == 0
        assert self.baron.is_ruler
        assert self.baron.duchy_id == self.h.duchy_of(47) == "goldfield"

    def test_grant_fief_recomputes_duchy_on_move(self):
        # duchy_id обязан пересчитываться при переезде, иначе рвётся связь
        # «барон -> duchy_id -> сюзерен» и он остаётся вассалом прежнего герцога
        assert self.baron.duchy_id == "greymoor"
        self.h.revoke_fief("baron_wolf")
        self.h.grant_fief(40, "baron_wolf")  # 40 входит в leafguard (duke_lyra)
        assert self.baron.duchy_id == "leafguard"
        assert self.h.duchy_of(40) == "leafguard"
        assert self.h.liege_of("baron_wolf").id == "duke_lyra"

    def test_grant_fief_into_unheld_duchy_leaves_no_liege(self):
        # нейтральные герцогства (goldfield) не имеют герцога — сюзерена нет
        self.h.revoke_fief("baron_wolf")
        self.h.grant_fief(47, "baron_wolf")
        assert self.baron.duchy_id == "goldfield"
        assert self.h.liege_of("baron_wolf") is None

    def test_grant_fief_on_unknown_baron_is_noop(self):
        assert self.h.grant_fief(3, "baron_ghost") == []

    def test_revoke_fief_drops_opinion_and_clears_ownership(self):
        before = self.baron.opinion_of_liege
        events = self.h.revoke_fief("baron_wolf")
        assert self.baron.opinion_of_liege < before
        assert self.baron.province_idx is None
        assert not self.baron.is_ruler
        assert events

    def test_revoke_fief_on_unknown_baron_is_noop(self):
        assert self.h.revoke_fief("baron_ghost") == []

    def test_opinion_clamped_to_hundred(self):
        self.baron.opinion_of_liege = 100
        self.h.revoke_fief("baron_wolf")
        assert self.baron.opinion_of_liege == 80
        self.baron.province_idx = None
        self.baron.opinion_of_liege = -100
        self.h.grant_fief(47, "baron_wolf")
        assert self.baron.opinion_of_liege == -80

    # --- контракт против мнения ---

    def test_raising_contract_cuts_opinion(self):
        baron = self.h.characters["baron_volkov"]
        before = baron.opinion_of_liege
        self.h.set_contract("baron_volkov", 3)
        assert self.h.contracts["baron_volkov"].level == 3
        assert baron.opinion_of_liege < before

    def test_lowering_contract_raises_opinion(self):
        self.h.set_contract("baron_volkov", 3)
        baron = self.h.characters["baron_volkov"]
        before = baron.opinion_of_liege
        self.h.set_contract("baron_volkov", 1)
        assert self.h.contracts["baron_volkov"].level == 1
        assert baron.opinion_of_liege > before

    def test_first_contract_for_known_vassal_is_cheaper(self):
        # у новичка нет «старого» контракта — штраф мягче, чем при повышении
        del self.h.contracts["baron_volkov"]
        baron = self.h.characters["baron_volkov"]
        baron.opinion_of_liege = 0
        self.h.set_contract("baron_volkov", 4)
        assert baron.opinion_of_liege == -5

    def test_same_contract_level_reports_no_change(self):
        events = self.h.set_contract("baron_volkov", 2)
        assert len(events) == 1
        assert self.h.characters["baron_volkov"].opinion_of_liege == 20

    # --- выполнение приказов ---

    def test_can_accept_order_with_positive_opinion(self):
        self.baron.opinion_of_liege = 0
        assert self.h.can_accept_order("baron_wolf", "raise_the_siege")

    def test_can_accept_order_refused_when_hated(self):
        self.baron.opinion_of_liege = -70
        assert not self.h.can_accept_order("baron_wolf", "raise_the_siege")

    def test_absolute_crown_authority_overrides_hate(self):
        self.baron.opinion_of_liege = -50
        self.h.realms[self.baron.realm_id or "kingdom_thorn"].crown_authority = 2
        assert not self.h.can_accept_order("baron_wolf", "raise_the_siege")
        self.h.realms["kingdom_thorn"].crown_authority = 3
        assert self.h.can_accept_order("baron_wolf", "raise_the_siege")

    def test_dead_vassal_accepts_no_orders(self):
        self.baron.alive = False
        assert not self.h.can_accept_order("baron_wolf", "raise_the_siege")

    def test_unknown_vassal_accepts_no_orders(self):
        assert not self.h.can_accept_order("baron_ghost", "raise_the_siege")

    # --- тик вассалов ---

    def test_landless_vassal_loses_opinion_every_turn(self):
        self.h.revoke_fief("baron_wolf")
        self.h.revoke_fief("baron_wolf")
        self.baron.opinion_of_liege = 20
        self.h.tick_vassals()
        assert self.baron.opinion_of_liege == 20 - LANDLESS_OPINION_DECAY
        assert self.baron.landless_turns == 1
        self.h.tick_vassals()
        assert self.baron.opinion_of_liege == 20 - 2 * LANDLESS_OPINION_DECAY
        assert self.baron.landless_turns == 2

    def test_ruling_vassal_keeps_landless_turns_at_zero(self):
        for _ in range(3):
            self.h.tick_vassals()
        assert self.baron.landless_turns == 0
        assert self.baron.opinion_of_liege == 20

    def test_tyranny_of_harsh_contract_bleeds_opinion(self):
        self.h.set_contract("baron_wolf", 4)  # тирания 6 -> -3 за ход
        self.baron.opinion_of_liege = 50
        self.h.tick_vassals()
        assert self.baron.opinion_of_liege == 50 - self.h.contracts["baron_wolf"].tyranny // 2

    def test_kings_are_skipped_by_vassal_tick(self):
        for king in characters_by_rank(self.h, TitleRank.KING):
            assert self.h.liege_of(king.id) is None
        before = {c.id: c.loyalty for c in characters_by_rank(self.h, TitleRank.KING)}
        self.h.tick_vassals()
        for king in characters_by_rank(self.h, TitleRank.KING):
            assert king.loyalty == before[king.id]

    # --- мятежи ---

    def test_rebellions_lists_only_low_loyalty_non_kings(self):
        self.h.characters["baron_wolf"].loyalty = 14
        self.h.characters["baron_gray"].loyalty = 15
        self.h.characters["duke_aldric"].loyalty = 0
        self.h.characters["king_erik"].loyalty = 0
        self.h.characters["baron_gray"].alive = False
        out = self.h.rebellions()
        assert out == sorted(out)
        assert out == ["baron_wolf", "duke_aldric"]
        assert "king_erik" not in out
        assert "baron_gray" not in out

    def test_rebellions_empty_in_healthy_realm(self):
        assert self.h.rebellions() == []

    def test_province_rebellion_threshold_drives_county_events(self):
        # REBELLION_LOYALTY — порог для ПОСЕЛЕНИЙ, мятеж барона живёт
        # на VASSAL_REBELLION_LOYALTY. Без гарнизона поселение само
        # восстанавливается, поэтому давление создаёт налоговая политика —
        # и только на владениях своей нации.
        p = self.h.provinces[26]  # принадлежит blue
        p.garrison = 0
        p.loyalty = REBELLION_LOYALTY + 1
        self.h.realms["kingdom_riven"].tax_policy = 1
        events = []
        for _ in range(5):
            events = self.h.tick_counties()
            if any("#26" in e for e in events):
                break
        assert any("#26" in e for e in events), events
        assert p.loyalty < REBELLION_LOYALTY
        # с гарнизоном лояльность растёт и мятежа не будет
        p.garrison = 200
        p.loyalty = REBELLION_LOYALTY + 10
        assert not any("#26" in e for e in self.h.tick_counties())

    def test_rebellions_agrees_with_vassal_tick(self):
        self.h.characters["baron_wolf"].loyalty = 10
        self.h.characters["baron_gray"].loyalty = 5
        warnings = self.h.tick_vassals()
        expected = {c.id for c in self.h.characters.values()
                    if c.alive and c.rank is not TitleRank.KING and c.loyalty < 15}
        assert set(self.h.rebellions()) == expected
        assert len(warnings) == len(expected)
        assert all("мятеж" in w for w in warnings)

    def assert_landless(self, baron_id: str):
        ch = self.h.characters[baron_id]
        assert ch.province_idx is None
        assert not ch.is_ruler


# --------------------------------------------------------------------------
# Конец хода
# --------------------------------------------------------------------------


class TestEndTurn:
    """Порядок тиков, границы полей и баланс на длинной дистанции."""

    def setup_method(self):
        self.h = make_hierarchy()

    def test_end_turn_increments_turn_by_exactly_one(self):
        for expected in range(2, 12):
            self.h.end_turn()
            assert self.h.turn == expected

    def test_end_turn_returns_and_logs_events(self):
        self.h.provinces[0].loyalty = 0
        self.h.provinces[0].garrison = 0
        events = self.h.end_turn()
        assert isinstance(events, list)
        assert any("Мятеж" in e for e in events)
        assert self.h.log == events
        events2 = self.h.end_turn()
        assert self.h.log == events + events2

    def test_loyalty_falls_without_garrison(self):
        # выше равновесия (55) гарнизон нужен, иначе поселение сползает вниз
        p = self.h.provinces[0]
        p.garrison = 0
        p.loyalty = 60
        self.h.tick_counties()
        assert p.loyalty == 58
        self.h.tick_counties()
        assert p.loyalty == 56

    def test_loyalty_rises_with_garrison(self):
        p = self.h.provinces[0]
        p.garrison = 150
        p.loyalty = 60
        self.h.tick_counties()
        assert p.loyalty == 62
        self.h.tick_counties()
        assert p.loyalty == 64

    def test_county_tick_never_goes_below_zero(self):
        p = self.h.provinces[0]
        p.garrison = 0
        p.loyalty = 1
        for _ in range(20):
            self.h.tick_counties()
            assert p.loyalty >= 0
        # лояльность растёт, а не падает в ноль: поселение восстанавливается
        assert p.loyalty > 1

    def test_county_settles_around_equilibrium_without_garrison(self):
        p = self.h.provinces[0]
        p.garrison = 0
        p.loyalty = 100
        for _ in range(40):
            self.h.tick_counties()
        assert 50 <= p.loyalty <= 60, p.loyalty
        assert self.h.county_income(0) > 0

    def test_prosperity_and_development_stay_inside_bounds(self):
        for _ in range(30):
            self.h.end_turn()
        for p in self.h.provinces:
            assert 0 <= p.prosperity <= 100, p.name
            assert 1 <= p.development <= 10, p.name
            assert 0 <= p.loyalty <= 100, p.name
            assert 0 <= p.security <= 20, p.name

    def test_tax_policy_drains_stability(self):
        realm = self.h.realms["kingdom_riven"]
        realm.stability = 50
        realm.tax_policy = 1
        self.h.tick_realms()
        assert realm.stability == 48
        realm.tax_policy = 0
        self.h.tick_realms()
        assert realm.stability == 49

    def test_tax_policy_also_presses_county_loyalty(self):
        p = self.h.provinces[26]  # принадлежит blue
        p.garrison = 0
        p.loyalty = 60
        self.h.realms["kingdom_riven"].tax_policy = 1
        self.h.tick_counties()
        # -2 за отсутствие гарнизона (свыше равновесия) и -2 за налоги
        assert p.loyalty == 60 - 2 - 2

    def test_tick_realms_keeps_gold_non_negative(self):
        for realm in self.h.realms.values():
            realm.gold = 0
        for _ in range(10):
            self.h.tick_realms()
            for realm in self.h.realms.values():
                assert realm.gold >= 0, realm.id
                assert 0 <= realm.prestige <= 100, realm.id
                assert 0 <= realm.stability <= 100, realm.id

    def test_prestige_grows_for_held_realm(self):
        realm = self.h.realms["kingdom_ember"]
        assert len(self.h.provinces_of_realm(realm.id)) >= 5
        before = realm.prestige
        self.h.tick_realms()
        assert realm.prestige == before + 1

    def test_thirty_turns_economy_survives(self):
        rng = random.Random(12345)
        for _ in range(30):
            # немного асимметрии: гарнизон в случайной деревне
            self.h.provinces[rng.randrange(50)].garrison = 120
            self.h.end_turn()
        assert self.h.turn == 31
        for realm in self.h.realms.values():
            assert realm.gold > 0, realm.id
            assert realm.gold < 10 ** 7, "экономика ушла в инфляцию"
        assert any(self.h.county_income(i) > 0 for i in range(50)), \
            "все поселения разорились"

    def test_thirty_turns_do_not_collapse_realm_treasury(self):
        for _ in range(30):
            self.h.end_turn()
        total_income = sum(self.h.realm_income(r) for r in self.h.realms)
        assert total_income > 0
        assert all(r.gold >= 0 for r in self.h.realms.values())


# --------------------------------------------------------------------------
# Детерминизм (задел под онлайн)
# --------------------------------------------------------------------------


class TestDeterminism:
    """Один и тот же мир, один и тот же хеш — иначе нельзя делать сервер."""

    def test_two_independent_builds_hash_equal(self, twin_hierarchies):
        h1, h2 = twin_hierarchies
        assert state_hash(h1.summary()) == state_hash(h2.summary())

    def test_hash_stable_after_same_end_turns(self, twin_hierarchies):
        h1, h2 = twin_hierarchies
        for _ in range(8):
            h1.end_turn()
            h2.end_turn()
        assert h1.turn == h2.turn == 9
        assert state_hash(h1.summary()) == state_hash(h2.summary())

    def test_hash_stable_after_identical_orders(self, twin_hierarchies):
        h1, h2 = twin_hierarchies
        for h in (h1, h2):
            h.set_contract("baron_volkov", 4)
            h.revoke_fief("baron_wolf")
            h.grant_fief(49, "baron_wolf")
            h.realms["kingdom_ember"].crown_authority = 1
            h.end_turn()
        assert state_hash(h1.summary()) == state_hash(h2.summary())

    def test_hash_ignores_insertion_order_of_dicts(self, twin_hierarchies):
        h1, h2 = twin_hierarchies
        a = h1.summary()
        b = {key: h2.summary()[key] for key in reversed(list(h2.summary()))}
        assert state_hash(a) == state_hash(b)

    def test_summary_is_nested_dict_with_sorted_keys(self, h):
        s = h.summary()
        assert isinstance(s, dict)
        assert set(s) == {"turn", "realms", "duchies", "characters"}
        for section in ("realms", "duchies", "characters"):
            assert isinstance(s[section], dict)
            assert list(s[section]) == sorted(s[section])
        for realm_id, data in s["realms"].items():
            assert realm_id in h.realms
            assert set(data) == {"gold", "prestige", "stability", "held"}
            assert isinstance(data["held"], int)
        for duchy_id, data in s["duchies"].items():
            assert duchy_id in h.duchies
            assert set(data) == {"holder", "income"}
        for ch_id, data in s["characters"].items():
            assert ch_id in h.characters
            assert set(data) == {"rank", "loyalty", "opinion", "gold"}
            assert data["rank"] in {"baron", "duke", "king"}

    def test_summary_matches_realm_values(self, h):
        s = h.summary()
        for realm_id, data in s["realms"].items():
            realm = h.realms[realm_id]
            assert data["gold"] == realm.gold
            assert data["prestige"] == realm.prestige
            assert data["stability"] == realm.stability
            assert data["held"] == len(h.provinces_of_realm(realm_id))

    def test_single_character_change_changes_hash(self, twin_hierarchies):
        h1, h2 = twin_hierarchies
        before = state_hash(h1.summary())
        h1.characters["baron_volkov"].loyalty += 1
        after = state_hash(h1.summary())
        assert after != before
        assert after != state_hash(h2.summary())
        h1.characters["baron_volkov"].loyalty -= 1
        assert state_hash(h1.summary()) == before

    def test_hash_tracks_contract_changes(self, twin_hierarchies):
        h1, h2 = twin_hierarchies
        before = state_hash(h1.summary())
        h1.set_contract("duke_aldric", 4)
        assert state_hash(h1.summary()) != before
        assert state_hash(h1.summary()) != state_hash(h2.summary())

    def test_hash_tracks_turn(self, twin_hierarchies):
        h1, h2 = twin_hierarchies
        before = state_hash(h1.summary())
        h1.end_turn()
        h2.end_turn()
        assert state_hash(h1.summary()) != before
        assert state_hash(h1.summary()) == state_hash(h2.summary())
# --------------------------------------------------------------------------
# Сериализация состояния (этап 0.1-0.2)
# --------------------------------------------------------------------------


def all_keys(obj) -> set:
    """Рекурсивно собрать ВСЕ ключи словарей внутри снапшота."""
    found = set()
    if isinstance(obj, dict):
        for key, value in obj.items():
            found.add(key)
            found |= all_keys(value)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            found |= all_keys(item)
    return found


class TestStateSerialization:
    """``to_state`` -> ``from_state`` обязан сохранять мир побайтно.

    Главный контракт здесь — **одинаковый ``state_fingerprint()`` до и
    после round-trip**. Именно он ловит тихую потерю данных: если забыть
    поле, хеш разъедется и это будет единственный сигнал.
    """

    def setup_method(self):
        self.h = make_hierarchy()

    # --- состав снапшота ---

    def test_state_has_exact_top_level_keys(self):
        assert set(self.h.to_state()) == SNAPSHOT_KEYS

    def test_version_is_one_and_integer(self):
        version = self.h.to_state()["version"]
        assert version == STATE_VERSION == 1
        assert isinstance(version, int) and not isinstance(version, bool)

    def test_no_world_layer_keys_anywhere_in_state(self):
        # рекурсивная проверка: запрещённого ключа не должно быть ни на
        # каком уровне вложенности, а не только в корне снапшота
        found = all_keys(self.h.to_state())
        for banned in FORBIDDEN_STATE_KEYS:
            assert banned not in found, banned

    def test_province_duchy_cache_is_not_serialized(self):
        # производный кэш обязан восстанавливаться, а не храниться
        state = self.h.to_state()
        assert "_province_duchy" not in state
        assert "_province_duchy" not in all_keys(state)
        assert self.h._province_duchy, "кэш у живой иерархии обязан быть непустым"

    def test_counties_cover_every_province_with_nine_fields(self):
        counties = self.h.to_state()["counties"]
        assert set(counties) == set(range(len(self.h.provinces)))
        expected = {"duchy_id", "hearths", "prosperity", "loyalty", "security",
                    "development", "fort_level", "garrison", "villages"}
        assert set(COUNTY_FIELDS) == expected
        assert len(COUNTY_FIELDS) == 9
        for idx, data in counties.items():
            assert set(data) == expected, idx

    def test_counties_keys_are_ints_in_fresh_snapshot(self):
        counties = self.h.to_state()["counties"]
        assert all(isinstance(k, int) for k in counties)

    def test_contract_snapshot_has_exactly_three_fields(self):
        contracts = self.h.to_state()["contracts"]
        assert len(contracts) == EXPECTED_CONTRACT_COUNT
        for vassal_id, data in contracts.items():
            assert set(data) == {"liege_id", "vassal_id", "level"}, vassal_id
            assert data["vassal_id"] == vassal_id
        assert contracts["baron_volkov"]["liege_id"] == "duke_aldric"

    def test_realm_duchy_character_snapshots_are_complete(self):
        state = self.h.to_state()
        for realm_id, realm in self.h.realms.items():
            assert set(state["realms"][realm_id]) == {
                f.name for f in dataclasses.fields(realm)}
        for duchy_id, duchy in self.h.duchies.items():
            assert set(state["duchies"][duchy_id]) == {
                f.name for f in dataclasses.fields(duchy)}
        for ch_id, ch in self.h.characters.items():
            assert set(state["characters"][ch_id]) == {
                f.name for f in dataclasses.fields(ch)}

    def test_log_is_capped_and_flagged_when_truncated(self):
        for _ in range(60):
            for p in self.h.provinces:
                p.loyalty = 0
            self.h.end_turn()
        assert len(self.h.log) == LOG_KEEP
        assert self.h.log_truncated is True
        state = self.h.to_state()
        assert len(state["log"]) == LOG_KEEP
        assert state["log_truncated"] is True

    def test_short_log_is_not_flagged(self):
        self.h.end_turn()
        state = self.h.to_state()
        assert len(state["log"]) <= LOG_KEEP
        assert state["log_truncated"] is False

    # --- round-trip ---

    def test_in_memory_round_trip_preserves_fingerprint(self):
        """ГЛАВНЫЙ ТЕСТ: никакое поле не теряется по дороге."""
        restored = Hierarchy.from_state(self.h.to_state(), copy_provinces())
        assert restored.state_fingerprint() == self.h.state_fingerprint()

    def test_json_round_trip_preserves_fingerprint(self):
        """То же, но через настоящий JSON — со строковыми ключами county."""
        state = loads(dumps(self.h.to_state()))
        restored = Hierarchy.from_state(state, copy_provinces())
        assert restored.state_fingerprint() == self.h.state_fingerprint()

    def test_round_trip_preserves_fingerprint_after_several_turns(self):
        for _ in range(9):
            self.h.end_turn()
        restored = Hierarchy.from_state(self.h.to_state(), copy_provinces())
        assert restored.state_fingerprint() == self.h.state_fingerprint()
        assert restored.turn == self.h.turn

    def test_round_trip_preserves_fingerprint_with_truncated_log(self):
        for _ in range(60):
            for p in self.h.provinces:
                p.loyalty = 0
            self.h.end_turn()
        restored = Hierarchy.from_state(self.h.to_state(), copy_provinces())
        assert restored.state_fingerprint() == self.h.state_fingerprint()
        assert restored.log_truncated is True
        assert len(restored.log) == LOG_KEEP
        # и повторный round-trip тоже стабилен (идемпотентность)
        again = Hierarchy.from_state(restored.to_state(), copy_provinces())
        assert again.state_fingerprint() == self.h.state_fingerprint()

    def test_round_trip_restores_income_and_upkeep(self):
        restored = Hierarchy.from_state(self.h.to_state(), copy_provinces())
        for realm_id in self.h.realms:
            assert restored.realm_income(realm_id) == self.h.realm_income(realm_id)
            assert restored.realm_upkeep(realm_id) == self.h.realm_upkeep(realm_id)
        for idx in range(len(self.h.provinces)):
            assert restored.county_income(idx) == self.h.county_income(idx)

    def test_round_trip_restores_dictionaries_by_id(self):
        restored = Hierarchy.from_state(self.h.to_state(), copy_provinces())
        assert set(restored.realms) == set(self.h.realms)
        assert set(restored.duchies) == set(self.h.duchies)
        assert set(restored.characters) == set(self.h.characters)
        assert set(restored.contracts) == set(self.h.contracts)
        assert len(restored.characters) == EXPECTED_CHARACTER_COUNT

    # --- восстановление типов ---

    def test_from_state_restores_de_jure_provinces_as_tuple(self):
        restored = Hierarchy.from_state(self.h.to_state(), copy_provinces())
        for duchy in restored.duchies.values():
            assert isinstance(duchy.de_jure_provinces, tuple), duchy.id
        assert restored.duchies["ravenhold"].de_jure_provinces == (10, 11, 12, 13, 14)

    def test_from_state_restores_traits_as_tuple(self):
        restored = Hierarchy.from_state(self.h.to_state(), copy_provinces())
        for ch in restored.characters.values():
            assert isinstance(ch.traits, tuple), ch.id
        self.h.characters["king_erik"].traits = ("crave", "brave")
        restored = Hierarchy.from_state(self.h.to_state(), copy_provinces())
        assert restored.characters["king_erik"].traits == ("crave", "brave")

    def test_from_state_restores_county_keys_as_int_after_json(self):
        state = loads(dumps(self.h.to_state()))
        assert all(isinstance(k, str) for k in state["counties"]), "JSON обязан дать строки"
        restored = Hierarchy.from_state(state, copy_provinces())
        assert set(restored.to_state()["counties"]) == set(range(50))
        assert all(isinstance(k, int) for k in restored.to_state()["counties"])

    def test_from_state_restores_enums_explicitly(self):
        state = loads(dumps(self.h.to_state()))
        restored = Hierarchy.from_state(state, copy_provinces())
        for ch_id, ch in self.h.characters.items():
            got = restored.characters[ch_id].rank
            assert got is ch.rank, ch_id
            assert isinstance(got, TitleRank)
        assert restored.characters["king_erik"].tier is Tier.REALM
        assert restored.characters["duke_aldric"].tier is Tier.DUCHY

    def test_from_state_rebuilds_province_duchy_index(self):
        state = self.h.to_state()
        index = dict(self.h._province_duchy)
        index.clear()
        self.h._province_duchy = index
        restored = Hierarchy.from_state(state, copy_provinces())
        # индекс восстановлен конструктором из de jure герцогств
        assert restored.duchy_of(0) == "northmark"
        assert restored.duchy_of(13) == "ravenhold"
        assert restored.duchy_of(49) == "goldfield"

    def test_from_state_accepts_both_enum_spellings(self):
        state = self.h.to_state()
        by_name = loads(dumps(state))
        by_value = {k: dict(v) for k, v in state["characters"].items()}
        for data in by_value.values():
            data["rank"] = TitleRank[data["rank"]].value  # "king" вместо "KING"
        state["characters"] = by_value
        restored_name = Hierarchy.from_state(by_name, copy_provinces())
        restored_value = Hierarchy.from_state(state, copy_provinces())
        assert restored_name.characters["king_erik"].rank is TitleRank.KING
        assert restored_value.characters["king_erik"].rank is TitleRank.KING

    def test_from_state_falls_back_on_broken_rank(self):
        state = {**self.h.to_state()}
        state["characters"] = {k: dict(v) for k, v in state["characters"].items()}
        state["characters"]["king_erik"]["rank"] = "НЕВАЛИДНЫЙ_РАНГ"
        restored = Hierarchy.from_state(state, copy_provinces())
        assert restored.characters["king_erik"].rank is TitleRank.BARON

    # --- терпимость к неполным снапшотам ---

    def test_from_state_tolerates_partial_snapshot(self):
        partial = {
            "version": 1,
            "realms": {"kingdom_ember": {"nation": "red", "gold": 7}},
            "characters": {"king_erik": {"name": "Erik", "nation": "red"}},
            "duchies": {"ravenhold": {"name": "Ravenhold"}},
            "contracts": {"king_erik": {}},
            "counties": {"3": {"hearths": 500, "loyalty": 80}},
        }
        provinces = copy_provinces()
        h = Hierarchy.from_state(partial, provinces)
        realm = h.realms["kingdom_ember"]
        assert realm.gold == 7
        assert realm.ruler_id is None and realm.capital_idx is None
        assert realm.crown_authority == 2 and realm.stability == 100
        assert h.characters["king_erik"].rank is TitleRank.BARON
        assert h.characters["king_erik"].loyalty == 70
        assert h.duchies["ravenhold"].de_jure_provinces == ()
        assert h.contracts["king_erik"].level == 2
        assert h.turn == 1 and h.log == []
        assert provinces[3].hearths == 500
        assert provinces[3].loyalty == 80
        # остальные восьминараторные поля взяты из дефолтов
        assert provinces[3].development == 1 and provinces[3].fort_level == 0

    def test_from_state_survives_completely_empty_snapshot(self):
        h = Hierarchy.from_state({}, copy_provinces())
        assert h.turn == 1 and h.log == []
        assert h.realms == {} and h.duchies == {}
        assert h.characters == {} and h.contracts == {}
        assert h.state_fingerprint() == Hierarchy.from_state({}, copy_provinces()).state_fingerprint()

    def test_from_state_ignores_out_of_range_and_bad_county_keys(self):
        state = self.h.to_state()
        state["counties"]["9999"] = dict(state["counties"][0])
        state["counties"]["не число"] = dict(state["counties"][0])
        restored = Hierarchy.from_state(state, copy_provinces())
        assert set(restored.to_state()["counties"]) == set(range(50))

    def test_from_state_cannot_inject_arbitrary_attributes(self):
        # битый снапшот не должен уметь дописать в провинцию что попало
        state = {"counties": {"0": {"hearths": 10, "зловред": "boom"}}}
        provinces = copy_provinces()
        Hierarchy.from_state(state, provinces)
        assert provinces[0].hearths == 10
        assert not hasattr(provinces[0], "зловред")

    # --- честный хеш ---

    def test_fingerprint_equal_for_two_independent_builds(self):
        a, b = make_hierarchy(), make_hierarchy()
        assert a.state_fingerprint() == b.state_fingerprint()
        for _ in range(8):
            a.end_turn()
            b.end_turn()
        assert a.state_fingerprint() == b.state_fingerprint()

    def test_fingerprint_differs_when_gold_differs(self):
        a, b = make_hierarchy(), make_hierarchy()
        before = a.state_fingerprint()
        b.realms["kingdom_ember"].gold += 1
        assert b.state_fingerprint() != before
        b.realms["kingdom_ember"].gold -= 1
        assert b.state_fingerprint() == before

    def test_fingerprint_tracks_county_and_character_changes(self):
        a, b = make_hierarchy(), make_hierarchy()
        before = a.state_fingerprint()
        a.provinces[3].garrison += 40
        assert a.state_fingerprint() != before
        b.characters["baron_volkov"].loyalty += 1
        assert b.state_fingerprint() != before

    def test_fingerprint_is_sha1_hex(self):
        fp = self.h.state_fingerprint()
        assert isinstance(fp, str) and len(fp) == 40
        assert all(ch in "0123456789abcdef" for ch in fp)

    def test_fingerprint_equals_state_hash_of_to_state(self):
        state = self.h.to_state()
        assert self.h.state_fingerprint() == state_hash(state)

    def test_hashing_the_object_directly_is_the_old_bug(self):
        """Зафиксированный баг: repr(Hierarchy) содержит адрес памяти.

        ``canonical`` не умеет dataclass'ы и ``Hierarchy`` не dataclass,
        поэтому ``state_hash(иерархия)`` уходит в ``repr`` и «залипает» на
        ``0x...``. Тест существует, чтобы никто не вернул этот путь.
        """
        a, b = make_hierarchy(), make_hierarchy()
        assert state_hash(a.summary()) == state_hash(b.summary())
        assert state_hash(a) != state_hash(b), "repr() содержит адрес — это ожидаемо"
        assert a.state_fingerprint() == b.state_fingerprint(), \
            "правильный путь — хешировать to_state()"

    def test_to_jsonable_no_longer_collapses_hierarchy(self):
        # раньше: '<states.Hierarchy object at 0x...>' — потеря всего мира
        payload = to_jsonable(self.h.to_state())
        assert isinstance(payload, dict)
        assert payload["version"] == 1
        assert len(payload["characters"]) == EXPECTED_CHARACTER_COUNT
        assert json_dumps_round_trips(payload)

    # --- регистрация enum ---

    def test_register_enum_title_rank_round_trip(self):
        rank = TitleRank.KING
        assert from_jsonable(to_jsonable(rank)) is TitleRank.KING
        assert from_jsonable(to_jsonable(TitleRank.DUKE)) is TitleRank.DUKE
        assert from_jsonable(to_jsonable(TitleRank.BARON)) is TitleRank.BARON

    def test_register_enum_tier_round_trip(self):
        assert from_jsonable(to_jsonable(Tier.REALM)) is Tier.REALM
        assert from_jsonable(to_jsonable(Tier.COUNTY)) is Tier.COUNTY

    def test_register_enum_is_idempotent(self):
        for _ in range(3):
            register_enum(TitleRank)
            register_enum(Tier)
        assert from_jsonable(to_jsonable(TitleRank.KING)) is TitleRank.KING

    def test_enum_registry_contains_states_enums(self):
        register_enum(TitleRank)
        register_enum(Tier)
        from sim import registered_enums
        assert {"TitleRank", "Tier"} <= registered_enums()

    def test_registered_enums_survive_a_json_hierarchy_snapshot(self):
        restored = Hierarchy.from_state(loads(dumps(self.h.to_state())), copy_provinces())
        ranks = {ch.rank for ch in restored.characters.values()}
        assert ranks == {TitleRank.KING, TitleRank.DUKE, TitleRank.BARON}


def json_dumps_round_trips(payload) -> bool:
    """Признак «это честный dict, а не строка от repr»."""
    return loads(dumps(payload)) == payload


# --------------------------------------------------------------------------
# Содержание гарнизонов и баланс (этап 0.3-0.5)
# --------------------------------------------------------------------------


class TestGarrisonUpkeep:
    """Гарнизон стоит денег, потолок задаётся стенами, престиж — сток.

    Контекст правки: до неё гарнизон не списывался НИГДЕ, при этом давал
    +2 лояльности и +1 безопасности за ход, то есть поднимал доход
    поселения примерно с 7 до 48. «Трата на гарнизон» была фиктивной
    кнопкой, а ``fort_level`` не читался нигде.
    """

    def setup_method(self):
        self.h = make_hierarchy()

    # --- потолок по стенам ---

    def test_garrison_cap_scales_with_fort_level(self):
        for idx, p in enumerate(self.h.provinces):
            expected = (p.fort_level + 1) * GARRISON_CAP_PER_FORT
            assert self.h.garrison_cap(idx) == expected, idx
        self.h.provinces[0].fort_level = 3
        assert self.h.garrison_cap(0) == 4 * GARRISON_CAP_PER_FORT
        self.h.provinces[0].fort_level = 0
        assert self.h.garrison_cap(0) == GARRISON_CAP_PER_FORT

    def test_start_garrisons_respect_the_cap(self):
        for idx, p in enumerate(self.h.provinces):
            assert 0 <= p.garrison <= self.h.garrison_cap(idx), (idx, p.garrison)

    def test_cap_scales_village_city_capital(self):
        capitals = [i for i in CAPITAL_INDICES]
        cities = [i for i, p in enumerate(self.h.provinces)
                  if p.region_type is RegionType.CITY]
        villages = [i for i, p in enumerate(self.h.provinces)
                    if p.region_type is RegionType.VILLAGE]
        # деревня держит сотню, город — две, крепость — три
        assert self.h.garrison_cap(capitals[0]) == 3 * GARRISON_CAP_PER_FORT
        assert self.h.garrison_cap(cities[0]) == 2 * GARRISON_CAP_PER_FORT
        assert self.h.garrison_cap(villages[0]) == 1 * GARRISON_CAP_PER_FORT

    # --- содержание ---

    def test_garrison_upkeep_is_zero_without_garrisons(self):
        for p in self.h.provinces:
            p.garrison = 0
        for realm in self.h.realms.values():
            assert self.h.garrison_upkeep(realm.id) == 0

    def test_garrison_upkeep_grows_with_number_of_garrisons(self):
        h = make_hierarchy()
        for p in h.provinces:
            p.garrison = 0
        owned = h.provinces_of_realm("kingdom_ember")
        bills = []
        for soldiers in (0, 100, 200, 300):
            for idx in owned:
                h.provinces[idx].garrison = soldiers
            bills.append(h.garrison_upkeep("kingdom_ember"))
        assert bills[0] == 0
        assert all(b > a for a, b in zip(bills, bills[1:])), bills
        assert bills[1] == len(owned) * GARRISON_UPKEEP_PER_100

    def test_garrison_upkeep_counts_only_own_provinces(self):
        h = make_hierarchy()
        h.realms["kingdom_ember"].gold = 99999
        for p in h.provinces:
            p.garrison = 0
        owned = h.provinces_of_realm("kingdom_ember")
        h.provinces[owned[0]].garrison = 100
        foreign = [i for i in range(50) if i not in owned][0]
        h.provinces[foreign].garrison = 100
        assert h.garrison_upkeep("kingdom_ember") == GARRISON_UPKEEP_PER_100

    def test_realm_upkeep_grows_with_garrison_count(self):
        h = make_hierarchy()
        for p in h.provinces:
            p.garrison = 0
        owned = h.provinces_of_realm("kingdom_riven")
        before = h.realm_upkeep("kingdom_riven")
        for idx in owned:
            h.provinces[idx].garrison = 200
        after = h.realm_upkeep("kingdom_riven")
        assert after > before
        assert after - before == len(owned) * 2 * GARRISON_UPKEEP_PER_100

    def test_garrison_is_paid_from_first_soldier(self):
        # GARRISON_IS_FREE_THRESHOLD == 0: стартовые гарнизоны платные сразу
        assert GARRISON_IS_FREE_THRESHOLD == 0
        h = make_hierarchy()
        for p in h.provinces:
            p.garrison = 0
        owned = h.provinces_of_realm("kingdom_thorn")
        h.provinces[owned[0]].garrison = 100
        assert h.garrison_upkeep("kingdom_thorn") == GARRISON_UPKEEP_PER_100

    def test_start_upkeep_includes_garrison_bill(self):
        for realm in self.h.realms.values():
            assert self.h.garrison_upkeep(realm.id) > 0, realm.id
        assert self.h.realm_upkeep("kingdom_riven") > 0

    # --- атриция ---

    def test_attrition_applies_when_treasury_is_empty(self):
        self.h.realms["kingdom_riven"].gold = 0
        city, capital = 28, 32
        before = (self.h.provinces[city].garrison, self.h.provinces[capital].garrison)
        assert min(before) > GARRISON_ATTRITION
        self.h.tick_counties()
        after = (self.h.provinces[city].garrison, self.h.provinces[capital].garrison)
        assert after == (before[0] - GARRISON_ATTRITION,
                         before[1] - GARRISON_ATTRITION)

    def test_attrition_never_goes_below_zero(self):
        """Гарнизон не уходит в минус, даже когда казна давно пуста.

        И не останавливается на «бесплатном остатке»: счёт пропорциональный,
        поэтому сто солдат глохнут до нуля, а не замирают на 60.
        """
        h = make_hierarchy()
        for realm in h.realms.values():
            realm.gold = 0
        owned = sorted({i for realm_id in h.realms
                        for i in h.provinces_of_realm(realm_id)})
        untouched = {i: h.provinces[i].garrison for i in range(50) if i not in owned}
        for i in owned:
            h.provinces[i].garrison = 100
        for _ in range(10):
            h.tick_counties()
            assert all(p.garrison >= 0 for p in h.provinces)
        assert all(h.provinces[i].garrison == 0 for i in owned)
        # нейтральные земли не платят ни одному королевству и не тронуты
        assert all(h.provinces[i].garrison == g for i, g in untouched.items())

    def test_broke_realm_is_drained_to_zero(self):
        """Разорённое королевство гарнизон НЕ сохраняет.

        Счёт пропорциональный (``billable * 10 // 100``), поэтому нет
        «безплатного остатка» меньше сотни, в котором атриция
        останавливается. Раньше округление вниз позволяло королевству
        дойти до нуля содержания, оставив себе войска.
        """
        h = make_hierarchy()
        for realm in h.realms.values():
            realm.gold = 0
        owned = sorted(h.provinces_of_realm("kingdom_riven"))
        for i in owned:
            h.provinces[i].garrison = 400
        history = []
        for _ in range(30):
            h.tick_counties()
            history.append(sum(h.provinces[i].garrison for i in owned))
        assert history[0] < 400 * len(owned), "хоть что-то должно было сгореть"
        assert all(b <= a for a, b in zip(history, history[1:])), "убывание обязано быть монотонным"
        assert history[-1] == 0, f"гарнизон должен сгореть полностью, осталось {history[-1]}"
        assert h.garrison_upkeep("kingdom_riven") == 0, "счёт схлопнулся в ноль"

    def test_small_garrison_is_paid_for_and_decays(self):
        """Гарнизон меньше сотни тоже стоит денег и тоже гниёт.

        Формула ``(garrison // 100) * 10`` делала 99 солдат бесплатными и
        бессмертными: при любой казне атриции не было, и разорённое
        королевство замирало на остатке. Счёт пропорциональный.
        """
        h = make_hierarchy()
        for realm in h.realms.values():
            realm.gold = 0
        owned = sorted({i for realm_id in h.realms
                        for i in h.provinces_of_realm(realm_id)})
        for i in owned:
            h.provinces[i].garrison = 99
        # 99 * 10 // 100 = 9 золота за провинцию, а не ноль
        bill = h.garrison_upkeep("kingdom_riven")
        riven_owned = sorted(h.provinces_of_realm("kingdom_riven"))
        assert bill == len(riven_owned) * 9, bill
        for _ in range(5):
            h.tick_counties()
        assert all(h.provinces[i].garrison <= 99 for i in owned), "малый гарнизон обязан гнить"
        assert any(h.provinces[i].garrison < 99 for i in riven_owned)

    def test_garrison_upkeep_is_proportional_not_per_hundred(self):
        h = make_hierarchy()
        realm = h.realms["kingdom_riven"]
        owned = sorted(h.provinces_of_realm(realm.id))
        for i in owned:
            h.provinces[i].garrison = 0
        h.provinces[owned[0]].garrison = 50
        half = h.garrison_upkeep(realm.id)
        h.provinces[owned[0]].garrison = 100
        full = h.garrison_upkeep(realm.id)
        assert full == 2 * half, (half, full)

    def test_no_attrition_when_treasury_covers_the_bill(self):
        realm = self.h.realms["kingdom_riven"]
        bill = self.h.garrison_upkeep(realm.id)
        before = [self.h.provinces[i].garrison for i in (28, 32)]
        realm.gold = bill
        self.h.tick_counties()
        assert [self.h.provinces[i].garrison for i in (28, 32)] == before
        realm.gold = bill - 1
        self.h.tick_counties()
        assert [self.h.provinces[i].garrison for i in (28, 32)] == [
            g - GARRISON_ATTRITION for g in before]

    def test_attrition_touches_only_the_broke_realm(self):
        broke = self.h.realms["kingdom_riven"]
        broke.gold = 0
        solvent_idx = self.h.provinces_of_realm("kingdom_ember")[0]
        before_solvent = self.h.provinces[solvent_idx].garrison
        before_broke = [self.h.provinces[i].garrison for i in (28, 32)]
        self.h.tick_counties()
        assert self.h.provinces[solvent_idx].garrison == before_solvent
        assert [self.h.provinces[i].garrison for i in (28, 32)] == [
            g - GARRISON_ATTRITION for g in before_broke]

    def test_attrition_skips_neutral_provinces(self):
        # у нейтральных земель нет королевства — платить некому
        neutral = [i for i, p in enumerate(self.h.provinces) if p.owner == "neutral"]
        before = [self.h.provinces[i].garrison for i in neutral]
        for realm in self.h.realms.values():
            realm.gold = 0
        self.h.tick_counties()
        assert [self.h.provinces[i].garrison for i in neutral] == before

    def test_ticks_never_roll_the_dice(self):
        """КРИТИЧНОЕ ПРАВИЛО этапа 0.3: ни один тик не трогает ГПСЧ."""
        h = make_hierarchy()
        assert len(h.streams) == 0
        for _ in range(12):
            h.end_turn()
        assert len(h.streams) == 0, "фаза хода создала именованный поток"
        assert h.streams.consumed("anything") == 0

    # --- престиж как сток ---

    def test_royal_court_cost_grows_with_prestige(self):
        realm = self.h.realms["kingdom_ember"]
        realm.prestige = 0
        baseline = self.h.realm_upkeep(realm.id)
        costs = []
        for prestige in (0, 10, 30, 60, 100):
            realm.prestige = prestige
            costs.append(self.h.realm_upkeep(realm.id))
        assert all(b > a for a, b in zip(costs, costs[1:])), costs
        assert costs[0] == baseline
        assert costs[-1] == baseline + 100 // ROYAL_COURT_PRESTIGE_DIVISOR
        assert ROYAL_COURT_BASE_COST == 30

    def test_prestige_divisor_scales_the_increment(self):
        realm = self.h.realms["kingdom_ember"]
        realm.prestige = 0
        base = self.h.realm_upkeep(realm.id)
        realm.prestige = 50
        assert self.h.realm_upkeep(realm.id) == base + \
            50 // ROYAL_COURT_PRESTIGE_DIVISOR

    def test_prestige_is_capped_so_court_cost_is_bounded(self):
        # потолок ставит tick_realms, поэтому «накручиваем» престиж только
        # честным путём — через него самого
        h = make_hierarchy()
        realm = h.realms["kingdom_ember"]
        for _ in range(200):
            h.tick_realms()
        assert realm.prestige == 100
        max_cost = h.realm_upkeep(realm.id)
        assert max_cost - 100 // ROYAL_COURT_PRESTIGE_DIVISOR > 0
        realm.prestige = 0
        min_cost = h.realm_upkeep(realm.id)
        assert max_cost > min_cost

    # --- баланс на длинной дистанции ---

    def balance_scenario(self, turns: int, seed: int, rnd_garrison: bool):
        h = make_hierarchy()
        rng = random.Random(seed)
        for _ in range(turns):
            if rnd_garrison:
                h.provinces[rng.randrange(50)].garrison = 120
            h.end_turn()
        return h

    def assert_healthy(self, h: Hierarchy, turns: int):
        assert h.turn == turns + 1
        for realm in h.realms.values():
            assert realm.gold > 0, realm.id
            assert realm.gold < 10 ** 7, f"{realm.id}: инфляция"
            assert 0 <= realm.prestige <= 100, realm.id
            assert 0 <= realm.stability <= 100, realm.id
            assert h.realm_income(realm.id) > 0, realm.id
        positive = sum(1 for idx in range(50) if h.county_income(idx) > 0)
        assert positive >= 40, f"разорилось слишком много поселений: {positive}/50"
        for p in h.provinces:
            assert 0 <= p.loyalty <= 100, p.name
            assert p.garrison >= 0, p.name

    def test_thirty_turns_balance(self):
        h = self.balance_scenario(30, seed=12345, rnd_garrison=False)
        self.assert_healthy(h, 30)
        assert h.realms["kingdom_riven"].gold < 10 ** 4

    def test_hundred_turns_balance(self):
        h = self.balance_scenario(100, seed=12345, rnd_garrison=False)
        self.assert_healthy(h, 100)

    def test_thirty_turns_balance_with_random_garrisons(self):
        h = self.balance_scenario(30, seed=12345, rnd_garrison=True)
        self.assert_healthy(h, 30)

    def test_hundred_turns_balance_with_random_garrisons(self):
        h = self.balance_scenario(100, seed=12345, rnd_garrison=True)
        self.assert_healthy(h, 100)

    def test_balance_is_reproducible_with_a_fixed_seed(self):
        a = self.balance_scenario(30, seed=999, rnd_garrison=True)
        b = self.balance_scenario(30, seed=999, rnd_garrison=True)
        assert a.state_fingerprint() == b.state_fingerprint()

    def test_garrison_upkeep_actually_presses_the_treasury(self):
        """Контрольный эксперимент: счёт за гарнизоны уменьшает казну.

        Один и тот же ход на двух копиях мира, отличающихся только
        гарнизонами: разница в золоте обязана равняться сумме счетов.
        """
        with_pay = make_hierarchy()
        without_pay = make_hierarchy()
        bill = {r.id: without_pay.garrison_upkeep(r.id) for r in without_pay.realms.values()}
        assert all(v > 0 for v in bill.values()), bill
        for p in without_pay.provinces:
            p.garrison = 0
        for h in (with_pay, without_pay):
            h.tick_realms()
        for realm_id in bill:
            # платящий за гарнизоны король обязан быть беднее ровно на счёт
            assert without_pay.realms[realm_id].gold - \
                with_pay.realms[realm_id].gold == bill[realm_id], realm_id

    def test_streams_do_not_affect_the_fingerprint(self):
        a = build_default_hierarchy(copy_provinces())
        b = build_default_hierarchy(copy_provinces(), streams=new_streams(424242))
        assert a.streams.seed == HIERARCHY_DEFAULT_SEED
        assert b.streams.seed == 424242
        assert a.state_fingerprint() == b.state_fingerprint()
        for _ in range(10):
            a.end_turn()
            b.end_turn()
        assert a.state_fingerprint() == b.state_fingerprint()
        assert len(b.streams) == 0, "ход не должен был потратить ни одного броска"

    def test_two_builds_with_the_same_explicit_seed_hash_equal(self):
        a = build_default_hierarchy(copy_provinces(), streams=new_streams(7))
        b = build_default_hierarchy(copy_provinces(), streams=new_streams(7))
        assert a.state_fingerprint() == b.state_fingerprint()
        for _ in range(5):
            a.end_turn()
            b.end_turn()
        assert a.state_fingerprint() == b.state_fingerprint()

    def test_default_streams_are_created_when_omitted(self):
        a = Hierarchy(copy_provinces())
        b = Hierarchy(copy_provinces())
        assert a.streams.seed == HIERARCHY_DEFAULT_SEED
        assert b.streams.seed == HIERARCHY_DEFAULT_SEED
        assert a.state_fingerprint() == b.state_fingerprint()
        # потоки — внешний источник энтропии, в снапшот они не попадают
        assert "streams" not in a.to_state()

# --------------------------------------------------------------------------
# Траты золота (этап 3)
# --------------------------------------------------------------------------


class TestExpenditures:
    """Шесть способов потратить золото — и общий контракт команд.

    Контекст этапа: до него золото было только входящим (net +22 золота за ход
    на старте, +169 в насыщении, к 100 ходу 16 тысяч в казне), то есть ресурс
    не стоил ничего. Здесь проверяется, что каждая из шести трат:

    * списывает ровно свою цену и даёт ровно свой эффект;
    * упирается в осмысленный потолок, а не в «бесконечность»;
    * требует права (вассал либо тот королевство, которому земля реально
      принадлежит);
    * отказывает без золота и НЕ меняет состояние при отказе;
    * не падает на мусоре во входных данных;
    * ограничена «не чаще N раз за ход на актёра» журналом ``action_ledger``.

    Отдельно — детерминизм найма наёмников (единственного потребителя ГПСЧ)
    и регрессия детерминизма после трат.
    """

    REALM = "kingdom_riven"
    RULER = "king_rurik"

    def setup_method(self):
        self.h = make_hierarchy()

    # ---------------- хелперы ----------------

    @property
    def realm(self):
        return self.h.realms[self.REALM]

    def fund(self, gold: int = 10000, realm_id: Optional[str] = None):
        """Положить в казну королевства ровно ``gold``."""
        realm = self.h.realms[realm_id or self.REALM]
        realm.gold = gold
        return realm

    def owned(self, realm_id: Optional[str] = None) -> List[int]:
        return sorted(self.h.provinces_of_realm(realm_id or self.REALM))

    def neutral_index(self) -> int:
        for idx, province in enumerate(self.h.provinces):
            if province.owner == "neutral":
                return idx
        raise AssertionError("на карте не осталось нейтральных земель")

    def capital(self) -> int:
        return self.realm.capital_idx

    def assert_refused(self, events) -> None:
        """Отказ — это ОДНО событие с причиной, а не пустой список.

        Пустой список означает «некому/нечего»: неизвестная цель. Отказ по
        существу (нет права, не хватает золота, исчерпан лимит) обязан
        объясняться — иначе UI нечего показать игроку.
        """
        assert isinstance(events, list), events
        assert len(events) == 1, events
        assert isinstance(events[0], str) and events[0], events

    # ==================================================================
    # T1. Подъём левейса
    # ==================================================================

    def test_levy_constants_are_the_documented_ones(self):
        assert LEVY_BLOCK_TROOPS == 100
        assert LEVY_COST_PER_BLOCK == 100
        assert RAISED_LEVY_UPKEEP_DIVISOR == 12
        # 8 золота за сотню за ход — заявленная цена содержания
        assert LEVY_BLOCK_TROOPS // RAISED_LEVY_UPKEEP_DIVISOR == 8

    def test_raise_levy_adds_soldiers_and_charges_gold(self):
        self.fund(1000)
        events = self.h.raise_levy(self.REALM, 2)
        assert events, "успешная трата обязана попасть в журнал"
        assert self.realm.raised_levy == 2 * LEVY_BLOCK_TROOPS
        assert self.realm.gold == 1000 - 2 * LEVY_COST_PER_BLOCK

    def test_raise_levy_starts_at_zero_and_lives_in_the_snapshot(self):
        assert self.realm.raised_levy == 0
        assert "raised_levy" in self.h.to_state()["realms"][self.REALM]

    def test_raise_levy_is_capped_by_realm_levy(self):
        cap = self.h.realm_levy(self.REALM)
        self.fund(100000)
        self.h.raise_levy(self.REALM, cap // LEVY_BLOCK_TROOPS)
        filled = cap // LEVY_BLOCK_TROOPS * LEVY_BLOCK_TROOPS
        assert self.realm.raised_levy == filled
        before = (self.realm.gold, self.realm.raised_levy)
        # остаток в два десятка солдат добрать нельзя: блок — это сотня,
        # поэтому «подобрать левейс до конца» невозможно by design
        events = self.h.raise_levy(self.REALM, 1)
        assert events, "левейс сверх наличного обязан быть отказом"
        assert (self.realm.gold, self.realm.raised_levy) == before
        assert filled <= cap

    def test_raise_levy_refused_without_gold_and_changes_nothing(self):
        self.fund(LEVY_COST_PER_BLOCK - 1)
        before_gold, before_levy = self.realm.gold, self.realm.raised_levy
        events = self.h.raise_levy(self.REALM, 1)
        assert events
        assert self.realm.gold == before_gold
        assert self.realm.raised_levy == before_levy

    def test_raise_levy_rejects_zero_and_negative_blocks(self):
        self.fund(1000)
        for blocks in (0, -1, -100):
            events = self.h.raise_levy(self.REALM, blocks)
            assert events, blocks
            assert self.realm.raised_levy == 0, blocks
            assert self.realm.gold == 1000, blocks

    def test_raise_levy_survives_junk_blocks(self):
        self.fund(1000)
        for junk in (None, "abc", True, [1], object()):
            events = self.h.raise_levy(self.REALM, junk)
            assert isinstance(events, list), junk
            assert events, junk
            assert self.realm.raised_levy == 0, junk
        assert self.realm.gold == 1000

    def test_raise_levy_truncates_float_blocks(self):
        self.fund(1000)
        assert self.h.raise_levy(self.REALM, 2.9)
        assert self.realm.raised_levy == 2 * LEVY_BLOCK_TROOPS

    def test_raise_levy_on_unknown_realm_is_noop(self):
        assert self.h.raise_levy("kingdom_of_narnia", 1) == []

    def test_raised_levy_grows_realm_upkeep(self):
        self.fund(100000)
        base = self.h.realm_upkeep(self.REALM)
        self.h.raise_levy(self.REALM, 3)
        after = self.h.realm_upkeep(self.REALM)
        assert after - base == 3 * LEVY_BLOCK_TROOPS // RAISED_LEVY_UPKEEP_DIVISOR
        assert after > base

    def test_realm_upkeep_of_empty_levy_is_unchanged(self):
        # содержание без поднятого левейса складывается ровно как до этапа 3
        h = make_hierarchy()
        realm = h.realms[self.REALM]
        ruler = realm.ruler_id
        assert h.realm_upkeep(self.REALM) == \
            h.realm_levy(self.REALM) // LEVY_UPKEEP_DIVISOR + \
            realm.raised_levy // RAISED_LEVY_UPKEEP_DIVISOR + \
            COURT_COST_PER_VASSAL * len(h.vassals_of(ruler)) + \
            h.garrison_upkeep(self.REALM) + ROYAL_COURT_BASE_COST + \
            realm.prestige // ROYAL_COURT_PRESTIGE_DIVISOR

    def test_raise_levy_refused_when_ruler_is_dead(self):
        self.fund(1000)
        self.h.characters[self.RULER].alive = False
        assert self.h.raise_levy(self.REALM, 1)
        assert self.realm.raised_levy == 0
        assert self.realm.gold == 1000

    def test_raised_levy_never_exceeds_the_cap_over_many_turns(self):
        self.fund(1000000)
        for _ in range(30):
            self.h.raise_levy(self.REALM, 1)
            self.h.end_turn()
        assert self.realm.raised_levy <= self.h.realm_levy(self.REALM)

    # ==================================================================
    # T2. Застройка графа
    # ==================================================================

    def test_development_cost_is_linear_and_bounded(self):
        assert DEV_COST_BASE == 40
        assert DEV_COST_STEP == 10
        assert DEVELOPMENT_MAX == 10
        costs = [development_upgrade_cost(dev) for dev in range(1, DEVELOPMENT_MAX)]
        assert costs == [50, 60, 70, 80, 90, 100, 110, 120, 130]
        assert all(b > a for a, b in zip(costs, costs[1:]))
        # полная застройка 1..10 стоит 810 золота на графство (9 ступеней)
        assert sum(costs) == 810

    def test_develop_county_raises_development_and_charges_gold(self):
        idx = self.capital()
        self.fund(1000)
        before = self.h.county_income(idx)
        events = self.h.develop_county(idx)
        assert events
        assert self.h.provinces[idx].development == 2
        assert self.realm.gold == 1000 - development_upgrade_cost(1)
        assert self.h.county_income(idx) > before, "застройка обязана повышать доход"

    def test_develop_county_price_follows_current_development(self):
        idx = self.capital()
        self.fund(100000)
        self.h.provinces[idx].development = 7
        gold = self.realm.gold
        assert self.h.develop_county(idx)
        assert self.realm.gold == gold - development_upgrade_cost(7)
        assert self.h.provinces[idx].development == 8

    def test_develop_county_refused_at_max(self):
        idx = self.capital()
        self.fund(10000)
        self.h.provinces[idx].development = DEVELOPMENT_MAX
        events = self.h.develop_county(idx)
        assert events
        assert self.h.provinces[idx].development == DEVELOPMENT_MAX
        assert self.realm.gold == 10000

    def test_develop_county_refused_without_gold(self):
        idx = self.capital()
        self.fund(DEV_COST_BASE + DEV_COST_STEP - 1)
        events = self.h.develop_county(idx)
        assert events
        assert self.h.provinces[idx].development == 1
        assert self.realm.gold == DEV_COST_BASE + DEV_COST_STEP - 1

    def test_develop_county_refused_for_a_foreign_actor(self):
        idx = self.capital()
        self.fund(10000)
        events = self.h.develop_county(idx, "king_erik")
        assert events, "чужой король не должен застраивать чужое графство"
        assert self.h.provinces[idx].development == 1
        assert self.realm.gold == 10000

    def test_develop_county_accepts_the_real_ruler(self):
        idx = self.capital()
        self.fund(10000)
        assert self.h.develop_county(idx, self.RULER)
        assert self.h.provinces[idx].development == 2

    def test_develop_county_refused_on_neutral_province(self):
        idx = self.neutral_index()
        gold_before = {r.id: r.gold for r in self.h.realms.values()}
        events = self.h.develop_county(idx)
        assert events, "нейтральная провинция обязана быть отказом"
        assert self.h.provinces[idx].development == 1
        assert {r.id: r.gold for r in self.h.realms.values()} == gold_before

    def test_develop_county_pays_the_owning_realm_not_the_neighbour(self):
        idx = self.capital()
        assert self.h.realm_owning(idx) == self.REALM
        others = [r.id for r in self.h.realms.values() if r.id != self.REALM]
        before = {r_id: self.h.realms[r_id].gold for r_id in others}
        self.fund(10000)
        assert self.h.develop_county(idx)
        assert {r_id: self.h.realms[r_id].gold for r_id in others} == before

    def test_develop_county_on_unknown_province_is_noop(self):
        for junk in (-1, 50, 9999, None, "3", True):
            assert self.h.develop_county(junk) == [], junk

    def test_develop_county_refused_when_ruler_is_dead(self):
        idx = self.capital()
        self.fund(10000)
        self.h.characters[self.RULER].alive = False
        assert self.h.develop_county(idx)
        assert self.h.provinces[idx].development == 1

    def test_development_never_exceeds_max_over_a_hundred_turns(self):
        self.fund(1000000)
        for _ in range(100):
            self.h.develop_county(self.capital())
            self.h.end_turn()
        assert self.h.provinces[self.capital()].development <= DEVELOPMENT_MAX

    # ==================================================================
    # T3. Подарок вассалу
    # ==================================================================

    def test_gift_constants(self):
        assert (GIFT_COST, GIFT_OPINION, GIFT_LOYALTY) == (60, 15, 10)
        assert GIFT_OPINION_BY_COUNT == (15, 8, 4, 2, 1)
        assert GIFT_LOYALTY_BY_COUNT == (10, 5, 3, 1, 1)

    def test_gift_gives_opinion_and_loyalty(self):
        vassal = self.h.characters["duke_brenna"]
        self.fund(5000)
        opinion, loyalty = vassal.opinion_of_liege, vassal.loyalty
        events = self.h.gift_vassal("duke_brenna")
        assert events
        assert vassal.opinion_of_liege == min(100, opinion + GIFT_OPINION)
        assert vassal.loyalty == min(100, loyalty + GIFT_LOYALTY)

    def test_gift_charges_the_liege_purse(self):
        # король платит из казны королевства
        self.fund(5000)
        assert self.h.gift_vassal("duke_brenna")
        assert self.realm.gold == 5000 - GIFT_COST
        # герцог без своего realm'а — из личного кошеля
        duke = self.h.characters["duke_orso"]
        personal = duke.gold
        assert self.h.gift_vassal("baron_wolf")
        assert duke.gold == personal - GIFT_COST
        assert self.h.purse_of(duke) == personal - GIFT_COST

    def test_gift_counts_received(self):
        vassal = self.h.characters["duke_brenna"]
        assert vassal.gifts_received == 0
        for expected in range(1, len(GIFT_OPINION_BY_COUNT) + 1):
            self.fund(5000)
            assert self.h.gift_vassal("duke_brenna")
            self.h.end_turn()
            assert vassal.gifts_received == expected

    def test_gift_keeps_opinion_and_loyalty_clamped(self):
        vassal = self.h.characters["duke_brenna"]
        vassal.opinion_of_liege = 95
        vassal.loyalty = 95
        self.fund(5000)
        assert self.h.gift_vassal("duke_brenna")
        assert vassal.opinion_of_liege == 100
        assert vassal.loyalty == 100

    def test_gift_returns_diminish_15_8_4_2_1(self):
        # отдача падает ЗА ЖИЗНЬ: 15, 8, 4, 2, 1 и дальше ноль
        assert [gift_gain(i, GIFT_OPINION_BY_COUNT) for i in range(5)] == [15, 8, 4, 2, 1]
        assert gift_gain(5, GIFT_OPINION_BY_COUNT) == 0
        assert gift_gain(99, GIFT_OPINION_BY_COUNT) == 0
        assert all(gift_gain(i + 1, GIFT_OPINION_BY_COUNT) <
                   gift_gain(i, GIFT_OPINION_BY_COUNT) for i in range(4))

    def test_gift_returns_actually_diminish_on_a_live_vassal(self):
        vassal = self.h.characters["duke_brenna"]
        gains = []
        for _ in range(len(GIFT_OPINION_BY_COUNT)):
            self.fund(5000)
            vassal.opinion_of_liege = 0
            assert self.h.gift_vassal("duke_brenna")
            gains.append(vassal.opinion_of_liege)
            self.h.end_turn()
        assert gains == list(GIFT_OPINION_BY_COUNT)

    def test_gift_sixth_is_refused_without_charge(self):
        vassal = self.h.characters["duke_brenna"]
        for _ in range(len(GIFT_OPINION_BY_COUNT)):
            self.fund(5000)
            assert self.h.gift_vassal("duke_brenna")
            self.h.end_turn()
        self.fund(5000)
        snapshot = (vassal.opinion_of_liege, vassal.loyalty,
                    vassal.gifts_received, self.realm.gold)
        events = self.h.gift_vassal("duke_brenna")
        assert events, "бессмысленный подарок обязан быть отказом"
        assert (vassal.opinion_of_liege, vassal.loyalty,
                vassal.gifts_received, self.realm.gold) == snapshot

    def test_gift_twice_to_the_same_vassal_in_one_turn_is_refused(self):
        vassal = self.h.characters["duke_brenna"]
        self.fund(5000)
        assert self.h.gift_vassal("duke_brenna")
        snapshot = (vassal.opinion_of_liege, vassal.loyalty, self.realm.gold)
        events = self.h.gift_vassal("duke_brenna")
        assert events, "второй подарок тому же вассалу за ход запрещён"
        assert (vassal.opinion_of_liege, vassal.loyalty,
                self.realm.gold) == snapshot
        assert vassal.gifts_received == 1

    def test_gift_to_different_vassals_in_one_turn_is_allowed(self):
        self.fund(5000)
        assert self.h.gift_vassal("duke_brenna")
        assert self.h.gift_vassal("duke_theon")
        assert self.h.characters["duke_brenna"].gifts_received == 1
        assert self.h.characters["duke_theon"].gifts_received == 1
        assert self.realm.gold == 5000 - 2 * GIFT_COST

    def test_gift_refused_without_gold(self):
        vassal = self.h.characters["duke_brenna"]
        self.fund(GIFT_COST - 1)
        events = self.h.gift_vassal("duke_brenna")
        assert events
        assert self.realm.gold == GIFT_COST - 1
        assert vassal.gifts_received == 0
        assert vassal.opinion_of_liege == 20

    def test_gift_refused_to_dead_vassal(self):
        self.fund(5000)
        self.h.characters["duke_brenna"].alive = False
        events = self.h.gift_vassal("duke_brenna")
        assert events
        assert self.realm.gold == 5000

    def test_gift_refused_to_a_character_without_a_liege(self):
        # король не вассал никому — подарок некому адресовать
        self.fund(5000)
        events = self.h.gift_vassal(self.RULER)
        assert events
        assert self.realm.gold == 5000

    def test_gift_to_unknown_vassal_is_noop(self):
        self.fund(5000)
        assert self.h.gift_vassal("baron_ghost") == []
        assert self.h.gift_vassal(None) == []
        assert self.realm.gold == 5000

    def test_gift_to_landless_baron_is_allowed(self):
        # безземельный вассал — самый обиженный, подарок ему особенно в тему
        self.fund(5000)
        self.h.revoke_fief("baron_wolf")
        self.h.characters["duke_orso"].gold = 500
        assert self.h.gift_vassal("baron_wolf")
        assert self.h.characters["baron_wolf"].gifts_received == 1

    # ==================================================================
    # T4. Корона и налоговая политика
    # ==================================================================

    def test_crown_constants(self):
        assert (CROWN_COST, CROWN_PRESTIGE_COST, MAX_CROWN_AUTHORITY) == (300, 30, 3)

    def test_crown_charges_gold_and_prestige(self):
        self.fund(1000)
        self.realm.prestige = 60
        authority_before = self.realm.crown_authority
        events = self.h.raise_crown_authority(self.REALM)
        assert events
        assert self.realm.gold == 1000 - CROWN_COST
        assert self.realm.prestige == 60 - CROWN_PRESTIGE_COST
        assert self.realm.crown_authority == authority_before + 1

    def test_crown_authority_grows_at_most_to_three(self):
        self.fund(10000)
        self.realm.crown_authority = 0
        for expected in (1, 2, 3):
            self.realm.prestige = 100
            assert self.h.raise_crown_authority(self.REALM)
            assert self.realm.crown_authority == expected
            self.h.end_turn()
        events = self.h.raise_crown_authority(self.REALM)
        assert events, "выше предела корона не растёт"
        assert self.realm.crown_authority == MAX_CROWN_AUTHORITY

    def test_crown_refused_without_prestige(self):
        self.fund(1000)
        self.realm.prestige = CROWN_PRESTIGE_COST - 1
        events = self.h.raise_crown_authority(self.REALM)
        assert events
        assert self.realm.prestige == CROWN_PRESTIGE_COST - 1
        assert self.realm.gold == 1000

    def test_crown_refused_without_gold(self):
        self.fund(CROWN_COST - 1)
        self.realm.prestige = 100
        authority = self.realm.crown_authority
        events = self.h.raise_crown_authority(self.REALM)
        assert events
        assert self.realm.gold == CROWN_COST - 1
        assert self.realm.prestige == 100
        assert self.realm.crown_authority == authority

    def test_crown_on_unknown_realm_is_noop(self):
        assert self.h.raise_crown_authority("kingdom_of_narnia") == []

    def test_crown_refused_when_ruler_is_dead(self):
        self.fund(1000)
        self.realm.prestige = 100
        self.h.characters[self.RULER].alive = False
        assert self.h.raise_crown_authority(self.REALM)
        assert self.realm.crown_authority == 2

    def test_tax_policy_one_requires_crown_authority(self):
        assert TAX_POLICY_CROWN_AUTHORITY == 2
        self.realm.crown_authority = 1
        events = self.h.set_tax_policy(self.REALM, 1)
        assert events, "тяжёлый налог без короны обязан быть отказом"
        assert self.realm.tax_policy == 0
        self.realm.crown_authority = TAX_POLICY_CROWN_AUTHORITY
        assert self.h.set_tax_policy(self.REALM, 1)
        assert self.realm.tax_policy == 1

    def test_tax_policy_gate_is_reachable_only_by_strong_crown(self):
        self.fund(10000)
        self.realm.prestige = 100
        self.realm.crown_authority = 2
        assert self.h.raise_crown_authority(self.REALM)
        assert self.realm.crown_authority == 3
        assert self.h.set_tax_policy(self.REALM, 1)
        self.h.end_turn()
        assert self.h.set_tax_policy(self.REALM, 0)

    def test_tax_policy_range_is_clamped(self):
        assert (TAX_POLICY_MIN, TAX_POLICY_MAX) == (0, 1)
        self.realm.crown_authority = 3
        assert self.h.set_tax_policy(self.REALM, 99)
        assert self.realm.tax_policy == TAX_POLICY_MAX
        self.h.end_turn()
        assert self.h.set_tax_policy(self.REALM, -42)
        assert self.realm.tax_policy == TAX_POLICY_MIN

    def test_tax_policy_out_of_range_respects_the_crown_gate(self):
        self.realm.crown_authority = 1
        assert self.h.set_tax_policy(self.REALM, 99)
        assert self.realm.tax_policy == 0

    def test_tax_policy_same_value_reports_no_change(self):
        self.realm.crown_authority = 3
        self.realm.tax_policy = 1
        events = self.h.set_tax_policy(self.REALM, 1)
        assert len(events) == 1
        assert self.realm.tax_policy == 1

    def test_tax_policy_costs_nothing(self):
        # это не трата, а переключатель: деньги берутся гейтом через корону
        self.fund(777)
        self.realm.crown_authority = 2
        assert self.h.set_tax_policy(self.REALM, 1)
        assert self.realm.gold == 777

    def test_tax_policy_rejects_junk_without_crashing(self):
        for junk in (None, "high", [], True):
            events = self.h.set_tax_policy(self.REALM, junk)
            assert isinstance(events, list), junk
            assert events, junk
            assert self.realm.tax_policy == 0, junk

    def test_tax_policy_on_unknown_realm_is_noop(self):
        assert self.h.set_tax_policy("kingdom_of_narnia", 1) == []

    # ==================================================================
    # T5. Наёмники — единственный потребитель ГПСЧ
    # ==================================================================

    def test_mercenary_constants(self):
        assert (MERC_COST_PER_BLOCK, MERC_MAX_BLOCKS_PER_TURN) == (180, 6)
        assert MERC_BLOCK_TROOPS == 100
        assert MERC_TIER_THRESHOLDS == (60, 90)
        assert MERC_SALT_STRIDE > MERC_MAX_BLOCKS_PER_TURN, \
            "иначе соли соседних ходов пересекутся"

    def test_mercenary_block_costs_180(self):
        self.fund(1000)
        assert len(self.h.hire_mercenaries(self.REALM, 3)) == 3
        assert self.realm.gold == 1000 - 3 * MERC_COST_PER_BLOCK
        assert len(self.realm.mercenary_tiers) == 3

    def test_mercenary_tiers_are_always_one_two_or_three(self):
        self.fund(1000000)
        for _ in range(20):
            assert self.h.hire_mercenaries(self.REALM, MERC_MAX_BLOCKS_PER_TURN)
            self.h.end_turn()
        assert len(self.realm.mercenary_tiers) == 20 * MERC_MAX_BLOCKS_PER_TURN
        assert set(self.realm.mercenary_tiers) <= {1, 2, 3}

    def test_mercenary_events_report_the_tier(self):
        self.fund(1000)
        events = self.h.hire_mercenaries(self.REALM, 2)
        assert len(events) == 2
        for index, event in enumerate(events):
            assert f"тира {self.realm.mercenary_tiers[index]}" in event, event
            assert str(MERC_BLOCK_TROOPS) in event, event

    def test_mercenary_block_limit_is_refused(self):
        self.fund(100000)
        events = self.h.hire_mercenaries(self.REALM, MERC_MAX_BLOCKS_PER_TURN + 1)
        assert events
        assert self.realm.gold == 100000
        assert self.realm.mercenary_tiers == []

    def test_mercenary_at_the_block_limit_is_allowed(self):
        self.fund(100000)
        assert len(self.h.hire_mercenaries(self.REALM, MERC_MAX_BLOCKS_PER_TURN)) == \
            MERC_MAX_BLOCKS_PER_TURN

    def test_mercenary_refused_without_gold(self):
        self.fund(MERC_COST_PER_BLOCK - 1)
        events = self.h.hire_mercenaries(self.REALM, 1)
        assert events
        assert self.realm.gold == MERC_COST_PER_BLOCK - 1
        assert self.realm.mercenary_tiers == []

    def test_mercenary_rejects_junk_blocks(self):
        self.fund(100000)
        for junk in (0, -3, None, "many", True, [1]):
            events = self.h.hire_mercenaries(self.REALM, junk)
            assert isinstance(events, list), junk
            assert events, junk
            assert self.realm.mercenary_tiers == [], junk
        assert self.realm.gold == 100000

    def test_mercenary_on_unknown_realm_is_noop(self):
        assert self.h.hire_mercenaries("kingdom_of_narnia", 1) == []

    def test_mercenary_tier_roll_is_integral_and_weighted(self):
        # тысяча бросков одного генератора обязана дать примерно 60/30/10
        rnd = new_streams(1).stream("probe")
        counts = [0, 0, 0, 0]
        for _ in range(1000):
            tier = mercenary_tier(rnd)
            assert tier in (1, 2, 3)
            counts[tier] += 1
        assert 520 < counts[1] < 680, counts
        assert 230 < counts[2] < 380, counts
        assert 40 < counts[3] < 160, counts

    def test_mercenary_salt_is_integer_arithmetic_only(self):
        assert mercenary_salt(1, 0) == 1 * MERC_SALT_STRIDE
        assert mercenary_salt(3, 4) == 3 * MERC_SALT_STRIDE + 4
        assert isinstance(mercenary_salt(5, 2), int)
        assert mercenary_salt(5, 2) != mercenary_salt(2, 5)

    def test_mercenary_salts_of_adjacent_turns_never_overlap(self):
        salts = {mercenary_salt(turn, index)
                 for turn in range(1, 120)
                 for index in range(MERC_MAX_BLOCKS_PER_TURN)}
        assert len(salts) == 119 * MERC_MAX_BLOCKS_PER_TURN

    def test_mercenary_tiers_are_reproducible_for_the_same_seed(self):
        a, b = seeded_hierarchy(4242), seeded_hierarchy(4242)
        for h in (a, b):
            h.hire_mercenaries(self.REALM, MERC_MAX_BLOCKS_PER_TURN)
        assert a.realms[self.REALM].mercenary_tiers == b.realms[self.REALM].mercenary_tiers
        assert len(a.realms[self.REALM].mercenary_tiers) == MERC_MAX_BLOCKS_PER_TURN

    def test_mercenary_tiers_are_reproducible_after_a_shared_history(self):
        a, b = seeded_hierarchy(4242), seeded_hierarchy(4242)
        for h in (a, b):
            h.end_turn()
            h.develop_county(h.realms[self.REALM].capital_idx)
            h.hire_mercenaries(self.REALM, MERC_MAX_BLOCKS_PER_TURN)
        assert a.realms[self.REALM].mercenary_tiers == b.realms[self.REALM].mercenary_tiers

    def test_different_seeds_give_different_mercenary_tiers(self):
        tiers = [tuple(hire_tiers(seed)) for seed in (0, 1, 7, 999, 424242, 31337)]
        assert len(set(tiers)) > 1, tiers

    def test_turn_shift_changes_the_tier_sequence(self):
        h = seeded_hierarchy(4242)
        first = hire_tiers_of(h, MERC_MAX_BLOCKS_PER_TURN)
        h.turn += 1
        second = hire_tiers_of(h, MERC_MAX_BLOCKS_PER_TURN)
        assert first != second, "сдвиг хода обязан менять соль, а значит и тиры"

    def test_turn_shift_changes_the_tier_at_least_somewhere(self):
        changed = []
        for seed in (0, 1, 7, 999, 424242):
            h = seeded_hierarchy(seed)
            before = hire_tiers_of(h, 3)
            h.turn += 1
            after = hire_tiers_of(h, 3)
            changed += [a != b for a, b in zip(before, after)]
        assert any(changed), "ни один сдвиг хода нигде не поменял тир"

    def test_hiring_mercenaries_is_the_only_spend_of_the_dice(self):
        h = seeded_hierarchy(4242)
        assert len(h.streams) == 0
        assert h.streams.consumed(MERC_QUALITY_STREAM, mercenary_salt(1, 0)) == 0
        h.hire_mercenaries(self.REALM, 2)
        # ответвлённые потоки не попадают в len(streams): там только базовые
        assert len(h.streams) == 0
        assert h.streams.consumed(MERC_QUALITY_STREAM, mercenary_salt(1, 0)) > 0
        assert h.streams.consumed(MERC_QUALITY_STREAM, mercenary_salt(1, 1)) > 0

    def test_mercenary_distribution_over_many_hires_is_roughly_60_30_10(self):
        h = make_hierarchy()
        h.realms[self.REALM].gold = 10 ** 6
        for _ in range(30):
            assert h.hire_mercenaries(self.REALM, MERC_MAX_BLOCKS_PER_TURN)
            h.end_turn()
        tiers = h.realms[self.REALM].mercenary_tiers
        assert len(tiers) == 180
        share1 = tiers.count(1) / len(tiers)
        share2 = tiers.count(2) / len(tiers)
        share3 = tiers.count(3) / len(tiers)
        assert 0.45 < share1 < 0.75, share1
        assert 0.15 < share2 < 0.45, share2
        assert 0.03 < share3 < 0.25, share3

    def test_mercenary_tiers_start_empty_and_are_not_shared_between_realms(self):
        a, b = make_hierarchy(), make_hierarchy()
        assert a.realms[self.REALM].mercenary_tiers == []
        for h in (a, b):
            h.realms[self.REALM].gold = 1000
            h.hire_mercenaries(self.REALM, 1)
        # правка тиров одного мира не трогает другой
        a.realms[self.REALM].mercenary_tiers.append(3)
        assert len(b.realms[self.REALM].mercenary_tiers) == 1
        assert len(a.realms["kingdom_ember"].mercenary_tiers) == 0

    def test_clean_mercenary_tiers_drops_junk(self):
        assert clean_mercenary_tiers([1, 2, "3", None, True, 3.5, 3]) == [1, 2, 3]
        assert clean_mercenary_tiers("tiers") == []
        assert clean_mercenary_tiers(None) == []

    def test_from_state_survives_broken_mercenary_tiers(self):
        state = self.h.to_state()
        state["realms"][self.REALM]["mercenary_tiers"] = ["a", None, 2]
        restored = Hierarchy.from_state(state, copy_provinces())
        assert restored.realms[self.REALM].mercenary_tiers == [2]

    # ==================================================================
    # T6. Наём гарнизона
    # ==================================================================

    def test_garrison_recruit_fee_is_four_turns_of_upkeep(self):
        assert GARRISON_RECRUIT_COST_PER_100 == 40
        assert GARRISON_RECRUIT_COST_PER_100 == 4 * GARRISON_UPKEEP_PER_100

    def test_hire_garrison_respects_the_cap(self):
        idx = self.capital()
        cap = self.h.garrison_cap(idx)
        self.h.provinces[idx].garrison = 0
        self.fund(10000)
        assert self.h.hire_garrison(idx, cap * 3)
        assert self.h.provinces[idx].garrison == cap

    def test_hire_garrison_charges_proportionally(self):
        idx = self.capital()
        self.h.provinces[idx].garrison = 0
        self.fund(10000)
        assert self.h.hire_garrison(idx, 250)
        assert self.h.provinces[idx].garrison == 250
        assert self.realm.gold == 10000 - 250 * GARRISON_RECRUIT_COST_PER_100 // 100

    def test_hire_garrison_takes_only_the_free_slots_left(self):
        idx = self.capital()
        cap = self.h.garrison_cap(idx)
        self.h.provinces[idx].garrison = cap - 40
        self.fund(10000)
        events = self.h.hire_garrison(idx, 200)
        assert events
        assert self.h.provinces[idx].garrison == cap

    def test_hire_garrison_refused_on_full_garrison(self):
        idx = self.capital()
        self.h.provinces[idx].garrison = self.h.garrison_cap(idx)
        self.fund(10000)
        events = self.h.hire_garrison(idx, 50)
        assert events
        assert self.h.provinces[idx].garrison == self.h.garrison_cap(idx)
        assert self.realm.gold == 10000

    def test_hire_garrison_refused_for_a_foreign_actor(self):
        idx = self.capital()
        before = self.h.provinces[idx].garrison
        self.fund(10000)
        events = self.h.hire_garrison(idx, 50, "king_erik")
        assert events, "чужой король не должен нанимать гарнизон в чужое графство"
        assert self.h.provinces[idx].garrison == before
        assert self.realm.gold == 10000

    def test_hire_garrison_refused_on_neutral_province(self):
        idx = self.neutral_index()
        before = self.h.provinces[idx].garrison
        self.fund(10000)
        events = self.h.hire_garrison(idx, 50)
        assert events
        assert self.h.provinces[idx].garrison == before

    def test_hire_garrison_refused_without_gold(self):
        idx = self.capital()
        before = self.h.provinces[idx].garrison
        self.fund(GARRISON_RECRUIT_COST_PER_100 // 100 - 1)
        events = self.h.hire_garrison(idx, 100)
        assert events
        assert self.h.provinces[idx].garrison == before

    def test_hire_garrison_rejects_junk(self):
        idx = self.capital()
        before = self.h.provinces[idx].garrison
        self.fund(10000)
        for junk in (0, -5, None, "many", True):
            events = self.h.hire_garrison(idx, junk)
            assert isinstance(events, list), junk
            assert events, junk
            assert self.h.provinces[idx].garrison == before, junk

    def test_hire_garrison_on_unknown_province_is_noop(self):
        self.fund(10000)
        for junk in (-1, 50, 9999, None, "3"):
            assert self.h.hire_garrison(junk, 50) == [], junk

    def test_hire_garrison_refused_when_ruler_is_dead(self):
        idx = self.capital()
        before = self.h.provinces[idx].garrison
        self.fund(10000)
        self.h.characters[self.RULER].alive = False
        assert self.h.hire_garrison(idx, 50)
        assert self.h.provinces[idx].garrison == before

    def test_hire_garrison_grows_the_upkeep_of_the_owning_realm(self):
        idx = self.capital()
        self.h.provinces[idx].garrison = 0
        self.fund(10000)
        base = self.h.garrison_upkeep(self.REALM)
        assert self.h.hire_garrison(idx, 100)
        assert self.h.garrison_upkeep(self.REALM) - base == GARRISON_UPKEEP_PER_100

    # ==================================================================
    # Лимиты «не чаще N раз за ход»
    # ==================================================================

    def test_limits_are_configurable_per_action(self):
        assert LEVY_RAISES_PER_TURN == 2
        assert DEVELOPMENTS_PER_TURN == 2
        assert GARRISON_HIRES_PER_TURN == 2
        assert GIFTS_PER_TURN == 1
        assert CROWN_RAISES_PER_TURN == 1
        assert MERC_HIRES_PER_TURN == 1

    def test_second_call_of_the_same_action_is_refused_and_reopened_by_end_turn(self):
        self.fund(100000)
        self.realm.prestige = 100
        assert self.h.raise_crown_authority(self.REALM)
        snapshot = (self.realm.gold, self.realm.crown_authority,
                    self.realm.prestige)
        events = self.h.raise_crown_authority(self.REALM)
        assert events, "вторая корона за ход обязана быть отказом"
        assert (self.realm.gold, self.realm.crown_authority,
                self.realm.prestige) == snapshot
        self.h.end_turn()
        self.realm.prestige = 100
        assert self.h.raise_crown_authority(self.REALM), "после end_turn можно снова"

    def test_levy_limit_is_two_per_turn(self):
        self.fund(100000)
        assert self.h.raise_levy(self.REALM, 1)
        assert self.h.raise_levy(self.REALM, 1)
        self.assert_refused(self.h.raise_levy(self.REALM, 1))
        assert self.realm.raised_levy == 2 * LEVY_BLOCK_TROOPS
        self.h.end_turn()
        assert self.h.raise_levy(self.REALM, 1)

    def test_development_limit_is_two_per_turn(self):
        self.fund(100000)
        first, second = self.owned()[:2]
        assert self.h.develop_county(first)
        assert self.h.develop_county(second)
        self.assert_refused(self.h.develop_county(first))
        assert self.h.provinces[first].development == 2
        self.h.end_turn()
        assert self.h.develop_county(first)

    def test_garrison_limit_is_two_per_turn(self):
        self.fund(100000)
        first, second = self.owned()[:2]
        for idx in (first, second):
            self.h.provinces[idx].garrison = 0
        assert self.h.hire_garrison(first, 10)
        assert self.h.hire_garrison(second, 10)
        self.assert_refused(self.h.hire_garrison(first, 10))
        assert self.h.provinces[first].garrison == 10
        self.h.end_turn()
        assert self.h.hire_garrison(first, 10)

    def test_mercenary_limit_is_one_hire_per_turn(self):
        self.fund(100000)
        assert len(self.h.hire_mercenaries(self.REALM, 2)) == 2
        self.assert_refused(self.h.hire_mercenaries(self.REALM, 1))
        assert len(self.realm.mercenary_tiers) == 2
        self.h.end_turn()
        assert len(self.h.hire_mercenaries(self.REALM, 1)) == 1

    def test_tax_policy_limit_is_one_change_per_turn(self):
        self.realm.crown_authority = 2
        assert self.h.set_tax_policy(self.REALM, 1)
        self.assert_refused(self.h.set_tax_policy(self.REALM, 0))
        assert self.realm.tax_policy == 1
        self.h.end_turn()
        assert self.h.set_tax_policy(self.REALM, 0)

    def test_a_refused_action_does_not_spend_the_allowance(self):
        # отказ по золоту не должен съедать право на действие
        self.fund(0)
        self.assert_refused(self.h.raise_levy(self.REALM, 1))
        self.fund(100000)
        assert self.h.raise_levy(self.REALM, 1), "право на левейс ещё осталось"

    def test_limits_are_per_actor_not_global(self):
        # лимит герцога не расходует лимит короля
        self.fund(100000)
        self.h.characters["duke_orso"].gold = 10000
        assert self.h.gift_vassal("duke_brenna")
        assert self.h.gift_vassal("baron_wolf")
        assert self.h.gift_vassal("baron_gray")

    def test_action_ledger_is_cleared_by_end_turn(self):
        self.fund(100000)
        self.h.develop_county(self.capital())
        assert self.h.action_ledger, "после траты журнал непуст"
        self.h.end_turn()
        assert self.h.action_ledger == {}

    def test_action_ledger_is_not_part_of_the_snapshot(self):
        # каноническая точка сохранения — граница хода, а там журнал пуст
        self.fund(100000)
        self.h.develop_county(self.capital())
        state = self.h.to_state()
        assert "action_ledger" not in state
        assert "action_ledger" not in all_keys(state)
        assert set(state) == SNAPSHOT_KEYS

    def test_snapshot_at_turn_boundary_keeps_fingerprint_and_empty_ledger(self):
        self.fund(100000)
        self.h.develop_county(self.capital())
        self.h.end_turn()
        restored = Hierarchy.from_state(self.h.to_state(), copy_provinces())
        assert restored.action_ledger == {}
        assert restored.state_fingerprint() == self.h.state_fingerprint()

    # ==================================================================
    # Новые поля в снапшоте
    # ==================================================================

    def test_new_fields_survive_round_trip(self):
        self.fund(100000)
        self.h.raise_levy(self.REALM, 2)
        self.h.hire_mercenaries(self.REALM, 3)
        self.h.gift_vassal("duke_brenna")
        restored = Hierarchy.from_state(self.h.to_state(), copy_provinces())
        assert restored.realms[self.REALM].raised_levy == self.realm.raised_levy
        assert restored.realms[self.REALM].mercenary_tiers == \
            self.realm.mercenary_tiers
        assert restored.characters["duke_brenna"].gifts_received == 1
        assert restored.state_fingerprint() == self.h.state_fingerprint()

    def test_new_fields_survive_json_round_trip(self):
        self.fund(100000)
        self.h.raise_levy(self.REALM, 1)
        self.h.hire_mercenaries(self.REALM, 2)
        restored = Hierarchy.from_state(loads(dumps(self.h.to_state())), copy_provinces())
        assert restored.realms[self.REALM].raised_levy == LEVY_BLOCK_TROOPS
        assert restored.realms[self.REALM].mercenary_tiers == \
            self.realm.mercenary_tiers
        assert restored.state_fingerprint() == self.h.state_fingerprint()

    def test_old_snapshot_without_new_fields_loads_as_zero(self):
        state = self.h.to_state()
        state["realms"] = {
            key: {name: value for name, value in data.items()
                  if name not in ("raised_levy", "mercenary_tiers")}
            for key, data in state["realms"].items()}
        state["characters"] = {
            key: {name: value for name, value in data.items()
                  if name != "gifts_received"}
            for key, data in state["characters"].items()}
        restored = Hierarchy.from_state(state, copy_provinces())
        assert restored.realms[self.REALM].raised_levy == 0
        assert restored.realms[self.REALM].mercenary_tiers == []
        assert restored.characters["duke_brenna"].gifts_received == 0

    def test_fingerprint_tracks_new_fields(self):
        a, b, c = make_hierarchy(), make_hierarchy(), make_hierarchy()
        before = a.state_fingerprint()
        a.realms[self.REALM].raised_levy += 1
        assert a.state_fingerprint() != before
        b.characters["duke_brenna"].gifts_received += 1
        assert b.state_fingerprint() != before
        c.realms[self.REALM].mercenary_tiers.append(2)
        assert c.state_fingerprint() != before

    def test_mercenary_tiers_in_snapshot_are_a_copy_not_the_live_list(self):
        self.fund(1000)
        self.h.hire_mercenaries(self.REALM, 1)
        state = self.h.to_state()
        state["realms"][self.REALM]["mercenary_tiers"].append(3)
        assert len(self.realm.mercenary_tiers) == 1

    # ==================================================================
    # Регрессия детерминизма
    # ==================================================================

    def test_thirty_turns_with_spending_hash_equal(self):
        a, b = make_hierarchy(), make_hierarchy()
        for h in (a, b):
            for _ in range(30):
                h.develop_county(h.realms[self.REALM].capital_idx)
                h.hire_garrison(h.realms[self.REALM].capital_idx, 40)
                h.raise_levy(self.REALM, 1)
                h.gift_vassal("duke_brenna")
                h.hire_mercenaries(self.REALM, 2)
                h.end_turn()
        assert a.turn == b.turn == 31
        assert a.state_fingerprint() == b.state_fingerprint()

    def test_ticks_still_never_roll_the_dice(self):
        h = make_hierarchy()
        h.realms[self.REALM].gold = 100000
        assert h.hire_mercenaries(self.REALM, 2)
        for _ in range(12):
            h.end_turn()
        assert len(h.streams) == 0, "фаза хода создала именованный поток"
        assert h.streams.consumed(MERC_QUALITY_STREAM, mercenary_salt(13, 0)) == 0

    def test_summary_keys_are_unchanged_by_the_stage(self):
        # точный набор ключей summary зафиксирован тестами детерминизма
        h = make_hierarchy()
        h.realms[self.REALM].gold = 100000
        h.develop_county(h.realms[self.REALM].capital_idx)
        h.hire_mercenaries(self.REALM, 1)
        h.gift_vassal("duke_brenna")
        summary = h.summary()
        assert set(summary) == {"turn", "realms", "duchies", "characters"}
        assert set(summary["realms"][self.REALM]) == {"gold", "prestige",
                                                      "stability", "held"}
        assert set(summary["duchies"]["emberfall"]) == {"holder", "income"}
        assert set(summary["characters"]["duke_brenna"]) == {"rank", "loyalty",
                                                             "opinion", "gold"}

    def test_states_does_not_import_global_random(self):
        source = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "states.py"), encoding="utf-8").read()
        assert "import random" not in source

    # ==================================================================
    # Длинная дистанция
    # ==================================================================

    def test_hundred_turns_of_spending_stay_healthy(self):
        h = make_hierarchy()
        realm = h.realms[self.REALM]
        for _ in range(100):
            realm.gold = max(realm.gold, 1000)  # «игрок не копит, а тратит»
            h.develop_county(realm.capital_idx)
            h.hire_garrison(realm.capital_idx, 40)
            h.raise_levy(self.REALM, 1)
            if realm.gold > 2000:
                h.hire_mercenaries(self.REALM, 2)
            h.end_turn()
        assert h.turn == 101
        for other in h.realms.values():
            assert other.gold >= 0, other.id
            assert other.gold < 10 ** 7, f"{other.id}: инфляция"
            assert h.realm_income(other.id) > 0, other.id
        assert realm.raised_levy <= h.realm_levy(self.REALM)
        assert realm.mercenary_tiers, "наёмников так и не наняли"
        assert all(1 <= p.development <= DEVELOPMENT_MAX for p in h.provinces)
        assert all(p.garrison >= 0 for p in h.provinces)
        assert sum(1 for i in range(50) if h.county_income(i) > 0) >= 40
        for province in h.provinces:
            assert 0 <= province.loyalty <= 100, province.name

    def test_a_spending_king_keeps_a_tighter_treasury_than_a_hoarder(self):
        spender, hoarder = make_hierarchy(), make_hierarchy()
        for _ in range(100):
            spender.develop_county(spender.realms[self.REALM].capital_idx)
            spender.hire_garrison(spender.realms[self.REALM].capital_idx, 40)
            spender.raise_levy(self.REALM, 1)
            spender.hire_mercenaries(self.REALM, 2)
            spender.end_turn()
            hoarder.end_turn()
        # у скупого казна раздувается, у расточителя держится в узде
        assert hoarder.realms[self.REALM].gold > spender.realms[self.REALM].gold
        assert spender.realms[self.REALM].gold >= 0
        assert spender.realms[self.REALM].gold < 10 ** 4
        assert hoarder.realms[self.REALM].gold > 10 ** 4

    def test_fingerprint_reproducible_with_a_seeded_mercenary_hire(self):
        a, b = seeded_hierarchy(20240), seeded_hierarchy(20240)
        for h in (a, b):
            for _ in range(6):
                h.hire_mercenaries(self.REALM, 4)
                h.end_turn()
        assert a.realms[self.REALM].mercenary_tiers == \
            b.realms[self.REALM].mercenary_tiers
        assert a.state_fingerprint() == b.state_fingerprint()


def seeded_hierarchy(seed: int) -> Hierarchy:
    """Иерархия на свежей копии карты с явным зерном ГПСЧ и полной казной."""
    hierarchy = build_default_hierarchy(copy_provinces(), streams=new_streams(seed))
    for realm in hierarchy.realms.values():
        realm.gold = 100000
    return hierarchy


def hire_tiers_of(hierarchy: Hierarchy, blocks: int) -> List[int]:
    """Найти ``blocks`` наёмников и вернуть только тиры этого найма."""
    realm = hierarchy.realms[TestExpenditures.REALM]
    before = len(realm.mercenary_tiers)
    hierarchy.hire_mercenaries(TestExpenditures.REALM, blocks)
    return list(realm.mercenary_tiers[before:])


def hire_tiers(seed: int) -> List[int]:
    return hire_tiers_of(seeded_hierarchy(seed), MERC_MAX_BLOCKS_PER_TURN)

# --------------------------------------------------------------------------
# Права приказов (этап 1.1)
# --------------------------------------------------------------------------


#: Актёры для тестов прав. Зелёное герцогство — единственное, у которого
#: ``province.owner`` совпадает с нацией во всём дукционе (leafguard, 40-44),
#: поэтому «свой барон» и «своя земля» проверяются на нём, а не на greymoor,
#: где все пять провинций нейтральны.
RIGHTS_KING = "king_sigurd"          # зелёный король
RIGHTS_DUKE = "duke_lyra"            # leafguard, 40-44, все зелёные
RIGHTS_DUKE_OTHER = "duke_orso"      # greymoor, 35-39, все нейтральные
RIGHTS_BARON = "baron_thorn"         # вассал RIGHTS_DUKE, держит 41
RIGHTS_BARON_OTHER = "baron_moss"    # второй вассал RIGHTS_DUKE, держит 43
RIGHTS_FOREIGN_KING = "king_erik"    # красный: ему не подчиняется никто зелёный
RIGHTS_OWN_PROVINCE = 44             # зелёная, в leafguard
RIGHTS_NEUTRAL_PROVINCE = 47         # нейтральная
RIGHTS_FOREIGN_PROVINCE = 11         # красная


class TestOrderRights:
    """``by_actor`` переносит правило «кто вправе» из UI в состояние.

    Контракт, который здесь защищается:

    * ``by_actor=None`` — прежнее поведение без проверок (его зовут 308 старых
      тестов и UI-обёртка, поэтому он обязан остаться прежним ДОСЛОВНО);
    * ``by_actor`` задан — актор обязан существовать, быть живым и быть
      сюзереном цели по рангу: герцогом командует король его realm'а, бароном —
      непосредственный сюзерен, королем — никто;
    * ``grant_fief`` сверх того требует, чтобы земля принадлежала realm'у
      актора и чтобы получатель не держал графство;
    * ``set_contract`` сверх того ОТКЛОНЯЕТ значение вне диапазона (не клампит)
      и тратит лимит ``action_ledger``.

    Отказ всегда — ОДНО событие с причиной: это то, что UI показывает игроку.
    """

    def setup_method(self):
        self.h = make_hierarchy()

    # ---------------- хелперы ----------------

    def landless(self, baron_id: str) -> str:
        """Сделать барона безземельным, сохранив его дукцию (и сюзерена)."""
        self.h.revoke_fief(baron_id)
        assert self.h.characters[baron_id].province_idx is None
        return baron_id

    def assert_refused(self, events, *parts: str) -> None:
        assert isinstance(events, list) and len(events) == 1, events
        message = events[0]
        assert isinstance(message, str) and message, events
        for part in parts:
            assert part in message, (part, message)

    def fingerprint(self) -> str:
        return self.h.state_fingerprint()

    # ==================================================================
    # Правило ранга
    # ==================================================================

    def test_command_min_rank_is_the_documented_one(self):
        # бароном командует герцог, герцогом — король, королем — никто
        assert COMMAND_MIN_RANK == {TitleRank.BARON: Tier.DUCHY,
                                    TitleRank.DUKE: Tier.REALM}
        assert TitleRank.KING not in COMMAND_MIN_RANK

    def test_contract_change_limit_is_once_per_turn(self):
        assert CONTRACT_CHANGES_PER_TURN == 1

    def test_duke_may_give_fief_to_own_baron(self):
        self.landless(RIGHTS_BARON)
        events = self.h.grant_fief(RIGHTS_OWN_PROVINCE, RIGHTS_BARON,
                                   by_actor=RIGHTS_DUKE)
        assert events, "своему барону герцог выдать обязан"
        assert self.h.characters[RIGHTS_BARON].province_idx == RIGHTS_OWN_PROVINCE

    def test_duke_may_not_give_fief_to_a_foreign_baron(self):
        # baron_wolf под duke_orso, а не под duke_lyra
        assert self.h.revoke_fief("baron_wolf")
        before = self.fingerprint()
        events = self.h.grant_fief(RIGHTS_OWN_PROVINCE, "baron_wolf",
                                   by_actor=RIGHTS_DUKE)
        self.assert_refused(events, "не сюзерен")
        assert self.h.characters["baron_wolf"].province_idx is None
        assert self.fingerprint() == before, "отказ не должен менять состояние"

    def test_king_may_command_own_duke(self):
        events = self.h.set_contract("duke_lyra", 3, by_actor=RIGHTS_KING)
        assert events, "король вправе менять контракт своего герцога"
        assert self.h.contracts["duke_lyra"].level == 3

    def test_king_may_not_command_a_foreign_duke(self):
        # ЭТО ТОТ САМЫЙ БАГ, который закрывает этап 1.1: раньше set_contract
        # подставлял liege_of(вассала) и позволял переписать чужой контракт
        before = self.fingerprint()
        events = self.h.set_contract("duke_lyra", 4, by_actor=RIGHTS_FOREIGN_KING)
        self.assert_refused(events, "не сюзерен")
        assert self.h.contracts["duke_lyra"].level == 2
        assert self.fingerprint() == before

    def test_king_may_give_fief_to_own_duke_and_keeps_his_duchy(self):
        events = self.h.grant_fief(RIGHTS_OWN_PROVINCE, RIGHTS_DUKE,
                                   by_actor=RIGHTS_KING)
        assert events
        duke = self.h.characters[RIGHTS_DUKE]
        assert duke.province_idx == RIGHTS_OWN_PROVINCE
        # выдача графства герцогу НЕ отнимает у него дукцию — иначе все его
        # бароны осиротели бы через liege_of
        assert duke.duchy_id == "leafguard"
        assert self.h.duchies["leafguard"].holder_id == RIGHTS_DUKE
        assert [c.id for c in self.h.vassals_of(RIGHTS_DUKE)] == \
            sorted([RIGHTS_BARON, RIGHTS_BARON_OTHER])

    def test_baron_may_not_command_another_baron(self):
        # ранг важен не только для сюзерена: барон не командует даже «своему»
        events = self.h.set_contract(RIGHTS_BARON_OTHER, 3, by_actor=RIGHTS_BARON)
        self.assert_refused(events, "не сюзерен")
        assert self.h.contracts[RIGHTS_BARON_OTHER].level == 2

    def test_nobody_may_command_a_king(self):
        for actor in (RIGHTS_DUKE, RIGHTS_FOREIGN_KING, RIGHTS_BARON):
            events = self.h.set_contract(RIGHTS_KING, 4, by_actor=actor)
            self.assert_refused(events, "никто")
        assert RIGHTS_KING not in self.h.contracts

    def test_fief_and_revoke_refuse_a_king_target_too(self):
        assert self.h.grant_fief(RIGHTS_OWN_PROVINCE, RIGHTS_KING,
                                 by_actor=RIGHTS_KING)
        assert self.h.revoke_fief(RIGHTS_KING, by_actor=RIGHTS_FOREIGN_KING)
        assert self.h.characters[RIGHTS_KING].province_idx is None

    # ==================================================================
    # Регрессия: by_actor=None — прежнее поведение
    # ==================================================================

    def test_none_actor_grants_fief_without_any_rights_check(self):
        # нейтральная земля и барон из чужого дукциона: без актора это как
        # раньше — землю можно выдать кому угодно и из любого герцогства
        assert self.h.revoke_fief("baron_wolf")
        events = self.h.grant_fief(RIGHTS_NEUTRAL_PROVINCE, "baron_wolf")
        assert events
        assert self.h.characters["baron_wolf"].province_idx == RIGHTS_NEUTRAL_PROVINCE
        assert self.h.characters["baron_wolf"].duchy_id == "goldfield"

    def test_none_actor_revokes_fief_without_any_rights_check(self):
        events = self.h.revoke_fief(RIGHTS_BARON)
        assert events
        assert self.h.characters[RIGHTS_BARON].province_idx is None

    def test_none_actor_still_clamps_the_contract_level(self):
        self.h.set_contract(RIGHTS_BARON, len(CONTRACT_LEVELS) + 17)
        assert self.h.contracts[RIGHTS_BARON].level == len(CONTRACT_LEVELS) - 1
        self.h.set_contract(RIGHTS_BARON, -25)
        assert self.h.contracts[RIGHTS_BARON].level == 0

    def test_none_actor_is_exactly_the_same_as_before_the_stage(self):
        # эталон «как было»: полный вызов без актора меняет ровно те поля,
        # которые менялись до этапа 1.1, и не занимает action_ledger
        before = self.fingerprint()
        self.h.revoke_fief(RIGHTS_BARON)
        self.h.grant_fief(RIGHTS_OWN_PROVINCE, RIGHTS_BARON)
        self.h.set_contract(RIGHTS_BARON, 1)
        assert self.h.action_ledger == {}, "путь без актора не тратит лимиты"
        assert self.fingerprint() != before
        assert self.h.characters[RIGHTS_BARON].province_idx == RIGHTS_OWN_PROVINCE
        assert self.h.contracts[RIGHTS_BARON].level == 1

    def test_unknown_target_stays_silent_on_all_three_methods(self):
        # «некому/нечего» — пустой список, а не объяснение
        assert self.h.grant_fief(3, "baron_ghost") == []
        assert self.h.revoke_fief("baron_ghost") == []
        assert self.h.set_contract("baron_ghost", 4) == []

    # ==================================================================
    # Актор: не существует / мёртв / мусор
    # ==================================================================

    def test_unknown_actor_is_refused_on_all_three_methods(self):
        cases = (
            lambda: self.h.grant_fief(RIGHTS_OWN_PROVINCE, RIGHTS_BARON,
                                      by_actor="duke_ghost"),
            lambda: self.h.revoke_fief(RIGHTS_BARON, by_actor="duke_ghost"),
            lambda: self.h.set_contract(RIGHTS_BARON, 3, by_actor="duke_ghost"),
        )
        for call in cases:
            self.assert_refused(call(), "актор")

    def test_dead_actor_is_refused_on_all_three_methods(self):
        self.h.characters[RIGHTS_DUKE].alive = False
        self.assert_refused(self.h.grant_fief(RIGHTS_OWN_PROVINCE, RIGHTS_BARON,
                                               by_actor=RIGHTS_DUKE), "мёртв")
        self.assert_refused(self.h.revoke_fief(RIGHTS_BARON, by_actor=RIGHTS_DUKE),
                            "мёртв")
        self.assert_refused(self.h.set_contract(RIGHTS_BARON, 3,
                                                by_actor=RIGHTS_DUKE), "мёртв")

    def test_junk_actor_is_refused_and_does_not_crash(self):
        # None — это НЕ мусор, а документированный путь «без проверки прав»
        # (его зовут старые тесты и UI), поэтому он проверяется отдельно ниже.
        # Здесь только настоящий мусор: и он обязан дать ровно ОДИН отказ.
        for junk in (7, 3.5, ["duke_lyra"], object()):
            self.assert_refused(self.h.revoke_fief(RIGHTS_BARON, by_actor=junk))

    def test_junk_actor_still_refused_while_revocation_returns_two_events(self):
        """Этап 2: отзыв теперь возвращает событие ПЕРЕДАЧИ плюс своё.

        Прежде ``_revoke_fief_now`` просто обнулял ``province_idx`` и возвращал
        одну строку. Теперь он идёт через ``transfer_county``, и журнал честно
        рассказывает, что графство освободилось, а затем — что барон лишён земли
        и какое у него мнение. Два события вместо одного — это не поломка, а
        информация; проверять «ровно одно» здесь было бы проверкой старой
        бедности лога.
        """
        assert self.h.revoke_fief(RIGHTS_BARON, by_actor=7)
        events = self.h.revoke_fief(RIGHTS_BARON)
        assert len(events) == 2, events
        assert "теряет Verdant" in events[0], events
        assert "лишён земли" in events[1], events
        again = self.h.revoke_fief(RIGHTS_BARON)
        assert len(again) == 1, "повторный отзыв ничего не передаёт"

    def test_dead_target_is_refused(self):
        self.h.characters[RIGHTS_BARON].alive = False
        self.assert_refused(self.h.grant_fief(RIGHTS_OWN_PROVINCE, RIGHTS_BARON,
                                               by_actor=RIGHTS_DUKE), "мёртв")

    # ==================================================================
    # grant_fief: земля
    # ==================================================================

    def test_grant_refused_on_a_neutral_province(self):
        self.landless(RIGHTS_BARON)
        before = self.fingerprint()
        events = self.h.grant_fief(RIGHTS_NEUTRAL_PROVINCE, RIGHTS_BARON,
                                   by_actor=RIGHTS_DUKE)
        self.assert_refused(events, "не под его властью")
        assert self.h.characters[RIGHTS_BARON].province_idx is None
        assert self.fingerprint() == before

    def test_grant_refused_on_a_province_of_another_realm(self):
        self.landless(RIGHTS_BARON)
        events = self.h.grant_fief(RIGHTS_FOREIGN_PROVINCE, RIGHTS_BARON,
                                   by_actor=RIGHTS_DUKE)
        self.assert_refused(events, "не под его властью")
        assert self.h.characters[RIGHTS_BARON].province_idx is None

    def test_grant_refuses_junk_province_instead_of_crashing(self):
        for junk in (None, -1, 999, True, "44"):
            events = self.h.grant_fief(junk, RIGHTS_BARON, by_actor=RIGHTS_DUKE)
            self.assert_refused(events)

    def test_grant_does_not_touch_province_owner(self):
        # фьеф не меняет владельца нации: доход realm'а считается по owner
        owner = self.h.provinces[RIGHTS_OWN_PROVINCE].owner
        income = self.h.realm_income("kingdom_thorn")
        self.landless(RIGHTS_BARON)
        assert self.h.grant_fief(RIGHTS_OWN_PROVINCE, RIGHTS_BARON,
                                 by_actor=RIGHTS_DUKE)
        assert self.h.provinces[RIGHTS_OWN_PROVINCE].owner == owner
        assert self.h.realm_income("kingdom_thorn") == income

    def test_successful_grant_moves_fief_duchy_and_opinion(self):
        baron = self.h.characters[RIGHTS_BARON]
        self.landless(RIGHTS_BARON)
        opinion, loyalty = baron.opinion_of_liege, baron.loyalty
        assert self.h.grant_fief(RIGHTS_OWN_PROVINCE, RIGHTS_BARON,
                                 by_actor=RIGHTS_DUKE)
        assert baron.province_idx == RIGHTS_OWN_PROVINCE
        assert baron.duchy_id == self.h.duchy_of(RIGHTS_OWN_PROVINCE) == "leafguard"
        assert baron.landless_turns == 0
        assert baron.is_ruler
        assert baron.opinion_of_liege == opinion + 20
        assert baron.loyalty == min(100, loyalty + 10)

    # ==================================================================
    # grant_fief: конфликт «у получателя уже есть графство»
    # ==================================================================

    def test_grant_refused_when_recipient_already_holds_a_fief(self):
        assert self.h.characters[RIGHTS_BARON].province_idx is not None
        events = self.h.grant_fief(RIGHTS_OWN_PROVINCE, RIGHTS_BARON,
                                   by_actor=RIGHTS_DUKE)
        self.assert_refused(events, "уже держит", "отзыв")
        assert self.h.characters[RIGHTS_BARON].province_idx == 41, "старое не тронуто"

    def test_revoke_then_grant_is_the_documented_way_to_move_a_fief(self):
        assert self.h.revoke_fief(RIGHTS_BARON, by_actor=RIGHTS_DUKE)
        assert self.h.grant_fief(RIGHTS_OWN_PROVINCE, RIGHTS_BARON,
                                 by_actor=RIGHTS_DUKE)
        assert self.h.characters[RIGHTS_BARON].province_idx == RIGHTS_OWN_PROVINCE

    def test_regranting_the_same_county_is_allowed_and_idempotent(self):
        held = self.h.characters[RIGHTS_BARON].province_idx
        assert self.h.grant_fief(held, RIGHTS_BARON, by_actor=RIGHTS_DUKE) == []
        assert self.h.characters[RIGHTS_BARON].province_idx == held

    # ==================================================================
    # set_contract: диапазон и лимит
    # ==================================================================

    def test_contract_level_out_of_range_is_refused_with_an_actor(self):
        for junk_level in (len(CONTRACT_LEVELS), 17, -1):
            events = self.h.set_contract(RIGHTS_BARON, junk_level,
                                         by_actor=RIGHTS_DUKE)
            self.assert_refused(events, "вне диапазона")
            assert self.h.contracts[RIGHTS_BARON].level == 2

    def test_contract_level_out_of_range_is_clamped_without_an_actor(self):
        # ровно то же, что до этапа 1.1: клампим, а не отказываем
        self.h.set_contract(RIGHTS_BARON, len(CONTRACT_LEVELS) + 17)
        assert self.h.contracts[RIGHTS_BARON].level == len(CONTRACT_LEVELS) - 1
        self.h.set_contract(RIGHTS_BARON, -25)
        assert self.h.contracts[RIGHTS_BARON].level == 0

    def test_contract_level_junk_is_refused_with_an_actor(self):
        for junk in (None, "high", [2], float("nan")):
            events = self.h.set_contract(RIGHTS_BARON, junk, by_actor=RIGHTS_DUKE)
            assert isinstance(events, list) and len(events) == 1, junk
        assert self.h.contracts[RIGHTS_BARON].level == 2

    def test_contract_limit_is_once_per_actor_per_turn(self):
        assert self.h.set_contract(RIGHTS_BARON, 3, by_actor=RIGHTS_DUKE)
        snapshot = self.fingerprint()
        self.assert_refused(self.h.set_contract(RIGHTS_BARON_OTHER, 1,
                                                by_actor=RIGHTS_DUKE), "этом ходу")
        assert self.fingerprint() == snapshot

    def test_contract_limit_is_per_actor_not_global(self):
        assert self.h.set_contract(RIGHTS_BARON, 3, by_actor=RIGHTS_DUKE)
        assert self.h.set_contract("baron_gray", 3, by_actor=RIGHTS_DUKE_OTHER)

    def test_contract_limit_reopens_on_the_next_turn(self):
        assert self.h.set_contract(RIGHTS_BARON, 3, by_actor=RIGHTS_DUKE)
        self.h.end_turn()
        assert self.h.set_contract(RIGHTS_BARON, 1, by_actor=RIGHTS_DUKE)

    def test_refused_contract_does_not_spend_the_allowance(self):
        self.assert_refused(self.h.set_contract(RIGHTS_BARON, 99,
                                                by_actor=RIGHTS_DUKE))
        assert self.h.set_contract(RIGHTS_BARON, 3, by_actor=RIGHTS_DUKE)

    def test_contract_by_actor_names_the_commanding_liege(self):
        self.h.set_contract(RIGHTS_BARON, 3, by_actor=RIGHTS_DUKE)
        assert self.h.contracts[RIGHTS_BARON].liege_id == RIGHTS_DUKE
        self.h.set_contract("duke_lyra", 1, by_actor=RIGHTS_KING)
        assert self.h.contracts["duke_lyra"].liege_id == RIGHTS_KING

    def test_command_is_refused_for_a_vassal_without_a_liege(self):
        # герцогство без держателя делает барона ничьим вассалом
        self.h.duchies["greymoor"].holder_id = None
        assert self.h.liege_of("baron_wolf") is None
        events = self.h.revoke_fief("baron_wolf", by_actor=RIGHTS_DUKE_OTHER)
        self.assert_refused(events, "не сюзерен")


# --------------------------------------------------------------------------
# Приказы как объект состояния (этап 1.2)
# --------------------------------------------------------------------------


class TestOrders:
    """Приказ живёт в состоянии: отказ, срок и наказание — это факты мира.

    Здесь проверяется весь цикл ``issue_order`` -> ``resolve_orders`` ->
    (``FULFILLED`` | ``REFUSED`` | ``PUNISHED``), плюс три вещи, которые легко
    испортить и которые дороже всего: детерминизм (решения не бросают кубик),
    round-trip снапшота с непустым ``orders`` и регрессия «мир без приказов
    ведёт себя ровно как раньше».
    """

    KING = "king_sigurd"
    DUKE = "duke_lyra"
    DUKE_OTHER = "duke_orso"
    BARON = "baron_thorn"
    BARON_OTHER = "baron_moss"
    PROVINCE = RIGHTS_OWN_PROVINCE       # зелёная, в leafguard
    NEUTRAL = RIGHTS_NEUTRAL_PROVINCE

    def setup_method(self):
        self.h = make_hierarchy()
        self.h.realms["kingdom_thorn"].gold = 10000
        self.h.characters[self.DUKE].gold = 10000

    # ---------------- хелперы ----------------

    def landless(self, baron_id: str) -> str:
        self.h.revoke_fief(baron_id)
        return baron_id

    def opinion(self, character_id: str) -> int:
        return self.h.characters[character_id].opinion_of_liege

    def issue(self, issuer: str, kind, target: str, args=None) -> Order:
        order = self.h.issue_order(issuer, kind, target, args)
        assert isinstance(order, Order), (issuer, kind, target, args)
        return order

    # ==================================================================
    # Модель приказа и его числа
    # ==================================================================

    def test_order_kinds_are_the_documented_seven(self):
        assert {k.value for k in OrderKind} == {
            "grant_fief", "revoke_fief", "set_contract", "summon_council",
            "raise_levy", "develop_county", "gift_vassal",
        }

    def test_order_statuses_are_the_documented_five(self):
        assert {s.value for s in OrderStatus} == {
            "pending", "accepted", "refused", "fulfilled", "punished",
        }

    def test_weights_table_is_the_documented_one(self):
        assert ORDER_WEIGHTS == {
            OrderKind.GIFT: 1,
            OrderKind.SUMMON_COUNCIL: 1,
            OrderKind.GRANT_FIEF: 2,
            OrderKind.DEVELOP_COUNTY: 2,
            OrderKind.SET_CONTRACT: 2,
            OrderKind.REVOKE_FIEF: 4,
            OrderKind.RAISE_LEVY: 5,
        }

    def test_refusal_penalty_is_the_base_weight_times_the_kind_weight(self):
        # штраф за отказ — это REFUSED_WEIGHT * вес вида приказа, а не таблица
        assert REFUSED_WEIGHT == 5
        for kind, weight in ORDER_WEIGHTS.items():
            order = Order(id="x", kind=kind, issuer_id="a", target_id="b",
                          turn_issued=1)
            assert order.weight == weight
            assert order.refusal_penalty == REFUSED_WEIGHT * weight

    def test_gift_is_forgiven_easier_than_a_levy_raising(self):
        # ключевое обещание модели: мелкий приказ прощают легче тяжёлого
        gift = self.issue(self.KING, OrderKind.GIFT, self.DUKE)
        levy = self.issue(self.KING, OrderKind.RAISE_LEVY, self.DUKE,
                          {"blocks": 1})
        assert gift.refusal_penalty < levy.refusal_penalty
        assert gift.refusal_penalty == 5
        assert levy.refusal_penalty == 25

    def test_refusal_threshold_ladder_starts_at_the_floor_and_widens(self):
        assert (ORDER_REFUSAL_FLOOR, ORDER_REFUSAL_STEP) == (-10, 5)
        assert order_refusal_threshold(OrderKind.GIFT) == -10
        assert order_refusal_threshold(OrderKind.SET_CONTRACT) == -15
        assert order_refusal_threshold("raise_the_siege") == -20
        assert order_refusal_threshold(OrderKind.REVOKE_FIEF) == -25
        assert order_refusal_threshold(OrderKind.RAISE_LEVY) == -30

    def test_order_kind_of_accepts_object_name_and_value(self):
        assert order_kind_of(OrderKind.GIFT) is OrderKind.GIFT
        assert order_kind_of("GIFT") is OrderKind.GIFT
        assert order_kind_of("gift_vassal") is OrderKind.GIFT
        assert order_kind_of("raise a levy") is None
        assert order_kind_of(None) is None
        assert order_kind_of(7) is None

    def test_order_weight_of_an_unknown_string_is_the_default_middle(self):
        assert ORDER_DEFAULT_WEIGHT == 3
        assert order_weight("raise_the_siege") == ORDER_DEFAULT_WEIGHT
        assert order_weight(None) == ORDER_DEFAULT_WEIGHT

    def test_clean_order_args_keeps_scalars_and_drops_junk(self):
        cleaned = clean_order_args({"province_idx": 44, "level": 3,
                                    "flag": True, "name": "x",
                                    "weird": {"nested": 1}, "list": [1],
                                    "nan": float("nan"), 7: "int key"})
        assert cleaned == {"province_idx": 44, "level": 3, "flag": True,
                           "name": "x", "7": "int key"}
        assert clean_order_args("not a dict") == {}

    # ==================================================================
    # can_accept_order наконец использует параметр order
    # ==================================================================

    def test_can_accept_order_depends_on_the_order_weight(self):
        # -20: подарок (вес 1, порог -10) отвергнут, левейс (вес 5, порог -30)
        # принят — при одном и том же мнении
        self.h.realms["kingdom_thorn"].crown_authority = 2
        self.h.characters[self.DUKE].opinion_of_liege = -20
        assert not self.h.can_accept_order(self.DUKE, OrderKind.GIFT)
        assert self.h.can_accept_order(self.DUKE, OrderKind.RAISE_LEVY)

    def test_can_accept_order_forgives_a_gift_deeper_than_a_levy_raising(self):
        self.h.realms["kingdom_thorn"].crown_authority = 2
        self.h.characters[self.DUKE].opinion_of_liege = -9
        assert self.h.can_accept_order(self.DUKE, OrderKind.GIFT)
        self.h.characters[self.DUKE].opinion_of_liege = -29
        assert self.h.can_accept_order(self.DUKE, OrderKind.RAISE_LEVY)

    def test_can_accept_order_still_answers_for_legacy_string_calls(self):
        # 308 старых тестов зовут can_accept_order(vassal, "raise_the_siege"):
        # при нулевом мнении любой приказ принимается, как и раньше
        self.h.characters[self.BARON].opinion_of_liege = 0
        assert self.h.can_accept_order(self.BARON, "raise_the_siege")
        self.h.characters[self.BARON].opinion_of_liege = -70
        assert not self.h.can_accept_order(self.BARON, "raise_the_siege")
        self.h.characters[self.BARON].alive = False
        assert not self.h.can_accept_order(self.BARON, OrderKind.GIFT)

    # ==================================================================
    # issue_order
    # ==================================================================

    def test_issue_order_creates_a_pending_order_in_the_registry(self):
        order = self.issue(self.DUKE, OrderKind.SUMMON_COUNCIL, self.BARON)
        assert order.status is OrderStatus.PENDING
        assert order.resolved_turn is None
        assert order.issuer_id == self.DUKE
        assert order.target_id == self.BARON
        assert order.turn_issued == self.h.turn
        assert self.h.orders[order.id] is order
        assert order.is_open

    def test_issue_order_does_not_apply_anything_yet(self):
        # приказ только выдан: контракт и земля не тронуты до решения
        opinion = self.opinion(self.BARON)
        self.issue(self.DUKE, OrderKind.SET_CONTRACT, self.BARON, {"level": 3})
        assert self.h.contracts[self.BARON].level == 2
        assert self.opinion(self.BARON) == opinion

    def test_issue_order_needs_the_right_to_command(self):
        assert self.h.issue_order("king_erik", OrderKind.SUMMON_COUNCIL,
                                  self.BARON) is None
        assert self.h.issue_order(self.BARON, OrderKind.SUMMON_COUNCIL,
                                  self.BARON_OTHER) is None
        assert self.h.issue_order(self.KING, OrderKind.SUMMON_COUNCIL,
                                  self.KING) is None
        assert self.h.orders == {}

    def test_issue_order_refuses_a_dead_actor(self):
        self.h.characters[self.DUKE].alive = False
        assert self.h.issue_order(self.DUKE, OrderKind.SUMMON_COUNCIL,
                                  self.BARON) is None

    def test_issue_order_refuses_an_unknown_kind_or_target(self):
        assert self.h.issue_order(self.DUKE, "raise a levy", self.BARON) is None
        assert self.h.issue_order(self.DUKE, OrderKind.GIFT, "baron_ghost") is None
        assert self.h.issue_order(self.DUKE, OrderKind.GIFT, None) is None

    def test_issue_order_refuses_a_fief_in_land_the_issuer_does_not_own(self):
        assert self.h.issue_order(self.DUKE, OrderKind.GRANT_FIEF, self.BARON,
                                  {"province_idx": self.NEUTRAL}) is None
        assert self.h.issue_order(self.DUKE, OrderKind.GRANT_FIEF, self.BARON,
                                  {"province_idx": RIGHTS_FOREIGN_PROVINCE}) is None
        assert self.h.issue_order(self.DUKE, OrderKind.GRANT_FIEF, self.BARON,
                                  {"province_idx": "many"}) is None
        self.landless(self.BARON)
        assert self.issue(self.DUKE, OrderKind.GRANT_FIEF, self.BARON,
                          {"province_idx": self.PROVINCE})

    def test_issue_order_refuses_a_fief_to_someone_who_already_has_one(self):
        assert self.h.issue_order(self.DUKE, OrderKind.GRANT_FIEF, self.BARON,
                                  {"province_idx": self.PROVINCE}) is None

    def test_issue_order_refuses_a_contract_level_out_of_range(self):
        assert self.h.issue_order(self.DUKE, OrderKind.SET_CONTRACT, self.BARON,
                                  {"level": 99}) is None
        assert self.h.issue_order(self.DUKE, OrderKind.SET_CONTRACT, self.BARON,
                                  {"level": "high"}) is None
        assert self.issue(self.DUKE, OrderKind.SET_CONTRACT, self.BARON,
                          {"level": 3})

    def test_issue_order_refuses_a_revocation_of_nothing(self):
        self.landless(self.BARON)
        assert self.h.issue_order(self.DUKE, OrderKind.REVOKE_FIEF, self.BARON) is None
        assert self.issue(self.DUKE, OrderKind.GIFT, self.BARON)

    def test_issue_order_refuses_a_levy_from_a_non_king(self):
        # левейс поднимает правитель realm'а, поэтому герцог его не поднимет
        assert self.h.issue_order(self.DUKE, OrderKind.RAISE_LEVY, self.BARON,
                                  {"blocks": 1}) is None
        assert self.h.issue_order(self.KING, OrderKind.RAISE_LEVY, self.DUKE,
                                  {"blocks": 0}) is None
        assert self.h.issue_order(self.KING, OrderKind.RAISE_LEVY, self.DUKE,
                                  {"blocks": 1,
                                   "realm_id": "kingdom_ember"}) is None
        assert self.issue(self.KING, OrderKind.RAISE_LEVY, self.DUKE, {"blocks": 1})

    def test_issue_order_refuses_development_ordered_by_a_vaudal_duke(self):
        # застройку платит казна realm'а, а тратить её может только правитель
        assert self.h.issue_order(self.DUKE, OrderKind.DEVELOP_COUNTY, self.BARON,
                                  {"province_idx": 43}) is None
        assert self.h.issue_order(self.KING, OrderKind.DEVELOP_COUNTY, self.DUKE,
                                  {"province_idx": self.NEUTRAL}) is None
        assert self.issue(self.KING, OrderKind.DEVELOP_COUNTY, self.DUKE,
                          {"province_idx": 43})

    def test_issue_order_limit_is_two_per_kind_per_turn(self):
        assert ORDERS_ISSUED_PER_TURN == 2
        first = self.issue(self.DUKE, OrderKind.GIFT, self.BARON)
        second = self.issue(self.DUKE, OrderKind.GIFT, self.BARON_OTHER)
        assert first.id != second.id
        # третий приказ того же вида в том же ходу — отказ, даже если он
        # адресован тому же вассалу, что и первый
        assert self.h.issue_order(self.DUKE, OrderKind.GIFT, self.BARON) is None
        # другой вид приказа — независимый счётчик
        assert self.issue(self.DUKE, OrderKind.SUMMON_COUNCIL, self.BARON)
        assert len(self.h.orders) == 3

    def test_issue_order_limit_is_per_actor_not_global(self):
        self.issue(self.DUKE, OrderKind.GIFT, self.BARON)
        self.issue(self.DUKE, OrderKind.GIFT, self.BARON_OTHER)
        assert self.h.issue_order(self.DUKE, OrderKind.GIFT, self.BARON) is None
        assert self.issue(self.DUKE_OTHER, OrderKind.GIFT, "baron_gray")

    def test_issue_order_limit_reopens_on_the_next_turn(self):
        self.issue(self.DUKE, OrderKind.GIFT, self.BARON)
        self.issue(self.DUKE, OrderKind.GIFT, self.BARON_OTHER)
        assert self.h.issue_order(self.DUKE, OrderKind.GIFT, self.BARON) is None
        self.h.end_turn()
        assert self.issue(self.DUKE, OrderKind.GIFT, self.BARON)

    def test_order_ids_are_deterministic_and_unique(self):
        ids = [self.issue(self.DUKE, OrderKind.GIFT, self.BARON).id,
               self.issue(self.DUKE, OrderKind.GIFT, self.BARON_OTHER).id]
        assert ids == [f"order_{self.h.turn}_0", f"order_{self.h.turn}_1"]

    def test_order_of_returns_the_latest_open_order_of_a_vassal(self):
        assert self.h.order_of(self.BARON) is None
        first = self.issue(self.DUKE, OrderKind.GIFT, self.BARON)
        second = self.issue(self.DUKE, OrderKind.SUMMON_COUNCIL, self.BARON)
        assert self.h.order_of(self.BARON) is second
        self.h.resolve_orders()
        # принятый приказ всё ещё открыт: он ждёт своего срока
        assert self.h.order_of(self.BARON) is second
        self.h.punish_order(first.id)
        assert self.h.order_of(self.BARON) is second
        for _ in range(ORDER_DEADLINE_TURNS + 1):
            self.h.end_turn()
        assert self.h.order_of(self.BARON) is None
        assert self.h.order_of("nobody") is None

    # ==================================================================
    # resolve_orders: решение вассала
    # ==================================================================

    def test_resolve_orders_is_silent_when_there_are_no_orders(self):
        assert self.h.orders == {}
        assert self.h.resolve_orders() == []
        self.h.end_turn()
        assert self.h.orders == {}

    def test_resolve_orders_accepts_a_loved_order(self):
        order = self.issue(self.DUKE, OrderKind.SUMMON_COUNCIL, self.BARON)
        events = self.h.resolve_orders()
        assert order.status is OrderStatus.ACCEPTED
        assert order.resolved_turn == self.h.turn
        assert any(order.id in e for e in events)

    def test_resolve_orders_refuses_and_costs_opinion(self):
        order = self.issue(self.DUKE, OrderKind.SUMMON_COUNCIL, self.BARON)
        self.h.characters[self.BARON].opinion_of_liege = -20
        before = self.opinion(self.BARON)
        events = self.h.resolve_orders()
        assert order.status is OrderStatus.REFUSED
        assert self.opinion(self.BARON) == before - order.refusal_penalty
        assert any("отказ" in e for e in events)

    def test_heavier_orders_cost_more_opinion_on_refusal(self):
        # одинаковое мнение и одинаковый порог отказа — разная цена отказа
        self.h.realms["kingdom_thorn"].crown_authority = 2
        self.h.characters[self.DUKE].opinion_of_liege = -35
        self.h.characters[self.DUKE_OTHER].opinion_of_liege = -35
        gift = self.issue(self.KING, OrderKind.GIFT, self.DUKE_OTHER)
        levy = self.issue(self.KING, OrderKind.RAISE_LEVY, self.DUKE,
                          {"blocks": 1})
        self.h.resolve_orders()
        assert gift.status is OrderStatus.REFUSED
        assert levy.status is OrderStatus.REFUSED
        # -35 - 25 = -60 за отказ от левейса и -35 - 5 = -40 за отказ от подарка
        assert self.opinion(self.DUKE) == -35 - levy.refusal_penalty == -60
        assert self.opinion(self.DUKE_OTHER) == -35 - gift.refusal_penalty == -40
        assert gift.refusal_penalty < levy.refusal_penalty

    def test_order_of_a_dead_vassal_is_closed_without_an_opinion_penalty(self):
        order = self.issue(self.DUKE, OrderKind.GIFT, self.BARON)
        self.h.characters[self.BARON].alive = False
        opinion = self.opinion(self.BARON)
        self.h.resolve_orders()
        assert order.status is OrderStatus.REFUSED
        assert order.message == "приказ снят: сюзерен или вассал мёртв"
        assert self.opinion(self.BARON) == opinion, "виноватых нет — штрафа нет"

    def test_resolve_orders_is_idempotent_for_closed_orders(self):
        order = self.issue(self.DUKE, OrderKind.SUMMON_COUNCIL, self.BARON)
        first = self.h.resolve_orders()
        opinion = self.opinion(self.BARON)
        assert first, "первый разбор обязан что-то вернуть"
        assert self.h.resolve_orders() == []
        assert order.status is OrderStatus.ACCEPTED
        assert self.opinion(self.BARON) == opinion

    def test_resolve_orders_accepts_a_str_kind_as_well_as_the_enum(self):
        order = self.issue(self.DUKE, "summon_council", self.BARON)
        assert order.kind is OrderKind.SUMMON_COUNCIL

    # ==================================================================
    # Срок приказа и его исполнение
    # ==================================================================

    def test_accepted_order_waits_its_deadline_before_it_is_applied(self):
        self.landless(self.BARON)
        order = self.issue(self.DUKE, OrderKind.GRANT_FIEF, self.BARON,
                           {"province_idx": self.PROVINCE})
        self.h.end_turn()
        assert order.status is OrderStatus.ACCEPTED
        assert self.h.characters[self.BARON].province_idx is None
        self.h.end_turn()
        assert order.status is OrderStatus.ACCEPTED
        assert self.h.characters[self.BARON].province_idx is None
        self.h.end_turn()
        assert order.status is OrderStatus.FULFILLED
        assert order.resolved_turn == 3, "приказ хода 1 исполняется на границе 1+2"
        assert self.h.characters[self.BARON].province_idx == self.PROVINCE

    def test_deadline_is_the_documented_number_of_turns(self):
        # приказ хода 1: решение на границе 1, исполнение на границе 1 + DEADLINE
        assert ORDER_DEADLINE_TURNS == 2
        order = self.issue(self.DUKE, OrderKind.SUMMON_COUNCIL, self.BARON)
        self.h.end_turn()
        assert order.status is OrderStatus.ACCEPTED
        for _ in range(ORDER_DEADLINE_TURNS):
            assert order.status is not OrderStatus.FULFILLED
            self.h.end_turn()
        assert order.status is OrderStatus.FULFILLED

    def test_fulfilled_order_really_applied_the_effect(self):
        order = self.issue(self.DUKE, OrderKind.SET_CONTRACT, self.BARON,
                           {"level": 3})
        for _ in range(ORDER_DEADLINE_TURNS + 1):
            self.h.end_turn()
        assert order.status is OrderStatus.FULFILLED
        assert self.h.contracts[self.BARON].level == 3
        assert self.opinion(self.BARON) < 20

    def test_fulfilled_council_order_really_gave_the_bonuses(self):
        order = self.issue(self.DUKE, OrderKind.SUMMON_COUNCIL, self.BARON)
        baron = self.h.characters[self.BARON]
        influence, loyalty = baron.influence, baron.loyalty
        for _ in range(ORDER_DEADLINE_TURNS + 1):
            self.h.end_turn()
        assert order.status is OrderStatus.FULFILLED
        # влияние никто, кроме совета, не трогает — оно проверяется точно;
        # лояльность же каждый ход подтягивает к своему равновесию tick_vassals,
        # поэтому проверяем только знак прироста
        assert baron.influence == influence + COUNCIL_INFLUENCE
        assert baron.loyalty > loyalty

    def test_order_application_rechecks_the_rights_at_the_moment_it_runs(self):
        # пока приказ висел, провинция сменила владельца — приказ обязан
        # закрыться как «не исполнен», а не выдать чужую землю
        self.landless(self.BARON)
        order = self.issue(self.DUKE, OrderKind.GRANT_FIEF, self.BARON,
                           {"province_idx": self.PROVINCE})
        self.h.end_turn()
        self.h.provinces[self.PROVINCE].owner = "red"
        for _ in range(ORDER_DEADLINE_TURNS):
            self.h.end_turn()
        assert order.status is OrderStatus.FULFILLED
        assert order.message == "не исполнен"
        assert self.h.characters[self.BARON].province_idx is None

    # ==================================================================
    # Наказание за неисполнение
    # ==================================================================

    def test_punish_order_marks_punished_and_costs_opinion_and_loyalty(self):
        order = self.issue(self.DUKE, OrderKind.SUMMON_COUNCIL, self.BARON)
        self.h.end_turn()
        assert order.status is OrderStatus.ACCEPTED
        baron = self.h.characters[self.BARON]
        opinion, loyalty = self.opinion(self.BARON), baron.loyalty
        events = self.h.punish_order(order.id, by_actor=self.DUKE)
        assert events
        assert order.status is OrderStatus.PUNISHED
        assert order.resolved_turn == self.h.turn
        assert self.opinion(self.BARON) == opinion + PUNISHED_OPINION
        assert baron.loyalty == max(0, loyalty - PUNISHED_LOYALTY)

    def test_non_fulfilment_costs_more_than_the_heaviest_refusal(self):
        assert abs(PUNISHED_OPINION) > REFUSED_WEIGHT * max(ORDER_WEIGHTS.values())
        assert PUNISHED_LOYALTY == 20

    def test_punished_order_is_not_applied_anymore(self):
        self.landless(self.BARON)
        order = self.issue(self.DUKE, OrderKind.GRANT_FIEF, self.BARON,
                           {"province_idx": self.PROVINCE})
        self.h.end_turn()
        self.h.punish_order(order.id)
        for _ in range(ORDER_DEADLINE_TURNS):
            self.h.end_turn()
        assert order.status is OrderStatus.PUNISHED
        assert self.h.characters[self.BARON].province_idx is None

    def test_punish_order_refused_for_a_foreign_actor(self):
        order = self.issue(self.DUKE, OrderKind.SUMMON_COUNCIL, self.BARON)
        self.h.end_turn()
        before = self.h.state_fingerprint()
        events = self.h.punish_order(order.id, by_actor="king_erik")
        assert isinstance(events, list) and len(events) == 1
        assert order.status is OrderStatus.ACCEPTED
        assert self.h.state_fingerprint() == before

    def test_punish_order_refused_when_the_order_is_not_accepted(self):
        pending = self.issue(self.DUKE, OrderKind.SUMMON_COUNCIL, self.BARON)
        events = self.h.punish_order(pending.id)
        assert isinstance(events, list) and len(events) == 1
        assert pending.status is OrderStatus.PENDING
        assert self.h.punish_order("order_1_999") == []

    # ==================================================================
    # Совет
    # ==================================================================

    def test_summon_council_gives_influence_and_loyalty(self):
        baron = self.h.characters[self.BARON]
        influence, loyalty = baron.influence, baron.loyalty
        events = self.h.summon_council(self.DUKE, self.BARON)
        assert events
        assert baron.influence == influence + COUNCIL_INFLUENCE
        assert baron.loyalty == loyalty + COUNCIL_LOYALTY

    def test_summon_council_costs_no_gold(self):
        # совет — не подарок: казна сюзерена не тратится
        purse = self.h.purse_of(self.h.characters[self.DUKE])
        self.h.summon_council(self.DUKE, self.BARON)
        assert self.h.purse_of(self.h.characters[self.DUKE]) == purse

    def test_summon_council_is_capped_at_the_top(self):
        baron = self.h.characters[self.BARON]
        baron.influence, baron.loyalty = 99, 99
        self.h.summon_council(self.DUKE, self.BARON)
        assert (baron.influence, baron.loyalty) == (100, 100)

    def test_summon_council_refused_for_a_foreign_liege_and_for_a_king(self):
        for call in (lambda: self.h.summon_council("king_erik", self.BARON),
                     lambda: self.h.summon_council(self.BARON, self.BARON_OTHER),
                     lambda: self.h.summon_council(self.KING, self.KING)):
            assert isinstance(call(), list) and len(call()) == 1
        assert self.h.summon_council(self.DUKE, "baron_ghost") == []
        assert self.h.characters[self.BARON].influence == 10, "отказ не награждает"

    def test_refused_council_order_costs_the_least_opinion_of_all(self):
        assert COUNCIL_INFLUENCE == 5 and COUNCIL_LOYALTY == 10
        council = self.issue(self.DUKE, OrderKind.SUMMON_COUNCIL, self.BARON)
        self.h.characters[self.BARON].opinion_of_liege = -20
        before = self.opinion(self.BARON)
        self.h.resolve_orders()
        assert council.status is OrderStatus.REFUSED
        assert before - self.opinion(self.BARON) == REFUSED_WEIGHT
        assert council.refusal_penalty == min(ORDER_WEIGHTS.values()) * REFUSED_WEIGHT

    # ==================================================================
    # end_turn: разбор приказов без поломки старого поведения
    # ==================================================================

    def test_end_turn_resolves_orders_when_they_exist(self):
        order = self.issue(self.DUKE, OrderKind.SUMMON_COUNCIL, self.BARON)
        events = self.h.end_turn()
        assert order.status is OrderStatus.ACCEPTED
        assert any(order.id in e for e in events)
        assert any(order.id in e for e in self.h.log)

    def test_end_turn_without_orders_is_unchanged_and_clears_the_ledger(self):
        self.h.develop_county(43, actor_id=self.KING)
        assert self.h.action_ledger
        events = self.h.end_turn()
        assert not any("приказ" in e for e in events)
        assert self.h.orders == {}
        assert self.h.action_ledger == {}, "граница хода — пустой журнал лимитов"

    def test_order_execution_does_not_spend_the_command_allowance(self):
        # приказ исполняется приказом сюзерена, но «раз в ход» относится к
        # живой кнопке: иначе ранее выданный приказ был бы неисполним из-за
        # того, что герцог уже кликнул ту же кнопку
        self.issue(self.DUKE, OrderKind.SET_CONTRACT, self.BARON, {"level": 3})
        self.h.set_contract(self.BARON_OTHER, 1, by_actor=self.DUKE)
        for _ in range(ORDER_DEADLINE_TURNS + 1):
            self.h.end_turn()
        assert self.h.contracts[self.BARON].level == 3, "приказ исполнен несмотря на лимит"
        assert self.h.contracts[self.BARON_OTHER].level == 1

    def test_resolve_orders_never_touches_the_dice(self):
        self.issue(self.DUKE, OrderKind.SUMMON_COUNCIL, self.BARON)
        self.issue(self.KING, OrderKind.RAISE_LEVY, self.DUKE, {"blocks": 1})
        for _ in range(ORDER_DEADLINE_TURNS + 2):
            self.h.end_turn()
        assert len(self.h.streams) == 0, "решение по приказу не бросает кубик"
        assert self.h.streams.consumed("anything") == 0

    def test_summary_keys_are_unchanged_by_orders(self):
        before = set(self.h.summary())
        self.issue(self.DUKE, OrderKind.SUMMON_COUNCIL, self.BARON)
        for _ in range(ORDER_DEADLINE_TURNS + 1):
            self.h.end_turn()
        assert set(self.h.summary()) == before == {"turn", "realms", "duchies",
                                                   "characters"}

    # ==================================================================
    # Детерминизм
    # ==================================================================

    def order_chatter(self, hierarchy: Hierarchy) -> None:
        """Одинаковая переписка приказов для двух независимых миров."""
        hierarchy.realms["kingdom_thorn"].gold = 10000
        hierarchy.characters["duke_lyra"].gold = 10000
        hierarchy.revoke_fief("baron_thorn")
        hierarchy.issue_order("duke_lyra", OrderKind.GRANT_FIEF, "baron_thorn",
                              {"province_idx": 44})
        hierarchy.issue_order("king_sigurd", OrderKind.SET_CONTRACT, "duke_lyra",
                              {"level": 3})
        hierarchy.issue_order("king_sigurd", OrderKind.SUMMON_COUNCIL, "duke_lyra")
        hierarchy.issue_order("duke_lyra", OrderKind.GIFT, "baron_moss")
        hierarchy.issue_order("king_sigurd", OrderKind.RAISE_LEVY, "duke_lyra",
                              {"blocks": 1})
        hierarchy.characters["duke_lyra"].opinion_of_liege = -35
        for _ in range(6):
            hierarchy.end_turn()

    def test_two_worlds_with_the_same_orders_hash_equal(self):
        first, second = make_hierarchy(), make_hierarchy()
        self.order_chatter(first)
        self.order_chatter(second)
        assert first.state_fingerprint() == second.state_fingerprint()
        assert [o.status for o in first.orders.values()] == \
            [o.status for o in second.orders.values()]

    def test_end_turn_events_are_identical_for_identical_orders(self):
        first, second = make_hierarchy(), make_hierarchy()
        collected = []
        for hierarchy in (first, second):
            hierarchy.issue_order("king_sigurd", OrderKind.SUMMON_COUNCIL,
                                  "duke_lyra")
            hierarchy.issue_order("king_sigurd", OrderKind.RAISE_LEVY, "duke_lyra",
                                  {"blocks": 1})
            hierarchy.characters["duke_lyra"].opinion_of_liege = -35
            events = []
            for _ in range(4):
                events += hierarchy.end_turn()
            collected.append(events)
        assert collected[0] == collected[1]
        assert any("отказ" in e for e in collected[0])

    def test_orders_do_not_depend_on_the_issue_order_of_the_same_kind(self):
        # два мира, где приказы выданы в разном порядке, обязаны разойтись:
        # порядок выдачи влияет на мир (id приказа, журнал лимитов)
        first, second = make_hierarchy(), make_hierarchy()
        first.issue_order("duke_lyra", OrderKind.GIFT, "baron_thorn")
        first.issue_order("duke_lyra", OrderKind.SUMMON_COUNCIL, "baron_thorn")
        second.issue_order("duke_lyra", OrderKind.SUMMON_COUNCIL, "baron_thorn")
        second.issue_order("duke_lyra", OrderKind.GIFT, "baron_thorn")
        assert first.state_fingerprint() != second.state_fingerprint()

    def test_thirty_turns_without_orders_still_hash_equal(self):
        first, second = make_hierarchy(), make_hierarchy()
        for _ in range(30):
            first.end_turn()
            second.end_turn()
        assert first.state_fingerprint() == second.state_fingerprint()
        assert first.orders == second.orders == {}
        assert len(first.streams) == 0, "ход не должен был потратить ни одного броска"

    def test_fingerprint_tracks_an_issued_order(self):
        hierarchy = make_hierarchy()
        before = hierarchy.state_fingerprint()
        hierarchy.issue_order("king_sigurd", OrderKind.SUMMON_COUNCIL, "duke_lyra")
        assert hierarchy.state_fingerprint() != before, \
            "выданный приказ — это состояние мира, а не строка в логе"

    # ==================================================================
    # Снапшот
    # ==================================================================

    def test_order_snapshot_has_exactly_the_documented_fields(self):
        self.issue(self.DUKE, OrderKind.SET_CONTRACT, self.BARON, {"level": 3})
        self.issue(self.KING, OrderKind.SUMMON_COUNCIL, self.DUKE)
        snapshot = self.h.to_state()
        assert set(snapshot) == SNAPSHOT_KEYS
        assert len(snapshot["orders"]) == 2
        for order_id, data in snapshot["orders"].items():
            assert set(data) == {"id", "kind", "issuer_id", "target_id",
                                 "turn_issued", "args", "status",
                                 "resolved_turn", "message"}, order_id
            assert data["id"] == order_id
        assert snapshot["orders"][f"order_{self.h.turn}_0"]["kind"] == "set_contract"
        assert snapshot["orders"][f"order_{self.h.turn}_1"]["args"] == {}

    def test_order_args_in_the_snapshot_are_a_copy_not_the_live_dict(self):
        order = self.issue(self.DUKE, OrderKind.SET_CONTRACT, self.BARON,
                           {"level": 3})
        snapshot = self.h.to_state()
        snapshot["orders"][order.id]["args"]["level"] = 99
        assert order.args["level"] == 3

    def test_round_trip_with_orders_preserves_the_fingerprint(self):
        self.order_chatter(self.h)
        assert self.h.orders
        restored = Hierarchy.from_state(self.h.to_state(), copy_provinces())
        assert restored.state_fingerprint() == self.h.state_fingerprint()

    def test_json_round_trip_with_orders_preserves_the_fingerprint(self):
        self.order_chatter(self.h)
        restored = Hierarchy.from_state(loads(dumps(self.h.to_state())),
                                        copy_provinces())
        assert restored.state_fingerprint() == self.h.state_fingerprint()
        assert set(restored.orders) == set(self.h.orders)

    def test_restored_orders_keep_their_status_and_continue_the_numbering(self):
        self.order_chatter(self.h)
        restored = Hierarchy.from_state(self.h.to_state(), copy_provinces())
        for order_id, order in self.h.orders.items():
            twin = restored.orders[order_id]
            assert twin.status is order.status
            assert twin.kind is order.kind
            assert twin.args == order.args
            assert twin.resolved_turn == order.resolved_turn
            assert twin.message == order.message
        # счётчик id продолжается, а не начинается заново: иначе новый приказ
        # занял бы уже занятый id
        fresh = restored.issue_order("king_sigurd", OrderKind.GIFT, "duke_lyra")
        assert fresh.id == f"order_{restored.turn}_{len(self.h.orders)}"

    def test_from_state_survives_a_broken_orders_block(self):
        state = self.h.to_state()
        state["orders"] = {"broken": {"kind": "raise a levy", "status": "???"}}
        restored = Hierarchy.from_state(state, copy_provinces())
        # неисполнимый вид приказа теряется, а не роняет загрузку
        assert restored.orders == {}

    def test_from_state_falls_back_on_a_broken_order_status(self):
        state = self.h.to_state()
        state["orders"] = {"order_1_0": {"kind": "gift_vassal", "status": "wat",
                                         "turn_issued": "4"}}
        restored = Hierarchy.from_state(state, copy_provinces())
        order = restored.orders["order_1_0"]
        assert order.status is OrderStatus.PENDING
        assert order.turn_issued == 4
        assert order.args == {}

    def test_from_state_without_orders_key_loads_an_empty_registry(self):
        state = self.h.to_state()
        del state["orders"]
        restored = Hierarchy.from_state(state, copy_provinces())
        assert restored.orders == {}
        assert restored.state_fingerprint() == self.h.state_fingerprint()

    def test_orders_stay_out_of_the_snapshot_of_the_action_ledger(self):
        # action_ledger живёт по тем же правилам, что и до этапа: не в снапшоте
        # и обнуляется на границе хода
        self.issue(self.DUKE, OrderKind.GIFT, self.BARON)
        assert self.h.action_ledger
        state = self.h.to_state()
        assert "action_ledger" not in all_keys(state)
        self.h.end_turn()
        assert self.h.action_ledger == {}

# --------------------------------------------------------------------------
# Этап 2: передача владений (de jure vs de facto)
# --------------------------------------------------------------------------


class TestTransferCounty:
    """``transfer_county`` — единственная точка смены владельца графства.

    Контракт, который здесь защищается:

    * ``province.owner`` меняется на ``new_nation``;
    * прежний держатель теряет ``province_idx`` и становится безземельным;
    * новый держатель получает графство, а его ``duchy_id`` пересчитывается;
    * ``contracts[id].liege_id`` пересчитывается — «вассал по контракту» и
      «вассал по ``liege_of``» обязаны быть одним человеком;
    * ``de_facto_holder_id`` пересчитывается у прежнего и нового герцогства;
    * прежний держатель НЕ теряет ``duchy_id``;
    * мусор на входе не меняет состояние.
    """

    def setup_method(self):
        self.h = make_hierarchy()
        # 41 — Verdant, зелёная, в leafguard, её держит baron_thorn
        self.county = 41
        self.holder = self.h.characters["baron_thorn"]

    def test_owner_follows_the_new_nation(self):
        events = self.h.transfer_county(self.county, "red", "baron_scar",
                                        cause="захват на карте")
        assert self.h.provinces[self.county].owner == "red"
        assert self.h.characters["baron_scar"].province_idx == self.county
        assert any("захват на карте" in e for e in events), events

    def test_previous_holder_becomes_landless(self):
        assert self.holder.province_idx == self.county
        self.h.transfer_county(self.county, "red", None)
        assert self.holder.province_idx is None
        assert self.holder.landless_turns == 0
        assert not self.holder.is_ruler

    def test_landless_holder_starts_losing_opinion(self):
        before = self.holder.opinion_of_liege
        self.h.transfer_county(self.county, "red", None)
        self.h.tick_vassals()
        assert self.holder.landless_turns == 1
        assert self.holder.opinion_of_liege == before - LANDLESS_OPINION_DECAY

    def test_previous_holder_keeps_his_duchy(self):
        self.h.transfer_county(self.county, "red", None)
        assert self.holder.duchy_id == "leafguard", \
            "потеря графства не должна выкидывать из дукции"

    def test_new_holder_duchy_is_recomputed(self):
        assert self.h.characters["baron_wolf"].duchy_id == "greymoor"
        self.h.transfer_county(self.county, "red", "baron_wolf")
        assert self.h.characters["baron_wolf"].duchy_id == "leafguard"

    def test_holder_of_a_duchy_keeps_his_duchy_when_given_a_county(self):
        # подарок графства герцогу НЕ отнимает дукцию: иначе все его бароны
        # осиротели бы через liege_of
        duke = self.h.characters["duke_lyra"]
        self.h.transfer_county(44, duke.nation, duke.id)
        assert duke.duchy_id == "leafguard"
        assert self.h.duchies["leafguard"].holder_id == "duke_lyra"
        assert {c.id for c in self.h.vassals_of("duke_lyra")} == \
            {"baron_thorn", "baron_moss"}

    def test_contract_liege_is_recomputed_for_the_new_holder(self):
        # baron_thorn был вассалом duke_lyra; переносим его в greymoor
        self.h.transfer_county(37, "green", "baron_thorn")
        assert self.h.characters["baron_thorn"].duchy_id == "greymoor"
        liege = self.h.liege_of("baron_thorn")
        assert liege is not None and liege.id == "duke_orso"
        assert self.h.contracts["baron_thorn"].liege_id == liege.id

    def test_contract_liege_is_recomputed_for_the_previous_holder(self):
        # прежний держатель теряет графство, но остаётся вассалом своего герцога,
        # поэтому контракт у него сохраняется — терять его было бы ошибкой
        self.h.transfer_county(self.county, "red", None)
        assert self.holder.province_idx is None
        assert self.h.contracts["baron_thorn"].liege_id == "duke_lyra"
        assert self.h.liege_of("baron_thorn").id == "duke_lyra"

    def test_contract_is_dropped_when_there_is_no_liege(self):
        # goldfield не имеет герцога — сюзерена нет, значит и контракта нет
        self.h.transfer_county(47, "green", "baron_thorn")
        assert self.h.characters["baron_thorn"].duchy_id == "goldfield"
        assert self.h.liege_of("baron_thorn") is None
        assert "baron_thorn" not in self.h.contracts

    def test_de_facto_holder_is_recomputed_on_both_sides(self):
        before = self.h.duchies["leafguard"].de_facto_holder_id
        assert before == "duke_lyra"
        # отдаём 3 из 5 провинций leafguard красным — это большинство
        for idx in (40, 42, 43):
            self.h.transfer_county(idx, "red", None)
        assert self.h.duchies["leafguard"].de_facto_holder_id == "king_erik"
        assert self.h.duchies["leafguard"].holder_id == "duke_lyra", \
            "de jure титул не отбирается"
        # прежнее герцогство нового держателя тоже пересчитано
        assert self.h.majority_nation_of_duchy("greymoor") is None

    def test_events_report_the_owner_change(self):
        events = self.h.transfer_county(self.county, "red", None, cause="битва")
        assert any("green → red" in e for e in events), events
        assert any("битва" in e for e in events), events

    def test_junk_input_changes_nothing(self):
        before = self.h.state_fingerprint()
        for args in ((None, "red", None), (-1, "red", None), (999, "red", None),
                     (True, "red", None), (41, None, None), (41, 7, None),
                     (41, "", None), (41, "red", "baron_ghost")):
            assert self.h.transfer_county(*args) == [], args
        assert self.h.state_fingerprint() == before

    def test_transfer_to_the_same_holder_is_idempotent_in_state(self):
        self.h.transfer_county(self.county, "green", "baron_thorn")
        assert self.h.characters["baron_thorn"].province_idx == self.county
        assert self.h.provinces[self.county].owner == "green"

    def test_holder_of_county_finds_the_holder(self):
        assert self.h.holder_of_county(self.county) is self.holder
        assert self.h.holder_of_county(0) is None
        assert self.h.holder_of_county(-5) is None


class TestDeFactoOwnership:
    """Правило «герцогство де-факто принадлежит большинству» и его следствия.

    Проверяется на КОНКРЕТНОЙ карте: ``EXPECTED_DE_FACTO_HOLDERS`` и
    ``NEUTRAL_DUCHIES`` — это утверждение о ``world_data.py``. Если параллельный
    агент перекрасит провинцию, тест упадёт сразу и с понятным сообщением, а не
    через три других теста.
    """

    def setup_method(self):
        self.h = make_hierarchy()

    def test_fresh_world_has_de_facto_holders_where_the_majority_is(self):
        for duchy_id, holder_id in EXPECTED_DE_FACTO_HOLDERS.items():
            duchy = self.h.duchies[duchy_id]
            assert duchy.de_facto_holder_id == holder_id, duchy_id
            assert self.h.de_facto_holder_of_duchy(duchy_id) is \
                self.h.characters[holder_id]

    def test_fresh_world_has_no_de_facto_holder_without_a_majority(self):
        for duchy_id in NEUTRAL_DUCHIES:
            assert self.h.duchies[duchy_id].de_facto_holder_id is None, duchy_id

    def test_neutral_is_never_a_nation(self):
        # полностью нейтральное герцогство не должно объявлять «большинство»
        # из словаря, где единственный ключ — это «никто»
        assert self.h.majority_nation_of_duchy("northmark") is None
        assert self.h.majority_nation_of_duchy("greymoor") is None
        for duchy_id in EXPECTED_DE_FACTO_HOLDERS:
            assert self.h.majority_nation_of_duchy(duchy_id) != NEUTRAL_NATION

    def test_majority_must_be_strict(self):
        # goldfield: 2 зелёные из 5 — это ровно НЕ большинство
        assert self.h.majority_nation_of_duchy("goldfield") is None
        self.h.transfer_county(46, "red", None)
        assert self.h.majority_nation_of_duchy("goldfield") is None, "2:2 — ничья"
        self.h.transfer_county(47, "green", None)
        self.h.transfer_county(48, "green", None)
        assert self.h.majority_nation_of_duchy("goldfield") == "green", "3:2 — да"
        assert self.h.de_facto_holder_of_duchy("goldfield") is \
            self.h.characters["king_sigurd"], "de jure герцога тут нет вовсе"

    def test_majority_of_three_out_of_five_is_enough(self):
        for idx in (45, 46, 47):
            self.h.transfer_county(idx, "green", None)
        assert self.h.majority_nation_of_duchy("goldfield") == "green"

    def test_without_a_strict_majority_the_duchy_pays_nobody(self):
        # leafguard: 1 зелёная, 2 синие, 2 красные — ни у кого нет половины
        self.h.transfer_county(41, "blue", None)
        self.h.transfer_county(42, "blue", None)
        self.h.transfer_county(43, "red", None)
        self.h.transfer_county(44, "red", None)
        assert self.h.majority_nation_of_duchy("leafguard") is None
        assert self.h.de_facto_holder_of_duchy("leafguard") is None
        assert self.h.duchy_income("leafguard") == 0
        assert self.h.duchies["leafguard"].holder_id == "duke_lyra", \
            "de jure титул остаётся, даже когда страна раздроблена"

    def test_three_out_of_five_is_a_majority(self):
        self.h.transfer_county(40, "blue", None)
        self.h.transfer_county(41, "blue", None)
        self.h.transfer_county(42, "blue", None)
        assert self.h.majority_nation_of_duchy("leafguard") == "blue"
        assert self.h.de_facto_holder_of_duchy("leafguard") is \
            self.h.characters["king_rurik"]

    def test_de_facto_holder_falls_back_to_the_king_of_the_nation(self):
        # захватываем emberfall целиком: de jure герцог — синий duke_brenna,
        # а править областью придётся красному трону
        for idx in (25, 26, 27, 28, 29):
            self.h.transfer_county(idx, "red", None, cause="захват")
        assert self.h.duchies["emberfall"].holder_id == "duke_brenna"
        assert self.h.duchies["emberfall"].de_facto_holder_id == "king_erik"

    def test_de_facto_holder_is_none_when_the_nation_has_no_ruler(self):
        self.h.kill_character("king_sigurd")
        assert self.h.duchies["leafguard"].de_facto_holder_id == "duke_lyra", \
            "de jure герцог — живой правитель своей нации"
        self.h.kill_character("duke_lyra")
        self.h.characters["baron_moss"].alive = False
        self.h.characters["baron_thorn"].alive = False
        self.h.characters["baron_wolf"].alive = False
        self.h.characters["duke_orso"].alive = False
        self.h.characters["baron_gray"].alive = False
        self.h.recompute_de_facto_holders()
        assert self.h.duchies["leafguard"].de_facto_holder_id is None

    def test_de_facto_holder_of_duchy_never_returns_a_corpse(self):
        self.h.characters["duke_lyra"].alive = False
        assert self.h.de_facto_holder_of_duchy("leafguard") is None

    def test_recompute_is_cheap_and_idempotent(self):
        before = {d.id: d.de_facto_holder_id for d in self.h.duchies.values()}
        assert self.h.recompute_de_facto_holders() == []
        assert {d.id: d.de_facto_holder_id for d in self.h.duchies.values()} == before

    def test_de_facto_holder_survives_the_snapshot(self):
        restored = Hierarchy.from_state(self.h.to_state(), copy_provinces())
        for duchy_id, holder_id in EXPECTED_DE_FACTO_HOLDERS.items():
            assert restored.duchies[duchy_id].de_facto_holder_id == holder_id
        for duchy_id in NEUTRAL_DUCHIES:
            assert restored.duchies[duchy_id].de_facto_holder_id is None

    def test_de_facto_holder_is_not_added_to_summary(self):
        # набор ключей summary зафиксирован тестами детерминизма, поэтому
        # de-факто держатель туда НЕ добавляется — он живёт в to_state
        assert set(self.h.summary()["duchies"]["leafguard"]) == {"holder", "income"}
        duchy_state = self.h.to_state()["duchies"]["leafguard"]
        assert set(duchy_state) == {f.name for f in
                                    dataclasses.fields(self.h.duchies["leafguard"])}
        assert "de_facto_holder_id" in duchy_state


class TestGrantRevokeOwnership:
    """``grant_fief``/``revoke_fief`` обязаны реально менять состояние земли."""

    def setup_method(self):
        self.h = make_hierarchy()

    def test_grant_moves_the_county_into_the_recipients_hands(self):
        self.h.revoke_fief("baron_wolf")
        assert self.h.grant_fief(44, "baron_wolf")
        assert self.h.characters["baron_wolf"].province_idx == 44
        assert self.h.provinces[44].owner == "green"

    def test_grant_of_neutral_land_records_the_annexation(self):
        # Путь без by_actor — «выдать можно что угодно кому угодно». Раньше
        # такая земля НЕ меняла владельца, то есть оставалась ничейной: после
        # этапа 2 duchy_income считает только фактические владения, и выданное
        # нейтральное графство не платило бы НИКОМУ.
        self.h.revoke_fief("baron_wolf")
        assert self.h.grant_fief(47, "baron_wolf")
        assert self.h.provinces[47].owner == "green"
        assert self.h.characters["baron_wolf"].nation == "green"

    def test_grant_inside_the_realm_keeps_the_owner(self):
        # 44 — зелёная провинция, baron_thorn зелёный: смена owner тут вхолостую,
        # и это правильно — выдать землю внутри своего realm'а не значит
        # аннексировать её у себя
        self.h.revoke_fief("baron_thorn")
        self.h.grant_fief(44, "baron_thorn", by_actor="duke_lyra")
        assert self.h.provinces[44].owner == "green"

    def test_grant_keeps_the_old_opinion_math(self):
        self.h.revoke_fief("baron_thorn")
        opinion, loyalty = (self.h.characters["baron_thorn"].opinion_of_liege,
                            self.h.characters["baron_thorn"].loyalty)
        assert self.h.grant_fief(44, "baron_thorn", by_actor="duke_lyra")
        assert self.h.characters["baron_thorn"].opinion_of_liege == opinion + 20
        assert self.h.characters["baron_thorn"].loyalty == min(100, loyalty + 10)

    def test_revoke_returns_the_land_to_the_realm_pool(self):
        holder = self.h.characters["baron_thorn"]
        owner_before = self.h.provinces[41].owner
        events = self.h.revoke_fief("baron_thorn")
        assert holder.province_idx is None
        assert self.h.provinces[41].owner == owner_before, \
            "отзыв не отбирает землю у короля, он забирает её у барона"
        assert self.h.holder_of_county(41) is None, "графство освободилось"
        assert any("теряет" in e for e in events), events

    def test_revoked_county_is_free_to_grant_again(self):
        self.h.revoke_fief("baron_thorn")
        assert self.h.holder_of_county(41) is None
        assert self.h.grant_fief(41, "baron_moss")
        assert self.h.characters["baron_moss"].province_idx == 41

    def test_revoke_then_grant_moves_the_fief_to_another_duchy(self):
        self.h.revoke_fief("baron_thorn")
        self.h.grant_fief(36, "baron_thorn")
        assert self.h.characters["baron_thorn"].duchy_id == "greymoor"
        assert self.h.contracts["baron_thorn"].liege_id == "duke_orso"

    def test_revoke_keeps_the_vassal_in_his_duchy(self):
        self.h.revoke_fief("baron_thorn")
        assert self.h.characters["baron_thorn"].duchy_id == "leafguard"
        assert self.h.contracts["baron_thorn"].liege_id == "duke_lyra"

    def test_grant_recomputing_de_facto_holder(self):
        # отдать три из пяти зелёных графств leafguard синим — de-факто
        # держателем станет их король
        for idx in (40, 41, 43):
            self.h.transfer_county(idx, "blue", None)
        assert self.h.duchies["leafguard"].de_facto_holder_id == "king_rurik"


# --------------------------------------------------------------------------
# Этап 4: ранг как состояние
# --------------------------------------------------------------------------


class TestRankAsState:
    """Ранг выводится из титулов, а не задаётся константой при постройке мира.

    Главный баг, который это закрывает: раньше ``rank`` был константой, и
    герцог, получивший герцогство из рук умершего дуке, оставался ``BARON``.
    У барона без сюзерена ``liege_of`` возвращает ``None``, а ``tick_vassals``
    делает ``continue`` — то есть мнение, лояльность и риск мятежа замирали
    навсегда.
    """

    def setup_method(self):
        self.h = make_hierarchy()

    def test_title_rank_has_no_bakeless(self):
        # «безземельный герцог» звучит естественно, но четвёртое значение сломало
        # бы _RANK_TO_TIER (нет для него Tier) и COMMAND_MIN_RANK (отказ с
        # неверным текстом). Отсутствие земли описывает province_idx is None.
        assert {r.value for r in TitleRank} == {"baron", "duke", "king"}

    def test_fresh_world_ranks_match_the_titles(self):
        for ch in self.h.characters.values():
            assert ch.rank is self.h.expected_rank(ch.id), ch.id

    def test_duke_holder_is_still_a_duke(self):
        # старый контракт тестов: holder_of_duchy(d).rank is TitleRank.DUKE
        for duchy in self.h.duchies.values():
            holder = self.h.holder_of_duchy(duchy.id)
            if holder is not None:
                assert holder.rank is TitleRank.DUKE, duchy.id

    def test_baron_liege_is_still_a_duke(self):
        # старый контракт тестов: liege_of(baron).rank is TitleRank.DUKE
        for baron in characters_by_rank(self.h, TitleRank.BARON):
            liege = self.h.liege_of(baron.id)
            assert liege is not None and liege.rank is TitleRank.DUKE, baron.id

    def test_realm_ruler_is_still_a_king(self):
        for realm in self.h.realms.values():
            assert self.h.characters[realm.ruler_id].rank is TitleRank.KING

    def test_promote_reports_the_change_once(self):
        events = self.h.promote("baron_thorn", TitleRank.DUKE)
        assert len(events) == 1 and "ранг" in events[0]
        assert self.h.characters["baron_thorn"].rank is TitleRank.DUKE
        assert self.h.promote("baron_thorn", TitleRank.DUKE) == [], \
            "повтор той же смены молчит"

    def test_promote_refuses_junk(self):
        before = self.h.state_fingerprint()
        assert self.h.promote("baron_ghost", TitleRank.DUKE) == []
        assert self.h.promote(7, TitleRank.DUKE) == []
        assert self.h.promote("baron_thorn", "duke") == []
        assert self.h.state_fingerprint() == before

    def test_expected_rank_follows_the_realm_throne(self):
        self.h.realms["kingdom_thorn"].ruler_id = "baron_thorn"
        assert self.h.expected_rank("baron_thorn") is TitleRank.KING

    def test_expected_rank_follows_the_duchy_title(self):
        self.h.duchies["leafguard"].holder_id = "baron_wolf"
        assert self.h.expected_rank("baron_wolf") is TitleRank.DUKE

    def test_expected_rank_falls_back_to_baron(self):
        self.h.characters["baron_wolf"].duchy_id = None
        self.h.characters["baron_wolf"].province_idx = None
        assert self.h.expected_rank("baron_wolf") is TitleRank.BARON

    def test_expected_rank_never_re_ranks_a_corpse(self):
        self.h.characters["duke_lyra"].alive = False
        assert self.h.expected_rank("duke_lyra") is TitleRank.DUKE
        assert self.h.refresh_rank("duke_lyra") == []

    def test_refresh_rank_demotes_a_landless_duke(self):
        duke = self.h.characters["duke_lyra"]
        self.h.duchies["leafguard"].holder_id = "baron_wolf"
        assert self.h.refresh_rank("duke_lyra")
        assert duke.rank is TitleRank.BARON

    def test_rank_does_not_leak_into_summary_keys(self):
        # набор ключей summary зафиксирован; ранг — это ЗНАЧЕНИЕ, а не новый ключ
        assert set(self.h.summary()["characters"]["baron_thorn"]) == \
            {"rank", "loyalty", "opinion", "gold"}


# --------------------------------------------------------------------------
# Этап 4: старение и смерть
# --------------------------------------------------------------------------


class TestAgingAndDeath:
    """Возраст растёт, смерть наступает строго по возрасту и без кубика."""

    def setup_method(self):
        self.h = make_hierarchy()

    def test_ageing_constants_are_the_documented_ones(self):
        assert CHARACTERS_AGE_PER_TURN == 1
        assert CHARACTER_DEATH_AGE == 80
        assert CHARACTERS_DEATH_AGE_SPREAD >= 1
        assert SUCCESSION_CRISIS_TURNS >= 1

    def test_death_ages_are_staggered_by_design(self):
        # С одинаковым порогом все бароны умирали в ОДИН ход, и к смерти
        # герцога его дукция была уже пуста: наследовать было некому, и мир
        # вымирал целиком на 50-м ходу.
        ages = {c.death_age for c in self.h.characters.values()}
        assert len(ages) > 5, "разброс обязателен"
        for ch in self.h.characters.values():
            assert CHARACTER_DEATH_AGE <= ch.death_age <= \
                CHARACTER_DEATH_AGE + CHARACTERS_DEATH_AGE_SPREAD

    def test_death_age_is_deterministic_and_id_based(self):
        assert character_death_age("baron_thorn") == \
            character_death_age("baron_thorn")
        for ch in self.h.characters.values():
            assert ch.death_age == character_death_age(ch.id), ch.id

    def test_death_age_never_uses_python_hash(self):
        # hash(str) рандомизируется PYTHONHASHSEED: реплей разъехался бы
        assert character_death_age("baron_thorn") == \
            CHARACTER_DEATH_AGE + sum(ord(c) for c in "baron_thorn") % \
            (CHARACTERS_DEATH_AGE_SPREAD + 1)

    def test_age_does_not_move_until_a_turn_passes(self):
        before = {c.id: c.age for c in self.h.characters.values()}
        self.h.tick_counties()
        self.h.tick_vassals()
        self.h.tick_realms()
        assert {c.id: c.age for c in self.h.characters.values()} == before, \
            "старение живёт в тике персонажей, а не в тиках поселений и realm'ов"

    def test_age_grows_by_exactly_one_per_turn(self):
        before = {c.id: c.age for c in self.h.characters.values()}
        self.h.tick_characters()
        after = {c.id: c.age for c in self.h.characters.values()}
        assert after == {k: v + CHARACTERS_AGE_PER_TURN for k, v in before.items()}

    def test_age_grows_through_end_turn(self):
        before = {c.id: c.age for c in self.h.characters.values()}
        self.h.end_turn()
        after = {c.id: c.age for c in self.h.characters.values()}
        assert after == {k: v + CHARACTERS_AGE_PER_TURN for k, v in before.items()}

    def test_no_one_dies_before_the_threshold(self):
        for _ in range(30):
            self.h.end_turn()
        assert all(c.alive for c in self.h.characters.values())
        assert self.h.characters["king_rurik"].age == 44 + 30

    def test_death_is_strictly_by_age(self):
        victim = self.h.characters["baron_thorn"]
        # тик сначала старит, потом проверяет порог, поэтому «ещё рано» — это
        # death_age на два года больше текущего возраста
        victim.death_age = victim.age + 2
        assert self.h.tick_characters() == [], "ещё не время"
        assert victim.alive
        victim.death_age = victim.age
        events = self.h.tick_characters()
        assert not victim.alive
        assert any(DEATH_CAUSE_AGE in e for e in events), events

    def test_death_is_reported_with_name_and_age(self):
        victim = self.h.characters["baron_thorn"]
        victim.age = victim.death_age
        events = self.h.tick_characters()
        assert any(victim.name in e and str(victim.age) in e for e in events), events

    def test_aging_never_touches_the_dice(self):
        for _ in range(40):
            self.h.end_turn()
        assert len(self.h.streams) == 0, "старение создало именованный поток"
        assert self.h.streams.consumed("anything") == 0

    def test_kill_character_is_deterministic_too(self):
        events = self.h.kill_character("baron_thorn")
        assert any(DEATH_CAUSE_KILLED in e for e in events), events
        assert not self.h.characters["baron_thorn"].alive

    def test_kill_character_refuses_the_dead_and_junk(self):
        self.h.kill_character("baron_thorn")
        assert self.h.kill_character("baron_thorn") == []
        assert self.h.kill_character("baron_ghost") == []
        assert self.h.kill_character(7) == []

    def test_death_age_survives_the_snapshot(self):
        self.h.characters["baron_thorn"].death_age = 111
        restored = Hierarchy.from_state(self.h.to_state(), copy_provinces())
        assert restored.characters["baron_thorn"].death_age == 111
        assert restored.state_fingerprint() == self.h.state_fingerprint()

    def test_old_snapshot_without_death_age_falls_back(self):
        state = self.h.to_state()
        for data in state["characters"].values():
            data.pop("death_age")
        restored = Hierarchy.from_state(state, copy_provinces())
        assert all(c.death_age == CHARACTER_DEATH_AGE
                   for c in restored.characters.values())

    def test_aging_is_reproducible_on_two_worlds(self):
        a, b = make_hierarchy(), make_hierarchy()
        for _ in range(12):
            a.tick_characters()
            b.tick_characters()
        assert a.state_fingerprint() == b.state_fingerprint()


# --------------------------------------------------------------------------
# Этап 4: наследование и престол
# --------------------------------------------------------------------------


class TestSuccession:
    """Смерть правителя разбирается по порядку realm -> герцогство -> графство."""

    def setup_method(self):
        self.h = make_hierarchy()

    # ---------------- наследование герцогства ----------------

    def test_duke_death_gives_the_title_to_an_heir(self):
        events = self.h.kill_character("duke_lyra")
        assert self.h.duchies["leafguard"].holder_id == "baron_moss"
        assert any("герцогом стал" in e for e in events), events

    def test_duke_heir_gets_the_duke_rank(self):
        # ГЛАВНЫЙ тест этапа 4.1: раньше титул достался барону с rank = BARON
        self.h.kill_character("duke_lyra")
        heir = self.h.characters["baron_moss"]
        assert heir.rank is TitleRank.DUKE
        assert heir.duchy_id == "leafguard"
        assert heir.realm_id == "kingdom_thorn"

    def test_duke_heir_gets_a_liege_so_the_tick_does_not_skip_him(self):
        self.h.kill_character("duke_lyra")
        heir = self.h.characters["baron_moss"]
        liege = self.h.liege_of(heir.id)
        assert liege is not None and liege.id == "king_sigurd"
        # наблюдаемо: тик реально его трогает (лояльность идёт к равновесию).
        # При прежнем баге rank остался бы BARON, liege_of вернул бы None и
        # tick_vassals сделал бы continue — лояльность осталась бы нулевой.
        heir.loyalty = 0
        self.h.tick_vassals()
        assert heir.loyalty == 3

    def test_old_vassals_of_the_duchy_follow_the_new_holder(self):
        self.h.kill_character("duke_lyra")
        assert {c.id for c in self.h.vassals_of("baron_moss")} == {"baron_thorn"}
        assert self.h.liege_of("baron_thorn").id == "baron_moss"

    def test_contracts_follow_the_new_duke(self):
        self.h.kill_character("duke_lyra")
        assert self.h.contracts["baron_thorn"].liege_id == "baron_moss"
        assert self.h.contracts["baron_moss"].liege_id == "king_sigurd"

    def test_dead_duke_keeps_his_own_duchy_field(self):
        # труп остаётся в своей дукции в снапшоте — это история, а не титул
        self.h.kill_character("duke_lyra")
        assert self.h.characters["duke_lyra"].duchy_id == "leafguard"

    def test_last_duke_leaves_the_duchy_without_a_holder(self):
        self.h.kill_character("duke_lyra")
        self.h.kill_character("baron_moss")
        events = self.h.kill_character("baron_thorn")
        # других зелёных в leafguard нет, а зелёные бароны других дукций живы —
        # наследование герцогства ограничено своей династией
        duchy = self.h.duchies["leafguard"]
        assert duchy.holder_id is None
        assert self.h.holder_of_duchy("leafguard") is None
        assert any("без герцога" in e for e in events), events

    def test_empty_duchy_still_reports_a_de_facto_holder_from_the_throne(self):
        # титул герцога пуст, но нация владеет областью и правит ею королём —
        # доход не должен исчезать только из-за смерти одного человека
        self.h.kill_character("duke_lyra")
        self.h.kill_character("baron_moss")
        self.h.kill_character("baron_thorn")
        duchy = self.h.duchies["leafguard"]
        assert duchy.holder_id is None
        assert duchy.de_facto_holder_id == "king_sigurd"
        assert self.h.duchy_income("leafguard") > 0

    def test_heirs_are_deterministic_by_loyalty_then_id(self):
        self.h.characters["baron_thorn"].loyalty = 10
        heirs = self.h.duchy_heirs("leafguard", exclude="duke_lyra")
        assert [c.id for c in heirs] == ["baron_moss", "baron_thorn"]
        self.h.characters["baron_thorn"].loyalty = 99
        assert [c.id for c in self.h.duchy_heirs("leafguard",
                                                exclude="duke_lyra")] == \
            ["baron_thorn", "baron_moss"]

    def test_duchy_heirs_stay_inside_the_dynasty(self):
        self.h.characters["baron_ember"].duchy_id = "leafguard"
        assert "baron_ember" not in [c.id for c in
                                     self.h.duchy_heirs("leafguard",
                                                        exclude="duke_lyra")]

    # ---------------- наследование графства ----------------

    def test_baron_death_without_heirs_frees_the_county(self):
        events = self.h.kill_character("baron_thorn")
        dead = self.h.characters["baron_thorn"]
        assert dead.province_idx is None
        assert self.h.holder_of_county(41) is None
        assert any("#41" in e for e in events), events

    def test_baron_death_with_a_heir_transfers_the_county(self):
        # освобождаем землю baron_moss заранее, чтобы преемник был
        self.h.revoke_fief("baron_moss")
        events = self.h.kill_character("baron_thorn")
        assert self.h.characters["baron_thorn"].province_idx is None
        assert self.h.characters["baron_moss"].province_idx == 41
        assert any("#41" in e for e in events), events

    def test_county_heir_gets_the_duchy_and_the_contract(self):
        self.h.revoke_fief("baron_moss")
        self.h.kill_character("baron_thorn")
        heir = self.h.characters["baron_moss"]
        assert heir.province_idx == 41
        assert heir.duchy_id == "leafguard"
        assert self.h.contracts["baron_moss"].liege_id == "duke_lyra"

    def test_county_is_never_inherited_by_a_king_or_a_duke(self):
        # графство — владение барона: наследование от умершего сюзерена может
        # подарить графство герцогу, а смерть барона — нет
        self.h.revoke_fief("baron_moss")
        self.h.revoke_fief("baron_gray")
        self.h.revoke_fief("baron_wolf")
        self.h.kill_character("baron_thorn")
        heir = self.h.holder_of_county(41)
        assert heir is not None and heir.rank is TitleRank.BARON, heir

    def test_county_heir_is_of_the_same_nation(self):
        # иначе налог по province.owner ушёл бы одной стране, а владение было бы
        # у персонажа другой — realm_income и duchy_income считали бы разное.
        # Нейтральные земли исключены намеренно: на стартовой карте барон может
        # держать нейтральное графство (baron_ray -> #33), и это не следствие
        # наследования, а исходная раскладка build_default_hierarchy.
        self.h.revoke_fief("baron_moss")
        self.h.kill_character("baron_thorn")
        for ch in self.h.characters.values():
            if ch.province_idx is None:
                continue
            owner = self.h.nation_of(ch.province_idx)
            assert owner == "neutral" or ch.nation == owner, ch.id

    def test_county_heirs_are_deterministic(self):
        self.h.revoke_fief("baron_moss")
        assert [c.id for c in self.h.county_heirs(41, exclude="baron_thorn")] \
            == ["baron_moss"]
        assert [c.id for c in self.h.county_heirs(41, exclude="baron_thorn")] \
            == [c.id for c in self.h.county_heirs(41, exclude="baron_thorn")]

    # ---------------- престол ----------------

    def test_king_death_moves_the_throne(self):
        events = self.h.kill_character("king_rurik")
        realm = self.h.realms["kingdom_riven"]
        assert realm.ruler_id == "baron_dawn"
        assert self.h.characters[realm.ruler_id].rank is TitleRank.KING
        assert any("престол перешёл" in e for e in events), events

    def test_player_claim_survives_succession(self):
        # is_player — это свойство КОРОНЫ, а не человека: претензия игрока не
        # исчезает вместе с королём, поэтому флаг остаётся на королевстве
        realm = self.h.realms["kingdom_riven"]
        assert realm.is_player is True
        self.h.kill_character("king_rurik")
        assert self.h.realms["kingdom_riven"].is_player is True
        assert self.h.characters[realm.ruler_id].nation == "blue"

    def test_new_ruler_can_spend_the_treasury(self):
        # иначе realm_upkeep продолжал бы брать 10 * len(vassals_of(труп)) + 30
        realm = self.h.realms["kingdom_riven"]
        gold, upkeep = realm.gold, self.h.realm_upkeep(realm.id)
        self.h.kill_character("king_rurik")
        assert self.h.realm_upkeep(realm.id) == upkeep
        assert self.h.raise_levy(realm.id, 1), "новый король обязан платить"
        assert realm.gold < gold

    def test_dead_king_keeps_no_contract(self):
        self.h.kill_character("king_rurik")
        assert "king_rurik" not in self.h.contracts
        # новый король — тоже без контракта: у короля нет сюзерена
        assert self.h.realms["kingdom_riven"].ruler_id not in self.h.contracts

    def test_heir_candidates_are_sorted_by_loyalty_martial_id(self):
        candidates = self.h.heir_candidates("kingdom_riven")
        assert candidates, "у королевства обязаны быть преемники"
        keys = [(-c.loyalty, -c.martial, c.id) for c in candidates]
        assert keys == sorted(keys)
        assert all(c.nation == "blue" and c.alive for c in candidates)

    def test_heir_candidates_are_living_and_of_the_realm_nation(self):
        self.h.characters["baron_dawn"].loyalty = 5
        assert [c.id for c in self.h.heir_candidates("kingdom_riven")][0] != \
            "baron_dawn"
        assert self.h.heir_candidates("kingdom_ember")[0].nation == "red"

    def test_heir_candidates_of_an_unknown_realm_is_empty(self):
        assert self.h.heir_candidates("kingdom_ghost") == []
        assert self.h.heir_candidates(7) == []

    def test_throne_without_heirs_is_an_explicit_state(self):
        for character_id in sorted(c.id for c in self.h.characters.values()
                                   if c.nation == "blue" and c.alive):
            self.h.kill_character(character_id)
        realm = self.h.realms["kingdom_riven"]
        assert realm.ruler_id is None
        crisis = self.h.succession_crisis_of(realm.id)
        assert isinstance(crisis, SuccessionCrisis)
        assert crisis.is_open
        assert crisis.candidates == ()
        assert crisis.ruler_id is None
        assert crisis.resolved_turn is None
        assert crisis.turn_limit == crisis.turn_opened + SUCCESSION_CRISIS_TURNS

    def test_a_realm_without_a_ruler_spends_nothing(self):
        for character_id in sorted(c.id for c in self.h.characters.values()
                                   if c.nation == "blue" and c.alive):
            self.h.kill_character(character_id)
        realm = self.h.realms["kingdom_riven"]
        assert self.h.realm_upkeep(realm.id) > 0, "содержание всё ещё платится"
        assert self.h.raise_levy(realm.id, 1) == ["Kingdom of Riven: "
                                                   "поднимать левейс некому"]
        assert self.h.realms["kingdom_riven"].gold == realm.gold
        self.h.end_turn()
        assert self.h.realms["kingdom_riven"].gold >= 0

    def test_crisis_records_who_took_the_throne(self):
        self.h.kill_character("king_rurik")
        crisis = self.h.succession_crisis_of("kingdom_riven")
        assert crisis.realm_id == "kingdom_riven"
        assert "baron_dawn" in crisis.candidates
        assert crisis.ruler_id == "baron_dawn"
        assert crisis.resolved_turn == self.h.turn
        assert not crisis.is_open

    def test_crisis_is_keyed_by_realm_so_the_registry_does_not_grow(self):
        for turn in range(1, 40):
            self.h.end_turn()
            assert len(self.h.succession_crises) <= len(self.h.realms)

    def test_resolve_succession_lets_the_player_pick_a_candidate(self):
        self.h.characters["baron_dawn"].loyalty = 1
        self.h.kill_character("king_rurik")
        auto = self.h.realms["kingdom_riven"].ruler_id
        other = next(c.id for c in self.h.heir_candidates("kingdom_riven")
                     if c.id != auto)
        events = self.h.resolve_succession("kingdom_riven", other)
        assert events
        assert self.h.realms["kingdom_riven"].ruler_id == other
        assert self.h.characters[other].rank is TitleRank.KING

    def test_resolve_succession_refuses_a_stranger(self):
        self.h.kill_character("king_rurik")
        before = self.h.state_fingerprint()
        events = self.h.resolve_succession("kingdom_riven", "duke_aldric")
        assert len(events) == 1 and "преемник" in events[0]
        assert self.h.state_fingerprint() == before
        assert self.h.resolve_succession("kingdom_thorn", "baron_thorn") == []

    def test_crisis_survives_the_snapshot(self):
        self.h.kill_character("king_rurik")
        restored = Hierarchy.from_state(self.h.to_state(), copy_provinces())
        crisis = restored.succession_crisis_of("kingdom_riven")
        assert isinstance(crisis, SuccessionCrisis)
        assert crisis.candidates == \
            self.h.succession_crisis_of("kingdom_riven").candidates
        assert restored.state_fingerprint() == self.h.state_fingerprint()

    def test_crisis_candidates_are_tuple_after_json(self):
        self.h.kill_character("king_rurik")
        restored = Hierarchy.from_state(loads(dumps(self.h.to_state())),
                                        copy_provinces())
        crisis = restored.succession_crisis_of("kingdom_riven")
        assert isinstance(crisis.candidates, tuple)

    def test_from_state_survives_a_broken_crisis_block(self):
        state = self.h.to_state()
        state["succession_crises"] = {"x": {"candidates": "baron_thorn",
                                            "turn_opened": "wat"}}
        restored = Hierarchy.from_state(state, copy_provinces())
        crisis = restored.succession_crisis_of("x")
        assert crisis.candidates == ("baron_thorn",), "строка стала одним id"
        assert crisis.turn_opened == 0 and crisis.turn_limit == 0
        assert crisis.ruler_id is None and crisis.resolved_turn is None
        # сломанный блок не обязан ломать хеш: он остаётся таким, каким прочитан
        assert restored.state_fingerprint() == Hierarchy.from_state(
            restored.to_state(), copy_provinces()).state_fingerprint()

    def test_from_state_without_crisis_block_loads_an_empty_registry(self):
        state = self.h.to_state()
        state.pop("succession_crises")
        restored = Hierarchy.from_state(state, copy_provinces())
        assert restored.succession_crises == {}
        assert restored.state_fingerprint() == self.h.state_fingerprint()

    # ---------------- auto_inherit ----------------

    def test_auto_inherit_still_works_as_a_module_function(self):
        # историческая точка входа для внешнего кода: разбор титулов умерших
        self.h.characters["duke_lyra"].alive = False
        events = auto_inherit(self.h)
        assert events
        assert self.h.duchies["leafguard"].holder_id == "baron_moss"

    def test_auto_inherit_is_idempotent(self):
        self.h.kill_character("duke_lyra")
        assert auto_inherit(self.h) == [], "разбор уже сделан kill_character"

    def test_auto_inherit_is_deterministic(self):
        a, b = make_hierarchy(), make_hierarchy()
        for h in (a, b):
            h.characters["duke_lyra"].alive = False
            h.characters["king_rurik"].alive = False
        assert auto_inherit(a) == auto_inherit(b)
        assert a.state_fingerprint() == b.state_fingerprint()


# --------------------------------------------------------------------------
# Этап 2 + 4: длинная дистанция и детерминизм
# --------------------------------------------------------------------------


class TestLongStage24Determinism:
    """Старение, наследование и передача владений вместе: два мира — один хеш."""

    def test_two_worlds_fifty_turns_hash_equal(self):
        a, b = make_hierarchy(), make_hierarchy()
        for _ in range(50):
            a.end_turn()
            b.end_turn()
        assert a.turn == b.turn == 51
        assert a.state_fingerprint() == b.state_fingerprint()

    def test_fifty_turns_events_are_identical(self):
        a, b = make_hierarchy(), make_hierarchy()
        collected = []
        for h in (a, b):
            events = []
            for _ in range(50):
                events += h.end_turn()
            collected.append(events)
        assert collected[0] == collected[1]
        assert any("умер" in e for e in collected[0]), \
            "на 50 ходах уже должен быть кто-то, кто умер"

    def test_fifty_turns_with_orders_and_transfers_hash_equal(self):
        def churn(h: Hierarchy) -> None:
            for _ in range(50):
                h.grant_fief(44, "baron_thorn", by_actor="duke_lyra")
                h.revoke_fief("baron_thorn", by_actor="duke_lyra")
                h.transfer_county(46, "blue", None, cause="разведка")
                h.transfer_county(46, "green", None, cause="отбита")
                h.issue_order("duke_lyra", OrderKind.SUMMON_COUNCIL, "baron_moss")
                h.end_turn()
        a, b = make_hierarchy(), make_hierarchy()
        churn(a)
        churn(b)
        assert a.state_fingerprint() == b.state_fingerprint()

    def test_fifty_turns_never_touch_the_dice(self):
        h = make_hierarchy()
        for _ in range(50):
            h.end_turn()
        assert len(h.streams) == 0

    def test_round_trip_with_deaths_preserves_the_fingerprint(self):
        h = make_hierarchy()
        for _ in range(45):
            h.end_turn()
        assert any(not c.alive for c in h.characters.values())
        restored = Hierarchy.from_state(h.to_state(), copy_provinces())
        assert restored.state_fingerprint() == h.state_fingerprint()

    def test_json_round_trip_with_orders_and_deaths_preserves_it(self):
        h = make_hierarchy()
        h.realms["kingdom_riven"].gold = 10000
        for _ in range(45):
            h.issue_order("king_rurik", OrderKind.SUMMON_COUNCIL, "duke_brenna")
            h.end_turn()
        restored = Hierarchy.from_state(loads(dumps(h.to_state())), copy_provinces())
        assert restored.state_fingerprint() == h.state_fingerprint()
        assert restored.turn == h.turn

    def test_snapshot_keys_gained_only_the_two_documented_blocks(self):
        assert SNAPSHOT_KEYS == set(make_hierarchy().to_state())
        duchy_fields = set(make_hierarchy().to_state()["duchies"]["leafguard"])
        assert "de_facto_holder_id" in duchy_fields
        character_fields = set(make_hierarchy().to_state()["characters"]["king_erik"])
        assert "death_age" in character_fields

    def test_two_hundred_turns_keep_the_world_consistent(self):
        h, other = make_hierarchy(), make_hierarchy()
        for world in (h, other):
            for _ in range(200):
                world.end_turn()
        assert h.state_fingerprint() == other.state_fingerprint()
        for realm in h.realms.values():
            assert realm.gold >= 0, realm.id
        for p in h.provinces:
            assert 0 <= p.loyalty <= 100, p.name
            assert p.garrison >= 0, p.name
        # ни один живой персонаж не держит чужую нацию и не висит на мёртвом
        for ch in h.characters.values():
            if ch.province_idx is not None:
                assert ch.nation == h.nation_of(ch.province_idx), ch.id

    def test_two_hundred_turns_do_not_rotate_the_streams(self):
        h = make_hierarchy()
        for _ in range(200):
            h.end_turn()
        assert len(h.streams) == 0

    def test_states_does_not_import_random_anymore(self):
        source = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "states.py"), encoding="utf-8").read()
        assert "import random" not in source