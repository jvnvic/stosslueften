# Stoßlüften CFD

This project runs automated **OpenFOAM** simulations of *Stoßlüften*: opening windows wide for a few minutes to replace the air in a room. The room has two windows, and the results become a dataset for training a **machine learning surrogate model**. It is a student project for the Master's course *Machine Learning* at Hochschule Hannover.

![The three window layouts](docs/images/layouts.png)

*The three window layouts, shown with the roof removed. The blue plates are the open sashes, and the arrow shows the wind coming from the south. These are the example cases in `configs/examples/`.*

## Status

| Step | State |
|---|---|
| Project plan | ✅ [PLAN.md](PLAN.md) |
| Geometry and mesh generator | ✅ |
| OpenFOAM case: steady wind flow | ✅ first test case runs |
| Tracer (air replacement) and metrics | ✅ runs on the frozen steady flow |
| Solver benchmark: comparison with a fully transient run | ✅ steady method chosen (see below) |
| Mesh study | ✅ snappyHexMesh, medium cell sizes (see PLAN.md §6) |
| Parameter sweep, dataset | planned |

## First result

![Air speed and streamlines in the default case](docs/images/default_flow.png)

This is the default case: windows on opposite walls, both turned open 90°, with a 3 m/s wind from the south. The wind enters through the south window and crosses the room diagonally as a jet, with a slow vortex in the south-east corner. It leaves through the north window. About **5,250 m³/h** of air flows through the 50 m³ room.

The mesh is a hex-dominant snappyHexMesh with 103k cells, and the whole case (mesh, flow, tracer) takes about 5 min on 8 cores. The mesh study in [PLAN.md §6](PLAN.md) shows that the air-replacement results change by less than 2 % with finer cells.

### Air replacement

![Share of air replaced over time](docs/images/default_curve.png)

At the start, the room is full of "old" indoor air (a tracer with value 1), and outdoor air is fresh (value 0). The tracer is then carried and mixed by the simulated wind flow.

- **90 % replaced:** after **76 s**.
- **Time constant:** the curve follows 1 − exp(−t/τ) with **τ = 33.5 s**.
- **Compared with perfect mixing:** a perfectly mixed room with the same airflow would reach 90 % after about 79 s. The diagonal jet stirs the whole room, so it comes close to perfect mixing.

![Where the original indoor air is after 30, 60 and 120 s](docs/images/default_tracer.png)

The pictures show where the old air stays longest: in the eastern half of the room, around the vortex, and in the south-west corner.

### Solver benchmark: is the fast method good enough?

The dataset uses a fast method:
- **(A)** compute the steady (averaged) wind flow once, then move the tracer through it.

We compared it with a much more expensive one:
- **(B)** compute the time-varying flow with the tracer (URANS), about 25–30× slower.

We ran both on two cases: windows on opposite walls, and both windows on the same wall. The second is the hardest case for method A. This benchmark ran on the earlier tetrahedral mesh.

![Benchmark, opposite walls](docs/images/benchmark_default.png)
![Benchmark, same wall](docs/images/benchmark_same_wall.png)

The two methods agree within 6 % (opposite walls) and 12 % (same wall). Method A replaces the air slightly faster. We use method A for the dataset and report this difference as a known uncertainty. Details are in [PLAN.md §5](PLAN.md).

## What is simulated

- **Room:** 5 × 4 × 2.5 m with two Dreh-Kipp windows.
- **Window layouts:** both windows on the same wall, on opposite walls, or on adjacent walls.
- **Window opening:** each window is either turned open (angle 15–90°, hinged on the left or right) or tilted (6°).
- **Wind:** comes from the south at 1–5 m/s and blows around the building.
- **Tracer:** the room starts full of "old air" (a tracer value of 1). We measure how fast fresh outdoor air replaces it.
- **Output:** each simulation adds one row to `results/summary.csv`, containing the inputs and results such as the fresh-air fraction over time and the time until 90 % of the air is replaced.

Details are in [PLAN.md](PLAN.md).

## Setup

You only need this on the **Linux machine that runs the simulations**. Teammates who only work with the results (CSV files) don't need to install anything here.

1. Install OpenFOAM v2606 and ParaView. On Arch Linux, run `yay -S openfoam-com paraview`.
   - **Known build problem (Oct 2026):** the build stops at `viewFactorsGen` with `undefined reference to __gmpz_…`, and the solvers are never built. To fix it:
     1. In `~/.cache/yay/openfoam-com/src/OpenFOAM-v2606/applications/utilities/preProcessing/viewFactorsGen/Make/options`, add the line `$(CGAL_LIBRARIES) \` as the first entry under `EXE_LIBS = \`.
     2. In `~/.cache/yay/openfoam-com`, run `makepkg -e` to finish the build without unpacking the sources again.
     3. If packaging then fails with "File exists" errors, run `rm -rf pkg && makepkg -R` to redo only the packaging.
     4. Install with `sudo pacman -U openfoam-com-v2606-1-x86_64.pkg.tar.zst`.
2. Create the Python environment in the repository folder:

   ```bash
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   ```

3. In every new terminal, activate the environment and load OpenFOAM:

   ```bash
   source .venv/bin/activate
   of    # if "of" is not found: source /opt/OpenFOAM/OpenFOAM-v2606/etc/bashrc
   ```

## Usage

```bash
python -m geometry.generate --config configs/default.yaml                     # build + mesh -> cases/default/mesh.msh
python -m geometry.render configs/default.yaml --out docs/images/default.png  # picture of the room setup
python -m cfd.run_case --config configs/default.yaml                          # wind + air replacement (needs OpenFOAM, ~6 min)
python -m cfd.run_case --config configs/default.yaml --tracer-only            # rerun only the air replacement
python -m analysis.visualize --config configs/default.yaml --kind flow --out flow.png   # also: --kind tracer, --kind curve
python -m analysis.monitor                                                    # live window: progress, CPU cores, convergence
python -m pytest                                                              # run all tests
```

**Monitor:** `python -m analysis.monitor` opens a dark window on the right half of the screen. It refreshes every 5 s and shows:
- every running case, with progress, estimated finish time and two small plots that show whether the values level off;
- the load of every CPU core and which case runs on it;
- the run queues: counts, progress, average time per case, and the expected finish time, even for hundreds of entries.

The queue list fills the rest of the window height and scrolls with the mouse wheel. The window can be resized up to full screen; the layout adapts. Closing it does not affect the simulations. Options: `--interval 10`, `--geometry 960x1040+960+0`, `--once picture.png`.

**Run queue:** many cases one after another, for example a parameter sweep:

```bash
setsid nohup python -m cfd.queue configs/examples/*.yaml > cases/queue.out 2>&1 &
setsid nohup python -m cfd.queue --resume cases/queues/<name>.json > cases/queue.out 2>&1 &   # after an interruption
```

**Long runs:** a simulation started from a terminal or from VS Code stops when that window is closed. To keep it running, start it detached, with the log going to a file:

```bash
setsid nohup python -m cfd.run_case --config configs/default.yaml > run.out 2>&1 &
```

An interrupted transient comparison run can be continued from its last save point (every 30 s of simulated time) with `--transient --resume`.

`cfd.run_case` writes everything to `cases/<case_id>/`:
- `summary.json`: the key numbers.
- `fresh_fraction.csv`: the air-replacement curve, one value per second.
- A `log.<tool>` file for each OpenFOAM tool's output.

The first run automatically compiles our own OpenFOAM solver `tracerFoam` (`cfd/solvers/`).

To try a different case:

1. Copy `configs/default.yaml` or one of the files in `configs/examples/`.
2. Change the values (layout, window positions, modes, angles, hinge sides, wind speed).
3. Pass the new file to the commands above.

Invalid values stop with a message that says what to fix. `geometry.render` takes several config files at once and puts their pictures side by side.

## Repository layout

| Path | Contents |
|---|---|
| `configs/` | Case files (YAML), with one example per layout in `configs/examples/` |
| `cfd/` | Config loading, the OpenFOAM case templates and setup, the case runner, and our tracer solver |
| `analysis/` | Metrics and pictures from solved cases |
| `geometry/` | Window placement, the Gmsh geometry and mesh generator, and the 3D renders |
| `docs/images/` | Pictures used in this README |
| `tests/` | Automated tests |
| `cases/` | Generated simulation folders (not in git) |
| `results/` | The dataset (planned) |

## Documentation

- [PLAN.md](PLAN.md): agreed decisions, dataset columns and schedule.
- [VENTILATION_CFD_PROJECT.md](VENTILATION_CFD_PROJECT.md): the original project specification.
- [log.md](log.md): how AI tools were used in each step (a course requirement).
- [AGENTS.md](AGENTS.md): instructions for AI coding assistants working in this repository.
