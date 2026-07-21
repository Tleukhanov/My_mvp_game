<div align="center">

# Tactic Battle

Napoleonic-style top-down 2D tactical battle simulator with RTS controls, A\* pathfinding, type-advantage combat, village capture, and modular AI architecture. Built with Python 3 + Pygame.

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)
![Pygame](https://img.shields.io/badge/Pygame_CE-2.5-4172B5)
![Docker](https://img.shields.io/badge/Docker-2496ED?logo=docker&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)

</div>

---

## Features

### Game Modes
- **Main Menu** — stylish launch screen with mode selection
- **Skirmish** — quick battle on the default tactical map
- **Campaign** — 4 handcrafted missions with unique terrain and objectives
- **Online** — planned (placeholder)

### Campaign Missions
1. **Битва у моста** — defend/attack a strategic bridge crossing over a river with mountain flanks
2. **Ущелье смерти** — navigate through a narrow mountain canyon with chokepoints
3. **Речная крепость** — assault an enemy fortress behind a river and mountain defenses
4. **Деревни** — capture and hold 6 villages to build an economic advantage

### Gameplay
- **Multi-Select** — select up to 6 units with Shift+click, box drag, or `A` to select all
- **RTS Controls** — left-click to select, right-click to move or attack
- **3 Unit Types** — Infantry (circles), Cavalry (squares), Archers (triangles)
- **Type Advantage System** — Cavalry beats Archers, Archers damage Infantry, Infantry holds against Cavalry
- **Soldier Count** — each unit represents a regiment (500 soldiers), numbers decrease during combat
- **Combat Range** — Archers fire from 5 tiles away, melee units close the distance automatically
- **Unit Collision** — units cannot overlap, they push apart and pathfind around each other

### Village Capture System
- **Capture** — move a unit onto a village to capture it for your team
- **Food Economy** — each captured village produces 20 food/sec, each unit consumes 5 food/sec
- **Recruit** — every 3 minutes a free Infantry spawns at a captured village
- **Max Food** — supply is capped at 1000 food

### Terrain
- **Grass Plains** — multiple green tones with procedural grass blades and flowers
- **Mountains** — impassable with 3D peak shading and shadows
- **Rivers** — animated flowing water with highlights, waves and depth
- **Bridges** — the only way to cross rivers at normal speed
- **Villages** — capturable buildings that produce food and spawn units

### AI
- **Village Capture** — AI prioritizes capturing neutral/enemy villages
- **Proactive Aggression** — enemies advance toward you from the start
- **A\* Pathfinding Chase** — AI units navigate around terrain when pursuing targets
- **State Machine** — Idle / Move / Attack / Capture / Retreat states
- **Retreat Logic** — units flee when below 20% health
- **Modular Design** — swap the AI controller with an ML agent via the `AIController` interface

### Architecture
- **A\* Pathfinding** — respects terrain costs, diagonal movement, mountain avoidance
- **MVC Separation** — config, map, units, AI, engine, pathfinding are independent modules
- **Extensible** — add new unit types, maps, game modes, or ML agents by swapping single files

---

## Tech Stack

| Category | Technology |
|---|---|
| Language | Python 3.10+ |
| Graphics | Pygame-CE 2.5 |
| Pathfinding | A\* with terrain cost weighting |
| AI | Finite State Machine (Idle/Move/Attack/Capture/Retreat) |
| Testing | pytest (93 tests) |
| Container | Docker + docker-compose |

---

## Quick Start

### Local (recommended for play)
```bash
git clone https://github.com/Tleukhanov/My_mvp_game.git
cd My_mvp_game
pip install pygame-ce
python main.py
```

### Docker
```bash
git clone https://github.com/Tleukhanov/My_mvp_game.git
cd My_mvp_game

# Linux (X11 forwarding)
xhost +local:docker
docker compose --profile gui up --build

# Headless (CI / testing)
docker compose --profile headless up --build
```

---

## Controls

| Key | Action |
|---|---|
| **Left Click** | Select a Blue unit |
| **Shift + Left Click** | Add unit to selection (up to 6) |
| **Drag (Left Mouse)** | Box-select multiple units |
| **A** | Select all friendly units |
| **Right Click** | Move selected units / Attack enemy unit |
| **ESC** | Deselect unit / Quit game |
| **SPACE** | Toggle range indicators on/off |
| **R** | Restart the battle |

---

## Project Structure

```
My_mvp_game/
├── config.py            # Constants, enums, colors, unit stats, combat matrix
├── map.py               # TacticalMap — tile grid with terrain generation and villages
├── pathfinding.py       # A* pathfinding with terrain cost awareness
├── units.py             # Unit class with collision, pathfinder, combat
├── ai.py                # State-machine AI (UnitAI + AIController) with village capture
├── engine.py            # Game loop, multi-select, food system, village capture, HUD
├── main.py              # Entry point with menu
├── menu.py              # Main menu + campaign selection screens
├── campaigns.py         # 4 campaign mission definitions and maps
├── requirements.txt     # pygame-ce dependency
├── test_tactics.py      # 93 unit, integration, and edge-case tests
├── Dockerfile           # Docker image (X11 + dummy driver support)
├── docker-compose.yml   # Compose profiles: gui + headless
└── README.md
```

---

## Unit Stats

| Type | Shape | HP | Speed | Damage | Range | Advantage |
|---|---|---|---|---|---|---|
| Infantry | Circle | 500 | 1.8 | 8 | 1.2 tiles | Balanced |
| Cavalry | Square | 350 | 3.2 | 14 | 1.4 tiles | Beats Archers (1.5x) |
| Archer | Triangle | 280 | 1.5 | 6 | 5.0 tiles | Deals damage from range |

---

## Testing

```bash
# Run all 93 tests
python -m pytest test_tactics.py -v

# Test categories:
# - TestConfig (9)              — constants, enums, combat matrix, food constants
# - TestTacticalMap (13)        — terrain grid, bounds, passability, grass rendering
# - TestVillages (8)            — village ownership, passability, rendering
# - TestPathfinding (6)         — A* routing, obstacles, bridges, villages
# - TestUnit (17)               — creation, damage, combat, rendering
# - TestUnitCollision (5)       — unit separation, overlap prevention
# - TestAI (9)                  — state machine, targeting, village capture
# - TestCampaigns (12)          — mission validation, village placement, map generation
# - TestFoodSystem (3)          — food cap, consumption, production
# - TestIntegration (6)         — full-scene, multi-unit, AI engagement, village capture
# - TestEdgeCases (5)           — boundary conditions, overkill
```

---

## Architecture for Extension

### Adding a New Unit Type
1. Add enum value in `config.py` → `UnitType`
2. Add stats in `config.py` → `UNIT_STATS`
3. Add advantage entries in `config.py` → `COMBAT_ADVANTAGE`
4. Add shape renderer in `units.py` → `Unit._render_*`

### Adding a New Campaign
1. Create a `get_mission_N()` function in `campaigns.py`
2. Define the grid, blue_units, red_units, village_positions
3. Add to `MISSIONS` dict in `campaigns.py`
4. Engine auto-loads it when `mission=N` is passed

### Swapping AI with ML Agent
```python
# Replace AIController.update() with your ML inference:
class MLController:
    def __init__(self, model_path):
        self.model = load_model(model_path)

    def update(self, dt, enemies):
        for unit in self.red_units:
            action = self.model.predict(unit, enemies)
            unit.set_move_path(action.path)  # or set_attack_target()
```

---

## Docker Configuration

The `Dockerfile` supports two modes:

| Mode | Env Variable | Use Case |
|---|---|---|
| `SDL_VIDEODRIVER=dummy` | Headless | CI testing, no display needed |
| `DISPLAY=:0` | GUI | X11 forwarding, actual gameplay |

### Platform-Specific GUI Setup

| Platform | Steps |
|---|---|
| **Linux** | `xhost +local:docker` then `docker compose --profile gui up --build` |
| **macOS** | Install XQuartz, open it, `xhost +local:docker`, same compose command |
| **Windows** | Install VcXsrv, set `DISPLAY` to host IP, same compose command |

---

## Author

- **Developer:** Tleukhanov Yeraly
- **Focus:** Game Development, Python, AI Systems
- **GitHub:** [@Tleukhanov](https://github.com/Tleukhanov)

---

<div align="center">

Made with Python and Pygame

</div>
