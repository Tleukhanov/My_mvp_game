import os
os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"

import pytest
import math
import pygame
pygame.init()
pygame.display.set_mode((1, 1))

from config import (
    TerrainType, UnitType, Team, AIState,
    CELL_SIZE, MAP_COLS, MAP_ROWS,
    TERRAIN_MOVE_COST, UNIT_STATS, COMBAT_ADVANTAGE,
    COLOR_GRASS_1, COLOR_GRASS_2, COLOR_GRASS_3,
    COLOR_RIVER, COLOR_RIVER_LIGHT, COLOR_RIVER_FLOW,
)
from map import TacticalMap
from pathfinding import Pathfinder
from units import Unit
from ai import AIController, UnitAI
from campaigns import get_mission_1, get_mission_2, get_mission_3, MISSIONS


class TestConfig:
    def test_terrain_types_exist(self):
        assert TerrainType.PLAIN
        assert TerrainType.MOUNTAIN
        assert TerrainType.RIVER
        assert TerrainType.BRIDGE

    def test_unit_types_exist(self):
        assert UnitType.INFANTRY
        assert UnitType.CAVALRY
        assert UnitType.ARCHER

    def test_teams(self):
        assert Team.BLUE.value == "blue"
        assert Team.RED.value == "red"

    def test_terrain_costs(self):
        assert TERRAIN_MOVE_COST[TerrainType.PLAIN] == 1.0
        assert TERRAIN_MOVE_COST[TerrainType.MOUNTAIN] == float("inf")
        assert TERRAIN_MOVE_COST[TerrainType.RIVER] == 5.0
        assert TERRAIN_MOVE_COST[TerrainType.BRIDGE] == 1.0

    def test_unit_stats_have_required_keys(self):
        for unit_type in UnitType:
            stats = UNIT_STATS[unit_type]
            assert "max_health" in stats
            assert "speed" in stats
            assert "damage" in stats
            assert "attack_range" in stats
            assert "attack_speed" in stats

    def test_combat_advantage_matrix_complete(self):
        for attacker in UnitType:
            for defender in UnitType:
                assert (attacker, defender) in COMBAT_ADVANTAGE

    def test_cavalry_beats_archers(self):
        assert COMBAT_ADVANTAGE[(UnitType.CAVALRY, UnitType.ARCHER)] > 1.0

    def test_infantry_balanced(self):
        assert COMBAT_ADVANTAGE[(UnitType.INFANTRY, UnitType.INFANTRY)] == 1.0

    def test_cell_size_positive(self):
        assert CELL_SIZE > 0

    def test_map_dimensions(self):
        assert MAP_COLS > 0
        assert MAP_ROWS > 0

    def test_grass_colors_defined(self):
        assert COLOR_GRASS_1 is not None
        assert COLOR_GRASS_2 is not None
        assert COLOR_GRASS_3 is not None

    def test_river_colors_defined(self):
        assert COLOR_RIVER is not None
        assert COLOR_RIVER_LIGHT is not None
        assert COLOR_RIVER_FLOW is not None


class TestTacticalMap:
    def setup_method(self):
        self.game_map = TacticalMap()

    def test_default_map_created(self):
        assert len(self.game_map.grid) == MAP_ROWS
        for row in self.game_map.grid:
            assert len(row) == MAP_COLS

    def test_in_bounds(self):
        assert self.game_map.in_bounds(0, 0)
        assert self.game_map.in_bounds(MAP_COLS - 1, MAP_ROWS - 1)
        assert not self.game_map.in_bounds(-1, 0)
        assert not self.game_map.in_bounds(MAP_COLS, 0)

    def test_mountain_center_impassable(self):
        terrain = self.game_map.get_terrain(20, 2)
        assert terrain == TerrainType.MOUNTAIN
        assert not self.game_map.is_passable(20, 2)

    def test_plain_passable(self):
        terrain = self.game_map.get_terrain(0, 0)
        assert terrain == TerrainType.PLAIN
        assert self.game_map.is_passable(0, 0)

    def test_river_exists(self):
        terrain = self.game_map.get_terrain(13, 5)
        assert terrain == TerrainType.RIVER

    def test_bridge_exists(self):
        terrain = self.game_map.get_terrain(13, 8)
        assert terrain == TerrainType.BRIDGE
        assert self.game_map.is_passable(13, 8)

    def test_out_of_bounds_returns_mountain(self):
        terrain = self.game_map.get_terrain(-5, -5)
        assert terrain == TerrainType.MOUNTAIN

    def test_pixel_to_grid(self):
        col, row = self.game_map.pixel_to_grid(
            CELL_SIZE * 5 + 10, CELL_SIZE * 3 + 5
        )
        assert col == 5
        assert row == 3

    def test_grid_to_pixel_center(self):
        x, y = self.game_map.grid_to_pixel_center(5, 3)
        assert x == 5 * CELL_SIZE + CELL_SIZE / 2
        assert y == 3 * CELL_SIZE + CELL_SIZE / 2

    def test_custom_grid(self):
        grid = [[TerrainType.PLAIN] * 10 for _ in range(5)]
        m = TacticalMap(grid)
        assert m.cols == 10
        assert m.rows == 5
        assert m.get_terrain(0, 0) == TerrainType.PLAIN

    def test_render_does_not_crash(self):
        surface = pygame.Surface((1280, 720))
        self.game_map.render(surface)

    def test_grass_variants_precomputed(self):
        assert len(self.game_map._grass_variants) > 0

    def test_render_has_grass_colors(self):
        surface = pygame.Surface((1280, 720))
        self.game_map.render(surface)
        center_pixel = surface.get_at((1, 1))
        assert center_pixel[2] < center_pixel[1]


class TestPathfinding:
    def setup_method(self):
        self.game_map = TacticalMap()
        self.pathfinder = Pathfinder(self.game_map)

    def test_same_start_goal(self):
        path = self.pathfinder.find_path((1, 1), (1, 1))
        assert path == [(1, 1)]

    def test_straight_path_plain(self):
        path = self.pathfinder.find_path((0, 0), (5, 0))
        assert path is not None
        assert path[0] == (0, 0)
        assert path[-1] == (5, 0)

    def test_path_around_mountain(self):
        path = self.pathfinder.find_path((15, 2), (25, 2))
        assert path is not None
        assert path[0] == (15, 2)
        assert path[-1] == (25, 2)
        for col, row in path:
            assert self.game_map.get_terrain(col, row) != TerrainType.MOUNTAIN

    def test_path_through_bridge(self):
        path = self.pathfinder.find_path((10, 8), (16, 8))
        assert path is not None
        has_bridge = any(
            self.game_map.get_terrain(c, r) == TerrainType.BRIDGE
            for c, r in path
        )
        assert has_bridge

    def test_unreachable_returns_none(self):
        grid = [[TerrainType.PLAIN] * 5 for _ in range(3)]
        grid[1][2] = TerrainType.MOUNTAIN
        grid[0][2] = TerrainType.MOUNTAIN
        grid[2][2] = TerrainType.MOUNTAIN
        m = TacticalMap(grid)
        pf = Pathfinder(m)
        path = pf.find_path((0, 1), (4, 1))
        assert path is None

    def test_grid_to_pixel_path(self):
        grid_path = [(0, 0), (1, 0), (2, 0)]
        pixel_path = self.pathfinder.grid_to_pixel_path(grid_path)
        assert len(pixel_path) == 3
        assert pixel_path[0] == (CELL_SIZE / 2, CELL_SIZE / 2)

    def test_find_path_pixels(self):
        path = self.pathfinder.find_path_pixels(
            CELL_SIZE * 5, CELL_SIZE * 5,
            CELL_SIZE * 10, CELL_SIZE * 5,
        )
        assert path is not None
        assert len(path) >= 2

    def test_path_max_cost_limits_search(self):
        path = self.pathfinder.find_path(
            (0, 0), (39, 21), max_cost=5.0
        )
        assert path is None


class TestUnit:
    def setup_method(self):
        self.game_map = TacticalMap()

    def _make_unit(self, unit_type=UnitType.INFANTRY, team=Team.BLUE, x=100, y=100):
        return Unit(unit_type, team, x, y)

    def test_create_infantry(self):
        unit = self._make_unit(UnitType.INFANTRY)
        assert unit.unit_type == UnitType.INFANTRY
        assert unit.team == Team.BLUE
        assert unit.health == UNIT_STATS[UnitType.INFANTRY]["max_health"]
        assert unit.alive

    def test_create_cavalry(self):
        unit = self._make_unit(UnitType.CAVALRY)
        assert unit.unit_type == UnitType.CAVALRY
        assert unit.speed > self._make_unit(UnitType.INFANTRY).speed

    def test_create_archer(self):
        unit = self._make_unit(UnitType.ARCHER)
        assert unit.unit_type == UnitType.ARCHER
        assert unit.attack_range > self._make_unit(UnitType.INFANTRY).attack_range

    def test_distance_to_unit(self):
        u1 = self._make_unit(x=0, y=0)
        u2 = self._make_unit(x=3, y=4)
        assert u1.distance_to(u2) == 5.0

    def test_distance_to_point(self):
        u = self._make_unit(x=0, y=0)
        assert u.distance_to_point(3, 4) == 5.0

    def test_take_damage(self):
        unit = self._make_unit()
        initial = unit.health
        unit.take_damage(100)
        assert unit.health == initial - 100
        assert unit.alive

    def test_lethal_damage_kills(self):
        unit = self._make_unit()
        unit.take_damage(unit.health + 1)
        assert not unit.alive
        assert unit.health == 0

    def test_health_ratio(self):
        unit = self._make_unit()
        unit.take_damage(unit.max_health // 2)
        assert 0.4 <= unit.health_ratio <= 0.6

    def test_set_move_path(self):
        unit = self._make_unit()
        path = [(10.0, 10.0), (20.0, 10.0), (30.0, 10.0)]
        unit.set_move_path(path)
        assert unit._path == path
        assert unit._path_index == 0

    def test_clear_orders(self):
        unit = self._make_unit()
        unit.set_move_path([(10.0, 10.0)])
        unit.set_attack_target(self._make_unit(x=200, y=200))
        unit.clear_orders()
        assert unit._path == []
        assert unit._attack_target is None

    def test_combat_infantry_vs_infantry(self):
        u1 = self._make_unit(UnitType.INFANTRY, x=0, y=0)
        u2 = self._make_unit(UnitType.INFANTRY, Team.RED, x=10, y=0)
        initial_hp = u2.health
        u1._perform_attack(u2)
        assert u2.health < initial_hp

    def test_combat_cavalry_vs_archer_bonus(self):
        cav = self._make_unit(UnitType.CAVALRY, x=0, y=0)
        arc = self._make_unit(UnitType.ARCHER, Team.RED, x=10, y=0)
        initial_hp = arc.health
        cav._perform_attack(arc)
        assert cav.health == UNIT_STATS[UnitType.CAVALRY]["max_health"]
        assert arc.health < initial_hp

    def test_attack_cooldown(self):
        unit = self._make_unit()
        assert unit._attack_timer == 0.0
        unit._attack_timer = 0.5
        unit.update(0.1, self.game_map, [])
        assert unit._attack_timer > 0.0

    def test_dead_unit_does_not_update(self):
        unit = self._make_unit()
        unit.alive = False
        unit.update(0.1, self.game_map, [])
        assert not unit.alive

    def test_render_does_not_crash(self):
        surface = pygame.Surface((1280, 720))
        unit = self._make_unit()
        unit.render(surface)

    def test_render_dead_unit(self):
        surface = pygame.Surface((1280, 720))
        unit = self._make_unit()
        unit.alive = False
        unit.render(surface)

    def test_grid_position(self):
        unit = self._make_unit(x=CELL_SIZE * 5 + 10, y=CELL_SIZE * 3 + 5)
        assert unit.grid_col == 5
        assert unit.grid_row == 3


class TestUnitCollision:
    def setup_method(self):
        self.game_map = TacticalMap()

    def test_close_units_separate(self):
        u1 = Unit(UnitType.INFANTRY, Team.BLUE, 100.0, 100.0)
        u2 = Unit(UnitType.INFANTRY, Team.BLUE, 102.0, 100.0)
        x1_before, x2_before = u1.x, u2.x
        u1._resolve_collisions([u2])
        u2._resolve_collisions([u1])
        dist = math.hypot(u1.x - u2.x, u1.y - u2.y)
        assert dist > 2.0

    def test_far_units_not_affected(self):
        u1 = Unit(UnitType.INFANTRY, Team.BLUE, 100.0, 100.0)
        u2 = Unit(UnitType.INFANTRY, Team.BLUE, 200.0, 200.0)
        x1, y1 = u1.x, u1.y
        u1._resolve_collisions([u2])
        assert u1.x == x1
        assert u1.y == y1

    def test_dead_units_ignored_in_collision(self):
        u1 = Unit(UnitType.INFANTRY, Team.BLUE, 100.0, 100.0)
        u2 = Unit(UnitType.INFANTRY, Team.RED, 101.0, 100.0)
        u2.alive = False
        x1, y1 = u1.x, u1.y
        u1._resolve_collisions([u2])
        assert u1.x == x1
        assert u1.y == y1

    def test_collision_in_update(self):
        u1 = Unit(UnitType.INFANTRY, Team.BLUE, 100.0, 100.0)
        u2 = Unit(UnitType.INFANTRY, Team.BLUE, 101.0, 100.0)
        u1.set_move_path([(100.0, 100.0), (150.0, 100.0)])
        u2.set_move_path([(101.0, 100.0), (151.0, 100.0)])
        for _ in range(10):
            u1.update(0.016, self.game_map, [u1, u2])
            u2.update(0.016, self.game_map, [u1, u2])
        dist = math.hypot(u1.x - u2.x, u1.y - u2.y)
        assert dist >= Unit.MIN_SEPARATION - 5

    def test_different_teams_still_separate(self):
        u1 = Unit(UnitType.INFANTRY, Team.BLUE, 100.0, 100.0)
        u2 = Unit(UnitType.INFANTRY, Team.RED, 102.0, 100.0)
        u1._resolve_collisions([u2])
        u2._resolve_collisions([u1])
        dist = math.hypot(u1.x - u2.x, u1.y - u2.y)
        assert dist > 2.0


class TestAI:
    def setup_method(self):
        self.game_map = TacticalMap()
        self.pathfinder = Pathfinder(self.game_map)
        self.ai = AIController(self.pathfinder)

    def test_register_unit(self):
        unit = Unit(UnitType.INFANTRY, Team.RED, 100, 100)
        self.ai.register_unit(unit)
        assert len(self.ai._unit_ais) == 1

    def test_remove_dead(self):
        u1 = Unit(UnitType.INFANTRY, Team.RED, 100, 100)
        u2 = Unit(UnitType.INFANTRY, Team.RED, 200, 100)
        self.ai.register_unit(u1)
        self.ai.register_unit(u2)
        u1.alive = False
        self.ai.remove_dead()
        assert len(self.ai._unit_ais) == 1

    def test_ai_finds_enemy(self):
        red = Unit(UnitType.INFANTRY, Team.RED, 10 * CELL_SIZE, 10 * CELL_SIZE)
        blue = Unit(UnitType.INFANTRY, Team.BLUE, 11 * CELL_SIZE, 10 * CELL_SIZE)
        self.ai.register_unit(red)

        unit_ai = self.ai._unit_ais[0]
        nearest = unit_ai._find_nearest_enemy([blue])
        assert nearest is blue

    def test_ai_moves_towards_distant_enemy(self):
        red = Unit(UnitType.INFANTRY, Team.RED, 10 * CELL_SIZE, 10 * CELL_SIZE)
        blue = Unit(UnitType.INFANTRY, Team.BLUE, 30 * CELL_SIZE, 10 * CELL_SIZE)
        red._pathfinder = self.pathfinder
        self.ai.register_unit(red)

        unit_ai = self.ai._unit_ais[0]
        assert unit_ai.state == AIState.IDLE
        unit_ai.update(1.0, [blue], [])
        assert unit_ai.state == AIState.MOVE
        assert unit_ai.unit._path is not None
        assert len(unit_ai.unit._path) > 0

    def test_ai_attack_when_in_range(self):
        red = Unit(UnitType.INFANTRY, Team.RED, 10 * CELL_SIZE, 10 * CELL_SIZE)
        blue = Unit(UnitType.INFANTRY, Team.BLUE, 10 * CELL_SIZE + 10, 10 * CELL_SIZE)
        self.ai.register_unit(red)

        unit_ai = self.ai._unit_ais[0]
        unit_ai.update(1.0, [blue], [])
        assert unit_ai.state == AIState.ATTACK
        assert unit_ai.unit._attack_target is blue

    def test_ai_retreats_when_low_health(self):
        red = Unit(UnitType.INFANTRY, Team.RED, 10 * CELL_SIZE, 10 * CELL_SIZE)
        red.take_damage(450)
        blue = Unit(UnitType.INFANTRY, Team.BLUE, 10 * CELL_SIZE + 10, 10 * CELL_SIZE)
        self.ai.register_unit(red)

        unit_ai = self.ai._unit_ais[0]
        unit_ai.update(1.0, [blue], [])
        assert unit_ai.state == AIState.MOVE

    def test_ai_ignores_dead_enemies(self):
        red = Unit(UnitType.INFANTRY, Team.RED, 10 * CELL_SIZE, 10 * CELL_SIZE)
        blue = Unit(UnitType.INFANTRY, Team.BLUE, 11 * CELL_SIZE, 10 * CELL_SIZE)
        blue.alive = False
        self.ai.register_unit(red)

        unit_ai = self.ai._unit_ais[0]
        unit_ai.update(1.0, [blue], [])
        assert unit_ai.state == AIState.IDLE

    def test_ai_chases_with_pathfinding(self):
        red = Unit(UnitType.INFANTRY, Team.RED, 10 * CELL_SIZE, 10 * CELL_SIZE)
        red._pathfinder = self.pathfinder
        blue = Unit(UnitType.INFANTRY, Team.BLUE, 35 * CELL_SIZE, 10 * CELL_SIZE)
        self.ai.register_unit(red)

        unit_ai = self.ai._unit_ais[0]
        unit_ai.update(0.5, [blue], [])
        if unit_ai.unit._path:
            for px, py in unit_ai.unit._path:
                col = int(px) // CELL_SIZE
                row = int(py) // CELL_SIZE
                if self.game_map.in_bounds(col, row):
                    assert self.game_map.get_terrain(col, row) != TerrainType.MOUNTAIN


class TestCampaigns:
    def test_mission_1_valid(self):
        m = get_mission_1()
        assert m.name == "Битва у моста"
        assert len(m.grid) == MAP_ROWS
        assert len(m.blue_units) > 0
        assert len(m.red_units) > 0

    def test_mission_2_valid(self):
        m = get_mission_2()
        assert m.name == "Ущелье смерти"
        assert len(m.grid) == MAP_ROWS
        assert len(m.blue_units) > 0
        assert len(m.red_units) > 0

    def test_mission_3_valid(self):
        m = get_mission_3()
        assert m.name == "Речная крепость"
        assert len(m.grid) == MAP_ROWS
        assert len(m.blue_units) > 0
        assert len(m.red_units) > 0

    def test_missions_dict_has_all(self):
        assert 1 in MISSIONS
        assert 2 in MISSIONS
        assert 3 in MISSIONS

    def test_mission_1_has_mountains(self):
        m = get_mission_1()
        has_mountain = any(
            m.grid[r][c] == TerrainType.MOUNTAIN
            for r in range(len(m.grid))
            for c in range(len(m.grid[0]))
        )
        assert has_mountain

    def test_mission_2_has_narrow_passage(self):
        m = get_mission_2()
        mountain_count = sum(
            1 for r in range(len(m.grid))
            for c in range(len(m.grid[0]))
            if m.grid[r][c] == TerrainType.MOUNTAIN
        )
        total = len(m.grid) * len(m.grid[0])
        assert mountain_count / total > 0.3

    def test_mission_3_has_river(self):
        m = get_mission_3()
        has_river = any(
            m.grid[r][c] == TerrainType.RIVER
            for r in range(len(m.grid))
            for c in range(len(m.grid[0]))
        )
        assert has_river

    def test_campaign_map_render(self):
        m = get_mission_1()
        game_map = TacticalMap(m.grid)
        surface = pygame.Surface((1280, 720))
        game_map.render(surface)

    def test_campaign_pathfinding(self):
        m = get_mission_1()
        game_map = TacticalMap(m.grid)
        pf = Pathfinder(game_map)
        blue_start = m.blue_units[0][1:]
        red_start = m.red_units[0][1:]
        path = pf.find_path(blue_start, red_start)
        assert path is not None

    def test_campaign_units_spawn_correctly(self):
        from engine import UNIT_TYPE_MAP
        m = get_mission_1()
        for type_str, col, row in m.blue_units:
            assert type_str in UNIT_TYPE_MAP
            assert 0 <= col < MAP_COLS
            assert 0 <= row < MAP_ROWS


class TestIntegration:
    def test_path_around_full_map(self):
        game_map = TacticalMap()
        pathfinder = Pathfinder(game_map)
        path = pathfinder.find_path((1, 1), (38, 20))
        assert path is not None
        assert len(path) > 10

    def test_multiple_units_on_map(self):
        game_map = TacticalMap()
        units = [
            Unit(UnitType.INFANTRY, Team.BLUE, 3 * CELL_SIZE, 5 * CELL_SIZE),
            Unit(UnitType.CAVALRY, Team.BLUE, 4 * CELL_SIZE, 5 * CELL_SIZE),
            Unit(UnitType.ARCHER, Team.BLUE, 2 * CELL_SIZE, 6 * CELL_SIZE),
            Unit(UnitType.INFANTRY, Team.RED, 36 * CELL_SIZE, 5 * CELL_SIZE),
            Unit(UnitType.CAVALRY, Team.RED, 35 * CELL_SIZE, 5 * CELL_SIZE),
            Unit(UnitType.ARCHER, Team.RED, 37 * CELL_SIZE, 6 * CELL_SIZE),
        ]
        pathfinder = Pathfinder(game_map)
        for u in units:
            u.update(0.016, game_map, units)

    def test_combat_cycle(self):
        u1 = Unit(UnitType.INFANTRY, Team.BLUE, 0, 0)
        u2 = Unit(UnitType.INFANTRY, Team.RED, 5, 0)
        initial = u2.health
        u1._perform_attack(u2)
        assert u2.health < initial

    def test_render_full_scene(self):
        game_map = TacticalMap()
        surface = pygame.Surface((1280, 720))
        game_map.render(surface)
        units = [
            Unit(UnitType.INFANTRY, Team.BLUE, 100, 100),
            Unit(UnitType.CAVALRY, Team.RED, 200, 200),
            Unit(UnitType.ARCHER, Team.BLUE, 150, 150),
        ]
        for u in units:
            u.render(surface)

    def test_ai_engages_on_spawn(self):
        game_map = TacticalMap()
        pf = Pathfinder(game_map)
        ai = AIController(pf)
        red = Unit(UnitType.INFANTRY, Team.RED, 10 * CELL_SIZE, 10 * CELL_SIZE)
        blue = Unit(UnitType.INFANTRY, Team.BLUE, 30 * CELL_SIZE, 10 * CELL_SIZE)
        red._pathfinder = pf
        ai.register_unit(red)
        for _ in range(20):
            ai.update(0.5, [blue])
            red.update(0.5, game_map, [red, blue])
        moved = red.x != 10 * CELL_SIZE or red.y != 10 * CELL_SIZE
        assert moved


class TestEdgeCases:
    def test_zero_health_unit_dies(self):
        unit = Unit(UnitType.INFANTRY, Team.BLUE, 0, 0, health=1)
        unit.take_damage(1)
        assert not unit.alive
        assert unit.health == 0

    def test_overkill_does_not_go_negative(self):
        unit = Unit(UnitType.INFANTRY, Team.BLUE, 0, 0, health=100)
        unit.take_damage(9999)
        assert not unit.alive
        assert unit.health == 0

    def test_unit_at_map_edge(self):
        unit = Unit(UnitType.INFANTRY, Team.BLUE, CELL_SIZE - 1, CELL_SIZE - 1)
        assert unit.grid_col == 0
        assert unit.grid_row == 0

    def test_pathfinding_same_tile(self):
        game_map = TacticalMap()
        pf = Pathfinder(game_map)
        path = pf.find_path((1, 1), (1, 1))
        assert path == [(1, 1)]

    def test_pathfinding_adjacent(self):
        game_map = TacticalMap()
        pf = Pathfinder(game_map)
        path = pf.find_path((0, 0), (1, 0))
        assert path is not None
        assert len(path) == 2
