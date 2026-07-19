import math
from typing import List, Optional
from config import AIState, Team, CELL_SIZE
from units import Unit
from pathfinding import Pathfinder


class UnitAI:
    def __init__(self, unit: Unit, pathfinder: Pathfinder):
        self.unit = unit
        self.pathfinder = pathfinder
        self.state = AIState.IDLE
        self._think_timer = 0.0
        self._think_interval = 0.5
        self._last_known_enemy_pos: Optional[tuple] = None
        self._retreat_threshold = 0.2

    def update(self, dt: float, enemies: List[Unit], allies: List[Unit]):
        if not self.unit.alive:
            return

        self._think_timer -= dt
        if self._think_timer > 0:
            return
        self._think_timer = self._think_interval

        if self.state == AIState.IDLE:
            self._do_idle(enemies)
        elif self.state == AIState.MOVE:
            self._do_move(enemies)
        elif self.state == AIState.ATTACK:
            self._do_attack(enemies)

    def _do_idle(self, enemies: List[Unit]):
        nearest = self._find_nearest_enemy(enemies)
        if nearest is None:
            self.state = AIState.IDLE
            return

        dist = self.unit.distance_to(nearest)

        if self.unit.health_ratio < self._retreat_threshold:
            self._flee(nearest, enemies)
            return

        if dist <= self.unit.attack_range:
            self.unit.set_attack_target(nearest)
            self.state = AIState.ATTACK
        elif dist <= CELL_SIZE * 8:
            self._last_known_enemy_pos = nearest.center
            self.state = AIState.MOVE
        else:
            self.state = AIState.IDLE

    def _do_move(self, enemies: List[Unit]):
        nearest = self._find_nearest_enemy(enemies)
        if nearest and self.unit.distance_to(nearest) <= self.unit.attack_range:
            self.unit.set_attack_target(nearest)
            self.state = AIState.ATTACK
            return

        if self.unit.health_ratio < self._retreat_threshold and nearest:
            self._flee(nearest, enemies)
            return

        if not self.unit._path or self.unit._path_index >= len(self.unit._path):
            self.state = AIState.IDLE

    def _do_attack(self, enemies: List[Unit]):
        target = self.unit._attack_target
        if not target or not target.alive:
            self.unit._attack_target = None
            self.state = AIState.IDLE
            return

        if self.unit.health_ratio < self._retreat_threshold:
            self._flee(target, enemies)
            return

        dist = self.unit.distance_to(target)
        if dist > self.unit.attack_range * 1.5:
            self.unit._attack_target = None
            self.state = AIState.IDLE

    def _find_nearest_enemy(self, enemies: List[Unit]) -> Optional[Unit]:
        nearest = None
        min_dist = float("inf")
        for e in enemies:
            if not e.alive:
                continue
            d = self.unit.distance_to(e)
            if d < min_dist:
                min_dist = d
                nearest = e
        return nearest

    def _flee(self, threat: Unit, all_enemies: List[Unit]):
        dx = self.unit.x - threat.x
        dy = self.unit.y - threat.y
        dist = math.hypot(dx, dy)
        if dist < 1:
            dx, dy = 1, 0
            dist = 1

        flee_dist = CELL_SIZE * 6
        fx = self.unit.x + (dx / dist) * flee_dist
        fy = self.unit.y + (dy / dist) * flee_dist

        fx = max(CELL_SIZE, min(fx, (self.pathfinder.game_map.cols - 1) * CELL_SIZE))
        fy = max(CELL_SIZE, min(fy, (self.pathfinder.game_map.rows - 1) * CELL_SIZE))

        pixel_path = self.pathfinder.find_path_pixels(
            self.unit.x, self.unit.y, fx, fy
        )
        if pixel_path:
            self.unit.set_move_path(pixel_path)
            self.state = AIState.MOVE
        else:
            self.state = AIState.IDLE

    def _update_chase(self, target: Unit):
        pixel_path = self.pathfinder.find_path_pixels(
            self.unit.x, self.unit.y, target.x, target.y
        )
        if pixel_path:
            self.unit.set_move_path(pixel_path)


class AIController:
    def __init__(self, pathfinder: Pathfinder):
        self.pathfinder = pathfinder
        self._unit_ais: List[UnitAI] = []

    def register_unit(self, unit: Unit):
        ai = UnitAI(unit, self.pathfinder)
        self._unit_ais.append(ai)

    def remove_dead(self):
        self._unit_ais = [a for a in self._unit_ais if a.unit.alive]

    def update(self, dt: float, enemies: List[Unit]):
        for ai in self._unit_ais:
            allies = [a.unit for a in self._unit_ais if a.unit is not ai.unit and a.unit.alive]
            ai.update(dt, enemies, allies)
