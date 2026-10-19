# Dataset: Stoßlüften in one room

Each row is one CFD simulation. A room (5 m × 4 m × 2.5 m) has two windows, wind blows from the south, and the simulation measures how fast the indoor air is replaced by outdoor air during 10 minutes of airing. The aim is to train an ML model that predicts the air replacement from the window setup and the wind.

## Files

| File | Content |
|---|---|
| `summary.csv` | One row per simulation: the inputs, the results and some bookkeeping. **Start here.** |
| `timeseries/<case_id>.csv` | The full air-replacement curve of one simulation: `time_s, fresh_fraction`, one value per second from 0 to 600 s (only rows with `status = ok`). |
| `dataset_info.json` | When the files were made, from which runs and code versions, and the problems found. |

Plain CSV: UTF-8, comma-separated, decimal point. Load it with `pandas.read_csv("results/summary.csv")`, or open it in Excel / LibreOffice (choose comma as separator).

## What is in it now (2026-10-19)

- **250 training simulations** from three runs, all on the simulation PC:
  - `train-v1`: 150 cases, a third for each layout.
  - `train-a-v1`: 50 extra cases with windows on opposite or adjacent walls.
  - `train-a-turn-v1`: another 50 such cases, with both windows turned (none tilted).
- **241 rows are `ok`, 9 are `failed`.** All 9 are same-wall cases with weak airflow, where the tracer (the marker for indoor air) stopped moving in the simulation. This is a numerical fault, so their results are left empty until they are rerun. Leave these rows out for training.
- **The test set (`test-v1`, 30 cases) has not run yet.** Use only `split = train` rows for training and validation until it exists.
- Because of the two extra runs, the training set has more opposite-wall and adjacent-wall cases (100 each) than same-wall cases (41 ok), and more turned windows than tilted ones. The test set will have equal shares.

## Columns of `summary.csv`

**Identification**

| Column | Meaning |
|---|---|
| `case_id` | Name of the simulation, e.g. `train-v1_017` |
| `run_id` | The run it belongs to |
| `split` | `train` or `test` |

**Inputs**: use these as model features.

| Column | Unit | Meaning |
|---|---|---|
| `layout` | – | Where the two windows are: `same_wall` (both in the south wall), `opposite_walls` (south and north, cross-ventilation) or `adjacent_walls` (south and east, a corner room) |
| `window1_x_m`, `window2_x_m` | m | Position of each window's centre along its wall (0.7 m to wall length − 0.7 m) |
| `window1_mode`, `window2_mode` | – | `turn` (opened like a door) or `tilt` (top tilted inward, a 6° gap) |
| `window1_angle_deg`, `window2_angle_deg` | ° | Opening angle: 15–90 for `turn`, always 6 for `tilt` |
| `window1_hinge`, `window2_hinge` | – | Hinge side of a turned window, `left` or `right`, seen from inside; `none` for a tilted window |
| `wind_speed_ms` | m/s | Wind speed at roof height, 1–5 |

**Status**

| Column | Meaning |
|---|---|
| `status` | `ok`, or `failed` (results empty) |
| `error_message` | Why a row failed |

**Results**: candidates for the model's targets.

| Column | Unit | Meaning |
|---|---|---|
| `method` | – | How it was simulated: `A` = steady airflow + tracer (fast), `B` = time-varying airflow (slow, more accurate for same-wall windows). Same-wall cases use B, all others A. |
| `fresh_frac_030s` … `fresh_frac_600s` | 0–1 | Share of the indoor air replaced by outdoor air after 30 s, 60 s, … 600 s (20 points of the curve) |
| `t90_s` | s | Time until 90 % of the air is replaced. **Empty if that takes longer than 600 s.** |
| `tau_s` | s | Time constant τ of the curve fresh_fraction ≈ 1 − exp(−t/τ). Always given. Smaller means faster airing. |
| `airflow_m3h` | m³/h | Outdoor air flowing in through both windows (includes air that comes in and goes out again through the same window) |
| `steady_t90_s`, `steady_tau_s` | s | Method A's values. For A rows the same as `t90_s`/`tau_s`; for same-wall (B) rows they allow a comparison of the two methods. Not a model target. |

**Bookkeeping**: not model features.

| Column | Meaning |
|---|---|
| `n_cells` | Number of cells of the simulation mesh (about 100,000) |
| `runtime_s` | Compute time of the simulation steps, in seconds |
| `machine`, `openfoam_version` | Computer and OpenFOAM version |
| `git_commit` | Version of this repository's code that ran the simulation |
| `finished_utc` | When the simulation finished (UTC) |

## How accurate are the values?

- Method A rows (opposite and adjacent walls): about ±3 %.
- Method B rows (same wall): about ±15 %, because the time-varying flow fluctuates and the result depends somewhat on the mesh.

Details are in [PLAN.md](../PLAN.md) §5–6.

## How it is made

Every simulation was run by the scripts in this repository (`cfd/`) on the simulation PC. The results were collected with:

```bash
python -m sweeps.dataset --hpc --runs train-v1 train-a-v1 train-a-turn-v1
```

Running this again rebuilds this folder (except this README) from the stored results. The writer checks every case and marks known faults as `failed`; see `sweeps/dataset.py`.
