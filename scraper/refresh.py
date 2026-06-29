#!/usr/bin/env python3
"""
refresh.py — regenerate every city dataset and restage deploy/.

Run this AFTER the research seeds (sources/<city>.json) are up to date. The
weekly cloud routine does: (1) re-research the 4 cities -> rewrite their seeds,
(2) run this, (3) git commit & push -> the connected host auto-deploys.

  python refresh.py            # regenerate all cities from existing seeds
  python refresh.py --fetch-nyc  # also re-pull the NYC seed from the hardtobook API

Each researched city is ranked by hardness and trimmed to the top 25.
"""
import subprocess, sys, shutil, json, urllib.request
from pathlib import Path

SCR = Path(__file__).resolve().parent
ROOT = SCR.parent
PY = sys.executable

# key, label, short, region, timezone, top (0 = keep all)
CITIES = [
    ("nyc",      "New York City", "NYC", "New York, NY",   "America/New_York", 0),
    ("dc",       "Washington, DC", "DC", "Washington, DC", "America/New_York", 25),
    ("richmond", "Richmond, VA",  "RVA", "Richmond, VA",   "America/New_York", 25),
    ("boston",   "Boston, MA",    "BOS", "Boston, MA",     "America/New_York", 25),
    ("houston",  "Houston, TX",   "HOU", "Houston, TX",    "America/Chicago",  25),
]


def fetch_nyc():
    url = "https://www.hardtobook.xyz/api/v1/spots"
    data = json.loads(urllib.request.urlopen(url, timeout=30).read())
    out = SCR / "sources" / "nyc.json"
    json.dump(data.get("spots", []), open(out, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(f"refreshed NYC seed: {len(data.get('spots', []))} spots")


def run_city(c):
    key, label, short, region, tz, top = c
    seed = SCR / "sources" / f"{key}.json"
    if not seed.exists():
        print(f"-- skip {key}: no seed at {seed}")
        return
    cmd = [PY, str(SCR / "curate.py"), str(seed), "--city", key, "--label", label,
           "--short", short, "--region", region, "--timezone", tz, "--update-manifest"]
    if top:
        cmd += ["--top", str(top)]
    print(f"\n== {key} ==")
    subprocess.run(cmd, check=True)


def run_concierge():
    """Re-apply the date-night vibe/occasion tags (curate rebuilds spots from the
    seeds, which don't carry tags, so this has to run after every curate)."""
    print("\n== concierge (date-night tags) ==")
    subprocess.run([PY, str(SCR / "concierge.py"), "--no-deploy"], check=True)


def sync_deploy():
    dep = ROOT / "deploy"
    dep.mkdir(exist_ok=True)
    shutil.copy2(ROOT / "index.html", dep / "index.html")
    if (dep / "cities").exists():
        shutil.rmtree(dep / "cities")
    shutil.copytree(ROOT / "cities", dep / "cities")
    print("\ndeploy/ restaged")


if __name__ == "__main__":
    if "--fetch-nyc" in sys.argv:
        fetch_nyc()
    for c in CITIES:
        run_city(c)
    run_concierge()
    sync_deploy()
    print("done.")
