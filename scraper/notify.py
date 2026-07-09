"""
notify.py — "a table just opened" alerts (Stage 1: Telegram).

The radar (sniper.py) flags genuinely-new slots each sweep. This sends a push
message for the ones matching your watchlist. Telegram is the Stage-1 channel:
free, instant, no accounts, and a 3-line HTTP call — perfect for proving the
loop before we build sign-ups + email/push (Stage 2).

Setup (one time):
  1. In Telegram, message @BotFather -> /newbot -> copy the bot token.
  2. Message your new bot once, then open
     https://api.telegram.org/bot<TOKEN>/getUpdates to find your numeric chat id.
  3. Put them in scraper/.notify.json (gitignored):
        { "token": "123456:ABC...", "chat_id": "987654321" }
     (or set env TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID)
  4. Edit scraper/watchlist.json (copy watchlist.example.json) to say what to watch.

Nothing secret is committed; creds live only in the gitignored .notify.json / env.
"""
import os, json, urllib.request, urllib.parse
from pathlib import Path

SCR = Path(__file__).resolve().parent


def _creds():
    tok = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if tok and chat:
        return tok, chat
    p = SCR / ".notify.json"
    if p.exists():
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            return d.get("token"), d.get("chat_id")
        except Exception:
            pass
    return None, None


def _watches():
    p = SCR / "watchlist.json"
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("watches", [])
    except Exception:
        return []


def _send(token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": chat_id, "text": text,
        "parse_mode": "HTML", "disable_web_page_preview": "true",
    }).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=15) as r:
            return r.status == 200
    except Exception:
        return False


def _matches(item, watch):
    """A watch is {city, venues:[spotId]|'all', earliest:'17:00', latest, dates:[...]}."""
    if watch.get("city") and item.get("city") != watch["city"]:
        return False
    v = watch.get("venues")
    if v and v != "all" and item.get("spotId") not in v:
        return False
    t = item.get("time", "")
    if watch.get("earliest") and t < watch["earliest"]:
        return False
    if watch.get("latest") and t > watch["latest"]:
        return False
    if watch.get("dates") and item.get("date") not in watch["dates"]:
        return False
    return True


def notify_new(items):
    """Alert once for each NEW slot matching any watch. Returns the number sent."""
    token, chat = _creds()
    watches = _watches()
    if not token or not chat or not watches:
        return 0
    sent = 0
    for it in items:
        if not it.get("new"):
            continue
        if not any(_matches(it, w) for w in watches):
            continue
        text = (f"✌️ <b>{it.get('name','')}</b> — a table for {it.get('party', 2)} just opened\n"
                f"{it.get('date','')} at {it.get('time','')}"
                + (f" · {it['type']}" if it.get('type') else "")
                + (f" · {it['neighborhood']}" if it.get('neighborhood') else "") + "\n"
                + (f'<a href="{it["url"]}">Grab it →</a>' if it.get('url') else ""))
        if _send(token, chat, text):
            sent += 1
    return sent
