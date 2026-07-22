from menu import MainMenu, CampaignSelect, VictoryScreen
from campaigns import MISSIONS


def main():
    current_mission = None

    while True:
        if current_mission is not None:
            from engine import GameEngine
            engine = GameEngine(mission=current_mission)
            next_mission = engine.run()

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
            from engine import GameEngine
            engine = GameEngine()
            engine.run()
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
        else:
            break


if __name__ == "__main__":
    main()
