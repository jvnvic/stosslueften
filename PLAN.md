# Data Generation Plan

**Goal:** produce a documented CFD dataset of Stoßlüften cases (Stage 1: isothermal airflow + passive tracer) that an ML surrogate model can be trained on later. The ML part is planned separately.

Agreed 2026-10-14. Deadline: less than 6 weeks away; the exact date is still to be set. Background: [VENTILATION_CFD_PROJECT.md](VENTILATION_CFD_PROJECT.md). This plan wins wherever the two differ.

## 1. Fixed setup

| Item | Value |
|---|---|
| Room (inside) | 5.0 m (x) × 4.0 m (y) × 2.5 m (z). Walls and roof are 0.3 m thick, the floor sits on the ground, and the building is 2.8 m tall. |
| Axes | Origin at the inner south-west floor corner. x points east, y north, z up. |
| Windows | Single Dreh-Kipp sash, 1.0 m wide × 1.25 m high, sill at 0.9 m. The sash is a 0.06 m solid plate that opens inward and turns about a solid hinge post (r = 4 cm). The post prevents mesh-breaking thin wedges at the hinge. |
| Turn mode | Hinge side set per window with `hinge: left \| right`, seen from inside the room facing the window. |
| Tilt mode | Hinge at the bottom, fixed at 6°, which gives a ~13 cm gap at the top. |
| Window position | `x_m` is the distance from the wall's west end (S/N walls) or south end (E/W walls) to the window centre. |
| Layouts | `same_wall` uses the south wall twice. `opposite_walls` uses south + north. `adjacent_walls` uses south + east. |
| Wind | From the south, hitting the south facade head-on. Log-law wind profile at the inlet (roughness z0 = 0.03 m), with the speed defined at roof height. |
| Outdoor domain | 5 H upstream, to the sides and above; 15 H downstream (H = 2.8 m). Shrink it only if a test shows no effect on results. |
| Physics | Isothermal RANS with the k-ω SST turbulence model. A passive tracer starts at C = 1 inside the room and is 0 in outdoor air. |
| Simulated time | 600 s, with the time series written every 1 s. |

## 2. Varied inputs

| Input | Range |
|---|---|
| `layout` | `same_wall`, `opposite_walls`, `adjacent_walls`, in equal shares |
| `window1_x_m`, `window2_x_m` | 0.7 m to (wall length − 0.7 m), keeping 0.2 m clear of the corners |
| `window1_mode`, `window2_mode` | `turn` or `tilt`, chosen independently (4 combinations) |
| `window1_angle_deg`, `window2_angle_deg` | `turn`: 15–90°. `tilt`: fixed at 6°. |
| `window1_hinge`, `window2_hinge` | `left` or `right`; only matters in turn mode. Whether the sweep samples it or keeps it fixed is decided after the benchmark. |
| `wind_speed_ms` | 1–5 m/s |

**Sampling:** Latin hypercube (`scipy.stats.qmc`) with fixed seeds. We aim for about 150 training runs plus a separately drawn test set of about 30 runs. The week-1 benchmark sets the final count.

**Rejected samples:** a sample is redrawn if windows overlap (less than 0.2 m between frames) or if sashes collide in plan view. The generator logs how many were redrawn.

## 3. Outputs (the dataset contract; columns are frozen at M2)

`results/summary.csv` has one row per run. Each row contains `case_id`, `split` (train or test) and all the inputs above, plus:

| Column | Meaning |
|---|---|
| `status`, `error_message` | Whether the run succeeded, and why not if it failed |
| `fresh_frac_030s` … `fresh_frac_600s` | 20 points of the curve. fresh_fraction = 1 − room-average tracer. |
| `t90_s` | First time fresh_fraction ≥ 0.9. **Left empty** if never reached. |
| `tau_s` | Time constant τ from fitting fresh_fraction ≈ 1 − exp(−t/τ). Always defined. |
| `airflow_m3h` | Mean volumetric inflow through both window openings (inflow equals outflow) |
| `n_cells`, `solver`, `runtime_s`, `git_commit` | Reproducibility information |

`results/timeseries/<case_id>.csv` holds `time_s, fresh_fraction` every 1 s. Logs and configs stay in `cases/<case_id>/`, which is not committed.

## 4. Pipeline

Each case goes through these steps:

1. YAML config.
2. Geometry and mesh with the Gmsh Python API.
3. `gmshToFoam` conversion, then `checkMesh`.
4. Flow solver.
5. Tracer.
6. Metrics, then one row appended to `summary.csv`.

Commands:
- `python -m cfd.run_case --config <file>` runs one case.
- `python -m sweeps.run_sweep --config <file>` runs a sampled set. It skips finished cases, records failures and continues.

Implementation notes:
- The room is a cellZone, because `gmshToFoam` maps Gmsh physical volumes to cellZones.
- Window flux needs faceZones built with `topoSet`, because `gmshToFoam` creates none.
- The pipeline assumes Linux with OpenFOAM v2606 sourced, and fails with a clear message otherwise.

## 5. Solver benchmark (week 1, decides the approach)

Run two options on one coarse `opposite_walls` case and one coarse `same_wall` case:

- **A:** steady `simpleFoam`, then the tracer transported on the frozen flow field.
- **B:** transient `pimpleFoam` with the `scalarTransport` function object, for 600 s.

**Decision rule:** choose B if it stays at or below about 30 min per case (180 runs ≈ 4 days of compute). Otherwise choose A. Record how the curves differ, because that difference is a limitation to report.

**Caveat for A:** `scalarTransportFoam` in v2606 only has a constant diffusivity `DT` (checked in the source), which ignores turbulent mixing. A needs either a small modified copy of that solver with D = DT + νt/Sct (about 20 lines of C++), or another frozen-flow method found in week 1.

## 6. Checks before the big sweep

- `checkMesh` passes for all 3 layouts × both modes.
- **Mesh sensitivity:** a coarse and a fine mesh on one case should give fresh_fraction curves within about 5 % of each other. Otherwise refine.
- The tracer stays within 0…1, and window inflow ≈ outflow.
- **Plausibility:** compare the cross-ventilation airflow with a simple orifice-equation estimate.
- **Reynolds independence:** the same case at 2 and 4 m/s should give τ·U ≈ constant. If that holds, wind speed could be handled by scaling results instead of by sampling. Decide this in week 2.

## 7. Schedule

| Week | Dates | Work | Milestone |
|---|---|---|---|
| 1 | Oct 14–20 | Install the tools:<br>• OpenFOAM v2606 via AUR `openfoam-com` (compiles from source, about 1–2 h)<br>• ParaView<br>• Python venv with `gmsh`, `numpy`, `pandas`, `scipy`, `pyyaml`<br>Then:<br>• Run one official tutorial.<br>• Mesh one layout with turned windows and solve the steady flow.<br>• Run the benchmark (§5). | **M1:** solver approach decided |
| 2 | Oct 21–27 | Tracer and metrics; all layouts, turn/tilt and the validator; `run_case` as one command; the checks in §6 | **M2:** a valid CSV row for every layout and mode; columns frozen |
| 3 | Oct 28–Nov 3 | Sampler and sweep runner; a 15-run pilot; start the full sweep (train + test) | **M3:** sweep running |
| 4 | Nov 4–10 | Sweep runs, failed cases fixed and rerun; ParaView streamline and tracer visualizations for 2–3 cases | **M4:** dataset complete |
| 5–6 | Nov 11–24 | Buffer, dataset documentation, hand-over to the ML part. Stage 2 only if everything else is done. | |

## 8. Risks and fallbacks

| Risk | Fallback |
|---|---|
| Runs are too slow | Coarser mesh, smaller domain, option A, or fewer runs (at least about 100) |
| The thin tilt gap needs fine cells | Refine the mesh only around the windows |
| The Gmsh tetrahedral mesh is poor or slow for RANS | Switch to `snappyHexMesh`, with the geometry exported as STL from Python |
| Steady RANS underestimates single-sided (`same_wall`) exchange | Document it as a limitation |

## 9. Still open

- Exact deadline and deliverables.
- Whether to sample the hinge side or keep it fixed. Decide after the benchmark, once the affordable number of runs is known.
- Task split in the team. CFD runs only on Daniel's PC, so teammates could take visualizations, literature and documentation.
