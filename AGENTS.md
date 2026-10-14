# AGENTS.md

Shared instructions for every AI assistant used in this repo (Claude Code, Codex, Copilot, Cursor, Gemini, …). Keep this file short and current. `CLAUDE.md` only imports it.

## What this project is

This is a uni project for the Master's course *Machine Learning* (Hochschule Hannover). Automated **OpenFOAM** CFD simulations of *Stoßlüften* (window ventilation) in one room with two windows produce a CSV dataset. An **ML surrogate model** will be trained on it later.

- **Current phase: data generation** (the CFD pipeline). The ML part will be planned later.
- [PLAN.md](PLAN.md) holds the agreed decisions, dataset columns and schedule. **Read it first.**
- [VENTILATION_CFD_PROJECT.md](VENTILATION_CFD_PROJECT.md) is the original background spec. PLAN.md wins wherever they differ.
- Status: no code yet. Deadline: less than 6 weeks from 2026-10-14.

## Environment

- CFD runs only on Daniel's Arch Linux PC. It uses a native OpenFOAM v2606 (openfoam.com, AUR `openfoam-com`, no Docker), ParaView, and a Python venv with the Gmsh API.
- Teammates use Windows, macOS or Linux and have little programming experience. They don't run CFD; they work with the CSV results.

## Rules for AI assistants

1. **Log your work in [log.md](log.md) before you finish a task.** Append an entry using the template at the top of that file: who, which tool/model, what the AI did, and what the humans decided. Verbatim prompts are not needed. The course requires this log.
2. Write simple, readable code. Explain CFD and physics choices in brief comments, and tell the user exactly how to run what you built.
3. Don't silently change the decisions in PLAN.md or, once they are frozen, the CSV columns, because they are the ML dataset contract. Propose the change, and update PLAN.md once the team agrees.
4. Never commit generated case folders (`cases/`). Do commit the dataset CSVs (`results/`).
5. The CFD pipeline may assume Linux with OpenFOAM sourced. Anything teammates run must work on any OS.
6. When you add commands or folders, update the two sections below.

## Commands

None yet. This is the target interface from PLAN.md §4:

```bash
python -m cfd.run_case --config configs/default.yaml
python -m sweeps.run_sweep --config configs/sweeps/screening.yaml
```

## Structure

Planned layout: spec §7.
