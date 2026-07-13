-- Table for Two — Stage 2 schema (public sign-ups + email alerts).
--
-- Stage 1 alerts one person over Telegram from a local watchlist.json. Stage 2
-- lets ANYONE sign up and get emailed when a matching table opens. Identity is
-- delegated to Supabase Auth (auth.users) — we never store passwords here; the
-- frontend uses magic-link / OTP.
--
-- Safe to paste whole into the Supabase SQL editor, or apply with `supabase db push`.

-- profiles ------------------------------------------------------------------
-- One row per authenticated user. Mirrors the email so the ingest function can
-- address an alert without touching the protected auth schema on every match.
create table if not exists public.profiles (
  id          uuid primary key references auth.users (id) on delete cascade,
  email       text,
  created_at  timestamptz not null default now()
);

-- Populate a profile automatically the moment Supabase Auth creates a user, so
-- the app never has to remember to do it (and can't race the first watchlist).
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer set search_path = public
as $$
begin
  insert into public.profiles (id, email)
  values (new.id, new.email)
  on conflict (id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- watchlists ----------------------------------------------------------------
-- A user can keep several. Column names mirror scraper/notify.py's watch shape
-- ({city, venues, earliest, latest, dates, party}) so the matching logic in the
-- Edge Function stays a straight port.
--
-- `venues` is jsonb so it can hold either the string 'all' or an array of spot
-- ids — the same duality the Python side already handles.
create table if not exists public.watchlists (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references auth.users (id) on delete cascade,
  city        text not null,
  venues      jsonb not null default '"all"'::jsonb,   -- 'all' | ["spot-id", ...]
  earliest    text,                                    -- 24h 'HH:MM', inclusive
  latest      text,                                    -- 24h 'HH:MM', inclusive
  dates       jsonb,                                    -- null = any date, else ["YYYY-MM-DD", ...]
  party       int  not null default 2,
  active      boolean not null default true,
  created_at  timestamptz not null default now()
);

create index if not exists watchlists_user_idx   on public.watchlists (user_id);
-- The ingest function scans active watchlists by city on every sweep.
create index if not exists watchlists_active_city_idx on public.watchlists (city) where active;

-- alerts_sent ---------------------------------------------------------------
-- Dedupe ledger: one row per (user, slot) we've already emailed. slot_key is a
-- stable digest of the slot (see slotKey() in the Edge Function) so re-seeing
-- the same table on the next sweep doesn't re-alert.
create table if not exists public.alerts_sent (
  id        bigint generated always as identity primary key,
  user_id   uuid not null references auth.users (id) on delete cascade,
  slot_key  text not null,
  sent_at   timestamptz not null default now()
);

-- The dedupe guarantee. The Edge Function relies on this to make a losing
-- concurrent insert fail loudly rather than double-send.
create unique index if not exists alerts_sent_user_slot_uniq
  on public.alerts_sent (user_id, slot_key);

-- Row Level Security --------------------------------------------------------
-- Everything below is user-scoped. The ingest function talks to the DB with the
-- service_role key, which BYPASSES RLS — so it can read every user's watchlists
-- and write the ledger while ordinary logged-in clients stay boxed into their
-- own rows.
alter table public.profiles   enable row level security;
alter table public.watchlists enable row level security;
alter table public.alerts_sent enable row level security;

-- profiles: a user sees and edits only their own row.
create policy "profiles: self read"   on public.profiles
  for select using (auth.uid() = id);
create policy "profiles: self update" on public.profiles
  for update using (auth.uid() = id) with check (auth.uid() = id);

-- watchlists: full CRUD, but only over rows you own.
create policy "watchlists: self read"   on public.watchlists
  for select using (auth.uid() = user_id);
create policy "watchlists: self insert" on public.watchlists
  for insert with check (auth.uid() = user_id);
create policy "watchlists: self update" on public.watchlists
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "watchlists: self delete" on public.watchlists
  for delete using (auth.uid() = user_id);

-- alerts_sent: read-only from the client (so a user can see their history);
-- inserts happen only via the service role, which skips these policies anyway.
create policy "alerts_sent: self read" on public.alerts_sent
  for select using (auth.uid() = user_id);
