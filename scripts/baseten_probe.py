"""Probe Muse Spark Open on Baseten with the hackathon key (agent.openweights).

  python scripts/baseten_probe.py                 # hello + one tool-call round, raw shapes
  python scripts/baseten_probe.py --full "Get four of us into Carbone this Saturday around eight"
  python scripts/baseten_probe.py --effort medium --full "..."

The key comes from BASETEN_API_KEY or the env block of .claude/settings.local.json
(git-ignored); it is never printed. Each probe is one or two calls, cents at most.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent import config, openweights  # noqa: E402


def show(label: str, resp: dict) -> dict:
    ch = (resp.get("choices") or [{}])[0]
    msg = ch.get("message") or {}
    u = resp.get("usage") or {}
    print(f"\n== {label}: model={resp.get('model')} finish={ch.get('finish_reason')} "
          f"usage={u.get('prompt_tokens')}/{u.get('completion_tokens')}")
    print("   message keys:", sorted(msg.keys()))
    r = msg.get("reasoning_content") or msg.get("reasoning") or ""
    if r:
        print(f"   reasoning ({len(r)} chars):", r[:240].replace("\n", " "), "…")
    c = msg.get("content")
    print("   content:", (c if isinstance(c, str) else json.dumps(c))[:400] if c else repr(c))
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function") or {}
        print(f"   tool_call {tc.get('id')}: {fn.get('name')}({fn.get('arguments')})")
    return msg


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", metavar="MESSAGE", help="run the whole concierge loop on Spark Open")
    ap.add_argument("--city", default="nyc")
    ap.add_argument("--effort", default=None, help="reasoning_effort: low|medium|high|xhigh")
    ap.add_argument("--model", default=None, help=f"default {config.OPENWEIGHTS_MODEL}")
    a = ap.parse_args()
    if a.effort:
        config.OPENWEIGHTS_EFFORT = a.effort
    print("base:", config.BASETEN_BASE_URL, "model:", a.model or config.OPENWEIGHTS_MODEL,
          "effort:", config.OPENWEIGHTS_EFFORT, "key:", "present" if config.has_baseten_key() else "MISSING")
    if not config.has_baseten_key():
        return 2

    if a.full:
        t0 = time.time()
        for ev in openweights.run(a.full, a.city, model=a.model, fallback=False):
            t = ev["type"]
            if t == "usage":
                print(f"[{t}] round {ev['round']} {ev['model']} {ev['ms']} ms in={ev['input_tokens']} out={ev['output_tokens']} stop={ev['stop_reason']}")
            elif t == "thinking":
                print(f"[{t}] {ev['chars']} chars: {ev['text'][:160].replace(chr(10), ' ')}…")
            elif t == "tool_call":
                print(f"[{t}] {ev['name']} {json.dumps(ev['input'])}")
            elif t == "tool_result":
                print(f"[{t}] {ev['name']} ok={ev['ok']} {ev['bytes']} B: {ev['preview'][:160]}")
            elif t == "final":
                print(f"\n[{t}] rounds={ev['rounds']} in={ev['input_tokens']} out={ev['output_tokens']} "
                      f"resy={ev.get('resy_calls_used')} ({time.time() - t0:.1f} s)\n{ev['text']}")
            else:
                print(f"[{t}] {ev.get('text')}")
        return 0

    t0 = time.time()
    hello = openweights.chat([{"role": "user", "content": "In one short sentence, say hello to a guest at a restaurant."}],
                             model=a.model)
    show(f"hello ({time.time() - t0:.1f} s)", hello)

    t0 = time.time()
    tools = openweights.openai_tools()
    msgs = [{"role": "system", "content": "You are a restaurant concierge. Use the tools; call search_spots first."},
            {"role": "user", "content": "Find Carbone in New York City."}]
    r = openweights.chat(msgs, tools, model=a.model)
    msg = show(f"tool round ({time.time() - t0:.1f} s)", r)
    if not msg.get("tool_calls"):
        print("\n!! no tool_calls: Baseten's Spark Open did not call a function. Fall back to the sub-task plan.")
        return 1
    print("\nOK: function calling works; try --full for the whole loop.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
