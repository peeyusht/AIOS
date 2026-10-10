# Registers Shadow Filer to start at every logon (so it survives reboots), run indefinitely,
# and be restarted by Task Scheduler if it stops. Runs as you, without admin rights.
#
# Usage (from this folder):
#   powershell -ExecutionPolicy Bypass -File .\install_task.ps1
#   powershell -ExecutionPolicy Bypass -File .\install_task.ps1 -Remove

param([string]$TaskName = "ShadowFiler", [switch]$Remove)
$ErrorActionPreference = "Stop"

if ($Remove) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed task '$TaskName'. Your data (shadow.db, logs, config) is untouched."
    exit 0
}

$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pyw = Join-Path $dir ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $pyw)) { throw "Not found: $pyw. Create the virtual environment first (README step 1)." }

$user = "$env:USERDOMAIN\$env:USERNAME"

# The task runs a small supervisor, which runs the agent and restarts it when you click
# "Restart agent" or if it crashes. pythonw = no console window.
$action = New-ScheduledTaskAction -Execute $pyw -Argument "`"$dir\shadow_agent.py`" supervise" -WorkingDirectory $dir

$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$trigger.Delay = "PT30S"   # give Ollama a head start after login

# ExecutionTimeLimit 0 = no limit. The default (72 hours) would silently kill the agent after 3 days.
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -MultipleInstances IgnoreNew

$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
    -Principal $principal -Force `
    -Description "Shadow Filer: predicts where new files belong. Never moves, renames or deletes files." | Out-Null

Start-ScheduledTask -TaskName $TaskName
Write-Host "Installed and started '$TaskName'."
Write-Host "Open http://127.0.0.1:8765 (give it a few seconds)."
