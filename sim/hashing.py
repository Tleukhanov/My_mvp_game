"""Канонизация объектов и вычисление стабильного хеша состояния.

Смысл: сервер и все клиенты должны уметь посчитать *одина и тот же* хеш
состояния мира. Для этого объект приводится к каноническому виду, который
убирает всё недетерминированное: порядок ключей dict, порядок элементов set,
различия типов-контейнеров, шум плавающей точки и представление объектов.
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
import enum
import hashlib
import json
import math
from typing import Any

__all__ = ["canonical", "state_hash", "hash_equal", "FLOAT_PRECISION"]

#: Сколько знаков после запятой сохраняем у float (остальное — шум ГПСЧ).
FLOAT_PRECISION = 9


def _round_float(value: float) -> float | int:
    """Округлить float до ``FLOAT_PRECISION`` знаков, сохранив целые как int."""
    if math.isnan(value) or math.isinf(value):
        return value
    rounded = round(value, FLOAT_PRECISION)
    if rounded == int(rounded) and abs(rounded) < 1e15:
        return int(rounded)
    return rounded


def canonical(obj: Any) -> Any:
    """Рекурсивно привести ``obj`` к детерминированному виду.

    Поддерживаются ``dict``/``Mapping``, ``set``/``frozenset``, ``list``/``tuple``,
    ``Enum``, dataclass-ы, ``datetime``/``date``/``time``, ``float``, ``int``,
    ``str``, ``bool``, ``None``, ``bytes``. Для всего остального используется
    ``repr`` — функция никогда не падает на неизвестных типах.
    """
    # Enum проверяем раньше int/str: IntEnum и StrEnum — их подклассы.
    if isinstance(obj, enum.Enum):
        return obj.name
    # bool проверяем раньше int: bool — подкласс int.
    if obj is None or isinstance(obj, bool):
        return obj
    if isinstance(obj, int):
        return obj
    if isinstance(obj, float):
        return _round_float(obj)
    if isinstance(obj, str):
        return obj
    if isinstance(obj, (bytes, bytearray, memoryview)):
        return bytes(obj).hex()
    if isinstance(obj, (_dt.datetime, _dt.date, _dt.time)):
        return obj.isoformat()
    if isinstance(obj, _dt.timedelta):
        return obj.total_seconds()
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: canonical(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, dict):
        return {str(key): canonical(value) for key, value in sorted(obj.items(), key=lambda kv: repr(kv[0]))}
    if isinstance(obj, (set, frozenset)):
        items = [canonical(item) for item in obj]
        return sorted(items, key=repr)
    if isinstance(obj, (list, tuple)):
        return [canonical(item) for item in obj]
    return repr(obj)


def state_hash(obj: Any) -> str:
    """sha1-хеш (hex) канонического представления ``obj``.

    Хеш не зависит от порядка ключей, от порядка элементов множеств и от
    младших различий во floats.
    """
    payload = json.dumps(
        canonical(obj),
        sort_keys=True,
        separators=(",", ":"),
        default=repr,
        ensure_ascii=True,
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def hash_equal(a: Any, b: Any) -> bool:
    """True, если состояния ``a`` и ``b`` дают одинаковый хеш."""
    return state_hash(a) == state_hash(b)
