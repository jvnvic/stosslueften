# AI Usage Log

The course requires us to document how AI was used in this project. Add one entry per working step, with the newest at the bottom. Exact prompts are not needed. Record who used which tool, what the AI did, and what the humans decided or checked.

Template:

    ## YYYY-MM-DD — Short title
    - **Who:** name
    - **AI tool / model:** e.g. Claude Code (Claude Opus 5.5), ChatGPT-6 (Medium effort)
    - **What the AI did:** …
    - **Human decisions / review:** …

---

## 2026-10-14 — Project specification
- **Who:** Daniel
- **AI tool / model:** ChatGPT-6 (Medium effort)
- **What the AI did:** Wrote the initial project specification, [VENTILATION_CFD_PROJECT.md](VENTILATION_CFD_PROJECT.md). It covers the goals, a two-stage CFD plan (airflow and tracer first, conjugate heat transfer second) and the tool choice (OpenFOAM, Gmsh, ParaView, Python). It also covers the parameter sweep, the CSV output schema, and the risks and non-goals.
- **Human decisions / review:** The team provided the project idea.

## 2026-10-14 — Repository setup and scoping
- **Who:** Daniel
- **AI tool / model:** Claude Code (Claude Opus 5.5)
- **What the AI did:**
  - Read the spec and checked the local machine. It found no OpenFOAM, Gmsh or ParaView installed, Docker available, and 8 cores with 30 GB RAM.
  - Pointed out that the spec does not cover the ML surrogate goal, and that the CFD cost of each run limits how big the dataset can be.
  - Asked eight scoping questions: ML target, CFD scope, compute, deadline, window model, solver approach, language and team.
  - Proposed two defaults: ESI OpenFOAM running in Docker, and keeping the dataset CSVs under version control in git.
  - Created `AGENTS.md` (shared instructions for all AI tools), `CLAUDE.md` (imports `AGENTS.md`), this log and `.gitignore`, and initialized the git repository.
  - Created the private GitHub repository `stosslueften` using the GitHub CLI and pushed the first commit.
- **Human decisions / review:**
  - Stage 1 is in scope, with Stage 2 as a stretch goal.
  - The surrogate predicts scalar metrics plus the air-replacement curve.
  - Simulations run on one PC, and the deadline is under 6 weeks away.
  - Windows are Dreh-Kipp, defined by turn/tilt mode plus angle.
  - The steady and transient solver approaches get benchmarked before choosing one.
  - Everything is in English.
  - The team works on mixed operating systems, so the instructions must be concise and usable with other AI models.

## 2026-10-14 — Data generation plan
- **Who:** Daniel
- **AI tool / model:** Claude Code (Claude Opus 5.5)
- **What the AI did:**
  - Asked eight planning questions: room and window size, window opening states, wind, simulated time, sampling, ML models, software setup and deliverables. Each came with a recommended default.
  - Checked package availability on Arch Linux. OpenFOAM v2606 is in the AUR as `openfoam-com`, ParaView is in the official repos, and Gmsh comes via pip.
  - Checked the OpenFOAM v2606 source code. `scalarTransportFoam` has only a constant diffusivity, which matters for the frozen-flow option, and `gmshToFoam` creates cell zones but no face zones.
  - Wrote `PLAN.md`, covering the fixed setup, varied inputs, output columns, pipeline, solver benchmark, checks, a 6-week schedule and risks.
  - Updated `AGENTS.md` to point to the plan.
- **Human decisions / review:**
  - The room is 4×5×2.5 m with 1.0×1.25 m windows.
  - Window modes are chosen independently per window, with the turn angle sampled and the tilt angle fixed.
  - Wind comes from one fixed direction.
  - Each run simulates 600 s, with the curve sampled every 30 s.
  - Inputs are sampled with a Latin hypercube, plus a separate test set.
  - OpenFOAM is installed natively instead of in Docker.
  - The ML models will follow the course requirements. The deliverables are not defined yet.
  - Focus on data generation first; the ML part will be planned later.

## 2026-10-14 — Python environment
- **Who:** Daniel
- **AI tool / model:** Claude Code (Claude Opus 5.5)
- **What the AI did:**
  - Created the Python virtual environment (Python 3.14) with `gmsh`, `numpy`, `pandas`, `scipy` and `pyyaml`, and pinned their versions in `requirements.txt`.
  - Ran a Gmsh smoke test: meshed a room box with a window opening and exported it in the MSH 2.2 format that OpenFOAM's `gmshToFoam` reads.
  - Read the AUR package's install notes. OpenFOAM is loaded with `of`, and ParaView has to use its built-in OpenFOAM reader.
  - Added the setup commands to `AGENTS.md`.
- **Human decisions / review:** Daniel started the OpenFOAM v2606 build (AUR `openfoam-com`) and asked the AI to commit, push and set up the Python environment.

## 2026-10-14 — Geometry and mesh generator
- **Who:** Daniel
- **AI tool / model:** Claude Code (Claude Opus 5.5)
- **What the AI did:**
  - Wrote the case config format (`configs/default.yaml`) and a loader that checks it (`cfd/config.py`). Unknown keys, missing keys and invalid values stop with a clear error.
  - Wrote the window placement logic (`geometry/windows.py`): wall coordinate frames, turn/tilt sash rotation, and checks that windows fit on their wall, don't overlap, and that open sashes don't collide.
  - Wrote the Gmsh model and mesh generator (`geometry/generate.py`). It builds the room, 0.3 m walls, window openings, sashes and outdoor domain, names the boundary patches, sets refinement zones and writes a mesh `gmshToFoam` can read.
  - Made one modeling choice: each sash turns about a solid 4 cm hinge post. Without it, the sash and wall form razor-thin wedges near the hinge that can't be meshed.
  - Added 56 automated tests. Meshed all 21 distinct layout, mode and angle combinations: each takes about 1 s and gives about 155–160k cells, with no poor-quality cells.
- **Human decisions / review:** Daniel asked the AI to start the geometry generator while OpenFOAM compiles.

## 2026-10-14 — README
- **Who:** Daniel
- **AI tool / model:** Claude Code (Claude Opus 5.5)
- **What the AI did:**
  - Wrote `README.md` covering the project summary, status, what is simulated, setup, usage, repository layout and links to the other documents.
  - Added Daniel's Gmsh screenshot of the default geometry as `docs/images/geometry_default.png`.
  - Added a rule to `AGENTS.md` that every AI assistant keeps the README up to date.
- **Human decisions / review:** Daniel asked for a README that is always kept current, and provided the screenshot.

## 2026-10-14 — 3D renders of the room setup
- **Who:** Daniel
- **AI tool / model:** Claude Code (Claude Opus 5.5)
- **What the AI did:**
  - Wrote `geometry/render.py`, which renders the same Gmsh geometry the simulation uses off-screen with PyVista. It shows a cut-away view without the roof, with solid walls, blue sashes, the floor, the ground and a wind arrow. Several cases can be placed side by side.
  - Added one example config per layout in `configs/examples/`.
  - Adjusted lighting and camera over a few render rounds, checking each picture. The result is a sun from the south-west, a fill light from the east, a soft camera light and soft corner shadows.
  - Replaced the wireframe screenshot in the README with a three-layout overview (`docs/images/layouts.png`) and added a picture of the default case.
  - Added PyVista and VTK to `requirements.txt` and added a test.
- **Human decisions / review:** Daniel asked for more appealing pictures than the Gmsh wireframe screenshot.

## 2026-10-14 — Hinge side setting
- **Who:** Daniel
- **AI tool / model:** Claude Code (Claude Opus 5.5)
- **What the AI did:**
  - Explained that the hinge side had been fixed by a coordinate convention. Seen from inside, south and east windows were hinged on the right and north and west windows on the left. The AI pointed out that this matters for the windward window, because a turned sash scoops or blocks the wind depending on its hinge side.
  - Added a required `hinge: left | right` setting per window, seen from inside the room facing the window. It only changes the geometry in turn mode.
  - Updated the configs, the geometry, the render titles and the tests (104 pass), including checks for each wall and hinge side and for a collision that a different hinge side avoids.
  - Re-rendered the README pictures.
- **Human decisions / review:** Daniel decided to add the hinge side as a setting. Whether the sweep samples it is decided after the benchmark.

## 2026-10-14 — Fixing the OpenFOAM build
- **Who:** Daniel
- **AI tool / model:** Claude Code (Claude Opus 5.5)
- **What the AI did:**
  - Analysed the failed AUR build log. One utility, `viewFactorsGen`, failed to link against the GMP/MPFR math libraries because its build file misses the CGAL link flags. The build stopped there, so none of the solvers (e.g. `simpleFoam`) were built.
  - Added the missing `$(CGAL_LIBRARIES)` line in the build tree, verified that this one utility now links, and resumed the build with `makepkg -e`. The full build completed: 276 programs and 143 libraries.
  - The first packaging run failed with "File exists" copy errors. The AI cleaned the package folder and reran only the packaging (`makepkg -R`), which succeeded.
  - Checked that the package contains all needed solvers and tools, and documented the workaround in the README.
- **Human decisions / review:** Daniel started the AUR build and reported the failure. Installing the finished package (needs sudo) is done by Daniel.

## 2026-10-14 — OpenFOAM installation check
- **Who:** Daniel
- **AI tool / model:** Claude Code (Claude Opus 5.5)
- **What the AI did:**
  - Explained why `of` was not found after installing. The shortcut is defined in `/etc/profile.d`, which only loads at login. Sourcing `etc/bashrc` directly works.
  - Ran the official `pitzDaily` tutorial with `simpleFoam`. It converged in 281 iterations (about 4 s), so the installation works.
  - Converted our default mesh with `gmshToFoam` and ran `checkMesh`. The result was "Mesh OK": one region, 160k cells, all 8 patches present, max aspect ratio 8.6, max skewness 1.36.
  - Added the non-login-shell fallback to `AGENTS.md`.
- **Human decisions / review:** Daniel installed the package with `sudo pacman -U`.

## 2026-10-14 — First wind simulation of the default room
- **Who:** Daniel
- **AI tool / model:** Claude Code (Claude Opus 5.5)
- **What the AI did:**
  - Studied the official OpenFOAM v2606 validation case for atmospheric wind (`atmDownstreamDevelopment`, k-ω SST variant) and based our boundary conditions on it: log-law wind profile at the inlet, rough ground, constant shear stress at the top, symmetry at the sides.
  - Wrote OpenFOAM case templates (`cfd/templates/`), a setup module that fills them in per case (`cfd/case_setup.py`), and a runner that does everything with one command (`cfd/run_case.py`). The runner meshes, converts, sets patch types, marks the room cells, checks the mesh, solves in parallel and writes a summary.
  - Added a `flow` section to the config: ground roughness, maximum iterations, CPU cores.
  - Ran the default case. Mesh check OK, 160k cells, 2000 iterations in 4.4 min on 8 cores. About 7,736 m³/h flows in through window 1 and 7,731 m³/h out through window 2. Normalized by window area and wind speed (0.58), this is within the typical range for cross-ventilation. The residuals level off, but the monitored values are stable from about iteration 600.
  - Wrote `analysis/visualize.py`, a plan-view picture at window height with air speed (one-hue blue scale) and streamlines, after checking the data-visualization guidelines. Improved the picture over three render rounds and added it to the README.
  - Added tests for the case setup (all pass).
- **Human decisions / review:** Daniel asked for a test simulation of the default room.

## 2026-10-14 — Tracer solver (air replacement)
- **Who:** Daniel
- **AI tool / model:** Claude Code (Claude Opus 5.5)
- **What the AI did:**
  - Wrote our own OpenFOAM solver `tracerFoam` (`cfd/solvers/tracerFoam/`). It is a copy of `scalarTransportFoam` that adds turbulent mixing (D = ν/Sc + νt/Sct) and reuses the mass-conserving flow of the steady simulation. It compiled without errors.
  - Added the tracer stage: templates (`cfd/templates/tracer/`), the setup in `cfd/run_case.py` (copies the mesh and frozen flow, sets C = 1 in the room) and `--tracer-only` to rerun just this stage.
  - Wrote `analysis/metrics.py`, which computes the dataset values `fresh_frac_030s` … `fresh_frac_600s`, `t90_s` and `tau_s`. The curve is saved as `fresh_fraction.csv`.
  - Found and fixed a numerical problem. The first scheme choice let the tracer overshoot to −114…+252 near the sashes (Courant number about 100). Bounded first-order upwind keeps it within 0…1 after the first 0.4 s and changes the room result by only 4 %. A looser solver tolerance made the tracer 2.5× faster.
  - Ran the time-step check from the plan: Δt = 0.1, 0.2 and 0.5 s give t90 within 0.6 % of each other.
  - Result for the default room: 90 % of the air is replaced after 67 s (τ = 30 s); a perfectly mixed room would take 54 s.
  - Made two pictures following the data-visualization guidelines: the replacement curve compared with perfect mixing, and top views of the remaining old air after 30, 60 and 120 s. Added them to the README.
  - Added tests for the metrics and the tracer templates (110 tests pass).
- **Human decisions / review:** Daniel asked the AI to continue with the tracer solver.
