-- city_demand(): aggregated demand from city_requests, safe for anonymous reads.
-- Exposes ONLY city name + request count + latest timestamp — never emails or
-- coordinates. This is what lets the autonomous city-concierge agent (and any
-- future public "most requested" widget) read demand without holding a secret.
create or replace function public.city_demand()
returns table(city text, requests bigint, latest timestamptz)
language sql
security definer
set search_path = public
as $$
  select city_guess, count(*), max(created_at)
  from city_requests
  where city_guess is not null and length(trim(city_guess)) > 0
  group by city_guess
  order by count(*) desc, max(created_at) desc
$$;

revoke all on function public.city_demand() from public;
grant execute on function public.city_demand() to anon, authenticated;
