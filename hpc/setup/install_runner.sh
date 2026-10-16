#!/bin/bash
# Installs and starts the sweep runner as a systemd service (hpc/README.md). Run inside WSL from the repository:
#   bash hpc/setup/install_runner.sh
# Running it again updates the service. Logs: journalctl -u stosslueften-runner -f
set -euo pipefail
cd "$(dirname "$0")/../.."
REPO=$(pwd)
case "$(systemctl is-system-running 2>/dev/null || true)" in
    running|degraded) ;;
    *) echo "systemd is not running: see hpc/setup/README.md step 4"; exit 1 ;;
esac
sed -e "s#@USER@#$(whoami)#g" -e "s#@REPO@#$REPO#g" -e "s#@HOME@#$HOME#g" hpc/setup/stosslueften-runner.service \
    | sudo tee /etc/systemd/system/stosslueften-runner.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable stosslueften-runner
sudo systemctl restart stosslueften-runner
sleep 3
systemctl --no-pager --lines=5 status stosslueften-runner || true
echo
echo "The runner is installed. It starts with WSL, restarts after errors, and follows hpc/control.yaml on main."
