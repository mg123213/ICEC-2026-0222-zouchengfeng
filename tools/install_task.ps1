# Register / remove the two daily scheduled tasks that keep the log continuous.
#
#   powershell -ExecutionPolicy Bypass -File tools\install_task.ps1
#   powershell -ExecutionPolicy Bypass -File tools\install_task.ps1 -Uninstall
#
# Uses the current user's context, so no administrator rights are required.

param([switch]$Uninstall)

$ErrorActionPreference = 'Stop'

$root      = Split-Path -Parent $PSScriptRoot
$dailyRun  = Join-Path $PSScriptRoot 'daily_run.py'
$taskNames = @('CampusRadar-Daily-AM', 'CampusRadar-Daily-PM')
$times     = @('08:10', '19:30')

if ($Uninstall) {
    foreach ($name in $taskNames) {
        try {
            Unregister-ScheduledTask -TaskName $name -Confirm:$false
            Write-Host "Removed $name"
        } catch {
            Write-Host "Not found: $name"
        }
    }
    exit 0
}

$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) {
    throw 'python.exe not found in PATH. Add Python to PATH first.'
}
if (-not (Test-Path $dailyRun)) {
    throw "daily_run.py not found at $dailyRun"
}

$action = New-ScheduledTaskAction `
    -Execute $python `
    -Argument ('"{0}" --quiet' -f $dailyRun) `
    -WorkingDirectory $root

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

for ($i = 0; $i -lt $taskNames.Count; $i++) {
    $trigger = New-ScheduledTaskTrigger -Daily -At $times[$i]
    Register-ScheduledTask `
        -TaskName $taskNames[$i] `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Description 'Campus Notice Radar - daily parse, self-check and log rollup' `
        -Force | Out-Null
    Write-Host ("Registered {0} at {1}" -f $taskNames[$i], $times[$i])
}

Write-Host ''
Write-Host 'Verify with:  schtasks /Query /TN CampusRadar-Daily-AM /V /FO LIST'
