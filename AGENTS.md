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
7. Start simulations that take longer than a few minutes detached: `setsid nohup <command> > <log> 2>&1 &`. Processes started from an editor or agent session die when that session closes.
8. **Keep [README.md](README.md) up to date.** Whenever the status, setup, commands or folders change, update it in the same commit. It is written for teammates, so keep it plain and short.

## Commands

One-time setup on the Linux CFD machine:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

Each shell session:

```bash
source .venv/bin/activate
of    # loads OpenFOAM v2606 (alias from the AUR package); needed before any OpenFOAM command
      # in non-login shells (and for agents) use: source /opt/OpenFOAM/OpenFOAM-v2606/etc/bashrc
```

Working now:

```bash
python -m pytest                                              # all tests (~10 s)
python -m pytest tests/test_windows.py -k collide             # a single test
python -m geometry.generate --config configs/default.yaml     # geometry + mesh -> cases/default/mesh.msh
python -m geometry.generate --config configs/default.yaml --no-mesh --gui   # Gmsh wireframe view
python -m geometry.render configs/examples/*.yaml --out docs/images/layouts.png   # README picture
python -m cfd.run_case --config configs/default.yaml          # mesh + steady flow + tracer -> cases/default/ (needs OpenFOAM)
python -m cfd.run_case --config configs/default.yaml --tracer-only   # rerun the tracer on the existing flow
python -m analysis.visualize --config configs/default.yaml --kind flow|tracer|curve --out <png>
python -m cfd.run_case --config configs/benchmark/same_wall.yaml --transient --procs 4   # option B comparison run (hours)
python -m cfd.run_case --config configs/benchmark/same_wall.yaml --transient --resume   # continue it after an interruption
python -m analysis.monitor                                    # live progress window (--once <png> for a snapshot)
```

Not implemented yet (PLAN.md §4): the transient comparison run (benchmark option B) and `python -m sweeps.run_sweep`.

- Gmsh meshes must be written in MSH 2.2 format (`Mesh.MshFileVersion = 2.2`) for `gmshToFoam`.
- In ParaView, use its built-in OpenFOAM reader. The AUR package's reader plugin does not build.

## Structure

- `configs/default.yaml` is one complete case. Every key is required, and `cfd/config.py` loads and validates it. Invalid values raise `ConfigError` with a clear message.
- `geometry/windows.py` holds the wall frames, sash positions and the overlap/collision checks. It uses plain numpy, without Gmsh.
- `geometry/generate.py` builds the Gmsh OpenCASCADE model as a single `fluid` volume. It sorts boundary surfaces into patches (`inlet outlet sides top ground building room_walls sashes`) by their position, sets the mesh size fields, and writes the mesh in MSH 2.2.
- `geometry/render.py` makes off-screen PyVista renders of that same Gmsh geometry, shown as a cut-away view with the roof removed. Several configs can be shown side by side.
- `configs/examples/` holds one example case per layout. They are used for the README picture.
- `cfd/templates/flow/` and `cfd/templates/tracer/` hold the OpenFOAM case files of the two stages, with `@PLACEHOLDERS@`. `cfd/case_setup.py` fills them in, adds window-flow monitors and sets patch types.
- `cfd/solvers/tracerFoam/` is our solver: `scalarTransportFoam` plus turbulent diffusivity `D = nu/Sc + nut/Sct` on the frozen steady `phi`. It is compiled by `wmake` into `$FOAM_USER_APPBIN`, and `run_case` does this automatically.
  - Schemes: Euler with `bounded Gauss upwind`. Second-order schemes overshoot badly because the max Courant number is about 100 at the sashes.
  - The tracer case lives in `cases/<id>/tracer/`, with the mesh copied and `phi`/`nut` copied from the steady result.
- `analysis/metrics.py` computes `fresh_frac_XXXs`, `t90_s` and `tau_s` (PLAN.md §3) from the room-average tracer.
- The boundary conditions follow the OpenFOAM v2606 validation case `atmDownstreamDevelopment`: a log-law wind profile at the inlet, k-ω SST turbulence, rough ground via `atmNutkWallFunction`, and a fixed shear stress at the top.
- `cfd/run_case.py` runs the chain: Gmsh mesh, `gmshToFoam`, patch types, `topoSet` (cellZone `room`), `renumberMesh`, `checkMesh`, then `simpleFoam` in parallel. It writes `summary.json`.
- `analysis/monitor.py` is a live matplotlib/Tk window. It finds running solvers via psutil (process name and working directory), then reads `log.<solver>` and `postProcessing/` and shows progress, an estimated finish time, convergence plots and per-core load and affinity.
- `cfd/templates/transient/` is the option-B comparison stage: pimpleFoam starting from the steady solution, with a spin-up and then the tracer via the `scalarTransport` function object. The runner uses `mpirun --bind-to none` so that two cases can share the CPU.
- `analysis/visualize.py` reads a solved case with PyVista. It renders top views at window height (air speed with streamlines, or the tracer) and plots the replacement curve with matplotlib.
- `tests/`: pytest.
- `docs/images/` holds the images used in README.md. Re-render them when the geometry or the examples change.

The rest of the planned layout is in spec §7.
