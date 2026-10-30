# Registers the "Renewal Radar daily rates" task for the current user (no admin, no stored password).
#   powershell -ExecutionPolicy Bypass -File tools\install_recorder_task.ps1          # install / update
#   powershell -ExecutionPolicy Bypass -File tools\install_recorder_task.ps1 -Remove  # uninstall
param([switch]$Remove)
$name = "Renewal Radar daily rates"
if ($Remove) { Unregister-ScheduledTask -TaskName $name -Confirm:$false; "removed $name"; exit }
$root = Split-Path -Parent $PSScriptRoot
$action = New-ScheduledTaskAction -Execute "$root\tools\record_daily.cmd" -WorkingDirectory $root
# Layer 4: three daily runs plus at logon; a missed run starts as soon as the PC is on and online.
$triggers = @(
  (New-ScheduledTaskTrigger -Daily -At 8:15AM),
  (New-ScheduledTaskTrigger -Daily -At 12:45PM),
  (New-ScheduledTaskTrigger -Daily -At 6:30PM),
  (New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME")
)
$triggers[3].Delay = "PT5M"
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable `
  -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 15) -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
  -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $name -Action $action -Trigger $triggers -Settings $settings -Principal $principal `
  -Description "Records every lender's own posted mortgage rates daily (Renewal Radar). Logs: data\ratewatch\recorder_logs" -Force | Out-Null
"installed: $name"
Get-ScheduledTask -TaskName $name | Get-ScheduledTaskInfo | Select-Object NextRunTime, LastRunTime, LastTaskResult
