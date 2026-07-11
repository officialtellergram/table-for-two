"""
opentable_find.py — slot-level OpenTable availability, proven 2026-07-11.

How (and why this shape):
- Plain HTTP and *headless* browsers are blocked below the page layer: Akamai
  kills the h2 connection for automated TLS fingerprints, and headless with a
  spoofed UA gets a flat "Access Denied". A real headful Edge window passes
  cleanly. We park it off-screen (--window-position=-2400,-2400) so nothing
  visibly flashes; runs from a residential IP like the Resy poller.
- No protocol reverse-engineering: loading the restaurant page fires the
  GraphQL we need, and we just listen for the responses:
    opname=RestaurantsAvailability        requested day; timeOffsetMinutes is
                                          relative to the REQUESTED TIME, and the
                                          payload includes ~15 nearby alternates,
                                          so filter by restaurantId
    opname=RestaurantMultiDayAvailability ~4 weeks in one shot, this venue only;
                                          timeOffsetMinutes is minutes FROM
                                          MIDNIGHT, dayOffset from the requested
                                          date; ~8 slots/day (a preview rail —
                                          enough for the radar)
- One page load = one venue's whole window, so the sniper calls this once per
  venue, not once per day. Reuse a single OTBrowser across venues per sweep.

CAVEAT: automating OpenTable is against their ToS and can break when they
tighten bot detection. Fine for a personal beta; the legit path for a public
launch is their partner/affiliate API.

  python opentable_find.py "https://www.opentable.com/r/dalia-boston" 2026-07-13 2
"""
import sys
from datetime import date, datetime, timedelta

_ARGS = ["--disable-blink-features=AutomationControlled",
         "--window-position=-2400,-2400"]   # headful but parked off-screen


def _hhmm(minutes):
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


class OTBrowser:
    """One real Edge window reused across venues (launch is the slow part)."""

    def __init__(self, headless=False):
        self._pw = None
        self._browser = None
        self._headless = headless   # True = blocked by Akamai; keep for experiments

    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            channel="msedge", headless=self._headless, args=_ARGS)
        return self

    def __exit__(self, *exc):
        try:
            if self._browser:
                self._browser.close()
        finally:
            if self._pw:
                self._pw.stop()
        return False

    def slots(self, url, day, party=2, at="19:00", settle_ms=12000):
        """Open slots for one venue: the requested day plus the multiday preview.
        Returns [{date, time, type}] sorted; [] on any miss (challenge, closed).
        `day` anchors the request; multiday extends ~4 weeks past it."""
        base = date.fromisoformat(day)
        req_min = int(at[:2]) * 60 + int(at[3:5])
        payloads = {}   # opname -> body

        def on_response(resp):
            u = resp.url
            if "opentable.com/dapi/fe/gql" not in u or "opname=Restaurant" not in u:
                return
            if "json" not in (resp.headers or {}).get("content-type", ""):
                return
            try:
                body = resp.json()
            except Exception:
                return
            for op in ("RestaurantsAvailability", "RestaurantMultiDayAvailability"):
                if f"opname={op}" in u:
                    payloads[op] = body

        sep = "&" if "?" in url else "?"
        full = f"{url}{sep}covers={party}&dateTime={day}T{at}"
        for attempt in range(2):   # ~1 in 3 loads hits a transient challenge; retry once
            ctx = self._browser.new_context(viewport={"width": 1280, "height": 900},
                                            locale="en-US")
            ctx.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
            page = ctx.new_page()
            page.on("response", on_response)
            try:
                page.goto(full, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(settle_ms)
            except Exception:
                pass   # whatever responses arrived before the miss still count
            finally:
                ctx.close()
            if payloads:
                break

        out = {}   # (date, time) -> slot dict

        def avail(body):
            return ((body or {}).get("data") or {}).get("availability") or []

        # Multiday first: single venue, minutes-from-midnight, ~4 weeks.
        rid = None
        for r in avail(payloads.get("RestaurantMultiDayAvailability")):
            rid = r.get("restaurantId")
            for d in r.get("availabilityDays") or []:
                day_iso = (base + timedelta(days=d.get("dayOffset", 0))).isoformat()
                for sl in d.get("slots") or []:
                    if not sl.get("isAvailable"):
                        continue
                    t = _hhmm(sl["timeOffsetMinutes"])
                    out[(day_iso, t)] = {"date": day_iso, "time": t,
                                         "type": sl.get("type") or ""}

        # Requested day: offsets relative to the requested time; alternates mixed
        # in, so only trust it when we know this venue's id from the multiday call.
        for r in avail(payloads.get("RestaurantsAvailability")):
            if rid is not None and r.get("restaurantId") != rid:
                continue
            if rid is None and len(avail(payloads.get("RestaurantsAvailability"))) > 1:
                continue   # can't tell which is ours — skip rather than guess
            for d in r.get("availabilityDays") or []:
                day_iso = (base + timedelta(days=d.get("dayOffset", 0))).isoformat()
                for sl in d.get("slots") or []:
                    if not sl.get("isAvailable"):
                        continue
                    t = _hhmm(req_min + sl["timeOffsetMinutes"])
                    out[(day_iso, t)] = {"date": day_iso, "time": t,
                                         "type": sl.get("type") or ""}

        return sorted(out.values(), key=lambda s: (s["date"], s["time"]))


def find(url, day, party=2):
    """One-shot CLI/diagnostic helper."""
    with OTBrowser() as ot:
        return ot.slots(url, day, party)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: python opentable_find.py <opentable_url> <YYYY-MM-DD> [party]")
        sys.exit(1)
    t0 = datetime.now()
    res = find(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 2)
    print(f"{len(res)} open slots ({(datetime.now() - t0).seconds}s):")
    for s in res[:40]:
        print(f"  {s['date']} {s['time']}" + (f"  {s['type']}" if s['type'] else ""))
