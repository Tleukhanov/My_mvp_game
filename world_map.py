import pygame
import sys
import math
import random
from typing import Optional, List, Tuple
from world_data import (
    SCREEN_WIDTH, SCREEN_HEIGHT,
    COLOR_OCEAN, COLOR_OCEAN_LIGHT, COLOR_LAND, COLOR_RIVER,
    COLOR_BRIDGE, COLOR_NEUTRAL, COLOR_PROVINCE_BORDER,
    COLOR_HUD_BG, COLOR_HUD_TEXT, COLOR_HUD_TEXT_DIM,
    COLOR_WHITE, COLOR_BLACK,
    COLOR_GENERAL_SELECTED, COLOR_GENERAL_MOVABLE, COLOR_GENERAL_DONE,
    WORLD_NATIONS, WORLD_PROVINCES, PLAYER_NATION, WORLD_GENERALS,
    RegionType, Province, General,
    PROVINCE_CONNECTIONS, BRIDGE_CONNECTIONS,
    RIVER_WEST_X, RIVER_EAST_X,
)
from diplomacy import DiplomacyManager, Relation
from textures import TextureManager, GeneralIcon, RiverRenderer


class WorldMapScreen:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("Tactic Battle - World Map")
        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        self.clock = pygame.time.Clock()
        self.running = True

        self.font_hud = pygame.font.SysFont(None, 16)
        self.font_title = pygame.font.SysFont(None, 24, bold=True)
        self.font_small = pygame.font.SysFont(None, 12)
        self.font_region = pygame.font.SysFont(None, 11)
        self.font_troops = pygame.font.SysFont(None, 14, bold=True)

        self.cam_x = 0
        self.cam_y = 0
        self._scroll_speed = 400
        self._dragging = False
        self._drag_start = (0, 0)
        self._cam_start = (0, 0)
        self._keys_held = set()

        self.diplomacy = DiplomacyManager()
        self.provinces: List[Province] = [Province(p.name, p.owner, p.region_type,
                                                    list(p.polygon), list(p.neighbors))
                                           for p in WORLD_PROVINCES]
        self.generals: List[General] = [General(g.name, g.nation, g.province_idx, g.troops)
                                         for g in WORLD_GENERALS]
        for orig, copy in zip(WORLD_GENERALS, self.generals):
            copy.health = orig.health

        self.connections: List[Tuple[int, int]] = list(PROVINCE_CONNECTIONS)
        self._build_connection_index()

        self.selected_general: Optional[General] = None
        self._turn = 1
        self._show_diplomacy = False
        self._diplomacy_target: Optional[str] = None
        self._battle_result: Optional[str] = None
        self._battle_timer = 0.0
        self._game_over = False
        self._winner: Optional[str] = None
        self._message: Optional[str] = None
        self._message_timer = 0.0

        self.tex_manager = TextureManager()
        self._build_province_offsets()

    def _build_connection_index(self):
        self._conn_by_province = {}
        for a, b in self.connections:
            self._conn_by_province.setdefault(a, set()).add(b)
            self._conn_by_province.setdefault(b, set()).add(a)

    def _build_province_offsets(self):
        self._prov_offsets = []
        for prov in self.provinces:
            poly = prov.polygon
            min_x = min(p[0] for p in poly)
            min_y = min(p[1] for p in poly)
            self._prov_offsets.append((min_x, min_y))

    def _adjacent_provinces(self, idx: int) -> List[int]:
        return list(self._conn_by_province.get(idx, set()))

    def _clamp_camera(self):
        map_w = SCREEN_WIDTH
        map_h = SCREEN_HEIGHT - 80
        self.cam_x = max(0, min(self.cam_x, map_w - SCREEN_WIDTH))
        self.cam_y = max(0, min(self.cam_y, map_h - (SCREEN_HEIGHT - 80)))

    def _screen_to_world(self, sx: int, sy: int) -> Tuple[int, int]:
        return sx + self.cam_x, sy + self.cam_y

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
                self._keys_held.add(event.key)
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
                elif event.key == pygame.K_TAB:
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

            elif event.type == pygame.KEYUP:
                self._keys_held.discard(event.key)

            elif event.type == pygame.MOUSEWHEEL:
                self.cam_y -= event.y * 40
                self._clamp_camera()

            elif event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 2:
                    self._dragging = True
                    self._drag_start = event.pos
                    self._cam_start = (self.cam_x, self.cam_y)
                elif event.button == 1:
                    mx, my = event.pos
                    if my < SCREEN_HEIGHT - 80:
                        self._handle_map_click(mx, my)

            elif event.type == pygame.MOUSEBUTTONUP:
                if event.button == 2:
                    self._dragging = False

            elif event.type == pygame.MOUSEMOTION:
                if self._dragging:
                    dx = event.pos[0] - self._drag_start[0]
                    dy = event.pos[1] - self._drag_start[1]
                    self.cam_x = self._cam_start[0] - dx
                    self.cam_y = self._cam_start[1] - dy
                    self._clamp_camera()

    def _handle_map_click(self, mx: int, my: int):
        if my >= SCREEN_HEIGHT - 80:
            return

        wx, wy = self._screen_to_world(mx, my)

        clicked_province = None
        for i, prov in enumerate(self.provinces):
            if prov.contains_point(wx, wy):
                clicked_province = i
                break

        if self.selected_general:
            g = self.selected_general
            g_prov = g.province_idx

            if clicked_province is not None and clicked_province != g_prov:
                adj = self._adjacent_provinces(g_prov)
                if clicked_province in adj:
                    self._move_general_to_province(g, clicked_province)
                    self.selected_general = None
                    return

            if clicked_province is not None:
                for gen in self.generals:
                    if gen.nation == PLAYER_NATION and not gen.moved:
                        if gen.province_idx == clicked_province:
                            self.selected_general = gen
                            return
            self.selected_general = None
        else:
            if clicked_province is not None:
                for gen in self.generals:
                    if gen.nation == PLAYER_NATION and not gen.moved:
                        if gen.province_idx == clicked_province:
                            self.selected_general = gen
                            return

    def _move_general_to_province(self, general: General, target_idx: int):
        target = self.provinces[target_idx]

        for other in self.generals:
            if other is not general and other.province_idx == target_idx:
                if self.diplomacy.is_enemy(general.nation, other.nation):
                    self._start_battle(general, other)
                    general.moved = True
                    return
                elif general.nation != other.nation:
                    rel = self.diplomacy.get_relation(general.nation, other.nation)
                    if rel in (Relation.FRIENDLY, Relation.ALLIANCE):
                        other.troops += general.troops
                        self.generals.remove(general)
                        general.moved = True
                        self._show_msg("Армии объединены!")
                        return
                    else:
                        self._show_msg("Нельзя войти на чужую территорию!")
                        return

        if target.owner == "neutral":
            target.owner = general.nation
            general.province_idx = target_idx
            general.moved = True
            self._show_msg(f"{target.name} захвачена!")
        elif target.owner == general.nation:
            target.troops += general.troops // 10
            general.province_idx = target_idx
            general.moved = True
        else:
            rel = self.diplomacy.get_relation(general.nation, target.owner)
            if rel == Relation.WAR:
                if target.troops <= 0:
                    target.owner = general.nation
                    target.troops = 0
                    general.province_idx = target_idx
                    general.moved = True
                    self._show_msg(f"{target.name} захвачена!")
                else:
                    self._start_battle_with_region(general, target)
                    general.moved = True
            else:
                self._show_msg("Нельзя войти на чужую территорию!")
                return

    def _start_battle(self, attacker: General, defender: General):
        a_power = attacker.troops * (attacker.health / 100)
        d_power = defender.troops * (defender.health / 100)
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
                self._battle_result = f"{attacker.name} отбит, потеряно {losses}"
            defender.health = max(0, defender.health - 20)
        else:
            losses = int(attacker.troops * 0.5)
            attacker.troops = max(0, attacker.troops - losses)
            if attacker.troops <= 0:
                self.generals.remove(attacker)
                self._battle_result = f"{defender.name} уничтожил {attacker.name}!"
            else:
                self._battle_result = f"{attacker.name} отступил, потеряно {losses}"
        self._battle_timer = 3.0

    def _start_battle_with_region(self, general: General, region: Province):
        a_power = general.troops * (general.health / 100)
        d_power = region.troops
        a_roll = a_power * random.uniform(0.7, 1.3)
        d_roll = d_power * random.uniform(0.7, 1.3)

        if a_roll > d_roll:
            losses = int(general.troops * 0.2)
            general.troops = max(100, general.troops - losses)
            region.owner = general.nation
            region.troops = 0
            general.province_idx = self.provinces.index(region)
            self._battle_result = f"{general.name} захватил {region.name}!"
        else:
            losses = int(general.troops * 0.4)
            general.troops = max(0, general.troops - losses)
            region.troops = max(0, region.troops - int(region.troops * 0.3))
            self._battle_result = f"{general.name} отбит от {region.name}!"
        self._battle_timer = 3.0

    def _show_msg(self, msg: str):
        self._message = msg
        self._message_timer = 2.0

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
        self._show_msg(msg)

    def _end_turn(self):
        self._turn += 1
        for g in self.generals:
            g.moved = False
        self._ai_turn()

    def _ai_turn(self):
        for g in self.generals:
            if g.nation != PLAYER_NATION and not g.moved:
                self._ai_move_general(g)

    def _ai_move_general(self, general: General):
        g_idx = general.province_idx

        enemies = []
        for e in self.generals:
            if e.nation != general.nation and self.diplomacy.is_enemy(general.nation, e.nation):
                enemies.append(e)

        if enemies:
            nearest = min(enemies, key=lambda e: general.distance_to(e))
            if general.distance_to(nearest) <= 200:
                for adj in self._adjacent_provinces(g_idx):
                    for e in self.generals:
                        if e is nearest and e.province_idx == adj:
                            self._move_general_to_province(general, adj)
                            general.moved = True
                            return

        neutral_targets = []
        for adj in self._adjacent_provinces(g_idx):
            if self.provinces[adj].owner == "neutral":
                neutral_targets.append(adj)

        if neutral_targets:
            target_idx = random.choice(neutral_targets)
            self._move_general_to_province(general, target_idx)
            general.moved = True
            return

        for adj in self._adjacent_provinces(g_idx):
            prov = self.provinces[adj]
            if prov.owner != general.nation and prov.owner != "neutral":
                rel = self.diplomacy.get_relation(general.nation, prov.owner)
                if rel == Relation.WAR and prov.troops <= 0:
                    self._move_general_to_province(general, adj)
                    general.moved = True
                    return

    def _update(self, dt: float):
        if not self._show_diplomacy:
            scroll = self._scroll_speed * dt
            if pygame.K_w in self._keys_held or pygame.K_UP in self._keys_held:
                self.cam_y -= scroll
            if pygame.K_s in self._keys_held or pygame.K_DOWN in self._keys_held:
                self.cam_y += scroll
            if pygame.K_a in self._keys_held or pygame.K_LEFT in self._keys_held:
                self.cam_x -= scroll
            if pygame.K_d in self._keys_held or pygame.K_RIGHT in self._keys_held:
                self.cam_x += scroll
            self._clamp_camera()

        if self._battle_timer > 0:
            self._battle_timer -= dt
            if self._battle_timer <= 0:
                self._battle_result = None

        if self._message_timer > 0:
            self._message_timer -= dt
            if self._message_timer <= 0:
                self._message = None

        blue_alive = any(g.nation == PLAYER_NATION for g in self.generals)
        other_alive = [g for g in self.generals if g.nation != PLAYER_NATION]
        if not blue_alive and other_alive:
            self._game_over = True
            self._winner = "DEFEAT"
        elif blue_alive and not other_alive:
            self._game_over = True
            self._winner = "VICTORY"

    def _render(self):
        ocean = self.tex_manager.get_ocean_texture(SCREEN_WIDTH, SCREEN_HEIGHT - 80)
        self.screen.blit(ocean, (0, 0))

        for i, prov in enumerate(self.provinces):
            min_x, min_y = self._prov_offsets[i]
            tex = self.tex_manager.get_province_texture(
                i, prov.polygon, prov.owner, prov.region_type,
                SCREEN_WIDTH, SCREEN_HEIGHT
            )
            sx = min_x - self.cam_x - 4
            sy = min_y - self.cam_y - 4
            self.screen.blit(tex, (sx, sy))

            screen_poly = [(x - self.cam_x, y - self.cam_y) for x, y in prov.polygon]
            pygame.draw.polygon(self.screen, COLOR_PROVINCE_BORDER, screen_poly, 1)

        self._render_rivers()

        for general in self.generals:
            self._render_general(general)

        if self.selected_general:
            g_idx = self.selected_general.province_idx
            adj = self._adjacent_provinces(g_idx)
            for ai in adj:
                prov = self.provinces[ai]
                cx, cy = prov.centroid
                sx = cx - self.cam_x
                sy = cy - self.cam_y
                pulse = abs(math.sin(pygame.time.get_ticks() * 0.004)) * 0.4 + 0.6
                col = (int(255 * pulse), int(255 * pulse), int(80 * pulse))
                pygame.draw.circle(self.screen, col, (sx, sy), 22, 2)

        self._render_hud()

        if self._show_diplomacy:
            self._render_diplomacy_panel()

        if self._battle_result:
            self._render_overlay_text(self._battle_result)

        if self._message:
            self._render_overlay_text(self._message)

        if self._game_over:
            self._render_game_over()

        pygame.display.flip()

    def _render_rivers(self):
        t = pygame.time.get_ticks()

        for river_x in [RIVER_WEST_X, RIVER_EAST_X]:
            RiverRenderer.draw_river(self.screen, river_x, self.cam_x, self.cam_y,
                                     SCREEN_HEIGHT, t)

            bridge_indices = []
            for a, b in BRIDGE_CONNECTIONS:
                pa = self.provinces[a]
                pb = self.provinces[b]
                cx_a, cy_a = pa.centroid
                cx_b, cy_b = pb.centroid
                if abs(cx_a - river_x) < 30 or abs(cx_b - river_x) < 30:
                    bridge_y = (cy_a + cy_b) // 2
                    bridge_indices.append(bridge_y)

            for by in bridge_indices:
                RiverRenderer.draw_bridge(self.screen, river_x, by, self.cam_x, self.cam_y)

    def _render_general(self, general: General):
        prov = self.provinces[general.province_idx]
        cx, cy = prov.centroid
        x = cx - self.cam_x
        y = cy - self.cam_y

        if x < -30 or x > SCREEN_WIDTH + 30 or y < -30 or y > SCREEN_HEIGHT + 30:
            return

        nation = WORLD_NATIONS.get(general.nation)
        color = nation.color if nation else (150, 150, 150)

        is_selected = general is self.selected_general
        GeneralIcon.draw_shield(self.screen, int(x), int(y), color,
                                selected=is_selected, moved=general.moved)

        label = self.font_region.render(f"{general.name[:6]}({general.troops})", True, COLOR_WHITE)
        lx = int(x) - label.get_width() // 2
        ly = int(y) - 24
        bg = pygame.Surface((label.get_width() + 4, label.get_height() + 2), pygame.SRCALPHA)
        bg.fill((0, 0, 0, 160))
        self.screen.blit(bg, (lx - 2, ly - 1))
        self.screen.blit(label, (lx, ly))

    def _render_hud(self):
        hud_y = SCREEN_HEIGHT - 80
        pygame.draw.rect(self.screen, COLOR_HUD_BG, (0, hud_y, SCREEN_WIDTH, 80))

        turn_text = self.font_hud.render(
            f"Turn: {self._turn} | SPACE: End Turn | TAB: Diplomacy | WASD/Arrows: Scroll | ESC: Menu",
            True, COLOR_HUD_TEXT
        )
        self.screen.blit(turn_text, (12, hud_y + 4))

        nation = WORLD_NATIONS[PLAYER_NATION]
        info = self.font_hud.render(
            f"{nation.name} | Gold: {nation.gold}",
            True, nation.color
        )
        self.screen.blit(info, (12, hud_y + 22))

        generals_info = [f"{g.name}({g.troops})" for g in self.generals
                         if g.nation == PLAYER_NATION]
        gen_text = self.font_hud.render(
            f"Generals: {', '.join(generals_info)}",
            True, COLOR_HUD_TEXT_DIM
        )
        self.screen.blit(gen_text, (12, hud_y + 40))

        provinces_count = {}
        for p in self.provinces:
            provinces_count[p.owner] = provinces_count.get(p.owner, 0) + 1
        rx = SCREEN_WIDTH - 12
        for nation_key in ["red", "blue", "green"]:
            count = provinces_count.get(nation_key, 0)
            n = WORLD_NATIONS[nation_key]
            rt = self.font_hud.render(f"{n.name}: {count}", True, n.color)
            rx -= rt.get_width() + 16
            self.screen.blit(rt, (rx, hud_y + 4))

        if self.selected_general:
            sel = self.selected_general
            adj = self._adjacent_provinces(sel.province_idx)
            adj_names = [self.provinces[i].name[:8] for i in adj[:5]]
            sel_text = self.font_hud.render(
                f"Selected: {sel.name} | Adjacent: {', '.join(adj_names)}",
                True, COLOR_GENERAL_SELECTED
            )
            self.screen.blit(sel_text, (SCREEN_WIDTH // 2 - sel_text.get_width() // 2, hud_y + 60))

    def _render_diplomacy_panel(self):
        overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 120))
        self.screen.blit(overlay, (0, 0))

        pw, ph = 450, 320
        px = SCREEN_WIDTH // 2 - pw // 2
        py = SCREEN_HEIGHT // 2 - ph // 2
        pygame.draw.rect(self.screen, (40, 35, 30), (px, py, pw, ph), border_radius=8)
        pygame.draw.rect(self.screen, COLOR_WHITE, (px, py, pw, ph), 2, border_radius=8)

        title = self.font_title.render("DIPLOMACY", True, (220, 200, 160))
        self.screen.blit(title, (px + pw // 2 - title.get_width() // 2, py + 10))

        if self._diplomacy_target:
            target_nation = WORLD_NATIONS[self._diplomacy_target]
            current = self.diplomacy.get_relation(PLAYER_NATION, self._diplomacy_target)
            rel_name = self.diplomacy.get_relation_name(PLAYER_NATION, self._diplomacy_target)
            rel_color = self.diplomacy.get_relation_color(PLAYER_NATION, self._diplomacy_target)

            target_text = self.font_hud.render(
                f"Target: {target_nation.name}", True, target_nation.color
            )
            self.screen.blit(target_text, (px + 20, py + 45))

            current_text = self.font_hud.render(
                f"Current: {rel_name}", True, rel_color
            )
            self.screen.blit(current_text, (px + 20, py + 68))

            actions = [
                ("1", "Declare WAR", (200, 60, 60)),
                ("2", "Propose NEUTRAL", (180, 170, 150)),
                ("3", "Propose FRIENDLY", (80, 180, 80)),
                ("4", "Propose ALLIANCE", (60, 120, 220)),
            ]
            for i, (key, text, color) in enumerate(actions):
                ay = py + 100 + i * 32
                key_text = self.font_hud.render(f"[{key}]", True, COLOR_HUD_TEXT_DIM)
                act_text = self.font_hud.render(text, True, color)
                self.screen.blit(key_text, (px + 30, ay))
                self.screen.blit(act_text, (px + 70, ay))
        else:
            no_target = self.font_hud.render("Press N/P to select target", True, COLOR_HUD_TEXT_DIM)
            self.screen.blit(no_target, (px + 20, py + 55))

        hint = self.font_small.render("N: next | P: prev | 1-4: action | ESC: close", True, (170, 155, 130))
        self.screen.blit(hint, (px + 20, py + ph - 25))

    def _render_overlay_text(self, text: str):
        overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 80))
        self.screen.blit(overlay, (0, 0))

        rendered = self.font_title.render(text, True, COLOR_WHITE)
        tx = SCREEN_WIDTH // 2 - rendered.get_width() // 2
        ty = 30
        bg = pygame.Surface((rendered.get_width() + 20, rendered.get_height() + 10), pygame.SRCALPHA)
        bg.fill((0, 0, 0, 180))
        self.screen.blit(bg, (tx - 10, ty - 5))
        self.screen.blit(rendered, (tx, ty))

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
