"""Фундамент детерминированной сервер-авторитетной симуляции.

Пакет намеренно изолирован: ни ``pygame``, ни импортов остальных модулей
проекта. Только стандартная библиотека — чтобы ядро симуляции можно было
перенести в отдельный серверный процесс без правок.

Что внутри:

* :class:`~sim.rng.NamedStreams` — именованные независимые потоки ГПСЧ;
* :func:`~sim.hashing.state_hash` — стабильный хеш состояния;
* :func:`~sim.serialization.dumps` / :func:`~sim.serialization.loads` — JSON;
* :class:`~sim.commands.CommandQueue` — детерминированный порядок команд.
"""

from __future__ import annotations

from .commands import VALID_COMMAND_TYPES, Command, CommandQueue
from .hashing import canonical, hash_equal, state_hash
from .rng import NamedStreams, new_streams
from .serialization import (
    SCHEMA_VERSION,
    dumps,
    envelope,
    from_jsonable,
    loads,
    register_enum,
    registered_enums,
    to_jsonable,
    unwrap,
)

__all__ = [
    "NamedStreams",
    "new_streams",
    "state_hash",
    "hash_equal",
    "canonical",
    "to_jsonable",
    "from_jsonable",
    "dumps",
    "loads",
    "envelope",
    "unwrap",
    "register_enum",
    "registered_enums",
    "SCHEMA_VERSION",
    "Command",
    "CommandQueue",
    "VALID_COMMAND_TYPES",
]
