// Filter-gate harness — proves the quiz ingest filters actually filter.
// Extracts the PURE rankDeck block from index.html and asserts invariants
// against LIVE production data for every city × filter combination.
//   node match/test-filters.mjs
// Exit 0 = every invariant holds. Anything else = a filter is lying to users.
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const BASE = 'https://tablefortwo.city/';
const html = readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'index.html'), 'utf8');
const m = html.match(/PURE:BEGIN[\s\S]*?\*\/([\s\S]*?)\/\* PURE:END/);
if (!m) { console.error('PURE block not found'); process.exit(2); }
const rankDeck = new Function(`${m[1]}; return rankDeck;`)();

// deterministic jitter so runs are reproducible
const mulberry32 = a => () => {
  a |= 0; a = (a + 0x6D2B79F5) | 0;
  let t = Math.imul(a ^ (a >>> 15), 1 | a);
  t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
};

const j = async p => (await fetch(BASE + p)).json();
const idx = await j('cities/index.json');
const cities = idx.cities.filter(c => c.source?.type === 'json');
const radarAll = (await j('cities/just-opened.json')).items || [];
const today = new Date().toISOString().slice(0, 10);

const notchOf = s => (/^\$+$/.test(s.priceRange || '') ? s.priceRange.length : null);
const distOf = (s, sel) => {
  if (!sel.length) return 0;
  const n = notchOf(s); if (n == null) return 1;
  return Math.min(...sel.map(x => Math.abs(x - n)));
};
const tagsOf = s => new Set([...(s.vibe || []), ...(s.occasion || [])]);
const MEAL = /breakfast|brunch|lunch|dinner|tapas|drinks/;

let checks = 0, fails = 0;
const fail = msg => { fails++; console.error('  FAIL ' + msg); };

for (const c of cities) {
  const data = await j(c.source.url);
  const spots = (data.spots || data).filter(s => s.name);
  const radar = radarAll.filter(i => i.city === c.key);

  for (const budget of [[], ['$'], ['$$'], ['$$$'], ['$$$$'], ['$', '$$']]) {
    for (const when of ['tonight', 'week']) {
      const A = { when, party: '2', budget: new Set(budget), vibe: new Set() };
      const r = rankDeck(spots, radar, A, mulberry32(42), today);
      const sel = budget.map(b => b.length);
      const label = `${c.key} [${budget.join(',') || 'any'}] ${when}`;
      checks++;

      // S1 — deck shape + numbering
      if (r.deck.length > 16 || r.deck.some((x, i) => x.no !== i + 1)) fail(`${label}: deck shape/numbering`);

      if (sel.length) {
        const exact = spots.filter(s => distOf(s, sel) === 0).length;
        const within = d => spots.filter(s => distOf(s, sel) <= d).length;
        // B1 — every card within the declared relax distance
        const cap = r.budgetRelax === 'all' ? Infinity : r.budgetRelax;
        if (r.deck.some(x => distOf(x.s, sel) > cap)) fail(`${label}: card outside declared relax=${r.budgetRelax}`);
        // B2 — ample exact supply must mean NO relaxation and all-exact cards
        if (exact >= 8 && (r.budgetRelax !== 0 || r.deck.some(x => distOf(x.s, sel) !== 0)))
          fail(`${label}: exact supply ${exact} but relax=${r.budgetRelax}`);
        // B3 — 'all' only when even ±2 can't fill a deck
        if (r.budgetRelax === 'all' && within(2) >= 8) fail(`${label}: relaxed to all with within2=${within(2)}`);
        // B4 — the field repro: $ selected + any relax<'all' must exclude $$$$
        if (budget.length === 1 && budget[0] === '$' && r.budgetRelax !== 'all'
            && r.deck.some(x => (x.s.priceRange || '') === '$$$$'))
          fail(`${label}: $$$$ shown to a $ picker (relax=${r.budgetRelax})`);
      }

      // T1 — tonight with ample open supply ⇒ all-open deck
      if (when === 'tonight' && !sel.length) {
        const openSupply = spots.filter(s => {
          const av = s.availability, ds = (av && av.dates || []).filter(d => d >= today);
          return !!(av && av.open && ds.length);
        }).length;
        if (openSupply >= 16 && r.deck.some(x => !x.open && !x.jo))
          fail(`${label}: openSupply=${openSupply} but non-open card in deck`);
      }
    }
  }

  // V1 — a well-supplied vibe must hard-filter
  const freq = {};
  for (const s of spots) for (const t of tagsOf(s)) if (!MEAL.test(t)) freq[t] = (freq[t] || 0) + 1;
  const [topTag, supply] = Object.entries(freq).sort((a, b) => b[1] - a[1])[0] || [];
  if (topTag && supply >= 8) {
    checks++;
    const A = { when: 'week', party: '2', budget: new Set(), vibe: new Set([topTag]) };
    const r = rankDeck(spots, radar, A, mulberry32(7), today);
    if (r.vibeRelaxed) fail(`${c.key} vibe[${topTag}] supply=${supply} but vibeRelaxed`);
    if (r.deck.some(x => !tagsOf(x.s).has(topTag))) fail(`${c.key} vibe[${topTag}]: non-matching card in deck`);
  }
}

console.log(`${checks} scenario checks across ${cities.length} cities — ${fails ? fails + ' FAILURES' : 'ALL GATES HOLD'}`);
process.exit(fails ? 1 : 0);
