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

## 2026-10-14 — Python environment
- **Who:** Daniel
- **AI tool / model:** Claude Code (Claude Opus 5.5)
- **What the AI did:**
  - Created the Python virtual environment (Python 3.14) with `gmsh`, `numpy`, `pandas`, `scipy` and `pyyaml`, and pinned their versions in `requirements.txt`.
  - Ran a Gmsh smoke test: meshed a room box with a window opening and exported it in the MSH 2.2 format that OpenFOAM's `gmshToFoam` reads.
  - Read the AUR package's install notes. OpenFOAM is loaded with `of`, and ParaView has to use its built-in OpenFOAM reader.
  - Added the setup commands to `AGENTS.md`.
- **Human decisions / review:** Daniel started the OpenFOAM v2606 build (AUR `openfoam-com`) and asked the AI to commit, push and set up the Python environment.

## 2026-10-14 — Geometry and mesh generator
- **Who:** Daniel
- **AI tool / model:** Claude Code (Claude Opus 5.5)
- **What the AI did:**
  - Wrote the case config format (`configs/default.yaml`) and a loader that checks it (`cfd/config.py`). Unknown keys, missing keys and invalid values stop with a clear error.
  - Wrote the window placement logic (`geometry/windows.py`): wall coordinate frames, turn/tilt sash rotation, and checks that windows fit on their wall, don't overlap, and that open sashes don't collide.
  - Wrote the Gmsh model and mesh generator (`geometry/generate.py`). It builds the room, 0.3 m walls, window openings, sashes and outdoor domain, names the boundary patches, sets refinement zones and writes a mesh `gmshToFoam` can read.
  - Made one modeling choice: each sash turns about a solid 4 cm hinge post. Without it, the sash and wall form razor-thin wedges near the hinge that can't be meshed.
  - Added 56 automated tests. Meshed all 21 distinct layout, mode and angle combinations: each takes about 1 s and gives about 155–160k cells, with no poor-quality cells.
- **Human decisions / review:** Daniel asked the AI to start the geometry generator while OpenFOAM compiles.

## 2026-10-14 — README
- **Who:** Daniel
- **AI tool / model:** Claude Code (Claude Opus 5.5)
- **What the AI did:**
  - Wrote `README.md` covering the project summary, status, what is simulated, setup, usage, repository layout and links to the other documents.
  - Added Daniel's Gmsh screenshot of the default geometry as `docs/images/geometry_default.png`.
  - Added a rule to `AGENTS.md` that every AI assistant keeps the README up to date.
- **Human decisions / review:** Daniel asked for a README that is always kept current, and provided the screenshot.

## 2026-10-14 — 3D renders of the room setup
- **Who:** Daniel
- **AI tool / model:** Claude Code (Claude Opus 5.5)
- **What the AI did:**
  - Wrote `geometry/render.py`, which renders the same Gmsh geometry the simulation uses off-screen with PyVista. It shows a cut-away view without the roof, with solid walls, blue sashes, the floor, the ground and a wind arrow. Several cases can be placed side by side.
  - Added one example config per layout in `configs/examples/`.
  - Adjusted lighting and camera over a few render rounds, checking each picture. The result is a sun from the south-west, a fill light from the east, a soft camera light and soft corner shadows.
  - Replaced the wireframe screenshot in the README with a three-layout overview (`docs/images/layouts.png`) and added a picture of the default case.
  - Added PyVista and VTK to `requirements.txt` and added a test.
- **Human decisions / review:** Daniel asked for more appealing pictures than the Gmsh wireframe screenshot.
