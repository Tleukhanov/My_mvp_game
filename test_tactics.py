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
    MAX_SELECTION, FOOD_MAX, FOOD_PER_UNIT_PER_SEC,
    FOOD_PER_VILLAGE_PER_SEC, SELECT_CLICK_RADIUS,
)
from world_data import Relation
from map import TacticalMap
from pathfinding import Pathfinder
from units import Unit
from ai import AIController, UnitAI
from campaigns import get_mission_1, get_mission_2, get_mission_3, get_mission_4, MISSIONS


class TestConfig:
    def test_terrain_types_exist(self):
        assert TerrainType.PLAIN
        assert TerrainType.MOUNTAIN
        assert TerrainType.RIVER
        assert TerrainType.BRIDGE
        assert TerrainType.VILLAGE

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
        assert TERRAIN_MOVE_COST[TerrainType.VILLAGE] == 1.2

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

    def test_max_selection(self):
        assert MAX_SELECTION == 6

    def test_food_constants(self):
        assert FOOD_MAX == 1000
        assert FOOD_PER_UNIT_PER_SEC == 5
        assert FOOD_PER_VILLAGE_PER_SEC == 20

    def test_select_click_radius(self):
        assert SELECT_CLICK_RADIUS > 0


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


class TestVillages:
    def test_village_in_custom_map(self):
        grid = [[TerrainType.PLAIN] * 10 for _ in range(5)]
        grid[2][5] = TerrainType.VILLAGE
        m = TacticalMap(grid, [(5, 2)])
        assert m.get_terrain(5, 2) == TerrainType.VILLAGE
        assert (5, 2) in m.village_owners

    def test_village_owner_default_none(self):
        grid = [[TerrainType.PLAIN] * 10 for _ in range(5)]
        grid[2][5] = TerrainType.VILLAGE
        m = TacticalMap(grid, [(5, 2)])
        assert m.get_village_owner(5, 2) is None

    def test_set_village_owner(self):
        grid = [[TerrainType.PLAIN] * 10 for _ in range(5)]
        grid[2][5] = TerrainType.VILLAGE
        m = TacticalMap(grid, [(5, 2)])
        m.set_village_owner(5, 2, "blue")
        assert m.get_village_owner(5, 2) == "blue"

    def test_get_village_at(self):
        grid = [[TerrainType.PLAIN] * 10 for _ in range(5)]
        grid[2][5] = TerrainType.VILLAGE
        m = TacticalMap(grid, [(5, 2)])
        assert m.get_village_at(5, 2) == (5, 2)
        assert m.get_village_at(0, 0) is None

    def test_village_passable(self):
        grid = [[TerrainType.PLAIN] * 10 for _ in range(5)]
        grid[2][5] = TerrainType.VILLAGE
        m = TacticalMap(grid)
        assert m.is_passable(5, 2)

    def test_get_all_villages(self):
        grid = [[TerrainType.PLAIN] * 10 for _ in range(5)]
        grid[2][5] = TerrainType.VILLAGE
        grid[3][7] = TerrainType.VILLAGE
        m = TacticalMap(grid, [(5, 2), (7, 3)])
        assert len(m.get_all_villages()) == 2

    def test_village_render(self):
        grid = [[TerrainType.PLAIN] * 10 for _ in range(5)]
        grid[2][5] = TerrainType.VILLAGE
        m = TacticalMap(grid, [(5, 2)])
        surface = pygame.Surface((320, 160))
        m.render(surface)

    def test_village_blue_render(self):
        grid = [[TerrainType.PLAIN] * 10 for _ in range(5)]
        grid[2][5] = TerrainType.VILLAGE
        m = TacticalMap(grid, [(5, 2)])
        m.set_village_owner(5, 2, "blue")
        surface = pygame.Surface((320, 160))
        m.render(surface)


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

    def test_find_path_through_village(self):
        grid = [[TerrainType.PLAIN] * 10 for _ in range(3)]
        grid[1][5] = TerrainType.VILLAGE
        m = TacticalMap(grid)
        pf = Pathfinder(m)
        path = pf.find_path((0, 1), (9, 1))
        assert path is not None
        assert any(m.get_terrain(c, r) == TerrainType.VILLAGE
                    for c, r in path if m.in_bounds(c, r))


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
        assert unit.speed > self._make_unit(UnitType.INFANTRY).speed

    def test_create_archer(self):
        unit = self._make_unit(UnitType.ARCHER)
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
        assert arc.health < initial_hp

    def test_attack_cooldown(self):
        unit = self._make_unit()
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

    def test_attack_target_not_pushed_away(self):
        u1 = Unit(UnitType.INFANTRY, Team.BLUE, 100.0, 100.0)
        u2 = Unit(UnitType.INFANTRY, Team.RED, 102.0, 100.0)
        u1.set_attack_target(u2)
        x1_before = u1.x
        u1._resolve_collisions([u2])
        assert u1.x == x1_before

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
        red2 = Unit(UnitType.INFANTRY, Team.RED, 11 * CELL_SIZE, 10 * CELL_SIZE)
        blue = Unit(UnitType.INFANTRY, Team.BLUE, 30 * CELL_SIZE, 10 * CELL_SIZE)
        red._pathfinder = self.pathfinder
        red2._pathfinder = self.pathfinder
        self.ai.register_unit(red)
        self.ai.register_unit(red2)
        unit_ai = self.ai._unit_ais[0]
        unit_ai.update(1.5, [blue], [red2])
        assert unit_ai.state in (AIState.MOVE, AIState.GROUP_UP, AIState.FLANK, AIState.ATTACK)

    def test_ai_attack_when_in_range(self):
        red = Unit(UnitType.INFANTRY, Team.RED, 10 * CELL_SIZE, 10 * CELL_SIZE)
        blue = Unit(UnitType.INFANTRY, Team.BLUE, 10 * CELL_SIZE + 10, 10 * CELL_SIZE)
        self.ai.register_unit(red)
        unit_ai = self.ai._unit_ais[0]
        unit_ai.update(1.5, [blue], [])
        assert unit_ai.state == AIState.ATTACK

    def test_ai_retreats_when_low_health(self):
        red = Unit(UnitType.INFANTRY, Team.RED, 10 * CELL_SIZE, 10 * CELL_SIZE)
        red.take_damage(450)
        blue = Unit(UnitType.INFANTRY, Team.BLUE, 10 * CELL_SIZE + 10, 10 * CELL_SIZE)
        self.ai.register_unit(red)
        unit_ai = self.ai._unit_ais[0]
        unit_ai.update(1.5, [blue], [])
        assert unit_ai.state == AIState.RETREAT

    def test_ai_ignores_dead_enemies(self):
        red = Unit(UnitType.INFANTRY, Team.RED, 10 * CELL_SIZE, 10 * CELL_SIZE)
        blue = Unit(UnitType.INFANTRY, Team.BLUE, 11 * CELL_SIZE, 10 * CELL_SIZE)
        blue.alive = False
        self.ai.register_unit(red)
        unit_ai = self.ai._unit_ais[0]
        unit_ai.update(1.5, [blue], [])
        assert unit_ai.state == AIState.IDLE

    def test_ai_chases_with_pathfinding(self):
        red = Unit(UnitType.INFANTRY, Team.RED, 10 * CELL_SIZE, 10 * CELL_SIZE)
        red._pathfinder = self.pathfinder
        blue = Unit(UnitType.INFANTRY, Team.BLUE, 35 * CELL_SIZE, 10 * CELL_SIZE)
        self.ai.register_unit(red)
        unit_ai = self.ai._unit_ais[0]
        unit_ai.update(1.5, [blue], [])
        if unit_ai.unit._path:
            for px, py in unit_ai.unit._path:
                col = int(px) // CELL_SIZE
                row = int(py) // CELL_SIZE
                if self.game_map.in_bounds(col, row):
                    assert self.game_map.get_terrain(col, row) != TerrainType.MOUNTAIN

    def test_ai_captures_village(self):
        grid = [[TerrainType.PLAIN] * 20 for _ in range(10)]
        grid[5][10] = TerrainType.VILLAGE
        m = TacticalMap(grid, [(10, 5)])
        pf = Pathfinder(m)
        ai = AIController(pf)
        red = Unit(UnitType.INFANTRY, Team.RED, 5 * CELL_SIZE, 5 * CELL_SIZE)
        red._pathfinder = pf
        ai.register_unit(red)
        unit_ai = ai._unit_ais[0]
        ai.update(1.5, [], [(10, 5)], m.village_owners)
        assert unit_ai.state == AIState.CAPTURE


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

    def test_mission_3_valid(self):
        m = get_mission_3()
        assert m.name == "Речная крепость"
        assert len(m.grid) == MAP_ROWS

    def test_mission_4_valid(self):
        m = get_mission_4()
        assert m.name == "Деревни"
        assert len(m.grid) == MAP_ROWS
        assert len(m.villages) > 0

    def test_missions_dict_has_all(self):
        for i in range(1, 5):
            assert i in MISSIONS

    def test_mission_1_has_villages(self):
        m = get_mission_1()
        assert len(m.villages) > 0

    def test_mission_4_has_villages(self):
        m = get_mission_4()
        village_count = sum(
            1 for r in range(len(m.grid))
            for c in range(len(m.grid[0]))
            if m.grid[r][c] == TerrainType.VILLAGE
        )
        assert village_count == len(m.villages)

    def test_mission_4_blue_starts_bottom(self):
        m = get_mission_4()
        for _, _, row in m.blue_units:
            assert row >= MAP_ROWS // 2

    def test_mission_4_red_starts_top(self):
        m = get_mission_4()
        for _, _, row in m.red_units:
            assert row < MAP_ROWS // 2

    def test_campaign_map_render(self):
        m = get_mission_1()
        game_map = TacticalMap(m.grid, m.villages)
        surface = pygame.Surface((1280, 720))
        game_map.render(surface)

    def test_campaign_pathfinding(self):
        m = get_mission_1()
        game_map = TacticalMap(m.grid, m.villages)
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


class TestFoodSystem:
    def test_food_max(self):
        assert FOOD_MAX == 1000

    def test_food_per_unit_per_sec(self):
        assert FOOD_PER_UNIT_PER_SEC == 5

    def test_food_per_village_per_sec(self):
        assert FOOD_PER_VILLAGE_PER_SEC == 20


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
        red2 = Unit(UnitType.INFANTRY, Team.RED, 11 * CELL_SIZE, 11 * CELL_SIZE)
        blue = Unit(UnitType.INFANTRY, Team.BLUE, 30 * CELL_SIZE, 10 * CELL_SIZE)
        red._pathfinder = pf
        red2._pathfinder = pf
        ai.register_unit(red)
        ai.register_unit(red2)
        for _ in range(20):
            ai.update(0.5, [blue])
            red.update(0.5, game_map, [red, red2, blue])
            red2.update(0.5, game_map, [red, red2, blue])
        moved = red.x != 10 * CELL_SIZE or red.y != 10 * CELL_SIZE
        assert moved

    def test_village_capture_in_game(self):
        grid = [[TerrainType.PLAIN] * 10 for _ in range(5)]
        grid[2][5] = TerrainType.VILLAGE
        m = TacticalMap(grid, [(5, 2)])
        blue = Unit(UnitType.INFANTRY, Team.BLUE, 5 * CELL_SIZE + CELL_SIZE / 2, 2 * CELL_SIZE + CELL_SIZE / 2)
        for _ in range(10):
            dist = math.hypot(blue.x - (5 * CELL_SIZE + CELL_SIZE / 2),
                              blue.y - (2 * CELL_SIZE + CELL_SIZE / 2))
            if dist < CELL_SIZE * 1.2:
                m.set_village_owner(5, 2, "blue")
                break
        assert m.get_village_owner(5, 2) == "blue"


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


class TestDiplomacy:
    def setup_method(self):
        from diplomacy import DiplomacyManager
        self.diplo = DiplomacyManager()

    def test_initial_red_blue_war(self):
        assert self.diplo.get_relation("red", "blue") == Relation.WAR

    def test_initial_red_green_neutral(self):
        assert self.diplo.get_relation("red", "green") == Relation.NEUTRAL

    def test_initial_blue_green_friendly(self):
        assert self.diplo.get_relation("blue", "green") == Relation.FRIENDLY

    def test_same_nation_is_alliance(self):
        assert self.diplo.get_relation("red", "red") == Relation.ALLIANCE

    def test_set_relation(self):
        self.diplo.set_relation("red", "green", Relation.ALLIANCE)
        assert self.diplo.get_relation("red", "green") == Relation.ALLIANCE
        assert self.diplo.get_relation("green", "red") == Relation.ALLIANCE

    def test_is_enemy_war(self):
        assert self.diplo.is_enemy("red", "blue") is True

    def test_is_enemy_neutral(self):
        assert self.diplo.is_enemy("red", "green") is False

    def test_can_move_through_alliance(self):
        self.diplo.set_relation("red", "green", Relation.ALLIANCE)
        assert self.diplo.can_move_through("red", "green") is True

    def test_can_move_through_war(self):
        assert self.diplo.can_move_through("red", "blue") is False

    def test_declare_war(self):
        success, msg = self.diplo.propose("red", "green", Relation.WAR)
        assert success is True
        assert self.diplo.get_relation("red", "green") == Relation.WAR

    def test_propose_neutral_from_war(self):
        self.diplo.set_relation("red", "blue", Relation.WAR)
        success, msg = self.diplo.propose("red", "blue", Relation.NEUTRAL)
        assert "мир" in msg.lower() or "мир" in msg

    def test_relation_name(self):
        name = self.diplo.get_relation_name("red", "blue")
        assert name == "ВОЙНА"

    def test_relation_color_war(self):
        color = self.diplo.get_relation_color("red", "blue")
        assert color[0] > 150

    def test_already_same_relation(self):
        success, msg = self.diplo.propose("red", "blue", Relation.WAR)
        assert success is False


class TestWorldData:
    def test_nations_exist(self):
        from world_data import WORLD_NATIONS
        assert "red" in WORLD_NATIONS
        assert "blue" in WORLD_NATIONS
        assert "green" in WORLD_NATIONS

    def test_regions_exist(self):
        from world_data import WORLD_REGIONS
        assert len(WORLD_REGIONS) >= 18

    def test_generals_exist(self):
        from world_data import WORLD_GENERALS
        assert len(WORLD_GENERALS) >= 6

    def test_player_nation(self):
        from world_data import PLAYER_NATION
        assert PLAYER_NATION == "blue"

    def test_each_nation_has_capital(self):
        from world_data import WORLD_REGIONS, RegionType
        nations_with_caps = set()
        for r in WORLD_REGIONS:
            if r.region_type == RegionType.CAPITAL:
                nations_with_caps.add(r.owner)
        assert "red" in nations_with_caps
        assert "blue" in nations_with_caps
        assert "green" in nations_with_caps

    def test_general_start_positions_valid(self):
        from world_data import WORLD_GENERALS, WORLD_PROVINCES
        for g in WORLD_GENERALS:
            assert 0 <= g.province_idx < len(WORLD_PROVINCES)

    def test_region_start_positions_valid(self):
        from world_data import WORLD_REGIONS, MAP_COLS, MAP_ROWS
        for r in WORLD_REGIONS:
            assert 0 <= r.col < MAP_COLS
            assert 0 <= r.row < MAP_ROWS

    def test_general_has_nation(self):
        from world_data import WORLD_GENERALS, WORLD_NATIONS
        for g in WORLD_GENERALS:
            assert g.nation in WORLD_NATIONS

    def test_general_troops_positive(self):
        from world_data import WORLD_GENERALS
        for g in WORLD_GENERALS:
            assert g.troops > 0

    def test_region_has_valid_type(self):
        from world_data import WORLD_REGIONS, RegionType
        for r in WORLD_REGIONS:
            assert r.region_type in (RegionType.VILLAGE, RegionType.CITY,
                                      RegionType.CAPITAL)


class TestWorldMap:
    def setup_method(self):
        import world_data
        world_data.NATION_TERRITORY = []

    def test_general_distance(self):
        from world_data import General, WORLD_PROVINCES
        g1 = General("A", "red", 0, 1000)
        g2 = General("B", "blue", 1, 1000)
        dist = g1.distance_to(g2)
        assert dist >= 0

    def test_general_position(self):
        from world_data import General, WORLD_PROVINCES
        g = General("A", "red", 0, 1000)
        cx, cy = WORLD_PROVINCES[0].centroid
        assert g.x == cx
        assert g.y == cy

    def test_region_position(self):
        from world_data import Region, RegionType, CELL_SIZE
        r = Region("Test", RegionType.VILLAGE, 5, 6, "red")
        assert r.x == 5 * CELL_SIZE + CELL_SIZE // 2
        assert r.y == 6 * CELL_SIZE + CELL_SIZE // 2

    def test_general_moved_flag(self):
        from world_data import General
        g = General("A", "red", 0, 1000)
        assert g.moved is False
        g.moved = True
        assert g.moved is True

    def test_general_troops_cap(self):
        from world_data import General
        g = General("A", "red", 0, 5000)
        assert g.troops == 5000
        assert g.max_troops == 3000

    def test_nation_colors_unique(self):
        from world_data import WORLD_NATIONS
        colors = [n.color for n in WORLD_NATIONS.values()]
        assert len(colors) == 3


class TestImports:
    def test_import_world_data(self):
        import world_data
        assert hasattr(world_data, "WORLD_PROVINCES")
        assert hasattr(world_data, "WORLD_REGIONS")
        assert hasattr(world_data, "WORLD_GENERALS")
        assert hasattr(world_data, "WORLD_NATIONS")

    def test_import_diplomacy(self):
        from diplomacy import DiplomacyManager, Relation
        d = DiplomacyManager()
        assert d.get_relation("red", "blue") == Relation.WAR

    def test_import_config(self):
        from config import SCREEN_WIDTH, SCREEN_HEIGHT, CELL_SIZE
        assert SCREEN_WIDTH > 0
        assert SCREEN_HEIGHT > 0
        assert CELL_SIZE > 0

    def test_import_engine(self):
        from engine import GameEngine
        assert callable(GameEngine)

    def test_import_menu(self):
        from menu import MainMenu, VictoryScreen, CampaignSelect
        assert callable(MainMenu)
        assert callable(VictoryScreen)
        assert callable(CampaignSelect)

    def test_import_world_map(self):
        from world_map import WorldMapScreen
        assert callable(WorldMapScreen)

    def test_import_pathfinding(self):
        from pathfinding import Pathfinder
        assert callable(Pathfinder)

    def test_import_units(self):
        from units import Unit
        assert callable(Unit)

    def test_import_map(self):
        from map import TacticalMap
        assert callable(TacticalMap)

    def test_import_campaigns(self):
        from campaigns import get_mission_1, get_mission_2, get_mission_3, get_mission_4
        m = get_mission_1()
        assert m is not None


class TestWorldMapTopology:
    def test_province_count(self):
        from world_data import WORLD_PROVINCES
        assert len(WORLD_PROVINCES) == 50

    def test_all_provinces_have_polygons(self):
        from world_data import WORLD_PROVINCES
        for p in WORLD_PROVINCES:
            assert len(p.polygon) >= 3, f"Province {p.name} has < 3 vertices"

    def test_all_polygons_on_screen(self):
        from world_data import WORLD_PROVINCES, SCREEN_WIDTH, SCREEN_HEIGHT
        for p in WORLD_PROVINCES:
            for x, y in p.polygon:
                assert -10 <= x <= SCREEN_WIDTH + 10, \
                    f"Province {p.name} vertex ({x},{y}) off screen x"
                assert -10 <= y <= SCREEN_HEIGHT, \
                    f"Province {p.name} vertex ({x},{y}) off screen y"

    def test_centroids_computed(self):
        from world_data import WORLD_PROVINCES
        for p in WORLD_PROVINCES:
            cx, cy = p.centroid
            assert isinstance(cx, int)
            assert isinstance(cy, int)

    def test_point_in_polygon(self):
        from world_data import WORLD_PROVINCES
        for p in WORLD_PROVINCES:
            cx, cy = p.centroid
            assert p.contains_point(cx, cy), \
                f"Province {p.name} centroid not inside its polygon"

    def test_rivers_defined(self):
        from world_data import RIVER_WEST_X, RIVER_EAST_X
        assert 0 < RIVER_WEST_X < 1600
        assert 0 < RIVER_EAST_X < 1600
        assert RIVER_WEST_X < RIVER_EAST_X

    def test_bridges_defined(self):
        from world_data import BRIDGE_CONNECTIONS
        assert len(BRIDGE_CONNECTIONS) == 6

    def test_bridge_indices_valid(self):
        from world_data import BRIDGE_CONNECTIONS, WORLD_PROVINCES
        for a, b in BRIDGE_CONNECTIONS:
            assert 0 <= a < len(WORLD_PROVINCES)
            assert 0 <= b < len(WORLD_PROVINCES)

    def test_each_faction_has_regions(self):
        from world_data import WORLD_PROVINCES
        faction_counts = {}
        for p in WORLD_PROVINCES:
            if p.owner != "neutral":
                faction_counts[p.owner] = faction_counts.get(p.owner, 0) + 1
        for faction in ["red", "blue", "green"]:
            assert faction in faction_counts, f"Faction {faction} has no provinces"
            assert faction_counts[faction] >= 3, \
                f"Faction {faction} has only {faction_counts[faction]} provinces"

    def test_neutral_provinces_exist(self):
        from world_data import WORLD_PROVINCES
        neutral = [p for p in WORLD_PROVINCES if p.owner == "neutral"]
        assert len(neutral) >= 5, "Expected at least 5 neutral provinces"

    def test_nation_ids_correct(self):
        from world_data import NATION_ID
        assert NATION_ID["red"] == 1
        assert NATION_ID["blue"] == 2
        assert NATION_ID["green"] == 3

    def test_each_faction_has_7_provinces(self):
        from world_data import WORLD_PROVINCES
        counts = {}
        for p in WORLD_PROVINCES:
            if p.owner != "neutral":
                counts[p.owner] = counts.get(p.owner, 0) + 1
        assert counts["red"] == 7
        assert counts["blue"] == 7
        assert counts["green"] == 7

    def test_connections_exist(self):
        from world_data import PROVINCE_CONNECTIONS, WORLD_PROVINCES
        assert len(PROVINCE_CONNECTIONS) > 0
        for a, b in PROVINCE_CONNECTIONS:
            assert 0 <= a < len(WORLD_PROVINCES)
            assert 0 <= b < len(WORLD_PROVINCES)

    def test_three_continents_by_x_position(self):
        from world_data import WORLD_PROVINCES
        west = [p for p in WORLD_PROVINCES
                if p.centroid[0] < 480]
        center = [p for p in WORLD_PROVINCES
                  if 490 < p.centroid[0] < 1100]
        east = [p for p in WORLD_PROVINCES
                if p.centroid[0] > 1110]
        assert len(west) >= 5, f"West continent has only {len(west)} provinces"
        assert len(center) >= 10, f"Center continent has only {len(center)} provinces"
        assert len(east) >= 5, f"East continent has only {len(east)} provinces"

    def test_each_nation_has_capital(self):
        from world_data import WORLD_PROVINCES, RegionType
        nations_with_caps = set()
        for p in WORLD_PROVINCES:
            if p.region_type == RegionType.CAPITAL:
                nations_with_caps.add(p.owner)
        assert "red" in nations_with_caps
        assert "blue" in nations_with_caps
        assert "green" in nations_with_caps


class TestWorldMapInit:
    def test_world_map_screen_creates(self):
        import os
        os.environ["SDL_VIDEODRIVER"] = "dummy"
        try:
            from world_map import WorldMapScreen
            screen = WorldMapScreen()
            assert screen.running is True
            assert screen.diplomacy is not None
            assert len(screen.provinces) > 0
            assert len(screen.generals) > 0
            assert screen.selected_general is None
        except Exception:
            pass
        finally:
            os.environ.pop("SDL_VIDEODRIVER", None)
