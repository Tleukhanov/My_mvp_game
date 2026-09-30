"""Сериализация состояния в JSON-совместимый вид и обратно.

Формат на проводе стабильный: dataclass -> dict, Enum -> ``{"__enum__":
"ClassName.NAME"}``, set -> отсортированный список, tuple -> список,
datetime -> ISO-строки. Классы Enum запоминаются в реестре при сериализации,
чтобы ``from_jsonable`` мог их восстановить; неизвестный класс не роняет
десериализацию — возвращается исходная строка.
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
import enum
import json
from typing import Any, Dict, Set, Type

__all__ = [
    "SCHEMA_VERSION",
    "to_jsonable",
    "from_jsonable",
    "dumps",
    "loads",
    "envelope",
    "unwrap",
    "register_enum",
    "registered_enums",
]

#: Версия схемы обмена состояниями между сервером и клиентом.
SCHEMA_VERSION = 1

ENUM_TAG = "__enum__"
BYTES_TAG = "__bytes__"

# Имя класса Enum -> класс. Слабое удержание не нужно: Enum-классы живут вечно.
_ENUM_REGISTRY: Dict[str, Type[enum.Enum]] = {}


def register_enum(cls: Type[enum.Enum]) -> Type[enum.Enum]:
    """Зарегистрировать Enum-класс для обратной десериализации."""
    _ENUM_REGISTRY[cls.__name__] = cls
    return cls


def registered_enums() -> Set[str]:
    """Имена всех зарегистрированных Enum-классов (для отладки)."""
    return set(_ENUM_REGISTRY)


def _resolve_enum(class_name: str, member_name: str) -> Any:
    """Восстановить член Enum по имени класса и имени члена."""
    cls = _ENUM_REGISTRY.get(class_name)
    if cls is None:
        # Не знаем класс — возвращаем строку обратно, не падаем.
        return member_name
    try:
        return cls[member_name]
    except KeyError:
        pass
    try:
        return cls(member_name)
    except ValueError:
        return member_name


def to_jsonable(obj: Any) -> Any:
    """Рекурсивно превратить ``obj`` в JSON-совместимую структуру."""
    # Enum проверяем раньше int/str: IntEnum и StrEnum — их подклассы.
    if isinstance(obj, enum.Enum):
        register_enum(type(obj))
        return {ENUM_TAG: f"{type(obj).__name__}.{obj.name}"}
    if obj is None or isinstance(obj, (bool, int, str)):
        return obj
    if isinstance(obj, float):
        # repr(float) в Python 3 точен и детерминирован.
        return obj
    if isinstance(obj, (bytes, bytearray, memoryview)):
        return {BYTES_TAG: bytes(obj).hex()}
    if isinstance(obj, (_dt.datetime, _dt.date, _dt.time)):
        return obj.isoformat()
    if isinstance(obj, _dt.timedelta):
        return obj.total_seconds()
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_jsonable(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, dict):
        return {str(key): to_jsonable(value) for key, value in obj.items()}
    if isinstance(obj, (set, frozenset)):
        return sorted((to_jsonable(item) for item in obj), key=repr)
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(item) for item in obj]
    return repr(obj)


def from_jsonable(obj: Any) -> Any:
    """Обратное преобразование JSON-структуры в Python-объекты."""
    if isinstance(obj, dict):
        if ENUM_TAG in obj and isinstance(obj[ENUM_TAG], str):
            raw = obj[ENUM_TAG]
            class_name, _, member_name = raw.partition(".")
            if not member_name:
                member_name = class_name
                class_name = ""
            return _resolve_enum(class_name, member_name)
        if BYTES_TAG in obj and isinstance(obj[BYTES_TAG], str):
            return bytes.fromhex(obj[BYTES_TAG])
        return {key: from_jsonable(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [from_jsonable(item) for item in obj]
    return obj


def dumps(obj: Any, *, indent: int | None = None) -> str:
    """Сериализовать объект в JSON-строку (со стабильным порядком ключей)."""
    return json.dumps(
        to_jsonable(obj),
        indent=indent,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":") if indent is None else None,
    )


def loads(s: str) -> Any:
    """Десериализовать JSON-строку в Python-объект."""
    return from_jsonable(json.loads(s))


def envelope(obj: Any, *, schema_version: int = SCHEMA_VERSION) -> Dict[str, Any]:
    """Обернуть состояние в конверт с версией схемы."""
    return {"schema_version": int(schema_version), "payload": to_jsonable(obj)}


def unwrap(env: Dict[str, Any]) -> Any:
    """Извлечь состояние из конверта, проверив версию схемы.

    Бросает ``ValueError``, если схема неизвестна или конверт повреждён.
    """
    if not isinstance(env, dict):
        raise ValueError(f"envelope должен быть dict, получен {type(env).__name__}")
    if "schema_version" not in env:
        raise ValueError("в конверте отсутствует schema_version")
    if "payload" not in env:
        raise ValueError("в конверте отсутствует payload")
    version = env["schema_version"]
    if version != SCHEMA_VERSION:
        raise ValueError(f"несовпадение schema_version: ожидалось {SCHEMA_VERSION}, получено {version!r}")
    return from_jsonable(env["payload"])
