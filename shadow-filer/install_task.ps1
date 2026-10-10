# Registers Shadow Filer to start at every logon (so it survives reboots), run indefinitely,
# and be restarted by Task Scheduler if it stops. Runs as you, without admin rights.
#
# Usage (from this folder):
#   powershell -ExecutionPolicy Bypass -File .\install_task.ps1
#   powershell -ExecutionPolicy Bypass -File .\install_task.ps1 -Remove
#
# Move a running install to this folder (stops it, copies your settings, data and Python environment,
# then starts it from here; the old folder is left untouched):
#   powershell -ExecutionPolicy Bypass -File .\install_task.ps1 -MigrateFrom D:\Tools\shadow-filer

param([string]$TaskName = "ShadowFiler", [switch]$Remove, [string]$MigrateFrom = "", [int]$Port = 8765)
$ErrorActionPreference = "Stop"

function Stop-Agent {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    }
    # The agent exits on its own a moment after its supervisor stops. Wait until the UI port is free.
    for ($i = 0; $i -lt 30; $i++) {
        $busy = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        if (-not $busy) { return }
        Start-Sleep -Seconds 1
    }
    throw "Shadow Filer is still running on port $Port after 30 seconds. Close it (Task Manager > pythonw.exe) and run this again."
}

if ($Remove) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed task '$TaskName'. Your data (shadow.db, logs, config) is untouched."
    exit 0
}

$dir = Split-Path -Parent $MyInvocation.MyCommand.Path

if ($MigrateFrom) {
    $src = (Resolve-Path $MigrateFrom).Path
    if ($src -eq $dir) { throw "-MigrateFrom points at this folder." }
    if (-not (Test-Path (Join-Path $src "shadow_agent.py"))) { throw "Not a Shadow Filer folder: $src" }
    Write-Host "Stopping the agent running from $src ..."
    Stop-Agent
    # Settings and data. Existing files here are kept as *.before-migrate, never silently overwritten.
    $items = @("config.yaml", "config.yaml.bak", "shadow.db", "shadow.db-wal", "shadow.db-shm",
               "search.db", "search.db-wal", "search.db-shm", "cleanup_report.json",
               "shadow.log", "supervisor.log")
    foreach ($name in $items) {
        $from = Join-Path $src $name
        if (-not (Test-Path $from)) { continue }
        $to = Join-Path $dir $name
        if (Test-Path $to) { Move-Item -Force $to "$to.before-migrate" }
        Copy-Item $from $to
        Write-Host "  copied $name"
    }
    # Rotated logs (shadow.log.1 ...)
    Get-ChildItem -Path $src -Filter "shadow.log.*" -ErrorAction SilentlyContinue | ForEach-Object {
        Copy-Item $_.FullName (Join-Path $dir $_.Name) -Force
    }
    if (-not (Test-Path (Join-Path $dir ".venv"))) {
        Write-Host "  copying the Python environment (.venv) ..."
        Copy-Item -Recurse (Join-Path $src ".venv") (Join-Path $dir ".venv")
    }
}

$py = Join-Path $dir ".venv\Scripts\python.exe"
$pyw = Join-Path $dir ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $pyw)) { throw "Not found: $pyw. Create the virtual environment first (README step 1)." }
if (-not (Test-Path (Join-Path $dir "config.yaml"))) {
    throw "No config.yaml here. Copy config.example.yaml to config.yaml and edit it first (README step 2)."
}
# Make sure the environment works from this folder before switching the task over.
$ErrorActionPreference = "Continue"   # a native command writing to stderr must not abort the script here
& $py -c "import watchdog, yaml, requests, pypdf" 2>&1 | Out-Null
$ok = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = "Stop"
if (-not $ok) { throw "The Python environment in $dir\.venv doesn't work. Recreate it (README step 1)." }

if (-not $MigrateFrom) { Stop-Agent }

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
    -Description "Shadow Filer: predicts where new files belong; deletes only files you confirm on the Cleanup page (Recycle Bin)." | Out-Null

Start-ScheduledTask -TaskName $TaskName
Write-Host "Installed and started '$TaskName' from $dir."
if ($MigrateFrom) { Write-Host "The old folder $src was left as it was. Delete it once you're happy." }
Write-Host "Open http://127.0.0.1:$Port (give it a few seconds)."
