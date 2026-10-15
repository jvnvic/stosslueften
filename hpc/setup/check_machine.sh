#!/bin/bash
# Checks that the simulation PC is ready (hpc/setup/README.md, step 5). Run inside WSL from the repository:
#   bash hpc/setup/check_machine.sh | tee cases/check_machine.txt
# Prints one line per check (OK / WARN / FAIL) and exits with 1 if anything failed.
cd "$(dirname "$0")/../.." || exit 1
mkdir -p cases
fails=0
ok()   { printf 'OK    %s\n' "$*"; }
warn() { printf 'WARN  %s\n' "$*"; }
fail() { printf 'FAIL  %s\n' "$*"; fails=$((fails + 1)); }

echo "--- hardware visible to WSL"
threads=$(nproc)
if [ "$threads" -ge 16 ]; then ok "$threads CPU threads"; else warn "$threads CPU threads (expected 16, see .wslconfig)"; fi
mem_gb=$(awk '/MemTotal/ {printf "%d", $2 / 1048576}' /proc/meminfo)
if [ "$mem_gb" -ge 20 ]; then ok "$mem_gb GB RAM"; else warn "$mem_gb GB RAM (expected about 24, see .wslconfig)"; fi
free_gb=$(df -BG --output=avail "$HOME" | tail -1 | tr -dc '0-9')
if [ "$free_gb" -ge 100 ]; then ok "$free_gb GB free disk"; else fail "only $free_gb GB free disk (the sweep needs about 50 GB)"; fi
case "$(pwd)" in
    /mnt/*) fail "the repository is on a Windows drive ($(pwd)); clone it into the Linux home folder" ;;
    *) ok "repository in the Linux file system ($(pwd))" ;;
esac

echo "--- WSL"
state=$(systemctl is-system-running 2>/dev/null)
case "$state" in
    running|degraded) ok "systemd is $state" ;;
    *) fail "systemd is not running ('$state'): check /etc/wsl.conf, then 'wsl --shutdown' in Windows" ;;
esac
if pgrep -a -x sleep | grep -q infinity; then ok "keep-alive process (sleep infinity) is running"
else warn "no keep-alive process: Start-ScheduledTask -TaskName 'stosslueften WSL keep-alive' (guide step 4)"; fi
winprofile=$(cd /mnt/c 2>/dev/null && /mnt/c/Windows/System32/cmd.exe /c "echo %USERPROFILE%" 2>/dev/null | tr -d '\r')
wslconfig=""
[ -n "$winprofile" ] && wslconfig="$(wslpath "$winprofile")/.wslconfig"
if [ -n "$wslconfig" ] && [ -f "$wslconfig" ] && grep -q "^vmIdleTimeout=-1" "$wslconfig"; then ok ".wslconfig has vmIdleTimeout=-1"
else warn "vmIdleTimeout=-1 not found in C:\\Users\\<you>\\.wslconfig (guide step 4)"; fi

echo "--- OpenFOAM"
if source hpc/setup/foam_env.sh 2>/dev/null; then
    if [ "$WM_PROJECT_VERSION" = "v2606" ]; then ok "OpenFOAM $WM_PROJECT_VERSION in $WM_PROJECT_DIR"
    else fail "OpenFOAM version is $WM_PROJECT_VERSION, the laptop uses v2606"; fi
    for tool in blockMesh snappyHexMesh simpleFoam pimpleFoam tracerFoam mpirun; do
        if command -v "$tool" >/dev/null; then ok "$tool found"; else fail "$tool not found"; fi
    done
    if mpirun --bind-to none -np 4 true >/dev/null 2>&1; then ok "mpirun starts 4 processes"; else fail "mpirun -np 4 failed"; fi
else
    fail "OpenFOAM v2606 not found (guide step 3)"
fi

echo "--- Python"
if .venv/bin/python -c "import gmsh, pyvista, vtk, numpy, scipy, pandas, psutil, yaml" 2>/dev/null; then ok "Python packages"
else fail "Python packages missing: .venv/bin/pip install -r requirements.txt"; fi
if .venv/bin/python -m pytest -q > cases/check_pytest.log 2>&1; then ok "tests: $(tail -1 cases/check_pytest.log)"
else fail "tests failed, see cases/check_pytest.log"; fi
# Pictures: the runner will run as a service without a display, so test without one
render='import pyvista as pv; p = pv.Plotter(off_screen=True); p.add_mesh(pv.Sphere()); p.screenshot("cases/check_render.png")'
if env -u DISPLAY -u WAYLAND_DISPLAY .venv/bin/python -c "$render" >/dev/null 2>&1; then ok "pictures without a display"
elif env -u DISPLAY -u WAYLAND_DISPLAY xvfb-run -a .venv/bin/python -c "$render" >/dev/null 2>&1; then warn "pictures only with xvfb-run (fine, the runner will use it)"
else fail "pictures do not work, not even with xvfb-run"; fi

echo "--- GitHub"
remote=$(git remote get-url origin 2>/dev/null)
case "$remote" in
    github-stosslueften:*) ok "git remote uses the deploy key ($remote)" ;;
    *) warn "git remote is '$remote'; pushing needs the deploy key (guide step 3a)" ;;
esac
ssh_answer=$(ssh -o BatchMode=yes -o ConnectTimeout=10 -T github-stosslueften 2>&1)
case "$ssh_answer" in
    *"successfully authenticated"*) ok "GitHub accepts the deploy key" ;;
    *) fail "GitHub does not accept the deploy key: $ssh_answer" ;;
esac
if git ls-remote --exit-code origin main >/dev/null 2>&1; then ok "git can reach GitHub"; else fail "git ls-remote origin failed"; fi
token_file="$HOME/.config/stosslueften/token"
if [ -f "$token_file" ]; then
    perms=$(stat -c %a "$token_file")
    [ "$perms" = "600" ] || warn "the token file is readable by others ($perms): chmod 600 $token_file"
    code=$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $(cat "$token_file")" \
        https://api.github.com/repos/jvnvic/stosslueften)
    if [ "$code" = "200" ]; then ok "the issue token is valid"; else fail "the issue token is rejected (HTTP $code)"; fi
else
    warn "no issue token yet ($token_file); only needed from phase 2 on (guide step 9)"
fi

echo
if [ "$fails" -eq 0 ]; then echo "All checks passed."; else echo "$fails check(s) failed."; fi
exit $((fails > 0))
