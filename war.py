"""Мост между мировой картой и тактическим боем.

До этого модуля два слоя жили независимо: мировой бой решался мгновенно
формулой, а тактический экран был отдельной песочницей без входа и выхода.
Здесь лежит контракт между ними — ровно три вещи:

* :class:`WarSession` — «билет» в тактический бой: кто с кем за что сражается;
* :class:`BattleOutcome` — «квитанция» обратно: кто выжил и что захватил;
* :func:`outcome_to_world` — перевод квитанции в словарь дельт для мира.

Модуль намеренно ничего не импортирует из проекта: ни pygame, ни world_data,
ни engine, ни states. Иначе изоляция ядра рассыплется, а проверка
``test_sim_has_no_project_imports`` станет зависеть от формы файла. Всё, что
нужно снаружи, передаётся аргументами (индексы провинций, имена наций) или
возвращается простыми числами.

Детерминизм. Ни одного глобального ``random`` и ни одного глобального seed'а:
поток для бросков и для зерна сессии создаёт вызывающий код через
``sim.rng.NamedStreams`` и передаёт сюда уже готовое число (поле ``seed``).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

__all__ = [
    "TROOPS_PER_TACTICAL_UNIT",
    "TACTICS_UNIT_CAP",
    "LOOT_PER_SURVIVING_UNIT",
    "PRESTIGE_PER_VILLAGE",
    "PRESTIGE_BASE",
    "QUALITY_MIN",
    "QUALITY_MAX",
    "QUALITY_BONUS",
    "WORLD_BATTLE_STREAM",
    "WORLD_BATTLE_SALT_BASE",
    "WORLD_SESSION_SALT_BASE",
    "WORLD_STREAM_SEED",
    "MIN_GENERAL_TROOPS",
    "WarSession",
    "BattleOutcome",
    "quality_bonuses",
    "tactical_units_for",
    "defender_units_for",
    "quality_from_roll",
    "outcome_to_world",
    "clamp_quality",
    "apply_deltas_to_screen",
]

#: Сколько мировых солдат соответствует одному тактическому юниту. Та же
#: величина уже зашита в ``states.Character.troops_hint`` (``troops // 100``),
#: поэтому левейс, показанный в панели владений, и число юнитов в бою больше не
#: расходятся: 500 солдат генерала — это ровно 5 юнитов на карте.
TROOPS_PER_TACTICAL_UNIT = 100

#: Потолок по юнитам за бой. Без него левейс в несколько тысяч превращался бы в
#: армию в сотни юнитов: карта 40x22 клеток не вмещает столько, да и отрисовка
#: каждого юнита стоит кадру. Лишний левейс не сгорает — он остаётся в мире и
#: приносит трофеи, поэтому потолок не наказывает игрока.
TACTICS_UNIT_CAP = 9

#: Золото за каждого уцелевшего синего юнита. Считается только при победе:
#: поражение не должно оплачиваться.
LOOT_PER_SURVIVING_UNIT = 30

#: Прибавка престижа за каждую захваченную деревню.
PRESTIGE_PER_VILLAGE = 2

#: Престиж за саму победу, без учёта деревень. Отдельной константой, чтобы
#: «победил, но ничего не захватил» всё равно что-то давало.
PRESTIGE_BASE = 5

#: Границы качества левейса. Всё, что вне диапазона, прижимается к нему:
#: мусор из сети или из старого снапшота не должен ронять бой.
QUALITY_MIN = 1
QUALITY_MAX = 3

#: Множители (здоровье, урон) по качеству. Качество — это не отдельный тип
#: юнита, а «выучка» одной и той же пехоты, поэтому 1 = обычная пехота,
#: 2 = ветераны (+15% HP), 3 = гвардия (+15% HP и +15% урона).
QUALITY_BONUS: Dict[int, Tuple[float, float]] = {
    1: (1.00, 1.00),
    2: (1.15, 1.00),
    3: (1.15, 1.15),
}

#: Имя именованного потока ГПСЧ для всего, что на мировой карте решается
#: броском: мгновенный бой бота, выбор цели ИИ, качество левейса и зерно
#: сессии. Поток один на весь мир, поэтому расход бота не сдвигает качество
#: войск игрока и наоборот.
WORLD_BATTLE_STREAM = "world:battle"

#: Соли именованного потока разведены по непересекающимся диапазонам.
#: ``NamedStreams.derive(name, salt)`` отдаёт ОДИН и тот же генератор на пару
#: (имя, соль), поэтому если бы мгновенный бой и сессия пользовались одной и
#: той же солью, качество войск игрока зависело бы от того, сколько боёв у бота
#: случилось до него. Сессия №N обязана получать одно и то же качество и зерно
#: при любом порядке событий — иначе реплей мира невозможен.
WORLD_BATTLE_SALT_BASE = 0
WORLD_SESSION_SALT_BASE = 1_000_000

#: Зерно набора потоков мира. Константа, а не ``None``, чтобы два запуска игры
#: давали одинаковую картину боёв — иначе реплей мира невозможен.
WORLD_STREAM_SEED = 1337

#: Нижняя граница войск генерала после боя. Ровно тот же пол, что и в старом
#: мгновенном бою (``max(100, troops - losses)``): проигравший не должен
#: исчезать с карты из-за одного неудачного набега.
MIN_GENERAL_TROOPS = 100


def clamp_quality(quality: object) -> int:
    """Привести качество к целому в диапазоне 1..3.

    Всё, что не число или лежит вне диапазона, даёт ``QUALITY_MIN``: испорченное
    качество должно делать войска хуже, а не сильнее.
    """
    try:
        value = int(quality)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return QUALITY_MIN
    return max(QUALITY_MIN, min(QUALITY_MAX, value))


def quality_bonuses(quality: object) -> Tuple[float, float]:
    """Множители (здоровье, урон) для качества левейса."""
    return QUALITY_BONUS[clamp_quality(quality)]


def quality_from_roll(roll: object) -> int:
    """Качество левейса по целочисленному броску 0..99.

    Пороги 60/90 — те же, что у тира наёмника в ``states``: качество должно
    быть редким, иначе «плохой» левейс перестаёт быть наказанием. Целое число
    вместо ``random()`` с порогом — чтобы качество не зависело от порядка
    вычислений с плавающей точкой.
    """
    try:
        value = int(roll)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return QUALITY_MIN
    if value < 60:
        return 1
    if value < 90:
        return 2
    return 3


def tactical_units_for(troops_committed: object) -> int:
    """Сколько синих юнитов выйдет на поле из вложенного левейса.

    ``TROOPS_PER_TACTICAL_UNIT`` солдат на юнит, не больше
    ``TACTICS_UNIT_CAP``, но хотя бы один — иначе игрок, отправивший в бой
    копейки, получал мгновенный проигрыш без единого броска на карте, а это
    плохое сообщение об ошибке, а не проигрыш.
    """
    try:
        troops = max(0, int(troops_committed))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        troops = 0
    return max(1, min(TACTICS_UNIT_CAP, troops // TROOPS_PER_TACTICAL_UNIT))


def defender_units_for(session: "WarSession") -> int:
    """Сколько юнитов получает защитник.

    Считается из **реальных войск защитника** (``session.defender_troops``).
    Раньше здесь было ``own // 2`` — защитник всегда вдвое слабее, сколько бы
    солдат у него ни было: игрок со 1200 войск выходил против «3000», а
    получал противника вдвое меньше собственного. Число метрик уходило.

    Фолбэк на ``own // 2`` оставлен только для сессий без данных о
    защитнике (старая сессия, приказ из UI), чтобы число не падало до нуля.
    """
    troops = getattr(session, "defender_troops", None)
    if troops is None:
        own = tactical_units_for(session.troops_committed)
        return max(1, min(TACTICS_UNIT_CAP, own // 2))
    try:
        raw = max(0, int(troops))
    except (TypeError, ValueError):
        raw = 0
    if raw <= 0:
        return 1
    return max(1, min(TACTICS_UNIT_CAP, raw // TROOPS_PER_TACTICAL_UNIT))


@dataclass(frozen=True)
class WarSession:
    """Билет в тактический бой: всё, что нужно, чтобы открыть карту сражения.

    ``frozen=True`` намеренно: билет проходит через несколько экранов, и если
    кто-то по дороге подправит левейс или зерно, тактический бой перестанет
    соответствовать миру, из которого он вырос. Изменить набор войск можно
    только новым билетом.

    Поля:

    * ``match_id`` — порядковый номер боя в партии, он же целочисленная соль
      для именованного потока (``sim.rng.NamedStreams.derive``);
    * ``attacker_nation`` / ``defender_nation`` — кто с кем;
    * ``province_idx`` — индекс провинции, из-за которой начался бой;
    * ``general_name`` — имя атакующего генерала: по нему мир найдёт ту армию,
      которой надо вернуть уцелевших;
    * ``troops_committed`` — вложенный левейс в солдатах;
    * ``quality`` — 1..3, см. :func:`quality_bonuses`;
    * ``seed`` — целое зерно тактического боя;
    * ``player_attacker`` — атакует ли игрок. Изначально всегда ``True``
      (создать сессию может только игрок), но поле есть, чтобы форк бота можно
      было довести без изменения контракта.
    """

    match_id: int
    attacker_nation: str
    defender_nation: str
    province_idx: int
    general_name: str
    troops_committed: int
    #: Реальные войска защитника. ``None`` — данных нет (старая сессия),
    #: тогда :func:`defender_units_for` падает на подстановку.
    defender_troops: Optional[int] = None
    quality: int = QUALITY_MIN
    seed: int = 0
    player_attacker: bool = True

    @property
    def tactical_units(self) -> int:
        """Сколько юнитов уйдёт в бой (с учётом потолка)."""
        return tactical_units_for(self.troops_committed)

    @property
    def defender_units(self) -> int:
        """Сколько юнитов у защитника."""
        return defender_units_for(self)

    @property
    def player_nation(self) -> str:
        """Нация игрока в этой сессии."""
        return self.attacker_nation if self.player_attacker else self.defender_nation

    def to_state(self) -> Dict[str, object]:
        """Снапшот билета — обычный dict, пригодный для хеша и JSON."""
        return {
            "match_id": int(self.match_id),
            "attacker_nation": str(self.attacker_nation),
            "defender_nation": str(self.defender_nation),
            "province_idx": int(self.province_idx),
            "general_name": str(self.general_name),
            "troops_committed": int(self.troops_committed),
            "defender_troops": (None if self.defender_troops is None
                                else int(self.defender_troops)),
            "quality": int(self.quality),
            "seed": int(self.seed),
            "player_attacker": bool(self.player_attacker),
        }

    @classmethod
    def from_state(cls, data: object) -> Optional["WarSession"]:
        """Восстановить билет из снапшота. ``None``, если данных не хватает.

        Возвращать ``None``, а не бросать, — сознательно: значение приходит из
        чужого файла, и повреждённый билет должен означать «боя не будет», а не
        падение игрового цикла.
        """
        if not isinstance(data, dict):
            return None
        try:
            return cls(
                match_id=int(data["match_id"]),
                attacker_nation=str(data["attacker_nation"]),
                defender_nation=str(data["defender_nation"]),
                province_idx=int(data["province_idx"]),
                general_name=str(data["general_name"]),
                troops_committed=int(data["troops_committed"]),
                defender_troops=(None if data.get("defender_troops") is None
                                else int(data["defender_troops"])),
                quality=clamp_quality(data.get("quality", QUALITY_MIN)),
                seed=int(data.get("seed", 0)),
                player_attacker=bool(data.get("player_attacker", True)),
            )
        except (KeyError, TypeError, ValueError):
            return None


@dataclass
class BattleOutcome:
    """Квитанция тактического боя для мира.

    Не ``frozen``: квитанцию собирает движок по ходу боя (потери считаются в
    момент конца партии), и она должна оставаться пригодной для отладки и
    логирования целиком, а не по полям.
    """

    match_id: int
    winner_nation: str
    blue_surviving: int
    blue_losses: int
    red_losses: int
    captured_villages: int

    def to_state(self) -> Dict[str, object]:
        """Снапшот квитанции — обычный dict."""
        return {
            "match_id": int(self.match_id),
            "winner_nation": str(self.winner_nation),
            "blue_surviving": int(self.blue_surviving),
            "blue_losses": int(self.blue_losses),
            "red_losses": int(self.red_losses),
            "captured_villages": int(self.captured_villages),
        }

    @classmethod
    def from_state(cls, data: object) -> Optional["BattleOutcome"]:
        """Восстановить квитанцию из снапшота. ``None``, если данных не хватает."""
        if not isinstance(data, dict):
            return None
        try:
            return cls(
                match_id=int(data["match_id"]),
                winner_nation=str(data["winner_nation"]),
                blue_surviving=int(data["blue_surviving"]),
                blue_losses=int(data["blue_losses"]),
                red_losses=int(data["red_losses"]),
                captured_villages=int(data["captured_villages"]),
            )
        except (KeyError, TypeError, ValueError):
            return None


def outcome_to_world(ws: WarSession, outcome: BattleOutcome) -> Dict[str, object]:
    """Перевести квитанцию боя в словарь дельт для мирового слоя.

    Возвращаются не новые значения, а ИЗМЕНЕНИЯ: мир сам решает, кому и куда
    их применить. Так один и тот же расчёт годится и для экрана карты, и для
    серверной проверки, и для реплея.

    Правила (все целочисленные, чтобы не плодить float в состоянии мира):

    * ``gold`` — ``LOOT_PER_SURVIVING_UNIT`` за каждого уцелевшего синего юнита,
      но только если выиграла нация игрока. Поражение и прерванный бой не платят;
    * ``prestige`` — ``PRESTIGE_BASE`` за победу плюс ``PRESTIGE_PER_VILLAGE``
      за каждую захваченную синим деревню, тоже только при победе;
    * ``villages_delta`` — отрицательное число: столько деревень уходит из
      копилки атакуемой провинции в пользу атакующего;
    * ``troops_returned`` / ``troops_lost`` — левейс, который вернётся в
      генерала. Ушедшие в бой солдаты списываются при создании сессии, здесь
      они либо возвращаются уцелевшими, либо окончательно теряются;
    * ``trophy`` — человекочитаемая строка для плашки над картой.

    Победой считается победа нации игрока: для сессии, заведённой игроком, это
    атакующая нация, но поле ``player_attacker`` позволяет проверять и форк
    бота, не переписывая формулу. Пустой ``winner_nation`` — это «бой не
    доигран», награды нет, потери считаются.
    """
    player_nation = ws.player_nation
    winner = str(getattr(outcome, "winner_nation", "") or "")
    surviving = max(0, int(getattr(outcome, "blue_surviving", 0) or 0))
    blue_losses = max(0, int(getattr(outcome, "blue_losses", 0) or 0))
    red_losses = max(0, int(getattr(outcome, "red_losses", 0) or 0))
    captured = max(0, int(getattr(outcome, "captured_villages", 0) or 0))

    player_won = bool(winner) and winner == player_nation

    gold = LOOT_PER_SURVIVING_UNIT * surviving if player_won else 0
    prestige = (PRESTIGE_BASE + PRESTIGE_PER_VILLAGE * captured) if player_won else 0
    villages_delta = -captured if player_won else 0

    # Солдаты возвращаются в генерала только за выжившие юниты; потолок
    # max_troops держит сам мир при применении дельт.
    troops_returned = surviving * TROOPS_PER_TACTICAL_UNIT
    troops_lost = max(0, int(ws.troops_committed) - troops_returned)

    if player_won:
        trophy = (f"{ws.general_name} победил, деревень: {captured} "
                  f"| +{gold} золота, +{prestige} престижа")
    elif winner:
        trophy = (f"{ws.general_name} отбит | -{troops_lost} солдат, "
                  f"вернулось отрядов: {surviving}")
    else:
        trophy = (f"{ws.general_name} вышел из боя без награды "
                  f"| -{troops_lost} солдат")

    return {
        "match_id": int(getattr(outcome, "match_id", ws.match_id)),
        "nation": player_nation,
        "attacker_nation": str(ws.attacker_nation),
        "defender_nation": str(ws.defender_nation),
        "winner_nation": winner,
        "player_won": player_won,
        "province_idx": int(ws.province_idx),
        "general_name": str(ws.general_name),
        "gold": int(gold),
        "prestige": int(prestige),
        "villages_delta": int(villages_delta),
        "captured_villages": int(captured),
        "troops_returned": int(troops_returned),
        "troops_lost": int(troops_lost),
        "blue_surviving": surviving,
        "blue_losses": blue_losses,
        "red_losses": red_losses,
        "trophy": trophy,
    }


def _screen_nation(screen, nation_key: str):
    """Достать объект нации с экрана. ``None``, если не нашлось.

    Экран отдаёт нацию либо методом ``_nation_object``, либо словарём
    ``nations``. Оба способа — duck typing: war.py не знает world_data.
    """
    getter = getattr(screen, "_nation_object", None)
    if callable(getter):
        try:
            nation = getter(nation_key)
        except Exception:
            nation = None
        if nation is not None:
            return nation
    nations = getattr(screen, "nations", None)
    if isinstance(nations, dict):
        return nations.get(nation_key)
    return None


def _screen_realm(screen, nation_key: str):
    """Достать королевство нации из иерархии экрана. ``None``, если нет."""
    getter = getattr(screen, "_realm_of_nation", None)
    if not callable(getter):
        return None
    try:
        return getter(nation_key)
    except Exception:
        return None


def apply_deltas_to_screen(screen, deltas: Dict[str, object]) -> None:
    """Разложить дельты ``outcome_to_world`` по живому экрану мировой карты.

    Функция живёт здесь, а не в ``world_map.py``, потому что список полей
    дельты — это контракт ``outcome_to_world``, и разбирать его в двух местах
    значит однажды забыть про новое поле.

    Что происходит:

    * золото идёт и в казну нации (её рисует HUD), и в королевство из
      иерархии (её тратит ``states``: левейс, наёмники, гарнизоны);
    * престиж — в королевство, с потолком 100, как и в ``tick_realms``;
    * ``villages_delta`` — в провинцию, из которой ушли захваченные деревни;
    * при победе провинция меняет владельца на нацию атакующего и обнуляет
      гарнизон — ровно то, что делал старый мгновенный бой;
    * уцелевшие солдаты возвращаются генералу, остальные списываются;
    * на карте появляется трофейная плашка, панель владений перерисовывается.

    Экран вне контекста (``None``) переживает вызов молча: применять дельты
    некуда, но падать из-за этого нельзя.
    """
    if screen is None or not isinstance(deltas, dict):
        return

    nation_key = str(deltas.get("nation", "") or "")
    gold = int(deltas.get("gold", 0) or 0)
    prestige = int(deltas.get("prestige", 0) or 0)

    # 1. Казна нации: WORLD_NATIONS общий для всех экранов, но HUD читает
    #    именно оттуда, поэтому обновляем в первую очередь.
    nation = _screen_nation(screen, nation_key)
    if nation is not None:
        nation.gold = max(0, int(getattr(nation, "gold", 0)) + gold)

    # 2. Королевство из иерархии — оттуда states.py берёт деньги на левейс.
    realm = _screen_realm(screen, nation_key)
    if realm is not None:
        realm.gold = max(0, int(getattr(realm, "gold", 0)) + gold)
        realm.prestige = max(0, min(100, int(getattr(realm, "prestige", 0)) + prestige))

    # 3. Провинция: деревни и владелец.
    provinces = getattr(screen, "provinces", None)
    idx = int(deltas.get("province_idx", -1))
    if isinstance(provinces, (list, tuple)) and 0 <= idx < len(provinces):
        prov = provinces[idx]
        delta_villages = int(deltas.get("villages_delta", 0) or 0)
        if delta_villages:
            prov.villages = max(0, int(getattr(prov, "villages", 0)) + delta_villages)
        if bool(deltas.get("player_won", False)):
            attacker = str(deltas.get("attacker_nation", "") or "")
            if attacker:
                # через иерархию, иначе персонаж/контракты/де-факто
                # держатель герцогства остались бы от прежнего хозяина
                hierarchy = getattr(screen, "hierarchy", None)
                transfer = getattr(hierarchy, "transfer_county", None)
                name = str(deltas.get("general_name", "") or "")
                holder = None
                if hierarchy is not None:
                    attacker_nation = str(deltas.get("attacker_nation", "") or "")
                    for ch in hierarchy.characters.values():
                        # сверка по паре (имя, нация): имена переиспользуются
                        # в разных державах, сверка только по имени отдала бы
                        # провинцию персонажу чужой нации
                        if ch.name == name and ch.nation == attacker_nation:
                            holder = ch.id
                            break
                if transfer is not None:
                    transfer(idx, attacker, holder, cause="битва")
                else:
                    prov.owner = attacker
            prov.troops = 0

    # 4. Генерал: уцелевшие солдаты возвращаются в его левейс.
    general_name = str(deltas.get("general_name", "") or "")
    returned = int(deltas.get("troops_returned", 0) or 0)
    for gen in (getattr(screen, "generals", None) or []):
        if getattr(gen, "name", None) != general_name:
            continue
        cap = int(getattr(gen, "max_troops", 0) or 0)
        troops = max(MIN_GENERAL_TROOPS, returned)
        if cap > 0:
            troops = min(cap, troops)
        gen.troops = troops
        break

    # 5. Плашка над картой и перерисовка панели владений.
    show_msg = getattr(screen, "_show_msg", None)
    if callable(show_msg):
        show_msg(str(deltas.get("trophy", "") or ""))
    invalidate = getattr(screen, "_invalidate_panel", None)
    if callable(invalidate):
        invalidate()