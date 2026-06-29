# Local cancellation-radar scheduler (Windows)

The radar **must run from a residential IP** — Resy blocks datacenter IPs, so the
Anthropic cloud routine got 0 slots and was disabled. This machine's IP sees the
real data, so the poller runs here on a Windows Scheduled Task.

- **Runner:** `scraper/radar_run.ps1` — polls Resy, refreshes `cities/just-opened.json`
  (+ deploy mirror) and `scraper/.sniper_state.json`, commits, and pushes to both
  `origin` and `site` (Netlify redeploys). Uses absolute Anaconda-python + git paths
  on purpose (a task gets a minimal PATH; bare `python` is the broken MS Store stub).
- **Task name:** `TableForTwoRadar` — every 30 min while the PC is on.
- **Log:** `scraper/.radar.log` (gitignored).

## Manage it

```powershell
Get-ScheduledTaskInfo -TaskName TableForTwoRadar      # last/next run + result
Start-ScheduledTask    -TaskName TableForTwoRadar      # run now
Disable-ScheduledTask  -TaskName TableForTwoRadar      # pause
Enable-ScheduledTask   -TaskName TableForTwoRadar      # resume
Unregister-ScheduledTask -TaskName TableForTwoRadar -Confirm:$false   # remove
```

## Change the cadence

Re-register with a different `-RepetitionInterval`:

```powershell
$s='C:\Users\Karen Plankton\Desktop\hardtobook-dashboard\scraper\radar_run.ps1'
$a=New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}"' -f $s)
$t=New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 15) -RepetitionDuration (New-TimeSpan -Days 3650)
Register-ScheduledTask -TaskName TableForTwoRadar -Action $a -Trigger $t -Force
```

## Caveats

- Only runs while the PC is on/awake. For 24/7, move `radar_run.ps1` to an
  always-on device on a residential connection (e.g. a Raspberry Pi at home).
- The sniper keeps the last good feed if a sweep returns 0 slots (IP-block/outage
  guard), so a transient failure won't wipe the radar.
