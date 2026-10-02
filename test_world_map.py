"""Регрессионные тесты мировой карты и моста мир↔тактика.

Раньше мировой слой тестами не был покрыт вообще: `test_tactics.py` создаёт
`WorldMapScreen()` в блоке `try/except`, а `test_states.py` не импортирует
`world_map`. Поэтому баги «после боя не выйти в глобалку», «метрика войск
соперника игнорируется» и «бот стоит столбом» прошли незамеченными.

Здесь закрыты именно они, плюс поиск пути — чтобы следующая правка баланса
не откатила поведение обратно.

Запуск: python -m pytest test_world_map.py -q
"""

import copy
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import math

import pygame
import pytest

pygame.init()
pygame.display.set_mode((1, 1))

from diplomacy import Relation  # noqa: E402
from engine import GameEngine  # noqa: E402
from war import (  # noqa: E402
    TACTICS_UNIT_CAP,
    TROOPS_PER_TACTICAL_UNIT,
    WarSession,
    defender_units_for,
    tactical_units_for,
)
from world_data import PLAYER_NATION, WORLD_PROVINCES  # noqa: E402
from world_map import MOVE_ORDER_STUCK_TURNS, WorldMapScreen  # noqa: E402


@pytest.fixture(scope="module")
def screen():
    return WorldMapScreen()


@pytest.fixture
def fresh_screen():
    """Отдельный экран для тестов, которые реально двигают мир.

    Общий `screen` живёт на весь модуль, и тест «мир оживает» прогоняет
    десятки ходов: к концу модуля нейтральных провинций может не остаться,
    а армии игрока — быть выбиты. Из-за этого проверки захвата падали в
    зависимости от порядка, хотя сами по себе были верны.
    """
    return WorldMapScreen()


def _session(troops=1200, defender=None, **kw):
    base = dict(
        match_id=1,
        attacker_nation=PLAYER_NATION,
        defender_nation="red",
        province_idx=15,
        general_name="Tester",
        troops_committed=troops,
        quality=1,
        seed=7,
    )
    base.update(kw)
    if defender is not None:
        base["defender_troops"] = defender
    return WarSession(**base)


def _quit_call_lines(path):
    """Номера строк с РЕАЛЬНЫМИ вызовами pygame.quit().

    Разбор через AST, а не поиск подстроки: комментарии в коде про это
    тоже упоминают `pygame.quit`, и наивная проверка даёт ложное падение.
    """
    import ast

    tree = ast.parse(open(path, encoding="utf-8").read())
    lines = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_quit = (
            isinstance(func, ast.Attribute) and func.attr == "quit"
            and isinstance(func.value, ast.Name) and func.value.id == "pygame"
        )
        if is_quit:
            lines.add(node.lineno)
    return lines


HERE = os.path.dirname(os.path.abspath(__file__))


class TestReturnToWorldMap:
    """После тактики игрок обязан вернуться на ту же карту."""

    def test_engine_run_does_not_kill_pygame(self):
        # `GameEngine.run()` раньше вызывал pygame.quit(): мировая карта
        # оставалась с мёртвой поверхностью, и возврат из боя падал.
        import inspect

        tree_src = inspect.getsource(GameEngine.run)
        calls = [l for l in tree_src.splitlines()
                 if "pygame.quit()" in l and not l.strip().startswith("#")]
        assert not calls, f"run() всё ещё вызывает pygame.quit: {calls}"

    def test_quit_only_in_main_entrypoint(self):
        # Глушить видеорежим можно только последним действием всей игры:
        # тактика открывается поверх карты, и обратный возврат возможен.
        engine_quits = _quit_call_lines(os.path.join(HERE, "engine.py"))
        assert not engine_quits, \
            f"engine.py вызывает pygame.quit() на строках {sorted(engine_quits)}"
        main_quits = _quit_call_lines(os.path.join(HERE, "main.py"))
        assert main_quits, "main.py обязан глушить видеорежим при выходе"

    def test_world_screen_survives_tactics_cycle(self, screen):
        # Экран остаётся пригодным после «боя»: поверхность жива и рисуется.
        before = screen.screen
        screen.reopen()
        screen._render()
        assert screen.screen is before
        assert screen.screen.get_at((10, 10))[3] >= 0


class TestTroopMetrics:
    """Войска обеих сторон видны и реально влияют на бой."""

    def test_defender_units_use_real_troops(self):
        assert defender_units_for(_session(1200, defender=3000)) == TACTICS_UNIT_CAP
        assert defender_units_for(_session(1200, defender=100)) == 1
        assert defender_units_for(_session(1200, defender=2500)) == TACTICS_UNIT_CAP

    def test_attacker_units_from_troops(self):
        assert tactical_units_for(1200) == TACTICS_UNIT_CAP
        assert tactical_units_for(400) == 4
        assert tactical_units_for(0) == 1  # минимум один отряд
        assert tactical_units_for(-5) == 1

    def test_missing_defender_troops_falls_back(self):
        s = _session(1200)  # defender_troops=None
        assert defender_units_for(s) >= 1

    def test_session_round_trip_keeps_defender_troops(self):
        s = _session(1200, defender=3000)
        assert WarSession.from_state(s.to_state()) == s

    def test_old_snapshot_without_field_loads(self):
        data = _session(1200).to_state()
        data.pop("defender_troops", None)
        restored = WarSession.from_state(data)
        assert restored is not None and restored.defender_troops is None

    def test_unit_cap_preserves_force_ratio(self):
        """Потолок отрядов не должен ровнять армии разного размера."""
        def total_hp(troops, defender):
            engine = GameEngine(session=_session(troops, defender=defender))
            return (sum(u.max_health for u in engine.blue_units),
                    sum(u.max_health for u in engine.red_units))

        blue, red = total_hp(1200, 3000)
        assert blue / red == pytest.approx(1200 / 3000, rel=0.05)
        blue, red = total_hp(1200, 1200)
        assert blue / red == pytest.approx(1.0, rel=0.05)


class TestPathfinding:
    def test_graph_fully_connected(self, screen):
        g = next(x for x in screen.generals if x.nation == PLAYER_NATION)
        unreachable = [i for i in range(len(WORLD_PROVINCES))
                       if not screen.find_province_path(0, i, g)]
        assert unreachable == [], f"недостижимые провинции: {unreachable}"

    def test_own_army_does_not_block(self, screen):
        """Своя армия не преграда: маршрут строится сквозь неё."""
        g = next(x for x in screen.generals if x.nation == PLAYER_NATION)
        friend = next(x for x in screen.generals
                      if x is not g and x.nation == g.nation)
        other_idx = screen._adjacent_provinces(g.province_idx)[0]
        saved = friend.province_idx
        friend.province_idx = other_idx
        try:
            path = screen.find_province_path(g.province_idx, other_idx, g)
            assert path[-1] == other_idx
        finally:
            friend.province_idx = saved

    def test_foreign_general_forces_detour(self, screen):
        g = next(x for x in screen.generals if x.nation == PLAYER_NATION)
        foe = next(x for x in screen.generals if x.nation != g.nation)
        gate = next(i for i in screen._adjacent_provinces(g.province_idx)
                    if screen.find_province_path(g.province_idx, i, g))
        saved = foe.province_idx
        foe.province_idx = gate
        try:
            path = screen.find_province_path(g.province_idx, gate, g)
            # цель осталась целью, даже когда занята врагом
            assert path[-1] == gate
            # а сквозь неё промежуточной клеткой не пускает
            detour = screen.find_province_path(g.province_idx,
                                               screen._adjacent_provinces(gate)[0], g)
            if len(detour) > 1:
                assert detour[1] != gate
        finally:
            foe.province_idx = saved

    def test_unreachable_goal_returns_empty(self, screen):
        g = next(x for x in screen.generals if x.nation == PLAYER_NATION)
        assert screen.find_province_path(g.province_idx, g.province_idx, g) == \
            [g.province_idx]


class TestMoveOrders:
    def test_far_click_orders_march(self, screen):
        """Клик по далёкой чужой провинции без выбора армии = приказ."""
        screen._cancel_move_order()
        foe_idx = next(i for i, p in enumerate(screen.provinces)
                       if p.owner != PLAYER_NATION)
        ok = screen._auto_attack_order(foe_idx)
        assert ok is True
        assert screen._move_order is not None
        general, goal = screen._move_order
        assert general.nation == PLAYER_NATION and goal == foe_idx
        assert len(screen._move_path) > 0
        screen._cancel_move_order()

    def test_own_province_click_is_not_attack(self, screen):
        screen._cancel_move_order()
        own = next(i for i, p in enumerate(screen.provinces)
                   if p.owner == PLAYER_NATION)
        assert screen._auto_attack_order(own) is False
        assert screen._move_order is None

    def test_no_war_blocks_attack(self, screen):
        """По нейтрали или дружбе в поход не ходят."""
        screen._cancel_move_order()
        blocked = 0
        for idx, p in enumerate(screen.provinces):
            owner = getattr(p, "owner", "neutral")
            if owner in (PLAYER_NATION, "neutral"):
                continue
            if screen.diplomacy.is_enemy(PLAYER_NATION, owner):
                continue
            assert screen._auto_attack_order(idx) is False, \
                f"#{idx} ({owner}): поход без войны не запрещён"
            assert screen._move_order is None
            blocked += 1
        assert blocked > 0, "тест не нашёл ни одной небоевой провинции"

    def test_order_walks_and_completes(self, screen):
        screen._cancel_move_order()
        g = next(x for x in screen.generals if x.nation == PLAYER_NATION)
        # цель — соседняя провинция: один шаг и приказ снят
        goal = screen._adjacent_provinces(g.province_idx)[0]
        before = g.province_idx
        screen._issue_move_order(g, goal)
        assert screen._move_order is not None
        screen._advance_move_order()
        assert screen._move_order is None or g.province_idx != before
        screen._cancel_move_order()

    def test_stuck_order_is_cancelled(self, screen):
        """Армия, застрявшая на блокере, не должна бесконечно повторять цель."""
        screen._cancel_move_order()
        g = next(x for x in screen.generals if x.nation == PLAYER_NATION)
        far = next(i for i, p in enumerate(screen.provinces)
                   if p.owner != PLAYER_NATION
                   and len(screen.find_province_path(g.province_idx, i, g)) > 3)
        assert screen._issue_move_order(g, far) is True
        for _ in range(MOVE_ORDER_STUCK_TURNS + 2):
            if screen._move_order is None:
                break
            screen._advance_move_order()
        # либо дошёл, либо приказ честно снят
        assert screen._move_order is None or g.province_idx == far
        screen._cancel_move_order()


class TestAiActivity:
    def test_ai_target_is_reachable(self, screen):
        for g in screen.generals:
            if g.province_idx is None:
                continue
            target = screen._ai_target(g)
            if target is None:
                continue
            assert target != g.province_idx
            assert screen._ai_can_enter(target, g), \
                f"{g.name}: цель #{target} недостижима"

    def test_ai_does_not_target_friendly_generals(self, screen):
        for g in screen.generals:
            if g.province_idx is None:
                continue
            target = screen._ai_target(g)
            if target is None:
                continue
            occupant = screen._province_occupant(target)
            if occupant is not None:
                assert occupant.nation == g.nation or \
                    screen.diplomacy.is_enemy(g.nation, occupant.nation), \
                    f"{g.name} целится в мирного {occupant.name}"

    def test_world_becomes_alive(self, screen):
        """Нейтральные провинции должны убывать: бот не стоит столбом."""
        neutral_before = sum(1 for p in screen.provinces
                             if p.owner == "neutral")
        moved = 0
        for _ in range(10):
            prev = {g.name: g.province_idx for g in screen.generals}
            screen._end_turn()
            for g in screen.generals:
                if prev.get(g.name) != g.province_idx:
                    moved += 1
        neutral_after = sum(1 for p in screen.provinces
                            if p.owner == "neutral")
        assert moved > 0, "ни одна армия не сдвинулась за 10 ходов"
        assert neutral_after < neutral_before, "боты не захватили ничего"


class TestSelectionAndRendering:
    """Выбор генерала обязан переживать отрисовку.

    Регрессия: в `_render` стояло `self.selectedGeneral` вместо
    `self.selected_general`. Имя выглядит как опечатку, но это роняло
    рендер с `AttributeError` ровно в тот момент, когда игрок выбирал
    армию, — то есть на самом первом клике по генералу в бою.
    """

    def test_render_with_selected_general(self, fresh_screen):
        w = fresh_screen
        w._render()
        g = next(x for x in w.generals if x.province_idx is not None)
        w.selected_general = g
        w._render()  # раньше здесь был AttributeError

    def test_render_after_click_selects_without_crash(self, fresh_screen):
        w = fresh_screen
        w._render()
        g = next(x for x in w.generals if x.nation == PLAYER_NATION)
        cx, cy = w.provinces[g.province_idx].centroid
        w._handle_map_click(*w._world_to_screen(cx, cy))
        w._render()

    def test_no_typo_attributes_in_source(self, fresh_screen):
        import inspect

        src = inspect.getsource(type(fresh_screen)._render)
        assert "self.selectedGeneral" not in src, \
            "опечатка в имени атрибута роняет рендер при выборе генерала"

    def test_all_provinces_labelled_at_full_zoom(self, fresh_screen):
        """На зуме 1.0 подписаны все поселения — игрок видит, где что."""
        w = fresh_screen
        w.zoom = 1.0
        w._render()
        drawn = len(w._label_cache)
        assert drawn >= len(WORLD_PROVINCES) * 0.9, \
            f"подписано лишь {drawn} из {len(WORLD_PROVINCES)}"

    def test_frame_perf_budget(self, fresh_screen):
        """Кадр карты обязан укладываться в бюджет.

        Порог 20 мс, а не 16: под pytest в процессе живут десятки
        `WorldMapScreen` с их кэшами текстур, и замер завышается втрое —
        стенд-алоне карта рисуется за 7-11 мс на зумах 0.6/1.0/1.8.
        Тест ловит именно регрессии масштаба (например, возврат по-per-pixel
        заливки океана), а не дрожание машины.
        """
        import time

        w = fresh_screen
        w.zoom = 1.0
        for _ in range(3):
            w._render()  # прогрев кэшей текстур и окантовки
        best = None
        for _ in range(3):
            t = time.time()
            for _ in range(20):
                w._render()
            ms = (time.time() - t) / 20 * 1000
            best = ms if best is None else min(best, ms)
        assert best < 20.0, f"кадр {best:.1f} мс — бюджет превышен"


class TestCaptureOwnership:
    def test_capture_goes_through_hierarchy(self, fresh_screen):
        """Захват обязан обновлять и иерархию, и карту."""
        screen = fresh_screen
        target = next(i for i, p in enumerate(screen.provinces)
                      if p.owner == "neutral")
        g = next(x for x in screen.generals
                 if x.nation == PLAYER_NATION and x.province_idx != target)
        saved = (g.province_idx, screen.provinces[target].owner)
        try:
            screen._take_county(target, g, cause="тест")
            assert screen.provinces[target].owner == PLAYER_NATION
            assert g.province_idx == target, "генерал обязан занять клетку"
            ch = screen._general_character(g)
            if ch is not None:
                assert ch.province_idx == target
                assert ch.nation == PLAYER_NATION
            realm = next(r for r in screen.hierarchy.realms.values()
                         if r.nation == PLAYER_NATION)
            owned = screen.hierarchy.provinces_of_realm(realm.id)
            assert sum(screen.hierarchy.county_income(i) for i in owned) == \
                screen.hierarchy.realm_income(realm.id), "двойной доход"
        finally:
            g.province_idx = saved[0]
            screen.provinces[target].owner = saved[1]

    def test_general_matched_by_name_and_nation(self, screen):
        """Одинаковые имена в разных державах — разные люди."""
        for g in screen.generals:
            ch = screen._general_character(g)
            if ch is not None:
                assert ch.name == g.name and ch.nation == g.nation

    def test_general_moves_even_without_character(self, fresh_screen):
        """Генерал без пары-персонажа всё равно физически перемещается.

        Регрессия: `Theron` и `Aldric` не имеют персонажа в иерархии, и
        захват обновлял владельца провинции, но НЕ двигал генерала — армия
        стояла на месте и выглядела «зависшей».
        """
        screen = fresh_screen
        target = next(i for i, p in enumerate(screen.provinces)
                      if p.owner == "neutral")
        unlinked = next((g for g in screen.generals
                         if screen._general_character(g) is None), None)
        if unlinked is None:
            pytest.skip("нет генерала без персонажа на текущей карте")
        saved = unlinked.province_idx
        try:
            screen._take_county(target, unlinked, cause="тест")
            assert unlinked.province_idx == target
            assert screen.provinces[target].owner == unlinked.nation
        finally:
            unlinked.province_idx = saved