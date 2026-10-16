# HPC runner: remote-controlled sweep (plan)

Status (2026-10-16): **phases 0–3 are built and tested.**
- Phase 0: the machine setup ([hpc/setup/](hpc/setup/README.md)), done on the PC.
- Phases 1–3: the runner, the git channel and the dashboard. Tested with fake cases, a local stand-in for GitHub, and a real two-case OpenFOAM run on the laptop.
- Next is phase 4, the pilot on the simulation PC. Operations guide: [hpc/README.md](hpc/README.md).
- The decisions are in §10.

**Change from this plan:** the dashboard is published from the `hpc-status` branch directly ("Deploy from a branch"), not by an Actions workflow. That avoids maintaining third-party action versions. The price is at most ~10 Pages builds per hour, so the status is published every ~6 minutes; the runner still reacts to control changes within a minute.

## 1. Goal

A dedicated Windows 11 PC with WSL2 (the "HPC") runs the whole sweep (PLAN.md §9): hundreds of cases over several days. It has a Ryzen 7 8845HS (8 cores, 16 threads), 32 GB RAM and a 1 TB disk. Day-to-day work happens remotely; Daniel has physical access for emergencies.

- **Control** works by pushing files to GitHub: a run configuration, plus a small control file for pause, stop and retry.
- **Status** is shown on a GitHub Pages dashboard. It has the same numbers as `analysis.monitor`, plus pictures of the latest room setup and its streamlines.
- **Latency of about 1–3 minutes is fine.** Robustness matters more than speed: the HPC must recover by itself from crashes, reboots and network loss.

## 2. Overview

```
 Daniel (laptop / phone)              GitHub (public repo)                  HPC (Windows + WSL2 Ubuntu)
 ───────────────────────              ────────────────────                  ───────────────────────────
 edit hpc/control.yaml   ──push──▶  main        code, configs,  ◀──fetch──  runner (systemd service)
 add hpc/runs/<id>.yaml                          control files              every 60 s: read control,
                                                                            start/stop cases
 open dashboard ◀── Pages ◀─────── hpc-status   status.json +   ◀──push───  every 2 min: status
                                                latest pictures             (force-push, 1 commit)
 dataset writer ◀─────────────────  hpc-results  per-case results ◀──push─── after each case (batched)
```

- **The HPC only pulls from `main` and only pushes to its own two branches**, so it never conflicts with our commits.
- **Simulations never wait for GitHub.** Git runs in the runner's loop and only reads and writes files, while the cases run as separate processes.

## 3. Branches and files

| Where | Written by | Content |
|---|---|---|
| `main: hpc/runs/<run_id>.yaml` | us | A run: which configs, how many cases at once, cores per case |
| `main: hpc/control.yaml` | us | Desired state of the runner (§4) |
| `main: configs/sweep/<run_id>/*.yaml` | sweep generator (PLAN.md §9) | The case configs of a run |
| `main: hpc/` code | us | Runner, status builder, dashboard site, setup files |
| `hpc-status` (force-pushed, always 1 commit) | runner | `status.json`, latest pictures, a copy of the site, Pages workflow |
| `hpc-results` (appended) | runner | `results/<run_id>/<case_id>/`: summary.json, config, curves, two small pictures, a log tail if the case failed |

- **Force-pushing `hpc-status`** keeps the repo small: a status update every 2 min for a week, with pictures, would otherwise add hundreds of MB of history.
- **`hpc-results` grows by about 150 KB per case**, so about 30 MB for the whole sweep.
- **The final `results/summary.csv`** is built from `hpc-results` by the dataset writer and committed to `main` (PLAN.md §3).

## 4. Control: run files and control file

A run (pushed to `main`, picked up within a minute):

```yaml
# hpc/runs/sweep-train-v1.yaml
run_id: sweep-train-v1
configs: configs/sweep/train/*.yaml   # validated before the run starts; invalid -> run rejected, shown on the dashboard
code: main            # resolved to a commit when the run starts; every case of the run uses that commit
slots: 3              # cases at the same time
procs_per_case: 4     # same for every case (results depend slightly on it, PLAN.md §5 finding 5)
retries: 1            # automatic retries of a failed case
```

The control file is declarative: it describes the wanted state, not a one-off command. A missed poll or a runner restart therefore can't lose a command.

```yaml
# hpc/control.yaml
state: run            # run | pause (finish running cases, start no new ones) | stop (abort running cases now, requeue them)
runs: [sweep-train-v1, sweep-test-v1]   # order = priority; a run not listed here is not started
skip: []              # case ids to leave out
retry: []             # failed case ids to run again
runner_ref: main      # runner code version; applied only when paused and idle (remote self-update)
```

- **Editing is possible from anywhere:** in the GitHub web editor (also on a phone) or with `git push`.
- **Reaction time:** the runner reacts within 60 s. The dashboard shows the acknowledgement with the next status push (≤ 3 min).
- **Safety:** the runner never executes anything from these files. It only reads values and config paths, and validates every config with `cfd.config` and `geometry.windows` before use.

## 5. The runner (on the HPC)

`python -m hpc.runner` runs as a systemd service inside WSL (`Restart=always`). One loop, every 60 s, with each step wrapped so that an error in one step cannot stop the loop:

1. **Sync:** `git fetch`, then read `hpc/control.yaml` and `hpc/runs/*.yaml` from `origin/main` with `git show`, without touching the working tree.
2. **Reconcile:**
   - Start cases in free slots if `state: run`.
   - On `stop`, kill running cases (process group) and requeue them.
   - Apply `skip` and `retry`.
3. **Watch:** check that running cases are still alive, and apply the timeouts (A: 30 min, B: 4 h, configurable). Read their progress from the logs, reusing `analysis.monitor`.
4. **Finish:** for each case that has finished:
   - collect the results;
   - render the room setup (`geometry.render`) and the streamlines (`analysis.visualize --kind flow`) as small JPEGs;
   - queue them for `hpc-results`.
5. **Publish:**
   - every 2 min if something changed, and at least every 10 min as a heartbeat: build `status.json` and force-push `hpc-status`;
   - results: batched pushes to `hpc-results`.

**Cases**
- Each case is started as `python -m cfd.run_case --config … --procs N` in its own process group, from a git worktree of the run's code commit. `run_case` itself stays unchanged.
- **Order:** within a run, method B cases (same wall, 40–120 min) start first and A cases (~4 min) fill the gaps. Long jobs first avoid a long tail at the end in which one B case runs alone.
- **Disk:** at < 20 GB free the runner pauses itself and says so on the dashboard.

**State and recovery**
- **Local state** is kept in `~/hpc/state.json`, written atomically. It holds each case's status (pending, running, done, failed, skipped), PID, start time and attempts.
- **After a runner restart:** cases whose processes still run are adopted again (PID and start time match). The runner then watches them through their files, since it can't wait on them directly.
- **After a reboot:**
  - running A cases start again;
  - running B cases continue from their last save point with `--transient --resume`, which saves up to 2 h.
- **Failed cases:** one automatic retry. After that the case counts as failed, with the last 50 log lines on the dashboard, and the run continues.

**Remote update of the runner:** set `runner_ref` and `state: pause`. When no case is running, the runner checks out that commit and restarts itself. Running cases are never affected by code updates, because a run keeps its pinned code commit.

**Notifications** come through GitHub issues, so the GitHub app on the phone shows them.
- **One issue per run**, opened when the run starts. Each event is a comment on it, which notifies:
  - a case failed after its retries;
  - the runner paused itself (disk);
  - the runner came back after a reboot or a long network loss;
  - the run finished, with a summary. The issue is closed then.
- **Not too many messages:** comments are batched to at most one per 30 min, except the final summary.
- **Access:** issues need a token, because a deploy key only works for git. It is a fine-grained access token limited to this repo with *Issues: read and write*. It is stored only on the HPC (`~/.config/stosslueften/token`, readable only by the user) and is never in the repo or in `status.json`.

## 6. Status data and dashboard

`status.json` (about 20–50 KB) contains:
- **runner:** state, last update, host, code commit, OpenFOAM version, a message;
- **machine:** load per core, RAM, free disk;
- **runs:** counts (done, running, failed, waiting), throughput, finish estimate (separate averages for A and B);
- **running cases:** layout, method, stage (mesh, flow, tracer, transient), progress, elapsed time, a thinned residual history;
- **finished:** the last 30, with t90, τ, airflow, method and runtime;
- **failures:** with log tails;
- **events:** control changes, retries, restarts;
- **history:** finished cases per hour.

**Page** (`hpc/site/`, static HTML + CSS + plain JavaScript, no framework, no build step)
- Reloads `status.json` every 60 s, with a cache-busting query.
- Deployed by a small GitHub Actions workflow on every push to `hpc-status`. Actions minutes are free for public repos, and this avoids the 10-builds-per-hour limit of branch-based Pages.

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│ STOSSLUEFTEN · HPC      ● RUNNING      updated 1 min ago      hpc-01 · a1b2c3d     │
├──────────────────────────────────────────────────────────────────────────────────┤
│ sweep-train-v1  ▕████████████░░░░░░░░▏ 92/150   done 89  failed 3  running 3   ETA Thu 14:20 │
├────────────────────┬────────────────────┬────────────────────┬───────────────────┤
│ slot 1  case_0412  │ slot 2  case_0398  │ slot 3  case_0415  │ CPU  ▮▮▮▮▮▮▮▮▮▮▮▮ │
│ same wall · B      │ opposite · A       │ adjacent · A       │ RAM  11 / 32 GB   │
│ transient  42 %    │ flow  1430/2000    │ mesh               │ disk 412 GB free  │
│ ╲__ residuals      │ ╲___ residuals     │                    │                   │
├────────────────────┴───────────┬────────┴────────────────────┴───────────────────┤
│ latest case_0397: room setup   │ streamlines at window height │ t90 88 s, τ 37 s │
│ [picture]                      │ [picture]                    │ 4,410 m³/h · A   │
├────────────────────────────────┴──────────────────────────────┴──────────────────┤
│ results so far: t90 per case (dots, colour = layout)  │ last finished · failures  │
├──────────────────────────────────────────────────────────────────────────────────┤
│ events: 14:02 paused (control.yaml) · 14:05 running · 13:40 case_0377 failed (retry) │
└──────────────────────────────────────────────────────────────────────────────────┘
```

**Look:** like `analysis.monitor`, an engineering tool rather than a product page.
- Dark background, thin lines, numbers in a monospace font.
- Fixed colour meanings: blue = method A or fresh air, orange = method B or old air, red only for failures, gray for waiting.
- No gradients, glows, emoji or animations beyond the progress bars.
- Stacks to one column on a phone.
- **Stale data is shown clearly:** without an update for 15 min the badge turns to `OFFLINE?` with the time of the last contact.

## 7. Robustness: what can go wrong

| Failure | Effect | Handling |
|---|---|---|
| HPC loses internet / GitHub down | Status stale, control not received | Cases keep running. Git calls retry with backoff, and unsent results are pushed later. Dashboard shows `OFFLINE?`. |
| Runner crashes | No reconciling | systemd restarts it within 10 s. State comes from `state.json`, and running cases are adopted. |
| Windows reboot / power cut | All processes die | Windows auto-login and a scheduled task start WSL. systemd starts the runner, which requeues running cases (B cases resume from their last save point). BIOS: power on after power loss. |
| WSL shuts down when idle | All processes die | A keep-alive task (`sleep infinity` started from Windows at logon), and `vmIdleTimeout=-1` in `.wslconfig`. Tested in phase 0. |
| A case hangs | Slot blocked | Timeout per method, kill, one retry, then failed. |
| A case fails | — | One retry, then failed with the log tail. The run continues. |
| Bad config pushed | — | The run is rejected before it starts, and the reason is shown on the dashboard. |
| Disk almost full | — | Auto-pause at < 20 GB free. |
| Windows Update restart | Like a reboot | Pause updates for the sweep's duration, and set active hours. |
| Two people edit control.yaml | Git merge on `main` as usual | The runner only reads it. |

**Emergency access:** if Windows or WSL itself hangs, git-based control can't help. Daniel then works on the HPC directly. The dashboard's `OFFLINE?` badge and the missing heartbeat show when that is needed.

## 8. HPC setup (phase 0)

The step-by-step guide with all scripts is [hpc/setup/README.md](hpc/setup/README.md). In short:

1. **Windows:**
   - power plan "never sleep";
   - hibernation off;
   - updates paused;
   - auto-login;
   - BIOS "restore on AC power loss".
2. **WSL2 with Ubuntu 24.04.**
   - `.wslconfig`: all 16 threads, `memory=24GB` (WSL's default is half of the 32 GB), and `vmIdleTimeout=-1`.
   - `/etc/wsl.conf`: `systemd=true`.
   - A Windows scheduled task at logon that starts the keep-alive.
3. **OpenFOAM v2606** from the openfoam.com Ubuntu packages, including the development part for `wmake` (needed for `tracerFoam`).
   - Also: `build-essential`, `python3-venv`, the system libraries for Gmsh, and `xvfb` for off-screen pictures if WSLg isn't usable from a service.
4. **Repo:**
   - clone into the Linux home folder (not `/mnt/c`);
   - venv, `pytest`;
   - a deploy key with write access, used only on this machine;
   - git author `stosslueften-hpc`.
5. **Reference check:**
   - Run the default case, `demo_1` and one same-wall case on the HPC with the same `--procs` as on the laptop.
   - The cell count must be identical, and t90 within 1 %. Otherwise we find the cause before mixing results from two machines.
6. **Measure throughput** with `procs_per_case: 4` (the same as in the benchmark comparison runs):
   - Compare 2 slots (one per 4 physical cores) with 3 and 4 slots (using the second thread of each core).
   - CFD usually gains little from those extra threads, so 2–3 slots is the expected result.
   - Record the time per A case and per B case, choose `slots`, and note the choice.
   - Result: see *Phase 0 results* below.
   - The 8845HS is a laptop chip. If the PC is a mini PC, check during the pilot that it doesn't throttle under days of full load. Its temperature can't be read from inside WSL, so check it in Windows.

**Phase 0 results (2026-10-15).** From the PC's output files (reference check, throughput, tests):
- **Reference check passed:** the PC reproduces the laptop.
  - Identical cell counts in all cases.
  - Method A: t90 and τ within 0.2 % (default, demo_1) and 0.9 % (same wall; run on 4 instead of 8 cores).
  - Method B (same wall): t90 +2.0 %, τ +2.7 %, within the 5 % tolerance.
  - The window-flow numbers of B differ more (window 1: 133 vs 259 m³/h). That fits the known problem with that measurement (PLAN.md §5 finding 6) and does not affect the tracer.
- **Speed per case:** about the same as the laptop at its best, but steady (no throttling seen).
  - Default case: flow 171 s (laptop 170–247 s).
  - Same-wall B case alone on 4 cores: 59 min.
  - Meshing is a little slower (16–18 s vs 12 s).
- **Throughput** (method A, 4 cores per case): 16.9, 17.0 and 16.8 cases per hour with 2, 3 and 4 slots.
  - The 8 physical cores are fully used at 2 slots; the extra threads add nothing (CFD is limited by memory bandwidth).
  - **Decision: `slots: 2`, `procs_per_case: 4`.**
- **Estimated sweep time on this PC:** 120 A cases ≈ 7 h, plus 60 B cases ≈ 40 h (two at a time, ~80 min each), so **about 2 days**. That is the same as the laptop; the gain is a dedicated, steady machine.
  - Running a separate run on the laptop at the same time (e.g. the test set) would roughly halve this, without any shared case list.
- **Still to confirm:** the machine check output (`cases/check_machine.txt`) and the reboot test (guide steps 5 and 6) were not on the drive. The tests passed (130) and off-screen pictures work.

## 9. Build phases

| Phase | Work | Done when | Effort |
|---|---|---|---|
| 0 | HPC setup and reference check (§8) | The reference cases match the laptop; reboot recovery works | ½–1 day |
| 1 | Runner core: slots, order, pause/stop, timeouts, retries, adopt/requeue, `state.json`. Tested on the laptop with shortened cases and fake jobs. | Kill tests pass: killing the runner, a case or WSL loses nothing | 1 day |
| 2 | Git channel: read control, force-push status, push results, offline behaviour | Works with the network unplugged and replugged | ½ day |
| 3 | Dashboard and Pages workflow, built and tested with recorded `status.json` snapshots | Readable on laptop and phone; stale data clearly marked | 1 day |
| 4 | Pilot: 10–15 real cases (all layouts, including B) on the HPC for a day. Exercise pause, stop, retry, skip, reboot and network loss remotely. | Every action works from the phone and the HPC recovers by itself | 1 day |
| 5 | Full sweep (train + test) | `hpc-results` complete, `results/summary.csv` built | 2–3 days compute |

**Prerequisites from PLAN.md §9:**
- the checks before the sweep (fine-mesh check of a same-wall case with B, iteration-averaged flow for A, airflow from face fluxes);
- then the sweep generator (writes `configs/sweep/<run_id>/`) and the dataset writer (reads `hpc-results`). These are built alongside the runner, once the benchmarks are done.

Until then, phases 0–4 use the existing configs in `configs/comparison/` and `configs/demo/`.

**New code**
- `hpc/runner.py`: the loop and the cases.
- `hpc/gitsync.py`: fetch, show, push with retries.
- `hpc/status.py`: builds `status.json`, reusing the progress parsing of `analysis.monitor`.
- `hpc/site/`: the dashboard.
- `hpc/setup/`: systemd unit, `wsl.conf`, `.wslconfig` example, Windows task, setup notes.
- Tests in `tests/test_hpc_*.py`.

`cfd.queue` and `analysis.monitor` stay as they are for local use.

## 10. Decisions (Daniel, 2026-10-15)

1. **Visibility:** the repo stays public. The dashboard, control files and `hpc-results` may be readable by anyone. No secrets go into the repo; the deploy key and the issue token stay on the HPC.
2. **Hardware:** Ryzen 7 8845HS (8 cores, 16 threads), 32 GB RAM, 1 TB disk, Windows 11.
3. **The machine** is dedicated to the sweep: auto-login, no sleep, updates paused.
4. **Emergency access:** physical access by Daniel; no remote desktop or VPN needed.
5. **Notifications:** yes, through GitHub issues (§5).
6. **A second runner on the laptop:** not in the first version.
7. **Order:** the sweep generator and dataset writer are built later, once the remaining benchmarks are done.

## 11. Implementation details (phases 1–4)

**Modules** in `hpc/`, each testable on its own:

| Module | Job |
|---|---|
| `runner.py` | The 60 s loop and the command line (`python -m hpc.runner`, `--fake` for tests) |
| `state.py` | `~/hpc/state.json`: cases with status, attempts, PID and process start time. Atomic writes; allowed status changes only. |
| `control.py` | Reads and validates `hpc/control.yaml` and `hpc/runs/*.yaml` from `origin/main` (`git show`) |
| `jobs.py` | Starts, watches, kills and re-adopts case processes; decides between rerun and resume |
| `results.py` | After a case: copies summary, config and curves; two JPEG pictures (setup, streamlines; ~80 KB each) |
| `status.py` | Builds `status.json`, using the progress readers of `analysis.monitor` |
| `gitsync.py` | `fetch`, `show`, and pushes to `hpc-status` (one commit, amended and force-pushed) and `hpc-results` (appended). Retries after 1, 2, 5, 10 min; never waits on GitHub. |
| `notify.py` | One issue per run, comments batched (§5), plain `urllib` and the token file |
| `site/` | `index.html`, `app.js`, `style.css` (no framework), `sample_status.json` for testing |
| `setup/` | phase 0, plus `stosslueften-runner.service` and the Pages workflow |

**Cases**
- Each case starts as `python -m cfd.run_case --config … --procs 4` with `start_new_session=True` (its own process group, so a stop kills OpenFOAM's MPI processes too). Its output goes to `cases/<case>.runner.log`.
- **Order:** same-wall (B) cases first, then A cases. A run's cases use all slots; runs follow each other in the order given in `control.yaml`.
- **Restart rules:**
  - A case interrupted during the A stage runs again from the start.
  - A same-wall case interrupted during B, with `summary.json` present and `transient/processor*` folders, continues with `--transient --resume`.
- **Adopting after a runner restart:** a case whose PID still runs with the recorded start time is watched again by its files: `summary.json` with the `"transient"` part for B, and the log. If the process is gone and the result is incomplete, the case fails or goes back to waiting.
- **Timeouts:** A 45 min, B 5 h. Then the case is killed, retried once, and after that fails.

**Code versions**
- **Pinned per run:** a run's cases use a git worktree of its pinned commit, `~/hpc/code/<sha>`.
- **Shared folders:** the cases folder is the same for all versions. `run_case`, `queue` and `monitor` will read it from the environment variable `STOSSLUEFTEN_CASES` (default `cases`). That is a small change to the existing code.
- **Shared venv:** if `requirements.txt` of a new run differs, the runner does not start the run, and says so on the dashboard.
- **Our solver:** `tracerFoam` is rebuilt with `wmake` when a run starts (fast if unchanged). Only one code version runs at a time.

**Service:** `systemd` unit with `Restart=always` and **`KillMode=process`**, so that a runner restart does not kill the running cases. The unit starts a small wrapper that loads OpenFOAM (`hpc/setup/foam_env.sh`) and then the runner.

**`status.json` (version 1):**
- `schema`, `updated_utc`;
- `runner`: state, host, code commit, message;
- `machine`: load per thread, RAM, disk;
- `runs`: per run the counts, cases per hour, finish estimate;
- `running`: per slot the case, layout, method, stage, progress, elapsed time, and the last 200 residual values (thinned);
- `finished`: the last 30;
- `failures`: with log tails;
- `events`: the last 50;
- `latest`: case id and the two picture names.

**Testing before the pilot**
1. **Unit tests:**
   - status changes;
   - control file checks: a wrong value is rejected with a clear message;
   - the case order;
   - the finish estimate;
   - `status.json` fields;
   - result packaging;
   - notification batching (with a fake sender).
2. **Fake cases:** `hpc/fake_case.py` has the same command line and output files as `run_case`. It takes seconds, can be set to fail or hang, and writes a fake log. The whole loop then runs in minutes:
   - pause, stop, retry, skip;
   - timeouts;
   - killing the runner (adopting);
   - killing everything at once, as in a reboot (rerun or resume).
3. **Git without GitHub:** a local bare repository in a temp folder stands in for GitHub: control on `main`, status and results branches, a push failing and recovering.
4. **Dashboard:** open `site/index.html` with `sample_status.json`. Check states, old data (`OFFLINE?`), many failures, and phone width.
5. **Then phase 4 (pilot) on the simulation PC** with real cases.
