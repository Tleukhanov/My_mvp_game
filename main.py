from menu import MainMenu, CampaignSelect


def main():
    while True:
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
                from engine import GameEngine
                engine = GameEngine(mission=mission_num)
                engine.run()
        else:
            break


if __name__ == "__main__":
    main()
