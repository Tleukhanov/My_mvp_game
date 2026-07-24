import pygame
import sys
import math
from typing import Optional, List, Tuple
from world_data import (
    CELL_SIZE, MAP_COLS, MAP_ROWS, SCREEN_WIDTH, SCREEN_HEIGHT,
    COLOR_OCEAN, COLOR_OCEAN_LIGHT, COLOR_LAND, COLOR_LAND_DARK,
    COLOR_BORDER, COLOR_GRID, COLOR_NEUTRAL_REGION,
    COLOR_FORTRESS, COLOR_CAPITAL, COLOR_HUD_BG, COLOR_HUD_TEXT,
    COLOR_HUD_TEXT_DIM, COLOR_WHITE, COLOR_BLACK,
    COLOR_GENERAL_SELECTED, COLOR_GENERAL_MOVABLE, COLOR_GENERAL_DONE,
    COLOR_MENU_BG, COLOR_MENU_TITLE, COLOR_MENU_BUTTON,
    COLOR_MENU_BUTTON_HOVER, COLOR_MENU_BUTTON_TEXT, COLOR_MENU_SUBTITLE,
    WORLD_NATIONS, WORLD_REGIONS, WORLD_GENERALS,
    PLAYER_NATION, RegionType, General, Nation, Region,
)
from diplomacy import DiplomacyManager, Relation


WORLD_MAP = [
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [0, 0, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [0, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [0, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [0, 0, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
]

NATION_TERRITORY = [
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [0, 0, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [0, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [0, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [0, 0, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 2, 2, 2, 2, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0, 0, 2, 2, 2, 2, 2, 2, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0, 0, 2, 2, 2, 2, 2, 2, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 2, 2, 2, 2, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2, 2, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
]

NATION_ID = {"nordheim": 1, "valoria": 2, "drakoria": 3}


class WorldMapScreen:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("Tactic Battle - World Map")
        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        self.clock = pygame.time.Clock()
        self.running = True

        self.font_hud = pygame.font.SysFont(None, 18)
        self.font_title = pygame.font.SysFont(None, 28, bold=True)
        self.font_small = pygame.font.SysFont(None, 14)
        self.font_region = pygame.font.SysFont(None, 12)

        self.diplomacy = DiplomacyManager()
        self.regions: List[Region] = [Region(r.name, r.region_type, r.col, r.row, r.owner)
                                       for r in WORLD_REGIONS]
        self.generals: List[General] = [General(g.name, g.nation, g.col, g.row, g.troops)
                                         for g in WORLD_GENERALS]

        self.selected_general: Optional[General] = None
        self._turn = 1
        self._phase = "player"
        self._show_diplomacy = False
        self._diplomacy_target: Optional[str] = None
        self._battle_result: Optional[str] = None
        self._battle_timer = 0.0
        self._game_over = False
        self._winner: Optional[str] = None

        self._camera_x = 0
        self._camera_y = 0

    def run(self) -> Optional[str]:
        while self.running:
            dt = self.clock.tick(60) / 1000.0
            self._handle_events()
            self._update(dt)
            self._render()
        return self._winner

    def _handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    if self._show_diplomacy:
                        self._show_diplomacy = False
                        self._diplomacy_target = None
                    elif self.selected_general:
                        self.selected_general = None
                    else:
                        self.running = False
                elif event.key == pygame.K_SPACE:
                    self._end_turn()
                elif event.key == pygame.K_d:
                    self._show_diplomacy = not self._show_diplomacy
                elif event.key == pygame.K_n and self._show_diplomacy:
                    self._cycle_diplomacy_target(1)
                elif event.key == pygame.K_p and self._show_diplomacy:
                    self._cycle_diplomacy_target(-1)
                elif self._show_diplomacy:
                    if event.key == pygame.K_1:
                        self._diplomacy_action(Relation.WAR)
                    elif event.key == pygame.K_2:
                        self._diplomacy_action(Relation.NEUTRAL)
                    elif event.key == pygame.K_3:
                        self._diplomacy_action(Relation.FRIENDLY)
                    elif event.key == pygame.K_4:
                        self._diplomacy_action(Relation.ALLIANCE)

            elif event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1:
                    mx, my = event.pos
                    if my < SCREEN_HEIGHT - 80:
                        self._handle_map_click(mx, my)

    def _handle_map_click(self, mx: int, my: int):
        col = mx // CELL_SIZE
        row = my // CELL_SIZE

        for g in self.generals:
            if g.nation == PLAYER_NATION and not g.moved:
                if abs(g.col - col) <= 0 and abs(g.row - row) <= 0:
                    self.selected_general = g
                    return

        if self.selected_general:
            dist = math.hypot(self.selected_general.col - col,
                              self.selected_general.row - row)
            if dist <= 2:
                self._move_general(self.selected_general, col, row)
                self.selected_general = None

    def _move_general(self, general: General, col: int, row: int):
        if not (0 <= col < MAP_COLS and 0 <= row < MAP_ROWS):
            return
        if WORLD_MAP[row][col] == 0:
            return

        territory = NATION_TERRITORY[row][col]
        owner_nation = None
        for n, nid in NATION_ID.items():
            if nid == territory:
                owner_nation = n
                break

        if owner_nation and owner_nation != general.nation:
            rel = self.diplomacy.get_relation(general.nation, owner_nation)
            if rel == Relation.WAR:
                pass
            elif rel in (Relation.FRIENDLY, Relation.ALLIANCE):
                return
            else:
                return

        for g in self.generals:
            if g is not general and g.nation != general.nation:
                if abs(g.col - col) <= 1 and abs(g.row - row) <= 1:
                    if self.diplomacy.is_enemy(general.nation, g.nation):
                        self._start_battle(general, g)
                        general.moved = True
                        return

        general.col = col
        general.row = row
        general.moved = True

        self._try_capture_region(general)

    def _try_capture_region(self, general: General):
        for region in self.regions:
            if region.col == general.col and region.row == general.row:
                if region.owner != general.nation:
                    rel = self.diplomacy.get_relation(general.nation, region.owner)
                    if rel == Relation.WAR or region.owner == "neutral":
                        region.owner = general.nation
                        NATION_TERRITORY[region.row][region.col] = NATION_ID[general.nation]
                        self._expand_territory(general.nation, region.col, region.row)

    def _expand_territory(self, nation: str, center_col: int, center_row: int):
        nid = NATION_ID[nation]
        for dr in range(-1, 2):
            for dc in range(-1, 2):
                r, c = center_row + dr, center_col + dc
                if 0 <= r < MAP_ROWS and 0 <= c < MAP_COLS:
                    if WORLD_MAP[r][c] == 1 and NATION_TERRITORY[r][c] == 0:
                        NATION_TERRITORY[r][c] = nid

    def _start_battle(self, attacker: General, defender: General):
        a_power = attacker.troops * (attacker.health / 100)
        d_power = defender.troops * (defender.health / 100)

        import random
        a_roll = a_power * random.uniform(0.7, 1.3)
        d_roll = d_power * random.uniform(0.7, 1.3)

        if a_roll > d_roll:
            ratio = d_roll / a_roll if a_roll > 0 else 0
            losses = int(attacker.troops * ratio * 0.3)
            attacker.troops = max(100, attacker.troops - losses)
            defender.troops = max(0, defender.troops - int(defender.troops * 0.7))
            if defender.troops <= 0:
                self.generals.remove(defender)
                self._battle_result = f"{attacker.name} победил {defender.name}!"
            else:
                self._battle_result = f"{attacker.name} отбил атаку, потери: {losses}"
            defender.health = max(0, defender.health - 20)
        else:
            ratio = a_roll / d_roll if d_roll > 0 else 0
            losses = int(attacker.troops * 0.5)
            attacker.troops = max(0, attacker.troops - losses)
            if attacker.troops <= 0:
                self.generals.remove(attacker)
                self._battle_result = f"{defender.name} разбил {attacker.name}!"
            else:
                self._battle_result = f"{attacker.name} отступил, потери: {losses}"

        self._battle_timer = 3.0

    def _cycle_diplomacy_target(self, direction: int):
        nations = [n for n in WORLD_NATIONS if n != PLAYER_NATION]
        if not nations:
            return
        if self._diplomacy_target is None:
            self._diplomacy_target = nations[0]
        else:
            idx = nations.index(self._diplomacy_target) if self._diplomacy_target in nations else 0
            idx = (idx + direction) % len(nations)
            self._diplomacy_target = nations[idx]

    def _diplomacy_action(self, relation: Relation):
        if not self._diplomacy_target:
            return
        success, msg = self.diplomacy.propose(
            PLAYER_NATION, self._diplomacy_target, relation
        )
        self._battle_result = msg
        self._battle_timer = 3.0

    def _end_turn(self):
        self._turn += 1
        for g in self.generals:
            g.moved = False

        self._ai_turn()

    def _ai_turn(self):
        for g in self.generals:
            if g.nation != PLAYER_NATION:
                self._ai_move_general(g)

    def _ai_move_general(self, general: General):
        enemies = [e for e in self.generals
                   if e.nation != general.nation
                   and self.diplomacy.is_enemy(general.nation, e.nation)]
        if enemies:
            nearest = min(enemies, key=lambda e: general.distance_to(e))
            if general.distance_to(nearest) <= 3:
                dx = nearest.col - general.col
                dy = nearest.row - general.row
                dist = math.hypot(dx, dy)
                if dist > 0:
                    move_col = general.col + round(dx / dist)
                    move_row = general.row + round(dy / dist)
                    if 0 <= move_col < MAP_COLS and 0 <= move_row < MAP_ROWS:
                        if WORLD_MAP[move_row][move_col] == 1:
                            for eg in self.generals:
                                if eg is not general and eg.nation != general.nation:
                                    if abs(eg.col - move_col) <= 1 and abs(eg.row - move_row) <= 1:
                                        if self.diplomacy.is_enemy(general.nation, eg.nation):
                                            self._start_battle(general, eg)
                                            general.moved = True
                                            return
                            general.col = move_col
                            general.row = move_row
                            general.moved = True
                            self._try_capture_region(general)

    def _update(self, dt: float):
        if self._battle_timer > 0:
            self._battle_timer -= dt
            if self._battle_timer <= 0:
                self._battle_result = None

        blue_alive = any(g.nation == PLAYER_NATION for g in self.generals)
        other_alive = [g for g in self.generals if g.nation != PLAYER_NATION]
        if not blue_alive and other_alive:
            self._game_over = True
            self._winner = "DEFEAT"
        elif blue_alive and not other_alive:
            self._game_over = True
            self._winner = "VICTORY"

    def _render(self):
        self.screen.fill(COLOR_OCEAN)

        for row in range(MAP_ROWS):
            for col in range(MAP_COLS):
                x = col * CELL_SIZE
                y = row * CELL_SIZE

                if WORLD_MAP[row][col] == 0:
                    shade = ((row + col) % 2) * 5
                    color = (COLOR_OCEAN_LIGHT[0] + shade,
                             COLOR_OCEAN_LIGHT[1] + shade,
                             COLOR_OCEAN_LIGHT[2] + shade)
                    pygame.draw.rect(self.screen, color, (x, y, CELL_SIZE, CELL_SIZE))
                    continue

                territory = NATION_TERRITORY[row][col]
                if territory == 1:
                    base = WORLD_NATIONS["nordheim"].color
                elif territory == 2:
                    base = WORLD_NATIONS["valoria"].color
                elif territory == 3:
                    base = WORLD_NATIONS["drakoria"].color
                else:
                    base = COLOR_LAND

                shade = ((row + col) % 2) * 8
                land_color = (base[0] + shade, base[1] + shade, base[2] + shade)
                pygame.draw.rect(self.screen, land_color, (x, y, CELL_SIZE, CELL_SIZE))
                pygame.draw.rect(self.screen, COLOR_GRID, (x, y, CELL_SIZE, CELL_SIZE), 1)

        for region in self.regions:
            self._render_region(region)

        for general in self.generals:
            self._render_general(general)

        self._render_hud()

        if self._show_diplomacy:
            self._render_diplomacy_panel()

        if self._battle_result:
            self._render_battle_result()

        if self._game_over:
            self._render_game_over()

        pygame.display.flip()

    def _render_region(self, region: Region):
        x = region.col * CELL_SIZE + CELL_SIZE // 2
        y = region.row * CELL_SIZE + CELL_SIZE // 2

        nation = WORLD_NATIONS.get(region.owner)
        if nation:
            color = nation.light_color
        else:
            color = COLOR_NEUTRAL_REGION

        if region.region_type == RegionType.CAPITAL:
            size = 10
            pygame.draw.circle(self.screen, color, (x, y), size)
            pygame.draw.circle(self.screen, COLOR_WHITE, (x, y), size, 2)
            inner = 6
            pygame.draw.circle(self.screen, (255, 220, 100), (x, y), inner)
        elif region.region_type == RegionType.CITY:
            size = 8
            pygame.draw.circle(self.screen, color, (x, y), size)
            pygame.draw.circle(self.screen, COLOR_WHITE, (x, y), size, 1)
        elif region.region_type == RegionType.FORTRESS:
            half = 7
            rect = pygame.Rect(x - half, y - half, half * 2, half * 2)
            pygame.draw.rect(self.screen, color, rect)
            pygame.draw.rect(self.screen, COLOR_WHITE, rect, 1)
        else:
            size = 5
            pygame.draw.circle(self.screen, color, (x, y), size)
            pygame.draw.circle(self.screen, COLOR_WHITE, (x, y), size, 1)

        name = self.font_region.render(region.name, True, COLOR_WHITE)
        nx = x - name.get_width() // 2
        ny = y + 12
        bg = pygame.Surface((name.get_width() + 4, name.get_height() + 2), pygame.SRCALPHA)
        bg.fill((0, 0, 0, 140))
        self.screen.blit(bg, (nx - 2, ny - 1))
        self.screen.blit(name, (nx, ny))

    def _render_general(self, general: General):
        x = general.col * CELL_SIZE + CELL_SIZE // 2
        y = general.row * CELL_SIZE + CELL_SIZE // 2

        nation = WORLD_NATIONS.get(general.nation)
        color = nation.color if nation else (150, 150, 150)

        if general is self.selected_general:
            pygame.draw.circle(self.screen, COLOR_GENERAL_SELECTED, (x, y), 16, 3)
        elif not general.moved:
            pygame.draw.circle(self.screen, COLOR_GENERAL_MOVABLE, (x, y), 14, 2)
        else:
            pygame.draw.circle(self.screen, COLOR_GENERAL_DONE, (x, y), 14, 2)

        pygame.draw.circle(self.screen, color, (x, y), 10)
        pygame.draw.circle(self.screen, COLOR_WHITE, (x, y), 10, 1)

        star_points = []
        for i in range(5):
            angle = math.radians(i * 72 - 90)
            sx = x + math.cos(angle) * 5
            sy = y + math.sin(angle) * 5
            star_points.append((sx, sy))
            angle2 = math.radians(i * 72 + 36 - 90)
            sx2 = x + math.cos(angle2) * 2.5
            sy2 = y + math.sin(angle2) * 2.5
            star_points.append((sx2, sy2))
        pygame.draw.polygon(self.screen, COLOR_WHITE, star_points)

        label = self.font_region.render(f"{general.name} ({general.troops})", True, COLOR_WHITE)
        lx = x - label.get_width() // 2
        ly = y - 24
        bg = pygame.Surface((label.get_width() + 4, label.get_height() + 2), pygame.SRCALPHA)
        bg.fill((0, 0, 0, 160))
        self.screen.blit(bg, (lx - 2, ly - 1))
        self.screen.blit(label, (lx, ly))

    def _render_hud(self):
        hud_y = SCREEN_HEIGHT - 80
        pygame.draw.rect(self.screen, COLOR_HUD_BG, (0, hud_y, SCREEN_WIDTH, 80))

        turn_text = self.font_hud.render(
            f"Turn: {self._turn} | SPACE: End Turn | D: Diplomacy | ESC: Menu",
            True, COLOR_HUD_TEXT
        )
        self.screen.blit(turn_text, (12, hud_y + 4))

        nation = WORLD_NATIONS[PLAYER_NATION]
        info = self.font_hud.render(
            f"{nation.name} | Gold: {nation.gold}",
            True, nation.color
        )
        self.screen.blit(info, (12, hud_y + 24))

        generals_info = [f"{g.name}({g.troops})" for g in self.generals
                         if g.nation == PLAYER_NATION]
        gen_text = self.font_hud.render(
            f"Generals: {', '.join(generals_info)}",
            True, COLOR_HUD_TEXT_DIM
        )
        self.screen.blit(gen_text, (12, hud_y + 44))

        regions_count = {}
        for r in self.regions:
            regions_count[r.owner] = regions_count.get(r.owner, 0) + 1
        rx = SCREEN_WIDTH - 12
        for nation_key in ["nordheim", "valoria", "drakoria"]:
            count = regions_count.get(nation_key, 0)
            n = WORLD_NATIONS[nation_key]
            rt = self.font_hud.render(f"{n.name}: {count}", True, n.color)
            rx -= rt.get_width() + 16
            self.screen.blit(rt, (rx, hud_y + 4))

        if self.selected_general:
            sel = self.selected_general
            sel_text = self.font_hud.render(
                f"Selected: {sel.name} | Troops: {sel.troops} | Click to move",
                True, COLOR_GENERAL_SELECTED
            )
            self.screen.blit(sel_text, (SCREEN_WIDTH // 2 - sel_text.get_width() // 2, hud_y + 60))

    def _render_diplomacy_panel(self):
        overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 120))
        self.screen.blit(overlay, (0, 0))

        pw, ph = 500, 350
        px = SCREEN_WIDTH // 2 - pw // 2
        py = SCREEN_HEIGHT // 2 - ph // 2
        pygame.draw.rect(self.screen, (40, 35, 30), (px, py, pw, ph), border_radius=8)
        pygame.draw.rect(self.screen, COLOR_WHITE, (px, py, pw, ph), 2, border_radius=8)

        title = self.font_title.render("DIPLOMACY", True, COLOR_MENU_TITLE)
        self.screen.blit(title, (px + pw // 2 - title.get_width() // 2, py + 10))

        if self._diplomacy_target:
            target_nation = WORLD_NATIONS[self._diplomacy_target]
            current = self.diplomacy.get_relation(PLAYER_NATION, self._diplomacy_target)
            rel_name = self.diplomacy.get_relation_name(PLAYER_NATION, self._diplomacy_target)
            rel_color = self.diplomacy.get_relation_color(PLAYER_NATION, self._diplomacy_target)

            target_text = self.font_hud.render(
                f"Target: {target_nation.name}", True, target_nation.color
            )
            self.screen.blit(target_text, (px + 20, py + 50))

            current_text = self.font_hud.render(
                f"Current: {rel_name}", True, rel_color
            )
            self.screen.blit(current_text, (px + 20, py + 75))

            actions = [
                ("1", "Declare WAR", (200, 60, 60)),
                ("2", "Propose NEUTRAL", (180, 170, 150)),
                ("3", "Propose FRIENDLY", (80, 180, 80)),
                ("4", "Propose ALLIANCE", (60, 120, 220)),
            ]
            for i, (key, text, color) in enumerate(actions):
                ay = py + 110 + i * 35
                key_text = self.font_hud.render(f"[{key}]", True, COLOR_HUD_TEXT_DIM)
                act_text = self.font_hud.render(text, True, color)
                self.screen.blit(key_text, (px + 30, ay))
                self.screen.blit(act_text, (px + 70, ay))
        else:
            no_target = self.font_hud.render("Press N/P to select target", True, COLOR_HUD_TEXT_DIM)
            self.screen.blit(no_target, (px + 20, py + 60))

        hint = self.font_small.render("N: next | P: prev | 1-4: action | ESC: close", True, COLOR_MENU_SUBTITLE)
        self.screen.blit(hint, (px + 20, py + ph - 30))

    def _render_battle_result(self):
        overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 80))
        self.screen.blit(overlay, (0, 0))

        text = self.font_title.render(self._battle_result, True, COLOR_WHITE)
        tx = SCREEN_WIDTH // 2 - text.get_width() // 2
        ty = SCREEN_HEIGHT // 2 - text.get_height() // 2
        bg = pygame.Surface((text.get_width() + 20, text.get_height() + 10), pygame.SRCALPHA)
        bg.fill((0, 0, 0, 180))
        self.screen.blit(bg, (tx - 10, ty - 5))
        self.screen.blit(text, (tx, ty))

    def _render_game_over(self):
        overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 150))
        self.screen.blit(overlay, (0, 0))

        color = COLOR_GENERAL_MOVABLE if self._winner == "VICTORY" else (200, 60, 60)
        text = self.font_title.render(self._winner, True, color)
        tx = SCREEN_WIDTH // 2 - text.get_width() // 2
        ty = SCREEN_HEIGHT // 2 - text.get_height() // 2
        self.screen.blit(text, (tx, ty))

        hint = self.font_hud.render("Press ESC to quit", True, COLOR_WHITE)
        self.screen.blit(hint, (SCREEN_WIDTH // 2 - hint.get_width() // 2, ty + 40))
