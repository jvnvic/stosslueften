#!/bin/bash
# Started by systemd (stosslueften-runner.service): load OpenFOAM, then run the sweep runner.
cd "$(dirname "$0")/../.." || exit 1
source hpc/setup/foam_env.sh || exit 1
exec .venv/bin/python -m hpc.runner --home "$HOME/hpc" --repo "$(pwd)"
