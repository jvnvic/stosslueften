# Dataset plan: sweep generator and dataset writer

Status: **proposal, 2026-10-15. Nothing is built yet.** The decisions marked *(decide)* are collected in §5. The background is in PLAN.md §2–3 (inputs and columns) and §5 (method by layout).

The chain from inputs to the CSV:

```
spec.yaml ──▶ sweeps.generate ──▶ configs/sweep/<run>/*.yaml ──▶ cfd.queue / HPC runner ──▶ cases/<case>/ ──▶ sweeps.dataset ──▶ results/
 (ranges,      (Latin hypercube,     (one complete case           (A, or A+B for same-wall      (summary.json,     (checks,         summary.csv
  seed, n)      checks, redraws)      file per case)               cases, automatic)             curves)           collects)        timeseries/)
```

## 1. Before the real runs: two fixes that change the results

Both change numbers in the dataset, so they must be in place before the first real case runs.

1. **Method A uses the flow averaged over iterations 1000–2000**, not the last iteration (PLAN.md §5 finding 5).
   - A `fieldAverage` function object in the flow stage writes `UMean`, `phiMean` and `nutMean`. The tracer stage uses `phiMean` and `nutMean`.
   - The average of conserving fluxes still conserves mass.
   - **Check:** the adjacent-walls case on 8 and on 4 cores must give the same t90 within 1 % (now: 88.4 vs 94.0 s). The default case must stay within 0.5 % of its old result.
2. **Airflow from the exact face fluxes**, instead of the velocity sampled on a plane (PLAN.md §5 finding 6).
   - Per window, `topoSet` builds a face zone across the opening, in the middle of the wall (`searchableSurfaceToFaceZone` with a plate). The zone follows the mesh faces, so it captures the flow exactly.
   - Two sums over `phi` on each zone: the net flow (`sum`) and the total in plus out (`sumMag`). The **inflow** is (sumMag + net) / 2.
   - For windows on the same wall the net flow is about 0, but the inflow measures the real exchange.
   - Method B averages the inflow over time after the spin-up.
   - **Check:** in every case, inflow equals outflow summed over both windows, within 1 %. In the default case the inflow stays close to the old 5,260 m³/h. In the same-wall case it is clearly above 0.

Total check time: about 1 h of computing.

## 2. Sweep generator (`python -m sweeps.generate`)

**Input:** a spec file per run, so that every run is reproducible from one small file:

```yaml
# configs/sweep/train-v1/spec.yaml
run_id: train-v1
split: train                # train | test
n_cases: 150                # split evenly over the three layouts
seed: 20261016              # the test set gets its own seed
base_config: configs/default.yaml   # fixed setup: room, mesh, solver settings
turn_share: 0.5             # per window: share of turned (vs tilted) windows -> 4 mode pairs ~25 % each
turn_angle_deg: [15, 90]    # tilted windows always 6°
hinge: sampled              # sampled | left   (decide)
wind_speed_ms: [1, 5]       # range, or one value if wind is handled by scaling   (decide)
```

**Sampling:**
1. **Exactly equal shares per layout** (50 / 50 / 50).
2. **Within each layout, a Latin hypercube** (`scipy.stats.qmc.LatinHypercube`, fixed seed) over 9 dimensions: both window positions, both modes, both angles, both hinges and the wind. A Latin hypercube spreads every input evenly over its range, even with few cases.
   - **Mapping from the unit cube:**
     - positions: 0.7 m to wall length − 0.7 m (5 m south and north walls, 4 m east wall);
     - mode: turned if the value is below `turn_share`;
     - angle: only used when turned;
     - hinge: left or right.
3. **Invalid draws are redrawn:** windows too close together, or sashes colliding (`geometry.windows.place_windows`).
   - Only the two positions of that case are drawn again, uniformly. The other inputs keep their Latin hypercube values, so the even spread stays intact.
   - The number of redraws is recorded. Expected: often for the same wall, rarely otherwise.
4. **Every written config is loaded and checked** with `cfd.config` before the generator finishes.

**Output in `configs/sweep/<run_id>/`:**
- `<case_id>.yaml`: one complete case each (`train-v1_001` …), the same format as `configs/default.yaml`.
- `manifest.json`: seed, spec, code commit, number of redraws, and per input the min, max and mean as a coverage check.
- `coverage.png`: pairwise scatter plots of the inputs. A quick visual check, and a figure for the report.
- **`queue_1.txt`, `queue_2.txt`:** the cases split into two lists of about equal total runtime, so the sweep can start with plain `cfd.queue` before the HPC runner exists.
  - The split counts a same-wall (B) case as about 10 A cases.
  - The same-wall cases come first, so that no long B case is left alone at the end.

**Pilot:** the first 15 cases of `train-v1` (5 per layout) run first. If the dataset writer then shows nothing wrong, they stay in the dataset and the rest follows. No compute is wasted.

**Tests:**
- the same seed gives the same files;
- all configs are valid;
- the layout shares are exact;
- tilted windows have 6°;
- every input covers its range (Latin hypercube property);
- the queue split is balanced.

## 3. Dataset writer (`python -m sweeps.dataset`)

`python -m sweeps.dataset --runs train-v1 test-v1 [--cases <folder>]` rebuilds `results/` from scratch every time:
- `results/summary.csv`: one row per case, sorted by `case_id`.
- `results/timeseries/<case_id>.csv`: `time_s, fresh_fraction`, one value per second from 0 to 600 s.
- `results/dataset_info.json`: when, from which runs and code commits, and counts per status.
- `results/README.md`: data dictionary for teammates (columns, units, how the values were produced). Plain CSV (UTF-8, comma, decimal point), readable on any OS.

**Columns** (proposal; becomes PLAN.md §3 when the team agrees, and is then frozen as milestone M2):

| Group | Columns |
|---|---|
| Identification | `case_id`, `run_id`, `split` |
| Inputs | `layout`, `window1_x_m`, `window1_mode`, `window1_angle_deg`, `window1_hinge`, `window2_x_m`, `window2_mode`, `window2_angle_deg`, `window2_hinge`, `wind_speed_ms` |
| Status | `status` (`ok` / `failed`), `error_message` |
| Results | `method` (A / B), `fresh_frac_030s` … `fresh_frac_600s` (20), `t90_s` (empty if not reached in 600 s), `tau_s`, `airflow_m3h` (inflow through both windows, §1 fix 2) |
| Method A for comparison | `steady_t90_s`, `steady_tau_s`: method A's values, also for same-wall (B) rows. This gives the A-vs-B difference over 60 cases for free, for the report. |
| Reproducibility | `n_cells`, `runtime_s`, `machine`, `openfoam_version`, `git_commit`, `finished_utc` |

- The hinge of a tilted window has no effect, so the CSV writes `none` there instead of `left` or `right`. Otherwise the ML model would see a meaningless feature.
- B rows take their results from `summary.json["transient"]` and the curve `fresh_fraction_transient.csv`; A rows from the top level and `fresh_fraction.csv`.
- Failed cases keep a row with `status: failed` and an empty result. Cases that have not run yet are left out, and their number is reported.

**Checks on every row** (problems are printed; with `--strict` they stop the writer):
- the inputs in the CSV equal the case's config;
- `summary.json` has the expected method;
- the curve rises (small dips < 0.5 % are allowed) and stays between 0 and 1;
- the tracer stayed within its bounds;
- inflow equals outflow within 2 %;
- `n_cells` is within ±10 % of the medium-mesh size.

**Where the results come from:**
- **With plain `cfd.queue`:** run the writer on the machine that has `cases/`, and commit `results/`. From the simulation PC, push it to a branch `dataset` and merge it on GitHub.
- **With the HPC runner:** the writer reads a checkout of the `hpc-results` branch (`--cases <checkout>/results/<run_id>`). The runner keeps the same file names, so both ways use the same code.

**Tests:**
- a row from a fake A case and a fake B case;
- `t90` left empty when not reached;
- `none` hinge for tilted windows;
- the header equals the frozen column list;
- each check catches a broken file.

## 4. Order of work and time

| When | Work | Time |
|---|---|---|
| Tonight (automatic, laptop) | the same-wall mesh check (running), then the checks of the two fixes (§1), start ~03:00 | ~5 h of computing |
| Tomorrow morning | Evaluate both; you decide §5 | ~1 h |
| | Sweep generator and dataset writer, with tests | ~3–4 h |
| Tomorrow afternoon | Pilot: 15 cases on the simulation PC with two queues (~1.5 h); dataset writer on the pilot | ~2 h |
| Then | Full training set on the simulation PC (~2 days); test set on the laptop at the same time, or later with the HPC runner | 2 days |

The HPC runner (HPC_PLAN.md §11) is built alongside and takes over from the test set or the reruns. The data does not wait for it.

## 5. Decisions needed *(decide)*

1. **Wind speed: sampled (recommended) or scaled.**
   - **Sampled:** 1–5 m/s, as in PLAN.md §2. Simple and honest; no extrapolation.
   - **Scaled:** results scale with 1/U (PLAN.md §5 finding 4), so one simulation could stand for all wind speeds. But a case at 3 m/s only covers 600 s × 3/5 = 360 s at 5 m/s. Covering the whole range would mean simulating at 5 m/s, and B cases at 5 m/s cost about twice as much (smaller time steps).
   - The scaling finding fits better as a check in the report, and as a hint for the ML part (τ·U).
2. **Hinge side: sampled (recommended) or fixed left.** It changes how a turned sash catches or deflects the wind, so it is a real design variable. A binary input costs little in a Latin hypercube.
3. **Tracer time step: keep 0.2 s (recommended).** 0.5 s would save about 15 s per A case (~5 %) at a 0.6 % difference. Not worth it.
4. **Size: 150 training + 30 test cases (recommended, as in PLAN.md §2).** That is 60 same-wall B cases, about 2 days on the simulation PC. Fewer B cases would save the most compute, but the layouts should stay balanced.
5. **Mode pairs: about 25 % each** (turned/turned, turned/tilted, tilted/turned, tilted/tilted) with `turn_share: 0.5`. Or more turned windows, if Stoßlüften with tilted windows matters less to the team.
6. **Columns (§3):** the extra `steady_*` columns, `none` for the hinge of tilted windows, and failed cases kept as rows. Then freeze (M2).
