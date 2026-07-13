# Table for Two — Stage 2 (public sign-ups + email alerts)

Stage 1 alerts **you** over Telegram from a local `watchlist.json`. Stage 2 lets
**anyone** sign up on the site and get emailed when a matching table opens. This
folder is the backend for that: a Postgres schema, an Edge Function that fans a
sweep out to all subscribers, and the setup steps below.

Nothing here works until you plug in your own Supabase project. Follow in order.

---

## What talks to what

```
radar sweep (home PC)
   └─ writes cities/just-opened.json
   └─ scraper/notify_web.ps1  ──POST {items}──▶  ingest-openings (Edge Function)
                                                    ├─ match vs. everyone's watchlists
                                                    ├─ dedupe via alerts_sent
                                                    └─ sendEmail() (Resend)
web/auth.js (in the browser) ── sign-in + watchlist CRUD ──▶ Supabase (RLS-guarded)
```

---

## 1. Create the project

1. Go to <https://supabase.com>, sign in, **New project** (the free tier is fine).
2. Pick a name + a region near you, set a database password (save it), create.
3. When it finishes provisioning, open **Project Settings → API**. You need three
   values (copy them somewhere for the steps below):
   - **Project URL** — `https://<ref>.supabase.co`
   - **anon / public key** — the public client key
   - **service_role key** — the secret admin key (under "Project API keys",
     reveal it)

### PUBLIC-safe vs. SECRET — read this before pasting anything

| Value                | Where it may live                          | Never |
|----------------------|--------------------------------------------|-------|
| Project URL          | frontend, git                              | —     |
| anon (public) key    | frontend (`web/auth.js`), git              | —     |
| **service_role key** | Supabase function secrets only             | frontend, git |
| **INGEST_SECRET**    | Supabase function secrets + home-PC env    | frontend, git |
| **RESEND_API_KEY**   | Supabase function secrets only             | frontend, git |

RLS (row-level security) is what keeps the anon key safe to publish — a logged-in
user can only ever see their own rows. The service_role key bypasses RLS, so it
stays server-side, always.

---

## 2. Apply the schema

**Option A — SQL editor (no CLI):** open **SQL Editor → New query**, paste the
entire contents of `supabase/migrations/0001_init.sql`, **Run**.

**Option B — CLI:** with the [Supabase CLI](https://supabase.com/docs/guides/cli)
installed and `supabase link --project-ref <ref>` done:

```bash
supabase db push
```

This creates `profiles`, `watchlists`, `alerts_sent`, the sign-up trigger, and
the RLS policies.

---

## 3. Deploy the Edge Function

Requires the CLI and a linked project:

```bash
supabase functions deploy ingest-openings
```

`SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` are injected into every function
automatically — you do **not** set those. You DO set the three below.

---

## 4. Set the function secrets

```bash
supabase secrets set INGEST_SECRET="<a-long-random-string-you-invent>"
supabase secrets set RESEND_API_KEY="re_...."          # from resend.com → API Keys
supabase secrets set ALERT_FROM="Table for Two <alerts@yourdomain.com>"
```

- **INGEST_SECRET** — invent any long random string; it just has to match what
  the home PC sends. (e.g. `openssl rand -hex 24`)
- **RESEND_API_KEY** — sign up at <https://resend.com>, verify a sending domain,
  create an API key. `ALERT_FROM` must use a domain you've verified there.
- Swapping email providers? Only `sendEmail()` in `index.ts` needs editing.

---

## 5. Point the home PC at it

On the Windows radar box, set two environment variables (in the scheduled task,
or your PowerShell profile):

```powershell
$env:INGEST_URL    = "https://<ref>.functions.supabase.co/ingest-openings"
$env:INGEST_SECRET = "<the same long random string from step 4>"
```

Then, after a sweep writes the feed, run the bridge:

```powershell
& 'C:\Users\Karen Plankton\Desktop\hardtobook-dashboard\scraper\notify_web.ps1'
```

Wire it into `radar_run.ps1` / `radar_ot_run.ps1` yourself once you've reviewed
it — it's intentionally left un-wired. It fails soft, so a Stage-2 outage can't
break the local sweep or the Pages push.

---

## 6. Wire the frontend (later)

`web/auth.js` is ready but **not** imported by `index.html` yet. The usage
snippet is in the comment at the top of that file. Use the Project URL + anon key
from step 1 — both are public-safe.

---

## 7. Smoke test

With the function deployed and secrets set, send a fake NEW slot. Use a `city`
you actually have a watchlist row for, or you'll get `matched: 0`.

```bash
curl -i -X POST "https://<ref>.functions.supabase.co/ingest-openings" \
  -H "x-ingest-secret: <INGEST_SECRET>" \
  -H "Content-Type: application/json" \
  -d '{"items":[{"city":"nyc","spotId":"via-carota","name":"Via Carota","date":"2026-07-15","time":"19:00","type":"Dining Room","party":2,"url":"https://resy.com/","new":true}]}'
```

Expected: `200` with `{"matched":N,"sent":M}`. A wrong/missing secret → `401`.
Re-running the exact same call → the slot is already in `alerts_sent`, so
`sent` drops to `0` (dedupe working).

---

## Secrets recap (what YOU must supply)

| Name                       | Get it from                     | Goes where                          |
|----------------------------|---------------------------------|-------------------------------------|
| Project URL                | Settings → API                  | `web/auth.js`, `INGEST_URL`         |
| anon (public) key          | Settings → API                  | `web/auth.js`                       |
| service_role key           | Settings → API                  | (auto-injected — don't set)         |
| `INGEST_SECRET`            | you invent it                   | function secret + home-PC env       |
| `RESEND_API_KEY`           | resend.com → API Keys           | function secret                     |
| `ALERT_FROM`               | your verified Resend domain     | function secret                     |
| `INGEST_URL`               | your function's URL             | home-PC env                         |
