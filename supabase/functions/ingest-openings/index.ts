// ingest-openings — Stage 2 fan-out: turn newly-opened tables into per-user emails.
//
// The local radar (residential IP) POSTs the sweep's NEW slots here. We match
// each slot against every user's active watchlists — the same rules as
// scraper/notify.py — and email each user once per slot, recording the send in
// alerts_sent so the next sweep doesn't re-alert.
//
// Why an Edge Function and not the cloud radar: Resy blocks datacenter IPs, so
// polling must stay on the home box. But the fan-out (which needs the DB and the
// service_role key) has no business living on that machine — so the radar just
// ships the "new" list here and this runs the multi-user side in Supabase.
//
// Auth is a shared secret (INGEST_SECRET), not a user JWT: the caller is our own
// server-side radar, not a browser.

import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

// --- feed item shape (mirrors cities/just-opened.json items) ---------------
interface FeedItem {
  city: string;
  spotId: string;
  name: string;
  neighborhood?: string;
  cuisine?: string;
  date: string; // YYYY-MM-DD
  time: string; // 24h HH:MM
  type?: string;
  party?: number;
  url?: string;
  firstSeen?: string;
  new?: boolean;
}

interface Watchlist {
  id: string;
  user_id: string;
  city: string;
  venues: string | string[]; // 'all' | [spotId, ...]
  earliest: string | null;
  latest: string | null;
  dates: string[] | null;
  party: number;
  active: boolean;
}

const env = (k: string) => Deno.env.get(k) ?? "";

// Stable identity for a slot, used as the alerts_sent dedupe key. Any field that
// distinguishes "a different table you'd want to know about" belongs here.
function slotKey(it: FeedItem): string {
  return [it.city, it.spotId, it.date, it.time, it.type ?? "", it.party ?? ""].join("|");
}

// Direct port of _matches() in scraper/notify.py — keep the two in sync.
function matches(it: FeedItem, w: Watchlist): boolean {
  if (w.city && it.city !== w.city) return false;
  const v = w.venues;
  if (v && v !== "all" && Array.isArray(v) && !v.includes(it.spotId)) return false;
  const t = it.time ?? "";
  if (w.earliest && t < w.earliest) return false; // 'HH:MM' sorts lexicographically = chronologically
  if (w.latest && t > w.latest) return false;
  if (w.dates && w.dates.length && !w.dates.includes(it.date)) return false;
  return true;
}

// --- email: provider-agnostic seam ----------------------------------------
// TODO(you): swap the body for whatever you end up using (Postmark, SES, etc.).
// The rest of the function only knows this signature, so a provider change never
// leaks past here. Default is Resend's REST API — no SDK, one fetch.
async function sendEmail(to: string, subject: string, html: string): Promise<void> {
  const key = env("RESEND_API_KEY");
  const from = env("ALERT_FROM"); // e.g. "Table for Two <alerts@yourdomain.com>"
  if (!key || !from) throw new Error("email not configured (RESEND_API_KEY / ALERT_FROM)");

  const res = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: { "Authorization": `Bearer ${key}`, "Content-Type": "application/json" },
    body: JSON.stringify({ from, to, subject, html }),
  });
  if (!res.ok) throw new Error(`resend ${res.status}: ${await res.text()}`);
}

function alertHtml(it: FeedItem): string {
  const bits = [
    it.type ? `· ${it.type}` : "",
    it.neighborhood ? `· ${it.neighborhood}` : "",
  ].join(" ");
  const grab = it.url ? `<p><a href="${it.url}">Grab it →</a></p>` : "";
  return `<div style="font-family:system-ui,sans-serif">
    <p>✌️ <b>${it.name}</b> — a table for ${it.party ?? 2} just opened.</p>
    <p>${it.date} at ${it.time} ${bits}</p>
    ${grab}
  </div>`;
}

Deno.serve(async (req) => {
  if (req.method !== "POST") return new Response("method not allowed", { status: 405 });

  // Shared-secret gate. Constant-ish check; the secret never reaches a client.
  const secret = env("INGEST_SECRET");
  if (!secret || req.headers.get("x-ingest-secret") !== secret) {
    return new Response("unauthorized", { status: 401 });
  }

  let body: { items?: FeedItem[] };
  try {
    body = await req.json();
  } catch {
    return new Response("bad json", { status: 400 });
  }

  // Caller should only send new:true items, but never trust the caller.
  const items = (body.items ?? []).filter((it) => it && it.new === true);
  if (!items.length) return Response.json({ matched: 0, sent: 0 });

  // service_role bypasses RLS — required to read across all users' watchlists.
  const supa = createClient(env("SUPABASE_URL"), env("SUPABASE_SERVICE_ROLE_KEY"));

  // Pull the active watchlists once, only for the cities present in this batch.
  const cities = [...new Set(items.map((it) => it.city))];
  const { data: watchRows, error: wErr } = await supa
    .from("watchlists")
    .select("id,user_id,city,venues,earliest,latest,dates,party,active")
    .eq("active", true)
    .in("city", cities);
  if (wErr) return new Response(`db error: ${wErr.message}`, { status: 500 });
  const watchlists = (watchRows ?? []) as Watchlist[];

  // Cache emails so we don't refetch a profile per matched slot.
  const emailCache = new Map<string, string | null>();
  async function emailFor(userId: string): Promise<string | null> {
    if (emailCache.has(userId)) return emailCache.get(userId)!;
    const { data } = await supa.from("profiles").select("email").eq("id", userId).maybeSingle();
    const email = data?.email ?? null;
    emailCache.set(userId, email);
    return email;
  }

  let matched = 0;
  let sent = 0;

  for (const it of items) {
    const key = slotKey(it);
    // A user can own several watchlists; one matching slot = at most one alert.
    const users = new Set<string>();
    for (const w of watchlists) if (matches(it, w)) users.add(w.user_id);

    for (const userId of users) {
      matched++;

      // Claim the (user, slot) BEFORE sending. The unique index makes a duplicate
      // (e.g. an overlapping sweep) fail here, so we never double-email.
      const { error: insErr } = await supa
        .from("alerts_sent")
        .insert({ user_id: userId, slot_key: key });
      if (insErr) continue; // already sent (unique violation) or transient DB error — skip

      const to = await emailFor(userId);
      if (!to) continue;

      try {
        await sendEmail(to, `A table just opened: ${it.name}`, alertHtml(it));
        sent++;
      } catch (e) {
        // Don't let one bad address / provider hiccup abort the batch. Roll back
        // the claim so a later sweep can retry this user+slot.
        console.error("sendEmail failed", userId, key, String(e));
        await supa.from("alerts_sent").delete().eq("user_id", userId).eq("slot_key", key);
      }
    }
  }

  return Response.json({ matched, sent });
});
