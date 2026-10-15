#!/bin/bash
# Ubuntu part of the simulation PC setup (hpc/setup/README.md, step 3). Run inside WSL from the repository:
#   bash hpc/setup/install_ubuntu.sh
# Installs the system packages, OpenFOAM v2606, the Python environment and our solver, then runs the tests.
# Running it again is harmless. It asks for your Linux password (sudo).
set -eo pipefail
cd "$(dirname "$0")/../.."   # repository root
step() { printf '\n=== %s\n' "$*"; }

step "1/6 System packages"
sudo apt-get update
# build tools for our solver, Python, the libraries the Gmsh and VTK wheels need, and xvfb for pictures
sudo apt-get install -y build-essential git curl ca-certificates python3-venv python3-dev python3-tk \
    libglu1-mesa libgl1 libegl1 libosmesa6 libx11-6 libxext6 libxrender1 libxcursor1 libxfixes3 \
    libxft2 libxinerama1 libxi6 libfontconfig1 xvfb

step "2/6 OpenFOAM v2606 (openfoam.com Ubuntu packages)"
if ! dpkg -s openfoam2606-default >/dev/null 2>&1; then
    curl -fsSL https://dl.openfoam.com/add-debian-repo.sh | sudo bash
    sudo apt-get update
    if ! sudo apt-get install -y openfoam2606-default; then
        echo "Could not install openfoam2606-default. The current package names are listed on"
        echo "https://develop.openfoam.com/Development/openfoam/-/wikis/precompiled/debian"
        exit 1
    fi
fi
# wmake and the headers are needed to compile our solver tracerFoam (may already be part of -default)
sudo apt-get install -y openfoam2606-dev || echo "(no separate openfoam2606-dev package; step 6 shows whether wmake works)"

step "3/6 WSL settings: /etc/wsl.conf (systemd on)"
if [ -f /etc/wsl.conf ] && [ ! -f /etc/wsl.conf.bak ]; then
    sudo cp /etc/wsl.conf /etc/wsl.conf.bak
fi
{ cat hpc/setup/wsl.conf; printf '\n[user]\ndefault=%s\n' "$(whoami)"; } | sudo tee /etc/wsl.conf >/dev/null
echo "Takes effect after 'wsl --shutdown' in Windows (guide step 4)."

step "4/6 Shell: the command 'of' loads OpenFOAM, as on the laptop"
if ! grep -q "^alias of=" ~/.bashrc; then
    echo "alias of='source /usr/lib/openfoam/openfoam2606/etc/bashrc'" >> ~/.bashrc
fi

step "5/6 Python environment (.venv)"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

step "6/6 Compile tracerFoam, run the tests"
source hpc/setup/foam_env.sh
(cd cfd/solvers/tracerFoam && wmake)
command -v tracerFoam
.venv/bin/python -m pytest -q

printf '\nUbuntu part done. Next: guide step 4 (Windows settings).\n'
