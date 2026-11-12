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
| v3 | [v3_cv_tuning.ipynb](v3_cv_tuning.ipynb) | as v2; seminar unit 4: 5-fold cross-validation, grid search, test once | DecisionTree (depth 8, leaf 1), tuned | 44 s | 0.80 | Chosen by the CV error of log(τ). A classifier for "t90 > 600 s" finds 13 of 16 slow test cases (2 false alarms). On log(τ), v2's linear model is still slightly better. |
| v4 | [v4_ensembles.ipynb](v4_ensembles.ipynb) | as v3, with random forest and gradient boosting; all four candidates tuned, the best tested | GradientBoosting (depth 4, 2000 trees, learning rate 0.02) | **31 s** | **0.89** | CV error of log(τ) 0.147 (τ typically 16 % off; random forest 20 %, tree and Ridge 24–25 %). Finds 12 of 16 "t90 > 600 s" test cases with no false alarm. Largest errors: same-wall cases. |
| v5 | [v5_no_same_wall.ipynb](v5_no_same_wall.ipynb) | as v4, but without the same-wall cases (only windows on different walls) | GradientBoosting (depth 3, 300 trees, learning rate 0.1) | 31 s* | 0.90* | *On the 92 test cases on different walls. v4 on the same 92 cases: 29 s, R² 0.92, so leaving out the same-wall cases does not help; v4 stays the best model. |
| v6 | next | | | | | Options at the end of v5: save v4's pipeline with `joblib`, more same-wall training data, final check on `test-v1`. |

The scores of each version are also in `results/<version>.csv`, one row per model, and its predictions for the test cases in `results/<version>_test_predictions.csv`. From v4 on, `results/<version>_cv.csv` also holds the cross-validation comparison of the candidates. Later versions read these files to compare case by case.

## Making a new version

1. Copy the latest notebook to `vN_<short name>.ipynb` and set `VERSION` in the first code cell.
2. Keep sections 2 and 3 (loading the data, the split) unchanged. Otherwise the versions are tested on different cases.
   From v3 on, every choice (model, settings, inputs) is made by cross-validation on the training cases (the development data, seminar unit 4). The test cases are used once per version, after the choice, and only for the scores in the table.
3. Score t90 on the same test cases, write `results/<version>.csv` and `results/<version>_test_predictions.csv`, and add a row to the table above.
4. Add the version's steps to `VERSIONS` in `flow_diagrams.py`, mark what is new, run `python flow_diagrams.py`, and show `images/<version>_flow.png` under the notebook title.
5. End the notebook with its findings and what the next version should change.
