import pygame
import math
from typing import Optional, Tuple, List
from config import (
    UnitType, Team, CELL_SIZE, UNIT_STATS, COMBAT_ADVANTAGE,
    COLOR_BLUE, COLOR_BLUE_LIGHT, COLOR_BLUE_SELECTED,
    COLOR_RED, COLOR_RED_LIGHT, COLOR_RED_SELECTED,
    COLOR_WHITE, COLOR_BLACK,
    COLOR_HEALTH_BAR_BG, COLOR_HEALTH_BAR_GREEN,
    COLOR_HEALTH_BAR_YELLOW, COLOR_HEALTH_BAR_RED,
    SELECTED_BORDER_WIDTH, UNIT_OUTLINE_WIDTH, FONT_SIZE_UNIT,
)


class Unit:
    def __init__(
        self,
        unit_type: UnitType,
        team: Team,
        x: float,
        y: float,
        health: Optional[int] = None,
    ):
        stats = UNIT_STATS[unit_type]
        self.unit_type = unit_type
        self.team = team
        self.x = x
        self.y = y
        self.max_health = stats["max_health"]
        self.health = health if health is not None else self.max_health
        self.speed = stats["speed"]
        self.damage = stats["damage"]
        self.attack_range = stats["attack_range"]
        self.attack_cooldown = stats["attack_speed"]
        self._attack_timer = 0.0

        self.selected = False
        self.alive = True

        self._path: List[Tuple[float, float]] = []
        self._path_index = 0
        self._move_target: Optional[Tuple[float, float]] = None

        self._attack_target: Optional["Unit"] = None

        self._font = pygame.font.SysFont("consolas", FONT_SIZE_UNIT)
        self._last_attack_time = 0.0
        self._pathfinder = None
        self._chase_timer = 0.0

    @property
    def grid_col(self) -> int:
        return int(self.x) // CELL_SIZE

    @property
    def grid_row(self) -> int:
        return int(self.y) // CELL_SIZE

    @property
    def center(self) -> Tuple[float, float]:
        return self.x, self.y

    @property
    def health_ratio(self) -> float:
        return self.health / self.max_health if self.max_health > 0 else 0

    def distance_to(self, other: "Unit") -> float:
        return math.hypot(self.x - other.x, self.y - other.y)

    def distance_to_point(self, px: float, py: float) -> float:
        return math.hypot(self.x - px, self.y - py)

    def set_move_path(self, pixel_path: List[Tuple[float, float]]):
        if pixel_path and len(pixel_path) >= 2:
            self._path = pixel_path
            self._path_index = 0
            self._move_target = pixel_path[-1]

    def clear_orders(self):
        self._path = []
        self._path_index = 0
        self._move_target = None
        self._attack_target = None

    def set_attack_target(self, target: "Unit"):
        self._attack_target = target

    def update(self, dt: float, game_map, all_units: List["Unit"]):
        if not self.alive:
            return

        self._attack_timer = max(0.0, self._attack_timer - dt)
        self._chase_timer = max(0.0, self._chase_timer - dt)

        if self._attack_target and self._attack_target.alive:
            dist = self.distance_to(self._attack_target)
            if dist <= self.attack_range:
                self._path = []
                self._path_index = 0
                if self._attack_timer <= 0:
                    self._perform_attack(self._attack_target)
                    self._attack_timer = self.attack_cooldown
                return
            else:
                if self._chase_timer <= 0:
                    self._chase_target()
                    self._chase_timer = 1.0

        self._move_along_path(dt, game_map)
        self._resolve_collisions(all_units)

    def _move_along_path(self, dt: float, game_map):
        if not self._path or self._path_index >= len(self._path):
            self._path = []
            self._path_index = 0
            return

        target = self._path[self._path_index]
        dx = target[0] - self.x
        dy = target[1] - self.y
        dist = math.hypot(dx, dy)

        if dist < 2.0:
            self._path_index += 1
            if self._path_index >= len(self._path):
                self._path = []
                self._path_index = 0
            return

        step = self.speed * dt * 60
        if step >= dist:
            self.x = target[0]
            self.y = target[1]
            self._path_index += 1
        else:
            self.x += (dx / dist) * step
            self.y += (dy / dist) * step

    def _chase_target(self):
        if not self._attack_target or not self._attack_target.alive:
            self._attack_target = None
            return
        if self._pathfinder:
            pixel_path = self._pathfinder.find_path_pixels(
                self.x, self.y, self._attack_target.x, self._attack_target.y
            )
            if pixel_path:
                self._path = pixel_path
                self._path_index = 0
        else:
            self._path = [
                self._attack_target.center,
            ]
            self._path_index = 0

    MIN_SEPARATION = CELL_SIZE * 0.6

    def _resolve_collisions(self, all_units: List["Unit"]):
        for other in all_units:
            if other is self or not other.alive:
                continue
            if other is self._attack_target:
                continue
            dx = self.x - other.x
            dy = self.y - other.y
            dist = math.hypot(dx, dy)
            if dist < self.MIN_SEPARATION and dist > 0.1:
                overlap = self.MIN_SEPARATION - dist
                push_x = (dx / dist) * overlap * 0.8
                push_y = (dy / dist) * overlap * 0.8
                self.x += push_x
                self.y += push_y

    def _perform_attack(self, target: "Unit"):
        if not target.alive:
            return
        advantage = COMBAT_ADVANTAGE.get(
            (self.unit_type, target.unit_type), 1.0
        )
        base_damage = self.damage * advantage
        health_damage = max(1, int(base_damage * (self.health / self.max_health)))
        target.take_damage(health_damage)

    def take_damage(self, amount: int):
        self.health -= amount
        if self.health <= 0:
            self.health = 0
            self.alive = False

    def render(self, surface: pygame.Surface):
        if not self.alive:
            return

        if self.team == Team.BLUE:
            base_color = COLOR_BLUE
            light_color = COLOR_BLUE_LIGHT
            select_color = COLOR_BLUE_SELECTED
        else:
            base_color = COLOR_RED
            light_color = COLOR_RED_LIGHT
            select_color = COLOR_RED_SELECTED

        if self.selected:
            size = CELL_SIZE // 2 + SELECTED_BORDER_WIDTH
            pygame.draw.circle(
                surface, select_color,
                (int(self.x), int(self.y)), size, SELECTED_BORDER_WIDTH
            )

        if self.unit_type == UnitType.INFANTRY:
            self._render_circle(surface, base_color, light_color)
        elif self.unit_type == UnitType.CAVALRY:
            self._render_square(surface, base_color, light_color)
        elif self.unit_type == UnitType.ARCHER:
            self._render_triangle(surface, base_color, light_color)

        self._render_health_bar(surface)
        self._render_label(surface)

    def _render_circle(self, surface, base, light):
        r = CELL_SIZE // 2 - 2
        pygame.draw.circle(surface, base, (int(self.x), int(self.y)), r)
        pygame.draw.circle(surface, light, (int(self.x), int(self.y)), r, UNIT_OUTLINE_WIDTH)

    def _render_square(self, surface, base, light):
        half = CELL_SIZE // 2 - 2
        rect = pygame.Rect(
            int(self.x) - half, int(self.y) - half, half * 2, half * 2
        )
        pygame.draw.rect(surface, base, rect)
        pygame.draw.rect(surface, light, rect, UNIT_OUTLINE_WIDTH)

    def _render_triangle(self, surface, base, light):
        half = CELL_SIZE // 2 - 2
        cx, cy = int(self.x), int(self.y)
        points = [
            (cx, cy - half),
            (cx - half, cy + half),
            (cx + half, cy + half),
        ]
        pygame.draw.polygon(surface, base, points)
        pygame.draw.polygon(surface, light, points, UNIT_OUTLINE_WIDTH)

    def _render_health_bar(self, surface):
        bar_w = CELL_SIZE - 4
        bar_h = 4
        bx = int(self.x) - bar_w // 2
        by = int(self.y) - CELL_SIZE // 2 - 6
        pygame.draw.rect(surface, COLOR_HEALTH_BAR_BG, (bx, by, bar_w, bar_h))

        ratio = self.health_ratio
        fill_w = int(bar_w * ratio)
        if ratio > 0.5:
            color = COLOR_HEALTH_BAR_GREEN
        elif ratio > 0.25:
            color = COLOR_HEALTH_BAR_YELLOW
        else:
            color = COLOR_HEALTH_BAR_RED
        if fill_w > 0:
            pygame.draw.rect(surface, color, (bx, by, fill_w, bar_h))

    def _render_label(self, surface):
        label = self._font.render(str(self.health), True, COLOR_WHITE)
        lx = int(self.x) - label.get_width() // 2
        ly = int(self.y) - label.get_height() // 2
        bg_rect = pygame.Rect(lx - 1, ly - 1, label.get_width() + 2, label.get_height() + 2)
        bg_surface = pygame.Surface((bg_rect.width, bg_rect.height), pygame.SRCALPHA)
        bg_surface.fill((0, 0, 0, 140))
        surface.blit(bg_surface, bg_rect.topleft)
        surface.blit(label, (lx, ly))
