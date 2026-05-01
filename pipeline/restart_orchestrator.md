# Start the local orchestrator (the brain on the laptop)

## Stop any running orchestrator first

```powershell
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*stock*serve*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

## Start it detached, with logs to file

Single block — paste all of it.

```powershell
$proj = "C:\Users\claw\Desktop\Project\STOCK"; $logDir = "$proj\pipeline\logs"; New-Item -ItemType Directory -Force -Path $logDir | Out-Null; $p = Start-Process -FilePath "$proj\.venv\Scripts\python.exe" -ArgumentList "-m","stock","serve" -WorkingDirectory $proj -WindowStyle Hidden -RedirectStandardOutput "$logDir\orchestrator.stdout.log" -RedirectStandardError "$logDir\orchestrator.stderr.log" -PassThru; Write-Host "Started orchestrator with PID $($p.Id)"
```

## Verify it's alive

```powershell
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Select-Object ProcessId, CommandLine | Format-List
```

You should see two `python.exe` rows with `stock serve` in CommandLine.

## Watch the live log

```powershell
Get-Content C:\Users\claw\Desktop\Project\STOCK\pipeline\logs\orchestrator.log -Wait -Tail 20
```

Press Ctrl+C to stop watching (this just exits the tail; the orchestrator keeps running).

## Search the log

```powershell
# Errors only
Select-String -Path C:\Users\claw\Desktop\Project\STOCK\pipeline\logs\orchestrator.log -Pattern "ERROR|WARNING"

# Reply pipeline activity
Select-String -Path C:\Users\claw\Desktop\Project\STOCK\pipeline\logs\orchestrator.log -Pattern "Reply note generated|Inline F13 fired"

# When something actually moved through sync
Select-String -Path C:\Users\claw\Desktop\Project\STOCK\pipeline\logs\orchestrator.log -Pattern "Render sync"
```

## Foreground mode (if you'd rather watch in PowerShell window)

```powershell
cd C:\Users\claw\Desktop\Project\STOCK
.venv\Scripts\python.exe -m stock serve
```

This blocks the PowerShell window. Closing the window kills the orchestrator. Detached mode (above) keeps it running across PowerShell sessions.
