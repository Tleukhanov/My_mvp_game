from menu import MainMenu, CampaignSelect, VictoryScreen, TutorialScreen
from campaigns import MISSIONS
from war import WarSession, BattleOutcome, outcome_to_world


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
            world_screen = _run_world(world_screen)
            if world_screen is None or world_screen.is_finished:
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
            from world_map import WorldMapScreen
            world_screen = WorldMapScreen()
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