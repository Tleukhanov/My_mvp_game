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
import random
from typing import Dict, List, Sequence, Tuple

import pytest

from sim import state_hash
from states import (
    CONTRACT_LEVELS,
    DUCHY_DEFS,
    LANDLESS_OPINION_DECAY,
    LOYALTY_COLLAPSE,
    LOYALTY_TAX_BREAK,
    LOYALTY_TAX_FLOOR,
    REBELLION_LOYALTY,
    VASSAL_REBELLION_LOYALTY,
    Character,
    Hierarchy,
    Tier,
    TitleRank,
    VassalContract,
    build_default_hierarchy,
    development_tax_multiplier,
    loyalty_tax_multiplier,
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

    def test_duchy_income_equals_sum_of_county_incomes(self):
        for duchy in self.h.duchies.values():
            expected = sum(self.h.county_income(i) for i in duchy.de_jure_provinces)
            assert self.h.duchy_income(duchy.id) == expected, duchy.id

    def test_duchy_levy_equals_sum_of_county_levies(self):
        for duchy in self.h.duchies.values():
            expected = sum(self.h.county_levy(i) for i in duchy.de_jure_provinces)
            assert self.h.duchy_levy(duchy.id) == expected, duchy.id

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

    def test_random_world_income_is_still_consistent(self):
        rng = random.Random(12345)
        for idx in range(50):
            p = self.h.provinces[idx]
            p.hearths = rng.randint(0, 2000)
            p.security = rng.randint(0, 20)
        for duchy in self.h.duchies.values():
            assert self.h.duchy_income(duchy.id) == sum(
                self.h.county_income(i) for i in duchy.de_jure_provinces)


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
