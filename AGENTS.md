# AGENTS.md

Shared instructions for every AI assistant used in this repo (Claude Code, Codex, Copilot, Cursor, Gemini, …). Keep this file short and current. It is the single source of truth, and `CLAUDE.md` only imports it.

## What this project is

This is a uni project for the Master's course *Machine Learning* (Hochschule Hannover). We run automated **OpenFOAM** CFD simulations of *Stoßlüften* (short, intensive window ventilation) in one room with two windows. Each run produces one CSV row, and we train an **ML surrogate model** on the resulting dataset.

- Technical spec: [VENTILATION_CFD_PROJECT.md](VENTILATION_CFD_PROJECT.md). The spec was written before the decisions below, so this file wins wherever the two conflict.
- Status: **planning. There is no code yet.**
- Deadline: less than 6 weeks from 2026-10-14. Prefer the simplest approach that works.

## Decisions (team, 2026-10-14)

- **Scope:** Stage 1, meaning isothermal airflow plus a passive tracer. Stage 2 (wall and air temperatures) happens only if time remains.
- **ML targets:** scalar metrics (`t90_s`, `fresh_air_60s_pct`, `airflow_m3h`, …) and the replacement curve `fresh_fraction(t)`.
- **Windows:** Dreh-Kipp. Each window has a `mode` (`turn` | `tilt`) and an `opening_angle_deg`, and the sash is modelled as a solid obstruction. This replaces the spec's `opening_length_m`.
- **Solver:** first benchmark *steady flow + frozen tracer* against *transient PIMPLE + tracer* on one coarse case. Pick whichever allows about 150 or more runs.
- **Compute:** one PC (8 cores, 30 GB RAM), so meshes stay coarse and simulated time stays short.
- **Tools:**
  - OpenFOAM, ESI distribution (openfoam.com), running in **Docker**. The version is not pinned yet.
  - Gmsh Python API for geometry and meshing.
  - ParaView for visualization.
  - Python with pandas and scikit-learn for analysis and ML.
- **Language:** English for code, docs and the log.

## Rules for AI assistants

1. **Log your work in [log.md](log.md) before you finish a task.** Append an entry using the template at the top of that file: who, which tool/model, what the AI did, and what the humans decided. Verbatim prompts are not needed. The course requires this log.
2. The team are not experienced programmers. Write simple, readable code, explain CFD and physics choices in brief comments, and tell the user exactly how to run what you built.
3. Everything must work on Windows, macOS and Linux. CFD tools run in Docker. Don't use bash-only scripts for anything teammates run on their own machine.
4. Don't silently change the decisions above. Once the CSV columns are defined, don't change them silently either, because they are the ML dataset contract. Propose the change, and update this file once the team agrees.
5. Never commit generated case folders (`cases/`). Do commit the dataset CSVs (`results/`) so everyone can train models.
6. When you add commands or folders, update the two sections below.

## Commands

None yet. This is the target interface from the spec (§7), and it is not implemented:

```bash
python -m cfd.run_case --config configs/default.yaml
python -m sweeps.run_sweep --config configs/sweeps/screening.yaml
```

## Structure

Planned layout: spec §7, plus a folder for the ML notebooks.
