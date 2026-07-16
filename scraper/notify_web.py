#!/usr/bin/env python3
"""notify_web.py — Stage 2 bridge: ship this sweep's NEW slots to the web.

The Linux twin of notify_web.ps1, for the GitHub Actions radar (the runner has
no PowerShell). Same contract: POST the new:true slots from cities/just-opened.json
to the ingest-openings Edge Function, which fans them out to everyone signed up.
Run it AFTER the feed is written. The .ps1 stays for local/manual sweeps.

Fails soft on purpose: a signup-alert outage must never fail the radar workflow
or block its feed push. We log and exit 0; we never raise.

INGEST_URL/INGEST_SECRET are set at user level on the dev box, so running this
by hand emails for real — and against a stale feed it blasts old openings to
whoever matches. Use --dry-run to see what *would* go out.

Env:
  INGEST_URL     https://<project-ref>.functions.supabase.co/ingest-openings
  INGEST_SECRET  shared secret (same value set as a Supabase function secret)
"""
import argparse
import json
import os
import pathlib
import sys

import requests

FEED = pathlib.Path(__file__).resolve().parent.parent / "cities" / "just-opened.json"


def log(msg):
    # Venue names carry accents (Kōbe, Côte). The Actions runner is UTF-8, but a
    # Windows console is cp1252 and raises on them — which the soft-fail below
    # would swallow as a bogus "ERROR". Degrade the glyph, never the run.
    try:
        print(f"web: {msg}")
    except UnicodeEncodeError:
        enc = sys.stdout.encoding or "ascii"
        print(f"web: {msg}".encode(enc, "replace").decode(enc, "replace"))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="print what would be sent; POST nothing, email no one")
    args = ap.parse_args()

    url, secret = os.environ.get("INGEST_URL"), os.environ.get("INGEST_SECRET")
    if not url or not secret:
        log("INGEST_URL/INGEST_SECRET not set; skipping")
        return
    if not FEED.exists():
        log("no just-opened.json; skipping")
        return

    try:
        feed = json.loads(FEED.read_text(encoding="utf-8"))
        # Only the genuinely-new slots — the same gate the Edge Function re-applies.
        items = [i for i in (feed.get("items") or []) if i.get("new") is True]
        if not items:
            log("no new slots this sweep")
            return

        if args.dry_run:
            log(f"DRY RUN — would post {len(items)} new slot(s), emailing no one:")
            for i in items:
                log(f"  - {i.get('name')} {i.get('date')} {i.get('time')}")
            return

        r = requests.post(url, json={"items": items},
                          headers={"x-ingest-secret": secret}, timeout=30)
        r.raise_for_status()
        body = r.json()
        log(f"posted {len(items)} new -> matched={body.get('matched')} sent={body.get('sent')}")
    except Exception as e:
        log(f"ERROR: {e}")   # swallow: signup alerts are best-effort


if __name__ == "__main__":
    main()
    sys.exit(0)
