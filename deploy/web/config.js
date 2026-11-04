// web/config.js — public Supabase config for the browser.
//
// These two values are PUBLIC-safe by design: the anon key only grants what Row
// Level Security allows, so shipping it in a static page is expected. The
// service_role key and INGEST_SECRET are SECRET and never appear here.
export const SUPABASE_URL = "https://thrshcloruvcxrowfzui.supabase.co";
export const SUPABASE_ANON_KEY =
  "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InRocnNoY2xvcnV2Y3hyb3dmenVpIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODM5NzMyMTYsImV4cCI6MjA5OTU0OTIxNn0.19DgFDy6ZMGXO3c1r9HosUZ_iVyUoAqkkv8-H8y8IVs";

// Concierge agent service (hackathon, agent/app.py). The deployed URL comes from
// `modal deploy agent/modal_app.py`; until then only local runs work. A visitor
// can point the page elsewhere with ?concierge=<url> (remembered in localStorage),
// which is how the demo talks to a `modal serve` dev URL.
export const CONCIERGE_URL_PROD = "https://officialtellergram--table-for-two-concierge-web.us-east.modal.run";
export const CONCIERGE_URL = (() => {
  try {
    const q = new URLSearchParams(location.search).get("concierge");
    if (q) localStorage.setItem("t42-concierge", q);
    const saved = localStorage.getItem("t42-concierge");
    if (saved) return saved.replace(/\/+$/, "");
  } catch (e) { /* storage blocked: fall through */ }
  const h = location.hostname;
  if (h === "localhost" || h === "127.0.0.1" || h === "") return "http://127.0.0.1:8000";
  return CONCIERGE_URL_PROD;
})();
