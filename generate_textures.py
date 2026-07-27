import pygame
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

pygame.init()

from textures import TextureManager, GeneralIcon, RiverRenderer
from world_data import WORLD_PROVINCES, SCREEN_WIDTH, SCREEN_HEIGHT

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "assets")
os.makedirs(OUTPUT_DIR, exist_ok=True)

tex = TextureManager()

for i, prov in enumerate(WORLD_PROVINCES):
    min_x = min(p[0] for p in prov.polygon)
    min_y = min(p[1] for p in prov.polygon)
    max_x = max(p[0] for p in prov.polygon)
    max_y = max(p[1] for p in prov.polygon)
    w = max_x - min_x + 8
    h = max_y - min_y + 8
    if w <= 0 or h <= 0:
        continue
    surf = pygame.Surface((w, h))
    surf.fill((40, 70, 120))
    tex_surf = tex.get_province_texture(i, prov.polygon, prov.owner, prov.region_type, SCREEN_WIDTH, SCREEN_HEIGHT)
    surf.blit(tex_surf, (0, 0))
    safe_name = prov.name.replace(" ", "_").lower()
    pygame.image.save(surf, os.path.join(OUTPUT_DIR, f"prov_{i:02d}_{safe_name}.png"))
    print(f"  Saved prov_{i:02d}_{safe_name}.png ({w}x{h})")

icon_surf = pygame.Surface((40, 40), pygame.SRCALPHA)
GeneralIcon.draw_shield(icon_surf, 20, 20, (50, 80, 160), selected=False, moved=False)
pygame.image.save(icon_surf, os.path.join(OUTPUT_DIR, "icon_shield_blue.png"))
GeneralIcon.draw_shield(icon_surf, 20, 20, (170, 45, 40), selected=True, moved=False)
pygame.image.save(icon_surf, os.path.join(OUTPUT_DIR, "icon_shield_red_selected.png"))
GeneralIcon.draw_shield(icon_surf, 20, 20, (50, 130, 70), selected=False, moved=True)
pygame.image.save(icon_surf, os.path.join(OUTPUT_DIR, "icon_shield_green_moved.png"))
print("  Saved general icons")

ocean_surf = tex.get_ocean_texture(256, 256)
pygame.image.save(ocean_surf, os.path.join(OUTPUT_DIR, "ocean_tile.png"))
print("  Saved ocean_tile.png")

print(f"\nAll textures saved to {OUTPUT_DIR}/")
pygame.quit()
