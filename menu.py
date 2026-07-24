import pygame
import sys
from typing import Optional, Tuple
from config import (
    SCREEN_WIDTH, SCREEN_HEIGHT,
    COLOR_MENU_BG, COLOR_MENU_TITLE, COLOR_MENU_BUTTON,
    COLOR_MENU_BUTTON_HOVER, COLOR_MENU_BUTTON_TEXT,
    COLOR_MENU_BUTTON_LOCKED, COLOR_MENU_BUTTON_LOCKED_TEXT,
    COLOR_MENU_SUBTITLE, COLOR_WHITE, COLOR_BLACK,
    FONT_NAME,
)


class MenuButton:
    def __init__(self, x: int, y: int, w: int, h: int, text: str, locked: bool = False):
        self.rect = pygame.Rect(x, y, w, h)
        self.text = text
        self.locked = locked
        self.hovered = False

    def draw(self, surface: pygame.Surface, font: pygame.font.Font):
        if self.locked:
            bg = COLOR_MENU_BUTTON_LOCKED
            text_color = COLOR_MENU_BUTTON_LOCKED_TEXT
        elif self.hovered:
            bg = COLOR_MENU_BUTTON_HOVER
            text_color = COLOR_WHITE
        else:
            bg = COLOR_MENU_BUTTON
            text_color = COLOR_MENU_BUTTON_TEXT

        pygame.draw.rect(surface, bg, self.rect, border_radius=8)
        pygame.draw.rect(surface, COLOR_WHITE, self.rect, 2, border_radius=8)

        label = font.render(self.text, True, text_color)
        lx = self.rect.centerx - label.get_width() // 2
        ly = self.rect.centery - label.get_height() // 2
        surface.blit(label, (lx, ly))

    def check_hover(self, mx: int, my: int):
        self.hovered = self.rect.collidepoint(mx, my)

    def is_clicked(self, mx: int, my: int) -> bool:
        return self.rect.collidepoint(mx, my) and not self.locked


class MainMenu:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("Tactic Battle - Main Menu")
        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        self.clock = pygame.time.Clock()
        self.running = True

        self.font_title = pygame.font.SysFont(FONT_NAME, 48, bold=True)
        self.font_subtitle = pygame.font.SysFont(FONT_NAME, 18)
        self.font_button = pygame.font.SysFont(FONT_NAME, 22, bold=True)
        self.font_small = pygame.font.SysFont(FONT_NAME, 14)

        btn_w = 280
        btn_h = 55
        btn_x = SCREEN_WIDTH // 2 - btn_w // 2
        start_y = SCREEN_HEIGHT // 2 - 30

        self.buttons = [
            MenuButton(btn_x, start_y, btn_w, btn_h, "КАМПАНИЯ"),
            MenuButton(btn_x, start_y + 75, btn_w, btn_h, "СРАЖЕНИЕ"),
            MenuButton(btn_x, start_y + 150, btn_w, btn_h, "ГЛОБАЛЬНАЯ КАРТА"),
            MenuButton(btn_x, start_y + 225, btn_w, btn_h, "КАК ИГРАТЬ"),
            MenuButton(btn_x, start_y + 300, btn_w, btn_h, "ОНЛАЙН", locked=True),
        ]

        self.result: Optional[str] = None
        self._show_message: Optional[str] = None
        self._message_timer = 0.0

    def run(self) -> Optional[str]:
        while self.running:
            dt = self.clock.tick(60) / 1000.0
            self._handle_events(dt)
            self._render()
        return self.result

    def _handle_events(self, dt: float):
        if self._show_message:
            self._message_timer -= dt
            if self._message_timer <= 0:
                self._show_message = None
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                elif event.type == pygame.KEYDOWN or event.type == pygame.MOUSEBUTTONDOWN:
                    self._show_message = None
            return

        mx, my = pygame.mouse.get_pos()
        for btn in self.buttons:
            btn.check_hover(mx, my)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    self.running = False
            elif event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1:
                    self._handle_click(mx, my)

    def _handle_click(self, mx: int, my: int):
        if self.buttons[0].is_clicked(mx, my):
            self.result = "campaign"
            self.running = False
        elif self.buttons[1].is_clicked(mx, my):
            self.result = "battle"
            self.running = False
        elif self.buttons[2].is_clicked(mx, my):
            self.result = "world_map"
            self.running = False
        elif self.buttons[3].is_clicked(mx, my):
            self.result = "tutorial"
            self.running = False
        elif self.buttons[4].is_clicked(mx, my):
            self._show_message = "В РАЗРАБОТКЕ"
            self._message_timer = 2.0

    def _render(self):
        self.screen.fill(COLOR_MENU_BG)

        title = self.font_title.render("TACTIC BATTLE", True, COLOR_MENU_TITLE)
        tx = SCREEN_WIDTH // 2 - title.get_width() // 2
        self.screen.blit(title, (tx, 60))

        subtitle = self.font_subtitle.render("Napoleonic Tactics Simulator", True, COLOR_MENU_SUBTITLE)
        sx = SCREEN_WIDTH // 2 - subtitle.get_width() // 2
        self.screen.blit(subtitle, (sx, 120))

        for btn in self.buttons:
            btn.draw(self.screen, self.font_button)

        if self._show_message:
            overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 150))
            self.screen.blit(overlay, (0, 0))

            msg = self.font_title.render(self._show_message, True, COLOR_WHITE)
            mx = SCREEN_WIDTH // 2 - msg.get_width() // 2
            my = SCREEN_HEIGHT // 2 - msg.get_height() // 2
            self.screen.blit(msg, (mx, my))

            hint = self.font_small.render("Нажмите любую клавишу чтобы закрыть", True, COLOR_MENU_SUBTITLE)
            hx = SCREEN_WIDTH // 2 - hint.get_width() // 2
            self.screen.blit(hint, (hx, my + msg.get_height() + 16))

        controls = self.font_small.render("ESC: Выход", True, COLOR_MENU_SUBTITLE)
        self.screen.blit(controls, (12, SCREEN_HEIGHT - 28))

        pygame.display.flip()


class VictoryScreen:
    def __init__(self, completed_mission: int, next_mission: int):
        pygame.init()
        pygame.display.set_caption("Tactic Battle - Victory!")
        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        self.clock = pygame.time.Clock()
        self.running = True

        self.font_title = pygame.font.SysFont(FONT_NAME, 42, bold=True)
        self.font_subtitle = pygame.font.SysFont(FONT_NAME, 20)
        self.font_button = pygame.font.SysFont(FONT_NAME, 22, bold=True)
        self.font_small = pygame.font.SysFont(FONT_NAME, 14)

        self.completed_mission = completed_mission
        self.next_mission = next_mission

        btn_w = 300
        btn_h = 55
        btn_x = SCREEN_WIDTH // 2 - btn_w // 2

        self.buttons = [
            MenuButton(btn_x, SCREEN_HEIGHT // 2 + 20, btn_w, btn_h,
                       f"NEXT: MISSION {next_mission}"),
            MenuButton(btn_x, SCREEN_HEIGHT // 2 + 90, btn_w, btn_h, "CAMPAIGN MENU"),
        ]

        self.result: Optional[str] = None

    def run(self) -> Optional[str]:
        while self.running:
            dt = self.clock.tick(60) / 1000.0
            self._handle_events()
            self._render()
        return self.result

    def _handle_events(self):
        mx, my = pygame.mouse.get_pos()
        for btn in self.buttons:
            btn.check_hover(mx, my)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    self.result = "menu"
                    self.running = False
                elif event.key == pygame.K_n:
                    self.result = "next"
                    self.running = False
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self.buttons[0].is_clicked(mx, my):
                    self.result = "next"
                    self.running = False
                elif self.buttons[1].is_clicked(mx, my):
                    self.result = "menu"
                    self.running = False

    def _render(self):
        self.screen.fill(COLOR_MENU_BG)

        title = self.font_title.render("VICTORY!", True, (220, 200, 80))
        tx = SCREEN_WIDTH // 2 - title.get_width() // 2
        self.screen.blit(title, (tx, SCREEN_HEIGHT // 2 - 80))

        subtitle = self.font_subtitle.render(
            f"Mission {self.completed_mission} completed!", True, COLOR_MENU_SUBTITLE
        )
        sx = SCREEN_WIDTH // 2 - subtitle.get_width() // 2
        self.screen.blit(subtitle, (sx, SCREEN_HEIGHT // 2 - 30))

        for btn in self.buttons:
            btn.draw(self.screen, self.font_button)

        controls = self.font_small.render(
            "N: Next Mission | ESC: Campaign Menu", True, COLOR_MENU_SUBTITLE
        )
        self.screen.blit(controls, (12, SCREEN_HEIGHT - 28))

        pygame.display.flip()


class CampaignSelect:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("Tactic Battle - Campaign Select")
        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        self.clock = pygame.time.Clock()
        self.running = True

        self.font_title = pygame.font.SysFont(FONT_NAME, 36, bold=True)
        self.font_button = pygame.font.SysFont(FONT_NAME, 20, bold=True)
        self.font_desc = pygame.font.SysFont(FONT_NAME, 14)
        self.font_small = pygame.font.SysFont(FONT_NAME, 14)

        self.result: Optional[str] = None

        btn_w = 350
        btn_h = 90
        btn_x = SCREEN_WIDTH // 2 - btn_w // 2

        self.buttons = [
            MenuButton(btn_x, 150, btn_w, btn_h, "1. БИТВА У МОСТА"),
            MenuButton(btn_x, 250, btn_w, btn_h, "2. УЩЕЛЬЕ СМЕРТИ"),
            MenuButton(btn_x, 350, btn_w, btn_h, "3. РЕЧНАЯ КРЕПОСТЬ"),
            MenuButton(btn_x, 450, btn_w, btn_h, "4. ДЕРЕВНИ"),
            MenuButton(btn_x, 560, btn_w, 50, "НАЗАД"),
        ]

    def run(self) -> Optional[str]:
        while self.running:
            dt = self.clock.tick(60) / 1000.0
            self._handle_events()
            self._render()
        return self.result

    def _handle_events(self):
        mx, my = pygame.mouse.get_pos()
        for btn in self.buttons:
            btn.check_hover(mx, my)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    self.result = "back"
                    self.running = False
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self.buttons[0].is_clicked(mx, my):
                    self.result = "campaign_1"
                    self.running = False
                elif self.buttons[1].is_clicked(mx, my):
                    self.result = "campaign_2"
                    self.running = False
                elif self.buttons[2].is_clicked(mx, my):
                    self.result = "campaign_3"
                    self.running = False
                elif self.buttons[3].is_clicked(mx, my):
                    self.result = "campaign_4"
                    self.running = False
                elif self.buttons[4].is_clicked(mx, my):
                    self.result = "back"
                    self.running = False

    def _render(self):
        self.screen.fill(COLOR_MENU_BG)

        title = self.font_title.render("ВЫБОР КАМПАНИИ", True, COLOR_MENU_TITLE)
        tx = SCREEN_WIDTH // 2 - title.get_width() // 2
        self.screen.blit(title, (tx, 100))

        descs = [
            "Удержите стратегический мост через реку",
            "Пройдите через узкое горное ущелье",
            "Штурмуйте вражескую крепость у реки",
            "Захватите деревни и удержите территорию",
        ]
        for i, btn in enumerate(self.buttons[:4]):
            if i < len(descs):
                d = self.font_desc.render(descs[i], True, COLOR_MENU_SUBTITLE)
                dx = btn.rect.centerx - d.get_width() // 2
                self.screen.blit(d, (dx, btn.rect.bottom + 4))

        for btn in self.buttons:
            btn.draw(self.screen, self.font_button)

        controls = self.font_small.render("ESC: Назад", True, COLOR_MENU_SUBTITLE)
        self.screen.blit(controls, (12, SCREEN_HEIGHT - 28))

        pygame.display.flip()


class TutorialScreen:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("Tactic Battle - How to Play")
        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        self.clock = pygame.time.Clock()
        self.running = True

        self.font_title = pygame.font.SysFont(FONT_NAME, 32, bold=True)
        self.font_section = pygame.font.SysFont(FONT_NAME, 18, bold=True)
        self.font_body = pygame.font.SysFont(FONT_NAME, 14)
        self.font_small = pygame.font.SysFont(FONT_NAME, 12)

        self._page = 0
        self._pages = self._build_pages()

    def _build_pages(self):
        return [
            self._page_battle(),
            self._page_world(),
            self._page_diplomacy(),
            self._page_tips(),
        ]

    def _page_battle(self):
        return [
            ("TACTICAL BATTLE", self.font_title, COLOR_MENU_TITLE),
            ("", self.font_body, COLOR_MENU_SUBTITLE),
            ("CONTROLS", self.font_section, COLOR_WHITE),
            ("", self.font_body, COLOR_MENU_SUBTITLE),
            ("Left Click ........... Select unit", self.font_body, COLOR_HUD_TEXT),
            ("Shift + Click ........ Add to selection (max 6)", self.font_body, COLOR_HUD_TEXT),
            ("Drag (Left Mouse) .... Box select multiple units", self.font_body, COLOR_HUD_TEXT),
            ("A .................... Select all friendly units", self.font_body, COLOR_HUD_TEXT),
            ("Right Click .......... Move / Attack order", self.font_body, COLOR_HUD_TEXT),
            ("ESC .................. Deselect / Quit", self.font_body, COLOR_HUD_TEXT),
            ("SPACE ................ Toggle range indicators", self.font_body, COLOR_HUD_TEXT),
            ("R .................... Restart battle", self.font_body, COLOR_HUD_TEXT),
            ("N .................... Next mission (after victory)", self.font_body, COLOR_HUD_TEXT),
            ("", self.font_body, COLOR_MENU_SUBTITLE),
            ("COMMAND MODES (right-click behavior)", self.font_section, COLOR_WHITE),
            ("G .................... ATTACK - units pursue enemies", self.font_body, COLOR_HUD_TEXT),
            ("H .................... HOLD - move then hold position", self.font_body, COLOR_HUD_TEXT),
            ("F .................... DEFEND - move then engage nearby", self.font_body, COLOR_HUD_TEXT),
        ]

    def _page_world(self):
        return [
            ("WORLD MAP", self.font_title, COLOR_MENU_TITLE),
            ("", self.font_body, COLOR_MENU_SUBTITLE),
            ("You command Nordheim (blue). 3 nations fight for territory.", self.font_body, COLOR_HUD_TEXT),
            ("", self.font_body, COLOR_MENU_SUBTITLE),
            ("CONTROLS", self.font_section, COLOR_WHITE),
            ("", self.font_body, COLOR_MENU_SUBTITLE),
            ("Left Click ........... Select general", self.font_body, COLOR_HUD_TEXT),
            ("Left Click ........... Move selected general (1-2 tiles)", self.font_body, COLOR_HUD_TEXT),
            ("SPACE ................ End turn", self.font_body, COLOR_HUD_TEXT),
            ("D .................... Open diplomacy panel", self.font_body, COLOR_HUD_TEXT),
            ("ESC .................. Quit", self.font_body, COLOR_HUD_TEXT),
            ("", self.font_body, COLOR_MENU_SUBTITLE),
            ("HOW IT WORKS", self.font_section, COLOR_WHITE),
            ("", self.font_body, COLOR_MENU_SUBTITLE),
            ("1. Select a general by clicking on him", self.font_body, COLOR_HUD_TEXT),
            ("2. Click a nearby tile to move (max 2 tiles)", self.font_body, COLOR_HUD_TEXT),
            ("3. Moving onto enemy territory captures the region", self.font_body, COLOR_HUD_TEXT),
            ("4. Colliding with enemy general triggers a battle", self.font_body, COLOR_HUD_TEXT),
            ("5. Press SPACE to end your turn - AI moves next", self.font_body, COLOR_HUD_TEXT),
            ("6. Win by eliminating all enemy generals", self.font_body, COLOR_HUD_TEXT),
        ]

    def _page_diplomacy(self):
        return [
            ("DIPLOMACY", self.font_title, COLOR_MENU_TITLE),
            ("", self.font_body, COLOR_MENU_SUBTITLE),
            ("Press D on world map to open diplomacy.", self.font_body, COLOR_HUD_TEXT),
            ("", self.font_body, COLOR_MENU_SUBTITLE),
            ("RELATION TYPES", self.font_section, COLOR_WHITE),
            ("", self.font_body, COLOR_MENU_SUBTITLE),
            ("WAR ......... Red ... You fight on contact", self.font_body, (200, 60, 60)),
            ("NEUTRAL ..... Gray .. Cannot move through territory", self.font_body, (180, 170, 150)),
            ("FRIENDLY .... Green . Cannot enter their territory", self.font_body, (80, 180, 80)),
            ("ALLIANCE .... Blue .. Share territory freely", self.font_body, (60, 120, 220)),
            ("", self.font_body, COLOR_MENU_SUBTITLE),
            ("HOW TO USE", self.font_section, COLOR_WHITE),
            ("", self.font_body, COLOR_MENU_SUBTITLE),
            ("N / P ........ Cycle target nation", self.font_body, COLOR_HUD_TEXT),
            ("1 ........... Declare WAR", self.font_body, (200, 60, 60)),
            ("2 ........... Propose peace (NEUTRAL)", self.font_body, (180, 170, 150)),
            ("3 ........... Propose FRIENDLY (60% chance)", self.font_body, (80, 180, 80)),
            ("4 ........... Propose ALLIANCE (need FRIENDLY first)", self.font_body, (60, 120, 220)),
            ("ESC ......... Close panel", self.font_body, COLOR_HUD_TEXT),
        ]

    def _page_tips(self):
        return [
            ("TIPS & STRATEGY", self.font_title, COLOR_MENU_TITLE),
            ("", self.font_body, COLOR_MENU_SUBTITLE),
            ("TACTICAL BATTLE", self.font_section, COLOR_WHITE),
            ("", self.font_body, COLOR_MENU_SUBTITLE),
            ("- Infantry groups up before attacking - don't send alone", self.font_body, COLOR_HUD_TEXT),
            ("- Cavalry flanks from the side - great for ambushes", self.font_body, COLOR_HUD_TEXT),
            ("- Archers hold position and shoot - keep them safe", self.font_body, COLOR_HUD_TEXT),
            ("- Capture villages for food + free recruits every 3 min", self.font_body, COLOR_HUD_TEXT),
            ("- Use HOLD mode to set defensive positions", self.font_body, COLOR_HUD_TEXT),
            ("", self.font_body, COLOR_MENU_SUBTITLE),
            ("WORLD MAP", self.font_section, COLOR_WHITE),
            ("", self.font_body, COLOR_MENU_SUBTITLE),
            ("- Capture regions to expand your territory", self.font_body, COLOR_HUD_TEXT),
            ("- Make alliances before attacking strong enemies", self.font_body, COLOR_HUD_TEXT),
            ("- AI generals move toward enemies each turn", self.font_body, COLOR_HUD_TEXT),
            ("- Generals that moved cannot move again this turn", self.font_body, COLOR_HUD_TEXT),
            ("", self.font_body, COLOR_MENU_SUBTITLE),
            ("GOOD LUCK, COMMANDER!", self.font_section, COLOR_WHITE),
        ]

    def run(self) -> Optional[str]:
        while self.running:
            dt = self.clock.tick(60) / 1000.0
            self._handle_events()
            self._render()
        return "done"

    def _handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    self.running = False
                elif event.key == pygame.K_RIGHT or event.key == pygame.K_n:
                    self._page = min(self._page + 1, len(self._pages) - 1)
                elif event.key == pygame.K_LEFT or event.key == pygame.K_p:
                    self._page = max(self._page - 1, 0)
            elif event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1:
                    mx, my = event.pos
                    if my > SCREEN_HEIGHT - 40:
                        self.running = False
                    elif mx > SCREEN_WIDTH // 2:
                        self._page = min(self._page + 1, len(self._pages) - 1)
                    else:
                        self._page = max(self._page - 1, 0)

    def _render(self):
        self.screen.fill(COLOR_MENU_BG)

        lines = self._pages[self._page]
        y = 30
        for text, font, color in lines:
            if text == "":
                y += 8
                continue
            rendered = font.render(text, True, color)
            x = 40
            if font == self.font_title:
                x = SCREEN_WIDTH // 2 - rendered.get_width() // 2
            self.screen.blit(rendered, (x, y))
            y += font.get_height() + 3

        page_text = self.font_small.render(
            f"Page {self._page + 1}/{len(self._pages)}  |  Left/Right arrows to navigate  |  Click or ESC to close",
            True, COLOR_MENU_SUBTITLE
        )
        self.screen.blit(page_text, (12, SCREEN_HEIGHT - 28))

        pygame.display.flip()
