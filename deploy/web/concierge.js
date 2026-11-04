// web/concierge.js — the "Get me in" panel (Meta hackathon, phase 2).
//
// Streams one planner run from the concierge service (agent/app.py, POST
// /ask/stream) over Server-Sent Events and renders it as it happens: a chip per
// tool call, then the NOW / DROP / WATCH plan. The cards under each tier are
// built from the tool results themselves (live Resy slots with booking links,
// the drop countdown and the venue's tips, the watch that was armed), so the
// page never has to trust prose for a time or a link. Muse Wonder does the
// planning on the server; this file only draws what it did.
//
// Voice: initVoice() (same module, next commit) wires the mic button to Muse
// Voice Transcribe through the service's /ask/voice and drops the transcript
// into the editable box before anything runs.
import { CONCIERGE_URL } from './config.js';

const $ = id => document.getElementById(id);
const esc = x => String(x == null ? '' : x).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

export const EXAMPLE = "Get four of us into Carbone this Saturday around eight, or something similar in the West Village if that's impossible.";

const TOOL_LABEL = {
  search_spots: 'search', get_spot: 'record', next_drop: 'next drop', booking_link: 'booking link',
  check_live_availability: 'live Resy check', similar_spots: 'alternates', create_watch: 'watch',
};

function argSummary(name, input) {
  const i = input || {};
  const who = i.query || i.spot_id || [i.neighborhood, i.cuisine, i.vibe, i.occasion].filter(Boolean).join(' ');
  const when = i.date || i.target_date || i.date_from || '';
  return [who, when].filter(Boolean).join(' · ');
}

// Plain text -> escaped HTML with URLs as links and **bold** markers dropped.
function rich(text) {
  const t = esc(String(text || '').replace(/\*\*/g, ''));
  return t.replace(/(https?:\/\/[^\s<>)]+)/g, u => `<a href="${u}" target="_blank" rel="noopener">${u.replace(/^https?:\/\//, '')}</a>`);
}

// Split the planner's answer into the three tiers it was asked to use.
export function tiers(answer) {
  const out = { NOW: '', DROP: '', WATCH: '', other: '' };
  let cur = 'other';
  for (const raw of String(answer || '').split('\n')) {
    const line = raw.replace(/^\s*[-*#_]+\s*/, '');
    const m = line.match(/^\**\s*(NOW|DROP|WATCH)\s*\**\s*:\s*(.*)$/i);
    if (m) { cur = m[1].toUpperCase(); out[cur] += (out[cur] ? '\n' : '') + m[2]; }
    else if (line.trim()) out[cur] += (out[cur] ? '\n' : '') + line;
  }
  return out;
}

function fmtCountdown(secs) {
  if (secs <= 0) return 'now';
  const d = Math.floor(secs / 86400), h = Math.floor(secs % 86400 / 3600), m = Math.floor(secs % 3600 / 60), s = Math.floor(secs % 60);
  const hms = [h, m, s].map(n => String(n).padStart(2, '0')).join(':');
  return d ? `${d}d ${hms}` : hms;
}

function prettyDates(dates) {
  if (!dates || !dates.length) return '';
  return dates.length === 1 ? dates[0] : `${dates[0]} to ${dates[dates.length - 1]}`;
}

async function* sse(resp) {
  const reader = resp.body.getReader();
  const dec = new TextDecoder();
  let buf = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf('\n\n')) >= 0) {
      const frame = buf.slice(0, i); buf = buf.slice(i + 2);
      let event = 'message', data = '';
      for (const line of frame.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim();
        else if (line.startsWith('data:')) data += line.slice(5).trim();
      }
      if (!data) continue;
      try { yield { event, data: JSON.parse(data) }; } catch (e) { /* skip a torn frame */ }
    }
  }
}

export function initConcierge(opts) {
  const o = Object.assign({
    getCity: () => ({ key: 'nyc', label: 'New York City' }),
    getParty: () => 2,
    getToken: async () => null,
    onSignIn: () => { const b = $('alertBtn'); if (b) b.click(); },
  }, opts || {});
  const scrim = $('cgScrim');
  if (!scrim) return null;
  const text = $('cgText'), go = $('cgGo'), status = $('cgStatus'), steps = $('cgSteps'),
    plan = $('cgPlan'), msg = $('cgMsg'), ctx = $('cgCtx');
  let abort = null, ticker = null, running = false;

  // Planner model: Muse Wonder on the Meta API (default) or Muse Spark Open, Meta's
  // open-weights model, served per token by Baseten (?model=spark-open or the toggle in
  // the panel; remembered per browser). The service falls back to Wonder by itself.
  let model = 'wonder';
  try { model = new URLSearchParams(location.search).get('model') || localStorage.getItem('t42-model') || 'wonder'; } catch (e) { /* private mode */ }
  const modelParam = () => model === 'spark-open' ? 'spark-open' : undefined;
  const modelLabel = () => model === 'spark-open' ? 'Muse Spark Open' : 'Muse Wonder';
  // Service model ids -> names for the status line (meta-models/muse-spark-open-1026 -> Muse Spark Open).
  const pretty = m => /spark-open/.test(m || '') ? 'Muse Spark Open' : /wonder/.test(m || '') ? 'Muse Wonder' : /spark/.test(m || '') ? 'Muse Spark' : (m || 'Muse');
  function setModel(m) {
    model = m === 'spark-open' ? 'spark-open' : 'wonder';
    try { localStorage.setItem('t42-model', model); } catch (e) { /* ignore */ }
    document.querySelectorAll('#cgModel button').forEach(b => {
      const on = b.dataset.model === model;
      b.classList.toggle('on', on); b.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
  }
  document.querySelectorAll('#cgModel button').forEach(b => { b.onclick = () => setModel(b.dataset.model); });
  setModel(model);

  function open() {
    scrim.hidden = false;
    const c = o.getCity();
    ctx.textContent = `${c.label.replace(/ — .*/, '')} · party of ${o.getParty()}`;
    setTimeout(() => text.focus(), 30);
  }
  function close() { scrim.hidden = true; if (abort) abort.abort(); }
  $('cgOpen').onclick = open;
  $('cgClose').onclick = close;
  scrim.addEventListener('click', e => { if (e.target === scrim) close(); });
  $('cgExample').onclick = e => { e.preventDefault(); text.value = EXAMPLE; text.focus(); };
  go.onclick = () => ask(text.value.trim());
  text.addEventListener('keydown', e => { if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') go.click(); });

  function setMsg(kind, t) { msg.className = 'modal-msg' + (kind ? ' ' + kind : ''); msg.textContent = t || ''; }
  function stopTicker() { if (ticker) { clearInterval(ticker); ticker = null; } }

  function chip(ev) {
    const li = document.createElement('li');
    li.className = 'run'; li.dataset.id = ev.id;
    li.innerHTML = `<span>${esc(TOOL_LABEL[ev.name] || ev.name)}</span><small>${esc(argSummary(ev.name, ev.input))}</small>`;
    steps.appendChild(li);
  }
  function settle(ev) {
    const li = steps.querySelector(`li[data-id="${CSS.escape(ev.id)}"]`);
    if (!li) return;
    li.className = ev.ok ? 'ok' : 'err';
    const r = ev.result;
    if (!r) return;                      // oversized result: the chip stays, no summary
    let extra = '';
    if (ev.name === 'check_live_availability') extra = r.status === 'open' ? `${(r.in_window || r.slots || []).length} open` : r.status;
    else if (ev.name === 'similar_spots') extra = `${(r.alternates || []).length} found`;
    else if (ev.name === 'create_watch') extra = r.alerts_active ? 'armed' : 'saved locally';
    else if (ev.name === 'search_spots') extra = `${r.matched ?? ''} match${r.matched === 1 ? '' : 'es'}`;
    if (extra) li.querySelector('small').textContent += ` · ${extra}`;
  }

  async function ask(message) {
    if (running) return;
    if (!message) { text.focus(); return; }
    if (!CONCIERGE_URL) {
      setMsg('err', 'The concierge service is not configured for this host. Run `uvicorn agent.app:app` locally, or open the page with ?concierge=<service url>.');
      return;
    }
    running = true; go.disabled = true; stopTicker();
    const hero = $('cgHero'); if (hero) hero.hidden = true;   // the plan takes the hero's place
    steps.innerHTML = ''; plan.hidden = true; plan.innerHTML = ''; setMsg('', '');
    status.textContent = `${modelLabel()} is reading the request…`;
    const S = { order: [], spots: {}, drops: {}, live: {}, links: {}, alternates: null, watch: null, t0: Date.now(), rounds: 0, model: '', prov: '' };
    const seen = id => { if (id && !S.order.includes(id)) S.order.push(id); };
    abort = new AbortController();
    const city = o.getCity().key;
    let token = null;
    try { token = await o.getToken(); } catch (e) { token = null; }
    try {
      const resp = await fetch(`${CONCIERGE_URL}/ask/stream`, {
        method: 'POST', signal: abort.signal,
        headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
        body: JSON.stringify({ message, city, user_token: token, model: modelParam() }),
      });
      if (!resp.ok || !resp.body) throw new Error(`service answered ${resp.status}`);
      for await (const { event, data } of sse(resp)) {
        if (event === 'tool_call') chip(data);
        else if (event === 'tool_result') {
          settle(data);
          const r = data.result;
          if (!r || !data.ok) continue;
          if (data.name === 'get_spot') { seen(r.id); S.spots[r.id] = r; }
          else if (data.name === 'next_drop') { seen(r.spot_id); S.drops[r.spot_id] = Object.assign({ at: Date.now() }, r); }
          else if (data.name === 'check_live_availability') { seen(r.spot_id); S.live[r.spot_id] = r; }
          else if (data.name === 'booking_link') { seen(r.spot_id); S.links[r.spot_id] = r.url; }
          else if (data.name === 'similar_spots') S.alternates = r;
          else if (data.name === 'create_watch') S.watch = r;
        }
        else if (event === 'usage') {
          S.rounds = data.round; S.model = pretty(data.model);
          S.prov = data.provider === 'baseten' ? ' · open weights on Baseten' : '';
          status.textContent = `${S.model}${S.prov} · round ${data.round} · ${((Date.now() - S.t0) / 1000).toFixed(1)} s`;
        }
        else if (event === 'thinking') status.textContent = `${S.model || modelLabel()} reasoned for ${data.chars} characters, now acting…`;
        else if (event === 'text') status.textContent = data.text;
        else if (event === 'note') setMsg('', data.text);
        else if (event === 'final') {
          render(data, S);
          const live = data.resy_calls_used != null ? ` · ${data.resy_calls_used} live Resy call${data.resy_calls_used === 1 ? '' : 's'}` : '';
          status.textContent = `${S.model || 'Muse'}${S.prov} · ${data.rounds} rounds · ${((Date.now() - S.t0) / 1000).toFixed(1)} s${live}`;
        }
        else if (event === 'error') setMsg('err', data.text);
      }
    } catch (err) {
      if (err.name !== 'AbortError') setMsg('err', `Could not reach the concierge at ${CONCIERGE_URL}: ${err.message || err}`);
    } finally {
      running = false; go.disabled = false; abort = null;
    }
  }

  // ---- rendering -------------------------------------------------------------

  function liveCard(live, name, sub) {
    const st = live.status;
    const cls = st === 'open' ? 'open' : st === 'none' ? 'none' : 'unknown';
    const label = { open: 'open now', none: 'nothing open', failed: 'live check failed', budget: 'not checked (cap)',
      rate_limited: 'Resy paused', unsupported: 'not checkable live' }[st] || st;
    const slots = (live.in_window && live.in_window.length ? live.in_window : live.slots) || [];
    let body = '';
    if (slots.length) {
      body = '<div class="cg-slots">' + slots.slice(0, 8).map(s =>
        `<a href="${esc(live.booking_url)}" target="_blank" rel="noopener" title="${esc(s.type)}">${esc(s.time)}</a>`).join('') + '</div>';
    } else if (live.booking_url) {
      body = `<div class="cg-slots"><a href="${esc(live.booking_url)}" target="_blank" rel="noopener">open on ${esc(live.platform || 'the platform')}</a></div>`;
    }
    return `<div class="cg-card"><b>${esc(name)}</b><span class="sub">${esc(sub || '')}</span>` +
      `<span class="cg-st ${cls}">${esc(label)}${live.cached ? ' · cached' : ''}</span>${body}</div>`;
  }

  function render(fin, S) {
    stopTicker();
    const t = tiers(fin.text);
    const primary = S.order[0];
    const pSpot = S.spots[primary] || {};
    const html = [];

    // NOW: the first choice's live check, then the alternates.
    let nowCards = '';
    if (primary && S.live[primary]) nowCards += liveCard(S.live[primary], pSpot.name || primary, `${pSpot.neighborhood || ''} · ${S.live[primary].date} · party of ${S.live[primary].party}`);
    if (S.alternates) for (const a of S.alternates.alternates || []) {
      if (a.live) nowCards += liveCard(a.live, a.name, `${a.neighborhood || ''} · ${a.cuisine || ''} · ${a.difficulty}/5`);
      else nowCards += `<div class="cg-card"><b>${esc(a.name)}</b><span class="sub">${esc(a.neighborhood || '')} · ${esc(a.cuisine || '')}</span></div>`;
    }
    if (t.NOW || nowCards) html.push(`<section class="cg-tier"><h3>Now</h3>${t.NOW ? `<p class="cg-answer">${rich(t.NOW)}</p>` : ''}${nowCards ? `<div class="cg-cards">${nowCards}</div>` : ''}</section>`);

    // DROP: countdown to the release that covers the date, plus the tips.
    const d = primary && S.drops[primary];
    let dropCard = '';
    if (d) {
      const released = !!(d.drop_for_target && d.drop_for_target.already_released);
      const target = d.drop_for_target && !released ? d.drop_for_target : d.next_drop;
      if (target) {
        const tips = (pSpot.tips || []).slice(0, 4).map(x => `<li>${esc(x)}</li>`).join('');
        const lead = released ? 'your date is already released · next ' : 'your date opens at the ';
        dropCard = `<div class="cg-card cg-drop"><b>${esc(pSpot.name || d.name || primary)}</b>` +
          `<span class="sub">${esc(lead)}${esc(d.schedule || '')} drop · ${esc(target.local_pretty || target.local || '')}</span>` +
          `<div class="cg-count" data-secs="${+target.seconds_until || 0}" data-at="${d.at}">${esc(fmtCountdown(+target.seconds_until || 0))}</div>` +
          (tips ? `<ul class="cg-tips">${tips}</ul>` : '') + '</div>';
      }
    }
    if (t.DROP || dropCard) html.push(`<section class="cg-tier"><h3>Drop</h3>${t.DROP ? `<p class="cg-answer">${rich(t.DROP)}</p>` : ''}${dropCard ? `<div class="cg-cards">${dropCard}</div>` : ''}</section>`);

    // WATCH: what was armed and where it lives.
    let watchCard = '';
    if (S.watch) {
      const w = S.watch;
      const win = w.earliest || w.latest ? ` · ${w.earliest || '…'}–${w.latest || '…'}` : '';
      watchCard = `<div class="cg-card cg-watch"><b>${esc(w.name)}</b><span class="sub">${esc(prettyDates(w.dates))}${esc(win)} · party of ${esc(w.party)}</span>` +
        (w.alerts_active
          ? `<span class="cg-st open">armed · we email you when a table opens</span>`
          : `<span class="cg-st unknown">saved on the concierge only</span><div style="margin-top:6px"><button class="cg-link" id="cgSignIn">Sign in to arm the alert</button></div>`) +
        '</div>';
    }
    if (t.WATCH || watchCard) html.push(`<section class="cg-tier"><h3>Watch</h3>${t.WATCH ? `<p class="cg-answer">${rich(t.WATCH)}</p>` : ''}${watchCard ? `<div class="cg-cards">${watchCard}</div>` : ''}</section>`);

    if (t.other) html.unshift(`<section class="cg-tier"><p class="cg-answer">${rich(t.other)}</p></section>`);
    plan.innerHTML = html.join('') || `<section class="cg-tier"><p class="cg-answer">${rich(fin.text)}</p></section>`;
    plan.hidden = false;
    const si = $('cgSignIn');
    if (si) si.onclick = () => { close(); o.onSignIn(); };
    const cd = plan.querySelector('.cg-count');
    if (cd) ticker = setInterval(() => {
      const left = +cd.dataset.secs - (Date.now() - +cd.dataset.at) / 1000;
      cd.textContent = fmtCountdown(left);
      if (left <= 0) stopTicker();
    }, 1000);
  }

  return { open, close, ask, setText: v => { text.value = v; }, setModel };
}

// ---- voice: mic -> 16 kHz mono WAV -> /ask/voice (Muse Voice Transcribe) --------
// The transcript lands in the editable box and nothing runs until the guest
// taps Ask, so a misheard restaurant name can be fixed first (SPEC section 5).

async function toWav16k(blob) {
  const AC = window.AudioContext || window.webkitAudioContext;
  const ac = new AC();
  let decoded;
  try { decoded = await ac.decodeAudioData(await blob.arrayBuffer()); }
  finally { ac.close().catch(() => {}); }
  const rate = 16000, len = Math.max(1, Math.ceil(decoded.duration * rate));
  const oc = new OfflineAudioContext(1, len, rate);     // mono destination downmixes
  const src = oc.createBufferSource();
  src.buffer = decoded; src.connect(oc.destination); src.start();
  const mono = (await oc.startRendering()).getChannelData(0);
  const out = new ArrayBuffer(44 + mono.length * 2), v = new DataView(out);
  const tag = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
  tag(0, 'RIFF'); v.setUint32(4, 36 + mono.length * 2, true); tag(8, 'WAVE');
  tag(12, 'fmt '); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, rate, true); v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
  tag(36, 'data'); v.setUint32(40, mono.length * 2, true);
  for (let i = 0, o = 44; i < mono.length; i++, o += 2) {
    const s = Math.max(-1, Math.min(1, mono[i]));
    v.setInt16(o, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
  }
  return out;
}

export function initVoice() {
  const mic = $('cgMic'), text = $('cgText'), status = $('cgStatus'), msg = $('cgMsg');
  if (!mic || !navigator.mediaDevices || !window.MediaRecorder || !CONCIERGE_URL) return null;
  mic.hidden = false;
  let rec = null, chunks = [], stream = null;
  const fail = t => { msg.className = 'modal-msg err'; msg.textContent = t; };

  async function start() {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    rec = new MediaRecorder(stream);
    chunks = [];
    rec.ondataavailable = e => { if (e.data && e.data.size) chunks.push(e.data); };
    rec.onstop = finish;
    rec.start();
    mic.classList.add('rec'); mic.title = 'Tap to stop';
    status.textContent = 'Listening. Tap the mic again when you are done.';
  }
  function stop() { if (rec && rec.state !== 'inactive') rec.stop(); }
  async function finish() {
    mic.classList.remove('rec'); mic.classList.add('busy'); mic.title = 'Hold to talk';
    if (stream) stream.getTracks().forEach(t => t.stop());
    status.textContent = 'Muse Voice is transcribing…';
    try {
      const wav = await toWav16k(new Blob(chunks, { type: rec.mimeType || 'audio/webm' }));
      const fd = new FormData();
      fd.append('audio', new Blob([wav], { type: 'audio/wav' }), 'speech.wav');
      const t0 = Date.now();
      const r = await fetch(`${CONCIERGE_URL}/ask/voice`, { method: 'POST', body: fd });
      if (!r.ok) throw new Error(`voice route answered ${r.status}`);
      const d = await r.json();
      if (d.transcript) {
        text.value = d.transcript; text.focus();
        status.textContent = `Heard it (${d.model}, ${((d.audio_ms || 0) / 1000).toFixed(1)} s of audio, ${((Date.now() - t0) / 1000).toFixed(1)} s). Fix anything, then Ask.`;
      } else status.textContent = 'Nothing was heard. Try again a little closer to the mic.';
    } catch (e) {
      status.textContent = '';
      fail(`Voice failed: ${e.message || e}`);
    } finally { mic.classList.remove('busy'); }
  }
  mic.onclick = () => {
    msg.textContent = '';
    if (rec && rec.state === 'recording') stop();
    else start().catch(e => fail(`Microphone unavailable: ${e.message || e}`));
  };
  return { start, stop };
}
