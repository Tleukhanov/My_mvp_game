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
            MenuButton(btn_x, start_y + 150, btn_w, btn_h, "ОНЛАЙН", locked=True),
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
