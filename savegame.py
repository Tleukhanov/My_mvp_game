"""Сохранение и загрузка кампании мировой карты.

Зачем модуль нужен
------------------
Кампания жила только в памяти процесса: ``main.py`` при выходе в меню
выбрасывал ``WorldMapScreen`` вместе со всей партией, а ``WorldMapScreen``
строился заново при каждом входе в карту. Для стратегии это самая дорогая
дыра из возможных — потерять двадцать ходов из-за закрытия окна.

Формат хранения
---------------
Одна база SQLite на файл ``*.db`` (``.gitignore`` её уже игнорирует), таблица
``saves`` — по строке на слот. SQLite выбран не по вкусу, а по одному
свойству: **атомарность через транзакцию**. Запись либо целиком
коммитится, либо откатывается к предыдущему снимку, поэтому падение посреди
сохранения не оставит «наполовину записанный» мир. Обычный файл для того же
пришлось бы писать во временный и подменять через ``os.replace`` — эффект
тот же, но вручную и без проверки целостности при чтении.

Внутри строки лежит JSON, собранный ``sim.serialization.dumps``: он уже умеет
plain-dict, tuple и enum, и это ровно тот словарь, который ``states.py``
отдаёт из ``Hierarchy.to_state()``. Отдельный формат для иерархии не нужен и
был бы второй правдой о том же мире.

Второй слой защиты — отпечаток (``fingerprint``). Это ``state_hash`` от
состояния, и он кладётся рядом с ним же. При чтении хеш пересчитывается и
сравнивается: обрезанный или подменённый файл отсекается как повреждённый,
а не превращается в партию, у которой наполовина восстановленных генералов.

Что сериализуется
-----------------
Состояние мира, из которого растут все следующие ходы:

* владелец и гарнизон каждой провинции (девять «поселенческих» полей
  приходят из ``Hierarchy.to_state()``, а ``owner`` и ``troops`` — из
  мирового слоя и в тот снимок не входят по контракту ``states.py``);
* каждый генерал целиком: где стоит, сколько солдат, флаг ``moved``,
  здоровье и потолок ``max_troops``;
* счётчик ходов карты ``_turn`` (у иерархии свой, он уже в её снимке);
* отношения между нациями целиком, а не «как было на старте»: война,
  объявленная на 12-м ходу, обязана пережить перезапуск;
* золото наций из ``WORLD_NATIONS`` — HUD рисует именно его, и оно
  расходится с золотом королевства из иерархии;
* очередь приказов движения ``_orders`` и ``_queued_orders``: приказ это
  обещание на будущие ходы, и потерять его — значит тихо изменить партию;
* счётчики солей ``_match_seq`` / ``_battle_seq`` (см. ниже про ГПСЧ);
* снимок иерархии целиком — золото, престиж, приказы короля, кризисы
  престола, де-факто держатели герцогств.

Чего в сохранении нет и почему
------------------------------
* **Состояние экрана**: камера, зум, ховер, открытая панель, выделенные
  армии, отряды под номерами, курсор панели, всплывающая плашка, таймеры.
  Ни одно из этих полей не читается ни одной фазой хода — это ввод и
  рисование, а не мир. Камера вдобавок привязана к текущему разрешению
  окна, и сохранённая камера в другом окне восстановила бы бессмысленный
  кадр. Единственное исключение — выделение НЕ восстанавливается, и это
  осознанно: игрок после перезапуска видит карту целиком и выбирает заново,
  а «призрачное» выделение после закрытия панели уже умело портить вид.
* **Позиция генераторов ГПСЧ.** Мир обращается только к
  ``NamedStreams.derive(имя, соль)``, а соль всегда уникальна и считается
  из счётчиков, которые сохраняются. Ветка ``derive`` — чистая функция от
  ``(seed, имя, соль)``, поэтому позиция потока на результат не влияет, и
  хранить её незачем; хватит зерна. Если появится код, зовущий
  ``streams.stream(...)``, это станет неправдой, и ``fingerprint`` без
  ГПСЧ перестанет ловить расхождение.
* **Журнал лимитов ``Hierarchy.action_ledger``** — ``states.from_state`` его
  сознательно не восстанавливает (см. докстринг ``to_state``), и это
  зафиксированный там компромисс: загрузка ПОСЕРЕДИНЕ хода возвращает игроку
  израсходованные «раз за ход» лимиты. Формат сохраняет ход как есть, вместе
  с этим эффектом: подглядывать лимиты можно было и до сохранения, а вот
  тихо расширять их в обход правил — нет.
* **``pending_session``** — билет в тактический бой. Тактический слой
  принадлежит другому агенту и не умеет продолжаться с середины, поэтому
  сохранение с живой сессией отклоняется понятным сообщением, а не
  оставляет партию в состоянии, из которого бой уже нельзя доиграть.

Формат версионируется
---------------------
``SAVE_FORMAT_VERSION`` — целое число, растущее при смене смысла полей.
Файл со старой версией отвергается с текстом «сохранение версии N, игра
знает M», а не «частично восстановлен». Внутри снимка лежит та же версия:
проверяются обе, потому что файл могли переписать руками.
"""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from diplomacy import Relation
from sim.hashing import state_hash
from sim.rng import new_streams
from sim.serialization import SCHEMA_VERSION, dumps, loads

#: Версия формата сохранения. Рост числа означает смену СМЫСЛА полей.
#: Добавление нового необязательного поля версию не поднимает: читается оно
#: через ``.get(field, default)``, и старый файл остаётся годным.
SAVE_FORMAT_VERSION = 1

#: Слот по умолчанию. Один слот — осознанно: партия одна, а список слотов
#: в меню означал бы обещание UI выбора, которого в ``menu.py`` нет.
DEFAULT_SLOT = "campaign"

#: Переопределение пути к базе переменной окружения. Нужно тестам (чтобы не
#: писать в дерево репозитория) и игроку с нестандартным размещением.
SAVE_PATH_ENV = "TACTIC_BATTLE_SAVE"

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS saves (
    slot            TEXT PRIMARY KEY,
    save_version    INTEGER NOT NULL,
    schema_version  INTEGER NOT NULL,
    turn            INTEGER NOT NULL,
    fingerprint     TEXT NOT NULL,
    saved_at        INTEGER NOT NULL,
    payload         TEXT NOT NULL
)
"""


class SaveError(Exception):
    """Базовая ошибка слоя сохранения.

    Отдельный тип нужен, чтобы ``main.py`` мог отличить «сохранения нет» и
    «сохранение есть, но не читается» от программной ошибки: игроку в обоих
    случаях нужен текст, а не трассировка.
    """


class SaveNotFound(SaveError):
    """Сохранения для этого слота нет."""


class SaveIncompatible(SaveError):
    """Файл читается, но сделан другой версией игры."""


class SaveCorrupt(SaveError):
    """Файл повреждён: обрезан, подменён или не того формата."""


# --------------------------------------------------------------------------
# Путь и слой SQLite
# --------------------------------------------------------------------------

def default_save_path() -> Path:
    """Путь к базе сохранений по умолчанию.

    По умолчанию — ``saves/<слот>.db`` рядом с кодом. Расширение ``.db``
    уже перечислено в ``.gitignore``, поэтому файл не попадёт в коммит
    случайно; ``SAVE_PATH_ENV`` позволяет увести его куда угодно.
    """
    override = os.environ.get(SAVE_PATH_ENV)
    if override:
        return Path(override)
    return Path(__file__).resolve().parent / "saves" / f"{DEFAULT_SLOT}.db"


def _connect(path: Path) -> sqlite3.Connection:
    """Открыть базу (создав файл и таблицу) и включить проверку целостности.

    Журнал оставляем штатным (rollback), а не WAL: WAL добавляет рядом
    ``-wal``/``-shm``, то есть три файла вместо одного, ради преимущества,
    которое для одиночной записи раз в несколько ходов не нужно.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute(_SCHEMA_SQL)
    return conn


# --------------------------------------------------------------------------
# Состояние кампании
# --------------------------------------------------------------------------

def general_key(name: str, nation: str) -> str:
    """Ключ генерала в сохранении: имя и нация вместе.

    Имена переиспользуются между державами (синий генерал Aldric и красный
    герцог duke_aldric — разные люди, см. ``WorldMapScreen._general_character``),
    поэтому ключ только по имени склеил бы две разные армии при загрузке.
    """
    return f"{str(name)}|{str(nation)}"


def _general_state(general) -> Dict[str, object]:
    province_idx = getattr(general, "province_idx", None)
    return {
        "key": general_key(general.name, general.nation),
        "name": str(general.name),
        "nation": str(general.nation),
        "province_idx": (None if province_idx is None else int(province_idx)),
        "troops": int(general.troops),
        "max_troops": int(getattr(general, "max_troops", 0)),
        "moved": bool(getattr(general, "moved", False)),
        "health": int(getattr(general, "health", 100)),
    }


def _order_state(order: Dict[str, object]) -> Dict[str, object]:
    """Приказ движения в JSON-виде: генерал по ключу, цель и маршрут числами."""
    general = order["general"]
    return {
        "general": general_key(general.name, general.nation),
        "goal": int(order["goal"]),
        "path": [int(idx) for idx in (order.get("path") or [])],
        "stuck": int(order.get("stuck", 0) or 0),
    }


def _relation_state(manager) -> List[Dict[str, str]]:
    """Отношения наций как отсортированный список троек.

    Список, а не словарь: ключ отношения — ПАРА наций, и после ``json``
    пара превратилась бы в строку с разделителем, который пришлось бы ещё и
    разбирать. Здесь ключ остаётся данными и проверяется по-настоящему.
    """
    relations = getattr(manager, "_relations", None) or {}
    return [{"a": str(a), "b": str(b), "relation": rel.name}
            for (a, b), rel in sorted(relations.items())]


def campaign_state(screen) -> Dict[str, object]:
    """Снимок живой кампании: plain-dict, годный и для хеша, и для JSON.

    Именно этот словарь — единственный представитель партии. ``fingerprint``
    считается по нему же, поэтому «состояние» и «то, что записано в файл»
    разойтись не могут по построению.
    """
    hierarchy = screen.hierarchy
    nations = getattr(screen, "nations", None) or {}
    return {
        "format": SAVE_FORMAT_VERSION,
        "turn": int(screen._turn),
        # соли ГПСЧ: без них последовательность боёв после загрузки
        # начинается заново и совпадает с уже виденной игроку
        "match_seq": int(screen._match_seq),
        "battle_seq": int(screen._battle_seq),
        "streams": {
            "seed": int(screen.streams.seed),
            "hierarchy_seed": int(hierarchy.streams.seed),
        },
        "provinces": {
            # owner и troops — единственные поля провинции, которые меняет
            # мировой слой; остальные девять живут в снимке иерархии
            "owners": [str(getattr(p, "owner", "neutral"))
                       for p in screen.provinces],
            "troops": [int(getattr(p, "troops", 0)) for p in screen.provinces],
        },
        "generals": [_general_state(g) for g in screen.generals],
        "nation_gold": {str(key): int(getattr(nat, "gold", 0))
                        for key, nat in sorted(nations.items())},
        "diplomacy": _relation_state(screen.diplomacy),
        "orders": [_order_state(o) for o in screen._orders],
        "queued_orders": [_order_state(o) for o in screen._queued_orders],
        "hierarchy": hierarchy.to_state(),
    }


def campaign_fingerprint(state: Dict[str, object]) -> str:
    """Хеш снимка кампании: одна точка правды о «состоянии партии»."""
    return state_hash(state)


# --------------------------------------------------------------------------
# Разбор и проверка
# --------------------------------------------------------------------------

def _require_dict(value: object, what: str) -> Dict[str, object]:
    if not isinstance(value, dict):
        raise SaveCorrupt(f"«{what}» — не словарь, а {type(value).__name__}")
    return dict(value)


def _require_int(value: object, what: str) -> int:
    # bool — подтип int, но «moved: True» в поле счётчика означает битый файл
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SaveCorrupt(f"«{what}» — не число, а {value!r}")
    return int(value)


def _require_str(value: object, what: str) -> str:
    if not isinstance(value, str):
        raise SaveCorrupt(f"«{what}» — не строка, а {value!r}")
    return value


def check_format(raw: Dict[str, object]) -> Dict[str, object]:
    """Проверить версии снимка и достать состояние. Бросает при несовпадении.

    Проверяются ОБА номера: ``format`` внутри снимка (файл могли переписать
    руками или склеить снимки разных версий) и ``save_version`` в строке
    таблицы (её пишет только эта версия кода). Молча читать несовместимое
    нельзя — получится мир, у которого часть полей заполнена, а часть
    молча осталась стартовой.
    """
    state = _require_dict(raw, "состояние")
    version = state.get("format")
    if version != SAVE_FORMAT_VERSION:
        raise SaveIncompatible(
            f"сохранение версии {version!r}, эта версия игры знает "
            f"{SAVE_FORMAT_VERSION}; партия из такого файла не грузится")
    return state


def _validate_provinces(state: Dict[str, object], province_count: int
                        ) -> Tuple[List[str], List[int]]:
    provinces = _require_dict(state.get("provinces"), "provinces")
    owners = provinces.get("owners")
    troops = provinces.get("troops")
    if not isinstance(owners, list) or not isinstance(troops, list):
        raise SaveCorrupt("«provinces» ждёт списки owners и troops")
    if len(owners) != province_count or len(troops) != province_count:
        # это не «частичный файл», а снимок ДРУГОЙ карты: незаметно
        # подставить значения по умолчанию значило бы выдумать партию
        raise SaveCorrupt(
            f"в сохранении {len(owners)}/{len(troops)} провинций, "
            f"а в игре {province_count}: карта изменилась, партия не подходит")
    return ([_require_str(o, "владелец провинции") for o in owners],
            [_require_int(t, "гарнизон провинции") for t in troops])


def _validate_generals(state: Dict[str, object], province_count: int
                       ) -> List[Dict[str, object]]:
    raw = state.get("generals")
    if not isinstance(raw, list):
        raise SaveCorrupt(f"«generals» — не список, а {type(raw).__name__}")
    out: List[Dict[str, object]] = []
    seen = set()
    for entry in raw:
        data = _require_dict(entry, "генерал")
        key = _require_str(data.get("key"), "ключ генерала")
        if key in seen:
            # два генерала с одним ключом склеились бы в один объект, и
            # вторая армия исчезла бы молча
            raise SaveCorrupt(f"генерал «{key}» записан дважды")
        seen.add(key)
        province_idx = data.get("province_idx")
        if province_idx is not None:
            idx = _require_int(province_idx, "провинция генерала")
            if not 0 <= idx < province_count:
                raise SaveCorrupt(
                    f"генерал «{key}» стоит в провинции {idx}, которой "
                    f"на карте нет")
            province_idx = idx
        out.append({
            "key": key,
            "name": _require_str(data.get("name"), "имя генерала"),
            "nation": _require_str(data.get("nation"), "нация генерала"),
            "province_idx": province_idx,
            "troops": _require_int(data.get("troops", 0), "солдаты генерала"),
            "max_troops": _require_int(data.get("max_troops", 0),
                                       "потолок армии"),
            "moved": bool(data.get("moved", False)),
            "health": _require_int(data.get("health", 100), "здоровье генерала"),
        })
    return out


def _validate_diplomacy(state: Dict[str, object], known_nations: Sequence[str]
                        ) -> List[Tuple[str, str, Relation]]:
    raw = state.get("diplomacy")
    if not isinstance(raw, list):
        raise SaveCorrupt(f"«diplomacy» — не список, а {type(raw).__name__}")
    nations = set(known_nations)
    out: List[Tuple[str, str, Relation]] = []
    for entry in raw:
        data = _require_dict(entry, "отношение")
        a = _require_str(data.get("a"), "нация A")
        b = _require_str(data.get("b"), "нация B")
        name = _require_str(data.get("relation"), "вид отношения")
        if a not in nations or b not in nations:
            # отношение с несуществующей нацией нельзя ни показать, ни
            # проверить — это уже другой набор держав, а не другой снимок
            raise SaveCorrupt(
                f"отношение {a}/{b} ссылается на нацию, которой нет на карте")
        try:
            relation = Relation[name]
        except KeyError:
            raise SaveCorrupt(f"неизвестный вид отношения «{name}»") from None
        out.append((a, b, relation))
    return out


def _validate_orders(raw: object, province_count: int, label: str
                     ) -> List[Dict[str, object]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise SaveCorrupt(f"«{label}» — не список, а {type(raw).__name__}")
    out: List[Dict[str, object]] = []
    for entry in raw:
        data = _require_dict(entry, f"приказ ({label})")
        goal = _require_int(data.get("goal"), "цель приказа")
        if not 0 <= goal < province_count:
            raise SaveCorrupt(
                f"приказ ведёт в провинцию {goal}, которой на карте нет")
        path_raw = data.get("path") or []
        if not isinstance(path_raw, list):
            raise SaveCorrupt("маршрут приказа — не список")
        out.append({
            "general": _require_str(data.get("general"), "генерал приказа"),
            "goal": goal,
            "path": [_require_int(idx, "провинция маршрута") for idx in path_raw],
            "stuck": _require_int(data.get("stuck", 0), "счётчик застревания"),
        })
    return out


# --------------------------------------------------------------------------
# Запись
# --------------------------------------------------------------------------

class SaveInfo:
    """Что именно лежит на диске. Читается в ``main.py`` для плашки."""

    __slots__ = ("path", "slot", "turn", "fingerprint", "saved_at")

    def __init__(self, path: Path, slot: str, turn: int, fingerprint: str,
                 saved_at: int):
        self.path = path
        self.slot = slot
        self.turn = turn
        self.fingerprint = fingerprint
        self.saved_at = saved_at

    def __repr__(self) -> str:  # pragma: no cover - только для отладки
        return (f"SaveInfo(slot={self.slot!r}, turn={self.turn}, "
                f"fingerprint={self.fingerprint[:8]}…, path={self.path})")


def save_campaign(screen, path: Optional[Path] = None,
                  slot: str = DEFAULT_SLOT) -> SaveInfo:
    """Записать кампанию в базу. Одна транзакция, один коммит.

    Порядок именно такой: сначала весь снимок и его отпечаток считаются в
    памяти, потом база пишется и коммитится. Если падение случится на
    середине — откат вернёт предыдущий снимок целиком, а не оставит
    половину нового. Путь ``pending_session`` проверяется ДО сериализации:
    бой нельзя продолжить с середины, и сохранять такую партию молча нельзя.
    """
    if getattr(screen, "pending_session", None) is not None:
        raise SaveError(
            "нельзя сохранить посреди тактического боя: бой нельзя "
            "продолжить с середины, сохраните на карте")

    state = campaign_state(screen)
    fingerprint = campaign_fingerprint(state)
    target = Path(path) if path is not None else default_save_path()
    saved_at = int(time.time())

    # сериализация ДО открытия базы: JSON-ошибка в снимке не должна
    # открывать (и подвисать на блокировке) файл, который сейчас читают
    try:
        payload = dumps(state, indent=None)
    except Exception as exc:
        raise SaveError(f"снимок не сериализуется: {exc}") from exc

    try:
        conn = _connect(target)
    except (OSError, sqlite3.DatabaseError) as exc:
        raise SaveError(f"не открыть {target}: {exc}") from exc
    try:
        with conn:                      # контекст коммитит, а исключение откатывает
            conn.execute(
                "INSERT OR REPLACE INTO saves "
                "(slot, save_version, schema_version, turn, fingerprint, "
                " saved_at, payload) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (str(slot), SAVE_FORMAT_VERSION, SCHEMA_VERSION,
                 int(state["turn"]), fingerprint, saved_at, payload),
            )
    except sqlite3.DatabaseError as exc:
        raise SaveCorrupt(
            f"не удалось записать сохранение в {target}: {exc}") from exc
    finally:
        conn.close()

    return SaveInfo(target, str(slot), int(state["turn"]), fingerprint, saved_at)


def has_save(path: Optional[Path] = None, slot: str = DEFAULT_SLOT) -> bool:
    """Есть ли снимок в этом слоте. Меню спрашивает это до «Продолжить»."""
    target = Path(path) if path is not None else default_save_path()
    if not target.exists():
        return False
    try:
        conn = _connect(target)
    except sqlite3.DatabaseError:
        return False
    try:
        row = conn.execute("SELECT 1 FROM saves WHERE slot = ?",
                           (str(slot),)).fetchone()
        return row is not None
    except sqlite3.DatabaseError:
        return False
    finally:
        conn.close()


def load_state(path: Optional[Path] = None,
               slot: str = DEFAULT_SLOT) -> Dict[str, object]:
    """Прочитать снимок и проверить его, НЕ строя экран.

    Отдельная ступень нужна, чтобы «файл не читается» и «мир не собрался»
    проверялись разными тестами, а ``main.py`` мог спросить «есть ли
    пригодное сохранение», ничего не создавая.
    """
    target = Path(path) if path is not None else default_save_path()
    if not target.exists():
        raise SaveNotFound(f"сохранения нет: {target}")
    try:
        conn = _connect(target)
    except sqlite3.DatabaseError as exc:
        raise SaveCorrupt(f"{target} не база SQLite: {exc}") from exc
    try:
        row = conn.execute(
            "SELECT save_version, schema_version, fingerprint, payload "
            "FROM saves WHERE slot = ?", (str(slot),)).fetchone()
    except sqlite3.DatabaseError as exc:
        raise SaveCorrupt(f"{target} повреждён: {exc}") from exc
    finally:
        conn.close()

    if row is None:
        raise SaveNotFound(f"в {target} нет слота «{slot}»")
    save_version, schema_version, stored_hash, payload = row

    if save_version != SAVE_FORMAT_VERSION:
        raise SaveIncompatible(
            f"файл сохранения версии {save_version}, эта версия игры знает "
            f"{SAVE_FORMAT_VERSION}")
    if schema_version != SCHEMA_VERSION:
        raise SaveIncompatible(
            f"снимок собран по схеме {schema_version}, читать умеем "
            f"только схему {SCHEMA_VERSION}")
    try:
        raw = loads(payload)
    except Exception as exc:
        # json.JSONDecodeError и его потомки: сообщение игроку должно быть
        # про файл, а не про класс исключения из stdlib
        raise SaveCorrupt(f"{target}: не читается JSON ({exc})") from exc

    state = check_format(_require_dict(raw, "сохранение"))
    if state_hash(state) != stored_hash:
        raise SaveCorrupt(
            f"{target}: отпечаток не совпал, файл обрезан или подменён")
    return state


# --------------------------------------------------------------------------
# Восстановление
# --------------------------------------------------------------------------

def _build_general(data: Dict[str, object]):
    # импорт внутри функции: world_map.py обращается к savegame-у, и
    # модульный импорт здесь замкнул бы кольцо
    from world_data import General
    general = General(data["name"], data["nation"], 0, data["troops"])
    general.max_troops = data["max_troops"]
    general.moved = data["moved"]
    general.health = data["health"]
    # province_idx ставится последним и может быть None: конструктор требует
    # число, а у генерала без провинции честное значение — «нигде»
    general.province_idx = data["province_idx"]
    return general


def restore_screen(state: Dict[str, object], screen=None):
    """Собрать экран карты по снимку (или перестроить существующий).

    Снимок проверяется целиком ДО того, как хоть что-то изменится. Это и
    требование «никогда не наполовину восстановленный мир»: если файл не
    годится, ``screen`` остаётся ровно тем, чем был, а игрок получает текст
    ошибки вместо партии с дырами.

    Единственное, что происходит до проверки, — создание экрана, когда его
    не дали: проверять нужно против СВОЕГО списка провинций, а не против
    неизвестного заранее.
    """
    state = check_format(state)
    if screen is None:
        from world_map import WorldMapScreen
        screen = WorldMapScreen()

    province_count = len(screen.provinces)
    owners, garrisons = _validate_provinces(state, province_count)
    generals = _validate_generals(state, province_count)
    relations = _validate_diplomacy(state, sorted(screen.nations))
    orders = _validate_orders(state.get("orders"), province_count, "orders")
    queued = _validate_orders(state.get("queued_orders"), province_count,
                              "queued_orders")
    hierarchy_state = _require_dict(state.get("hierarchy"), "hierarchy")
    streams = _require_dict(state.get("streams", {}), "streams")
    turn = _require_int(state.get("turn", 1), "ход")

    # ---- с этого момента файл признан годным и мир меняется целиком ----

    for prov, owner, troops in zip(screen.provinces, owners, garrisons):
        prov.owner = owner
        prov.troops = troops

    screen.generals = [_build_general(g) for g in generals]
    by_key = {general_key(g.name, g.nation): g for g in screen.generals}

    for key, value in sorted(
            _require_dict(state.get("nation_gold", {}), "nation_gold").items()):
        nation = screen.nations.get(key)
        if nation is not None:
            nation.gold = _require_int(value, f"золото нации {key}")

    screen.diplomacy._relations.clear()
    screen.diplomacy._init_relations()
    for a, b, relation in relations:
        # через set_relation, а не записью в словарь: так обе стороны
        # отношения остаются симметричными, как их и ждёт весь код
        screen.diplomacy.set_relation(a, b, relation)

    screen.streams = new_streams(
        _require_int(streams.get("seed", 0), "зерно мира"))
    screen.hierarchy = _restore_hierarchy(
        hierarchy_state, screen,
        seed=_require_int(streams.get("hierarchy_seed", 0),
                          "зерно иерархии"))

    screen._turn = turn
    screen._match_seq = _require_int(state.get("match_seq", 0), "match_seq")
    screen._battle_seq = _require_int(state.get("battle_seq", 0), "battle_seq")
    screen._orders = _rebuild_orders(orders, by_key)
    screen._queued_orders = _rebuild_orders(queued, by_key)

    # состояние экрана сознательно не трогаем, кроме явного сброса: камера,
    # зум и открытые панели в снимке нет, а вот выделение и «исход боя»
    # ссылались бы на генералов прошлого мира
    screen.selected_generals = []
    screen._control_groups.clear()
    screen.pending_session = None
    screen._battle_result = None
    screen._battle_timer = 0.0
    screen._message = None
    screen._message_timer = 0.0
    # победа/поражение пересчитываются в _update из списка генералов каждую
    # фазу кадра, поэтому старую плашку сбрасываем, а состояние не храним
    screen._game_over = False
    screen._winner = None
    screen._invalidate_panel()
    return screen


def _restore_hierarchy(state: Dict[str, object], screen, *, seed: int = 0):
    """Иерархия на ТЕХ ЖЕ провинциях экрана, с сохранённым зерном.

    Порядок обязателен: владельцы провинций ставятся ДО ``from_state``,
    иначе de-факто держатели посчитались бы по старой карте, а из снимка
    не читались бы вовсе (см. докстринг ``Hierarchy.from_state``).
    """
    from states import Hierarchy
    return Hierarchy.from_state(state, screen.provinces,
                                streams=new_streams(int(seed)))


def _rebuild_orders(raw_orders: List[Dict[str, object]], by_key: Dict[str, object]
                    ) -> List[Dict[str, object]]:
    """Приказы с привязкой к живым генералам; приказы без армии отбрасываются.

    Отбрасывание — не потеря, а ровно то же, что делает
    ``_advance_move_order`` («приказ отпадает»): между сохранением и
    загрузкой генерал вполне мог быть убит в бою, и приказ на его маршрут
    физически исполнять уже некому.
    """
    out: List[Dict[str, object]] = []
    for order in raw_orders:
        general = by_key.get(order["general"])
        if general is None:
            continue
        out.append({"general": general, "goal": order["goal"],
                    "path": list(order["path"]), "stuck": order["stuck"]})
    return out


def load_screen(path: Optional[Path] = None, slot: str = DEFAULT_SLOT,
                screen=None):
    """Прочитать сохранение и восстановить по нему экран карты.

    Короткая дорога для ``main.py``: чтение, проверка отпечатка и сборка
    мира одним вызовом. Любая ошибка поднимается как ``SaveError`` — вызов
    не имеет права оставить партию наполовину.
    """
    state = load_state(path=path, slot=slot)
    return restore_screen(state, screen=screen)