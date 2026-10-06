"""Регрессионные тесты баланса тактического боя.

Тесты опираются на измерения ``balance.py`` и держат три инварианта, которые
заданы как требования к бою:

1. равные армии обязаны доигрываться и делить победу примерно поровну;
2. перевес 4:1 должен быть явно в пользу сильного, но не автоматическим;
3. разгром 7.5:1 — это почти наверняка поражение, но не приговор.

Три из них движок сегодня НЕ выполняет, поэтому они помечены
``xfail(strict=True)``. Метка не «прячет» проблему: ``strict=True`` означает,
что как только инвариант начнёт выполняться, тест станет падать с сообщением
«XPASS» — и метку придётся снять руками. Это сигнал «починили, проверьте
замер», а не зелёная галочка на несуществующем балансе.

Что стоит знать про числа в тестах.

* Зерно сессии движком не читается (см. ``test_session_seed_does_not_change_a_battle``),
  поэтому «прогон по зёрнам» — это один и тот же бой. Настоящее распределение
  исходов даёт разброс начальных позиций (``BattleSpec.jitter_px``): армии те
  же, коэффициенты те же, различается только микроскопический расклад колонн.
* Тесты меряют на трёх отрядах (``300``-``400`` солдат на сторону), а не на
  девяти: девять отрядов стоят вчетверо дороже по времени, а соотношения и
  выводы те же. Отчёты в ``balance.py`` считаются на девяти.
* Ширины допусков выбраны так, чтобы «срез лезвия» (один хаотичный бой
  может перевернуться от мелочи вроде другой версии libm) не ронял тест, но
  настоящий перекос — сто процентов побед одной стороны или нули — ловил.
"""
import os

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"

import pytest
import pygame

pygame.init()
pygame.display.set_mode((1, 1))

from balance import (  # noqa: E402  (pygame поднят выше, до импорта движка)
    BLUE,
    RED,
    UNRESOLVED,
    BattleSpec,
    exact_binomial_two_sided,
    probe_team_order,
    run_battle,
    run_sweep,
    wilson_interval,
)
from engine import GameEngine  # noqa: E402
from war import (  # noqa: E402
    QUALITY_MAX,
    TACTICS_UNIT_CAP,
    TROOPS_PER_TACTICAL_UNIT,
    WarSession,
    defender_units_for,
    tactical_units_for,
)

#: Равные армии: три отряда на сторону, 300 солдат на отряд — ровно штатный
#: масштаб, поэтому множитель силы равен 1.0 и сравнивается «чистый» бой.
PARITY = (300, 300)

#: Перевес 4:1: девять отрядов атакующего (1200 солдат) против трёх (300).
STRONGER_4X = (1200, 300)

#: Разгром 7.5:1: 2250 солдат девятью отрядами против 300 тремя.
STRONGER_7H5X = (2250, 300)

#: Конфигурация, которая demonstrably замирает: перевес всего 10%, а бой всё
#: равно не доигрывается. Берётся вместо 1200:1200, где та же болезнь стоит
#: вчетверо дороже по времени.
DEADLOCK = (330, 300)

#: Сколько «равных боёв» набираем для распределения исходов. Восемь —
#: минимум, при котором наблюдаемые «8 из 8» дают доверительный интервал
#: Уилсона [67.6%, 100%] и этого достаточно, чтобы ОПРОВЕРГНУть «4:1 не
#: автоматический» (точка 100% выше потолка 95%); чтобы такой инвариант потом
#: подтвердить, выборку надо увеличить вчетверо.
ENSEMBLE = 8


def _equal_battles(attacker_troops, defender_troops, samples=ENSEMBLE,
                   jitter=6.0):
    """Прогнать ``samples`` равных боёв: те же армии, разный расклад колонн."""
    return [run_battle(BattleSpec(attacker_troops, defender_troops,
                                  seed=seed, jitter_px=jitter))
            for seed in range(1, samples + 1)]


def _troops_scale(troops: int, units: int) -> float:
    """Масштаб прочности отряда из самого движка (без запуска боя)."""
    return GameEngine._troops_per_unit_scale(troops, units)


class TestHarnessIsTrustworthy:
    """Инструмент замера должен быть честным, иначе меряем не то."""

    def test_session_seed_does_not_change_a_battle(self):
        """Зерно сессии на тактический бой не влияет вообще.

        Движок не читает ``WarSession.seed`` ни разу, а единственный потребитель
        глобального ``random`` — ``UnitAI._flank_side``, который читается только
        в состоянии FLANK, куда попадает лишь кавалерия, а войска из сессии
        сплошь пехота. Проверено на зависшем бою: два зерна дают побайтово
        одинаковый результат.

        Если тест начнёт падать — это хорошие новости: случайность в бою
        появилась, и win_rate по зёрнам снова станет оценкой вероятности.
        """
        a = run_battle(BattleSpec(*DEADLOCK, seed=1))
        b = run_battle(BattleSpec(*DEADLOCK, seed=99))
        assert (a.outcome, a.ticks, a.blue_alive, a.red_alive,
                a.blue_hp, a.red_hp) == \
               (b.outcome, b.ticks, b.blue_alive, b.red_alive,
                b.blue_hp, b.red_hp)

    def test_half_timestep_gives_the_same_verdict(self):
        """1/30 вместо игровых 1/60 не меняет исход на счётных конфигурациях.

        Ради этого ускорения всё и сделано: вдвое меньше тиков на тот же бой.
        Оговорка зафиксирована в отчёте честно — на пограничных соотношениях
        вроде 1320:1200 шаг всё же переворачивает исход, потому что там бой
        решается с точностью до одного раненого юнита.
        """
        full = run_battle(BattleSpec(*STRONGER_7H5X, seed=1, dt=1.0 / 60.0))
        half = run_battle(BattleSpec(*STRONGER_7H5X, seed=1, dt=1.0 / 30.0))
        assert full.outcome == half.outcome == BLUE
        assert half.ticks < full.ticks

    def test_stall_detection_reports_a_frozen_battle(self):
        """Замерший бой помечается stalled и не выдаётся за победу."""
        frozen = run_battle(BattleSpec(*DEADLOCK, seed=1))
        assert frozen.stalled is True
        assert frozen.outcome == UNRESOLVED

        decided = run_battle(BattleSpec(*PARITY, seed=1))
        assert decided.stalled is False
        assert decided.resolved is True

    def test_stall_detection_matches_a_long_run(self):
        """Предохранитель зависания не обрывает бой, который доигрался бы.

        Тот же бой без ограничителя зависания и с длинным потолком обязан
        остаться недоигранным: иначе «не доигралось» означало бы «проиграло»,
        а это ровно тот подменяющий вывод, который стенд запрещает.
        """
        with_guard = run_battle(BattleSpec(*DEADLOCK, seed=1))
        without_guard = run_battle(BattleSpec(*DEADLOCK, seed=1,
                                              stall_ticks=0,
                                              max_ticks=30 * 200))
        assert without_guard.outcome == UNRESOLVED
        assert without_guard.stalled is False
        assert with_guard.ticks < without_guard.ticks

    def test_jitter_touches_positions_only(self):
        """Разброс расклада не должен двигать ни силу, ни состав войск."""
        plain = run_battle(BattleSpec(*STRONGER_4X, seed=1, max_ticks=1))
        shaken = run_battle(BattleSpec(*STRONGER_4X, seed=1,
                                       jitter_px=6.0, max_ticks=1))
        assert (plain.blue_start_hp, plain.red_start_hp) == \
               (shaken.blue_start_hp, shaken.red_start_hp)
        assert (plain.blue_start_units, plain.red_start_units) == \
               (shaken.blue_start_units, shaken.red_start_units)

    def test_passive_blue_cannot_deal_damage(self):
        """Без зеркального ИИ синие не бьют вообще — это свойство движка.

        В движке ИИ есть только у красных (``_setup_units`` регистрирует лишь
        ``red_units``), синими командует игрок. Если стенд начнёт «измерять»
        синюю сторону без ИИ, он измеряет статую, и это обязано быть видно в
        тесте, а не спрятано в настройке прогона.
        """
        passive = run_battle(BattleSpec(*PARITY, seed=1, mirror_ai=False,
                                        max_ticks=30 * 200))
        assert passive.red_hp == passive.red_start_hp

        mirrored = run_battle(BattleSpec(*PARITY, seed=1, mirror_ai=True,
                                         max_ticks=30 * 200))
        assert mirrored.red_hp < mirrored.red_start_hp

    def test_statistics_helpers_are_sane(self):
        """Разброс по выборке должен быть честным на обоих краях.

        При 8 из 8 Уилсон даёт [67.6%, 100%] — ровно та ширина, которая нужна,
        чтобы отличить «всегда» от «почти всегда». Именно поэтому восьми
        равных боёв хватает, чтобы ОПРОВЕРГНУТЬ инвариант (точка 100% выше
        потолка 95%), но не хватает, чтобы его подтвердить: для сертификации
        «85-95%» нужно 30-60 равных боёв, и стенд должен быть перезапущен с
        большей выборкой перед тем, как объявлять инвариант выполненным.
        """
        low, high = wilson_interval(8, 8)
        assert low == pytest.approx(0.676, abs=0.01)
        assert high == pytest.approx(1.0, abs=1e-9)
        assert wilson_interval(0, 0) == (0.0, 1.0)

        # Точный критерий: 8 из 8 — это не 50/50, а именно 8 из 8.
        assert exact_binomial_two_sided(8, 8) < 0.01
        assert exact_binomial_two_sided(4, 8) > 0.5
        assert exact_binomial_two_sided(0, 8) < 0.01

    def test_order_probe_reveals_the_bias_mechanism(self):
        """Диагностика порядка обязана отличать «естественный» порядок от иного.

        Это не тест баланса, а тест самого способа вскрытия: если перестановка
        юнитов перестанет что-либо менять, значит механизм перекоса починен,
        диагностика стала бесполезной — и об этом лучше узнать из теста.
        Тот же приём на 9 отрядах даёт natural 5/3, red-first 7/1.
        """
        spec = BattleSpec(*PARITY, seed=1)
        natural = probe_team_order(spec, mode="natural")
        swapped = probe_team_order(spec, mode="red-first")
        assert (natural.outcome, natural.blue_alive, natural.red_alive) != \
               (swapped.outcome, swapped.blue_alive, swapped.red_alive)


class TestStructuralInvariants:
    """Свойства, которые движок держит уже сегодня — их надо удержать."""

    @pytest.mark.parametrize("attacker,defender", [
        (500, 500), (1200, 1200), (1200, 3000), (3000, 400),
        (1200, 300), (2250, 300), (300, 400),
    ])
    def test_both_sides_field_the_same_number_of_units(self, attacker, defender):
        """На поле выходят ровно те отряды, за которых заплатили, и столько же
        у противника.

        Это и есть смысл последней правки: 1200 против 3000 больше не
        превращается в «9 против 4», потому что меньшая армия выглядела
        разобранной из-за потолка ``TACTICS_UNIT_CAP``.
        """
        ws = WarSession(match_id=1, attacker_nation="a", defender_nation="b",
                        province_idx=0, general_name="g",
                        troops_committed=attacker, defender_troops=defender)
        units = ws.battle_units
        assert units == min(ws.tactical_units, ws.defender_units,
                            TACTICS_UNIT_CAP)
        assert 1 <= units <= TACTICS_UNIT_CAP

    @pytest.mark.parametrize("attacker,defender", [
        (300, 300), (1200, 300), (2250, 300), (300, 400), (3000, 400),
    ])
    def test_total_health_ratio_equals_troop_ratio(self, attacker, defender):
        """Суммарное HP обеих сторон относится ровно так же, как левейс.

        Перенос перевеса в прочность отряда бессмыслен, если он теряется по
        дороге: при 7.5:1 суммарное здоровье должно быть в 7.5 раза больше, а
        не «примерно». Один тик достаточен: расклад и здоровье ставятся в
        конструкторе движка.
        """
        report = run_battle(BattleSpec(attacker, defender, seed=1, max_ticks=1))
        assert report.blue_start_units == report.red_start_units
        expected = attacker / float(defender)
        assert report.hp_ratio == pytest.approx(expected, rel=0.01), (
            f"{attacker}:{defender} -> HP x{report.hp_ratio:.3f}, "
            f"ожидалось x{expected:.3f}")

    @pytest.mark.parametrize("quality", [1, 2, 3, 4])
    def test_quality_is_applied_to_both_sides(self, quality):
        """Выучка одинакова для обеих сторон и не может перекосить бой.

        ``_add_session_warriors`` берёт ``quality_bonuses`` из сессии и
        применяет к синим и к красным одинаково, так что в бою из мира
        качество не влияет на исход вовсе: это «выучка пехоты», а не чья-то
        фора. Четвёртое значение срезается потолком ``QUALITY_MAX``.
        """
        plain = run_battle(BattleSpec(*PARITY, seed=1, quality=1, max_ticks=1))
        report = run_battle(BattleSpec(*PARITY, seed=1, quality=quality,
                                       max_ticks=1))
        assert report.blue_start_hp == report.red_start_hp
        if quality > QUALITY_MAX:
            top = run_battle(BattleSpec(*PARITY, seed=1,
                                        quality=QUALITY_MAX, max_ticks=1))
            assert report.blue_start_hp == top.blue_start_hp
        else:
            assert report.blue_start_hp >= plain.blue_start_hp

    def test_quality_does_not_change_the_winner(self):
        """Гвардия и обычная пехота дают один и тот же исход боя."""
        low = run_battle(BattleSpec(*STRONGER_4X, seed=1, quality=1))
        high = run_battle(BattleSpec(*STRONGER_4X, seed=1, quality=3))
        assert low.outcome == high.outcome


class TestBalanceInvariants:
    """Требования к бою. Сегодня не выполняются — помечены xfail."""

    @pytest.mark.xfail(strict=True, reason=(
        "равные армии 1200:1200 не доигрываются: 0 из 24 боёв закончились "
        "исходом за 600 игровых секунд, все замерли на 1-5 уцелевших отрядах"))
    def test_equal_armies_battle_must_resolve(self):
        """1200 против 1200 обязаны доиграться, а не замереть.

        Проверяется ровно та конфигурация, которую назвали в задании, целиком
        (девять отрядов на сторону). Зерно одно, и это честно: зерно на такой
        бой не влияет, что закреплено выше отдельным тестом.
        """
        report = run_battle(BattleSpec(1200, 1200, seed=1))
        assert report.resolved, (
            f"бой не доигран за {report.seconds:.0f} с: уцелело синих "
            f"{report.blue_alive}, красных {report.red_alive}")

    @pytest.mark.xfail(strict=True, reason=(
        "при равном левейсе синий выигрывает все доигранные бои: на карте, "
        "заявленной симметричной, исход решает порядок юнитов в "
        "engine.all_units (см. probe_team_order), а синие там всегда первые"))
    def test_equal_armies_must_be_a_coin_flip(self):
        """Равные армии — это 50/50, а не «сколько выиграет синий».

        Допуск 0.3..0.7 по восьми равным боям: два-три переворота честной
        монетки в него укладываются, а настоящий перекос (12 из 12) — нет.
        """
        reports = _equal_battles(*PARITY)
        decided = [r for r in reports if r.resolved]
        assert len(decided) >= 6, (
            f"доигралось только {len(decided)} из {len(reports)}")
        blue_share = sum(1 for r in decided if r.outcome == BLUE) / len(decided)
        assert 0.3 <= blue_share <= 0.7, (
            f"синий победил в {blue_share * 100:.0f}% доигранных боёв")

    @pytest.mark.xfail(strict=True, reason=(
        "перевес 4:1 выигрывается в 8 боях из 8: исход детерминирован, "
        "вероятности у боя в движке нет вовсе"))
    def test_four_to_one_is_clearly_but_not_automatic(self):
        """4:1 — это «почти наверняка да», но не «всегда».

        Целевая полоса 85-95% сильного: ниже — перевес не читается как
        перевес, выше — бой превращается в формальность.
        """
        reports = _equal_battles(*STRONGER_4X)
        wins = sum(1 for r in reports if r.outcome == BLUE)
        rate = wins / float(len(reports))
        assert 0.85 <= rate <= 0.95, (
            f"синий победил в {rate * 100:.0f}% из {len(reports)} равных боёв")

    @pytest.mark.xfail(strict=True, reason=(
        "при 7.5:1 слабая сторона не выигрывает ни разу: 0 из 24 зёрен и 0 из "
        "8 равных боёв, потому что у боя нет случайности"))
    def test_seven_and_a_half_to_one_is_not_a_death_sentence(self):
        """Разгром должен быть почти всегда поражением, но не всегда.

        Хотя бы одна победа слабой стороны на восемь равных боёв — самый
        дешёвый честный критерий «это ещё бой, а не казнь».
        """
        reports = _equal_battles(*STRONGER_7H5X)
        weaker_wins = sum(1 for r in reports if r.outcome == RED)
        assert weaker_wins >= 1, (
            f"слабый не выиграл ни разу из {len(reports)}")


class TestSweepAggregation:
    """Агрегат прогона должен считаться честно, включая недоигранные бои."""

    def test_sweep_counts_timeouts_as_non_wins(self):
        """Недоигранный бой не должен попадать в победу сильной стороны."""
        row = run_sweep(PARITY[0], PARITY[1], seeds=[1, 2], max_ticks=1)
        assert row.seeds == 2
        # потолок в один тик: ни один бой не успевает решиться
        assert row.decided == 0
        assert row.unresolved == 2
        assert row.win_rate == 0.0
        assert row.decided_win_rate == 0.0

    def test_sweep_reports_both_sides_survivors(self):
        """В строке прогона видно, сколько отрядов уцелело у каждой стороны."""
        row = run_sweep(*STRONGER_4X, seeds=[1])
        assert row.stronger == BLUE
        assert row.wins == 1
        assert row.avg_weaker_alive == 0.0
        assert row.avg_stronger_alive > 0.0
        assert row.avg_hp_ratio == pytest.approx(4.0, rel=0.01)

    def test_hp_scale_is_monotone_in_troops(self):
        """Масштаб прочности отряда обязан расти с левейсом.

        Монотонность — единственное свойство, на котором держится вся идея
        «перевес переехал в прочность отряда»: если бы 3000 солдат давали отряд
        слабее, чем 1200, число отрядов перестало бы что-то значить.
        """
        scales = [_troops_scale(t, 3) for t in (300, 600, 1200, 2400, 3000)]
        assert scales == sorted(scales)
        assert scales[0] == pytest.approx(1.0)

    def test_troops_per_unit_math_is_exact(self):
        """Формула масштаба обязана совпадать с формулировкой «сотня на отряд»."""
        scale = _troops_scale
        assert scale(300, 3) == pytest.approx(1.0)
        assert scale(1200, 3) == pytest.approx(4.0)
        assert scale(2250, 3) == pytest.approx(7.5)
        assert scale(3000, 9) == pytest.approx(
            3000 / 9 / TROOPS_PER_TACTICAL_UNIT)
        # пол в 1.0 не даёт слабой стороне стать «дырявой»
        assert scale(100, 3) == pytest.approx(1.0)
        assert scale(0, 3) == pytest.approx(1.0)


def test_war_session_math_matches_tactical_counts():
    """Боец из сессии не должен появляться из пустоты и делить паритет честно."""
    ws = WarSession(match_id=1, attacker_nation="a", defender_nation="b",
                    province_idx=0, general_name="g",
                    troops_committed=1200, defender_troops=3000)
    assert ws.battle_units == TACTICS_UNIT_CAP
    assert tactical_units_for(1200) == 9
    assert defender_units_for(ws) == 9
    # 1200 против 3000 — девять на девять, а не девять на четыре
    assert ws.battle_units == min(ws.tactical_units, ws.defender_units)
