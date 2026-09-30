"""Тесты пакета ``sim`` — фундамента детерминированной симуляции.

Покрываются три гарантии, на которых держится будущий мультиплеер:
детерминизм ГПСЧ, стабильность хеша состояния и обратимость сериализации,
а также детерминированный порядок команд.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Any, List

import pytest

import sim
from sim import (
    SCHEMA_VERSION,
    VALID_COMMAND_TYPES,
    Command,
    CommandQueue,
    NamedStreams,
    dumps,
    hash_equal,
    loads,
    new_streams,
    state_hash,
    to_jsonable,
    from_jsonable,
)


# --------------------------------------------------------------------------
# Тестовые типы
# --------------------------------------------------------------------------


class Phase(Enum):
    """Фаза хода."""

    DAWN = "dawn"
    DUSK = "dusk"


class Rank(IntEnum):
    """Звание командира."""

    PEASANT = 0
    KNIGHT = 1


@dataclass
class Unit:
    """Тестовый юнит."""

    uid: str
    x: float
    y: float
    hp: int = 100
    tags: frozenset = field(default_factory=frozenset)


@dataclass(frozen=True)
class Order:
    """Тестовый приказ."""

    actor: str
    target: str
    phase: Phase = Phase.DAWN


def make_unit(**kwargs: Any) -> Unit:
    """Сборка юнита с дефолтами, чтобы тесты были короче."""
    data: dict[str, Any] = {"uid": "u1", "x": 1.0, "y": 2.0}
    data.update(kwargs)
    return Unit(**data)


# --------------------------------------------------------------------------
# RNG
# --------------------------------------------------------------------------


def test_streams_same_seed_same_sequence() -> None:
    """Поток, пересозданный с тем же seed, даёт ту же последовательность из 100 чисел."""
    a = NamedStreams(12345)
    first = [a.stream("combat").random() for _ in range(100)]
    b = NamedStreams(12345)
    second = [b.stream("combat").random() for _ in range(100)]
    assert first == second
    assert len(first) == 100


def test_streams_factory_matches_class() -> None:
    """Фабрика ``new_streams`` эквивалентна конструктору."""
    a = [new_streams(7).stream("ai").random() for _ in range(20)]
    b = [NamedStreams(7).stream("ai").random() for _ in range(20)]
    assert a == b


def test_different_seed_different_sequence() -> None:
    """Разные зерна дают разные последовательности."""
    a = [NamedStreams(1).stream("x").random() for _ in range(50)]
    b = [NamedStreams(2).stream("x").random() for _ in range(50)]
    assert a != b


def test_streams_are_independent() -> None:
    """Расход ``combat`` не сдвигает последовательность ``ai``."""
    only_ai_streams = NamedStreams(99)
    only_ai = [only_ai_streams.stream("ai").random() for _ in range(30)]
    mixed = NamedStreams(99)
    for _ in range(30):
        mixed.stream("combat").random()
        mixed.stream("weather").random()
    assert [mixed.stream("ai").random() for _ in range(30)] == only_ai


def test_stream_call_order_does_not_matter() -> None:
    """Порядок создания потоков не влияет на их содержимое."""
    first = NamedStreams(555)
    order_a = [first.stream("a").random() for _ in range(10)]
    order_b = [first.stream("b").random() for _ in range(10)]

    second = NamedStreams(555)
    for name in ("b", "a", "c", "b"):
        second.stream(name)
    assert [second.stream("a").random() for _ in range(10)] == order_a
    assert [second.stream("b").random() for _ in range(10)] == order_b


def test_stream_reused_gives_same_object() -> None:
    """Повторный ``stream`` возвращает тот же генератор, продолжая последовательность."""
    s = NamedStreams(3)
    rng = s.stream("q")
    first = rng.random()
    second = s.stream("q").random()
    assert s.stream("q") is rng
    fresh = NamedStreams(3)
    assert fresh.stream("q").random() == first
    assert fresh.stream("q").random() == second


def test_derive_differs_from_base() -> None:
    """Ветвь ``derive`` отличается от основного потока."""
    s = NamedStreams(42)
    base = [s.stream("combat").random() for _ in range(20)]
    branch = [s.derive("combat", 1).random() for _ in range(20)]
    assert base != branch


def test_derive_is_deterministic() -> None:
    """``derive`` воспроизводим: те же (seed, name, salt) -> те же числа."""
    a = [NamedStreams(42).derive("combat", 7).random() for _ in range(20)]
    b = [NamedStreams(42).derive("combat", 7).random() for _ in range(20)]
    assert a == b


def test_derive_different_salt_differs() -> None:
    """Разная соль даёт разную ветвь."""
    a = [NamedStreams(42).derive("combat", 7).random() for _ in range(10)]
    b = [NamedStreams(42).derive("combat", 8).random() for _ in range(10)]
    assert a != b


def test_derive_does_not_depend_on_base_consumption() -> None:
    """Ветвление не зависит от того, сколько съедено из базового потока."""
    a = NamedStreams(42)
    for _ in range(50):
        a.stream("combat").random()
    branch_a = [a.derive("combat", 3).random() for _ in range(10)]

    b = NamedStreams(42)
    branch_b = [b.derive("combat", 3).random() for _ in range(10)]
    assert branch_a == branch_b


def test_reseed_resets_streams() -> None:
    """``reseed`` сбрасывает все потоки на новое зерно."""
    s = NamedStreams(1)
    before = [s.stream("x").random() for _ in range(10)]
    s.reseed(1)
    after = [s.stream("x").random() for _ in range(10)]
    assert before == after

    s.reseed(2)
    assert [s.stream("x").random() for _ in range(10)] != before
    assert s.seed == 2


def test_reseed_clears_derived() -> None:
    """После ``reseed`` ветви пересоздаются с нового зерна."""
    s = NamedStreams(10)
    old = [s.derive("d", 1).random() for _ in range(5)]
    s.reseed(10)
    assert [s.derive("d", 1).random() for _ in range(5)] == old
    s.reseed(11)
    assert [s.derive("d", 1).random() for _ in range(5)] != old


def test_consumed_grows() -> None:
    """``consumed`` растёт по мере извлечения чисел."""
    s = NamedStreams(5)
    assert s.consumed("m") == 0
    rng = s.stream("m")
    for expected in (1, 2, 3, 4, 5, 6):
        rng.random()
        assert s.consumed("m") == expected


def test_consumed_is_per_stream() -> None:
    """Счётчики потоков независимы."""
    s = NamedStreams(5)
    for _ in range(4):
        s.stream("a").random()
    assert s.consumed("a") == 4
    assert s.consumed("b") == 0


def test_consumed_does_not_create_stream() -> None:
    """Запрос ``consumed`` для неизвестного потока не создаёт его."""
    s = NamedStreams(5)
    assert s.consumed("ghost") == 0
    assert s.known_streams() == ()


def test_consumed_counts_range_calls() -> None:
    """Счётчик растёт и на randrange/randint, а не только на random()."""
    s = NamedStreams(6)
    assert s.consumed("m") == 0
    s.stream("m").randint(1, 6)
    after_randint = s.consumed("m")
    s.stream("m").randrange(0, 10)
    assert after_randint >= 1
    assert s.consumed("m") > after_randint


def test_rng_stable_across_interpreter_hashes() -> None:
    """Потоки не зависят от PYTHONHASHSEED: хеш имени считается через hashlib."""
    import hashlib

    expected = int.from_bytes(hashlib.sha256(b"77|combat").digest()[:8], "big")
    assert NamedStreams(77).stream("combat").random() == __import__("random").Random(expected).random()


def test_clone_preserves_position() -> None:
    """Клон продолжает с того же места и не влияет на оригинал."""
    s = NamedStreams(8)
    first = [s.stream("a").random() for _ in range(5)]
    copy = s.clone()
    # Клон повторяет то, что выдаст оригинал с текущего места.
    assert [copy.stream("a").random() for _ in range(5)] == [s.stream("a").random() for _ in range(5)]
    # Изолированность: сдвигаем клон — оригинал не уезжает вместе с ним.
    copy.stream("a").random()
    assert copy.stream("a").random() != s.stream("a").random()
    assert first[0] != s.stream("a").random()
    assert len(s) == 1
    assert "a" in list(s)


def test_known_streams_sorted() -> None:
    """Список созданных потоков отсортирован и удобен для логов."""
    s = NamedStreams(2)
    for name in ("zeta", "alpha", "mid"):
        s.stream(name)
    assert s.known_streams() == ("alpha", "mid", "zeta")


def test_stream_usable_as_random_source() -> None:
    """Поток совместим с обычным API random (choice/randrange)."""
    s = NamedStreams(21)
    rng = s.stream("dice")
    assert rng.choice([1, 2, 3, 4, 5, 6]) in (1, 2, 3, 4, 5, 6)
    assert 0 <= rng.random() < 1.0
    assert isinstance(s.derive("dice", 2).randint(0, 10), int)


# --------------------------------------------------------------------------
# Хеширование
# --------------------------------------------------------------------------


def test_hash_equal_objects_same_hash() -> None:
    """Одинаковые по смыслу объекты дают одинаковый хеш."""
    a = {"x": 1, "y": [1, 2, 3]}
    b = {"x": 1, "y": [1, 2, 3]}
    assert state_hash(a) == state_hash(b)
    assert hash_equal(a, b)


def test_hash_different_objects_differ() -> None:
    """Разные значения дают разные хеши."""
    assert state_hash({"hp": 100}) != state_hash({"hp": 99})
    assert not hash_equal({"hp": 100}, {"hp": 99})


def test_hash_ignores_dict_key_order() -> None:
    """Порядок ключей dict не влияет на хеш."""
    a = {"a": 1, "b": 2, "c": 3}
    b = {"c": 3, "b": 2, "a": 1}
    assert state_hash(a) == state_hash(b)


def test_hash_ignores_set_order() -> None:
    """Порядок элементов set/frozenset не влияет на хеш."""
    a = {"tags": {"sword", "shield", "horse"}}
    b = {"tags": {"horse", "sword", "shield"}}
    assert state_hash(a) == state_hash(b)
    assert state_hash(frozenset({1, 2, 3})) == state_hash(frozenset({3, 2, 1}))


def test_hash_handles_dataclass() -> None:
    """Dataclass сравнивается по полям, а не по repr с адресом памяти."""
    assert state_hash(make_unit()) == state_hash(make_unit())
    assert not hash_equal(make_unit(), make_unit(hp=1))
    assert state_hash(make_unit(uid="u1")) != state_hash(make_unit(uid="u2"))


def test_hash_handles_enum() -> None:
    """Enum хешируется по имени, а не по порядковому номеру."""
    assert state_hash(Phase.DAWN) == state_hash("DAWN")
    assert state_hash(Rank.KNIGHT) == state_hash("KNIGHT")
    assert state_hash({"p": Phase.DUSK}) == state_hash({"p": "DUSK"})


def test_hash_handles_datetime() -> None:
    """datetime/date приводятся к ISO-строке."""
    moment = dt.datetime(2026, 10, 1, 12, 30, 15)
    assert state_hash(moment) == state_hash(moment.isoformat())
    assert state_hash(dt.date(2026, 10, 1)) == state_hash("2026-10-01")


def test_hash_float_noise_ignored() -> None:
    """Шум порядка 1e-12 не ломает хеш."""
    assert state_hash(0.1 + 0.2) == state_hash(0.3)
    assert state_hash(1.0 + 1e-12) == state_hash(1.0)
    assert state_hash({"x": 2.000000000001}) == state_hash({"x": 2.0})


def test_hash_float_meaningful_difference_detected() -> None:
    """Различия больше 9 знаков по-прежнему видны."""
    assert state_hash(1.0000001) != state_hash(1.0000002)


def test_hash_nested_structures() -> None:
    """Вложенные структуры канонизируются рекурсивно."""
    a = {"army": {"u1": {"hp": 10, "pos": (1.0, 2.0), "tags": {"a", "b"}}}}
    b = {"army": {"u1": {"tags": {"b", "a"}, "pos": [1.0, 2.0], "hp": 10}}}
    assert state_hash(a) == state_hash(b)


def test_hash_tuple_and_list_equal() -> None:
    """tuple и list с одинаковым содержимым дают одинаковый хеш."""
    assert state_hash((1, 2, 3)) == state_hash([1, 2, 3])


def test_hash_bool_distinct_from_int() -> None:
    """bool не путается с int (они разные значения JSON)."""
    assert state_hash({"v": True}) != state_hash({"v": 1})


def test_hash_none_and_scalars() -> None:
    """Скаляры хешируются как есть."""
    assert state_hash(None) == state_hash(None)
    assert state_hash("текст") != state_hash("другой")
    assert state_hash(b"\x00\xff") == state_hash("00ff")


def test_hash_unknown_object_falls_back_to_repr() -> None:
    """Неизвестный объект даёт хеш по repr, но не роняет функцию."""

    class Weird:
        def __repr__(self) -> str:
            return "Weird()"

    assert state_hash(Weird()) == state_hash(Weird())


def test_hash_is_hex_sha1() -> None:
    """Хеш — 40-символьный hex sha1."""
    digest = state_hash({"a": 1})
    assert len(digest) == 40
    assert all(char in "0123456789abcdef" for char in digest)


def test_hash_nested_dataclass_in_container() -> None:
    """Dataclass внутри dict/списка/set обрабатывается рекурсивно."""
    a = {"units": [make_unit(uid="a")], "meta": {"turn": 3}}
    b = {"meta": {"turn": 3}, "units": [make_unit(uid="a")]}
    assert state_hash(a) == state_hash(b)


def test_canonical_is_exported_and_repeatable() -> None:
    """``canonical`` доступен публично и повторяем."""
    assert sim.canonical((1, {2, 1})) == [1, [1, 2]]


# --------------------------------------------------------------------------
# Сериализация
# --------------------------------------------------------------------------


def test_serialization_roundtrip_dataclass() -> None:
    """Dataclass сериализуется в dict с именами полей (реhydration — на стороне симуляции)."""
    unit = make_unit(uid="u9", x=1.5, y=-2.25, hp=42, tags=frozenset({"a", "b"}))
    back = loads(dumps(unit))
    assert back == {"uid": "u9", "x": 1.5, "y": -2.25, "hp": 42, "tags": ["a", "b"]}
    restored = Unit(uid=back["uid"], x=back["x"], y=back["y"], hp=back["hp"], tags=frozenset(back["tags"]))
    assert restored == unit


def test_serialization_roundtrip_enum() -> None:
    """Enum восстанавливается с правильным классом даже внутри dataclass."""
    order = Order(actor="p1", target="u1", phase=Phase.DUSK)
    back = loads(dumps(order))
    assert back == {"actor": "p1", "target": "u1", "phase": Phase.DUSK}
    assert back["phase"] is Phase.DUSK
    assert Order(**back) == order


def test_serialization_roundtrip_set_and_tuple() -> None:
    """set становится отсортированным списком, tuple — списком."""
    payload = {"s": {"b", "a", "c"}, "t": (1, 2)}
    back = loads(dumps(payload))
    assert back == {"s": ["a", "b", "c"], "t": [1, 2]}


def test_serialization_roundtrip_datetime() -> None:
    """datetime переживает round-trip как ISO-строка."""
    moment = dt.datetime(2026, 10, 1, 8, 5, 0)
    assert loads(dumps(moment)) == moment.isoformat()


def test_serialization_roundtrip_nested() -> None:
    """Вложенная структура с dataclass/Enum/set восстанавливается целиком."""
    world = {
        "turn": 12,
        "units": [make_unit(uid="u1"), make_unit(uid="u2", hp=50)],
        "phase": Phase.DAWN,
        "deaths": {"u3", "u1"},
    }
    back = loads(dumps(world))
    assert back["turn"] == 12
    assert back["phase"] is Phase.DAWN
    assert back["deaths"] == ["u1", "u3"]
    assert back["units"][1]["hp"] == 50


def test_serialization_dumps_is_stable_text() -> None:
    """Один и тот же объект сериализуется в один и тот же текст."""
    payload = {"b": 1, "a": [1, 2], "c": {"y": 1, "x": 2}}
    assert dumps(payload) == dumps(payload)
    assert dumps(payload) == json.dumps(to_jsonable(payload), sort_keys=True, separators=(",", ":"))


def test_serialization_indent_option() -> None:
    """Параметр indent пробрасывается в json.dumps."""
    assert "\n" in dumps({"a": 1}, indent=2)
    assert "\n" not in dumps({"a": 1})


def test_serialization_does_not_write_files(tmp_path: Any) -> None:
    """Сериализация не создаёт файлов на диске (в т.ч. при импорте)."""
    before = set(tmp_path.iterdir())
    loads(dumps({"a": 1}))
    assert set(tmp_path.iterdir()) == before


def test_envelope_roundtrip() -> None:
    """Конверт со схемой переживает JSON-транспорт."""
    payload = {"turn": 3, "phase": Phase.DUSK}
    env = sim.envelope(payload)
    assert env["schema_version"] == SCHEMA_VERSION
    assert sim.unwrap(json.loads(dumps(env))) == payload


def test_envelope_custom_schema_version() -> None:
    """В конверт можно положить произвольную версию схемы."""
    env = sim.envelope({"a": 1}, schema_version=SCHEMA_VERSION + 1)
    with pytest.raises(ValueError):
        sim.unwrap(env)


def test_unwrap_mismatched_version_raises() -> None:
    """Несовпадение schema_version кидает ValueError."""
    env = sim.envelope({"a": 1})
    env["schema_version"] = 999
    with pytest.raises(ValueError):
        sim.unwrap(env)


def test_unwrap_broken_envelope_raises() -> None:
    """Повреждённый конверт кидает ValueError, а не TypeError/KeyError."""
    with pytest.raises(ValueError):
        sim.unwrap({"payload": {}})
    with pytest.raises(ValueError):
        sim.unwrap({"schema_version": SCHEMA_VERSION})
    with pytest.raises(ValueError):
        sim.unwrap("not a dict")


def test_to_from_jsonable_direct() -> None:
    """Прямые вызовы to_jsonable/from_jsonable дают ожидаемые структуры."""
    payload = to_jsonable({"p": Phase.DAWN, "s": {2, 1}})
    assert payload == {"p": {"__enum__": "Phase.DAWN"}, "s": [1, 2]}
    back = from_jsonable(payload)
    assert back["p"] is Phase.DAWN
    assert back["s"] == [1, 2]


def test_from_jsonable_unknown_enum_does_not_fail() -> None:
    """Неизвестный класс Enum не роняет десериализацию."""
    assert from_jsonable({"__enum__": "GhostMode.SPRINT"}) == "SPRINT"
    assert from_jsonable({"__enum__": "NoDots"}) == "NoDots"


def test_to_jsonable_enum_tag_format() -> None:
    """Тег Enum содержит имя класса и члена через точку."""
    assert to_jsonable(Rank.KNIGHT) == {"__enum__": "Rank.KNIGHT"}


def test_serialization_bytes_roundtrip() -> None:
    """bytes сериализуются в hex и обратно."""
    assert loads(dumps({"blob": b"\x01\x02\xff"})) == {"blob": b"\x01\x02\xff"}


def test_serialization_handles_unknown_object() -> None:
    """Неизвестный объект не ломает to_jsonable."""

    class Opaque:
        def __repr__(self) -> str:
            return "Opaque()"

    assert to_jsonable(Opaque()) == "Opaque()"


def test_registered_enums_reports_class() -> None:
    """После сериализации Enum появляется в реестре."""
    to_jsonable(Phase.DUSK)
    assert "Phase" in sim.registered_enums()


def test_serialization_version_constant() -> None:
    """Версия схемы — целое число 1."""
    assert isinstance(SCHEMA_VERSION, int)
    assert SCHEMA_VERSION == 1


# --------------------------------------------------------------------------
# Команды
# --------------------------------------------------------------------------


def test_append_returns_command_with_increasing_seq() -> None:
    """``append`` возвращает Command с монотонно растущим seq."""
    q = CommandQueue()
    first = q.append("p1", "move_army", {"to": (3, 4)}, turn=1)
    second = q.append("p2", "recruit", {"n": 10}, turn=1)
    third = q.append("p1", "tax_policy", None, turn=1)
    assert isinstance(first, Command)
    assert (first.seq, second.seq, third.seq) == (0, 1, 2)
    assert first.actor_id == "p1"
    assert first.args == {"to": (3, 4)}
    assert second.args == {"n": 10}
    assert third.args == {}


def test_drain_sorts_and_clears() -> None:
    """``drain`` сортирует по (turn, seq, actor_id) и очищает очередь."""
    q = CommandQueue()
    q.append("zeta", "recruit", {"n": 1}, turn=2)
    q.append("alpha", "recruit", {"n": 2}, turn=1)
    q.append("beta", "recruit", {"n": 3}, turn=1)
    drained = q.drain()
    assert [(c.turn, c.seq, c.actor_id) for c in drained] == [(1, 1, "alpha"), (1, 2, "beta"), (2, 0, "zeta")]
    assert len(q) == 0
    assert q.drain() == []


def test_drain_uses_actor_id_as_tiebreaker() -> None:
    """При равных (turn, seq) порядок решает actor_id."""
    cmd = Command(actor_id="b", type="recruit", args={}, turn=1, seq=5)
    other = Command(actor_id="a", type="recruit", args={}, turn=1, seq=5)
    assert [c.actor_id for c in sorted([cmd, other], key=Command.sort_key)] == ["a", "b"]


def test_peek_does_not_clear() -> None:
    """``peek`` возвращает тот же порядок, но не очищает очередь."""
    q = CommandQueue()
    q.append("p1", "recruit", turn=3)
    q.append("p1", "move_army", turn=1)
    first_peek = q.peek()
    second_peek = q.peek()
    assert [c.type for c in first_peek] == ["move_army", "recruit"]
    assert [c.type for c in second_peek] == ["move_army", "recruit"]
    assert len(q) == 2
    assert [c.type for c in q.drain()] == ["move_army", "recruit"]


def test_queue_len_and_iter() -> None:
    """Очередь поддерживает len и итерацию."""
    q = CommandQueue()
    assert len(q) == 0
    q.append("p1", "recruit")
    q.append("p2", "raise_levy")
    assert len(q) == 2
    assert [c.actor_id for c in q] == ["p1", "p2"]


def test_extend_adds_commands() -> None:
    """``extend`` добавляет готовые команды и продолжает нумерацию seq."""
    q = CommandQueue()
    q.extend([Command(actor_id="p1", type="recruit", args={}, turn=0, seq=10)])
    next_cmd = q.append("p2", "recruit")
    assert next_cmd.seq == 11
    assert len(q) == 2


def test_extend_rejects_non_commands() -> None:
    """``extend`` требует объекты Command."""
    with pytest.raises(TypeError):
        CommandQueue().extend([{"actor_id": "p1", "type": "recruit"}])


def test_clear_keeps_seq_monotonic() -> None:
    """``clear`` не сбрасывает счётчик seq — защита от повторной обработки."""
    q = CommandQueue()
    q.append("p1", "recruit")
    q.append("p1", "recruit")
    q.clear()
    assert len(q) == 0
    assert q.append("p1", "recruit").seq == 2


def test_validate_accepts_valid_command() -> None:
    """Валидная команда проходит проверку."""
    q = CommandQueue()
    for cmd_type in sorted(VALID_COMMAND_TYPES):
        q.validate(q.append("p1", cmd_type))


def test_validate_rejects_unknown_type() -> None:
    """Неизвестный тип команды кидает ValueError."""
    q = CommandQueue()
    with pytest.raises(ValueError):
        q.validate(Command(actor_id="p1", type="launch_missiles"))


def test_validate_rejects_empty_actor_id() -> None:
    """Пустой actor_id кидает ValueError."""
    q = CommandQueue()
    with pytest.raises(ValueError):
        q.validate(Command(actor_id="", type="recruit"))
    with pytest.raises(ValueError):
        q.validate(Command(actor_id="   ", type="recruit"))


def test_validate_rejects_non_command() -> None:
    """Валидатор требует объект Command."""
    with pytest.raises(TypeError):
        CommandQueue().validate("recruit")  # type: ignore[arg-type]


def test_valid_command_types_content() -> None:
    """Набор допустимых типов команд соответствует протоколу."""
    assert VALID_COMMAND_TYPES == frozenset(
        {
            "move_army",
            "recruit",
            "raise_levy",
            "grant_title",
            "revoke_title",
            "set_contract",
            "declare_war",
            "make_peace",
            "tax_policy",
            "grant_fief",
        }
    )
    assert len(VALID_COMMAND_TYPES) == 10


def test_command_is_immutable() -> None:
    """Command неизменяемый — его можно безопасно класть в лог."""
    cmd = Command(actor_id="p1", type="recruit")
    with pytest.raises(Exception):
        cmd.turn = 5  # type: ignore[misc]


def test_command_default_args_are_not_shared() -> None:
    """У экземпляров независимые словари args по умолчанию."""
    a = Command(actor_id="p1", type="recruit")
    b = Command(actor_id="p2", type="recruit")
    a.args["n"] = 1
    assert b.args == {}


def test_command_queue_replay_is_deterministic() -> None:
    """Один и тот же набор команд всегда даёт одинаковый порядок."""
    def build() -> List[Command]:
        q = CommandQueue()
        q.append("p2", "move_army", {"x": 1}, turn=1)
        q.append("p1", "move_army", {"x": 2}, turn=1)
        q.append("p3", "recruit", {"n": 5}, turn=0)
        return q.drain()

    # Порядок: (turn, seq) — p3 (turn 0), затем p2 (seq 0), затем p1 (seq 1).
    assert [c.actor_id for c in build()] == [c.actor_id for c in build()] == ["p3", "p2", "p1"]


def test_command_serializes_through_sim() -> None:
    """Команды сериализуются штатными средствами пакета."""
    q = CommandQueue()
    cmd = q.append("p1", "move_army", {"to": [1, 2]}, turn=4)
    back = loads(dumps(cmd))
    assert back == {"actor_id": "p1", "type": "move_army", "args": {"to": [1, 2]}, "turn": 4, "seq": 0}
    assert state_hash(back) == state_hash(to_jsonable(cmd))


def test_public_api_exports() -> None:
    """Все обещанные имена доступны из пакета ``sim``."""
    expected = {
        "NamedStreams",
        "state_hash",
        "hash_equal",
        "to_jsonable",
        "from_jsonable",
        "dumps",
        "loads",
        "SCHEMA_VERSION",
        "Command",
        "CommandQueue",
        "VALID_COMMAND_TYPES",
        "new_streams",
    }
    assert expected.issubset(set(sim.__all__))
    for name in expected:
        assert hasattr(sim, name)


def test_sim_has_no_project_imports() -> None:
    """Пакет ``sim`` не зависит от остальных модулей проекта и pygame."""
    import pathlib

    banned = ("pygame", "world_data", "states", "engine")
    root = pathlib.Path(sim.__file__).parent
    for path in root.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for name in banned:
            assert f"import {name}" not in text
