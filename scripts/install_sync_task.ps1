# Starts the sync helper at logon on this PC (for PCs where the scanner does not run).
# Run from the folder that holds WoWFlipSync.exe and config.toml:
#   powershell -ExecutionPolicy Bypass -File install_sync_task.ps1
param([string]$Exe = (Join-Path (Get-Location) "WoWFlipSync.exe"), [string]$TaskName = "WoW Flip Sync")

if (-not (Test-Path $Exe)) { throw "Not found: $Exe" }
$action = New-ScheduledTaskAction -Execute $Exe -WorkingDirectory (Split-Path $Exe)
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Write-Host "'$TaskName' runs $Exe at every logon, and is running now."
