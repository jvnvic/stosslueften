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

## 2026-10-14 — Solver benchmark setup and live monitor
- **Who:** Daniel
- **AI tool / model:** Claude Code (Claude Opus 5.5)
- **What the AI did:**
  - Recommended a "risk first" order: a quick plausibility check of the steady method on a `same_wall` case, then the transient comparison (option B), then speed optimizations.
  - **same_wall check (steady method):** 90 % of the air is replaced after 313 s (τ = 143 s). Compared with empirical single-sided ventilation formulas (de Gids & Phaff 1982, Warren & Parkins 1985: τ ≈ 210–250 s for single-sided exchange alone) plus the simulated through-flow between the two windows, this is plausible. No red flag.
  - **Transient comparison stage:** built the transient stage (`--transient`). It runs pimpleFoam starting from the steady flow, with a 60 s spin-up, and transports the tracer with OpenFOAM's `scalarTransport` function object using the same diffusivity as `tracerFoam`. Started it for the default and `same_wall` cases (about 4.5 h and 2 h).
  - **CPU fix:** found that two parallel runs were pinned to the same 4 CPU cores (each process got only 50 %). Fixed with `mpirun --bind-to none` and restarted.
  - **Cut the automatic early stop:** OpenFOAM's built-in criterion only supports an absolute tolerance, and the window flows differ by a factor of 10 between cases. The AI proposed checking the effect of the iteration count directly instead. Prepared mesh-sensitivity (×1.4 / ×0.7 cell size) and iteration-count (500/1000/1500) checks, queued to run automatically.
  - **Live monitor:** wrote `analysis/monitor.py`, a small window that shows running simulations (progress, finish time, time step, Courant number), convergence plots and per-core CPU load with process placement. It revealed that the transient flows were still drifting after the planned 60 s spin-up, which will be checked before trusting the comparison.
  - **Curve plot fixes:** clearer label for the "perfectly mixed" reference, which only counts the through-flow, and an x-axis that grows when 90 % is reached late.
- **Human decisions / review:** Daniel decided that more simulation time is acceptable if it makes the results more trustworthy, and asked for an explanation of the long transient run and for a live monitor window.

## 2026-10-14 — Rescuing the interrupted transient runs
- **Who:** Daniel
- **AI tool / model:** Claude Code (Claude Opus 5.5)
- **What the AI did:**
  - After VS Code was closed by accident, all runs started from it had stopped: the default room at t = 230 s of 360 s, `same_wall` at 545 s of 660 s, plus the queued checks and the monitor.
  - Found an AI bug while inspecting the cases. The tracer function object had no write setting and therefore wrote a time folder at every time step: 29 GB of redundant data. Fixed the template (`writeControl writeTime`).
  - Added `--resume` to the runner. It continues an interrupted parallel run from its last complete save point and removes the incomplete per-step folders. Measured values are joined across the restart (`read_series`), with a test.
  - Resumed both runs from their save points (210 s and 540 s), so only about 20 s and 5 s of simulated time were lost. Freed about 27 GB.
  - Restarted the runs, the queued checks and the monitor detached from VS Code (`setsid nohup`), so closing the editor no longer stops them. Documented this in the README and as a rule in AGENTS.md.
  - Made the monitor resume-aware: it reads the newest log and joins values across restarts.
- **Human decisions / review:** Daniel reported the accidental closing and asked for the simulations to be rescued.

## 2026-10-14 — Slow resumed run: file indexer and CPU heat
- **Who:** Daniel
- **AI tool / model:** Claude Code (Claude Opus 5.5)
- **What the AI did:**
  - Investigated why the resumed default run was about a third slower. The time step and the end time were unchanged.
  - **Cause 1, KDE file indexer:** `baloo_file` used about 85 % of a core and 6.6 GB RAM while processing the ~80,000 folders written and then deleted by the earlier tracer write bug. Its index had bloated to 7.1 GB, of which 0.24 GB was in use.
  - **Fix:** with Daniel's approval, excluded `cases/` from indexing (`balooctl6 config add excludeFolders …`). Pausing did not stop the work, so the AI disabled indexing until the simulations are done (`balooctl6 disable`) and ended the stuck process with SIGTERM. Simulation speed recovered from 0.024 to 0.041 simulated s per real s.
  - **Cause 2, heat:** verified with the CPU's thermal-throttle counters that thermal throttling is real and ongoing. About 120,000 events since boot, dozens per 20 s at the time, P-cores down to 2.4 GHz, up to 97 °C.
  - Added a rule to `AGENTS.md`: start long runs detached (`setsid nohup`).
- **Human decisions / review:** Daniel approved the indexer changes and will improve the laptop's cooling.
- **To undo later:** `balooctl6 enable` turns indexing back on; the `cases/` exclusion stays. Optionally, `balooctl6 purge` rebuilds the bloated index.

## 2026-10-14 — Solver benchmark result (milestone M1)
- **Who:** Daniel
- **AI tool / model:** Claude Code (Claude Opus 5.5)
- **What the AI did:**
  - Evaluated the transient comparison runs (option B) against the steady method (option A) for two cases.
  - **Default room:** t90 is 70.9 s (B) vs 66.9 s (A), +6 %.
  - **same_wall:** t90 is 352 s (B) vs 313 s (A), +12 %.
  - Checked the spin-up: the time-varying flow had leveled off after 30 s (default) and about 180 s (same wall), with nearly the same mean during the tracer phase. It fluctuates by less than 2 %.
  - Made comparison plots (both methods, plus the perfect-mixing reference, with both t90 values labeled). Documented the result table, caveats and the decision in PLAN.md §5 and the README.
  - Found that the queued mesh and iteration checks had never started. The queue's process-name wait matched leftover helper shells from the AI's own launch command. Restarted the checks directly and detached.
  - Recommended **option A** for the sweep. It is 25–30× cheaper, and its 6–12 % optimistic offset is documented as a known uncertainty. This follows the plan's decision rule (B costs far more than 30 min per case).
- **Human decisions / review:** Daniel had approved more simulation time for trustworthiness. The decision M1 is recorded as the AI's recommendation per the plan's rule; the team can override it.

## 2026-10-14 — Mesh and iteration checks: results not mesh-independent
- **Who:** Daniel
- **AI tool / model:** Claude Code (Claude Opus 5.5)
- **What the AI did:**
  - Evaluated the mesh study (coarse ×1.4 / medium / fine ×0.7) and the iteration study (500/1000/1500/2000) for the default case.
  - **No convergence with mesh size:** t90 is 85.0 / 66.9 / 79.8 s, and the fine mesh has 27 % less window flow.
  - **Scatter between identical settings:** the iteration runs, all with the medium settings, scatter by about ±10 % (t90 67–82 s).
  - Analysed the iteration histories. Every run settles after about 500 iterations, but into different states (window flow 5,670–8,030 m³/h). The steady flow has several possible states, and small mesh differences decide which one is reached.
  - Showed that Gmsh's multi-threaded meshing is not reproducible (different meshes from the same config), while single-threaded meshing is.
  - Documented the findings in PLAN.md §6. Recommended reproducible meshing first, then testing a better mesh type before choosing mesh settings.
- **Human decisions / review:** Daniel asked for the best mesh setting. The AI could not give one yet, because the data show the results are not mesh-independent.

## 2026-10-14 — Reproducible meshing, sash geometry fix, polyhedral test
- **Who:** Daniel
- **AI tool / model:** Claude Code (Claude Opus 5.5)
- **What the AI did:**
  - **Reproducible meshing:** set Gmsh to single-threaded meshing. Verified that two runs now give byte-identical mesh files (0.8 s per mesh).
  - **Polyhedral test:** tested converting the tetrahedral mesh to polyhedral cells (`polyDualMesh`, several feature angles and options). It reduced 160k tets to 32–41k polyhedra, but `checkMesh` always failed.
  - **Geometry fix:** located the invalid faces with `checkMesh -writeSets`. Some came from sash and post surfaces touching the planes of the opening. The sash now overlaps the opening by 2.5 cm (like a real sash) and the hinge post extends 2 cm further, and the config check makes sure the sash corner stays inside the post. Tet quality improved from 0.28 to 0.33, and all 114 tests pass.
  - **Result:** the remaining invalid polyhedral faces (15 at best) sit at all sharp concave window edges, a known limitation of `polyDualMesh`. Recommended switching to the hex-dominant `snappyHexMesh` (the plan's fallback).
- **Human decisions / review:** Daniel approved steps 1 (reproducible meshing) and 2 (polyhedral test).

## 2026-10-14 — snappyHexMesh mesh study: mesh-independent results
- **Who:** Daniel
- **AI tool / model:** Claude Code (Claude Opus 5.5)
- **What the AI did:**
  - Implemented a second mesher based on the OpenFOAM tutorial `windAroundBuildings` (`mesh.mesher: snappy`):
    - STL export of the solid parts with regions (`geometry/surfaces.py`);
    - a block mesh of the domain, with refinement levels derived from the configured cell sizes;
    - feature-edge snapping;
    - room floor moved to the room walls with `createPatch`.
    The first mesh was valid immediately: 103k cells, 90 % hexahedra, `checkMesh` OK.
  - Ran a mesh study (coarse, medium, fine) plus three perturbation tests (window ±1 cm, cell sizes ×0.97). t90 stays within ±2.5 % and τ within ±1.5 %, where the tetrahedral mesh scattered by ±10–20 %. The residuals converge about 100× better.
  - Recommended and set snappyHexMesh medium as the default mesher (about 5 min per case). Re-ran the default case: reproducible (t90 76.4 s vs 76.5 s).
  - Updated the README pictures and numbers. On the new mesh, the jet crosses the room diagonally and the air replacement is close to perfect mixing.
  - The AI's wait loop hung once more on a `pgrep -f` pattern that matched itself; Daniel noticed the idle machine. The AI added a rule to AGENTS.md (wait via output files) and saved it as a lesson.
- **Human decisions / review:** Daniel approved trying snappyHexMesh, and asked for the best mesh setting.

## 2026-10-14 — Run queue and restyled monitor
- **Who:** Daniel
- **AI tool / model:** Claude Code (Claude Opus 5.5)
- **What the AI did:**
  - Wrote a queue runner (`cfd/queue.py`). It runs many cases one after another, writes a status file per queue for the monitor, and `--resume` continues after an interruption. Tested live with the three example cases.
  - Rewrote the monitor (`analysis/monitor.py`) to Daniel's requirements:
    - a dark, plain engineering look, sized to the right half of a 16:9 screen;
    - modular for parallel runs (one compact row each, up to 4, then counted in the header);
    - compact per-core load bars that scale to any core count;
    - a queue panel built for hundreds of entries: summary, progress, average runtime, throughput, finish estimate, failures and only the relevant entries. Checked with a 180-entry test queue.
  - Kept the monitor light and robust: it reads only newly appended file lines, thins long series before plotting, and wraps each panel so that a half-written file cannot stop the window.
  - Interpreted the unclear sentence on the CPU bars ("We do need the huge processor load bars") as "compact" and told Daniel, so he can correct it.
  - Added tests for incremental reading, window placement and the queue estimate (121 pass).
- **Human decisions / review:** Daniel asked for the restyle (right half of a 16:9 screen, dark, simple, modular for parallel runs and many cores, a queue list, light and stable), and pointed out that hundreds of runs will be coming.

## 2026-10-14 — Monitor layout change
- **Who:** Daniel
- **AI tool / model:** Claude Code (Claude Opus 5.5)
- **What the AI did:**
  - Rearranged the monitor as specified. From top to bottom: each run's title and status on one line with a slim full-width progress bar, the two graphs side by side, the CPU core bars, one small notes line, then the queue list over the full remaining height.
  - Made the queue list scrollable (mouse wheel) and complete: summary, running, failed, all waiting, then all finished entries. Only the visible lines are drawn.
  - Made the layout recalculate on resize, so it works from half to full 16:9. The CPU bars fill their rows evenly (8 cores: 2 × 4 on half a screen, one row at full width).
  - Shows "t90 not reached" instead of "nan". The example queue (three layouts on the new mesh) had finished: t90 is 76.4 s (opposite walls), 88.4 s (adjacent walls), and not reached within 10 min (same wall with one window tilted).
- **Human decisions / review:** Daniel specified the new order of the panels, the scrollable queue and scaling to full 16:9.

## 2026-10-14 — Handoff before a context reset
- **Who:** Daniel
- **AI tool / model:** Claude Code (Claude Opus 5.5)
- **What the AI did:** Prepared the project for a fresh AI context.
  - Checked that all work is committed and pushed.
  - Updated the status line in `AGENTS.md` and turned PLAN.md §9 into an ordered list of next steps: repeat the solver benchmark on the new mesh, sweep generator, dataset writer, run the sweep, open decisions.
  - Saved machine state (file indexing disabled, thermal throttling, OpenFOAM build fix) and working preferences in the assistant's local memory.
- **Human decisions / review:** Daniel asked for the preparation.

## 2026-10-14 — Solver benchmark on the snappy mesh (started), queue for transient runs
- **Who:** Daniel
- **AI tool / model:** Claude Code (Claude Opus 5.5)
- **What the AI did:**
  - Added `configs/benchmark/snappy_same_wall.yaml`: the same-wall benchmark case on the snappy mesh.
  - Ran option A for it. Its result differs strongly from the tetrahedral mesh:
    - t90 581 s (was 313 s) and τ 249 s (was 143 s).
    - Almost no air flows from one window to the other (net flow ≈ 0, was 785 m³/h), so the exchange is single-sided.
    - τ now matches the empirical single-sided estimate (210–250 s).
  - Started option B (transient) for the default and the same-wall case, in parallel with 4 cores each. As in the first benchmark, the default's tracer phase is cut to 300 s.
  - Added `--transient` to `cfd.queue`, so comparison runs can also be queued and show up in the monitor's queue list. The monitor marks such queues as "transient".
- **Human decisions / review:** Daniel asked to continue with the benchmark repeat. He asked that the next runs go through the queue so they show up in the monitor, and checked that the work matches PLAN.md §9 step 1.

## 2026-10-14 — Solver benchmark on the snappy mesh: results
- **Who:** Daniel
- **AI tool / model:** Claude Code (Claude Opus 5.5)
- **What the AI did:**
  - Finished option B for both benchmark cases on the snappy mesh.
    - Opposite walls: A and B agree within 4 %.
    - Same wall: A is 24 % too slow (t90 581 s vs 443 s). In B, the flow at the windows swings strongly around a mean through-flow of about 235 m³/h. The steady flow has almost none.
    - Checked against the single-sided ventilation formulas; both results are plausible for their through-flow.
  - Wrote the results into PLAN.md §5, set decision M1 to "under review" with three options, and made it the next step in §9. Updated the README benchmark section and its two plots, and the status line in `AGENTS.md`.
  - Problem found: the script's live shortening of the default run's end time (to 360 s) was ignored. OpenFOAM only re-reads a file whose timestamp is more than 5 s newer than its last read (`fileModificationSkew`), and the edit came 3 s after the start. The run went past 360 s until Daniel noticed. It was then set to 390 s and stopped there.
- **Human decisions / review:** Daniel noticed the run going over time. The decision on M1 (method A, B, or more comparisons first) is left to the team.

## 2026-10-14 — Overnight comparison runs for decision M1
- **Who:** Daniel
- **AI tool / model:** Claude Code (Claude Opus 5.5)
- **What the AI did:**
  - Planned an overnight batch (about 8–10 h) to give the team more data for the choice between method A and B. All runs go through `cfd.queue`. The configs are in `configs/comparison/`.
    - Three runs with method A only: the same-wall case with window 1 shifted by ±1 cm and with all cell sizes ×0.97. They test whether the steady state with almost no through-flow is robust.
    - Ten A-vs-B comparisons in two queues side by side (4 cores each), most informative first:
      - every layout combined with turn/tilt, tilt/tilt and turn/turn windows;
      - wind at 1 m/s (opposite walls) and 5 m/s (same wall);
      - the same-wall case on the coarse mesh, as a mesh check for method B.
  - Extended `cfd.queue --transient` so that it first runs the steady flow for cases that don't have one yet. Two queues started in the same second now get different status files.
- **Human decisions / review:** Daniel asked for a long overnight plan that gives as much data as possible for the decision.

## 2026-10-15 — Overnight comparison: first findings and a mesh fix
- **Who:** Daniel (asleep; the AI worked unattended)
- **AI tool / model:** Claude Code (Claude Opus 5.5)
- **What the AI did:**
  - Checked the start of the overnight batch.
    - The three steady-method checks show that A's same-wall result is robust (t90 564–581 s).
    - The queue runs the steady flow and then the transient stage, as intended.
  - One case (opposite walls, turn 45° and tilt) failed `checkMesh`: 2 sash faces with skewness 4.1, while snappyHexMesh allows up to 20 at walls.
    - Set snappyHexMesh to checkMesh's limit (4).
    - Checked that the default mesh is byte-identical and that the failed case now passes.
    - Queued the case again; it starts when comparison queue 2 has finished.
  - Found that method A depends on where the steady solver stops, in cases whose flow keeps swinging over the iterations. The same adjacent-walls case gave t90 88.4 s on 8 cores and 94.0 s on 4 cores, with an identical mean flow over the last 1000 iterations. Wrote this into PLAN.md §5 with a proposed fix (run the tracer on the iteration-averaged flow), to be decided by the team.
- **Human decisions / review:** none yet; to be reviewed by Daniel in the morning.

## 2026-10-15 — Analysis of the overnight comparison (method A vs B)
- **Who:** Daniel
- **AI tool / model:** Claude Code (Claude Opus 5.5)
- **What the AI did:**
  - Collected A and B results for all 12 comparison cases. Wrote `analysis/compare_methods.py` (table and curve figure, with tests) and added the figure to the README.
  - Main findings (details in PLAN.md §5):
    - A matches B within 3 % for windows on different walls (7 of 7 cases), but not for the same wall (−6 to +31 %).
    - Same-wall results also depend on the mesh (11–17 %).
    - τ scales exactly with 1/wind speed (within 3 %).
    - The window-flow measurement is unsuitable for the planned `airflow_m3h` column.
  - Recommended for the team's decision M1: method by layout (A for different walls, B for the same wall, about 2 days of compute), plus three follow-ups before the sweep:
    - a fine-mesh check of a same-wall case;
    - the tracer on the iteration-averaged flow;
    - airflow from exact face fluxes.
  - Also proposed dropping wind speed from the sampled inputs, because results scale with it.
- **Human decisions / review:** Daniel asked for the analysis. M1 and the wind-speed question are left to the team.

## 2026-10-15 — One-page overview for the teacher
- **Who:** Daniel
- **AI tool / model:** Claude Code (Claude Opus 5.5)
- **What the AI did:** Wrote a short web page for a reader without CFD background (published as a private Claude artifact). It covers the goal (inputs and outputs of the dataset), a five-step schematic of one simulation, the checks made so far with their results, the current status and a short glossary. It reuses the room picture from `docs/images/`.
- **Human decisions / review:** Daniel asked for a very short, simple overview for the course teacher.

## 2026-10-15 — One-page overview as a LaTeX PDF
- **Who:** Daniel
- **AI tool / model:** Claude Code (Claude Opus 5.5)
- **What the AI did:** Replaced the web page from the previous entry with a plain one-page LaTeX document, `docs/overview/overview.tex` and `.pdf`. It has the same content (goal, inputs and outputs, five-step process diagram, checks table, status) plus the streamline picture of the default case.
- **Human decisions / review:** Daniel preferred a plain LaTeX page to a styled web page, and asked for the streamline picture to be included.

## 2026-10-15 — Two random demo cases
- **Who:** Daniel
- **AI tool / model:** Claude Code (Claude Opus 5.5)
- **What the AI did:**
  - Drew two random room setups within the sweep ranges (PLAN.md §2, seed 20261015), checked them for window overlap and collisions, and saved them as `configs/demo/demo_1.yaml` and `demo_2.yaml`.
  - Ran both with method A through `cfd.queue`, with the monitor open. Each took about 3.5 min.
    - demo_1 (adjacent walls, turn 59° / turn 15°, 4.5 m/s): 4,530 m³/h, t90 60 s.
    - demo_2 (same wall, turn 81° / turn 83°, 3.7 m/s): 490 m³/h, t90 540 s.
  - Rendered the room setups and the streamline pictures into `docs/demo/`.
- **Human decisions / review:** Daniel asked for the demo runs, the pictures and the monitor.

## 2026-10-15 — Decision M1: method by layout, built into the pipeline
- **Who:** Daniel
- **AI tool / model:** Claude Code (Claude Opus 5.5)
- **What the AI did:**
  - Recorded the team's decision in PLAN.md §5: method B for same-wall cases, A for windows on opposite or adjacent walls.
  - Updated PLAN.md §3 (new `method` column instead of `solver`), §4 (pipeline steps), §8 (risk table) and §9 (next steps and compute estimate).
  - Implemented it in `cfd/run_case.py`. `method_for(cfg)` decides the method. A same-wall case runs A and then automatically the transient stage, and `summary.json` records `"method"`. `--steady-only` skips B for quick tests.
  - Adjusted `cfd.queue` to report B's t90 for those cases and to avoid running B twice in `--transient` queues. Added a test.
  - Checked the whole path with a shortened same-wall case (5 s spin-up, 30 s tracer) through the queue, then deleted it.
  - Updated the README, `AGENTS.md` and the status lines of the overview PDF.
- **Human decisions / review:** Daniel and the team decided on the method by layout (B for the same wall, A otherwise).
