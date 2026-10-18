# AGENTS.md

Shared instructions for every AI assistant used in this repo (Claude Code, Codex, Copilot, Cursor, Gemini, …). Keep this file short and current. `CLAUDE.md` only imports it.

## What this project is

This is a uni project for the Master's course *Machine Learning* (Hochschule Hannover). Automated **OpenFOAM** CFD simulations of *Stoßlüften* (window ventilation) in one room with two windows produce a CSV dataset. An **ML surrogate model** will be trained on it later.

- **Current phase: data generation** (the CFD pipeline). The ML part will be planned later.
- [PLAN.md](PLAN.md) holds the agreed decisions, dataset columns and schedule. **Read it first.**
- [VENTILATION_CFD_PROJECT.md](VENTILATION_CFD_PROJECT.md) is the original background spec. PLAN.md wins wherever they differ.
- [DATASET_PLAN.md](DATASET_PLAN.md) plans the sweep generator (built) and the dataset writer (next).
- [HPC_PLAN.md](HPC_PLAN.md) plans the remote sweep runner (Windows/WSL2 PC, control and status through GitHub). It is built and runs on the simulation PC (`hpc/`, operations guide `hpc/README.md`).
- Status (2026-10-18):
  - The pipeline is verified (PLAN.md §5–6). Decision M1: method B for same-wall cases, A otherwise; `cfd.run_case` applies it.
  - The inputs and CSV columns are decided and frozen (PLAN.md §2–3). The runs `train-v1` (150), `train-a-v1` (50 extra method A cases) and `test-v1` (30) are drawn in `configs/sweep/`.
  - The remote runner and dashboard (`hpc/`) run on the simulation PC. `train-v1` is done (150/150); `train-a-v1` runs next.
  - **Next: check the results, build the dataset writer, run `test-v1`**; see PLAN.md §9.
- Deadline: less than 6 weeks from 2026-10-14.

## Environment

- CFD runs on Daniel's Arch Linux PC. It uses a native OpenFOAM v2606 (openfoam.com, AUR `openfoam-com`, no Docker), ParaView, and a Python venv with the Gmsh API.
- The big sweep will run on a Windows 11 PC with WSL2: Ubuntu 24.04 and the openfoam.com Ubuntu package of v2606 (`/usr/lib/openfoam/openfoam2606`). Its setup is in `hpc/setup/README.md`. Scripts load OpenFOAM through `hpc/setup/foam_env.sh`, which finds either install.
- Teammates use Windows, macOS or Linux and have little programming experience. They don't run CFD; they work with the CSV results.

## Rules for AI assistants

1. **Log your work in [log.md](log.md) before you finish a task.** Append an entry using the template at the top of that file: who, which tool/model, what the AI did, and what the humans decided. Verbatim prompts are not needed. The course requires this log.
2. Write simple, readable code. Explain CFD and physics choices in brief comments, and tell the user exactly how to run what you built.
3. Don't silently change the decisions in PLAN.md or, once they are frozen, the CSV columns, because they are the ML dataset contract. Propose the change, and update PLAN.md once the team agrees.
4. Never commit generated case folders (`cases/`). Do commit the dataset CSVs (`results/`).
5. The CFD pipeline may assume Linux with OpenFOAM sourced. Anything teammates run must work on any OS.
6. When you add commands or folders, update the two sections below.
7. Start simulations that take longer than a few minutes detached: `setsid nohup <command> > <log> 2>&1 &`. Processes started from an editor or agent session die when that session closes.
   - Start case runs through `python -m cfd.queue` (also single runs and `--transient`), so that they appear in the monitor's queue list.
   - To wait for a run, check its output file or use exact process names (`pgrep -x simpleFoam`).
   - Never use `pgrep -f <pattern>`: the pattern also matches the shell that does the waiting, which then waits forever.
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
python -m pytest                                              # all tests (~20 s, no OpenFOAM needed)
python -m pytest tests/test_windows.py -k collide             # a single test
python -m geometry.generate --config configs/default.yaml     # geometry + mesh -> cases/default/mesh.msh
python -m geometry.generate --config configs/default.yaml --no-mesh --gui   # Gmsh wireframe view
python -m geometry.render configs/examples/*.yaml --out docs/images/layouts.png   # README picture
python -m cfd.run_case --config configs/default.yaml          # mesh + steady flow + tracer -> cases/default/ (needs OpenFOAM)
python -m cfd.run_case --config configs/default.yaml --tracer-only   # rerun the tracer on the existing flow
python -m cfd.run_case --config configs/demo/demo_2.yaml --steady-only   # same-wall case without method B (quick test)
python -m analysis.visualize --config configs/default.yaml --kind flow|tracer|curve|mesh --out <png>
python -m cfd.run_case --config configs/benchmark/same_wall.yaml --transient --procs 4   # option B comparison run (hours)
python -m cfd.run_case --config configs/benchmark/same_wall.yaml --transient --resume   # continue it after an interruption
python -m analysis.compare_methods configs/comparison/*.yaml --out <png>   # method A vs B table and curves
python -m analysis.monitor                                    # live progress window (--once <png> for a snapshot)
python -m cfd.queue configs/a.yaml configs/b.yaml             # run cases one after another (start detached)
python -m cfd.queue --transient --procs 4 configs/a.yaml      # option-B comparison runs (steady flow first if missing)
python -m cfd.queue --resume cases/queues/<name>.json         # continue an interrupted queue
python -m sweeps.generate configs/sweep/train-v1/spec.yaml   # draw the cases of a run (any OS)
python -m sweeps.queues configs/sweep/train-v1 --first 15    # split cases into 2 balanced cfd.queue lists (--skip-done for the rest)
bash hpc/setup/check_machine.sh                              # simulation PC: readiness check (guide: hpc/setup/README.md)
python -m hpc.setup.compare_reference                        # simulation PC: reference results vs the laptop
bash hpc/setup/install_runner.sh                             # simulation PC: install/update the runner service (hpc/README.md)
python -m hpc.show --watch                                   # simulation PC: runner summary from ~/hpc/state.json
python -m hpc.runner --home /tmp/hpc --fake --once           # one runner round with fake cases (no OpenFOAM)
```

Not implemented yet: the dataset writer (`python -m sweeps.dataset`, DATASET_PLAN.md §3).

- Gmsh meshes must be written in MSH 2.2 format (`Mesh.MshFileVersion = 2.2`) for `gmshToFoam`.
- In ParaView, use its built-in OpenFOAM reader. The AUR package's reader plugin does not build.

## Structure

- One case flows like this: config YAML → `cases/<id>/` (steady flow; `tracer/` = method A; `transient/` = method B, same-wall cases only) → `cases/<id>/summary.json` → the runner packs it into the `hpc-results` branch → the dataset writer → `results/summary.csv`.
- `configs/default.yaml` is one complete case. Every key is required, and `cfd/config.py` loads and validates it. Invalid values raise `ConfigError` with a clear message.
- `geometry/windows.py` holds the wall frames, sash positions and the overlap/collision checks. It uses plain numpy, without Gmsh.
- `geometry/generate.py` builds the Gmsh OpenCASCADE model as a single `fluid` volume. It sorts boundary surfaces into patches (`inlet outlet sides top ground building room_walls sashes`) by their position, sets the mesh size fields, and writes the mesh in MSH 2.2.
- `geometry/surfaces.py` writes the solid parts (walls, roof, sashes) as `obstacle.stl` for snappyHexMesh, the default mesher (`mesh.mesher` in the config, case files in `cfd/templates/snappy/`). snappyHexMesh cuts it out of a block mesh. The Gmsh tetra mesh (`mesher: gmsh`) is still available.
- `geometry/render.py` makes off-screen PyVista renders of that same Gmsh geometry, shown as a cut-away view with the roof removed. Several configs can be shown side by side.
- `configs/examples/` holds one example case per layout. They are used for the README picture.
- `configs/demo/` holds two randomly drawn demo cases; their pictures are in `docs/demo/`.
- `configs/benchmark/` holds the mesh study and solver benchmark cases (PLAN.md §5–6). `configs/comparison/` holds the method A vs B comparison cases for decision M1 (one per layout and window-mode combination, plus wind speed and mesh checks).
- `cfd/templates/flow/` and `cfd/templates/tracer/` hold the OpenFOAM case files of the two stages, with `@PLACEHOLDERS@`. `cfd/case_setup.py` fills them in, adds window-flow monitors and sets patch types.
- `cfd/solvers/tracerFoam/` is our solver: `scalarTransportFoam` plus turbulent diffusivity `D = nu/Sc + nut/Sct` on the frozen steady `phi`. It is compiled by `wmake` into `$FOAM_USER_APPBIN`, and `run_case` does this automatically.
  - Schemes: Euler with `bounded Gauss upwind`. Second-order schemes overshoot badly because the max Courant number is about 100 at the sashes.
  - The tracer case lives in `cases/<id>/tracer/`, with the mesh copied and `phi`/`nut` copied from the steady result.
- `analysis/compare_methods.py` prints a table and draws the air-replacement curves of method A vs B for cases that have both results.
- `analysis/metrics.py` computes `fresh_frac_XXXs`, `t90_s` and `tau_s` (PLAN.md §3) from the room-average tracer.
- The boundary conditions follow the OpenFOAM v2606 validation case `atmDownstreamDevelopment`: a log-law wind profile at the inlet, k-ω SST turbulence, rough ground via `atmNutkWallFunction`, and a fixed shear stress at the top.
- `cfd/run_case.py` runs the chain: mesh (snappyHexMesh by default), `topoSet` (cellZone `room`), `renumberMesh`, `checkMesh`, `simpleFoam` in parallel, then the tracer.
  - `method_for(cfg)` implements decision M1: same-wall cases also run the transient stage (method B).
  - It writes `summary.json` with `"method"`; the B results are under `"transient"`.
  - Method A's tracer uses the flow averaged over the second half of the iterations (`fieldAverage`: `phiMean`, `nutMean`), so results do not depend on where the solver stops.
  - Window flows come from a face zone across each opening (`window1FlowZone`, built by `topoSet`): net flow and inflow; `airflow_m3h` is the inflow through both windows.
  - Method B stops with an error if its time step collapses below 1e-4 s (divergence).
- `cfd/queue.py` runs cases sequentially via `cfd.run_case`. It writes `cases/queues/<start>.json` atomically (status per entry: pending/running/done/failed, duration, t90). `--transient` queues option-B comparison runs. `--resume` continues after an interruption. Several queues can run side by side (e.g. with `--procs 4`).
- `analysis/monitor.py` is a live matplotlib/Tk window, dark theme, sized to the right half of a 16:9 screen.
  - Data: running solvers and mesh tools from psutil (one row each, up to 4), per-core load in a compact grid for any core count, and the queue files.
  - Large queues are summarised: counts, throughput, finish estimate, and only the relevant entries.
  - Light: `TailTable` reads only newly appended lines and plots are thinned. Each panel is wrapped so that errors cannot stop the window.
- `cfd/templates/transient/` is the option-B comparison stage: pimpleFoam starting from the steady solution, with a spin-up and then the tracer via the `scalarTransport` function object. The runner uses `mpirun --bind-to none` so that two cases can share the CPU.
- `analysis/visualize.py` reads a solved case with PyVista. It renders top views at window height (air speed with streamlines, or the tracer), the mesh (cuts coloured by cell size and the surface grid), and plots the replacement curve with matplotlib.
- `sweeps/generate.py` draws a run's cases from `configs/sweep/<run>/spec.yaml`: a Latin hypercube per layout (all three, or those in the optional key `layouts`), interleaved layouts, position redraws for overlapping windows. It writes the case files, `manifest.json` and `coverage.png`. `sweeps/queues.py` splits a run into balanced `cfd.queue` lists, with same-wall (B) cases first.
- `configs/sweep/train-v1/` (150 cases) and `configs/sweep/test-v1/` (30 cases) are the dataset runs (decided 2026-10-16). `configs/sweep/train-a-v1/` adds 50 training cases on opposite and adjacent walls (method A, 2026-10-18).
- `hpc/` is the sweep runner for the simulation PC (HPC_PLAN.md, operations: `hpc/README.md`).
  - Control comes from `hpc/control.yaml` and `hpc/runs/*.yaml` on `main`. The loop is in `runner.py`, its memory in `~/hpc/state.json` (`state.py`), and cases are handled by `jobs.py`.
  - Each case runs as `python -P -m cfd.run_case` with the run's pinned code on PYTHONPATH, in its own process group.
  - The runner publishes `status.json` and the dashboard (`site/`) to the `hpc-status` branch (one force-pushed commit, GitHub Pages), and results to `hpc-results` (`results.py`, `gitsync.py`). Notifications go through GitHub issues (`notify.py`).
  - Tests use `fake_case.py` and a local bare repository (`tests/test_hpc.py`).
  - The dashboard's Control panel starts the workflow `.github/workflows/runner-control.yml` (GitHub API, a token with *Actions: write* stored in the browser). The workflow edits `hpc/control.yaml` via `hpc/control_edit.py` and commits it to `main`. It uses no third-party actions.
- `hpc/setup/` prepares the simulation PC (HPC_PLAN.md phase 0): the guide `README.md`, the install and Windows scripts, the machine check, the reference check against the laptop (`reference.json`) and the throughput measurement.
- `tests/`: pytest.
- `docs/overview/overview.tex` is a one-page overview for the course (PDF next to it, `latexmk -pdf`). Update it when the status changes significantly.
- `docs/images/` holds the images used in README.md. Re-render them when the geometry or the examples change.

The rest of the planned layout is in spec §7.
