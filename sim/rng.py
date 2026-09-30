"""Детерминированные именованные потоки случайных чисел.

Ключевая идея модуля: симуляция не должна зависеть от глобального состояния
``random`` и от порядка вызовов. Каждый логический поток (бой, ИИ, погода,
разброс бросков и т.д.) получает собственный генератор, выведенный из пары
``(seed, name)`` через ``hashlib``.

Почему именно ``hashlib`` и не встроенный ``hash()``: строковый ``hash()``
рандомизируется между запусками интерпретатора (PYTHONHASHSEED), поэтому
после рестарта сервера последовательности разъехались бы. ``hashlib.sha256``
детерминирован на любой платформе и в любом процессе.
"""

from __future__ import annotations

import hashlib
import random
from typing import Dict, Iterator, Optional, Tuple

__all__ = ["NamedStreams", "new_streams"]


def _seed_material(seed: int, name: str, salt: Optional[int] = None) -> int:
    """Превратить ``(seed, name, salt)`` в стабильный 64-битный int.

    Хешируется каноническая строка, поэтому результат не зависит ни от
    порядка вызовов, ни от наличия других потоков.
    """
    payload = f"{int(seed)}|{name}"
    if salt is not None:
        payload = f"{payload}|derive|{int(salt)}"
    digest = hashlib.sha256(payload.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


class _TrackedRandom(random.Random):
    """``random.Random`` со счётчиком извлечённых чисел (для дебага/тестов).

    Счётчик приблизительный: он растёт на переопределённых методах, а не на
    любых внутренних обращениях к ГПСЧ. Для задач симуляции этого достаточно,
    чтобы проверить «поток действительно потреялся».
    """

    def __init__(self, seed: int) -> None:
        super().__init__(seed)
        self.draws: int = 0

    def random(self) -> float:  # noqa: D102
        self.draws += 1
        return super().random()

    def getrandbits(self, k: int) -> int:  # noqa: D102
        self.draws += 1
        return super().getrandbits(k)

    def randrange(self, start: int, stop: Optional[int] = None, step: int = 1) -> int:  # noqa: D102
        self.draws += 1
        return super().randrange(start, stop, step)

    def randint(self, a: int, b: int) -> int:  # noqa: D102
        self.draws += 1
        return super().randint(a, b)

    def choice(self, seq):  # type: ignore[no-untyped-def]  # noqa: D102
        self.draws += 1
        return super().choice(seq)

    def choices(self, population, weights=None, *, cum_weights=None, k: int = 1):  # type: ignore[no-untyped-def]  # noqa: D102
        self.draws += k
        return super().choices(population, weights, cum_weights=k)

    def sample(self, population, k: int, *, counts: bool = False):  # type: ignore[no-untyped-def]  # noqa: D102
        self.draws += k
        return super().sample(population, k, counts=counts)  # type: ignore[arg-type]

    def shuffle(self, x, random=None):  # type: ignore[no-untyped-def]  # noqa: D102
        self.draws += 1
        return super().shuffle(x)

    def randbytes(self, n: int) -> bytes:  # noqa: D102
        self.draws += n
        return super().randbytes(n)


class NamedStreams:
    """Набор именованных, независимых и воспроизводимых потоков ГПСЧ.

    Гарантии:

    * ``stream("x")`` дважды с одним и тем же ``seed`` даёт одну и ту же
      последовательность, независимо от того, когда и в каком порядке
      создавались другие потоки;
    * потоки изолированы: расход ``stream("combat")`` не сдвигает
      ``stream("ai")``;
    * ``derive`` порождает ветвь от именованного потока, не зависящую от его
      текущего состояния (важно для replay и для серверной верификации).
    """

    def __init__(self, seed: int) -> None:
        self._seed: int = int(seed)
        self._streams: Dict[str, _TrackedRandom] = {}
        self._derived: Dict[Tuple[str, int], _TrackedRandom] = {}

    @property
    def seed(self) -> int:
        """Текущее базовое зерно."""
        return self._seed

    def stream(self, name: str) -> random.Random:
        """Вернуть (лениво создать) поток по имени.

        Повторные вызовы с тем же именем возвращают тот же объект, чтобы
        сохранялось позиционирование последовательности.
        """
        key = str(name)
        existing = self._streams.get(key)
        if existing is None:
            existing = _TrackedRandom(_seed_material(self._seed, key))
            self._streams[key] = existing
        return existing

    def derive(self, name: str, salt: int) -> random.Random:
        """Вернуть поток, ответвившийся от ``name`` с солью ``salt``.

        Ветвь выводится только из ``(seed, name, salt)``, поэтому
        ``derive("combat", 7)`` даёт одну и ту же последовательность всегда,
        даже если основной поток ``combat`` уже израсходован.
        """
        key = (str(name), int(salt))
        existing = self._derived.get(key)
        if existing is None:
            existing = _TrackedRandom(_seed_material(self._seed, key[0], key[1]))
            self._derived[key] = existing
        return existing

    def reseed(self, seed: int) -> None:
        """Сбросить зерно и выбросить все потоки (следующий ``stream`` — новый)."""
        self._seed = int(seed)
        self._streams.clear()
        self._derived.clear()

    def consumed(self, name: str, salt: Optional[int] = None) -> int:
        """Сколько чисел взято из потока ``name`` (для дебага и тестов).

        Для неизвестного потока возвращается 0, сам поток при этом не создаётся.
        """
        if salt is None:
            rnd = self._streams.get(str(name))
        else:
            rnd = self._derived.get((str(name), int(salt)))
        return 0 if rnd is None else rnd.draws

    def known_streams(self) -> Tuple[str, ...]:
        """Имена уже созданных базовых потоков (для отладки и логов)."""
        return tuple(sorted(self._streams))

    def clone(self) -> "NamedStreams":
        """Создать независимую копию с тем же зерном и той же позицией."""
        other = NamedStreams(self._seed)
        for key, rnd in self._streams.items():
            copied = _TrackedRandom(0)
            copied.setstate(rnd.getstate())
            copied.draws = rnd.draws
            other._streams[key] = copied
        for key, rnd in self._derived.items():
            copied = _TrackedRandom(0)
            copied.setstate(rnd.getstate())
            copied.draws = rnd.draws
            other._derived[key] = copied
        return other

    def __iter__(self) -> Iterator[str]:
        return iter(sorted(self._streams))

    def __len__(self) -> int:
        return len(self._streams)

    def __repr__(self) -> str:
        return f"NamedStreams(seed={self._seed}, streams={len(self._streams)})"


def new_streams(seed: int) -> NamedStreams:
    """Фабрика нового набора именованных потоков с заданным зерном."""
    return NamedStreams(seed)
