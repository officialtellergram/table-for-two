# Table for Two — local cancellation-radar runner.
#
# Runs from this machine's RESIDENTIAL IP (Resy blocks datacenter IPs, so the
# cloud can't poll). It refreshes the Just-Opened feed on disk; your localhost
# server reads it directly, so you see updates locally with no deploy needed.
# A Windows scheduled task runs it every 30 min while the PC is on. See
# scraper/radar_task.md.
#
# $Push: while Netlify is paused we run LOCAL-ONLY (no commit/push, no git churn).
# Flip $Push = $true to resume committing + pushing to both repos (Netlify deploy).
#
# Absolute exe paths on purpose: a scheduled task gets a minimal PATH, and bare
# `python` here resolves to the broken Microsoft Store stub (no requests).

$ErrorActionPreference = 'Stop'
$Repo = 'C:\Users\Karen Plankton\Desktop\hardtobook-dashboard'
$Py   = 'C:\Users\Karen Plankton\anaconda3\python.exe'
$Git  = 'C:\Program Files\Git\cmd\git.exe'
$Log  = Join-Path $Repo 'scraper\.radar.log'
$Lock = Join-Path $Repo 'scraper\.sniper.lock'
$Push = $true    # push the fresh feed to GitHub Pages (origin) — free, auto-deploys

function Log($m) { "{0}  {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $m | Out-File -FilePath $Log -Append -Encoding utf8 }

# --- mutex: shared with the slow OpenTable task so the two never overlap ---
if (Test-Path $Lock) {
    $age = (Get-Date) - (Get-Item $Lock).LastWriteTime
    if ($age.TotalMinutes -lt 20) { Log 'another sweep holds the lock; skipping'; exit 0 }
    Remove-Item $Lock -Force   # stale lock (a crashed run) — reclaim it
}
New-Item -ItemType File -Path $Lock -Force | Out-Null

try {
    Set-Location $Repo

    # 3-day window + 0.75s spacing: Resy rate-limits sustained 30-min sweeps (429,
    # cools off over hours) — fewer, slower calls keep us under it. resy_find
    # aborts the pass on a sustained 429 so a limited sweep costs ~2 calls.
    $out = & $Py 'scraper\sniper.py' '--only' 'resy' '--days' '3' '--limit' '8' '--sleep' '0.75' '--notify' 2>&1
    Log ($out -join ' | ')

    if ($Push) {
        & $Git add cities/just-opened.json deploy/cities/just-opened.json scraper/.sniper_state.json
        & $Git diff --cached --quiet
        if ($LASTEXITCODE -ne 0) {
            & $Git commit --quiet -m 'radar: refresh just-opened feed'
            & $Git pull --quiet --no-edit origin main 2>&1 | Out-Null   # absorb any OT-task push
            & $Git push --quiet origin main 2>&1 | Out-Null   # GitHub Pages auto-redeploys (free)
            Log 'pushed update -> GitHub Pages will redeploy'
        } else {
            Log 'no feed changes; nothing to push'
        }
    } else {
        Log 'local-only: feed updated on disk (view at http://localhost:8080)'
    }

    # Stage 2 fan-out to public signups (no-op until INGEST_URL/INGEST_SECRET set).
    & (Join-Path $Repo 'scraper\notify_web.ps1')
} catch {
    Log ("ERROR: " + $_.Exception.Message)
    exit 1
} finally {
    Remove-Item $Lock -Force -ErrorAction SilentlyContinue
}
