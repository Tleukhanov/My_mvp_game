"""Измерительный стенд для тактического боя: считаем баланс, а не гадаем о нём.

Зачем модуль. Тактический экран нельзя проверить глазами в этой среде, а связь
«4:1 по солдатам → 4:1 по исходу» нигде не записана: после переноса перевеса в
прочность отрядов (``GameEngine._troops_per_unit_scale``) сила армии
определяется суммарным HP, а исход боя — результат того, кто кого первый
добьёт. Настраивать коэффициент, который нечем померить, — значит погадать,
поэтому здесь лежит прогон боя целиком без экрана и честная арифметика поверх
сотен прогонов.

Как устроен бой в стенде.

* :class:`GameEngine` создаётся из :class:`war.WarSession` — это ровно тот путь,
  которым мир открывает экран сражения;
* движок тикается вручную фиксированным шагом ``dt`` через ``_update``: ни
  ``_handle_events``, ни ``_render``, ни ``pygame.quit`` не нужны — событий в
  стенде нет, отрисовка ничего не решает, а ``pygame.quit`` убил бы поверхность
  мировой карты, поверх которой тактический бой и открывается;
* конец боя — ``_game_over`` / ``_winner``, которые ставит ``_check_game_over``.

Про ИИ — самое важное для честности замера. В движке ИИ есть **только у
красных**: ``_setup_units`` регистрирует в ``AIController`` лишь ``red_units``,
а синими управляет игрок. Если просто не слать приказов, синяя армия стоит
колонной и не бьёт вообще — это не «слабая сторона», это отсутствие игрока.
Поэтому у боя два режима:

* ``mirror_ai=False`` — честная реконструкция «игрок не играет». Такая цифра
  полезна ровно одним способом: она показывает, что без человека бой не
  измеряется вовсе;
* ``mirror_ai=True`` (по умолчанию) — зеркальный режим: и синим, и красным
  раздаётся **один и тот же** ``AIController`` из ``ai.py``, просто у каждого
  свой контроллер, а «врагами» для него служит противоположная сторона. Это
  A-против-A на симметричной карте, и именно эта цифра отвечает на вопрос
  «кто сильнее при равном левейсе».

Зеркальный режим ничего не «подкручивает» под себя: он не меняет ни одного
числа движка, не подменяет формул и не подстраивается под исход. Если движок
или ИИ предвят — предвзятость проявится здесь в цифрах, а не спрячется.

Детерминизм. ГПСЧ в тактическом бою один и только один — глобальный
``random``: его дёргает ``UnitAI.__init__`` (``_flank_side``). Зерно сессии
движок не читает вовсе, поэтому повторяемость даёт только ``random.seed``
перед созданием движка. Ставим его на каждый бой — иначе «прогон по 30
зернам» был бы одним и тем же боем, повторённым 30 раз.
"""

from __future__ import annotations

import os

# Драйверы SDL задаются ДО ``import pygame`` (который тянет за собой engine):
# иначе на машине без дисплея импорт упадёт. setdefault, а не присваивание,
# чтобы не мешать вызывающему коду, который уже выбрал драйвер сам.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import argparse
import math
import random
import time
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence, Tuple

import pygame

from ai import AIController
from engine import GameEngine
from war import QUALITY_MIN, TROOPS_PER_TACTICAL_UNIT, WarSession

__all__ = [
    "BLUE", "RED", "DRAW", "UNRESOLVED",
    "DEFAULT_DT", "DEFAULT_MAX_TICKS", "DEFAULT_STALL_TICKS",
    "BattleSpec", "BattleReport", "SweepRow",
    "run_battle", "run_sweep", "probe_battle",
    "wilson_interval", "exact_binomial_two_sided",
    "format_table", "main",
]

#: Фиксированный шаг симуляции. Игра тикает 1/60, но стенду важнее скорость:
#: 1/30 вдвое сокращает число тиков при том же порядке величин (погрешность на
#: кулдауне атаки 0.8 с — один тик из 24). Сверка «1/60 и 1/30 дают один
#: исход» живёт в test_balance.py, чтобы ускорение не было спрятанной
#: подменой физики.
DEFAULT_DT = 1.0 / 30.0

#: Предохранитель по длине боя. Стычка в этом движке идёт медленно (юниты
#: сближаются рывками, путь пересчитывается раз в секунду) и часто не
#: добивает противника, поэтому часть боёв честно не доигрывается. Это тоже
#: результат, и «не доиграно» нельзя молча считать победой сильного.
DEFAULT_MAX_TICKS = 30 * 600  # 600 секунд игрового времени

#: По сколько тиков допустимо НЕ получать урона, прежде чем бой признаётся
#: замершим. Нужен, чтобы не платить полную цену за бой, который всё равно не
#: закончится: раненые юниты отступают и застревают в столкновениях, и счётчик
#: HP не меняется сотнями секунд. Порог заведомо больше времени сближения
#: (~15-20 с на 9 отрядов), иначе стенд объявил бы замершим здоровый бой.
#: Ноль отключает проверку; test_balance.py сверяет её вердикт с полным прогоном.
DEFAULT_STALL_TICKS = 30 * 60  # 60 секунд без единого полученного удара

#: Исходы боя в терминах стенда.
BLUE = "blue"
RED = "red"
DRAW = "draw"
UNRESOLVED = "unresolved"

_WINNER_MAP = {
    "BLUE WINS": BLUE,
    "RED WINS": RED,
    "DRAW": DRAW,
}


@dataclass(frozen=True)
class BattleSpec:
    """Один прогон боя.

    Поля:

    * ``attacker_troops`` / ``defender_troops`` — левейс сторон в солдатах;
    * ``quality`` — выучка из сессии (1..4, ``war.clamp_quality`` срежет в 3);
    * ``seed`` — зерно глобального ``random`` на время боя;
    * ``mirror_ai`` — зеркалить ли ИИ на синих (см. модульный докстринг);
    * ``jitter_px`` — разброс начальных позиций в пикселях (см. ниже);
    * ``dt`` / ``max_ticks`` / ``stall_ticks`` — шаг симуляции, предохранители
      по длине и по «зависанию».

    Про ``jitter_px``. Зерно сессии движок не читает, а единственный потребитель
    глобального ``random`` — ``UnitAI._flank_side``, который читается только в
    состоянии FLANK, куда попадает только кавалерия, а войска из сессии сплошь
    пехота. Проверено: шесть разных зёрен дают БАЙТ-в-байт одинаковый бой.
    Значит «прогон по N зёрнам» — это один и тот же бой, повторённый N раз, и
    разброс win_rate в честном замере всегда ровно нулевой. Единственный
    оставшийся способ получить распределение исходов — сдвинуть начальные
    условия на считаные пиксели: армии те же, карта та же, различается только
    микроскопический расклад колонн. Это разброс «по равным боям», а не
    «по разным правилам»: ни один коэффициент движка при этом не меняется, и
    симметрия сдвига (плюс-минус, всем юнитам одинаково) не может сместить
    результат в чью-то пользу намеренно.
    """

    attacker_troops: int
    defender_troops: int
    quality: int = QUALITY_MIN
    seed: int = 0
    mirror_ai: bool = True
    jitter_px: float = 0.0
    dt: float = DEFAULT_DT
    max_ticks: int = DEFAULT_MAX_TICKS
    stall_ticks: int = DEFAULT_STALL_TICKS
    #: Заморозить бой: юниты не двигаются и не бьются. Нужно стенду, чтобы
    #: проверять СВОЙ предохранитель зависания на заведомо мёртвом бою.
    #: Раньше такой фикстурой был дедлок самого движка (равные армии не
    #: доигрывались), и тест зависания падал вместе с ним; после починки
    #: дедлока заморозка должна быть задана явно, иначе проверять нечего.
    frozen: bool = False

    @property
    def troop_ratio(self) -> float:
        """Во сколько раз у атакующего больше солдат."""
        if self.defender_troops <= 0:
            return float("inf")
        return self.attacker_troops / float(self.defender_troops)

    @property
    def stronger(self) -> str:
        """Какая сторона сильнее; при равенстве — синий (см. ``run_sweep``)."""
        if self.attacker_troops >= self.defender_troops:
            return BLUE
        return RED

    @property
    def label(self) -> str:
        return f"{self.attacker_troops}:{self.defender_troops}"


@dataclass(frozen=True)
class BattleReport:
    """Что получилось в одном бою."""

    spec: BattleSpec
    outcome: str
    ticks: int
    blue_alive: int
    red_alive: int
    blue_hp: int
    red_hp: int
    blue_start_hp: int
    red_start_hp: int
    blue_start_units: int
    red_start_units: int
    stalled: bool = False

    @property
    def seconds(self) -> float:
        """Длительность боя в игровых секундах."""
        return self.ticks * self.spec.dt

    @property
    def resolved(self) -> bool:
        """Бой доигран до явного исхода (ничья считается исходом)."""
        return self.outcome in (BLUE, RED, DRAW)

    @property
    def hp_ratio(self) -> float:
        """Во сколько раз больше суммарного HP у синих, чем у красных."""
        return (self.blue_start_hp / float(self.red_start_hp)
                if self.red_start_hp else float("inf"))

    def stronger_won(self) -> bool:
        return self.outcome == self.spec.stronger


def _make_session(spec: BattleSpec) -> WarSession:
    """Билет в бой. Нация/генерал тут не важны — важны левейс, качество, зерно."""
    return WarSession(
        match_id=int(spec.seed) + 1,
        attacker_nation="fra",
        defender_nation="eng",
        province_idx=0,
        general_name="BALANCE",
        troops_committed=int(spec.attacker_troops),
        defender_troops=int(spec.defender_troops),
        quality=int(spec.quality),
        seed=int(spec.seed),
        player_attacker=True,
    )


def _build_engine(spec: BattleSpec) -> GameEngine:
    """Собрать движок с заданным зерном.

    Зерно глобального ``random`` ставится ДО создания: ``UnitAI`` тянет из него
    ``_flank_side`` прямо в конструкторе, и без этого «прогон по зёрнам» был бы
    копией одного и того же боя.
    """
    random.seed(int(spec.seed))
    engine = GameEngine(session=_make_session(spec))
    _jitter_positions(engine, spec)
    return engine


def _jitter_positions(engine: GameEngine, spec: BattleSpec) -> None:
    """Сдвинуть стартовые позиции на ``±jitter_px`` (см. докстринг ``BattleSpec``).

    Отдельный генератор с ключом-строкой: глобальный ``random`` движка при этом
    не расходуется, и зерно боя остаётся ровно тем же, что и без сдвига.
    """
    jitter = float(spec.jitter_px)
    if jitter <= 0.0:
        return
    rng = random.Random(f"balance|jitter|{int(spec.seed)}|{jitter!r}")
    for unit in engine.all_units:
        unit.x += rng.uniform(-jitter, jitter)
        unit.y += rng.uniform(-jitter, jitter)


def _mirror_blue_ai(engine: GameEngine) -> AIController:
    """Второй ``AIController`` — ровно для синих, код из ``ai.py`` без правок.

    Отдельный контроллер нужен потому, что ``AIController.update`` получает
    СПИСОК ВРАГОВ ОДИН И ТОТ ЖЕ для всех зарегистрированных юнитов: если
    зарегистрировать в нём и синих, то синий ИИ увидит врагами синих же.
    Разведение по контроллерам даёт честное A-против-A: один и тот же класс
    ``UnitAI``, одни и те же таймеры и пороги отступления — различаются только
    стороны.
    """
    controller = AIController(engine.pathfinder)
    for unit in engine.blue_units:
        controller.register_unit(unit)
    return controller


def _total_hp(units: Sequence) -> int:
    return sum(int(u.health) for u in units if u.alive)


def _alive(units: Sequence) -> int:
    return sum(1 for u in units if u.alive)


def _freeze_engage(engine: GameEngine):
    """Заморозить бой: сбросить приказы и вернуть юнитов на исходные места.

    Суммарное здоровье не меняется, ни одна пара не сближается — то есть
    ровно то состояние, ради которого в стенде и нужен предохранитель.
    """
    home = getattr(engine, "_balance_home", None)
    if home is None:
        home = {id(u): (u.x, u.y) for u in engine.all_units}
        engine._balance_home = home
    for unit in engine.all_units:
        if not unit.alive:
            continue
        unit.x, unit.y = home[id(unit)]
        unit.clear_orders()


def _drive(engine: GameEngine, spec: BattleSpec,
           blue_ai: Optional[AIController]) -> Tuple[int, str, bool]:
    """Прогнать бой до конца. Возвращает (тики, исход, признак зависания).

    Синий ИИ (если он есть) обновляется в том же тике сразу после
    ``_update``: сам ``_update`` двигает юнитов, считает деревни и проверяет
    конец партии, и добавлять синюю фазу раньше означало бы, что она видит
    позиции прошлого тика, а красная — текущего.
    """
    villages = engine.game_map.get_all_villages()
    owners = engine.game_map.village_owners
    stall_limit = max(0, int(spec.stall_ticks))

    ticks = 0
    quiet_ticks = 0
    last_hp = -1
    stalled = False

    for _ in range(max(1, int(spec.max_ticks))):
        ticks += 1
        if spec.frozen:
            _freeze_engage(engine)
        engine._update(spec.dt)

        hp = _total_hp(engine.blue_units) + _total_hp(engine.red_units)
        if hp == last_hp:
            quiet_ticks += 1
        else:
            quiet_ticks = 0
            last_hp = hp

        if engine._game_over:
            return (ticks, _WINNER_MAP.get(engine._winner, UNRESOLVED), False)

        if blue_ai is not None:
            # remove_dead() уже отсекает мёртвых, поэтому длина списка — это
            # ровно число живых синих под управлением ИИ.
            if not blue_ai._unit_ais:
                break
            blue_ai.update(spec.dt,
                           [u for u in engine.red_units if u.alive],
                           villages, owners)
            blue_ai.remove_dead()

        if stall_limit and quiet_ticks >= stall_limit:
            stalled = True
            break

    return (ticks, _WINNER_MAP.get(engine._winner, UNRESOLVED), stalled)


def _report(engine: GameEngine, spec: BattleSpec, ticks: int,
            outcome: str, stalled: bool,
            start_hp: Optional[Tuple[int, int]] = None) -> BattleReport:
    if start_hp is None:
        start_hp = (_total_hp(engine.blue_units), _total_hp(engine.red_units))
    return BattleReport(
        spec=spec,
        outcome=outcome,
        ticks=ticks,
        blue_alive=_alive(engine.blue_units),
        red_alive=_alive(engine.red_units),
        blue_hp=_total_hp(engine.blue_units),
        red_hp=_total_hp(engine.red_units),
        blue_start_hp=start_hp[0],
        red_start_hp=start_hp[1],
        blue_start_units=len(engine.blue_units),
        red_start_units=len(engine.red_units),
        stalled=stalled,
    )


def run_battle(spec: BattleSpec) -> BattleReport:
    """Прогнать бой как есть: без единой правки чисел движка.

    Это единственная функция, которой меряется поставленный движок. Всё
    остальное в модуле либо считает по её отчётам, либо честно помечено как
    контрфакт.
    """
    engine = _build_engine(spec)
    start_hp = (_total_hp(engine.blue_units), _total_hp(engine.red_units))
    blue_ai = _mirror_blue_ai(engine) if spec.mirror_ai else None
    ticks, outcome, stalled = _drive(engine, spec, blue_ai)
    return _report(engine, spec, ticks, outcome, stalled, start_hp)


# ---------------- контрфакты: «а что было бы, если бы...» ----------------
#
# Ниже — НЕ измерение, а проверка гипотез: «если бы коэффициент в engine.py
# был таким, исход стал бы таким». Числа движка тут не меняются и не читаются
# по-старому; меняется ТОЛЬКО здоровье уже собранных юнитов, что даёт тот же
# результат, что и правка ``_troops_per_unit_scale`` (все коэффициенты
# линейные и целочисленно округляются один раз). Основной замер от этого не
# зависит: ``run_battle`` выше ничего из этого блока не касается.

def _apply_hp_factor(units: Sequence, factor: float) -> None:
    """Умножить здоровье и максимум здоровья отряда на ``factor``.

    Порядок ровно тот, что в ``GameEngine._make_warrior``: сначала масштаб от
    числа солдат, потом качество, округление — в конце. Поэтому результат
    совпадает с тем, что дала бы правка самого масштаба.
    """
    if factor == 1.0:
        return
    for unit in units:
        unit.max_health = max(1, int(round(unit.max_health * factor)))
        unit.health = unit.max_health


def _lognormal_luck(seed: int, side: str, sigma: float) -> float:
    """Множитель силы на бой, разбросанный логнормально.

    Отдельный генератор с ключом (зерно, сторона): бой синего и бой красного
    получают независимые значения, а глобальный ``random`` движка при этом не
    расходуется — иначе контрфакт искажал бы и честный замер.
    """
    if sigma <= 0.0:
        return 1.0
    # Ключ-строка, а не кортеж: random.seed принимает только None/int/float/str/
    # bytes, и кортеж молча пришёл бы в исключение на середине отчёта.
    z = random.Random(f"balance|luck|{int(seed)}|{side}").gauss(0.0, 1.0)
    return math.exp(sigma * z)


def _exponent_factor(troops: int, units: int, exponent: float) -> float:
    """Множитель, превращающий линейный масштаб отряда в степенной.

    Движок даёт ``(солдат на отряд) / 100``; предлагаемая правка даёт то же
    самое в степени ``exponent``. Разница и есть искомый множитель. Ровно так
    же выглядит правка в ``engine.py``::

        return max(1.0, (raw / n) / float(TROOPS_PER_TACTICAL_UNIT)) ** EXPONENT
    """
    per_unit = max(1.0, (max(0, int(troops)) / max(1, int(units)))
                   / float(TROOPS_PER_TACTICAL_UNIT))
    return per_unit ** (float(exponent) - 1.0)


def probe_battle(spec: BattleSpec, exponent: float = 1.0,
                 luck_sigma: float = 0.0) -> BattleReport:
    """Контрфакт: прогнать бой с другим законом масштаба HP.

    ``exponent=1.0`` — ровно то, что делает движок сейчас (контрольная
    проверка, что подпорки не искажают замер). ``exponent<1`` — приглушённый
    перевес, ``luck_sigma>0`` — разброс силы от боя к бою.
    """
    engine = _build_engine(spec)
    blue_ai = _mirror_blue_ai(engine) if spec.mirror_ai else None

    session = engine.session
    units = session.battle_units
    blue_factor = (_exponent_factor(session.troops_committed, units, exponent)
                   * _lognormal_luck(spec.seed, "blue", luck_sigma))
    red_factor = (_exponent_factor(session.defender_troops or 0, units, exponent)
                  * _lognormal_luck(spec.seed, "red", luck_sigma))
    _apply_hp_factor(engine.blue_units, blue_factor)
    _apply_hp_factor(engine.red_units, red_factor)
    start_hp = (_total_hp(engine.blue_units), _total_hp(engine.red_units))
    ticks, outcome, stalled = _drive(engine, spec, blue_ai)
    return _report(engine, spec, ticks, outcome, stalled, start_hp)


def probe_team_order(spec: BattleSpec, mode: str = "natural") -> BattleReport:
    """Диагностика: тот же бой при другом порядке юнитов в ``engine.all_units``.

    Не измерение, а вскрытие механизма. ``Unit._resolve_collisions`` правит
    координаты НА ХОДУ, обходя ``all_units`` как есть (метод Гаусса-Зейделя, а
    не Якоби), поэтому исход боя зависит от порядка элементов списка. Список
    всегда собирается как «сначала синие, потом красные», и на карте, которая
    заявлена симметричной относительно вертикали, это делает синюю сторону
    привилегированной. Здесь это видно буквально: при mode="red-first" синие
    идут в списке вторыми — и при равном левейсе выигрывают уже красные.

    Режимы:

    * ``natural`` — порядок как в движке (синие первыми);
    * ``red-first`` — блок красных переставлен вперёд;
    * ``shuffled`` — случайная перестановка с ключом из ``spec.seed``.
    """
    engine = _build_engine(spec)
    blue_ai = _mirror_blue_ai(engine) if spec.mirror_ai else None
    if mode == "red-first":
        reordered = engine.red_units + engine.blue_units
    elif mode == "shuffled":
        reordered = list(engine.all_units)
        random.Random(int(spec.seed)).shuffle(reordered)
    elif mode == "natural":
        reordered = None
    else:
        raise ValueError(f"неизвестный режим порядка: {mode!r}")
    if reordered is not None:
        engine.all_units = reordered
        # Списки сторон тоже переставляются: иначе «враги» для ИИ и порядок
        # раздачи целей останутся прежними и подмена ничего не покажет.
        engine.blue_units = [u for u in reordered if u.team.value == BLUE]
        engine.red_units = [u for u in reordered if u.team.value == RED]
    start_hp = (_total_hp(engine.blue_units), _total_hp(engine.red_units))
    ticks, outcome, stalled = _drive(engine, spec, blue_ai)
    return _report(engine, spec, ticks, outcome, stalled, start_hp)


@dataclass(frozen=True)
class SweepRow:
    """Агрегат по одному соотношению левейса на всех зёрнах."""

    attacker_troops: int
    defender_troops: int
    quality: int
    seeds: int
    stronger: str
    wins: int
    losses: int
    draws: int
    unresolved: int
    stalled: int
    avg_seconds: float
    avg_ticks: float
    avg_stronger_alive: float
    avg_weaker_alive: float
    avg_stronger_hp: float
    avg_weaker_hp: float
    avg_hp_ratio: float
    battles: List[BattleReport] = field(default_factory=list, repr=False)

    @property
    def decided(self) -> int:
        """Сколько боёв доигралось до явного исхода."""
        return self.wins + self.losses + self.draws

    @property
    def win_rate(self) -> float:
        """Доля побед сильного на ВСЕХ зёрнах (недоигранное — не победа)."""
        return self.wins / float(self.seeds) if self.seeds else 0.0

    @property
    def decided_win_rate(self) -> float:
        """Доля побед сильного среди доигранных боёв."""
        return self.wins / float(self.decided) if self.decided else 0.0

    @property
    def blue_wins(self) -> int:
        return sum(1 for b in self.battles if b.outcome == BLUE)

    @property
    def red_wins(self) -> int:
        return sum(1 for b in self.battles if b.outcome == RED)

    @property
    def ci_low(self) -> float:
        return wilson_interval(self.wins, self.seeds)[0]

    @property
    def ci_high(self) -> float:
        return wilson_interval(self.wins, self.seeds)[1]

    @property
    def label(self) -> str:
        return f"{self.attacker_troops}:{self.defender_troops}"

    @property
    def ratio(self) -> float:
        return (self.attacker_troops / float(self.defender_troops)
                if self.defender_troops else float("inf"))


def wilson_interval(successes: int, trials: int,
                    z: float = 1.959963985) -> Tuple[float, float]:
    """Доверительный интервал Уилсона по доле успеха.

    Именно Уилсон, а не «p ± 1.96*sqrt(p(1-p)/n)»: на малых выборках и при
    p, близком к 0 или 1, нормальное приближение рисует ложную уверенность,
    а нам нужен честный разброс по зёрнам.
    """
    n = int(trials)
    if n <= 0:
        return (0.0, 1.0)
    k = int(successes)
    phat = k / n
    denom = 1.0 + (z * z) / n
    center = (phat + (z * z) / (2 * n)) / denom
    spread = (z / denom) * math.sqrt(phat * (1 - phat) / n
                                     + z * z / (4 * n * n))
    return (max(0.0, center - spread), min(1.0, center + spread))


def exact_binomial_two_sided(successes: int, trials: int,
                             p: float = 0.5) -> float:
    """Двусторонний точный критерий Бернулли: P(|X - n p| >= |k - n p|).

    Суммированием хвостов, а не нормальным приближением: на n = 12 нормальное
    приближение заметно завышает значимость, а именно на таких выборках
    придётся ставить тесты.
    """
    n = int(trials)
    if n <= 0:
        return 1.0
    k = int(successes)
    mean = n * p
    tail = 0.0
    for i in range(n + 1):
        if abs(i - mean) >= abs(k - mean) - 1e-12:
            tail += math.comb(n, i) * (p ** i) * ((1.0 - p) ** (n - i))
    return min(1.0, tail)


def run_sweep(attacker_troops: int, defender_troops: int,
              seeds: Iterable[int], quality: int = QUALITY_MIN,
              mirror_ai: bool = True, dt: float = DEFAULT_DT,
              max_ticks: int = DEFAULT_MAX_TICKS,
              stall_ticks: int = DEFAULT_STALL_TICKS,
              jitter_px: float = 0.0,
              exponent: float = 1.0, luck_sigma: float = 0.0) -> SweepRow:
    """Прогнать набор зёрен для одного соотношения и посчитать агрегат.

    ``jitter_px``/``exponent``/``luck_sigma`` в дефолте — чистый замер
    поставленного движка; остальные значения переключают замер на
    контрфакт ``probe_battle`` (см. предупреждение в модуле).
    """
    seed_list = [int(s) for s in seeds]
    probe = not (float(exponent) == 1.0 and float(luck_sigma) == 0.0)
    reports = []
    for s in seed_list:
        spec = BattleSpec(
            attacker_troops=attacker_troops,
            defender_troops=defender_troops,
            quality=quality,
            seed=s,
            mirror_ai=mirror_ai,
            jitter_px=jitter_px,
            dt=dt,
            max_ticks=max_ticks,
            stall_ticks=stall_ticks,
        )
        if probe:
            reports.append(probe_battle(spec, exponent=exponent,
                                        luck_sigma=luck_sigma))
        else:
            reports.append(run_battle(spec))

    stronger = BattleSpec(attacker_troops, defender_troops).stronger
    wins = sum(1 for r in reports if r.outcome == stronger)
    losses = sum(1 for r in reports
                 if r.outcome in (BLUE, RED) and r.outcome != stronger)
    draws = sum(1 for r in reports if r.outcome == DRAW)
    unresolved = sum(1 for r in reports if r.outcome == UNRESOLVED)

    def _avg(values: Sequence[float]) -> float:
        return float(sum(values) / len(values)) if values else 0.0

    def _side(rep: BattleReport, team: str) -> Tuple[int, int]:
        if team == BLUE:
            return rep.blue_alive, rep.blue_hp
        return rep.red_alive, rep.red_hp

    strong_alive, strong_hp, weak_alive, weak_hp = [], [], [], []
    for rep in reports:
        sa, shp = _side(rep, stronger)
        wa, whp = _side(rep, RED if stronger == BLUE else BLUE)
        strong_alive.append(float(sa))
        strong_hp.append(float(shp))
        weak_alive.append(float(wa))
        weak_hp.append(float(whp))

    return SweepRow(
        attacker_troops=int(attacker_troops),
        defender_troops=int(defender_troops),
        quality=int(quality),
        seeds=len(reports),
        stronger=stronger,
        wins=wins,
        losses=losses,
        draws=draws,
        unresolved=unresolved,
        stalled=sum(1 for r in reports if r.stalled),
        avg_seconds=_avg([r.seconds for r in reports]),
        avg_ticks=_avg([float(r.ticks) for r in reports]),
        avg_stronger_alive=_avg(strong_alive),
        avg_weaker_alive=_avg(weak_alive),
        avg_stronger_hp=_avg(strong_hp),
        avg_weaker_hp=_avg(weak_hp),
        avg_hp_ratio=_avg([r.hp_ratio for r in reports]),
        battles=reports,
    )


def format_table(rows: Sequence[SweepRow], title: str = "") -> str:
    """Человекочитаемая таблица: её же печатает ``main``."""
    header = (f"{'lev':>10} {'ratio':>6} {'q':>2} {'seeds':>5} {'win%':>6} "
              f"{'95% CI':>13} {'dec%':>6} {'timeout':>7} {'sec':>6} {'ticks':>6} "
              f"{'str_al':>6} {'weak_al':>7} {'str_hp':>7} {'weak_hp':>7} {'hp_x':>6}")
    lines = [title] if title else []
    lines.append(header)
    lines.append("-" * len(header))
    for row in rows:
        ratio = f"{row.ratio:.2f}" if row.defender_troops else "inf"
        lines.append(
            f"{row.label:>10} {ratio:>6} {row.quality:>2} {row.seeds:>5} "
            f"{row.win_rate * 100:6.1f} "
            f"[{row.ci_low * 100:5.1f},{row.ci_high * 100:5.1f}] "
            f"{row.decided_win_rate * 100:6.1f} {row.unresolved:>7} "
            f"{row.avg_seconds:6.1f} {row.avg_ticks:6.0f} "
            f"{row.avg_stronger_alive:6.2f} {row.avg_weaker_alive:7.2f} "
            f"{row.avg_stronger_hp:7.0f} {row.avg_weaker_hp:7.0f} "
            f"{row.avg_hp_ratio:6.2f}")
    return "\n".join(lines)


#: Соотношения для отчётного прогона. Вокруг спорных точек (1:1, 2:1, 4:1,
#: 7.5:1) стоят соседние значения — по переходу видно, где именно шагает исход.
REPORT_RATIOS: Tuple[Tuple[int, int], ...] = (
    (500, 500),
    (1200, 1200),
    (2400, 1200),
    (3000, 1500),
    (4800, 1200),
    (3000, 400),
)


def _ensure_pygame() -> None:
    """Поднять pygame и пустую поверхность: движок просит ``set_mode``."""
    if not pygame.get_init():
        pygame.init()
    if pygame.display.get_surface() is None:
        pygame.display.set_mode((1, 1))


def format_order_probe(spec: BattleSpec,
                       modes: Sequence[str] = ("natural", "red-first",
                                               "shuffled")) -> str:
    """Таблица «тот же бой, другой порядок юнитов» — вскрытие перекоса."""
    lines = [f"{'order':>10} {'outcome':>10} {'ticks':>7} "
             f"{'blue alive':>10} {'red alive':>9}"]
    for mode in modes:
        report = probe_team_order(spec, mode=mode)
        lines.append(f"{mode:>10} {report.outcome:>10} {report.ticks:7d} "
                     f"{report.blue_alive:10d} {report.red_alive:9d}")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI стенда: напечатать таблицу замеров.

    Нужен для воспроизводимости отчёта: цифры в отчёте должны уметь получить
    заново любой, а не «мы когда-то померили».
    """
    parser = argparse.ArgumentParser(description="balance sweep for tactical battles")
    parser.add_argument("--seeds", type=int, default=24,
                        help="сколько зёрен на одно соотношение (default 24)")
    parser.add_argument("--seed0", type=int, default=1,
                        help="первое зерно (default 1)")
    parser.add_argument("--quality", type=int, default=QUALITY_MIN)
    parser.add_argument("--dt", type=float, default=DEFAULT_DT)
    parser.add_argument("--max-ticks", type=int, default=DEFAULT_MAX_TICKS)
    parser.add_argument("--stall-ticks", type=int, default=DEFAULT_STALL_TICKS)
    parser.add_argument("--jitter", type=float, default=0.0,
                        help="разброс стартовых позиций в пикселях (default 0)")
    parser.add_argument("--exponent", type=float, default=1.0)
    parser.add_argument("--luck-sigma", type=float, default=0.0)
    parser.add_argument("--passive", action="store_true",
                        help="без зеркального ИИ: синие стоят и не бьют")
    parser.add_argument("--ratios", default="",
                        help="свой список 'a:d,a:d,...' вместо REPORT_RATIOS")
    parser.add_argument("--order-probe", default="",
                        help="диагностика порядка юнитов на 'a:d' "
                             "(например 1200:1200)")
    args = parser.parse_args(argv)

    _ensure_pygame()
    seeds = list(range(args.seed0, args.seed0 + args.seeds))
    if args.ratios:
        ratios = tuple(tuple(int(part) for part in chunk.split(":"))
                       for chunk in args.ratios.split(",") if chunk.strip())
    else:
        ratios = REPORT_RATIOS

    rows = []
    started = time.time()
    for attacker, defender in ratios:
        rows.append(run_sweep(attacker, defender, seeds,
                              quality=args.quality,
                              mirror_ai=not args.passive,
                              dt=args.dt,
                              max_ticks=args.max_ticks,
                              stall_ticks=args.stall_ticks,
                              jitter_px=args.jitter,
                              exponent=args.exponent,
                              luck_sigma=args.luck_sigma))
    elapsed = time.time() - started
    mode = "PASSIVE BLUE (no player)" if args.passive else "MIRROR AI (A vs A)"
    extra = ""
    if args.jitter:
        extra += f", jitter=+-{args.jitter}px"
    if args.exponent != 1.0 or args.luck_sigma != 0.0:
        extra += f", COUNTERFACTUAL exp={args.exponent} sigma={args.luck_sigma}"
    print(format_table(rows, f"balance: {mode}, dt={args.dt:.4f}, "
                             f"seeds={args.seeds}, q={args.quality}{extra}"))
    print(f"cpu: {elapsed:.1f}s for {len(rows) * len(seeds)} battles")

    if args.order_probe:
        attacker, _, defender = args.order_probe.partition(":")
        spec = BattleSpec(int(attacker), int(defender or attacker), seed=1,
                          dt=args.dt, stall_ticks=args.stall_ticks)
        print()
        print(format_order_probe(spec))
    return 0


if __name__ == "__main__":  # pragma: no cover - точка входа для отчёта
    raise SystemExit(main())
