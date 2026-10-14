# AGENTS.md

Shared instructions for every AI assistant used in this repo (Claude Code, Codex, Copilot, Cursor, Gemini, …). Keep this file short and current. `CLAUDE.md` only imports it.

## What this project is

This is a uni project for the Master's course *Machine Learning* (Hochschule Hannover). Automated **OpenFOAM** CFD simulations of *Stoßlüften* (window ventilation) in one room with two windows produce a CSV dataset. An **ML surrogate model** will be trained on it later.

- **Current phase: data generation** (the CFD pipeline). The ML part will be planned later.
- [PLAN.md](PLAN.md) holds the agreed decisions, dataset columns and schedule. **Read it first.**
- [VENTILATION_CFD_PROJECT.md](VENTILATION_CFD_PROJECT.md) is the original background spec. PLAN.md wins wherever they differ.
- Status: the geometry and mesh generator works. The CFD case setup is next. Deadline: less than 6 weeks from 2026-10-14.

## Environment

- CFD runs only on Daniel's Arch Linux PC. It uses a native OpenFOAM v2606 (openfoam.com, AUR `openfoam-com`, no Docker), ParaView, and a Python venv with the Gmsh API.
- Teammates use Windows, macOS or Linux and have little programming experience. They don't run CFD; they work with the CSV results.

## Rules for AI assistants

1. **Log your work in [log.md](log.md) before you finish a task.** Append an entry using the template at the top of that file: who, which tool/model, what the AI did, and what the humans decided. Verbatim prompts are not needed. The course requires this log.
2. Write simple, readable code. Explain CFD and physics choices in brief comments, and tell the user exactly how to run what you built.
3. Don't silently change the decisions in PLAN.md or, once they are frozen, the CSV columns, because they are the ML dataset contract. Propose the change, and update PLAN.md once the team agrees.
4. Never commit generated case folders (`cases/`). Do commit the dataset CSVs (`results/`).
5. The CFD pipeline may assume Linux with OpenFOAM sourced. Anything teammates run must work on any OS.
6. When you add commands or folders, update the two sections below.
7. **Keep [README.md](README.md) up to date.** Whenever the status, setup, commands or folders change, update it in the same commit. It is written for teammates, so keep it plain and short.

## Commands

One-time setup on the Linux CFD machine:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

Each shell session:

```bash
source .venv/bin/activate
of    # loads OpenFOAM v2606 (alias from the AUR package); needed before any OpenFOAM command
```

Working now:

```bash
python -m pytest                                              # all tests (~10 s)
python -m pytest tests/test_windows.py -k collide             # a single test
python -m geometry.generate --config configs/default.yaml     # geometry + mesh -> cases/default/mesh.msh
python -m geometry.generate --config configs/default.yaml --no-mesh --gui   # Gmsh wireframe view
python -m geometry.render configs/examples/*.yaml --out docs/images/layouts.png   # README picture
```

Not implemented yet (PLAN.md §4):

```bash
python -m cfd.run_case --config configs/default.yaml
python -m sweeps.run_sweep --config configs/sweeps/screening.yaml
```

- Gmsh meshes must be written in MSH 2.2 format (`Mesh.MshFileVersion = 2.2`) for `gmshToFoam`.
- In ParaView, use its built-in OpenFOAM reader. The AUR package's reader plugin does not build.

## Structure

- `configs/default.yaml` is one complete case. Every key is required, and `cfd/config.py` loads and validates it. Invalid values raise `ConfigError` with a clear message.
- `geometry/windows.py` holds the wall frames, sash positions and the overlap/collision checks. It uses plain numpy, without Gmsh.
- `geometry/generate.py` builds the Gmsh OpenCASCADE model as a single `fluid` volume. It sorts boundary surfaces into patches (`inlet outlet sides top ground building room_walls sashes`) by their position, sets the mesh size fields, and writes the mesh in MSH 2.2.
- `geometry/render.py` makes off-screen PyVista renders of that same Gmsh geometry, shown as a cut-away view with the roof removed. Several configs can be shown side by side.
- `configs/examples/` holds one example case per layout. They are used for the README picture.
- `tests/`: pytest.
- `docs/images/` holds the images used in README.md. Re-render them when the geometry or the examples change.

The rest of the planned layout is in spec §7.
