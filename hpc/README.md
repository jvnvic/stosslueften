# Sweep runner on the simulation PC

The runner runs the dataset sweep on the Windows/WSL2 simulation PC. You control it from anywhere with the buttons on its dashboard (GitHub Pages), and get notifications in the GitHub app. The design is in [HPC_PLAN.md](../HPC_PLAN.md).

```
dashboard buttons ──▶ workflow "Runner control" ──▶ hpc/control.yaml on main ──▶ runner (every minute)
dashboard (GitHub Pages)  ◀── branch hpc-status   (every ~6 min: status.json, pictures)
dataset writer            ◀── branch hpc-results  (results of every finished case)
GitHub app                ◀── one issue per run   (failures, self-pauses, run finished)
```

## One-time setup

1. **Prepare the PC:** [setup/README.md](setup/README.md) (phase 0, done 2026-10-15).
2. **Install the runner** on the PC, in the Ubuntu window:

   ```bash
   cd ~/stosslueften && git pull
   bash hpc/setup/install_runner.sh
   ```

   - It becomes a systemd service. It starts with WSL, restarts after errors, and keeps running cases alive while it restarts.
   - While `hpc/control.yaml` says `state: pause`, it only publishes its status.
3. **Switch on GitHub Pages.** The runner's first status creates the branch `hpc-status` after about 1 minute. Then go to *Settings → Pages → Build and deployment → Source: Deploy from a branch → Branch `hpc-status`, folder `/ (root)` → Save*.
   - The dashboard appears at **https://jvnvic.github.io/stosslueften/** after 1–2 minutes.
4. **Optional, notifications:** add the issue token ([setup/README.md](setup/README.md) step 9), then run `sudo systemctl restart stosslueften-runner`.
5. **Buttons on the dashboard:** create a token once and save it on each device you use (phone, laptop):
   1. On GitHub: *your picture → Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token*.
   2. Name `stosslueften-dashboard`, expiration 90 days, *Only select repositories → jvnvic/stosslueften*, *Permissions → Repository → **Actions: Read and write***. Nothing else.
   3. On the dashboard, open *Buttons need a GitHub token on this device*, paste it, and press *Save*.

   This token can only start the "Runner control" workflow (and see or cancel workflow runs). It cannot change code or read anything secret. It is stored only in that browser; *Forget* removes it.

## Controlling it

**From the dashboard** (Control panel):
1. Choose Run / Pause / Stop, tick the runs and optionally failed cases to retry, and enter case ids to skip. The runs are worked on in the order you tick them; the panel numbers them (1., 2.).
2. Press *Apply*. If your choice is already the current state, the panel says so and sends nothing.

What happens then:
- The workflow changes `hpc/control.yaml` on `main` (~30 s). The panel reports when the workflow is done, with a link to it. The runner applies it within a minute and publishes right away.
- The panel shows the request until the dashboard confirms it, usually after 1–3 minutes.
- *Stop* asks for confirmation.

**Without a token** (any device where you are logged in to GitHub):
- In the GitHub app or on github.com, go to *Actions → Runner control → Run workflow* and fill in the same fields.
- On the dashboard, *Apply* opens that page when no token is saved.

**By hand:** edit [control.yaml](control.yaml) and push. The table shows what each setting does:

| You want to | Set in `hpc/control.yaml` |
|---|---|
| Start the training set | `state: run` and `runs: [train-v1]` |
| Then the test set too | `runs: [train-v1, test-v1]` (in this order) |
| Pause: running cases finish, no new ones start | `state: pause` |
| Stop at once: running cases are stopped and queued again | `state: stop` |
| Leave a case out | `skip: [train-v1_017]` |
| Run failed cases again | `retry: [train-v1_017]` |
| Update the runner's code | push the new code to `main`, set `state: pause`. When no case runs, the runner updates itself and restarts. Then `state: run` again. |

**Timing**
- The runner reads the file within a minute and, after a change, publishes its status right away. Otherwise the dashboard updates every ~6 minutes, because GitHub Pages rebuilds a branch at most about 10 times per hour.
- `skip` and `retry` act only on case ids that are new in the list. Later changes do not repeat them. To retry the same case again later, remove it and add it again; the dashboard and the workflow do that by themselves.

**A new run**
1. Draw its cases: `python -m sweeps.generate configs/sweep/<run>/spec.yaml`.
2. Add `hpc/runs/<run>.yaml`; copy [runs/train-v1.yaml](runs/train-v1.yaml) and change the name and pattern.
3. Add the run to `runs`.

A run uses the code of `main` at the moment it starts. All its cases keep that code, even if `main` changes later.

**What the runner does by itself**
- Same-wall cases (method B, 40–120 min) start first, so no long case is left alone at the end.
- A failed case gets one more try. After that it counts as failed, and the dashboard shows its log tail.
- Timeouts: 45 min for a method A case, plus 300 min for method B.
- Finished cases are adopted, not computed again. That includes cases finished by hand with `cfd.queue`, e.g. the pilot.
- While another process still works on a case (e.g. a pilot queue started by hand), the runner waits.
- After a reboot, interrupted cases start again. Method B continues from its last save point.
- Below 20 GB of free disk it pauses itself and says so on the dashboard.

## The dashboard

**Badge**
- `RUNNING` and `IDLE`: normal operation.
- `PAUSED`: `control.yaml` says `state: pause`.
- `STOPPED`: `control.yaml` says `state: stop`.
- `SELF-PAUSED`: the disk is nearly full.
- `OFFLINE?`: no update for 15 minutes. The runner, WSL, the PC or its internet connection may be down; check the PC.

**Red notes**
- **Control not applied:** a mistake in `control.yaml` or a run file. The message says what to fix; the runner keeps working with the last good version.
- **GitHub not reachable:** the cases keep running, and the results are sent later.

## Results

- **Branch `hpc-results`:** `results/<run>/<case>/` holds `config.yaml`, `summary.json` and the air-replacement curves. Finished cases also have `setup.jpg` and `flow.jpg`; failed cases have `log_tail.txt`. The dataset writer reads this branch.
- **Large case folders** stay on the PC in `~/stosslueften/cases/`.

## On the PC, if needed

```bash
.venv/bin/python -m hpc.show --watch            # summary: cases per status, running cases, failures, events
journalctl -u stosslueften-runner -f            # the service log (start-up messages and errors)
sudo systemctl restart stosslueften-runner      # restart it; running cases continue and are adopted
sudo systemctl stop stosslueften-runner         # stop the runner (running cases continue on their own)
cat ~/hpc/state.json                            # its memory: every case and its status
less ~/stosslueften/cases/<case>.runner.log     # output of one case
.venv/bin/python -m analysis.monitor            # the local monitor window shows the runner like a queue
```

## Testing without OpenFOAM or GitHub

- `python -m pytest tests/test_hpc.py` runs the whole runner with fake cases (seconds each) and a local repository in place of GitHub.
- **To look at the dashboard locally:**
  1. Copy `hpc/site/` to a folder.
  2. Rename `sample_status.json` to `status.json` there.
  3. Run `python -m http.server` in that folder.
  4. Open http://localhost:8000.

## Files

| File | Purpose |
|---|---|
| `control.yaml`, `runs/*.yaml` | What the runner should do (read from `main`) |
| `runner.py` | The loop: control, cases, publishing |
| `state.py` | The runner's memory (`~/hpc/state.json`) |
| `control.py` | Reads and checks the control and run files |
| `jobs.py` | Starts, watches, stops and adopts cases |
| `results.py` | Packs a finished case's results and pictures |
| `status.py` | Builds `status.json` for the dashboard |
| `gitsync.py` | Fetching `main`, publishing the two branches |
| `notify.py` | GitHub issue notifications |
| `show.py` | Short summary of the state for a terminal (`python -m hpc.show --watch`) |
| `control_edit.py` | Changes `control.yaml` for the workflow `.github/workflows/runner-control.yml` (the dashboard's buttons) |
| `fake_case.py` | Stand-in for `cfd.run_case` in tests |
| `site/` | The dashboard: `index.html`, `style.css`, `app.js` |
| `setup/` | Machine setup (phase 0) and the runner service |
