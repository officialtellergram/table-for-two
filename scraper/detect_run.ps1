# Table for Two — LOCAL detection sweep (residential IP => full coverage the
# throttled cloud cron can't get). Deliberately lightweight: pure HTTP/JSON (no
# browser), paced, and the Python runs at BELOW-NORMAL priority so it never
# competes with anything you're doing. Corrects booking windows across all
# cities, then pushes to GitHub Pages. Runs from the TableForTwoDetect task a
# couple times a day (and catches up whenever the PC comes back on).
#
# --no-state: this task only fixes booking WINDOWS (cities/*.json). The shared
# release-time series (.detect_state.json) is owned by the cloud cron, so the two
# never collide over git.
$ErrorActionPreference = 'Stop'
$Repo = 'C:\Users\Karen Plankton\Desktop\hardtobook-dashboard'
$Py   = 'C:\Users\Karen Plankton\anaconda3\python.exe'
$Git  = 'C:\Program Files\Git\cmd\git.exe'
$Log  = Join-Path $Repo 'scraper\.detect.log'
$Lock = Join-Path $Repo 'scraper\.detect.lock'

function Log($m) { "{0}  {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $m | Out-File -FilePath $Log -Append -Encoding utf8 }

if (Test-Path $Lock) {
    $age = (Get-Date) - (Get-Item $Lock).LastWriteTime
    if ($age.TotalMinutes -lt 20) { Log 'another detect sweep holds the lock; skipping'; exit 0 }
    Remove-Item $Lock -Force
}
New-Item -ItemType File -Path $Lock -Force | Out-Null

try {
    Set-Location $Repo
    $env:PYTHONIOENCODING = 'utf-8'   # venue names carry accents; keep the console happy

    # The whole task runs at Priority 9 (idle-class) via its scheduler settings, so
    # foreground apps always win the CPU — no Start-Process gymnastics needed. Call
    # Python directly and capture its real exit code + output tail.
    $out  = & $Py 'scraper\enrich_windows.py' '--all' '--no-state' 2>&1
    $code = $LASTEXITCODE
    ($out | Select-Object -Last 3) | ForEach-Object { Log ("  " + $_) }
    Log ("enrich_windows exit " + $code)

    # Photos for any new listings — skips spots that already have one, so the
    # steady state costs nothing. Plain pass (Resy API + og:image) first; the
    # headful-Edge pass (Tock/SevenRooms/OT, parked off-screen, shares the OT
    # radar profile) only when fresh candidates remain, and at most every 14
    # days per stubborn venue (photoChecked stamps). Failures never fail the sweep.
    $out = & $Py 'scraper\harvest_photos.py' '--all' 2>&1
    ($out | Select-Object -Last 2) | ForEach-Object { Log ("  " + $_) }
    $need = & $Py -c "import json,glob,os;from datetime import date,timedelta;st=(date.today()-timedelta(days=14)).isoformat();print(sum(1 for f in glob.glob(r'cities\*.json') if os.path.basename(f) not in ('index.json','demand.json','just-opened.json','restaurant-queue.json','_template.json') for s in json.load(open(f,encoding='utf-8')).get('spots',[]) if not s.get('photo') and (s.get('photoChecked') or '')<st))" 2>$null
    if ([int]$need -gt 0) {
        Log ("browser photo pass: " + $need + " candidate venue(s)")
        $out = & $Py 'scraper\harvest_photos_browser.py' '--all' 2>&1
        ($out | Select-Object -Last 2) | ForEach-Object { Log ("  " + $_) }
    }

    # Push only the window corrections. SAFE by design:
    #   * --autostash protects any uncommitted work you have open — it's stashed
    #     over the rebase and restored, never discarded. No reset --hard, ever.
    #   * on a conflict we rebase --abort and leave the local commit in place; the
    #     next sweep's pull replays it cleanly. Corrections are idempotent, so a
    #     deferred push loses nothing.
    & $Git add cities/*.json
    & $Git diff --cached --quiet
    if ($LASTEXITCODE -ne 0) {
        & $Git commit --quiet -m 'detect(local): windows + photos refresh [skip ci]'
        $pushed = $false
        for ($i = 0; $i -lt 3 -and -not $pushed; $i++) {
            & $Git pull --quiet --rebase --autostash origin main 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) {
                & $Git push --quiet origin main 2>&1 | Out-Null
                if ($LASTEXITCODE -eq 0) { $pushed = $true; Log 'pushed window corrections' }
            } else {
                & $Git rebase --abort 2>&1 | Out-Null
                Start-Sleep -Seconds 3
            }
        }
        if (-not $pushed) { Log 'could not push cleanly; local commit waits for the next sweep' }
    } else {
        Log 'no window changes this sweep'
    }
} catch {
    Log ("ERROR: " + $_.Exception.Message)
} finally {
    Remove-Item $Lock -Force -ErrorAction SilentlyContinue
}
