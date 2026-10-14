# AI Usage Log

The course requires us to document how AI was used in this project. Add one entry per working step, with the newest at the bottom. Exact prompts are not needed. Record who used which tool, what the AI did, and what the humans decided or checked.

Template:

    ## YYYY-MM-DD — Short title
    - **Who:** name
    - **AI tool / model:** e.g. Claude Code (Claude Opus 5.5), ChatGPT-6 (Medium effort)
    - **What the AI did:** …
    - **Human decisions / review:** …

---

## 2026-10-14 — Project specification
- **Who:** Daniel
- **AI tool / model:** ChatGPT-6 (Medium effort)
- **What the AI did:** Wrote the initial project specification, [VENTILATION_CFD_PROJECT.md](VENTILATION_CFD_PROJECT.md). It covers the goals, a two-stage CFD plan (airflow and tracer first, conjugate heat transfer second) and the tool choice (OpenFOAM, Gmsh, ParaView, Python). It also covers the parameter sweep, the CSV output schema, and the risks and non-goals.
- **Human decisions / review:** The team provided the project idea.

## 2026-10-14 — Repository setup and scoping
- **Who:** Daniel
- **AI tool / model:** Claude Code (Claude Opus 5.5)
- **What the AI did:**
  - Read the spec and checked the local machine. It found no OpenFOAM, Gmsh or ParaView installed, Docker available, and 8 cores with 30 GB RAM.
  - Pointed out that the spec does not cover the ML surrogate goal, and that the CFD cost of each run limits how big the dataset can be.
  - Asked eight scoping questions: ML target, CFD scope, compute, deadline, window model, solver approach, language and team.
  - Proposed two defaults: ESI OpenFOAM running in Docker, and keeping the dataset CSVs under version control in git.
  - Created `AGENTS.md` (shared instructions for all AI tools), `CLAUDE.md` (imports `AGENTS.md`), this log and `.gitignore`, and initialized the git repository.
  - Created the private GitHub repository `stosslueften` using the GitHub CLI and pushed the first commit.
- **Human decisions / review:**
  - Stage 1 is in scope, with Stage 2 as a stretch goal.
  - The surrogate predicts scalar metrics plus the air-replacement curve.
  - Simulations run on one PC, and the deadline is under 6 weeks away.
  - Windows are Dreh-Kipp, defined by turn/tilt mode plus angle.
  - The steady and transient solver approaches get benchmarked before choosing one.
  - Everything is in English.
  - The team works on mixed operating systems, so the instructions must be concise and usable with other AI models.

## 2026-10-14 — Data generation plan
- **Who:** Daniel
- **AI tool / model:** Claude Code (Claude Opus 5.5)
- **What the AI did:**
  - Asked eight planning questions: room and window size, window opening states, wind, simulated time, sampling, ML models, software setup and deliverables. Each came with a recommended default.
  - Checked package availability on Arch Linux. OpenFOAM v2606 is in the AUR as `openfoam-com`, ParaView is in the official repos, and Gmsh comes via pip.
  - Checked the OpenFOAM v2606 source code. `scalarTransportFoam` has only a constant diffusivity, which matters for the frozen-flow option, and `gmshToFoam` creates cell zones but no face zones.
  - Wrote `PLAN.md`, covering the fixed setup, varied inputs, output columns, pipeline, solver benchmark, checks, a 6-week schedule and risks.
  - Updated `AGENTS.md` to point to the plan.
- **Human decisions / review:**
  - The room is 4×5×2.5 m with 1.0×1.25 m windows.
  - Window modes are chosen independently per window, with the turn angle sampled and the tilt angle fixed.
  - Wind comes from one fixed direction.
  - Each run simulates 600 s, with the curve sampled every 30 s.
  - Inputs are sampled with a Latin hypercube, plus a separate test set.
  - OpenFOAM is installed natively instead of in Docker.
  - The ML models will follow the course requirements. The deliverables are not defined yet.
  - Focus on data generation first; the ML part will be planned later.
