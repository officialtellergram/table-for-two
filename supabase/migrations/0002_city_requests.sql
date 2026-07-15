-- Phase 1 demand capture: log requests for cities we don't cover yet, so we know
-- where to expand next (and can notify requesters when a city launches).
create table if not exists public.city_requests (
  id          uuid primary key default gen_random_uuid(),
  city_guess  text,                                   -- nearest major metro (from geo) or user-typed
  lat         double precision,
  lng         double precision,
  email       text,                                   -- optional, for a launch notification
  source      text not null default 'manual',         -- 'geo' | 'manual'
  created_at  timestamptz not null default now()
);
create index if not exists city_requests_city_idx on public.city_requests (lower(city_guess));

-- Anyone (even signed-out) may submit a request; nobody may read them from the
-- client. Demand is reviewed with the service_role key only.
alter table public.city_requests enable row level security;
drop policy if exists "city_requests: anyone can request" on public.city_requests;
create policy "city_requests: anyone can request" on public.city_requests
  for insert to anon, authenticated with check (true);
