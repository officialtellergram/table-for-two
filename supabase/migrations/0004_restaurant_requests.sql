-- Restaurant requests: visitors nominate a specific spot for a covered city.
-- Flow: widget inserts 'pending' -> owner flips status to 'approved'/'denied' in
-- the Supabase Table Editor -> the radar Action syncs approved rows (via the
-- restaurant_queue RPC, no emails exposed) into the repo -> the hourly
-- city-concierge agent vets approved spots under the anti-slop covenant and,
-- only if they survive, adds them to cities/<city_key>.json.
create table if not exists public.restaurant_requests (
  id uuid primary key default gen_random_uuid(),
  city_key text not null,
  restaurant_name text not null,
  note text,
  email text,
  status text not null default 'pending'
    check (status in ('pending','approved','denied')),
  source text not null default 'widget',
  created_at timestamptz not null default now(),
  decided_at timestamptz
);

alter table public.restaurant_requests enable row level security;

-- visitors can file a request; nobody anonymous can read them back (emails)
create policy "anon can insert restaurant requests"
  on public.restaurant_requests for insert
  to anon, authenticated
  with check (status = 'pending' and char_length(restaurant_name) between 2 and 120);

-- Approved-but-unprocessed queue for the repo bridge. No emails, no pending rows.
create or replace function public.restaurant_queue()
returns table(id uuid, city_key text, restaurant_name text, note text, approved_at timestamptz)
language sql
security definer
set search_path = public
as $$
  select id, city_key, restaurant_name, note, coalesce(decided_at, created_at)
  from restaurant_requests
  where status = 'approved'
  order by coalesce(decided_at, created_at) asc
$$;

revoke all on function public.restaurant_queue() from public;
grant execute on function public.restaurant_queue() to anon, authenticated;
