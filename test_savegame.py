"""Тесты сохранения и загрузки кампании мировой карты.

Слой ``savegame.py`` вводится тем, что партия до него жила только в памяти:
выход в меню выбрасывал ``WorldMapScreen`` целиком, и потерять двадцать
ходов можно было, просто закрыв окно. Закрыты ровно те дыры, которые такой
слой обязан закрывать:

* **точность кругового оборота** — главное свойство. Снимок, записанный и
  прочитанный без единого хода игры, обязан дать тот же отпечаток. Если это
  не так, «сохранение» — иллюзия: партия меняется при каждой перезагрузке;
* партия после реальных ходов (владения переходили, армии двигались и
  погибали, отношения менялись) читается без потерь;
* битый или чужой файл отвергается понятным текстом и НЕ оставляет мир
  наполовину восстановленным;
* восстановленная партия играется дальше — ход можно закончить, и он
  действительно что-то меняет.

Запуск: python -m pytest test_savegame.py -q
"""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import sqlite3

import pygame
import pytest

pygame.init()
pygame.display.set_mode((1, 1))

from diplomacy import Relation  # noqa: E402
from savegame import (  # noqa: E402
    SAVE_FORMAT_VERSION,
    SaveCorrupt,
    SaveError,
    SaveIncompatible,
    SaveNotFound,
    campaign_fingerprint,
    campaign_state,
    default_save_path,
    has_save,
    load_screen,
    load_state,
    restore_screen,
    save_campaign,
)
from sim.hashing import state_hash  # noqa: E402
from sim.serialization import SCHEMA_VERSION, dumps  # noqa: E402
from world_data import PLAYER_NATION  # noqa: E402
from world_map import WorldMapScreen  # noqa: E402


@pytest.fixture
def screen():
    """Свой экран на тест: тесты ходят по миру и портят его состояние."""
    return WorldMapScreen()


@pytest.fixture
def save_path(tmp_path):
    """Путь в ``tmp_path``: файл сохранения не должен попасть в дерево кода."""
    return tmp_path / "campaign.db"


def _play_turns(screen, count):
    for _ in range(count):
        screen._end_turn()


# --------------------------------------------------------------------------
# Точность кругового оборота
# --------------------------------------------------------------------------

class TestRoundTripFidelity:
    def test_state_hash_identical_without_any_play(self, screen, save_path):
        """Снимок на старте партии читается В ТОЧНОСТИ тем же состоянием.

        Это и есть определение «сохранение работает»: без единого хода между
        записью и чтением отпечаток обязан совпасть до бита.
        """
        before = screen.state_fingerprint()

        save_campaign(screen, path=save_path)
        loaded = load_screen(path=save_path)

        assert loaded.state_fingerprint() == before
        assert campaign_fingerprint(loaded.to_state()) == before

    def test_campaign_state_is_plain_json(self, screen):
        """Снимок обязан выживать ``dumps``/``loads`` без потерь формы.

        Проверяется явно, потому что формат хранения — JSON: если снимок
        держал бы что-то вроде ``tuple`` или объекта, круговой оборот
        разъезжался бы уже на записи.
        """
        from sim.serialization import loads

        state = campaign_state(screen)
        assert state_hash(loads(dumps(state))) == state_hash(state)

    def test_province_ownership_survives(self, screen, save_path):
        """Владелец каждой провинции и её гарнизон восстанавливаются буквально."""
        screen.provinces[15].owner = "blue"
        screen.provinces[15].troops = 640
        screen.provinces[40].owner = "red"
        screen.provinces[40].troops = 120

        save_campaign(screen, path=save_path)
        loaded = load_screen(path=save_path)

        assert [p.owner for p in loaded.provinces] == \
               [p.owner for p in screen.provinces]
        assert [p.troops for p in loaded.provinces] == \
               [p.troops for p in screen.provinces]

    def test_generals_keep_position_troops_and_moved_flag(self, save_path):
        """Генерал — это «где стоит, сколько солдат, ходил ли в этом ходу»."""
        screen = WorldMapScreen()
        general = screen.generals[2]
        general.province_idx = 27
        general.troops = 735
        general.health = 80
        general.moved = True
        screen.generals.pop(0)          # и выбитый генерал тоже часть партии

        save_campaign(screen, path=save_path)
        loaded = load_screen(path=save_path)

        assert [(g.name, g.nation) for g in loaded.generals] == \
               [(g.name, g.nation) for g in screen.generals]
        rest = [g for g in loaded.generals if g.name == general.name][0]
        assert (rest.province_idx, rest.troops, rest.health, rest.moved) == \
               (27, 735, 80, True)

    def test_turn_counter_restored(self, save_path):
        """Счётчик ходов карты и её иерархии — разные числа, и оба важны."""
        screen = WorldMapScreen()
        _play_turns(screen, 4)
        assert screen._turn == 5

        save_campaign(screen, path=save_path)
        loaded = load_screen(path=save_path)

        assert loaded._turn == 5
        assert loaded.hierarchy.turn == screen.hierarchy.turn

    def test_diplomacy_relations_restored(self, save_path):
        """Объявленная война обязана пережить перезапуск, а не откатиться."""
        screen = WorldMapScreen()
        screen.diplomacy.set_relation("blue", "green", Relation.WAR)
        screen.diplomacy.set_relation("red", "green", Relation.ALLIANCE)

        save_campaign(screen, path=save_path)
        loaded = load_screen(path=save_path)

        assert loaded.diplomacy.get_relation("blue", "green") is Relation.WAR
        # отношение симметрично в обе стороны — как его ставит set_relation
        assert loaded.diplomacy.get_relation("green", "blue") is Relation.WAR
        assert loaded.diplomacy.get_relation("red", "green") is Relation.ALLIANCE

    def test_nation_gold_restored(self, save_path):
        """HUD рисует золото нации из ``WORLD_NATIONS``, а не из иерархии."""
        screen = WorldMapScreen()
        screen.nations[PLAYER_NATION].gold = 4242

        save_campaign(screen, path=save_path)
        loaded = load_screen(path=save_path)

        assert loaded.nations[PLAYER_NATION].gold == 4242

    def test_move_orders_survive_with_rebound_generals(self, save_path):
        """Приказ — обещание на будущие ходы; в загрузке он должен быть ЖИВЫМ.

        Проверяется не только число приказов, но и то, что приказ ссылается
        на генерала из восстановленного списка, а не на объект чужого мира:
        иначе ``_advance_move_order`` молча счёл бы его отменённым.
        """
        screen = WorldMapScreen()
        hero = [g for g in screen.generals if g.nation == PLAYER_NATION][0]
        assert screen._issue_move_order(hero, 27) == 1
        assert screen._orders

        save_campaign(screen, path=save_path)
        loaded = load_screen(path=save_path)

        assert len(loaded._orders) == 1
        order = loaded._orders[0]
        assert order["general"] in loaded.generals
        assert (order["general"].name, order["goal"]) == (hero.name, 27)

    def test_order_of_dead_general_is_dropped_not_restored(self, save_path):
        """Приказ на маршрут убитого генерала отбрасывается, а не падает.

        Так же поступает сам мир в ``_advance_move_order``: исполнять приказ
        некому. Проверка нужна, чтобы «мягкая» обработка не оказалась тихим
        сохранением битой ссылки.
        """
        screen = WorldMapScreen()
        hero = [g for g in screen.generals if g.nation == PLAYER_NATION][0]
        screen._issue_move_order(hero, 27)

        state = campaign_state(screen)
        state["orders"][0]["general"] = "Ghost|blue"     # армии больше нет
        state.pop("format")                              # отпечаток пересчитаем

        restored = restore_screen({**state, "format": SAVE_FORMAT_VERSION})
        assert restored._orders == []

    def test_hierarchy_state_restored_in_full(self, save_path):
        """Золото, престиж, тратЫ и де-факто держатели — из снимка иерархии."""
        screen = WorldMapScreen()
        realm = next(r for r in screen.hierarchy.realms.values()
                     if r.nation == PLAYER_NATION)
        realm.gold = 3210
        realm.prestige = 44
        realm.raised_levy = 900

        save_campaign(screen, path=save_path)
        loaded = load_screen(path=save_path)

        back = next(r for r in loaded.hierarchy.realms.values()
                    if r.nation == PLAYER_NATION)
        assert (back.gold, back.prestige, back.raised_levy) == (3210, 44, 900)
        assert loaded.hierarchy.state_fingerprint() == \
               screen.hierarchy.state_fingerprint()

    def test_rng_salt_counters_restored(self, save_path):
        """Счётчики солей решают, каким будет СЛЕДУЮЩИЙ бой.

        Без них загруженный мир повторил бы уже показанные игроку исходы, а
        это не «продолжение партии», а повтор.
        """
        screen = WorldMapScreen()
        screen._match_seq = 5
        screen._battle_seq = 17

        save_campaign(screen, path=save_path)
        loaded = load_screen(path=save_path)

        assert (loaded._match_seq, loaded._battle_seq) == (5, 17)

    def test_save_file_is_not_created_in_the_repo(self, tmp_path, monkeypatch):
        """Путь по умолчанию переопределяется переменной окружения.

        Проверка на то, что файл сохранения нельзя случайно закоммитить: тесты
        и «умный» запуск обязаны уметь увести его во временный каталог.
        """
        target = tmp_path / "env.db"
        monkeypatch.setenv("TACTIC_BATTLE_SAVE", str(target))
        assert default_save_path() == target

        screen = WorldMapScreen()
        assert screen.save_game() is not None
        assert target.exists()

    def test_fingerprint_is_stable_across_dumps(self, screen):
        """Отпечаток не зависит от того, как именно состояние сериализовано."""
        state = campaign_state(screen)
        assert campaign_fingerprint(state) == campaign_fingerprint(state)
        assert campaign_fingerprint(state) == state_hash(state)


# --------------------------------------------------------------------------
# Партия после реальных ходов
# --------------------------------------------------------------------------

class TestPlayedOutCampaign:
    def test_round_trip_after_several_turns(self, save_path):
        """Основной случай: партия отыграна, сохранена, прочитата — 1:1."""
        screen = WorldMapScreen()
        _play_turns(screen, 12)

        save_campaign(screen, path=save_path)
        loaded = load_screen(path=save_path)

        assert loaded.state_fingerprint() == screen.state_fingerprint()
        assert loaded._turn == screen._turn

    def test_ownership_changes_through_play_survive(self, save_path):
        """Захваченные провинции и пересчитанные под них доходы не откатываются."""
        screen = WorldMapScreen()
        hero = [g for g in screen.generals if g.nation == PLAYER_NATION][0]
        screen._issue_move_order(hero, 27)
        _play_turns(screen, 8)

        owners_before = [p.owner for p in screen.provinces]
        assert any(o == "blue" for o in owners_before)

        save_campaign(screen, path=save_path)
        loaded = load_screen(path=save_path)

        assert [p.owner for p in loaded.provinces] == owners_before
        assert loaded.hierarchy.state_fingerprint() == \
               screen.hierarchy.state_fingerprint()

    def test_load_info_reports_turn(self, screen, save_path):
        """Загруженный снимок отвечает на вопрос «на каком я ходу был»."""
        _play_turns(screen, 6)

        info = save_campaign(screen, path=save_path)
        assert info.turn == 7

        state = load_state(path=save_path)
        assert state["turn"] == 7


# --------------------------------------------------------------------------
# Честный отказ на плохом файле
# --------------------------------------------------------------------------

class TestGracefulRejection:
    def test_missing_file(self, save_path):
        """Нет файла — понятное сообщение, а не ``FileNotFoundError``."""
        with pytest.raises(SaveNotFound):
            load_state(path=save_path)

    def test_has_save_false_without_file(self, save_path):
        assert has_save(path=save_path) is False

    def test_has_save_true_after_write(self, screen, save_path):
        assert has_save(path=save_path) is False
        save_campaign(screen, path=save_path)
        assert has_save(path=save_path) is True

    def test_truncated_payload(self, screen, save_path):
        """Обрезанный JSON: ни партии, ни исключения из json наружу."""
        save_campaign(screen, path=save_path)
        conn = sqlite3.connect(str(save_path))
        conn.execute("UPDATE saves SET payload = substr(payload, 1, 40)")
        conn.commit()
        conn.close()

        with pytest.raises(SaveCorrupt):
            load_state(path=save_path)

    def test_tampered_payload_is_caught_by_fingerprint(self, screen, save_path):
        """Правка полей в обход кода ловится отпечатком.

        Отпечаток — не шифрование и не защита от злого умысла: это дешёвая
        проверка «файл целый». Обрезанный или подправленный вручную снимок
        обязан падать, а не собирать партию из правдоподобных мусора и
        половины мира.
        """
        save_campaign(screen, path=save_path)
        conn = sqlite3.connect(str(save_path))
        row = conn.execute("SELECT payload FROM saves").fetchone()[0]
        conn.execute("UPDATE saves SET payload = ?", (row[:-5] + '"x":1}',))
        conn.commit()
        conn.close()

        with pytest.raises(SaveCorrupt):
            load_state(path=save_path)

    def test_file_that_is_not_a_database(self, save_path):
        """Случайный файл на месте сохранения — понятный отказ."""
        save_path.write_text("это не база", encoding="utf-8")
        with pytest.raises(SaveError):
            load_state(path=save_path)

    def test_incompatible_save_version(self, screen, save_path):
        """Файл будущей/прошлой версии отвергается, а не читается «как есть»."""
        save_campaign(screen, path=save_path)
        conn = sqlite3.connect(str(save_path))
        conn.execute("UPDATE saves SET save_version = ?",
                     (SAVE_FORMAT_VERSION + 7,))
        conn.commit()
        conn.close()

        with pytest.raises(SaveIncompatible) as excinfo:
            load_state(path=save_path)
        assert str(SAVE_FORMAT_VERSION) in str(excinfo.value)

    def test_incompatible_schema_version(self, screen, save_path):
        """Та же проверка для схемы сериализации ``sim``."""
        save_campaign(screen, path=save_path)
        conn = sqlite3.connect(str(save_path))
        conn.execute("UPDATE saves SET schema_version = ?", (SCHEMA_VERSION + 3,))
        conn.commit()
        conn.close()

        with pytest.raises(SaveIncompatible):
            load_state(path=save_path)

    def test_incompatible_version_inside_state(self, screen, save_path):
        """Версия внутри снимка проверяется тоже: файл могли переписать руками."""
        state = campaign_state(screen)
        state["format"] = SAVE_FORMAT_VERSION - 1

        with pytest.raises(SaveIncompatible):
            restore_screen(state)

    def test_state_of_another_map_size_is_rejected(self, screen):
        """Снимок с другим числом провинций — не «частичный файл», а чужая карта.

        Подставлять значения по умолчанию здесь нельзя: получилась бы партия,
        где половина мира молча стоит на старте.
        """
        state = campaign_state(screen)
        state["provinces"]["owners"] = state["provinces"]["owners"][:5]

        with pytest.raises(SaveCorrupt):
            restore_screen(state)

    def test_unknown_relation_is_rejected(self, screen):
        """Отношение неизвестного вида не превращается в «нейтралитет»."""
        state = campaign_state(screen)
        state["diplomacy"] = [{"a": "blue", "b": "red", "relation": "WORLD_END"}]

        with pytest.raises(SaveCorrupt):
            restore_screen(state)

    def test_relation_to_unknown_nation_is_rejected(self, screen):
        """Отношение с нацией, которой нет на карте, — тоже отказ."""
        state = campaign_state(screen)
        state["diplomacy"] = [{"a": "blue", "b": "purple", "relation": "WAR"}]

        with pytest.raises(SaveCorrupt):
            restore_screen(state)

    def test_general_outside_the_map_is_rejected(self, screen):
        """Генерал в несуществующей провинции — битый файл, а не падение."""
        state = campaign_state(screen)
        state["generals"][0]["province_idx"] = 9999

        with pytest.raises(SaveCorrupt):
            restore_screen(state)

    def test_duplicated_general_is_rejected(self, screen):
        """Два генерала с одним ключом склеились бы в одного — молча."""
        state = campaign_state(screen)
        state["generals"].append(dict(state["generals"][0]))

        with pytest.raises(SaveCorrupt):
            restore_screen(state)

    def test_order_goal_outside_the_map_is_rejected(self, screen):
        """Приказ в никуда — битый снимок, а не «приказ пропадёт по дороге»."""
        state = campaign_state(screen)
        state["orders"] = [{"general": state["generals"][0]["key"],
                            "goal": 4242, "path": [], "stuck": 0}]

        with pytest.raises(SaveCorrupt):
            restore_screen(state)

    def test_rejected_load_leaves_world_untouched(self, screen, save_path):
        """Главное требование к отказу: мир не трогают вообще.

        Проверяется по отпечатку ДО и ПОСЛЕ неудачной загрузки: если бы
        ``restore_screen`` наполовину переписал экран, отпечаток разошёлся бы,
        и игрок получил бы партию, которой не существует.
        """
        before = screen.state_fingerprint()
        state = campaign_state(screen)
        state["provinces"]["owners"] = []

        with pytest.raises(SaveCorrupt):
            restore_screen(state, screen=screen)

        assert screen.state_fingerprint() == before

    def test_missing_slot_in_existing_database(self, screen, save_path):
        """База есть, слота нет: это «сохранения нет», а не «файл битый»."""
        save_campaign(screen, path=save_path, slot="campaign")
        with pytest.raises(SaveNotFound):
            load_state(path=save_path, slot="другая-партия")


# --------------------------------------------------------------------------
# Восстановленная партия играется дальше
# --------------------------------------------------------------------------

class TestRestoredCampaignContinues:
    def test_turn_can_be_ended_after_loading(self, screen, save_path):
        """Главный вопрос к загрузке: партия живая?

        Если после чтения нельзя закончить ход, «сохранение» бесполезно —
        карта не просто читается, а продолжает работать.
        """
        _play_turns(screen, 3)
        save_campaign(screen, path=save_path)
        loaded = load_screen(path=save_path)

        turn_before = loaded._turn
        generals_before = [(g.name, g.troops) for g in loaded.generals]

        loaded._end_turn()

        assert loaded._turn == turn_before + 1
        assert loaded.hierarchy.turn == turn_before + 1

    def test_turn_changes_something_visible(self, screen, save_path):
        """Ход после загрузки меняет состояние, а не просто щёлкает счётчиком.

        Иначе «продолжение» было бы декорацией: счётчик бы раст, а экономика
        и армии стояли бы.
        """
        save_campaign(screen, path=save_path)
        loaded = load_screen(path=save_path)

        before = loaded.state_fingerprint()
        _play_turns(loaded, 2)

        assert loaded.state_fingerprint() != before

    def test_generals_may_move_after_loading(self, screen, save_path):
        """Приказ выдаётся и исполняется на загруженном мире.

        Здесь проверяется то, что ломается чаще всего: у приказа должен быть
        ЖИВОЙ генерал из восстановленного списка, иначе движение молча
        отменяется, а игрок не понимает почему.
        """
        save_campaign(screen, path=save_path)
        loaded = load_screen(path=save_path)

        hero = [g for g in loaded.generals if g.nation == PLAYER_NATION][0]
        assert loaded._issue_move_order(hero, 27) == 1

        before = hero.province_idx
        loaded._advance_move_order()
        assert hero.province_idx != before

    def test_hierarchy_turn_continues_without_replay(self, screen, save_path):
        """Экономика загруженной иерархии продолжает тикать по-настоящему.

        Проверяем именно то, что теряется при неверном зерне или сброшенном
        счётчике: золото и престиж обязаны расти так же, как до сохранения.
        """
        _play_turns(screen, 5)
        save_campaign(screen, path=save_path)

        live = WorldMapScreen()
        restore_screen(campaign_state(screen), screen=live)
        loaded = load_screen(path=save_path)

        # обе партии продолжаются одинаково, если снимок честный
        _play_turns(live, 3)
        _play_turns(loaded, 3)
        assert loaded.state_fingerprint() == live.state_fingerprint()

    def test_screen_methods_report_failures_instead_of_raising(self, save_path):
        """``load_game`` на пустом месте показывает плашку и НЕ падает.

        Игрок жмёт F9 без сохранения — это обычное действие, а не краш.
        """
        screen = WorldMapScreen()
        assert screen.load_game(path=save_path) is None
        assert screen._message

    def test_save_game_reports_the_turn(self, screen, save_path):
        info = screen.save_game(path=save_path)
        assert info is not None
        assert info.turn == screen._turn
        assert info.fingerprint == screen.state_fingerprint()

    def test_saving_mid_battle_is_refused_with_a_reason(self, save_path):
        """Живая сессия боя — единственное состояние, которое сохранять нельзя.

        Тактический слой не умеет продолжаться с середины, поэтому такая
        «партия» после загрузки была бы неиграбельной. Отказ должен быть
        честным, а не тихо битым файлом.
        """
        screen = WorldMapScreen()
        hero = [g for g in screen.generals if g.nation == PLAYER_NATION][0]
        screen._start_tactical_session(hero, "red", 27)

        assert screen.save_game(path=save_path) is None
        assert "посреди" in (screen._message or "")
        assert not save_path.exists()

    def test_failed_save_keeps_previous_one(self, screen, save_path, monkeypatch):
        """Упавшая запись не должна стирать прошлый снимок.

        Ровно то, зачем нужна транзакция: если перезапись оборвалась на
        середине, игрок возвращается к последнему целому сохранению, а не к
        пустой базе.
        """
        _play_turns(screen, 3)
        first = save_campaign(screen, path=save_path)
        assert load_state(path=save_path)["turn"] == 4

        import savegame

        def boom(*_args, **_kwargs):
            raise RuntimeError("нечем писать")

        monkeypatch.setattr(savegame, "dumps", boom)
        with pytest.raises(SaveError):
            save_campaign(screen, path=save_path)

        assert load_state(path=save_path)["turn"] == 4
        assert has_save(path=save_path) is True
        assert first.turn == 4

    def test_interrupted_write_rolls_back_to_previous_snapshot(self, screen,
                                                               save_path):
        """Обрыв записи на уровне базы оставляет ПРЕЖНИЙ снимок.

        Это и есть обещание формата «переживает падение посреди записи».
        Транзакция, начатая вручную и откаченная без коммита, — ровно то, что
        делает процесс, убитый во время ``INSERT OR REPLACE``.
        """
        _play_turns(screen, 3)
        save_campaign(screen, path=save_path)

        conn = sqlite3.connect(str(save_path))
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("UPDATE saves SET turn = 999")
            conn.rollback()                      # «процесс умер до коммита»
        finally:
            conn.close()

        assert load_state(path=save_path)["turn"] == 4

    def test_restore_into_existing_screen_keeps_the_object(self, screen, save_path):
        """Восстановление переиспользует экран, а не строит новый.

        Иначе потерялись бы текстуры, кэши и разметка панелей — ровно то,
        из-за чего объект держали между заходами на карту.
        """
        _play_turns(screen, 2)
        save_campaign(screen, path=save_path)

        other = WorldMapScreen()
        texture_manager = other.tex_manager
        restore_screen(load_state(path=save_path), screen=other)

        # тот же объект: иначе потерялись бы текстуры и кэши панелей
        assert other.tex_manager is texture_manager
        assert other._turn == screen._turn
        # и состояние экрана после чтения — стартовое, а не из прошлой партии
        assert other.selected_generals == []
        assert other.pending_session is None

    def test_loading_over_a_dirty_screen_clears_screen_state(self, save_path):
        """Читаем поверх грязного экрана: выделение и отряды обязаны сброситься.

        Ссылки на генералов прошлого мира — самая неприятная поломка такого
        чтения: они остаются живыми объектами и молча указывают не туда.
        """
        dirty = WorldMapScreen()
        hero = [g for g in dirty.generals if g.nation == PLAYER_NATION][0]
        dirty._select_only([hero])
        dirty._store_control_group(1)
        assert dirty.selected_generals and dirty._control_groups

        clean = WorldMapScreen()
        _play_turns(clean, 4)
        save_campaign(clean, path=save_path)
        restore_screen(load_state(path=save_path), screen=dirty)

        assert dirty.selected_generals == []
        assert dirty._control_groups == {}

    def test_turn_twice_around_a_save_is_identical(self, save_path):
        """Сильнейшая проверка: партия, прошедшая через сохранение, равна себе.

        Сравниваются не хеши снимков, а результат игры: одна и та же партия
        после записи/чтения должна дать тот же результат на том же числе
        ходов. Это ловит расхождения, которые не видит сравнение снимков —
        например, потерянную позицию ГПСЧ.
        """
        direct = WorldMapScreen()
        _play_turns(direct, 7)

        source = WorldMapScreen()
        _play_turns(source, 3)
        save_campaign(source, path=save_path)
        through = load_screen(path=save_path)
        _play_turns(through, 4)

        assert through.state_fingerprint() == direct.state_fingerprint()
        assert [(g.name, g.province_idx, g.troops) for g in through.generals] == \
               [(g.name, g.province_idx, g.troops) for g in direct.generals]