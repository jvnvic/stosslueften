# ML: model versions

Each version of the surrogate model is its own Jupyter notebook. All versions read [results/dataset_550/dataset_550.csv](../results/dataset_550/dataset_550.csv) and use the same train/test split, so their scores can be compared directly.

## Running a notebook

You need Python 3.11 or 3.12 with the packages in `requirements.txt`. The course environment (`ml-repo`) has the same versions and works as it is. Otherwise, from this folder:

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt        # Windows: .venv\Scripts\pip install -r requirements.txt
```

Open the notebook in VS Code or JupyterLab, select that environment as the kernel, and run all cells from the top. The notebooks are saved with their outputs, so you can also just read them on GitHub.

Each notebook starts with a flow diagram of its steps: data, training and prediction. The diagrams are drawn by `flow_diagrams.py` into `images/`.

## Versions

All scores are for t90 on the same 93 test cases (the test cases of the shared split that have a t90 value).

| Version | Notebook | What it predicts | Best model | MAE t90 | R² t90 | Notes |
|---|---|---|---|---|---|---|
| v0 | [v0_base.ipynb](v0_base.ipynb) | `t90_s` directly; cases without t90 are left out | DecisionTree | 42 s | 0.81 | The seminar template (unit 3). Has seen only 6 same-wall cases; the linear models predict negative t90. |
| v1 | [v1_tau.ipynb](v1_tau.ipynb) | log(`tau_s`) for every case, then t90 = ln(10) · τ | Ridge / LinearRegression | 50 s | 0.70 / 0.71 | Better for fast cases, worse for slow ones. Also covers same-wall and slow cases (τ typically 18 % off) and recognises 6 of 16 "t90 > 600 s" test cases. The tree drops to 58 s. |
| v2 | [v2_log_wind.ipynb](v2_log_wind.ipynb) | as v1, with log(wind speed) as input | Ridge / LinearRegression | 47 s | 0.74 / 0.75 | Better than v1 in every t90 score, mostly at the fastest and slowest cases; recognises 11 of 16 "t90 > 600 s" test cases. Learns τ ∝ (wind speed)^−0.97. The tree is unchanged. |
| v3 | next | | | | | Options at the end of v2: cross-validation, random forest or gradient boosting, a wind exponent per layout. |

The scores of each version are also in `results/<version>.csv`, one row per model, and its predictions for the test cases in `results/<version>_test_predictions.csv`. Later versions read these files to compare case by case.

## Making a new version

1. Copy the latest notebook to `vN_<short name>.ipynb` and set `VERSION` in the first code cell.
2. Keep sections 2 and 3 (loading the data, the split) unchanged. Otherwise the versions are tested on different cases.
3. Score t90 on the same test cases, write `results/<version>.csv` and `results/<version>_test_predictions.csv`, and add a row to the table above.
4. Add the version's steps to `VERSIONS` in `flow_diagrams.py`, mark what is new, run `python flow_diagrams.py`, and show `images/<version>_flow.png` under the notebook title.
5. End the notebook with its findings and what the next version should change.
