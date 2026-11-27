# Registers an hourly Windows scheduled task that runs scripts\run_scan.bat
# at 20 minutes past every hour. Run from the repository folder:
#   powershell -ExecutionPolicy Bypass -File scripts\install_task.ps1
param([int]$Minute = 20, [string]$TaskName = "WoW Flip Scanner")

$bat = Join-Path $PSScriptRoot "run_scan.bat"
$start = (Get-Date).Date.AddHours((Get-Date).Hour).AddMinutes($Minute)
if ($start -lt (Get-Date)) { $start = $start.AddHours(1) }

$action = New-ScheduledTaskAction -Execute $bat
$trigger = New-ScheduledTaskTrigger -Once -At $start -RepetitionInterval (New-TimeSpan -Hours 1)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Host "Scheduled '$TaskName' hourly at :$('{0:D2}' -f $Minute), first run $start."
