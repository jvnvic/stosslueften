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
| Solver benchmark: comparison with a fully transient run | ⏳ next |
| Parameter sweep, dataset | planned |

## First result

![Air speed and streamlines in the default case](docs/images/default_flow.png)

This is the default case: windows on opposite walls, both turned open 90°, with a 3 m/s wind from the south. The wind enters through the south window, crosses the room as a jet and leaves through the north window, with two slow vortices on either side of the jet. About **7,700 m³/h** of air flows through the 50 m³ room.

The mesh has 160k cells, and the steady solve took 4.4 min on 8 cores. These are first test values on a coarse mesh and have not been checked for accuracy yet.

### Air replacement

![Share of air replaced over time](docs/images/default_curve.png)

At the start, the room is full of "old" indoor air (a tracer with value 1), and outdoor air is fresh (value 0). The tracer is then carried and mixed by the simulated wind flow.

- **90 % replaced:** after **67 s**.
- **Time constant:** the curve follows 1 − exp(−t/τ) with **τ = 30 s**.
- **Compared with perfect mixing:** a perfectly mixed room with the same airflow would reach 90 % after 54 s. The real room is slower because part of the incoming air rushes straight through to the opposite window.

![Where the original indoor air is after 30, 60 and 120 s](docs/images/default_tracer.png)

The pictures show where the old air stays longest: in the slow vortex next to the jet, on the west side of the room.

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

`analysis.monitor` opens a small window that updates every 5 s while simulations run. It shows:
- the progress and estimated finish time of each running case;
- plots that show whether the values level off (residuals, window flow, air replaced);
- the load of each CPU core and which case runs on which core.

Start it in a second terminal. Closing it does not affect the simulations.

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
