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
$Push = $false   # local-only while Netlify is out; set $true to deploy again

function Log($m) { "{0}  {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $m | Out-File -FilePath $Log -Append -Encoding utf8 }

try {
    Set-Location $Repo

    $out = & $Py 'scraper\sniper.py' '--days' '4' '--limit' '8' 2>&1
    Log ($out -join ' | ')

    if ($Push) {
        & $Git add cities/just-opened.json deploy/cities/just-opened.json scraper/.sniper_state.json
        & $Git diff --cached --quiet
        if ($LASTEXITCODE -ne 0) {
            & $Git commit --quiet -m 'radar: refresh just-opened feed'
            & $Git push --quiet origin main 2>&1 | Out-Null
            & $Git push --quiet site   main 2>&1 | Out-Null
            Log 'pushed update -> Netlify will redeploy'
        } else {
            Log 'no feed changes; nothing to push'
        }
    } else {
        Log 'local-only: feed updated on disk (view at http://localhost:8080)'
    }
} catch {
    Log ("ERROR: " + $_.Exception.Message)
    exit 1
}
