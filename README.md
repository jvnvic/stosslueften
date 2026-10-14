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
| Tracer (air replacement) and metrics | ⏳ next |
| Solver benchmark, parameter sweep, dataset | planned |

## First result

![Air speed and streamlines in the default case](docs/images/default_flow.png)

This is the default case: windows on opposite walls, both turned open 90°, with a 3 m/s wind from the south. The wind enters through the south window, crosses the room as a jet and leaves through the north window, with two slow vortices on either side of the jet. About **7,700 m³/h** of air flows through the 50 m³ room.

The mesh has 160k cells, and the steady solve took 4.4 min on 8 cores. These are first test values on a coarse mesh and have not been checked for accuracy yet.

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
python -m cfd.run_case --config configs/default.yaml                          # mesh + wind simulation (needs OpenFOAM, ~5 min)
python -m analysis.visualize --config configs/default.yaml --out flow.png     # picture of the simulated flow
python -m pytest                                                              # run all tests
```

`cfd.run_case` writes everything to `cases/<case_id>/`. The key numbers go to `summary.json` there, and each OpenFOAM tool's output goes to a `log.<tool>` file.

To try a different case:

1. Copy `configs/default.yaml` or one of the files in `configs/examples/`.
2. Change the values (layout, window positions, modes, angles, hinge sides, wind speed).
3. Pass the new file to the commands above.

Invalid values stop with a message that says what to fix. `geometry.render` takes several config files at once and puts their pictures side by side.

## Repository layout

| Path | Contents |
|---|---|
| `configs/` | Case files (YAML), with one example per layout in `configs/examples/` |
| `cfd/` | Config loading, the OpenFOAM case templates and setup, and the case runner |
| `analysis/` | Pictures (and later metrics) from solved cases |
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
