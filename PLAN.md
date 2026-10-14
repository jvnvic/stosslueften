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

**First steady run (2026-10-14):** the default case on 160k tetrahedral cells with 8 cores ran 2000 iterations in 4.4 min. The residuals level off around 1e-3 to 1e-4, but the window flow has been stable to ±0.5 % since iteration ~600. Stopping once the monitored values are stable could cut this to about 1.5 min.

**Option A is implemented (2026-10-14).** Our solver `tracerFoam` (`cfd/solvers/`) is `scalarTransportFoam` with D = ν/Sc + νt/Sct (Sct = 0.7), running on the frozen steady fluxes.
- **Schemes:** Euler with bounded upwind. Second-order schemes overshoot to C = −114…+252, because the max Courant number is about 100 at the sashes. With upwind, C stays within 0…1 to better than 0.1 % after the first 0.4 s.
- **Time-step check (default case):** t90 is 66.84 s at Δt = 0.1 s, 66.88 s at 0.2 s and 67.26 s at 0.5 s. The default stays at 0.2 s; 0.5 s is an option for the sweep.
- **Cost:** about 1–1.5 min for the tracer plus about 4.5 min for the flow (about 1.5 min with an early stop). That is roughly 3–6 min per case, so 150+ runs are clearly affordable.
**Benchmark result (2026-10-14).** Option B: pimpleFoam (URANS, k-ω SST) on the same mesh, starting from the steady flow, max Courant number 10 (Δt ≈ 0.017–0.044 s), 60 s spin-up, then the tracer via `scalarTransport` with the same diffusivity.

| Case | Method | t90 | τ | Air replaced after 60 s | Window flow | Compute |
|---|---|---|---|---|---|---|
| opposite walls (default) | A | 66.9 s | 29.9 s | 87.1 % | 7,736 m³/h | ~6 min |
| | B | 70.9 s (+6 %) | 31.8 s (+6 %) | 85.5 % | 7,894 ± 25 m³/h | ~2.6 h* |
| same wall | A | 313 s | 143 s | 30.9 % | 785 m³/h | ~5 min |
| | B | 352 s (+12 %) | 160 s (+12 %) | 28.8 % | 727 ± 13 m³/h | ~2.2 h |

\*Tracer simulated for 300 s only. The run was shortened, since 99 % of the air was replaced after 120 s.

- **The time-varying flow is nearly steady.** The window flow fluctuates by less than 2 %.
- **Spin-up was enough.** The flow had leveled off after 30 s (default) and about 180 s (same wall), with nearly the same mean during the tracer phase.
- **B is slightly slower than A**, by 6 % (default) and 12 % (same wall). So A is slightly optimistic, not too pessimistic as feared for single-sided cases.
- **Empirical cross-check for same wall:** single-sided formulas (de Gids & Phaff 1982; Warren & Parkins 1985) give τ ≈ 210–250 s for single-sided exchange alone, plus the through-flow between the windows. Both methods are plausible.
- **Caveat:** URANS cannot capture turbulent "pumping" at openings either (that needs LES). The comparison tests unsteady mean-flow effects, not small-scale turbulence.

**Decision M1: option A (steady flow + frozen tracer) for the sweep.** It is 25–30× cheaper, and the difference to B (6–12 %) is reported as a known systematic uncertainty of the dataset.

**Repeat on the snappyHexMesh mesh (2026-10-14).** The same two cases and settings as above, on the medium snappy mesh (103k cells, §6). The B runs ran side by side with 4 cores each.

| Case | Method | t90 | τ | Air replaced after 60 s | after 600 s | Window flow | Compute |
|---|---|---|---|---|---|---|---|
| opposite walls (default) | A | 76.5 s | 33.5 s | 83.4 % | 100 % | 5,252 m³/h | 3.4 min (8 cores) |
| | B | 73.8 s (−4 %) | 32.6 s (−3 %) | 84.5 % | 100 % | 5,221 ± 73 m³/h | 48 min* |
| same wall | A | 581 s | 249 s | 22.1 % | 90.7 % | ≈ 0 (−21 / −4 m³/h) | 3.3 min (8 cores) |
| | B | 443 s (−24 %) | 190 s (−24 %) | 27.9 % | 95.3 % | 235 ± 150 m³/h, swinging between −650 and +840 | 63 min |

\*Tracer simulated for 330 s only (99.99 % replaced after 300 s).

- **Cross-ventilation: A and B agree within 4 %.** This is closer than on the tetrahedral mesh (6 %), and A is now slightly slower, not faster.
- **Same wall: A is 24 % slower than B.** The steady solution has almost no flow from one window to the other. In B, the flow through the windows swings strongly, around a stable mean through-flow of about 235 m³/h (100 s block averages 196–296 m³/h). A cannot represent that exchange.
- **Plausibility:** the single-sided formulas give τ ≈ 210–250 s for single-sided exchange alone, which matches A (249 s). Adding B's 235 m³/h of through-flow gives τ ≈ 180 s, which matches B (190 s).
- **On the tetrahedral mesh, the same-wall difference had the opposite sign** (A 12 % faster), because that steady solution had a through-flow of 785 m³/h. In weak-flow cases, the steady result depends on which of several steady states the solver ends up in. Those cases carry the largest uncertainty of method A.
- **Cost of B on this mesh:** two runs side by side each advance about 0.14 simulated s per second. A full case (60 s spin-up and 600 s tracer) takes about 80 min on 4 cores, which is about 40 min per case at two cases at a time. 180 cases would take about 5 days of continuous compute, versus about 15 h for A.

**Decision M1 is under review (team decision).** The decision rule above (B only at ≤ 30 min per case) still points to A. But A's error for weak-flow cases (same wall; probably also tilted windows) is now about 24 %, and those cases make up a large part of the sweep. Options:
1. Keep A for all cases. Report ±4 % for cross-ventilation and up to −24 % (A too slow) for single-sided cases.
2. Use B for all cases: about 5 days of compute. B would first need its own short mesh check.
3. First compare A and B on one or two cases with a tilted window (about 1–1.5 h), then choose between 1 and 2.

**Overnight comparison (started 2026-10-15 00:00, configs in `configs/comparison/`).** A vs B for every layout and window-mode combination, at 1 and 5 m/s wind, and a coarse-mesh check of B. The results go here when it has finished. Findings so far:
- **A's same-wall result is robust.** With window 1 moved by ±1 cm or with cells 3 % smaller, A gives t90 564–581 s, τ 242–249 s, and through-flow ≈ 0 every time. A's 24 % gap to B is systematic, not chance.
- **A depends on where the steady solver stops, in cases that never fully settle.** Adjacent walls (turn 60° / turn 30°), identical mesh, run on 8 vs 4 cores:
  - window flow 4,444 vs 4,345 m³/h, and t90 88.4 vs 94.0 s (6 %);
  - the window flow keeps swinging by ±1.3 % over the iterations, and the mean over iterations 1000–2000 is identical (4,406 vs 4,407 m³/h);
  - the default case barely swings (±0.2 %).
  - **Proposal if A is kept:** run the tracer on the flow averaged over the last ~1000 iterations (`fieldAverage` of U, phi and nut) instead of the last iteration.
- **Mesh fix:** one case failed `checkMesh` because of 2 sash faces with skewness 4.1. snappyHexMesh now uses the same limit as checkMesh (4) at walls. The default mesh is byte-identical, so earlier results stay valid.

## 6. Checks before the big sweep

- `checkMesh` passes for all 3 layouts × both modes.
- **Mesh sensitivity:** a coarse and a fine mesh on one case should give fresh_fraction curves within about 5 % of each other. Otherwise refine.
- The tracer stays within 0…1, and window inflow ≈ outflow.
- **Plausibility:** compare the cross-ventilation airflow with a simple orifice-equation estimate.
- **Reynolds independence:** the same case at 2 and 4 m/s should give τ·U ≈ constant. If that holds, wind speed could be handled by scaling results instead of by sampling. Decide this in week 2.

**Mesh and iteration checks (2026-10-14), default case, method A:**

| Mesh | Cells | t90 | Window flow (steady state reached) | Flow + tracer compute |
|---|---|---|---|---|
| coarse (×1.4) | 61k | 85.0 s | 8,030 m³/h | ~2 min |
| medium (default), 4 runs with the same settings | 160k | 66.9–82.0 s | 6,630–7,850 m³/h | ~2–5 min |
| fine (×0.7) | 457k | 79.8 s | 5,670 m³/h | ~11 min |

Findings:
- **Every run settles into a stable state after about 500 iterations, but not the same one.** The steady flow has several possible states, and small mesh differences decide which one the solver ends up in. The iteration count itself matters little once a state is reached.
- **Meshing was not reproducible.** Parallel (8-thread) Gmsh meshing gives a slightly different mesh each time; single-threaded meshing gives identical meshes.
- **Consequence:** results are not mesh-independent yet. Medium-mesh results scatter by about ±10 %, and the fine mesh differs systematically (−27 % window flow). No "best" setting can be chosen from this data.

**Follow-up (2026-10-14):**
- **Meshing is now reproducible.** Gmsh runs single-threaded: the same config gives a byte-identical mesh in 0.8 s.
- **Geometry fix:** the sash overlaps the opening by 2.5 cm on all sides, and the hinge post sticks out 2 cm beyond the sash, so no surfaces touch in the opening planes. Tet quality rose from 0.28 to 0.33.
- **Polyhedral cells (`polyDualMesh`) were rejected.** At the sharp concave window edges, 15–370 faces stay invalid, depending on the options, so `checkMesh` fails.
- **Hex-dominant `snappyHexMesh`** (2026-10-14), same physics, default case, method A:

| Mesh | Cells | t90 | τ | Air replaced after 60 s | Window flow | Compute per case |
|---|---|---|---|---|---|---|
| coarse (×1.4) | 53k | 78.2 s | 33.1 s | 83.1 % | 5,783 m³/h | 1.9 min |
| **medium** | **103k** | **76.5 s** | **33.5 s** | **83.4 %** | **5,253 m³/h** | **3.5 min** |
| fine (×0.7) | 249k | 77.6 s | 33.6 s | 83.3 % | 5,074 m³/h | 10.8 min |
| medium, cell sizes ×0.97 | 120k | 76.5 s | 32.9 s | 83.6 % | 5,546 m³/h | 5.0 min |
| medium, window 1 +1 cm | 104k | 74.2 s | 32.6 s | 84.3 % | 5,312 m³/h | 3.2 min |
| medium, window 1 −1 cm | 104k | 75.8 s | 33.2 s | 83.7 % | 5,317 m³/h | 4.5 min |

  - **Air-replacement metrics are mesh-independent and robust:** t90 within ±2.5 % and τ within ±1.5 % over all six runs. The tets scattered by ±10–20 %.
  - **Residuals:** about 1e-5 instead of about 1e-3, and the tracer stays exactly within 0…1.
  - **Window flow converges with refinement** (extrapolated ≈ 4,980 m³/h), so medium is about 5 % high.
  - **Decision: `snappyHexMesh` with the medium sizes is the default mesher.** About 5 min per case including the tracer, so 180 cases take about 15 h.
  - **Note:** the first solver benchmark (§5) ran on the old tetrahedral mesh. On the new mesh, the default case's flow is 32 % lower and t90 14 % higher than on that mesh. The benchmark was repeated on the new mesh (§5).

## 7. Schedule

| Week | Dates | Work | Milestone |
|---|---|---|---|
| 1 ✅ | Oct 14–20 | Install the tools:<br>• OpenFOAM v2606 via AUR `openfoam-com` (compiles from source, about 1–2 h)<br>• ParaView<br>• Python venv with `gmsh`, `numpy`, `pandas`, `scipy`, `pyyaml`<br>Then:<br>• Run one official tutorial.<br>• Mesh one layout with turned windows and solve the steady flow.<br>• Run the benchmark (§5). | **M1:** solver approach decided |
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

## 9. Still open / next steps (state 2026-10-14, end of day 1)

**Done:** the mesh decision (snappyHexMesh medium), about 5 min per case and 64 MB on disk per case. The solver benchmark was repeated on this mesh (§5, 2026-10-14).

Next, in this order:
1. **Decide M1 again (§5):** method A for all cases, B for all cases, or first one or two more comparisons with a tilted window. Whether B is chosen also changes the sweep's compute time (about 15 h for A, about 5 days for B).
2. **Sweep generator.** Latin hypercube sampling of the inputs (§2), writing one YAML per case (e.g. `configs/sweep/`). Train set of about 150 and a separate test set of about 30; invalid samples are redrawn and logged.
3. **Dataset writer:** `results/summary.csv` with the columns of §3, plus `results/timeseries/<case_id>.csv`. Freeze the columns (M2). Still missing from §3: the inputs as columns, `status`/`error_message`, `git_commit`.
4. **Run the sweep with `cfd.queue`** (detached; `--resume` after interruptions) and watch it with `analysis.monitor`.
5. **Open decisions:** sample the hinge side or keep it fixed; tracer Δt 0.2 s or 0.5 s for the sweep (0.6 % difference, §5).
6. **Still undecided:** exact deadline and deliverables, and the task split in the team. CFD runs only on Daniel's PC, so teammates could take visualizations, literature and documentation.
