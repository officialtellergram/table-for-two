// auth.js — Table for Two Stage-2 client: sign-in + watchlist CRUD.
//
// Plain ES module, no build step. index.html is a single static file, so this
// loads straight from a CDN. Drop this into the page when you're ready to wire
// up sign-ups (not wired yet — this is just the module):
//
//   <script type="module">
//     import { initAuth, signInWithEmail, getSession, saveWatchlist, listWatchlists }
//       from './web/auth.js';
//     initAuth('https://YOUR-REF.supabase.co', 'YOUR-ANON-PUBLIC-KEY');
//     // then, e.g. on a form submit:
//     await signInWithEmail(emailInput.value);   // sends a magic link
//   </script>
//
// The URL + anon key are PUBLIC-safe (RLS is what protects the data) — fine to
// ship in the page. Never put the service_role key or INGEST_SECRET here.

import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

let supa = null;

function client() {
  if (!supa) throw new Error("call initAuth(url, anonKey) first");
  return supa;
}

// Call once on page load with your project URL + anon (public) key.
export function initAuth(supabaseUrl, anonKey) {
  supa = createClient(supabaseUrl, anonKey);
  return supa;
}

// Passwordless: Supabase emails a magic link / OTP. The redirect returns the
// user to this same page, where getSession() will then resolve.
export async function signInWithEmail(email) {
  const { error } = await client().auth.signInWithOtp({
    email,
    options: { emailRedirectTo: window.location.href },
  });
  if (error) throw error;
  return { ok: true }; // "check your email" — nothing else to do here
}

export async function signOut() {
  const { error } = await client().auth.signOut();
  if (error) throw error;
}

export async function getSession() {
  const { data } = await client().auth.getSession();
  return data.session; // null when signed out
}

// Persist a watchlist for the current user. RLS fills/enforces user_id via the
// session, but we set it explicitly so the insert policy's check passes cleanly.
// `watch` = { city, venues:'all'|[spotId], earliest, latest, dates, party }.
export async function saveWatchlist(watch) {
  const session = await getSession();
  if (!session) throw new Error("not signed in");
  const row = { ...watch, user_id: session.user.id };
  const { data, error } = await client().from("watchlists").insert(row).select().single();
  if (error) throw error;
  return data;
}

// RLS scopes this to the caller automatically — no user_id filter needed.
export async function listWatchlists() {
  const { data, error } = await client()
    .from("watchlists")
    .select("*")
    .order("created_at", { ascending: false });
  if (error) throw error;
  return data;
}

export async function deleteWatchlist(id) {
  const { error } = await client().from("watchlists").delete().eq("id", id);
  if (error) throw error;
}
