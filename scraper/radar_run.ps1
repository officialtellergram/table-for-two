# Table for Two — local cancellation-radar runner. SUPERSEDED for routine sweeps
# by .github/workflows/radar.yml, which runs the same Resy pass on cron in the
# cloud and needs no PC. Keep this for manual/offline sweeps and for debugging a
# sweep against the local feed.
#
# It refreshes the Just-Opened feed on disk; your localhost server reads it
# directly, so you see updates locally with no deploy needed. The Windows
# scheduled task is disabled — see scraper/radar_task.md.
#
# On Resy vs datacenter IPs, measured 2026-07-16 — the nuance matters:
#   * A few calls from a GitHub Azure runner DO answer 200. So it is not a hard
#     IP block, and a small probe will tell you everything is fine. It isn't.
#   * A full 40-venue sweep from that same runner had 22/40 lookups fail, while
#     the identical sweep from this residential IP failed 0/40. Resy degrades
#     sustained datacenter traffic rather than blocking it outright.
# So this box still gives materially better Resy coverage than the cloud does.
# If you re-test, use a FULL sweep — a 3-call probe measures nothing.
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
    # --cities pinned to the legacy radar set — the manifest now carries 20+
    # agent-curated cities; sweeping them all would blow Resy's rate limits.
    $out = & $Py 'scraper\sniper.py' '--only' 'resy' '--cities' 'nyc,dc,richmond,boston,houston' '--days' '3' '--limit' '8' '--sleep' '0.75' '--notify' 2>&1
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
