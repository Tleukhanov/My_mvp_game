<div align="center">

# Tactic Battle

Napoleonic-style top-down 2D tactical battle simulator with RTS controls, A\* pathfinding, type-advantage combat, and modular AI architecture. Built with Python 3 + Pygame.

---

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)
![Pygame](https://img.shields.io/badge/Pygame_CE-2.5-4172B5?style=flat-square&logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCIgZmlsbD0id2hpdGUiPjxwYXRoIGQ9Ik0yMS4yIDEwLjZMMTIuNCAyLjRjLS42LS42LTEuNi0uNi0yLjIgMEwyLjEgMTAuNmMtLjYuNi0uNiAxLjYgMCAyLjJsOC4xIDguMmMuNi42IDEuNi42IDIuMiAwbDguMS04LjJjLjYtLjYuNi0xLjYgMC0yLjJ6TTcuNyAxNC42bC0zLjgtMy44IDMuOC0zLjggMy44IDMuOC0zLjggMy44em01LjYgNS42bC0zLjgtMy44IDMuOC0zLjggMy44IDMuOC0zLjggMy44em0yLjItNS42bC0zLjgtMy44IDMuOC0zLjggMy44IDMuOC0zLjggMy44eiIvPjwvc3ZnPg==&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?style=flat-square&logo=docker&logoColor=white)
![pytest](https://img.shields.io/badge/pytest-62%2F62-0A9EDC?style=flat-square&logo=pytest&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)
![Status](https://img.shields.io/badge/Status-Active-brightgreen?style=flat-square)
![GitHub stars](https://img.shields.io/github/stars/Tleukhanov/My_mvp_game?style=flat-square&logo=github&logoColor=white)
![GitHub forks](https://img.shields.io/github/forks/Tleukhanov/My_mvp_game?style=flat-square&logo=github&logoColor=white)
![GitHub issues](https://img.shields.io/github/issues/Tleukhanov/My_mvp_game?style=flat-square&logo=github&logoColor=white)
![GitHub last commit](https://img.shields.io/github/last-commit/Tleukhanov/My_mvp_game?style=flat-square&logo=git&logoColor=white)
![GitHub code size](https://img.shields.io/github/languages/code-size/Tleukhanov/My_mvp_game?style=flat-square)
![GitHub repo size](https://img.shields.io/github/repo-size/Tleukhanov/My_mvp_game?style=flat-square)
![GitHub language count](https://img.shields.io/github/languages/count/Tleukhanov/My_mvp_game?style=flat-square)
![Linux](https://img.shields.io/badge/Platform-Linux-FCC624?style=flat-square&logo=linux&logoColor=black)
![macOS](https://img.shields.io/badge/Platform-macOS-000000?style=flat-square&logo=apple&logoColor=white)
![Windows](https://img.shields.io/badge/Platform-Windows-0078D4?style=flat-square&logo=windows&logoColor=white)
![Pytest](https://img.shields.io/badge/Testing-62_tests-0A9EDC?style=flat-square&logo=pytest&logoColor=white)
![A*](https://img.shields.io/badge/Pathfinding-A*-FF6B35?style=flat-square)
![AI](https://img.shields.io/badge/AI-State_Machine-9B59B6?style=flat-square)

</div>

---

## Features

### Gameplay
- **RTS Controls** — left-click to select a unit, right-click to issue move or attack orders
- **3 Unit Types** — Infantry (circles), Cavalry (squares), Archers (triangles)
- **Type Advantage System** — Cavalry beats Archers, Archers damage Infantry, Infantry holds against Cavalry
- **Soldier Count** — each unit represents a regiment (500 soldiers), numbers decrease during combat
- **Combat Range** — Archers fire from 5 tiles away, melee units close the distance automatically

### Terrain
- **Mountains** — completely impassable, create natural choke points
- **Rivers** — 5x movement speed penalty, force tactical routing
- **Bridges** — the only way to cross rivers at normal speed
- **Parchment Map** — minimalist historical military map aesthetic with geometric terrain markers

### AI
- **State Machine** — Idle / Move / Attack states with 0.5s decision ticks
- **Auto-Targeting** — Red team finds and engages the nearest Blue unit
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
| AI | Finite State Machine (Idle/Move/Attack/Retreat) |
| Testing | pytest (62 tests) |
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
| **Right Click** | Move selected unit / Attack enemy unit |
| **ESC** | Deselect unit / Quit game |
| **SPACE** | Toggle range indicators on/off |
| **R** | Restart the battle |

---

## Project Structure

```
My_mvp_game/
├── config.py            # Constants, enums, colors, unit stats, combat matrix
├── map.py               # TacticalMap — 40x22 tile grid with terrain generation
├── pathfinding.py       # A* pathfinding with terrain cost awareness
├── units.py             # Unit base class + Infantry, Cavalry, Archer subclasses
├── ai.py                # State-machine AI (UnitAI + AIController)
├── engine.py            # Game loop, event handling, rendering pipeline, HUD
├── main.py              # Entry point
├── requirements.txt     # pygame-ce dependency
├── test_tactics.py      # 62 unit, integration, and edge-case tests
├── Dockerfile           # Docker image (X11 + dummy driver support)
├── docker-compose.yml   # Compose profiles: gui + headless
└── README.md
```

---

## Map Design

The default tactical map features:

```
    LEFT (Blue)          CENTER            RIGHT (Red)
  ┌─────────────┐   ┌──────────┐     ┌─────────────┐
  │  Infantry    │   │ Mountain │     │  Infantry    │
  │  Cavalry     │──▶│ Range    │────▶│  Cavalry     │
  │  Archer      │   │ Bridge   │     │  Archer      │
  └─────────────┘   └──────────┘     └─────────────┘
              River          River
         (5x slow)     (5x slow)
```

- Central mountain range splits the map vertically
- Two rivers with bridges create crossing choke points
- Sparse mountain clusters add tactical cover on flanks

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
# Run all 62 tests
python -m pytest test_tactics.py -v

# Test categories:
# - TestConfig (10)          — constants, enums, combat matrix
# - TestTacticalMap (11)     — terrain grid, bounds, passability
# - TestPathfinding (8)      — A* routing, obstacles, bridges
# - TestUnit (15)            — creation, damage, combat, rendering
# - TestAI (7)               — state machine, targeting, retreat
# - TestIntegration (4)      — full-scene rendering, multi-unit
# - TestEdgeCases (5)        — boundary conditions, overkill
```

---

## Architecture for Extension

### Adding a New Unit Type
1. Add enum value in `config.py` → `UnitType`
2. Add stats in `config.py` → `UNIT_STATS`
3. Add advantage entries in `config.py` → `COMBAT_ADVANTAGE`
4. Add shape renderer in `units.py` → `Unit._render_*`

### Adding a New Map
1. Create grid in `map.py` using `TerrainType` enum
2. Pass grid to `TacticalMap(grid)` constructor
3. Pathfinding and terrain costs adapt automatically

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

## Roadmap

| Priority | Feature | Description |
|---|---|---|
| High | **Scrolling Camera** | Pan and zoom for larger maps |
| High | **Unit Formations** | Group selection and formation movement |
| Medium | **Fog of War** | Limited visibility per unit type |
| Medium | **Morale System** | Units rout after taking heavy casualties |
| Medium | **New Unit Types** | Artillery, Dragoons, Light Infantry |
| Medium | **Campaign Mode** | Multi-battle progression with persistent armies |
| Low | **ML AI Agent** | Reinforcement learning opponent via `AIController` interface |
| Low | **Multiplayer** | Network multiplayer with turn-based or real-time modes |
| Low | **Sound Effects** | March, cannon fire, bugle calls |

---

## Author

- **Developer:** Tleukhanov Yeraly
- **Focus:** Game Development, Python, AI Systems
- **GitHub:** [@Tleukhanov](https://github.com/Tleukhanov)

---

<div align="center">

Made with Python and Pygame

</div>
