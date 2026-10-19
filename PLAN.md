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
| `window1_hinge`, `window2_hinge` | `left` or `right`, sampled (decided 2026-10-16); only matters in turn mode. In the CSV a tilted window has `none`. |
| `wind_speed_ms` | 1–5 m/s |

**Sampling:** a Latin hypercube (`scipy.stats.qmc`) per layout, with fixed seeds. 150 training runs and a separately drawn test set of 30 runs (decided 2026-10-16), so 60 same-wall (method B) cases. Wind speed is sampled, not derived by scaling. About 25 % of the cases fall on each mode pair. Details are in DATASET_PLAN.md §2.

**Rejected samples:** a sample is redrawn if windows overlap (less than 0.2 m between frames) or if sashes collide in plan view. The generator logs how many were redrawn.

## 3. Outputs (the dataset contract; **columns frozen 2026-10-16, M2**)

`results/summary.csv` has one row per case, in this column order:

| Column | Meaning |
|---|---|
| `case_id`, `run_id`, `split` | Identification; `split` is `train` or `test` |
| `layout`, `window1_x_m`, `window1_mode`, `window1_angle_deg`, `window1_hinge`, `window2_x_m`, `window2_mode`, `window2_angle_deg`, `window2_hinge`, `wind_speed_ms` | The inputs (§2). The hinge of a tilted window is `none`. |
| `status`, `error_message` | `ok` or `failed`, and why. Failed cases keep their row with empty results. |
| `method` | `A` (steady flow + tracer) or `B` (time-varying flow): B for same-wall cases, A otherwise (§5, decision M1) |
| `fresh_frac_030s` … `fresh_frac_600s` | 20 points of the curve. fresh_fraction = 1 − room-average tracer. |
| `t90_s` | First time fresh_fraction ≥ 0.9. **Left empty** if never reached within 600 s. |
| `tau_s` | Time constant τ from fitting fresh_fraction ≈ 1 − exp(−t/τ). Always defined. |
| `airflow_m3h` | Inflow through both window openings, from the exact face fluxes; also counts air that enters and leaves through the same window |
| `steady_t90_s`, `steady_tau_s` | Method A's values, also for method B rows (for the A-vs-B comparison) |
| `n_cells`, `runtime_s`, `machine`, `openfoam_version`, `git_commit`, `finished_utc` | Reproducibility information |

**Uncertainty** (approved 2026-10-16): about ±3 % for method A rows (cross-ventilation) and about ±15 % for method B rows (same wall), see §5.

`results/timeseries/<case_id>.csv` holds `time_s, fresh_fraction` every 1 s. Logs and configs stay in `cases/<case_id>/`, which is not committed.

## 4. Pipeline

Each case goes through these steps:

1. YAML config.
2. Geometry with the Gmsh Python API, exported as STL; mesh with `snappyHexMesh`, then `checkMesh` (§6).
3. Steady flow (`simpleFoam`).
4. Tracer on the frozen steady flow (`tracerFoam`): method A.
5. Same-wall cases only: time-varying flow with the tracer (`pimpleFoam`): method B (§5, decision M1).
6. Metrics, then one row appended to `summary.csv`.

Commands:
- `python -m cfd.run_case --config <file>` runs one case (steps 2–5).
- `python -m cfd.queue <files>` runs many cases one after another, with a status file for the monitor and `--resume` after interruptions.
- Sampling the sweep inputs and writing `summary.csv` are still to be built (§9).

Implementation notes:
- The room is a cellZone made by `topoSet`.
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

**Decision M1 (first version, superseded on 2026-10-15, see the end of this section): option A (steady flow + frozen tracer) for the sweep.** It is 25–30× cheaper, and the difference to B (6–12 %) is reported as a known systematic uncertainty of the dataset.

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

**Decision M1 was reopened.** The decision rule above (B only at ≤ 30 min per case) still points to A, but A's error for the same-wall case is about 24 %. The overnight comparison below tested how far this goes.

**Overnight comparison (2026-10-15).** A vs B on 10 more cases (`configs/comparison/`), covering every layout and window-mode combination, wind at 1 and 5 m/s, and a coarse-mesh check of B. Together with the two cases above, that makes 12. The table and figure come from `python -m analysis.compare_methods` ([docs/images/method_comparison.png](docs/images/method_comparison.png)).

| Case | τ A | τ B | A vs B | t90 A | t90 B | largest curve gap |
|---|---|---|---|---|---|---|
| opposite walls, turn 90 / turn 90, 3 m/s | 34 s | 33 s | +3 % | 77 s | 74 s | 1.2 % points |
| opposite walls, turn 45 / tilt 6, 3 m/s | 134 s | 133 s | +0 % | 300 s | 302 s | 0.7 |
| opposite walls, tilt 6 / tilt 6, 3 m/s | 188 s | 185 s | +2 % | 430 s | 425 s | 0.9 |
| opposite walls, turn 90 / turn 90, 1 m/s | 100 s | 99 s | +1 % | 229 s | 226 s | 0.4 |
| adjacent walls, turn 60 / turn 30, 3 m/s | 39 s | 38 s | +2 % | 94 s | 93 s | 1.0 |
| adjacent walls, turn 60 / tilt 6, 3 m/s | 132 s | 132 s | 0 % | 311 s | 309 s | 0.7 |
| adjacent walls, tilt 6 / tilt 6, 3 m/s | 182 s | 182 s | 0 % | 418 s | 417 s | 0.2 |
| same wall, turn 90 / turn 90, 3 m/s | 249 s | 190 s | **+31 %** | 581 s | 443 s | 9.9 |
| same wall, turn 45 / tilt 6, 3 m/s | 546 s | 581 s | **−6 %** | – | – | 3.8 |
| same wall, tilt 6 / tilt 6, 3 m/s | 1448 s | 1219 s | **+19 %** | – | – | 4.7 |
| same wall, turn 90 / turn 90, 5 m/s | 147 s | 117 s | **+26 %** | 342 s | 274 s | 8.9 |
| same wall, turn 90 / turn 90, 3 m/s, coarse mesh | 207 s | 211 s | −2 % | 479 s | 492 s | 0.9 |

(– = 90 % not reached within 600 s. "Largest curve gap" is the largest difference between the two curves, in percentage points of air replaced.)

Findings:
1. **Windows on different walls (cross-ventilation): A matches B.** In all 7 cases, τ agrees within 3 % and the curves within about 1 percentage point. This includes tilted windows, slow air exchange (τ up to 188 s) and 1 m/s wind.
2. **Windows on the same wall (single-sided): A does not match B.** τ differs by −6 to +31 %, with no consistent direction, so a correction factor is not possible. In B, the flow at the windows fluctuates strongly. That moves air in and out in a way the steady flow cannot represent.
3. **Same-wall results also depend on the mesh**, unlike the cross-ventilation default case (±2.5 %, §6). Coarse vs medium mesh gives τ −17 % for A and +11 % for B. The coarse-mesh agreement of A and B (−2 %) is a coincidence: A and B move in opposite directions.
4. **τ scales exactly with 1/wind speed.** τ·U changes by only −0.3 % (A) and +1.6 % (B) between 1 and 3 m/s (opposite walls), and by −1.7 % (A) and +2.7 % (B) between 3 and 5 m/s (same wall). So the results are independent of the Reynolds number (§6). A case at another wind speed is the same curve stretched in time by 3/U.
5. **A is robust to tiny changes, but depends on where the steady solver stops.**
   - Same wall: moving window 1 by ±1 cm or making the cells 3 % smaller gives τ 242–249 s.
   - Adjacent walls (turn 60 / turn 30), identical mesh, 8 vs 4 cores: t90 88.4 vs 94.0 s. The window flow keeps swinging by ±1.3 % over the iterations, and its mean over iterations 1000–2000 is identical in both runs.
6. **The window-flow measurement is not good enough for the `airflow_m3h` column (§3).** It integrates the interpolated velocity over a plane in each opening and gives the net flow.
   - For same-wall cases it is ≈ 0, although plenty of air is exchanged.
   - In B with tilted windows, inflow and outflow differ by up to 30 % (opposite walls tilt/tilt: 633 vs 930 m³/h), which is impossible for a closed room. A balances to within 2 %.
   - The tracer is not affected: it uses the solver's exact, conservative face fluxes.
7. **Cost of B:** 30–120 min per case on 4 cores, with two cases running side by side. 5 m/s and fast cross-ventilation need smaller time steps (Courant limit). The night's 10 cases took 6.3 h, so about 38 min per case.
8. **Mesh fix:** one case failed `checkMesh` (2 sash faces with skewness 4.1). snappyHexMesh now uses checkMesh's limit (4) at walls. The default mesh is byte-identical.

**Decision M1 (team, 2026-10-15): method by layout.**
- **B for windows on the same wall, A for windows on opposite or adjacent walls** (A was validated by 7 of 7 cases there).
- The `method` column (§3) records which one was used.
- The labels are then B quality everywhere, at about 40 % of B's cost: 120 × ~4 min + 60 × ~40 min ≈ 2 days of compute instead of about 5.
- `cfd.run_case` applies this automatically (`method_for`): a same-wall case runs A and then B, and `summary.json` records the method.

**Same-wall mesh check and B's own scatter (night of 2026-10-15/16).** Same-wall benchmark case (both windows turned 90°, 3 m/s):

| Mesh | Cells | τ with A | τ with B | Notes |
|---|---|---|---|---|
| coarse (×1.4) | 53k | 207 s | 211 s | |
| medium (standard) | 103k | 249 s | 190 s | laptop |
| medium, window 1 moved 1 cm | 106k | 248 s | 199 s | |
| medium, rerun on the simulation PC | 103k | 247 s | 195 s | |
| medium, with the two fixes below | 103k | 246 s | 198 s | |
| fine (×0.7) | 254k | 262 s | 220 s | B only stable with max Courant 5; ~4 h on 8 cores |

- **B scatters by about ±5 % on its own** (190–199 s on the medium mesh): tiny changes, another machine or the fixes all move it this much. The flow fluctuates, and 600 s is a finite average. A moves by less than 1.5 %.
- **A converges with the mesh:** 207, 249, 262 s; medium is about 5 % below fine.
- **B does not converge clearly:** 211, ~195, 220 s. Fine is 13 % above the medium average, partly because it needed a smaller time step (Courant 5 instead of 10), which may itself change the result.
- **Fine-mesh B with max Courant 10 diverged** at t = 34 s: the time step collapsed to 1e-93 s. B runs now stop with an error if the time step falls below 1e-4 s, instead of hanging.
- **Consequence:**
  - Same-wall rows (method B, medium mesh) carry an uncertainty of roughly ±15 % (mesh plus scatter); cross-ventilation rows (method A) about ±3 %.
  - A fine mesh for the 60 same-wall cases (~4 h each) is not affordable.
  - In this case the fine-mesh B value (220 s) lies between medium A (+13 %) and medium B (−11 %). Decision M1 stays as it is, with this uncertainty documented.

**Proposed follow-ups before the sweep:**
  - a fine-mesh check of a same-wall case (A and B), because of finding 3: **done**, see the table above;
  - A: run the tracer on the flow averaged over the last ~1000 iterations, not the last iteration (finding 5): **done** (2026-10-16), see DATASET_PLAN.md §1;
  - `airflow_m3h`: measure the inflow on the exact face fluxes of the openings, not the interpolated plane (finding 6): **done** (2026-10-16), see DATASET_PLAN.md §1.
- **Optional:** because of finding 4, wind speed could be dropped from the sampled inputs. Every geometry would run at 3 m/s, and other speeds would follow by scaling time with 3/U. The same compute then covers more window geometries. This is an ML-side decision, so it needs the team.

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
| Steady RANS gets single-sided (`same_wall`) exchange wrong (−6 to +31 %, §5) | Method B for same-wall cases (decision M1); check B's mesh dependence for these cases before the sweep |

## 9. Still open / next steps (state 2026-10-19)

**Done:**
- Mesh decision: snappyHexMesh medium (§6).
- **Decision M1:** B for same-wall cases, A otherwise, built into `cfd.run_case` (§5).
- Same-wall mesh check and B's ±5 % scatter (§5). The uncertainty is approved: ±3 % for A rows, ±15 % for B rows.
- The two pre-sweep fixes (DATASET_PLAN.md §1): A on the iteration-averaged flow, airflow from exact face fluxes, plus a divergence stop for B.
- Input decisions (§2) and the frozen CSV columns (§3, M2).
- The sweep generator. `train-v1` (150 cases) and `test-v1` (30) are drawn in `configs/sweep/`.
- The simulation PC is set up (HPC_PLAN.md §8) and the remote runner with its dashboard is running there.
  - Dashboard: https://jvnvic.github.io/stosslueften/, with buttons that start the "Runner control" workflow.
  - Guide: `hpc/README.md`.
- **`train-v1` ran on the simulation PC:** 150 of 150 done, 0 failed, 48 h (finished 2026-10-18 09:08).
- **Extra training run `train-a-v1`** (Daniel, 2026-10-18): 50 more method A cases, 25 with windows on opposite walls and 25 on adjacent walls (corner). Same input ranges as `train-v1`, own seed. Done: 50 of 50, 0 failed.
- **Extra training run `train-a-turn-v1`** (Daniel, 2026-10-18): another 50 method A cases on opposite and adjacent walls (25 + 25), with both windows turned (no tilted windows). Done: 50 of 50, 0 failed (finished 2026-10-19 05:29).
  - The training set has 250 cases: 50 same-wall, 100 opposite, 100 adjacent. The mode mix of the training set shifts towards turned windows; `test-v1` keeps the even mix of `train-v1`.

- **Dataset writer** (`python -m sweeps.dataset`, DATASET_PLAN.md §3) and the **first training CSV** (2026-10-19): `results/summary.csv` with 250 rows, 241 `ok` and 9 `failed`, plus `results/timeseries/` and the data dictionary `results/README.md`.

**Found while building the CSV: a frozen tracer in 9 same-wall (method B) cases** (`train-v1_019`, `_028`, `_043`, `_058`, `_064`, `_067`, `_070`, `_082`, `_121`).
- In these cases the B tracer hardly moves: after 600 s only 0.1–5 % of the air is replaced, 1–15 % of what method A gives for the same case. Between 146 and 598 of the 600 one-second steps show no change at all. The other 41 B cases agree with A within −10…+15 %, as in the benchmark (§5).
- In `train-v1_019`, method A's tracer froze as well. No other A curve shows it.
- Cause: the tracer solver settings (`C`: tolerance 1e-7, relTol 0, in `cfd/templates/tracer/` and `transient/`). The solver skips its iterations when the first residual is already below the tolerance. In very weak flows (all 9 are same-wall cases with weak room flow, mostly tilted windows) that happens nearly every time step, so the tracer stays as it was.
- The dataset writer detects it (more than 10 s without any change) and writes these rows as `failed`.

Next, in this order:
1. **Fix the tracer solver settings** in both templates, e.g. `minIter 1` and a much smaller tolerance. Verify on `train-v1_019` (methods A and B) and check that an unaffected case keeps its result.
2. **Rerun the 9 cases** with the fix: method B, about 1.5 h each, so about 7 h on the simulation PC. The runner only reruns failed cases, so this needs a small addition (e.g. a rerun run with the same configs).
3. **Run `test-v1`** with the fix: tick it on the dashboard.
4. **Hand over to the ML part:** `results/README.md` (data dictionary, done) and the uncertainty notes.
5. **Still undecided:** exact deadline and deliverables, and the task split in the team. CFD runs only on Daniel's PCs, so teammates could take visualizations, literature and documentation.
