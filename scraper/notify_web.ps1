# notify_web.ps1 — Stage 2 bridge: ship this sweep's NEW slots to the web.
#
# The radar writes cities/just-opened.json each sweep; Stage 1 (notify.py) alerts
# YOU over Telegram. This does the public side: it POSTs the same new:true slots
# to the ingest-openings Edge Function, which fans them out to everyone who
# signed up. Call it from a radar runner AFTER the feed is written.
#
# Fails soft on purpose: a signup-alert outage must never break the local sweep
# or its GitHub Pages push. We log and return; we never throw.
#
# Env (set on this Windows box, e.g. in the scheduled task or a profile):
#   INGEST_URL     https://<project-ref>.functions.supabase.co/ingest-openings
#   INGEST_SECRET  the shared secret (same value set as a Supabase function secret)

$Repo = 'C:\Users\Karen Plankton\Desktop\hardtobook-dashboard'
$Feed = Join-Path $Repo 'cities\just-opened.json'
$Log  = Join-Path $Repo 'scraper\.radar.log'

function Log($m) { "{0}  {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), "web: $m" | Out-File -FilePath $Log -Append -Encoding utf8 }

$url    = $env:INGEST_URL
$secret = $env:INGEST_SECRET
if (-not $url -or -not $secret) { Log 'INGEST_URL/INGEST_SECRET not set; skipping'; return }
if (-not (Test-Path $Feed))     { Log 'no just-opened.json; skipping'; return }

try {
    $feed = Get-Content -Path $Feed -Raw -Encoding utf8 | ConvertFrom-Json

    # Only the genuinely-new slots — the same gate the Edge Function re-applies.
    $items = @($feed.items | Where-Object { $_.new -eq $true })
    if ($items.Count -eq 0) { Log 'no new slots this sweep'; return }

    # -Depth so nested slot fields survive the round-trip to JSON.
    $payload = @{ items = $items } | ConvertTo-Json -Depth 6
    $headers = @{ 'x-ingest-secret' = $secret }

    $resp = Invoke-RestMethod -Uri $url -Method Post -Body $payload `
        -ContentType 'application/json' -Headers $headers -TimeoutSec 30
    Log ("posted {0} new -> matched={1} sent={2}" -f $items.Count, $resp.matched, $resp.sent)
} catch {
    Log ("ERROR: " + $_.Exception.Message)   # swallow: signup alerts are best-effort
}
