# Stoßlüften CFD — Project Specification and Prototype Plan

**Status:** Initial research and implementation plan  
**Date:** 2026-10-14  
**Primary simulation software:** **OpenFOAM** (open source)  
**Working language:** Python for automation; OpenFOAM dictionaries and scripts for CFD setup.

## 1. Project goal

**Build a reproducible, fully automated, open-source 3D CFD framework to investigate and optimize short-duration natural room ventilation (“Stoßlüften”) through two adjustable windows.**

The framework must:

1. Model one fixed-size rectangular room with **exactly two windows**, each with a configurable position along its assigned wall.
2. Support **three window layouts**: both windows on the **same wall**, on **opposite walls**, or on **adjacent walls** (corner configuration).
3. Vary **wind speed**, **window positions**, **opening angles**, and **opening lengths** through programmatically generated test cases.
4. Simulate air movement and the **time-dependent replacement of indoor air by outdoor air**, and visualize velocity fields, streamlines, and tracer concentration.
5. In a second prototype, simulate **time-varying temperature in both room air and solid walls**, including their thermal inertia and the cooling/reheating process.
6. Execute parameter sweeps without manually changing CFD case files, calculate comparable performance metrics, and export **one CSV row per simulation** with all input parameters and outcome metrics. Save time histories separately.
7. Eventually identify arrangements that achieve **effective air replacement with low thermal penalty**; the objective is ventilation effectiveness, not simply maximum window flow.

**Scientific distinction:** The initial model does **not** directly simulate oxygen consumption or CO2 emission. It transports a passive tracer representing the **original indoor air**. This estimates air replacement. Explicit oxygen/CO2 species transport and occupant sources can be added later if needed.

## 2. Scope and adjustable geometry

### Room

- Room width `room_width_m`, depth `room_depth_m`, and height `room_height_m` are set **once per project** and remain fixed during optimization.
- Coordinates: `x` horizontal, `y` horizontal, `z` vertical. Adopt a documented wall naming convention (`north`, `south`, `east`, `west`) and a single origin.
- The first prototype uses an empty room; furniture, occupants, radiators, infiltration and solar radiation are outside the initial scope.

### Two windows

Define each window independently:

- `wall`: wall identifier.
- `x_position_m`: **local horizontal distance measured along its assigned wall from a defined corner** (not necessarily global x). Convert to global coordinates in the geometry generator. For east/west walls this corresponds to a local coordinate along the wall, not the global x axis.
- `sill_height_m`, `window_height_m`, `window_width_m`: fixed initial dimensions (optionally configurable in later versions).
- `opening_angle_deg`: casement sash opening angle. Model the **rotated sash as a physical flow obstruction**, not merely as an ideal open area.
- `opening_length_m`: the opening extent to be swept; **define this precisely in implementation**. Initial proposal: effective unobstructed opening width/length, independent of sash angle only if a physically consistent geometry can be produced. A safer alternative is to define the physical sash/window width and calculate opening clearance from angle. Do not independently change mutually dependent geometric variables without defining the mechanism.
- Validate against wall boundaries, window overlap, impossible sash geometries, and intersections with other solids.

Supported layouts:

| Layout | Description | Geometry implications |
|---|---|---|
| `same_wall` | Both windows share one exterior wall | Both positions use the same wall-local coordinate; enforce non-overlap |
| `opposite_walls` | Windows face each other on opposing walls | Supports cross-ventilation |
| `adjacent_walls` | Windows occupy neighboring perpendicular walls | Corner-room ventilation |

In all layouts, **both windows' positions are configurable**. Start with one predefined pair of walls per layout, then generalize the wall-pair selection.

### External domain and wind

- Include a simplified **outdoor fluid region around the building/facades**. A wind-speed boundary applied directly at one window does not generally capture facade pressure or recirculation, particularly with two windows on the same wall.
- Specify `wind_speed_ms`, `wind_direction_deg`; keep wind direction fixed in initial screening unless deliberately included in a sweep.
- Set external domain extents and inlet/outlet/open boundary conditions consistently; check domain-size sensitivity.
- Start with isothermal air in Stage 1; include buoyancy in Stage 2.

## 3. Tools and architecture

| Component | Selected tool | Purpose |
|---|---|---|
| CFD solver | **OpenFOAM** | Flow and scalar transport; later conjugate heat transfer |
| Geometry and mesh | **Gmsh Python API** | Generate the room, exterior region, windows/sashes and meshes from parameters |
| Controller | **Python** | Case creation, run orchestration, parameter sweeps, error handling |
| Visualization | **ParaView** | Streamlines, vectors, tracer/temperature contours, animations |
| Scripted visualization | `pvpython` / optional PyVista | Automated screenshots and batch plots |
| Post-processing | Python (NumPy, pandas) + OpenFOAM function objects | Metrics, plots, CSV summaries |
| Later optimization | Optuna or SciPy | Sampling and multi-objective search |

**Version caveat:** OpenFOAM has multiple actively maintained distributions with differing solver names, function-object configurations, and tutorials. Pin one distribution/version in the project environment and test the selected scalar-transport coupling against it; avoid mixing incompatible documentation.

**Solver plan:**

- **Stage 1:** transient turbulent airflow (e.g. a version-appropriate incompressible PIMPLE solver) **plus passive scalar transport** via a compatible function object or coupled transport solver. Confirm scalar transport works with the chosen solver and flux field. Use RANS as the initial turbulence approach.
- **Stage 2:** `chtMultiRegionFoam` (or the corresponding multi-region CHT solver in the chosen OpenFOAM release) for **transient conjugate heat transfer** between fluid and solid walls, with buoyancy and tracer transport in the fluid region. `buoyantPimpleFoam` with imposed wall temperatures is useful as an intermediate check, but **does not by itself model changing solid-wall temperatures**.

Documentation:
- OpenFOAM solver reference: https://www.openfoam.com/documentation/user-guide/a-reference/a.1-standard-solvers
- `chtMultiRegionFoam`: https://doc.openfoam.com/2212/tools/processing/solvers/rtm/heat-transfer/chtMultiRegionFoam/
- `buoyantPimpleFoam`: https://doc.openfoam.com/2212/tools/processing/solvers/rtm/heat-transfer/buoyantPimpleFoam/
- Passive scalar transport: https://doc.openfoam.com/2606/tools/post-processing/function-objects/solvers/scalarTransport/
- Gmsh: https://gmsh.info/
- ParaView: https://www.paraview.org/

## 4. Prototype stage 1 — Air exchange, no wall-temperature evolution

### Goal

**Get a trustworthy, automated CFD pipeline working for airflow and indoor-air replacement with two configurable windows in all three layouts.** No heat transfer is solved. All air is treated as isothermal.

### Physics and boundary conditions

- Solve transient 3D air velocity and pressure; initially use a RANS turbulence model (candidate: `kOmegaSST`, subject to mesh/near-wall constraints).
- Transport a passive tracer concentration `C`:
  - `C(t=0) = 1` inside the room (original indoor air).
  - `C = 0` in outdoor inflow (fresh outdoor air).
  - Treat outflow with a suitable flux-aware condition and prevent unphysical incoming tracer during flow reversal.
  - Use physically consistent molecular/turbulent scalar diffusivity and check boundedness and mass balance.
- Indoor air replacement fraction: `fresh_fraction(t) = 1 - volumeAverage(C_room(t))`. This is a proxy for air replacement, **not a physiological O2 concentration**.
- Run a fixed interval or until a specified replacement target is reached.

### Minimum deliverables

- Python-configured geometry generation for `same_wall`, `opposite_walls`, `adjacent_walls` and independent window positions.
- Mesh import/conversion and `checkMesh` validation.
- Repeatable CFD case generation and solver execution from command line.
- ParaView visualization of 3D flow, streamlines and tracer concentration over time.
- Automated extraction of air replacement curve and ventilation performance.
- CSV summary including *all* inputs, case ID, success/failure and performance metrics.
- Basic verification (mass conservation, mesh refinement, time-step sensitivity).

### Definition of done

A user can change a configuration file and execute **one command** to generate, validate, simulate and analyze a case. A small automatic sweep covering **all three layouts** produces valid CSV rows and at least one reproducible streamline/tracer visualization for a successful case. Invalid configurations fail with a clear error.

## 5. Prototype stage 2 — Dynamic air and wall temperatures

### Goal

**Extend Stage 1 to predict the coupled, time-dependent cooling and reheating of air and wall solids during and after Stoßlüften.** Keep the parameter-sweep architecture and air-exchange metrics from Stage 1.

### Physics and geometry

- Use conjugate heat transfer (CHT): **convection in indoor/outdoor air + heat conduction/storage in solid wall regions**.
- Specify wall layers/material properties: density `rho`, specific heat `cp`, conductivity `k`, layer thickness; distinguish exterior walls from internal partitions if needed.
- Specify initial temperatures for indoor air, outdoor air and the **wall temperature field** (initially a uniform temperature per wall or a simplified through-thickness profile).
- Account for buoyancy due to temperature differences; avoid assuming wind is the only driving force.
- Model two consecutive phases:
  1. **Ventilation:** windows open for specified `ventilation_duration_s`.
  2. **Recovery:** windows closed, allowing air and walls to thermally equilibrate; optionally enable a documented heating power/thermostat model.
- Changing windows from open to closed is a **topology/mesh or boundary-condition problem**. Initial implementation may use **two linked simulations**, mapping final fields from the ventilation case to a separately meshed closed-window case. Validate the mapping/conservation rather than assuming continuous topology changes work automatically.
- Keep the passive tracer to compare thermal cost at equal air-exchange effectiveness.

### Additional output metrics

- Indoor air average and spatial minimum/maximum temperature vs. time.
- Mean/surface-specific wall temperatures vs. time and initial-to-final change.
- Heat flux between air and walls; wall internal-energy change.
- Thermal comfort proxies, if carefully defined.
- Recovery time to chosen room-air target temperature, **conditional on heating assumptions**.
- Integrated heating energy when an explicit heating model exists; do **not** report absolute reheating energy from room-air temperature alone.
- Joint optimization: ventilation effectiveness **versus** thermal/energy penalty.

### Definition of done

For the same geometry and wind case, the system produces air/tracer results **and** physically plausible wall/air temperature histories during an open-window and closed-window phase. A reproducible two-case comparison demonstrates the tradeoff between fresh-air replacement and thermal loss. Both phases' outputs and parameters are automatically recorded.

## 6. Parameter sweep and result files

Initial sweep inputs:

| Parameter | Key | Scope |
|---|---|---|
| Window arrangement | `layout` | `same_wall`, `opposite_walls`, `adjacent_walls` |
| First window wall and position | `window1.wall`, `window1.x_position_m` | Configurable; within wall bounds |
| Second window wall and position | `window2.wall`, `window2.x_position_m` | Configurable; within wall bounds |
| Wind speed | `wind_speed_ms` | Range/list |
| Wind direction | `wind_direction_deg` | Fixed initially; later sweep |
| First/second sash angle | `window1.opening_angle_deg`, `window2.opening_angle_deg` | Separate or linked values |
| First/second opening length | `window1.opening_length_m`, `window2.opening_length_m` | Separate or linked; finalize physical meaning |
| Ventilation duration | `ventilation_duration_s` | Fixed initially; later optimization |
| Initial indoor and outdoor temperature | `indoor_initial_C`, `outdoor_C` | **Stage 2** |
| Wall material and initial temperature | `wall_material`, `wall_initial_C` | **Stage 2** |

**Proposed summary file:** `results/summary.csv` with one row per run and columns such as:

```csv
case_id,stage,status,layout,window1_wall,window1_x_m,window2_wall,window2_x_m,wind_speed_ms,wind_direction_deg,window1_angle_deg,window2_angle_deg,window1_opening_length_m,window2_opening_length_m,ventilation_duration_s,t90_s,fresh_air_60s_pct,airflow_m3h,room_air_final_C,wall_mean_final_C,wall_energy_change_kJ,solver_runtime_s,error_message
```

Unavailable metrics (e.g. thermal values in Stage 1, or `t90_s` when not reached) must be **blank/NaN**, not fabricated as zeros. Also write `results/timeseries/<case_id>.csv` with `time_s`, room-average tracer and Stage 2 temperature/heat metrics. Store solver logs, input configuration, mesh metadata, and visualizations under each case directory.

**Metric note:** `airflow_m3h` must clearly define whether it measures total inflow, total outflow or another quantity. `t90_s` means the first time the volume-average original-air tracer falls to 0.10; inspect non-uniformity too, since short-circuit airflow can leave stagnant pockets.

For the first automation test, use only a handful of cases. Once results are reproducible, move to space-filling sampling, then optional Optuna-based optimization rather than an enormous full-factorial sweep.

## 7. Suggested repository structure

```text
stosslueften-cfd/
├── README.md
├── PROJECT_SPEC.md
├── configs/
│   ├── default.yaml
│   └── sweeps/
├── geometry/
│   └── generate.py
├── cfd/
│   ├── templates/
│   └── run_case.py
├── analysis/
│   ├── metrics.py
│   └── visualize.py
├── sweeps/
│   └── run_sweep.py
├── tests/
├── cases/                 # generated, gitignored
└── results/               # generated, gitignored
    ├── summary.csv
    └── timeseries/
```

Suggested CLI (target interface, **not implemented yet**):

```bash
python -m cfd.run_case --config configs/default.yaml
python -m sweeps.run_sweep --config configs/sweeps/screening.yaml
```

## 8. Implementation order

1. **Environment:** Choose and pin OpenFOAM release/distribution; install Gmsh, ParaView and Python dependencies. Run an unmodified official tutorial before customizing.
2. **Baseline geometry:** Rectangular room, exterior flow region, fixed two-window opening geometry; generate a valid mesh with named wall/window boundary patches.
3. **Baseline flow:** Obtain convergent, physically sensible airflow with proper outdoor wind boundary conditions.
4. **Tracer:** Add original-air scalar transport, calculate volume-average concentration and export time history.
5. **Window variants:** Parameterize each window's wall, local position, sash angle and opening length; test all three configurations and collision constraints.
6. **Automation:** One-command case creation, meshing, solver, post-processing and CSV export; robust failure reporting.
7. **Stage 1 verification:** Mesh/time-step sensitivity, flow conservation, tracer bounds, domain-size sensitivity, and qualitative symmetry/check cases.
8. **Stage 2 CHT:** Add solid-wall regions, material properties, thermally coupled interfaces and buoyancy; verify on a simple canonical heat-transfer case first.
9. **Open/close sequence:** Implement and validate the ventilation-to-recovery transition, then calculate temperature and energy metrics.
10. **Optimization:** Pilot parameter screening, results ranking, and eventually multi-objective search.

## 9. Key research risks and decisions

- **Window opening geometry:** Angular sash position and opening length may not be independent for a conventional casement. Define a physically consistent parametric model before large sweeps.
- **Geometry coordinate convention:** Input “X position” means local wall coordinate; explicitly document orientation for all four walls.
- **External pressures:** Same-facade flow needs external pressure and can reverse with wind direction; no guaranteed inlet/outlet window.
- **Numerical cost:** A transient 3D RANS + scalar run can already be costly; CHT with wall solids and open/close stages costs more. Use coarse smoke tests and convergence checks before extensive sweeps.
- **Ventilation physics:** With no occupants/source terms, tracer removal is a meaningful initial proxy; real oxygen or CO2 predictions require species boundary conditions/sources.
- **Heat transfer:** A prescribed wall surface temperature cannot predict wall thermal inertia. Stage 2 needs actual solid regions, correct fluid-solid interfaces, and initial wall temperature fields.
- **Validation:** CFD visualizations are not evidence of accuracy on their own. Compare with simplified mass/energy balance predictions and, if feasible, real room tracer/temperature measurements.
- **Phase transition:** Remeshing/open-to-closed mapping can introduce numerical errors; validate temperature and tracer transfer carefully.

## 10. Explicit non-goals for the first prototypes

- Direct microscopic oxygen diffusion modeling, occupant respiration and CO2 sources.
- High-fidelity LES or DNS turbulence modeling.
- Furniture, thermal bridges, humidity/condensation and solar heating.
- Fully realistic building envelope, heating system controls and occupant thermal comfort metrics.
- A graphical configuration UI; YAML and CLI are sufficient for the first working prototype.

## 11. Immediate next task for implementation

**Implement Stage 1 only first.** Set up the repository, pin the OpenFOAM distribution, create a minimal YAML schema and a Gmsh geometry generator that handles the three window layouts and validates window positions. Then get **one** isothermal airflow-plus-tracer case running end-to-end before introducing parameter sweeps or Stage 2 heat transfer.

The project is considered successful when it yields a **reproducible ranking of two-window ventilation setups by air-replacement effectiveness and, in Stage 2, by thermal penalty**, with transparent inputs, checkable CFD calculations, streamlines/temperature visualizations, and machine-readable CSV outputs.
