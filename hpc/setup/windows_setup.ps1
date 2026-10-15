# Windows part of the simulation PC setup (hpc/setup/README.md, step 4).
# Run once in an administrator PowerShell; running it again is harmless:
#   powershell -ExecutionPolicy Bypass -File \\wsl.localhost\<distro>\home\<linux user>\stosslueften\hpc\setup\windows_setup.ps1 -Distro <distro>
# <distro> is the name that `wsl -l -v` shows, e.g. Ubuntu-24.04 or Ubuntu.
# It sets the power options, writes .wslconfig and registers the WSL keep-alive task.

param(
    [string]$Distro = "Ubuntu-24.04"
)

$ErrorActionPreference = "Stop"
$TaskName = "stosslueften WSL keep-alive"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "1/3 Power: never sleep or hibernate on mains power (the screen may still switch off)"
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
powercfg /hibernate off

Write-Host "2/3 .wslconfig: cores, memory, no idle shutdown"
$Target = Join-Path $env:USERPROFILE ".wslconfig"
if (Test-Path $Target) {
    Copy-Item $Target "$Target.bak" -Force
    Write-Host "    the existing file was saved as .wslconfig.bak"
}
Copy-Item (Join-Path $Here "wslconfig.example") $Target -Force

Write-Host "3/3 Scheduled task '$TaskName' (starts at logon)"
# A wsl.exe process that never ends keeps WSL running. Without it, WSL may shut down when
# no terminal is open, and the simulations would stop with it.
$Command = "wsl.exe -d $Distro --exec /bin/sleep infinity"
$Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -WindowStyle Hidden -Command `"$Command`""
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Force | Out-Null

Write-Host ""
Write-Host "Done. Next (guide step 4):"
Write-Host "    wsl --shutdown"
Write-Host "    Start-ScheduledTask -TaskName '$TaskName'"
