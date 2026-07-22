import math
import random
from typing import List, Optional, Tuple
from config import AIState, Team, CELL_SIZE, TerrainType, UnitType
from units import Unit
from pathfinding import Pathfinder

GROUP_UP_RANGE = CELL_SIZE * 8
HOLD_DISTANCE = CELL_SIZE * 4
FLANK_ANGLE = 1.2
COORDINATE_MIN_ALLIES = 2
RETREAT_HEALTH = 0.35
ADVANCE_SAFE_DIST = CELL_SIZE * 12


class UnitAI:
    def __init__(self, unit: Unit, pathfinder: Pathfinder):
        self.unit = unit
        self.pathfinder = pathfinder
        self.state = AIState.IDLE
        self._think_timer = 0.0
        self._think_interval = 0.8
        self._retreat_threshold = RETREAT_HEALTH
        self._target_village: Optional[Tuple[int, int]] = None
        self._hold_pos: Optional[Tuple[float, float]] = None
        self._flank_side = random.choice([-1, 1])
        self._group_up_target: Optional[Tuple[float, float]] = None
        self._patrol_points: List[Tuple[float, float]] = []
        self._patrol_index = 0

    def update(self, dt: float, enemies: List[Unit], allies: List[Unit],
               villages: Optional[List[Tuple[int, int]]] = None,
               village_owners: Optional[dict] = None):
        if not self.unit.alive:
            return

        self._think_timer -= dt
        if self._think_timer > 0:
            return
        self._think_timer = self._think_interval

        alive_enemies = [e for e in enemies if e.alive]
        alive_allies = [a for a in allies if a.alive and a is not self.unit]

        if self.state == AIState.RETREAT:
            self._do_retreat(alive_enemies)
            return

        if self.unit.health_ratio < self._retreat_threshold:
            self.state = AIState.RETREAT
            self._do_retreat(alive_enemies)
            return

        nearest_enemy = self._find_nearest_enemy(alive_enemies)

        if self.state == AIState.IDLE:
            self._do_idle_tactical(nearest_enemy, alive_allies, alive_enemies,
                                   villages, village_owners)
        elif self.state == AIState.GROUP_UP:
            self._do_group_up(nearest_enemy, alive_allies, alive_enemies)
        elif self.state == AIState.MOVE:
            self._do_move(nearest_enemy, alive_allies, alive_enemies)
        elif self.state == AIState.HOLD:
            self._do_hold(nearest_enemy, alive_allies, alive_enemies)
        elif self.state == AIState.ATTACK:
            self._do_attack(nearest_enemy, alive_allies)
        elif self.state == AIState.FLANK:
            self._do_flank(nearest_enemy, alive_allies, alive_enemies)
        elif self.state == AIState.CAPTURE:
            self._do_capture(villages, village_owners)

    def _do_idle_tactical(self, nearest_enemy, allies, enemies,
                          villages, village_owners):
        if not nearest_enemy:
            if villages and village_owners is not None:
                self._try_capture_village(villages, village_owners)
            return

        dist = self.unit.distance_to(nearest_enemy)
        nearby_allies = self._count_nearby_allies(allies, self.unit, GROUP_UP_RANGE)

        if self.unit.unit_type == UnitType.ARCHER:
            if dist <= self.unit.attack_range:
                self.unit.set_attack_target(nearest_enemy)
                self.state = AIState.HOLD
                self._hold_pos = (self.unit.x, self.unit.y)
                return
            elif dist < ADVANCE_SAFE_DIST:
                self.state = AIState.HOLD
                self._hold_pos = (self.unit.x, self.unit.y)
                return
            else:
                self._move_towards(nearest_enemy.x, nearest_enemy.y)
                self.state = AIState.MOVE
                return

        if self.unit.unit_type == UnitType.CAVALRY:
            if dist <= self.unit.attack_range:
                self.unit.set_attack_target(nearest_enemy)
                self.state = AIState.ATTACK
                return
            if nearby_allies >= 1:
                self.state = AIState.FLANK
                self._flank_target(nearest_enemy)
                return
            else:
                self.state = AIState.GROUP_UP
                center = self._find_allies_center(allies)
                if center:
                    self._group_up_target = center
                    self._move_towards(center[0], center[1])
                return

        if self.unit.unit_type == UnitType.INFANTRY:
            if dist <= self.unit.attack_range:
                self.unit.set_attack_target(nearest_enemy)
                self.state = AIState.ATTACK
                return
            if nearby_allies >= COORDINATE_MIN_ALLIES:
                self.state = AIState.ATTACK
                self.unit.set_attack_target(nearest_enemy)
                return
            if nearby_allies >= 1:
                self.state = AIState.GROUP_UP
                center = self._find_allies_center(allies)
                if center:
                    self._group_up_target = center
                    self._move_towards(center[0], center[1])
                return
            else:
                self.state = AIState.GROUP_UP
                center = self._find_allies_center(allies)
                if center:
                    self._group_up_target = center
                    self._move_towards(center[0], center[1])
                return

        if villages and village_owners is not None:
            self._try_capture_village(villages, village_owners)

    def _do_group_up(self, nearest_enemy, allies, enemies):
        if nearest_enemy and self.unit.distance_to(nearest_enemy) <= self.unit.attack_range:
            self.unit.set_attack_target(nearest_enemy)
            self.state = AIState.ATTACK
            return

        nearby = self._count_nearby_allies(allies, self.unit, GROUP_UP_RANGE)

        if self.unit.unit_type == UnitType.INFANTRY and nearby >= COORDINATE_MIN_ALLIES:
            if nearest_enemy:
                self.unit.set_attack_target(nearest_enemy)
                self.state = AIState.ATTACK
                return

        if self.unit.unit_type == UnitType.CAVALRY and nearby >= 1:
            if nearest_enemy:
                self.state = AIState.FLANK
                self._flank_target(nearest_enemy)
                return

        if self.unit.unit_type == UnitType.ARCHER and nearest_enemy:
            if self.unit.distance_to(nearest_enemy) <= self.unit.attack_range:
                self.unit.set_attack_target(nearest_enemy)
                self.state = AIState.HOLD
                self._hold_pos = (self.unit.x, self.unit.y)
                return

        if self._group_up_target:
            tx, ty = self._group_up_target
            dist = math.hypot(self.unit.x - tx, self.unit.y - ty)
            if dist < CELL_SIZE * 2:
                if nearest_enemy and self.unit.distance_to(nearest_enemy) < ADVANCE_SAFE_DIST:
                    if self.unit.unit_type == UnitType.INFANTRY:
                        self.unit.set_attack_target(nearest_enemy)
                        self.state = AIState.ATTACK
                    elif self.unit.unit_type == UnitType.CAVALRY:
                        self.state = AIState.FLANK
                        self._flank_target(nearest_enemy)
                    else:
                        self.unit.set_attack_target(nearest_enemy)
                        self.state = AIState.HOLD
                        self._hold_pos = (self.unit.x, self.unit.y)
                else:
                    self.state = AIState.IDLE
                return

        if not self.unit._path or self.unit._path_index >= len(self.unit._path):
            center = self._find_allies_center(allies)
            if center:
                self._group_up_target = center
                self._move_towards(center[0], center[1])
            else:
                self.state = AIState.IDLE

    def _do_move(self, nearest_enemy, allies, enemies):
        if nearest_enemy and self.unit.distance_to(nearest_enemy) <= self.unit.attack_range:
            self.unit.set_attack_target(nearest_enemy)
            self.state = AIState.ATTACK
            return

        if not self.unit._path or self.unit._path_index >= len(self.unit._path):
            if nearest_enemy and self.unit.unit_type == UnitType.CAVALRY:
                self.state = AIState.FLANK
                self._flank_target(nearest_enemy)
            elif nearest_enemy:
                self.state = AIState.IDLE
            else:
                self.state = AIState.IDLE

    def _do_hold(self, nearest_enemy, allies, enemies):
        if nearest_enemy and self.unit.distance_to(nearest_enemy) <= self.unit.attack_range:
            self.unit.set_attack_target(nearest_enemy)
            self._hold_pos = (self.unit.x, self.unit.y)
            return

        if nearest_enemy and self.unit.distance_to(nearest_enemy) > self.unit.attack_range * 2:
            self.state = AIState.IDLE
            return

        if self._hold_pos:
            hx, hy = self._hold_pos
            dist = math.hypot(self.unit.x - hx, self.unit.y - hy)
            if dist > CELL_SIZE * 1.5:
                self._move_towards(hx, hy)

    def _do_attack(self, nearest_enemy, allies):
        target = self.unit._attack_target
        if not target or not target.alive:
            self.unit._attack_target = None
            self.state = AIState.IDLE
            return

        dist = self.unit.distance_to(target)
        if dist > self.unit.attack_range * 2:
            self.unit._attack_target = None
            self.state = AIState.IDLE

    def _do_flank(self, nearest_enemy, allies, enemies):
        if not nearest_enemy or not nearest_enemy.alive:
            self.state = AIState.IDLE
            return

        dist = self.unit.distance_to(nearest_enemy)

        if dist <= self.unit.attack_range:
            self.unit.set_attack_target(nearest_enemy)
            self.state = AIState.ATTACK
            return

        angle = math.atan2(
            nearest_enemy.y - self.unit.y,
            nearest_enemy.x - self.unit.x
        )
        flank_angle = angle + FLANK_ANGLE * self._flank_side
        flank_dist = self.unit.attack_range * 0.9
        fx = nearest_enemy.x + math.cos(flank_angle) * flank_dist
        fy = nearest_enemy.y + math.sin(flank_angle) * flank_dist

        fx = max(CELL_SIZE, min(fx, (self.pathfinder.game_map.cols - 2) * CELL_SIZE))
        fy = max(CELL_SIZE, min(fy, (self.pathfinder.game_map.rows - 2) * CELL_SIZE))

        self._move_towards(fx, fy)

    def _do_retreat(self, enemies):
        nearest = self._find_nearest_enemy(enemies)
        if not nearest:
            self.state = AIState.IDLE
            return

        dx = self.unit.x - nearest.x
        dy = self.unit.y - nearest.y
        dist = math.hypot(dx, dy)
        if dist < 1:
            dx, dy = 1, 0
            dist = 1

        flee_dist = CELL_SIZE * 8
        fx = self.unit.x + (dx / dist) * flee_dist
        fy = self.unit.y + (dy / dist) * flee_dist

        fx = max(CELL_SIZE, min(fx, (self.pathfinder.game_map.cols - 2) * CELL_SIZE))
        fy = max(CELL_SIZE, min(fy, (self.pathfinder.game_map.rows - 2) * CELL_SIZE))

        self._move_towards(fx, fy)

        if self.unit.health_ratio > self._retreat_threshold + 0.15:
            self.state = AIState.IDLE

    def _do_capture(self, villages, village_owners):
        if not self._target_village:
            self.state = AIState.IDLE
            return

        tv = self._target_village
        if village_owners and village_owners.get(tv) == "red":
            self._target_village = None
            self.state = AIState.IDLE
            return

        col, row = tv
        tx = col * CELL_SIZE + CELL_SIZE / 2
        ty = row * CELL_SIZE + CELL_SIZE / 2
        dist = math.hypot(self.unit.x - tx, self.unit.y - ty)
        if dist < CELL_SIZE * 1.5:
            self.state = AIState.IDLE
            return

        if not self.unit._path or self.unit._path_index >= len(self.unit._path):
            self._move_towards(tx, ty)

    def _try_capture_village(self, villages, village_owners):
        unowned = [v for v in villages if village_owners.get(v) != "red"]
        if not unowned:
            return
        nearest_v = min(unowned, key=lambda v: math.hypot(
            self.unit.x - (v[0] * CELL_SIZE + CELL_SIZE / 2),
            self.unit.y - (v[1] * CELL_SIZE + CELL_SIZE / 2)
        ))
        self._target_village = nearest_v
        self._move_towards(
            nearest_v[0] * CELL_SIZE + CELL_SIZE / 2,
            nearest_v[1] * CELL_SIZE + CELL_SIZE / 2
        )
        self.state = AIState.CAPTURE

    def _flank_target(self, target: Unit):
        angle = math.atan2(
            target.y - self.unit.y,
            target.x - self.unit.x
        )
        flank_angle = angle + FLANK_ANGLE * self._flank_side
        flank_dist = self.unit.attack_range * 0.9
        fx = target.x + math.cos(flank_angle) * flank_dist
        fy = target.y + math.sin(flank_angle) * flank_dist

        fx = max(CELL_SIZE, min(fx, (self.pathfinder.game_map.cols - 2) * CELL_SIZE))
        fy = max(CELL_SIZE, min(fy, (self.pathfinder.game_map.rows - 2) * CELL_SIZE))

        self._move_towards(fx, fy)

    def _move_towards(self, tx: float, ty: float):
        pixel_path = self.pathfinder.find_path_pixels(
            self.unit.x, self.unit.y, tx, ty
        )
        if pixel_path:
            self.unit.set_move_path(pixel_path)

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

    def _count_nearby_allies(self, allies: List[Unit], unit: Unit,
                             range_dist: float) -> int:
        count = 0
        for a in allies:
            if a.alive and a is not unit:
                if unit.distance_to(a) <= range_dist:
                    count += 1
        return count

    def _find_allies_center(self, allies: List[Unit]) -> Optional[Tuple[float, float]]:
        alive = [a for a in allies if a.alive]
        if not alive:
            return None
        sx = sum(a.x for a in alive)
        sy = sum(a.y for a in alive)
        return (sx / len(alive), sy / len(alive))


class AIController:
    def __init__(self, pathfinder: Pathfinder):
        self.pathfinder = pathfinder
        self._unit_ais: List[UnitAI] = []

    def register_unit(self, unit: Unit):
        ai = UnitAI(unit, self.pathfinder)
        self._unit_ais.append(ai)

    def remove_dead(self):
        self._unit_ais = [a for a in self._unit_ais if a.unit.alive]

    def update(self, dt: float, enemies: List[Unit],
               villages: Optional[List[Tuple[int, int]]] = None,
               village_owners: Optional[dict] = None):
        for ai in self._unit_ais:
            allies = [a.unit for a in self._unit_ais if a.unit is not ai.unit and a.unit.alive]
            ai.update(dt, enemies, allies, villages, village_owners)
