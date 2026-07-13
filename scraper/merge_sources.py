"""
merge_sources.py — fold a researched provenance map into a city.

Takes sources/_<city>_sources.json ({spotId: [{name,tier,url,note?}]}) and writes
those `sources` onto matching spots in BOTH:
  - sources/<city>.json   (the seed — so a future curate run keeps them), and
  - cities/<city>.json    (the live generated file — so the site shows them now
                           without a full curate/Resy re-run).

Every citation is re-run through curate._sources() with the city's allowlist, so
nothing untrusted can sneak in via a hand-authored research file either.

  python merge_sources.py nyc
"""
import json
import sys
from pathlib import Path

import curate  # reuse the allowlist gate

SCR = Path(__file__).resolve().parent
ROOT = SCR.parent


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def dump(p, obj):
    Path(p).write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main(city):
    prov_path = SCR / "sources" / f"_{city}_sources.json"
    seed_path = SCR / "sources" / f"{city}.json"
    live_path = ROOT / "cities" / f"{city}.json"
    prov = load(prov_path)

    # Gate every entry through the allowlist (defense in depth).
    gated = {sid: curate._sources(srcs, city) for sid, srcs in prov.items()}
    gated = {sid: s for sid, s in gated.items() if s}
    total = sum(len(s) for s in gated.values())
    print(f"{len(gated)} venues, {total} vetted sources after allowlist gate")

    def apply_to(spots):
        n = 0
        for spot in spots:
            s = gated.get(spot.get("id"))
            if s:
                spot["sources"] = s
                n += 1
        return n

    # Seed is a bare list; live file is {meta, spots:[...]}.
    seed = load(seed_path)
    ns = apply_to(seed)
    dump(seed_path, seed)

    live = load(live_path)
    spots = live["spots"] if isinstance(live, dict) else live
    nl = apply_to(spots)
    dump(live_path, live)

    print(f"seed: tagged {ns} spots -> {seed_path.name}")
    print(f"live: tagged {nl} spots -> cities/{city}.json")
    missing = set(gated) - {sp.get("id") for sp in spots}
    if missing:
        print(f"WARNING: {len(missing)} researched ids not found in city: {sorted(missing)}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "nyc")
