# Setting up the simulation PC (phase 0)

Step-by-step guide for the Windows 11 PC that will run the sweep (Ryzen 7 8845HS, 32 GB RAM, 1 TB). The background is in [HPC_PLAN.md](../../HPC_PLAN.md).

- **Time:** about 2 hours at the machine, plus about 2 hours of unattended test runs.
- **At the end, the PC:**
  - runs Ubuntu in WSL2 with OpenFOAM v2606 and this repository;
  - restarts everything by itself after a reboot;
  - has produced the same results as the laptop.

**Checklist**
- [ ] 1. Windows basics: BIOS, updates, automatic login
- [ ] 2. Install WSL and Ubuntu
- [ ] 3. In Ubuntu: deploy key, clone, install script
- [ ] 4. Windows settings script, restart WSL
- [ ] 5. Machine check: all `OK`
- [ ] 6. Reboot test
- [ ] 7. Reference check: same results as the laptop (~1.5 h, unattended)
- [ ] 8. Throughput measurement (~30 min, unattended)
- [ ] 9. Issue token for notifications (can also wait until phase 2)
- [ ] 10. Send the results back

Commands in `PowerShell` boxes run in Windows; commands in `bash` boxes run in the Ubuntu window.

## 1. Windows basics (about 15 min)

1. **BIOS / UEFI** (key at power-on, often F2 or Del):
   - Set *Restore on AC power loss* to **Power On**. The name varies: "AC Back", "Power On After Power Failure".
   - Check that *SVM / AMD-V* (virtualization) is **enabled**. WSL needs it.
2. **Windows Update:** *Settings → Windows Update*:
   - **Pause updates** for the longest offered period (up to 5 weeks).
   - Switch off *Get the latest updates as soon as they're available*.
   - A forced restart in the middle of the sweep would interrupt it.
3. **Automatic login**, so that everything starts again after a power cut:
   - *Settings → Accounts → Sign-in options*: switch off *For improved security, only allow Windows Hello sign-in…*.
   - Press `Win + R`, run `netplwiz`, untick *Users must enter a user name and password to use this computer*, and enter the password.
   - If that box is missing, use Microsoft's *Sysinternals Autologon* tool instead.
4. **Optional:** rename the PC (*Settings → System → About → Rename this PC*), e.g. `hpc-01`. The name appears on the dashboard.

Power and sleep settings follow in step 4 by script.

## 2. Install WSL and Ubuntu (about 15 min)

In an **administrator PowerShell** (right-click Start → *Terminal (Admin)*):

```powershell
wsl --install -d Ubuntu-24.04
```

1. Restart when asked. The Ubuntu window then opens by itself; choose a Linux user name and password.
2. Then, again in PowerShell:

   ```powershell
   wsl --update
   wsl -l -v          # lists the distro with VERSION 2; note its name (Ubuntu-24.04, or just Ubuntu)
   ```

## 3. In Ubuntu: deploy key, repository, installation (about 45 min, mostly waiting)

Open *Ubuntu* from the Start menu.

**3a. Deploy key**: lets this PC push its status and results to GitHub, for this repository only.

```bash
ssh-keygen -t ed25519 -f ~/.ssh/stosslueften_hpc -N "" -C "stosslueften-hpc"
cat ~/.ssh/stosslueften_hpc.pub
```

1. On GitHub, open the repository and go to *Settings → Deploy keys → Add deploy key*.
2. Title `hpc-01`, paste the printed line, and tick **Allow write access**.
3. Then:

   ```bash
   cat >> ~/.ssh/config <<'EOF'
   Host github-stosslueften
       HostName github.com
       User git
       IdentityFile ~/.ssh/stosslueften_hpc
       IdentitiesOnly yes
   EOF
   chmod 600 ~/.ssh/config
   ssh -T github-stosslueften    # answer "yes" once; expected: "Hi jvnvic/stosslueften! You've successfully authenticated…"
   ```

**3b. Repository**: clone it into the Linux home folder, not under `/mnt/c` (Windows drives are very slow from WSL):

```bash
git clone github-stosslueften:jvnvic/stosslueften.git ~/stosslueften
cd ~/stosslueften
git config user.name "stosslueften-hpc"
git config user.email "hpc@stosslueften.invalid"
```

**3c. Installation**: system packages, OpenFOAM v2606 (ready-made openfoam.com package), the Python environment and our solver. It asks for the Linux password once and ends with the test results:

```bash
bash hpc/setup/install_ubuntu.sh
```

If it stops at OpenFOAM, the package name has changed. The current names are on the [openfoam.com Debian/Ubuntu page](https://develop.openfoam.com/Development/openfoam/-/wikis/precompiled/debian).

## 4. Windows settings, restart WSL (about 5 min)

The script does three things:
- power: never sleep or hibernate on mains power;
- writes `.wslconfig`: 16 threads, 24 GB RAM, no idle shutdown;
- registers the task that keeps WSL running from logon on.

In an **administrator PowerShell**, with your distro name from step 2 (twice) and your Linux user name:

```powershell
powershell -ExecutionPolicy Bypass -File \\wsl.localhost\<distro>\home\<linux user>\stosslueften\hpc\setup\windows_setup.ps1 -Distro <distro>
wsl --shutdown
Start-ScheduledTask -TaskName "stosslueften WSL keep-alive"
```

The keep-alive task starts `wsl.exe -d <distro>`. With a wrong name it starts nothing, and the machine check reports "no keep-alive process".

`wsl --shutdown` applies the new settings, including systemd. Open the Ubuntu window again afterwards.

## 5. Machine check

```bash
cd ~/stosslueften
bash hpc/setup/check_machine.sh | tee cases/check_machine.txt
```

- Every line should say `OK`.
- The `WARN` about the missing issue token is fine until step 9.
- Each `FAIL` line says what to fix. Fix it and run the check again.

## 6. Reboot test

1. Restart Windows and don't touch anything. After the automatic login, wait one minute.
2. Then, in PowerShell:

   ```powershell
   wsl -l --running        # must list Ubuntu-24.04: the keep-alive task has started WSL by itself
   ```

3. Also test the idle case: close all windows, wait 5 minutes, and run `wsl -l --running` again. Ubuntu must still be listed.

## 7. Reference check (about 1.5 h, unattended)

The same three cases as on the laptop, with the same number of cores: default and demo_1 with method A, the same-wall benchmark case with method B. At the end, the results are compared with the laptop's ([reference.json](reference.json)).

```bash
cd ~/stosslueften
setsid nohup bash hpc/setup/reference_check.sh > cases/reference_check.out 2>&1 &
```

- **Watching it:** `tail -f cases/reference_check.out` (Ctrl+C stops only the watching). Or start the monitor window: `.venv/bin/python -m analysis.monitor`; WSL shows it on the Windows desktop.
- **Expected:** the last line says `All reference results match.`
- **If not:** stop here. Results from the two machines must not be mixed until we know why they differ.

## 8. Throughput measurement (about 30 min, unattended)

This runs 2, 3 and 4 cases at the same time (4 cores each) and recommends how many slots the runner should use:

```bash
source hpc/setup/foam_env.sh
setsid nohup .venv/bin/python -m hpc.setup.measure_throughput > cases/throughput.out 2>&1 &
```

The table at the end of `cases/throughput.out` gives the cases per hour.

## 9. Issue token for notifications (can wait until phase 2)

The runner will post events to a GitHub issue, so the GitHub app on the phone notifies you. A deploy key only works for git, so issues need a token.

1. On GitHub: *your picture → Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token*.
2. Settings:
   - name `stosslueften-hpc`, expiration 90 days;
   - *Repository access: Only select repositories → jvnvic/stosslueften*;
   - *Permissions → Repository → Issues: Read and write*.
3. Store it on the PC only, never in the repository:

   ```bash
   mkdir -p ~/.config/stosslueften && chmod 700 ~/.config/stosslueften
   nano ~/.config/stosslueften/token          # paste the token, Ctrl+O, Enter, Ctrl+X
   chmod 600 ~/.config/stosslueften/token
   bash hpc/setup/check_machine.sh | tail -3  # "the issue token is valid"
   ```

## 10. Send the results back

Send these three files, or paste their contents into the chat. The results then go into HPC_PLAN.md, and phase 1 (the runner) can be tested on this machine.
- `cases/check_machine.txt`
- the end of `cases/reference_check.out`
- the end of `cases/throughput.out`

## Files in this folder

| File | Used in | Purpose |
|---|---|---|
| `install_ubuntu.sh` | step 3 | Installs everything inside Ubuntu |
| `wsl.conf` | step 3 | `/etc/wsl.conf`: systemd on, Windows PATH off |
| `windows_setup.ps1` | step 4 | Power options, `.wslconfig`, keep-alive task |
| `wslconfig.example` | step 4 | WSL settings for this PC |
| `check_machine.sh` | steps 5, 9 | Checks everything, `OK` / `WARN` / `FAIL` per line |
| `reference_check.sh`, `reference.json`, `compare_reference.py` | step 7 | Runs the reference cases and compares them with the laptop |
| `measure_throughput.py` | step 8 | Cases per hour for 2, 3 or 4 slots |
| `foam_env.sh` | scripts | Loads OpenFOAM v2606: the Ubuntu package or the Arch build |
