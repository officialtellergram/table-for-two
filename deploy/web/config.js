// web/config.js — public Supabase config for the browser.
//
// These two values are PUBLIC-safe by design: the anon key only grants what Row
// Level Security allows, so shipping it in a static page is expected. The
// service_role key and INGEST_SECRET are SECRET and never appear here.
export const SUPABASE_URL = "https://thrshcloruvcxrowfzui.supabase.co";
export const SUPABASE_ANON_KEY =
  "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InRocnNoY2xvcnV2Y3hyb3dmenVpIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODM5NzMyMTYsImV4cCI6MjA5OTU0OTIxNn0.19DgFDy6ZMGXO3c1r9HosUZ_iVyUoAqkkv8-H8y8IVs";
