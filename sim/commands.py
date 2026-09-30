"""Команды игроков и очередь команд с детерминированным порядком.

Сервер принимает намерения игроков, сортирует их детерминированно и только
затем применяет к состоянию. Порядок задаётся тройкой
``(turn, seq, actor_id)``: ход, порядок добавления, идентификатор актора.
Именно этот порядок воспроизводится на клиенте и при реплее.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Iterator, List, Optional

__all__ = ["Command", "CommandQueue", "VALID_COMMAND_TYPES"]

#: Типы команд, которые симуляция принимает к исполнению.
VALID_COMMAND_TYPES = frozenset(
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


@dataclass(frozen=True)
class Command:
    """Одно намерение актора.

    Экземпляр неизменяемый (``frozen=True``), поэтому команда может свободно
    разлетаться по сети и храниться в логе.
    """

    actor_id: str
    type: str
    args: Dict[str, Any] = field(default_factory=dict)
    turn: int = 0
    seq: int = 0

    def sort_key(self) -> tuple[int, int, str]:
        """Ключ детерминированной сортировки: ``(turn, seq, actor_id)``."""
        return (self.turn, self.seq, self.actor_id)


def _sort_key(cmd: Command) -> tuple[int, int, str]:
    return cmd.sort_key()


class CommandQueue:
    """Очередь команд с монотонным ``seq`` и стабильной сортировкой."""

    def __init__(self) -> None:
        self._items: List[Command] = []
        self._next_seq: int = 0

    def append(
        self,
        actor_id: str,
        type: str,  # noqa: A002 - имя оставлено как в ТЗ
        args: Optional[Dict[str, Any]] = None,
        turn: int = 0,
    ) -> Command:
        """Создать команду с автоматическим ``seq`` и положить в очередь."""
        cmd = Command(
            actor_id=actor_id,
            type=type,
            args=dict(args) if args else {},
            turn=int(turn),
            seq=self._next_seq,
        )
        self._next_seq += 1
        self._items.append(cmd)
        return cmd

    def extend(self, cmds: Iterable[Command]) -> None:
        """Добавить несколько готовых команд, сохранив их ``seq``."""
        for cmd in cmds:
            if not isinstance(cmd, Command):
                raise TypeError(f"ожидался Command, получен {type(cmd).__name__}")
            self._items.append(cmd)
            if cmd.seq >= self._next_seq:
                self._next_seq = cmd.seq + 1

    def drain(self) -> List[Command]:
        """Вернуть команды в каноническом порядке и очистить очередь."""
        ordered = self.peek()
        self._items.clear()
        return ordered

    def peek(self) -> List[Command]:
        """Вернуть команды в каноническом порядке, не очищая очередь."""
        return sorted(self._items, key=_sort_key)

    def clear(self) -> None:
        """Удалить все команды (счётчик ``seq`` не сбрасывается)."""
        self._items.clear()

    def validate(self, cmd: Command) -> None:
        """Проверить команду, бросив ``ValueError`` при нарушении контракта."""
        if not isinstance(cmd, Command):
            raise TypeError(f"ожидался Command, получен {type(cmd).__name__}")
        if not isinstance(cmd.actor_id, str) or not cmd.actor_id.strip():
            raise ValueError("actor_id должен быть непустой строкой")
        if not isinstance(cmd.type, str) or cmd.type not in VALID_COMMAND_TYPES:
            raise ValueError(f"неизвестный тип команды: {cmd.type!r}")
        if not isinstance(cmd.args, dict):
            raise ValueError("args должен быть dict")
        if cmd.turn < 0:
            raise ValueError("turn не может быть отрицательным")

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self) -> Iterator[Command]:
        return iter(self._items)

    def __repr__(self) -> str:
        return f"CommandQueue(size={len(self._items)}, next_seq={self._next_seq})"
