# Table for Two — SLOW OpenTable radar runner.
#
# OpenTable's Akamai edge blocks this residential IP at the 30-min Resy cadence
# (even 8 venues back-to-back trips a multi-hour "Access Denied"), but a slow
# cadence is fine (117 slots after a rest). So OpenTable runs on ITS OWN task,
# every ~3h, a handful of venues, rotating through all of them across the day.
# See scraper/radar_task.md.
#
# Shares a lock with radar_run.ps1 so the two sniper processes never overlap
# (they write the same state + feed files and both push). Pulls before pushing
# so whichever ran more recently doesn't reject the other.

$ErrorActionPreference = 'Stop'
$Repo = 'C:\Users\Karen Plankton\Desktop\hardtobook-dashboard'
$Py   = 'C:\Users\Karen Plankton\anaconda3\python.exe'
$Git  = 'C:\Program Files\Git\cmd\git.exe'
$Log  = Join-Path $Repo 'scraper\.radar.log'
$Lock = Join-Path $Repo 'scraper\.sniper.lock'

function Log($m) { "{0}  [ot] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $m | Out-File -FilePath $Log -Append -Encoding utf8 }

# --- mutex: skip this run if a sweep is already going (a skip is harmless) ---
if (Test-Path $Lock) {
    $age = (Get-Date) - (Get-Item $Lock).LastWriteTime
    if ($age.TotalMinutes -lt 20) { Log 'another sweep holds the lock; skipping'; exit 0 }
    Remove-Item $Lock -Force   # stale lock (a crashed run) — reclaim it
}
New-Item -ItemType File -Path $Lock -Force | Out-Null

try {
    Set-Location $Repo

    # OpenTable only, 5 venues this run; the cursor in .sniper_state.json advances
    # so the next run picks up the following 5 — full rotation over the day.
    $out = & $Py 'scraper\sniper.py' '--only' 'opentable' '--ot-per-sweep' '5' '--days' '4' '--notify' 2>&1
    Log ($out -join ' | ')

    & $Git add cities/just-opened.json deploy/cities/just-opened.json scraper/.sniper_state.json
    & $Git diff --cached --quiet
    if ($LASTEXITCODE -ne 0) {
        & $Git commit --quiet -m 'radar: refresh OpenTable slots'
        & $Git pull --quiet --no-edit origin main 2>&1 | Out-Null   # absorb any Resy-radar push
        & $Git push --quiet origin main 2>&1 | Out-Null
        Log 'pushed OpenTable update -> GitHub Pages will redeploy'
    } else {
        Log 'no OpenTable changes; nothing to push'
    }

    # Stage 2 fan-out to public signups (no-op until INGEST_URL/INGEST_SECRET set).
    & (Join-Path $Repo 'scraper\notify_web.ps1')
} catch {
    Log ("ERROR: " + $_.Exception.Message)
    exit 1
} finally {
    Remove-Item $Lock -Force -ErrorAction SilentlyContinue
}
