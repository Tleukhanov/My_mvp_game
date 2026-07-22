import pygame
import sys
import math
from typing import Optional, List, Tuple, Set
from config import (
    SCREEN_WIDTH, SCREEN_HEIGHT, HUD_HEIGHT, CELL_SIZE,
    MAP_COLS, MAP_ROWS, FPS, Team, UnitType, CommandMode,
    COLOR_HUD_BG, COLOR_HUD_TEXT, COLOR_HUD_TEXT_DIM,
    COLOR_WHITE, COLOR_BLACK, COLOR_BLUE, COLOR_RED,
    FONT_NAME, FONT_SIZE_HUD, FONT_SIZE_TITLE,
    COLOR_MOVE_RANGE, COLOR_ATTACK_RANGE,
    COLOR_SELECT_RECT, COLOR_SELECT_RECT_BORDER,
    MAX_SELECTION, SELECT_CLICK_RADIUS,
    FOOD_MAX, FOOD_PER_UNIT_PER_SEC, FOOD_PER_VILLAGE_PER_SEC,
    RECRUIT_INTERVAL, TerrainType,
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

FORMATION_SPACING = CELL_SIZE * 1.2


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
        self.selected_units: List[Unit] = []

        self._setup_units()

        self.font_hud = pygame.font.SysFont(FONT_NAME, FONT_SIZE_HUD)
        self.font_title = pygame.font.SysFont(FONT_NAME, FONT_SIZE_TITLE, bold=True)

        self._show_orders = True
        self._game_over = False
        self._winner: Optional[str] = None

        self._drag_start: Optional[Tuple[int, int]] = None
        self._drag_end: Optional[Tuple[int, int]] = None
        self._dragging = False

        self._blue_food = FOOD_MAX
        self._red_food = FOOD_MAX
        self._recruit_timer = 0.0

        self._command_mode = CommandMode.ATTACK
        self._victory_next_mission: Optional[int] = None

    def _setup_map(self):
        if self.mission:
            from campaigns import MISSIONS
            mission_fn = MISSIONS.get(self.mission)
            if mission_fn:
                config = mission_fn()
                self.game_map = TacticalMap(config.grid, config.villages)
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
        return self._victory_next_mission

    def _handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    if self.selected_units:
                        for u in self.selected_units:
                            u.selected = False
                        self.selected_units.clear()
                    else:
                        self.running = False
                elif event.key == pygame.K_SPACE:
                    self._toggle_orders()
                elif event.key == pygame.K_r:
                    self._restart()
                elif event.key == pygame.K_a:
                    self._select_all_blue()
                elif event.key == pygame.K_h:
                    self._command_mode = CommandMode.HOLD
                elif event.key == pygame.K_f:
                    self._command_mode = CommandMode.DEFEND
                elif event.key == pygame.K_g:
                    self._command_mode = CommandMode.ATTACK

            elif event.type == pygame.MOUSEBUTTONDOWN:
                mx, my = event.pos
                if my >= SCREEN_HEIGHT - HUD_HEIGHT:
                    continue

                if event.button == 1:
                    keys = pygame.key.get_pressed()
                    if keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT]:
                        self._shift_click_select(mx, my)
                    else:
                        self._drag_start = (mx, my)
                        self._dragging = False
                elif event.button == 3:
                    self._handle_right_click(mx, my)

            elif event.type == pygame.MOUSEBUTTONUP:
                mx, my = event.pos
                if event.button == 1:
                    if self._drag_start is not None:
                        dx = mx - self._drag_start[0]
                        dy = my - self._drag_start[1]
                        if abs(dx) > 5 or abs(dy) > 5:
                            self._box_select(self._drag_start[0], self._drag_start[1], mx, my)
                        else:
                            self._single_click_select(mx, my)
                        self._drag_start = None
                        self._dragging = False

            elif event.type == pygame.MOUSEMOTION:
                if self._drag_start is not None:
                    mx, my = event.pos
                    dx = mx - self._drag_start[0]
                    dy = my - self._drag_start[1]
                    if abs(dx) > 5 or abs(dy) > 5:
                        self._dragging = True
                        self._drag_end = (mx, my)

    def _single_click_select(self, mx: int, my: int):
        for u in self.selected_units:
            u.selected = False
        self.selected_units.clear()

        for unit in self.blue_units:
            if not unit.alive:
                continue
            if unit.distance_to_point(mx, my) < SELECT_CLICK_RADIUS:
                unit.selected = True
                self.selected_units.append(unit)
                return

    def _shift_click_select(self, mx: int, my: int):
        for unit in self.blue_units:
            if not unit.alive:
                continue
            if unit.distance_to_point(mx, my) < SELECT_CLICK_RADIUS:
                if unit in self.selected_units:
                    unit.selected = False
                    self.selected_units.remove(unit)
                elif len(self.selected_units) < MAX_SELECTION:
                    unit.selected = True
                    self.selected_units.append(unit)
                return

    def _box_select(self, x1: int, y1: int, x2: int, y2: int):
        for u in self.selected_units:
            u.selected = False
        self.selected_units.clear()

        left = min(x1, x2)
        right = max(x1, x2)
        top = min(y1, y2)
        bottom = max(y1, y2)

        for unit in self.blue_units:
            if not unit.alive:
                continue
            if left <= unit.x <= right and top <= unit.y <= bottom:
                if len(self.selected_units) < MAX_SELECTION:
                    unit.selected = True
                    self.selected_units.append(unit)

    def _select_all_blue(self):
        for u in self.selected_units:
            u.selected = False
        self.selected_units.clear()
        for unit in self.blue_units:
            if unit.alive and len(self.selected_units) < MAX_SELECTION:
                unit.selected = True
                self.selected_units.append(unit)

    def _handle_right_click(self, mx: int, my: int):
        if not self.selected_units:
            return

        target_unit = None
        for unit in self.red_units:
            if unit.alive and unit.distance_to_point(mx, my) < CELL_SIZE:
                target_unit = unit
                break

        if target_unit:
            self._issue_attack_order(target_unit)
        elif self.selected_units:
            self._issue_formation_move(mx, my)

    def _issue_attack_order(self, target: Unit):
        if self._command_mode == CommandMode.HOLD:
            for su in self.selected_units:
                if su.alive:
                    su.clear_orders()
                    su.set_attack_target(target)
            return

        if self._command_mode == CommandMode.DEFEND:
            for su in self.selected_units:
                if su.alive:
                    su.clear_orders()
                    su.set_attack_target(target)
            return

        for su in self.selected_units:
            if su.alive:
                su.clear_orders()
                su.set_attack_target(target)

    def _issue_formation_move(self, mx: int, my: int):
        n = len(self.selected_units)
        if n == 0:
            return

        if n == 1:
            su = self.selected_units[0]
            if su.alive:
                pixel_path = self.pathfinder.find_path_pixels(su.x, su.y, mx, my)
                if pixel_path:
                    su.clear_orders()
                    if self._command_mode == CommandMode.HOLD:
                        su.set_move_path(pixel_path)
                    elif self._command_mode == CommandMode.DEFEND:
                        su.set_move_path(pixel_path)
                    else:
                        su.set_move_path(pixel_path)
            return

        angle = 0
        cols = min(n, 3)
        for i, su in enumerate(self.selected_units):
            if not su.alive:
                continue
            row_idx = i // cols
            col_idx = i % cols
            offset_x = (col_idx - (cols - 1) / 2) * FORMATION_SPACING
            offset_y = row_idx * FORMATION_SPACING
            tx = mx + offset_x
            ty = my + offset_y

            pixel_path = self.pathfinder.find_path_pixels(su.x, su.y, tx, ty)
            if pixel_path:
                su.clear_orders()
                if self._command_mode == CommandMode.HOLD:
                    su.set_move_path(pixel_path)
                elif self._command_mode == CommandMode.DEFEND:
                    su.set_move_path(pixel_path)
                else:
                    su.set_move_path(pixel_path)

    def _toggle_orders(self):
        self._show_orders = not self._show_orders

    def _restart(self):
        self._game_over = False
        self._winner = None
        self.selected_units.clear()
        self.all_units.clear()
        self.blue_units.clear()
        self.red_units.clear()
        self._blue_food = FOOD_MAX
        self._red_food = FOOD_MAX
        self._recruit_timer = 0.0
        self._command_mode = CommandMode.ATTACK
        self._setup_map()
        self.pathfinder = Pathfinder(self.game_map)
        self.ai_controller = AIController(self.pathfinder)
        self._setup_units()

    def _update(self, dt: float):
        for unit in self.all_units:
            unit.update(dt, self.game_map, self.all_units)

        villages = self.game_map.get_all_villages()
        v_owners = self.game_map.village_owners

        self.ai_controller.update(
            dt,
            [u for u in self.blue_units if u.alive],
            villages, v_owners
        )
        self.ai_controller.remove_dead()

        self._update_villages(dt)
        self._update_food(dt)
        self._update_recruit(dt)
        self._check_game_over()

    def _update_villages(self, dt: float):
        for col, row in self.game_map.get_all_villages():
            owner = self.game_map.get_village_owner(col, row)
            tx = col * CELL_SIZE + CELL_SIZE / 2
            ty = row * CELL_SIZE + CELL_SIZE / 2
            controlling_unit = None
            for unit in self.all_units:
                if not unit.alive:
                    continue
                dist = math.hypot(unit.x - tx, unit.y - ty)
                if dist < CELL_SIZE * 1.2:
                    controlling_unit = unit
                    break
            if controlling_unit:
                new_owner = controlling_unit.team.value
                if owner != new_owner:
                    self.game_map.set_village_owner(col, row, new_owner)

    def _update_food(self, dt: float):
        blue_count = sum(1 for u in self.blue_units if u.alive)
        red_count = sum(1 for u in self.red_units if u.alive)
        self._blue_food -= blue_count * FOOD_PER_UNIT_PER_SEC * dt
        self._red_food -= red_count * FOOD_PER_UNIT_PER_SEC * dt

        for col, row in self.game_map.get_all_villages():
            owner = self.game_map.get_village_owner(col, row)
            if owner == "blue":
                self._blue_food += FOOD_PER_VILLAGE_PER_SEC * dt
            elif owner == "red":
                self._red_food += FOOD_PER_VILLAGE_PER_SEC * dt

        self._blue_food = max(0, min(FOOD_MAX, self._blue_food))
        self._red_food = max(0, min(FOOD_MAX, self._red_food))

    def _update_recruit(self, dt: float):
        self._recruit_timer += dt
        if self._recruit_timer >= RECRUIT_INTERVAL:
            self._recruit_timer -= RECRUIT_INTERVAL
            self._recruit_unit("blue")
            self._recruit_unit("red")

    def _recruit_unit(self, team_str: str):
        food = self._blue_food if team_str == "blue" else self._red_food
        if food <= 0:
            return

        team = Team.BLUE if team_str == "blue" else Team.RED
        units = self.blue_units if team_str == "blue" else self.red_units
        villages = [
            (c, r) for c, r in self.game_map.get_all_villages()
            if self.game_map.get_village_owner(c, r) == team_str
        ]
        if not villages:
            return

        spawn_col, spawn_row = villages[0]
        sx = spawn_col * CELL_SIZE + CELL_SIZE / 2
        sy = spawn_row * CELL_SIZE + CELL_SIZE / 2

        offset_x = (len(units) % 3) * CELL_SIZE
        offset_y = (len(units) // 3) * CELL_SIZE
        sx += offset_x - CELL_SIZE
        sy += offset_y - CELL_SIZE

        new_unit = Unit(UnitType.INFANTRY, team, sx, sy, health=500)
        new_unit._pathfinder = self.pathfinder
        units.append(new_unit)
        self.all_units.append(new_unit)

        if team == Team.RED:
            self.ai_controller.register_unit(new_unit)

    def _check_game_over(self):
        blue_alive = any(u.alive for u in self.blue_units)
        red_alive = any(u.alive for u in self.red_units)

        if not blue_alive and not red_alive:
            self._game_over = True
            self._winner = "DRAW"
        elif not red_alive:
            self._game_over = True
            self._winner = "BLUE WINS"
            if self.mission and self.mission < 4:
                self._victory_next_mission = self.mission + 1
        elif not blue_alive:
            self._game_over = True
            self._winner = "RED WINS"

        for su in list(self.selected_units):
            if not su.alive:
                su.selected = False
                self.selected_units.remove(su)

    def _render(self):
        self.game_map.render(self.screen)

        if self._show_orders and self.selected_units:
            self._render_move_indicators()

        if self._dragging and self._drag_start and self._drag_end:
            self._render_selection_rect()

        for unit in self.all_units:
            unit.render(self.screen)

        self._render_hud()

        if self._game_over:
            self._render_game_over()

        pygame.display.flip()

    def _render_selection_rect(self):
        x1, y1 = self._drag_start
        x2, y2 = self._drag_end
        rect = pygame.Rect(min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1))
        sel_surface = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        sel_surface.fill(COLOR_SELECT_RECT)
        pygame.draw.rect(sel_surface, COLOR_SELECT_RECT_BORDER, sel_surface.get_rect(), 2)
        self.screen.blit(sel_surface, rect.topleft)

    def _render_move_indicators(self):
        indicator_surface = pygame.Surface(
            (SCREEN_WIDTH, SCREEN_HEIGHT - HUD_HEIGHT), pygame.SRCALPHA
        )
        for unit in self.selected_units:
            if not unit.alive:
                continue
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
            f"BLUE: {blue_alive} | HP:{total_blue} | Food:{int(self._blue_food)}", True, COLOR_BLUE
        )
        red_text = self.font_hud.render(
            f"RED: {red_alive} | HP:{total_red} | Food:{int(self._red_food)}", True, COLOR_RED
        )
        y_off = 20 if self._mission_config else 6
        self.screen.blit(blue_text, (12, hud_y + y_off))
        self.screen.blit(red_text, (SCREEN_WIDTH - red_text.get_width() - 12, hud_y + y_off))

        villages_info = []
        for col, row in self.game_map.get_all_villages():
            owner = self.game_map.get_village_owner(col, row)
            if owner:
                villages_info.append(owner)
        blue_v = villages_info.count("blue")
        red_v = villages_info.count("red")
        v_text = self.font_hud.render(
            f"Villages: B:{blue_v} R:{red_v}", True, COLOR_HUD_TEXT_DIM
        )
        self.screen.blit(v_text, (SCREEN_WIDTH // 2 - v_text.get_width() // 2, hud_y + 2))

        if self.selected_units:
            if len(self.selected_units) == 1:
                u = self.selected_units[0]
                info = (
                    f"SEL: {u.unit_type.value.upper()} | "
                    f"HP: {u.health}/{u.max_health} | "
                    f"DMG: {u.damage}"
                )
            else:
                types_count = {}
                for su in self.selected_units:
                    t = su.unit_type.value
                    types_count[t] = types_count.get(t, 0) + 1
                parts = [f"{v}x{k}" for k, v in types_count.items()]
                info = f"SELECTED: {len(self.selected_units)} units ({', '.join(parts)})"
            info_text = self.font_hud.render(info, True, COLOR_HUD_TEXT)
            self.screen.blit(info_text, (SCREEN_WIDTH // 2 - info_text.get_width() // 2, hud_y + 6))

        cmd_name = self._command_mode.value.upper()
        cmd_color = COLOR_ATTACK_RANGE if self._command_mode == CommandMode.ATTACK else (
            COLOR_MOVE_RANGE if self._command_mode == CommandMode.HOLD else (180, 180, 100)
        )
        cmd_text = self.font_hud.render(
            f"[{cmd_name}] G:Attack H:Hold F:Defend", True, cmd_color
        )
        self.screen.blit(cmd_text, (SCREEN_WIDTH - cmd_text.get_width() - 12, hud_y + 2))

        controls = self.font_hud.render(
            "LMB: Select | Shift+LMB: Multi | Drag: Box | RMB: Move/Attack | A: All | ESC: Quit",
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
        ty = SCREEN_HEIGHT // 2 - title.get_height() // 2 - 40
        self.screen.blit(title, (tx, ty))

        if self._winner == "BLUE WINS" and self.mission and self.mission < 4:
            next_text = self.font_hud.render(
                f"Press N for next mission (Mission {self.mission + 1}) | R: Restart | ESC: Menu",
                True, COLOR_WHITE
            )
        elif self._winner == "BLUE WINS" and self.mission == 4:
            next_text = self.font_hud.render(
                "CAMPAIGN COMPLETE! Press R: Restart | ESC: Menu",
                True, COLOR_WHITE
            )
        else:
            next_text = self.font_hud.render(
                "Press R to restart | ESC to quit",
                True, COLOR_WHITE
            )
        rx = SCREEN_WIDTH // 2 - next_text.get_width() // 2
        ry = ty + title.get_height() + 16
        self.screen.blit(next_text, (rx, ry))

        self._handle_game_over_keys()

    def _handle_game_over_keys(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_r:
                    self._restart()
                elif event.key == pygame.K_ESCAPE:
                    self.running = False
                elif event.key == pygame.K_n:
                    if self._winner == "BLUE WINS" and self._victory_next_mission:
                        self.running = False
