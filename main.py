from menu import MainMenu, CampaignSelect, VictoryScreen, TutorialScreen
from campaigns import MISSIONS
from war import WarSession, BattleOutcome, outcome_to_world


def _autosave(world_screen) -> None:
    """Сохранить партию при выходе с карты в меню.

    Раньше выход в меню просто выбрасывал экран вместе со всей партией, и
    двадцать ходов исчезали молча. Теперь выход сохраняет, а F5 на карте
    сохраняет явно.

    Отказ не роняет игру: сохранение может быть невозможно (партия кончена,
    бой не доигран), и это не повод закрывать окно.
    """
    if world_screen is None:
        return
    try:
        world_screen.save_game()
    except Exception:
        # экран мог не иметь метода (тестовая заглушка) или упасть на
        # отрисовке плашки; сохранение не обязано быть сильнее выхода
        pass


def _open_world():
    """Экран карты из сохранения, если оно есть, иначе новая партия.

    Один вход из главного меню делает обе вещи без новой кнопки: пункт
    «ГЛОБАЛЬНАЯ КАРТА» продолжает партию, если она сохранена, и начинает
    новую, если сохранения нет. Так «продолжить» работает сразу, без
    отдельного экрана выбора сохранений, которого в игре не существует.
    """
    from savegame import SaveError, has_save, load_screen
    from world_map import WorldMapScreen

    if not has_save():
        return WorldMapScreen()
    try:
        return load_screen()
    except SaveError as exc:
        # битое сохранение не должно запрещать игру: говорим ПОЧЕМУ оно не
        # читается (текст ошибки написан специально для игрока) и начинаем
        # партию с нуля, а не падаем на пустом меню
        print(f"[save] {exc}")
        return WorldMapScreen()


def _run_tactics(mission=None, session=None):
    """Прогнать тактический бой. Вернуть (следующая миссия, исход боя).

    ``GameEngine.run()`` по-прежнему отдаёт только ``Optional[int]`` — номер
    следующей миссии, — поэтому два разных вопроса («какая миссия дальше» и
    «чем кончился бой») идут разными дорогами: первый через возвращаемое
    значение, второй через ``engine.outcome`` и ``engine.build_outcome()``.

    ``outcome`` равен ``None`` у обычного тренировочного боя и миссии: миру
    такие бои ничего не должны. Если бой шёл по сессии, но игрок закрыл его
    через ESC, не доиграв, собирается честная квитанция без победителя — мир
    засчитает это отступление (потери есть, награды нет).
    """
    from engine import GameEngine
    engine = GameEngine(mission=mission, session=session)
    next_mission = engine.run()

    outcome = engine.outcome
    if outcome is None and session is not None:
        outcome = engine.build_outcome()
    return next_mission, outcome


def _run_world(world_screen):
    """Мир -> тактика (если игрок заявился) -> тот же мир.

    Возвращает экран, если игрок остался в партии, и ``None``, если ушёл
    (ESC или конец партии). Ключевая деталь: экран ЗДЕСЬ создаётся снаружи и
    переиспользуется. Раньше ``main`` строил новый ``WorldMapScreen`` при
    каждом заходе в карту, а тот в конструкторе заново строил иерархию владений
    и генералов — захваченные провинции и казну приходилось завоёвывать
    заново после каждого боя.
    """
    session = world_screen.run()
    if not isinstance(session, WarSession):
        # сессии нет: игрок закрыл карту, либо королевство пало/победило
        return None

    _next_mission, outcome = _run_tactics(session=session)
    if isinstance(outcome, BattleOutcome):
        world_screen.apply_outcome(outcome_to_world(session, outcome))
    world_screen.reopen()
    return world_screen


def main():
    current_mission = None
    # экран мира живёт между заходами: тот же объект, то же состояние
    world_screen = None
    world_active = False

    while True:
        if world_active:
            world_active = False
            # экран запоминаем ДО _run_world: тот возвращает None, когда
            # игрок ушёл с карты, и после этого держать объект для
            # сохранения было бы уже нечем
            screen = world_screen
            world_screen = _run_world(screen)
            if world_screen is None or world_screen.is_finished:
                # партия кончена — перезаписывать ею хорошее сохранение
                # нельзя, поэтому автосохранение только при обычном выходе
                if world_screen is None and not screen.is_finished:
                    _autosave(screen)
                world_screen = None
                continue
            # вернулись из тактики — сразу обратно на карту, а не в меню
            world_active = True
            continue

        if current_mission is not None:
            next_mission, _outcome = _run_tactics(mission=current_mission)

            if next_mission is not None and next_mission in MISSIONS:
                victory_screen = VictoryScreen(current_mission, next_mission)
                result = victory_screen.run()
                if result == "next":
                    current_mission = next_mission
                    continue
                elif result == "menu":
                    current_mission = None
                    continue
                else:
                    break
            else:
                current_mission = None
                continue

        menu = MainMenu()
        result = menu.run()

        if result is None:
            break
        elif result == "battle":
            _run_tactics()
        elif result == "campaign":
            campaign_select = CampaignSelect()
            campaign_result = campaign_select.run()
            if campaign_result and campaign_result.startswith("campaign_"):
                mission_num = int(campaign_result.split("_")[1])
                current_mission = mission_num
            elif campaign_result == "back":
                continue
            else:
                break
        elif result == "world_map":
            # тот же пункт меню продолжает сохранённую партию и начинает
            # новую, если сохранения нет (см. _open_world)
            world_screen = _open_world()
            world_active = True
            continue
        elif result == "tutorial":
            tutorial = TutorialScreen()
            tutorial.run()
        else:
            break


if __name__ == "__main__":
    try:
        main()
    finally:
        # видеорежим живёт всё время игры: тактика открывается поверх карты,
        # поэтому глушить pygame можно только здесь, последним действием
        import pygame

        pygame.quit()