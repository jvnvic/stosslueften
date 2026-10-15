#!/bin/bash
# Runs the reference cases on the simulation PC exactly as on the laptop (hpc/setup/README.md, step 7):
#   default and demo_1 with method A on 8 cores, the same-wall benchmark case with method B on 4 cores.
# Takes about 1-1.5 h. Start it detached from the repository root:
#   setsid nohup bash hpc/setup/reference_check.sh > cases/reference_check.out 2>&1 &
cd "$(dirname "$0")/../.." || exit 1
source hpc/setup/foam_env.sh || exit 1
PY=.venv/bin/python
echo "=== method A, 8 cores: default, demo_1   $(date +%T)"
$PY -m cfd.queue configs/default.yaml configs/demo/demo_1.yaml
echo "=== method B, 4 cores: same-wall benchmark case   $(date +%T)"
$PY -m cfd.queue --transient --procs 4 configs/benchmark/snappy_same_wall.yaml
echo "=== comparison with the laptop   $(date +%T)"
$PY -m hpc.setup.compare_reference
