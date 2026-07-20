import pygame
import sys
from typing import Optional, List, Tuple
from config import (
    SCREEN_WIDTH, SCREEN_HEIGHT, HUD_HEIGHT, CELL_SIZE,
    MAP_COLS, MAP_ROWS, FPS, Team, UnitType,
    COLOR_HUD_BG, COLOR_HUD_TEXT, COLOR_HUD_TEXT_DIM,
    COLOR_WHITE, COLOR_BLACK, COLOR_BLUE, COLOR_RED,
    FONT_NAME, FONT_SIZE_HUD, FONT_SIZE_TITLE,
    COLOR_MOVE_RANGE, COLOR_ATTACK_RANGE,
)
from map import TacticalMap
from units import Unit
from pathfinding import Pathfinder
from ai import AIController

UNIT_TYPE_MAP = {
    "infantry": UnitType.INFANTRY,
    "cavalry": UnitType.CAVALRY,
    "archer": UnitType.ARCHER,
}


class GameEngine:
    def __init__(self, mission: Optional[int] = None):
        pygame.init()
        self.mission = mission
        pygame.display.set_caption("Tactic Battle - Napoleonic Simulator")
        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        self.clock = pygame.time.Clock()
        self.running = True

        self._setup_map()
        self.pathfinder = Pathfinder(self.game_map)
        self.ai_controller = AIController(self.pathfinder)

        self.all_units: List[Unit] = []
        self.blue_units: List[Unit] = []
        self.red_units: List[Unit] = []
        self.selected_unit: Optional[Unit] = None

        self._setup_units()

        self.font_hud = pygame.font.SysFont(FONT_NAME, FONT_SIZE_HUD)
        self.font_title = pygame.font.SysFont(FONT_NAME, FONT_SIZE_TITLE, bold=True)

        self._show_orders = True
        self._game_over = False
        self._winner: Optional[str] = None

    def _setup_map(self):
        if self.mission:
            from campaigns import MISSIONS
            mission_fn = MISSIONS.get(self.mission)
            if mission_fn:
                config = mission_fn()
                self.game_map = TacticalMap(config.grid)
                self._mission_config = config
                return
        self.game_map = TacticalMap()
        self._mission_config = None

    def _setup_units(self):
        if self._mission_config:
            self._setup_campaign_units()
        else:
            self._setup_skirmish_units()

        for unit in self.all_units:
            unit._pathfinder = self.pathfinder

        for unit in self.red_units:
            self.ai_controller.register_unit(unit)

    def _setup_campaign_units(self):
        for type_str, col, row in self._mission_config.blue_units:
            ut = UNIT_TYPE_MAP[type_str]
            x = col * CELL_SIZE + CELL_SIZE / 2
            y = row * CELL_SIZE + CELL_SIZE / 2
            self.blue_units.append(Unit(ut, Team.BLUE, x, y))

        for type_str, col, row in self._mission_config.red_units:
            ut = UNIT_TYPE_MAP[type_str]
            x = col * CELL_SIZE + CELL_SIZE / 2
            y = row * CELL_SIZE + CELL_SIZE / 2
            self.red_units.append(Unit(ut, Team.RED, x, y))

        self.all_units = self.blue_units + self.red_units

    def _setup_skirmish_units(self):
        blue_infantry = Unit(UnitType.INFANTRY, Team.BLUE, 3 * CELL_SIZE + CELL_SIZE / 2, 8 * CELL_SIZE + CELL_SIZE / 2)
        blue_infantry2 = Unit(UnitType.INFANTRY, Team.BLUE, 4 * CELL_SIZE + CELL_SIZE / 2, 10 * CELL_SIZE + CELL_SIZE / 2)
        blue_cavalry = Unit(UnitType.CAVALRY, Team.BLUE, 5 * CELL_SIZE + CELL_SIZE / 2, 12 * CELL_SIZE + CELL_SIZE / 2)
        blue_archer = Unit(UnitType.ARCHER, Team.BLUE, 2 * CELL_SIZE + CELL_SIZE / 2, 14 * CELL_SIZE + CELL_SIZE / 2)

        red_infantry = Unit(UnitType.INFANTRY, Team.RED, 36 * CELL_SIZE + CELL_SIZE / 2, 8 * CELL_SIZE + CELL_SIZE / 2)
        red_infantry2 = Unit(UnitType.INFANTRY, Team.RED, 37 * CELL_SIZE + CELL_SIZE / 2, 10 * CELL_SIZE + CELL_SIZE / 2)
        red_cavalry = Unit(UnitType.CAVALRY, Team.RED, 35 * CELL_SIZE + CELL_SIZE / 2, 12 * CELL_SIZE + CELL_SIZE / 2)
        red_archer = Unit(UnitType.ARCHER, Team.RED, 38 * CELL_SIZE + CELL_SIZE / 2, 14 * CELL_SIZE + CELL_SIZE / 2)

        self.blue_units = [blue_infantry, blue_infantry2, blue_cavalry, blue_archer]
        self.red_units = [red_infantry, red_infantry2, red_cavalry, red_archer]
        self.all_units = self.blue_units + self.red_units

    def run(self):
        while self.running:
            dt = self.clock.tick(FPS) / 1000.0
            self._handle_events()
            if not self._game_over:
                self._update(dt)
            self._render()
        pygame.quit()
        sys.exit()

    def _handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    if self.selected_unit:
                        self.selected_unit.selected = False
                        self.selected_unit = None
                    else:
                        self.running = False
                elif event.key == pygame.K_SPACE:
                    self._toggle_orders()
                elif event.key == pygame.K_r:
                    self._restart()

            elif event.type == pygame.MOUSEBUTTONDOWN:
                mx, my = event.pos
                if my >= SCREEN_HEIGHT - HUD_HEIGHT:
                    continue

                if event.button == 1:
                    self._handle_left_click(mx, my)
                elif event.button == 3:
                    self._handle_right_click(mx, my)

    def _handle_left_click(self, mx: int, my: int):
        if self.selected_unit:
            self.selected_unit.selected = False
            self.selected_unit = None

        for unit in self.blue_units:
            if not unit.alive:
                continue
            if unit.distance_to_point(mx, my) < CELL_SIZE:
                self.selected_unit = unit
                unit.selected = True
                return

    def _handle_right_click(self, mx: int, my: int):
        if not self.selected_unit or not self.selected_unit.alive:
            return

        target_unit = None
        for unit in self.red_units:
            if unit.alive and unit.distance_to_point(mx, my) < CELL_SIZE:
                target_unit = unit
                break

        if target_unit:
            self.selected_unit.set_attack_target(target_unit)
        else:
            pixel_path = self.pathfinder.find_path_pixels(
                self.selected_unit.x, self.selected_unit.y, mx, my
            )
            if pixel_path:
                self.selected_unit.clear_orders()
                self.selected_unit.set_move_path(pixel_path)

    def _toggle_orders(self):
        self._show_orders = not self._show_orders

    def _restart(self):
        self._game_over = False
        self._winner = None
        self.selected_unit = None
        self.all_units.clear()
        self.blue_units.clear()
        self.red_units.clear()
        self._setup_map()
        self.pathfinder = Pathfinder(self.game_map)
        self.ai_controller = AIController(self.pathfinder)
        self._setup_units()

    def _update(self, dt: float):
        for unit in self.all_units:
            unit.update(dt, self.game_map, self.all_units)

        self.ai_controller.update(dt, [u for u in self.blue_units if u.alive])
        self.ai_controller.remove_dead()

        self._check_game_over()

    def _check_game_over(self):
        blue_alive = any(u.alive for u in self.blue_units)
        red_alive = any(u.alive for u in self.red_units)

        if not blue_alive and not red_alive:
            self._game_over = True
            self._winner = "DRAW"
        elif not red_alive:
            self._game_over = True
            self._winner = "BLUE WINS"
        elif not blue_alive:
            self._game_over = True
            self._winner = "RED WINS"

        if self.selected_unit and not self.selected_unit.alive:
            self.selected_unit.selected = False
            self.selected_unit = None

    def _render(self):
        self.game_map.render(self.screen)

        if self.selected_unit and self._show_orders:
            self._render_move_indicators()

        for unit in self.all_units:
            unit.render(self.screen)

        self._render_hud()

        if self._game_over:
            self._render_game_over()

        pygame.display.flip()

    def _render_move_indicators(self):
        unit = self.selected_unit
        if not unit:
            return

        indicator_surface = pygame.Surface(
            (SCREEN_WIDTH, SCREEN_HEIGHT - HUD_HEIGHT), pygame.SRCALPHA
        )

        range_r = int(unit.attack_range)
        if range_r > 0:
            pygame.draw.circle(
                indicator_surface, COLOR_ATTACK_RANGE,
                (int(unit.x), int(unit.y)), range_r, 2
            )

        move_range = int(unit.speed * CELL_SIZE * 10)
        pygame.draw.circle(
            indicator_surface, COLOR_MOVE_RANGE,
            (int(unit.x), int(unit.y)), move_range, 1
        )

        self.screen.blit(indicator_surface, (0, 0))

    def _render_hud(self):
        hud_y = SCREEN_HEIGHT - HUD_HEIGHT
        pygame.draw.rect(self.screen, COLOR_HUD_BG, (0, hud_y, SCREEN_WIDTH, HUD_HEIGHT))

        if self._mission_config:
            mission_text = self.font_hud.render(
                f"MISSION: {self._mission_config.name}", True, COLOR_HUD_TEXT
            )
            self.screen.blit(mission_text, (12, hud_y + 2))

        total_blue = sum(u.health for u in self.blue_units if u.alive)
        total_red = sum(u.health for u in self.red_units if u.alive)
        blue_alive = sum(1 for u in self.blue_units if u.alive)
        red_alive = sum(1 for u in self.red_units if u.alive)

        blue_text = self.font_hud.render(
            f"BLUE: {blue_alive} units | {total_blue} soldiers", True, COLOR_BLUE
        )
        red_text = self.font_hud.render(
            f"RED: {red_alive} units | {total_red} soldiers", True, COLOR_RED
        )
        y_off = 20 if self._mission_config else 6
        self.screen.blit(blue_text, (12, hud_y + y_off))
        self.screen.blit(red_text, (SCREEN_WIDTH - red_text.get_width() - 12, hud_y + y_off))

        if self.selected_unit:
            u = self.selected_unit
            info = (
                f"SELECTED: {u.unit_type.value.upper()} | "
                f"HP: {u.health}/{u.max_health} | "
                f"DMG: {u.damage} | SPD: {u.speed}"
            )
            info_text = self.font_hud.render(info, True, COLOR_HUD_TEXT)
            self.screen.blit(info_text, (SCREEN_WIDTH // 2 - info_text.get_width() // 2, hud_y + 6))

        controls = self.font_hud.render(
            "LMB: Select | RMB: Move/Attack | ESC: Deselect/Quit | SPACE: Toggle UI | R: Restart",
            True, COLOR_HUD_TEXT_DIM,
        )
        self.screen.blit(controls, (SCREEN_WIDTH // 2 - controls.get_width() // 2, hud_y + 28))

    def _render_game_over(self):
        overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 120))
        self.screen.blit(overlay, (0, 0))

        if self._winner == "BLUE WINS":
            color = COLOR_BLUE
        elif self._winner == "RED WINS":
            color = COLOR_RED
        else:
            color = COLOR_WHITE

        title = self.font_title.render(self._winner, True, color)
        tx = SCREEN_WIDTH // 2 - title.get_width() // 2
        ty = SCREEN_HEIGHT // 2 - title.get_height() // 2 - 20
        self.screen.blit(title, (tx, ty))

        restart_text = self.font_hud.render("Press R to restart | ESC to quit", True, COLOR_WHITE)
        rx = SCREEN_WIDTH // 2 - restart_text.get_width() // 2
        ry = ty + title.get_height() + 16
        self.screen.blit(restart_text, (rx, ry))
