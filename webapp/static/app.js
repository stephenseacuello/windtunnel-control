/* ==========================================================================
   Wind Tunnel Control — frontend.

   No charting library. The plots are hand-drawn on canvas, for the same
   reason the CSS uses system fonts: a lab bench is very likely on an isolated
   network, and a dashboard that needs a CDN to render is no use there.

   Colour discipline, consistent with the Conveyor Twin dashboard:
     gold   #8a7038  = commanded / what we asked for
     Keaney #2277b3  = measured   / what actually happened
   Never swap those. The whole point of most of these plots is the gap
   between the two.
   ========================================================================== */

const GOLD = '#8a7038', KEANEY = '#2277b3', DIM = '#5b7288',
      LINE = '#d3e0eb', INK = '#0d2338';

/**
 * A missing element must never be able to kill the page.
 *
 * `$('#gone').onclick = fn` throws a TypeError, and in a classic
 * non-deferred script that aborts the ENTIRE file. Not hypothetical: one
 * stale id (`#cfg-reload`, a button never present in the template) halted
 * app.js at line 392, so connectStream() never ran and the dashboard showed
 * its static zeros indefinitely — while START and E-STOP, bound earlier in
 * the file, still commanded a 15 HP fan. A calm, plausible, permanently
 * stale panel is the worst failure mode a control UI has.
 *
 * So $() returns an inert node for anything missing: property writes are
 * absorbed, reads chain, calls no-op. Misses are recorded and shown as a
 * banner at load, so the failure is loud instead of fatal.
 */
const MISSING = new Set();

const NULL_NODE = new Proxy(function () {}, {
  get(_t, k) {
    if (k === 'value' || k === 'textContent' || k === 'innerHTML') return '';
    if (k === 'length') return 0;
    if (k === Symbol.toPrimitive || k === 'toString') return () => '';
    return NULL_NODE;
  },
  set() { return true; },
  apply() { return NULL_NODE; },
});

const $ = s => {
  const el = document.querySelector(s);
  if (el) return el;
  MISSING.add(s);
  return NULL_NODE;
};

/** Duplicate ids make $() silently return the wrong element. */
function auditDom() {
  const seen = new Set(), dupes = new Set();
  document.querySelectorAll('[id]').forEach(e =>
    seen.has(e.id) ? dupes.add(e.id) : seen.add(e.id));
  const msgs = [];
  if (dupes.size) msgs.push('duplicate ids (a control is reading another '
                            + 'tab\'s input): ' + [...dupes].join(', '));
  if (MISSING.size) msgs.push('missing elements: ' + [...MISSING].join(', '));
  if (!msgs.length) return;
  console.error('DOM audit:', msgs);
  const b = document.createElement('div');
  b.className = 'boot-error';
  b.textContent = 'Dashboard DOM problem — ' + msgs.join(' · ');
  document.body.prepend(b);
}
window.addEventListener('load', auditDom);
const $$ = s => [...document.querySelectorAll(s)];

/**
 * Bind a handler, tolerating a missing element.
 *
 * `$('#x').onclick = ...` throws a TypeError when #x does not exist, and in a
 * classic non-deferred script that ABORTS THE WHOLE FILE. One stale id
 * (`#cfg-reload`, which had no button) silently killed every binding after it,
 * including connectStream() — so the page rendered its static zeros forever
 * while START and E-STOP stayed live. The dashboard looked calm and connected
 * and had never received a single telemetry frame.
 *
 * Nothing in this file may bind directly again.
 */
function bind(sel, ev, fn) {
  const el = document.querySelector(sel);
  if (!el) { console.warn(`bind: no element ${sel}`); return null; }
  el.addEventListener(ev, fn);
  return el;
}

/** Duplicate ids make $() return the wrong element silently. Fail loudly. */
function assertUniqueIds() {
  const seen = new Set(), dupes = new Set();
  document.querySelectorAll('[id]').forEach(e =>
    seen.has(e.id) ? dupes.add(e.id) : seen.add(e.id));
  if (dupes.size) {
    console.error('DUPLICATE DOM IDS — $() silently returns the first:',
                  [...dupes]);
    const b = document.createElement('div');
    b.className = 'boot-error';
    b.textContent = 'Duplicate element ids: ' + [...dupes].join(', ') +
      ' — controls on one tab are reading another tab\'s inputs.';
    document.body.prepend(b);
  }
}

async function api(path, body) {
  const r = await fetch(path, body ? {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body)
  } : undefined);
  const j = await r.json();
  if (j.ok === false) throw new Error(j.error || 'request failed');
  return j;
}

/* ===================== canvas plotting primitives ====================== */

/**
 * Prepare a canvas for drawing, or return null if it is not laid out.
 *
 * Returns null for a canvas inside a hidden tab. Callers MUST no-op on null;
 * the tab-switch handler repaints once the element is visible.
 *
 * The previous version tried to be helpful and fell back to `cv.width` when
 * the element measured 0x0. `cv.width` is the BITMAP size in device pixels —
 * the same quantity the next line writes — so each call re-multiplied it by
 * devicePixelRatio. A hidden canvas grew four times in area per frame:
 * 600, 1200, 2400, 4800, 9600, 19200 px, about 1.5 GB, and the tab died.
 * twinDraw calls this every animation frame from page load, on whichever tab
 * is showing, so it killed the dashboard — E-STOP included — before anyone
 * opened the Turbine tab. Stable only at devicePixelRatio exactly 1.0.
 *
 * Never let a written value feed back into a read.
 */
function setupCanvas(cv) {
  if (!cv || typeof cv.getBoundingClientRect !== 'function') return null;
  const b = cv.getBoundingClientRect();
  if (!(b.width > 0) || !(b.height > 0)) return null;   // hidden, not laid out
  const r = window.devicePixelRatio || 1;
  const W = Math.round(b.width * r), H = Math.round(b.height * r);
  // Only resize when it actually changed: assigning cv.width reallocates the
  // backing store and clears it, every frame, for nothing.
  if (cv.width !== W || cv.height !== H) { cv.width = W; cv.height = H; }
  const g = cv.getContext('2d');
  g.setTransform(r, 0, 0, r, 0, 0);
  return { g, w: b.width, h: b.height };
}

function niceTicks(lo, hi, n = 5) {
  if (!isFinite(lo) || !isFinite(hi) || lo === hi) return [lo || 0];
  const raw = (hi - lo) / n, mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map(m => m * mag)
                .find(s => raw <= s) || 10 * mag;
  const out = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(v);
  return out;
}

/**
 * series: [{x:[], y:[], color, width, dash}]
 * Shared plotting for every chart on the page.
 */
function drawPlot(cv, series, opts = {}) {
  const surf = setupCanvas(cv);
  if (!surf) return false;              // hidden tab; repainted on tab switch
  const {g, w, h} = surf;
  const pad = {l: 46, r: 12, t: 10, b: 24};
  g.clearRect(0, 0, w, h);

  // Range over FINITE values only. One NaN — which the default manual
  // velocity source produces on every frame until somebody types a reading —
  // made y0/y1 NaN for every series, and `(y1-y0)*0.12 || 1` swallowed it
  // because NaN is falsy. Every point then projected to NaN and the Control
  // tab's primary plot rendered as a white box with axis numbers and no
  // curves at all.
  const all = series.filter(s => s.x.length && s.y.some(Number.isFinite));
  if (!all.length) {
    g.fillStyle = DIM; g.font = '12px system-ui'; g.textAlign = 'center';
    g.fillText(opts.empty || 'no data', w / 2, h / 2);
    return true;
  }

  const fin = arr => arr.filter(Number.isFinite);
  let x0 = opts.x0 ?? Math.min(...all.map(s => Math.min(...fin(s.x))));
  let x1 = opts.x1 ?? Math.max(...all.map(s => Math.max(...fin(s.x))));
  let y0 = opts.y0 ?? Math.min(...all.map(s => Math.min(...fin(s.y))));
  let y1 = opts.y1 ?? Math.max(...all.map(s => Math.max(...fin(s.y))));
  if (!Number.isFinite(x0) || !Number.isFinite(y0) ||
      !Number.isFinite(x1) || !Number.isFinite(y1)) {
    g.fillStyle = DIM; g.font = '12px system-ui'; g.textAlign = 'center';
    g.fillText(opts.empty || 'no finite data', w / 2, h / 2);
    return true;
  }
  if (x1 === x0) x1 = x0 + 1;
  const padSpan = (y1 - y0) * 0.12;
  const padY = Number.isFinite(padSpan) && padSpan > 0 ? padSpan : 1;
  y0 -= padY; y1 += padY;

  const X = v => pad.l + (v - x0) / (x1 - x0) * (w - pad.l - pad.r);
  const Y = v => h - pad.b - (v - y0) / (y1 - y0) * (h - pad.t - pad.b);

  // grid + axes
  g.strokeStyle = LINE; g.lineWidth = 1;
  g.fillStyle = DIM; g.font = '10px ui-monospace,monospace';
  g.textAlign = 'right'; g.textBaseline = 'middle';
  niceTicks(y0, y1).forEach(v => {
    const y = Y(v);
    g.beginPath(); g.moveTo(pad.l, y); g.lineTo(w - pad.r, y); g.stroke();
    g.fillText(v.toFixed(Math.abs(v) < 10 ? 1 : 0), pad.l - 6, y);
  });
  g.textAlign = 'center'; g.textBaseline = 'top';
  niceTicks(x0, x1, 6).forEach(v => {
    const x = X(v);
    g.fillText(v.toFixed(0), x, h - pad.b + 5);
  });

  // series, clipped to the plot box
  g.save();
  g.beginPath();
  g.rect(pad.l, pad.t, w - pad.l - pad.r, h - pad.t - pad.b);
  g.clip();
  series.forEach(s => {
    if (!s.x.length) return;
    g.strokeStyle = s.color; g.lineWidth = s.width || 1.6;
    g.setLineDash(s.dash || []);
    g.beginPath();
    let started = false;
    for (let i = 0; i < s.x.length; i++) {
      if (!isFinite(s.y[i])) { started = false; continue; }
      const px = X(s.x[i]), py = Y(s.y[i]);
      started ? g.lineTo(px, py) : g.moveTo(px, py);
      started = true;
    }
    g.stroke();
  });
  g.restore();
  g.setLineDash([]);
}

/* ============================== tabs ================================== */

$$('.tab').forEach(t => t.onclick = () => {
  $$('.tab').forEach(x => x.classList.remove('on'));
  $$('.page').forEach(x => x.classList.remove('on'));
  t.classList.add('on');
  $('#p-' + t.dataset.p).classList.add('on');
  const load = {params: loadParams, calib: loadCalib, logs: loadLogs,
                commission: pollJob, blades: loadBlades};
  if (load[t.dataset.p]) load[t.dataset.p]();
  // Canvases drawn while their tab was hidden are zero-sized. Redraw on the
  // frame after the tab becomes visible, once layout has settled.
  requestAnimationFrame(() => {
    if (t.dataset.p === 'blades') drawMesh($('#cv-mesh'));
    if (t.dataset.p === 'turbine') {
      if (STATE.interlock) applyTurbine(STATE);
      TWIN.last = 0;
      if (!TWIN.raf) TWIN.raf = requestAnimationFrame(twinDraw);
    }
    if (STATE.measured) drawLive();
  });
});

/* ========================= live state + stream ========================= */

let TRACE = [], STATE = {};

function lamp(id, on, cls) {
  const e = $(id); if (!e) return;
  e.classList.toggle('on', !!on);
}

function fmt(v, d = 1) {
  return (v === null || v === undefined || !isFinite(v)) ? '—' : v.toFixed(d);
}

// Started at load, not at the first frame. It was initialised to 0 and the
// watchdog bailed on `if (!LAST_FRAME) return;`, so a backend that was down
// at page load never triggered the banner — the page showed the template's
// hard-coded zeros forever and looked connected.
let LAST_FRAME = Date.now();

/**
 * A frozen panel and a live one used to look identical. If the stream drops,
 * every indicator holds its last value: an operator sees a calm, connected
 * page reporting a stopped fan that may in fact be spinning. Staleness is
 * therefore rendered, not inferred.
 */
function markStale(stale, why) {
  document.body.classList.toggle('stale', !!stale);
  // The greyout selectors have to match what is actually on screen; a class
  // on <body> that no rule reaches is decoration, not a warning.
  $$('.big, .lamp, #ilk-text, #sf-strip').forEach(
    e => e.classList.toggle('is-stale', !!stale));
  const el = $('#stale-banner');
  if (el.textContent !== undefined) {
    el.textContent = stale ? (why || 'CONNECTION LOST — readings below are '
                              + 'frozen and may not reflect the machine') : '';
    el.style.display = stale ? 'block' : 'none';
  }
}

setInterval(() => {
  if (!LAST_FRAME) return;
  const age = (Date.now() - LAST_FRAME) / 1000;
  if (age > 4) markStale(true, `NO DATA FOR ${age.toFixed(0)} s — readings are `
                             + `frozen and may not reflect the machine`);
}, 1000);

/**
 * The safety strip, visible on EVERY tab.
 *
 * The most dangerous state on this rig — a spinning rotor with no load — was
 * rendered only inside the Turbine tab. An operator on Profiles or
 * Commissioning could not see it at all. One strip, always present, carrying
 * what is running, the interlock, the load, the fan, and the age of the data.
 */
function safetyStrip(s) {
  const ik = s.interlock || {}, L = s.load || {};
  const busy = s.sweep && s.sweep.state === 'running'
    ? `SWEEP ${s.sweep.blade} ${s.sweep.i}/${s.sweep.n}`
    : (s.job && s.job.state === 'running' ? `JOB ${s.job.kind}`
       : (s.running ? 'RUNNING' : 'idle'));
  $('#sf-run').textContent = busy;
  $('#sf-fan').textContent = `${fmt(s.measured.hz, 0)} rpm`;
  $('#sf-load').textContent = L.connected
    ? (L.on ? `load ON · ${fmt(L.amps * 1000, 1)} mA` : 'LOAD OFF')
    : 'no load';
  $('#sf-ilk').textContent = ik.text || '—';
  const dot = $('#sf-dot');
  if (dot.className !== undefined) dot.className = 'ilk-dot ' + (ik.level || 'none');
  $('#sf-strip').classList.toggle('danger', ik.level === 'danger');
  const age = s.age_s;
  $('#sf-age').textContent = age == null ? '—'
    : (age > 3 ? `DATA ${age.toFixed(0)} s OLD` : `${age.toFixed(1)} s`);
  $('#sf-age').classList.toggle('bad', age != null && age > 3);
}

function applyState(s) {
  STATE = s;
  LAST_FRAME = Date.now();
  markStale(false);
  try { safetyStrip(s); } catch (e) { console.error('safety strip', e); }
  try { twinUpdate(s); } catch (e) { /* twin is optional */ }
  try { applyTurbine(s); }
  catch (e) { console.error('turbine render failed', e); }
  const b = s.status_bits || {};
  lamp('#l-link', s.connected);
  lamp('#l-remote', b.REMOTE);
  lamp('#l-run', s.running);
  lamp('#l-setpt', b.AT_SETPOINT);
  lamp('#l-alarm', b.ALARM);
  lamp('#l-fault', b.TRIPPED || s.estopped);
  lamp('#l-sim', s.dry_run);

  // The drive commands speed, not frequency. The `hz` key is legacy; the
  // value is rpm. Renaming it would break every other consumer at once, so
  // the label is corrected here and the contract left alone.
  $('#m-hz').innerHTML = fmt(s.measured.hz, 0) + '<span class="unit">rpm</span>';
  $('#m-rpm').textContent = s.measured.mph != null ? fmt(s.measured.mph, 1) + ' mph' : '—';
  $('#m-mps').innerHTML = (s.measured.mps != null ? fmt(s.measured.mps, 1) : '—')
    + '<span class="unit">m/s</span>';
  $('#c-hz').innerHTML = fmt(s.target.hz, 0) + '<span class="unit">rpm</span>';
  $('#m-amps').innerHTML = fmt(s.amps) + '<span class="unit">A</span>';

  $('#estop').textContent = s.estopped ? 'CLEAR E-STOP' : 'E-STOP';
  $('#estop').classList.toggle('latched', s.estopped);

  $('#btn-go').disabled = s.running || s.estopped || !s.connected;
  $('#btn-stop').disabled = !s.running;

  const lim = s.hz_limit;
  if (lim) {
    $('#sp-slider').max = lim;
    $('#limit-note').textContent = `soft limit ${lim} rpm`;
  }
  $('#conn-note').textContent = s.connected
    ? (s.dry_run ? 'simulated' : 'live') : 'NO LINK';
  $('#foot').innerHTML = `τ ${s.tau ? s.tau.toFixed(1) + ' s' : '—'}<br>` +
    `cal ${s.calibration ? (s.calibration.status || 'set') : 'none'}`;

  // events
  fillSession(s.session);
  applyVelocity(s);
  $('#events').innerHTML = (s.events || []).map(e =>
    `<span class="ev-${e.level}"><span class="t">${e.t}</span>${e.msg}</span>`
  ).join('');

  // profile job
  const j = s.job;
  if (j && (j.state === 'running' || j.state === 'settling')) {
    $('#pf-bar').style.display = 'block';
    $('#pf-bar').firstElementChild.style.width = (j.progress * 100) + '%';
    $('#pf-abort').style.display = '';
    $('#pf-run').disabled = true;
  } else {
    $('#pf-abort').style.display = 'none';
    if (j && j.state) $('#pf-bar').firstElementChild.style.width = '100%';
  }

  // status word bits
  if ($('#p-diag').classList.contains('on')) {
    $('#bits').innerHTML = '<table><tr><th>bit</th><th>state</th></tr>' +
      Object.entries(b).map(([k, v]) =>
        `<tr><td class="mono">${k}</td><td style="color:${v ? KEANEY : DIM}">${v ? 'SET' : '—'}</td></tr>`
      ).join('') + '</table>';
  }
}

function drawLive() {
  if (!TRACE.length) { drawPlot($('#live-plot'), [], {empty: 'waiting for data'}); return; }
  const t0 = TRACE[TRACE.length - 1].t;
  const x = TRACE.map(p => p.t - t0);
  drawPlot($('#live-plot'), [
    {x, y: TRACE.map(p => p.cmd), color: GOLD, width: 1.8},
    {x, y: TRACE.map(p => p.meas), color: KEANEY, width: 1.8},
    {x, y: TRACE.map(p => p.amps), color: DIM, width: 1, dash: [3, 3]},
    {x, y: TRACE.map(p => p.v_meas ?? NaN), color: '#1f7a52', width: 1.4},
  ], {x0: -180, x1: 2});
}

function connectStream() {
  const es = new EventSource('/api/stream');
  es.onmessage = ev => {
    const d = JSON.parse(ev.data);
    applyState(d.state);
    (d.points || []).forEach(p => {
      if (!TRACE.length || p.t > TRACE[TRACE.length - 1].t) TRACE.push(p);
    });
    if (TRACE.length > 900) TRACE = TRACE.slice(-900);
    drawLive();
  };
  es.onerror = () => {
    markStale(true, 'NO CONNECTION TO THE TUNNEL SERVER');
    $('#conn-note').textContent = 'STREAM LOST';
    es.close();
    setTimeout(connectStream, 3000);
  };
}

/* ========================== manual control ============================ */

$('#sp-slider').oninput = e => {
  $('#sp-val').value = e.target.value;
  $('#sp-echo').textContent = e.target.value + ' ' + $('#sp-units').value;
  $('#sp-val').value = e.target.value;
};
$('#sp-val').oninput = e => { $('#sp-slider').value = e.target.value; };

$('#sp-set').onclick = async () => {
  try {
    const r = await api('/api/setpoint', {
      value: parseFloat($('#sp-val').value), units: $('#sp-units').value});
    note('#ctl-note', `setpoint → ${r.target.hz} Hz` +
      (r.target.mps != null ? ` · ${r.target.mps} m/s · ${r.target.rpm} rpm` : ''), 'ok');
  } catch (e) { note('#ctl-note', e.message, 'fault'); }
};

$('#btn-go').onclick = async () => {
  const t = STATE.target || {};
  if (!confirm(`Start the fan at ${t.hz} Hz` +
      (t.mps != null ? ` (${t.mps} m/s, ${t.rpm} rpm)` : '') +
      `?\n\nConfirm the test section is clear.`)) return;
  try { await api('/api/go', {}); } catch (e) { note('#ctl-note', e.message, 'fault'); }
};
$('#btn-stop').onclick = () => api('/api/stop', {});

$('#estop').onclick = async () => {
  if (STATE.estopped) {
    if (!confirm('Clear the E-stop? The setpoint will be zeroed.')) return;
    await api('/api/clear-estop', {});
  } else {
    await api('/api/estop', {});
  }
};

function note(sel, msg, cls = '') {
  const e = $(sel);
  e.style.display = 'block';
  e.className = 'note ' + cls;
  e.textContent = msg;
}

/* ============================= profiles =============================== */

function pfSpec() {
  const k = $('#pf-kind').value;
  return {
    kind: k, units: $('#pf-units').value,
    mean: parseFloat($('#pf-mean').value),
    amp: parseFloat($('#pf-amp').value),
    length: parseFloat($('#pf-length').value),
    freq: parseFloat($('#pf-freq').value),
    sigma: parseFloat($('#pf-sigma').value),
    length_scale: parseFloat($('#pf-ls').value),
    duration: parseFloat($('#pf-dur').value),
    seed: parseInt($('#pf-seed').value),
    settle: parseFloat($('#pf-settle').value),
    feedforward: !!$('#pf-ff').value,
  };
}

$('#pf-kind').onchange = () => {
  const k = $('#pf-kind').value, turb = k === 'vonkarman' || k === 'dryden';
  $('#w-turb').style.display = turb ? '' : 'none';
  $('#w-sine').style.display = k === 'sine' ? '' : 'none';
  $('#w-amp').style.display = turb ? 'none' : '';
  $('#w-len').style.display = turb ? 'none' : '';
};

$('#pf-preview').onclick = async () => {
  try {
    const r = await api('/api/profile/preview', pfSpec());
    $('#pf-desc').textContent = r.desc;
    const series = [{x: r.t, y: r.u, color: GOLD, width: 1.8}];
    if (r.predicted) {
      // With feedforward the commanded waveform looks alarming — it has to
      // overshoot to make the flow follow. The Keaney trace is the one that
      // matters: it is the gust the model will actually see.
      series.push({x: r.t, y: r.predicted, color: KEANEY, width: 1.6});
    }
    drawPlot($('#pf-plot'), series);
    $('#pf-run').disabled = false;
    $('#pf-check').disabled = false;

    const d = r.diagnostics || {};
    let cls = 'ok', lines = [];
    if (d.amplitude_retained != null) {
      const pct = Math.round(d.amplitude_retained * 100);
      cls = pct >= 85 ? 'ok' : pct >= 70 ? '' : pct >= 40 ? 'warn' : 'fault';
      lines.push(`Predicted amplitude retained: ${pct}% — ` + (
        pct >= 85 ? 'the tunnel will follow this closely' :
        pct >= 70 ? 'acceptable, mild rounding of the peak' :
        pct >= 40 ? 'MARGINAL — noticeably smaller and smoother than drawn' :
                    'NOT REALIZABLE — you will get a ripple, not a gust'));
    } else {
      cls = 'warn';
      lines.push('No τ recorded — run characterize so profiles can be checked ' +
                 'against the tunnel bandwidth.');
    }
    if (d.slew_ok === false)
      lines.push(`Slew: profile demands ${d.max_slew.toFixed(1)} Hz/s, the ` +
                 `drive ramp allows less. It will be clipped.`);
    const f = d.feedforward;
    if (f) {
      // Trust the RMS number, not the amplitude number: below ~6 s the
      // compensator restores amplitude while distorting shape.
      if (f.rms_improvement < 1.0) {
        cls = 'fault';
        lines.push(`FEEDFORWARD IS MAKING THIS WORSE — RMS tracking error ` +
          `${(f.rms_error_uncompensated * 100).toFixed(0)}% → ` +
          `${(f.rms_error_compensated * 100).toFixed(0)}%. Amplitude looks ` +
          `recovered but the shape is more distorted. Lengthen the gust or ` +
          `raise the slew limit.`);
      } else {
        lines.push(`Feedforward: RMS error ` +
          `${(f.rms_error_uncompensated * 100).toFixed(0)}% → ` +
          `${(f.rms_error_compensated * 100).toFixed(0)}% ` +
          `(${f.rms_improvement.toFixed(1)}× better). Command swings ` +
          `${f.overshoot_ratio.toFixed(1)}× the desired amplitude.`);
      }
      if (f.clipped_slew) lines.push('Slew-limited — shorten par 2202/2203 for the full benefit.');
      if (f.clipped_range) lines.push('Clipped at the operating limits — lower the mean or amplitude.');
    }
    if (d.asymmetry_rms > 0.02)
      lines.push(`The slower down-ramp costs ${d.recovery_penalty_s.toFixed(1)} s ` +
                 `of extra recovery — budget it between repeats.`);
    lines.push(`Range ${r.hz_min.toFixed(1)}–${r.hz_max.toFixed(1)} Hz over ` +
               `${r.duration.toFixed(0)} s.`);
    $('#pf-diag').innerHTML = `<div class="note ${cls}">` +
      lines.join('<br>') + '</div>';
  } catch (e) {
    $('#pf-diag').innerHTML = `<div class="note fault">${e.message}</div>`;
    $('#pf-run').disabled = true;
  }
};

function renderChecks(sel, checks, ok) {
  $(sel).innerHTML = checks.map(c =>
    `<div class="chk"><span class="tag ${c.status}">${c.status.toUpperCase()}</span>
     <div class="body"><div class="nm">${c.name}</div>
     <div class="dt">${c.detail}</div></div></div>`).join('') +
    (ok ? '' : '<div class="note fault">A check failed — fix it or use ' +
      'Run anyway, which skips pre-flight entirely.</div>');
}

$('#pf-check').onclick = async () => {
  try {
    const r = await api('/api/preflight', {spec: pfSpec()});
    renderChecks('#pf-diag', r.checks, r.ok);
  } catch (e) { $('#pf-diag').innerHTML = `<div class="note fault">${e.message}</div>`; }
};

bind('#cfg-reload', 'click', async () => {
  const r = await api('/api/config/reload', {});
  alert(r.summary);
});

$('#pf-run').onclick = async () => {
  const s = pfSpec();
  if (!confirm(`Run ${s.kind}?\n\nThe fan will settle for ${s.settle}s then ` +
               `play the profile.\n\nConfirm the test section is clear and ` +
               `nobody is near the tunnel.`)) return;
  try { await api('/api/profile/run', s); } catch (e) {
    // Pre-flight blocks rather than warns, so offer the override explicitly
    // instead of leaving the operator stuck with an error message.
    if (/pre-flight/.test(e.message) &&
        confirm(`${e.message}\n\nRun anyway, skipping pre-flight?`)) {
      try { await api('/api/profile/run', {...s, force: true}); return; }
      catch (e2) { $('#pf-diag').innerHTML = `<div class="note fault">${e2.message}</div>`; return; }
    }
    $('#pf-diag').innerHTML = `<div class="note fault">${e.message}</div>`;
  }
};
$('#pf-abort').onclick = () => api('/api/profile/abort', {});

/* ============================ parameters ============================== */

async function loadParams() {
  if (!PCAP) await loadParamCapability();
  const r = await api('/api/params');
  $('#pr-groups').innerHTML = r.groups.map(g => `
    <h3 style="margin:16px 0 6px">${g.name}</h3>
    <table><tr><th>Par</th><th>Name</th><th>Value</th><th>Note</th><th></th></tr>
    ${g.rows.map(row => `<tr>
      <td class="mono">${row.num}</td>
      <td>${row.name}</td>
      <td class="num">${row.readonly
        ? `<span class="mono">${row.value ?? '—'}</span>`
        : `<input class="num pv" data-p="${row.num}" value="${row.value ?? ''}">`}</td>
      <td class="sm dim">${row.note}</td>
      <td>${row.readonly || !(PCAP && PCAP.write) ? '' :
        `<button class="sm pw" data-p="${row.num}">Write</button>`}</td>
    </tr>`).join('')}</table>`).join('');

  $$('.pw').forEach(b => b.onclick = async () => {
    const num = b.dataset.p;
    const val = $(`.pv[data-p="${num}"]`).value;
    if (!confirm(`Write ${val} to parameter ${num}?\n\n` +
                 `This is persistent — the same as editing on the keypad. ` +
                 `There is no undo.`)) return;
    try {
      const r = await api('/api/params/write', {param: num, value: val});
      alert(`par ${num}: ${r.result.before} → ${r.result.after}`);
      loadParams();
    } catch (e) { alert(e.message); }
  });
}
$('#pr-refresh').onclick = loadParams;

/* ========================== velocity source =========================== */

$('#v-submit').onclick = async () => {
  const v = parseFloat($('#v-manual').value);
  if (!isFinite(v)) { alert('Enter a reading.'); return; }
  try { await api('/api/velocity/manual', {value: v}); }
  catch (e) { $('#v-out').innerHTML = `<div class="note fault">${e.message}</div>`; }
};

$('#v-hold').onclick = async () => {
  const t = parseFloat($('#v-target').value);
  if (!isFinite(t)) { alert('Enter a target wind speed.'); return; }
  if (!confirm(`Hold ${t} m/s closed-loop for ${$('#v-dur').value}s?\n\n` +
    `The loop starts from the calibration and trims against the measured ` +
    `wind speed.\n\nConfirm the test section is clear.`)) return;
  try {
    await api('/api/velocity/hold', {target: t, duration: parseFloat($('#v-dur').value)});
    pollJob();
    $('#v-out').innerHTML = '<div class="note">holding — progress on the ' +
      'Commissioning tab</div>';
  } catch (e) { $('#v-out').innerHTML = `<div class="note fault">${e.message}</div>`; }
};

function applyVelocity(s) {
  const vs = s.velocity_source;
  $('#vs-name').textContent = vs ? `${vs.name}${vs.healthy ? '' : ' · STALE'}` : 'none';
  $('#v-manual-row').style.display = (vs && vs.name === 'manual') ? '' : 'none';

  const m = vs && vs.value != null ? vs.value : null;
  const d = s.measured ? s.measured.mps : null;
  $('#v-meas').innerHTML = (m != null ? m.toFixed(2) : '—') + '<span class="unit">m/s</span>';
  $('#v-derived').innerHTML = (d != null ? d.toFixed(2) : '—') + '<span class="unit">m/s</span>';

  // The gap between measured and derived IS the calibration error today.
  // Surfacing it is the entire point of having a live source.
  if (m != null && d != null && d > 0.5) {
    const err = (m - d) / d;
    const cls = Math.abs(err) < 0.05 ? 'ok' : Math.abs(err) < 0.15 ? 'warn' : 'fault';
    $('#v-delta').innerHTML = `<div class="note ${cls}" style="margin:0">` +
      `Measured is <b>${(err * 100).toFixed(1)}%</b> ` +
      `${err > 0 ? 'above' : 'below'} what the calibration predicts.` +
      (Math.abs(err) > 0.05
        ? ' If that persists across sessions it is a calibration error worth' +
          ' folding in; if it moves day to day it is air density.'
        : ' The calibration is holding.') + '</div>';
  } else {
    $('#v-delta').innerHTML = vs && !vs.healthy
      ? '<div class="note warn" style="margin:0">No fresh reading. A closed ' +
        'loop will refuse to run rather than integrate against a stale value.</div>'
      : '';
  }
}

/* ============================= session ================================ */

$('#se-save').onclick = async () => {
  const r = await api('/api/session', {
    operator: $('#se-op').value, configuration: $('#se-cfg').value,
    project: $('#se-proj').value, notes: $('#se-notes').value});
  $('#sess-when').textContent = 'set ' + (r.session.updated || '').slice(11, 16);
};

function fillSession(s) {
  if (!s || $('#se-op').dataset.filled) return;
  $('#se-op').value = s.operator || '';
  $('#se-cfg').value = s.configuration || '';
  $('#se-proj').value = s.project || '';
  $('#se-notes').value = s.notes || '';
  $('#se-op').dataset.filled = '1';
  $('#sess-when').textContent = 'opened ' + (s.opened || '').replace('T', ' ');
}

/* ============================== sweep ================================= */

function sweepEst() {
  const n = Math.floor((parseFloat($('#sw-stop').value) -
    parseFloat($('#sw-start').value)) / parseFloat($('#pfsw-step').value)) + 1;
  const mins = n * (parseFloat($('#sw-settle').value) +
    parseFloat($('#pfsw-dwell').value)) / 60;
  $('#sw-est').textContent = `${n} points · ~${mins.toFixed(0)} min`;
}
['sw-start', 'sw-stop', 'pfsw-step', 'sw-settle', 'pfsw-dwell']
  .forEach(id => bind('#' + id, 'input', sweepEst));
sweepEst();

bind('#sw-run', 'click', async () => {
  const u = $('#sw-units').value;
  if (!confirm(`Sweep ${$('#sw-start').value} → ${$('#sw-stop').value} ${u} ` +
      `in steps of ${$('#pfsw-step').value}?\n\n${$('#sw-est').textContent}` +
      `\n\nConfirm the test section is clear.`)) return;
  try {
    await api('/api/sweep', {
      start: parseFloat($('#sw-start').value),
      stop: parseFloat($('#sw-stop').value),
      step: parseFloat($('#pfsw-step').value),
      settle: parseFloat($('#sw-settle').value),
      dwell: parseFloat($('#pfsw-dwell').value), units: u});
    pollJob();
    $('#sw-out').innerHTML = '<div class="note">running — progress on the ' +
      'Commissioning tab</div>';
  } catch (e) { $('#sw-out').innerHTML = `<div class="note fault">${e.message}</div>`; }
});

/* ========================== commissioning ============================= */
/*
   These move the fan and take minutes. Each is a job: one at a time, progress
   from the server, output captured so the UI can show what the routine
   printed rather than a spinner and a shrug.
*/

let jobTimer = null;

async function pollJob() {
  clearInterval(jobTimer);
  const tick = async () => {
    const r = await api('/api/job');
    const j = r.job;
    if (!j) { $('#jb-kind').textContent = 'idle'; return; }
    $('#jb-kind').textContent = j.kind || j.desc || '—';
    $('#jb-state').textContent = j.state + (j.error ? ' — ' + j.error : '');
    $('#jb-bar').firstElementChild.style.width = ((j.progress || 0) * 100) + '%';
    if (j.output) $('#jb-out').textContent = j.output;
    if (j.state !== 'running' && j.state !== 'settling') {
      clearInterval(jobTimer);
      if (j.result) renderJobResult(j);
    }
  };
  await tick();
  jobTimer = setInterval(tick, 1000);
}

function renderJobResult(j) {
  const r = j.result || {};
  const k = (j.kind || '');

  if (k.startsWith('characterize')) {
    const cls = r.tau_s ? 'ok' : 'warn';
    $('#ch-out').innerHTML = `<div class="note ${cls}">
      <b>τ = ${r.tau_s ? r.tau_s.toFixed(2) : '—'} s</b> ·
      corner ${r.f_corner_hz ? r.f_corner_hz.toFixed(3) : '—'} Hz ·
      10–90% rise ${r.rise_10_90_s ? r.rise_10_90_s.toFixed(2) : '—'} s<br>
      saved to the config as <code>${r.saved_as || '—'}</code>, so every
      profile from now on is checked against it automatically.<br>
      <span class="dim">Gusts slower than about
      ${r.tau_s ? (1 / (3 * r.tau_s)).toFixed(2) : '—'} Hz will reproduce
      faithfully; faster ones get attenuated.</span></div>`;
  }

  if (k === 'freqresp' && r.points) {
    const inband = r.points.filter(p => p.gain >= 0.707);
    const bw = inband.length ? Math.max(...inband.map(p => p.f_hz)) : null;
    $('#fr-out').innerHTML = `<div class="note ${bw ? 'ok' : 'warn'}">
      ${bw ? `<b>−3 dB bandwidth ≈ ${bw.toFixed(3)} Hz</b>` : 'no point reached −3 dB'}
      </div><table style="margin-top:9px"><tr><th>Hz</th><th>gain</th>
      <th>dB</th><th>phase</th></tr>` + r.points.map(p =>
      `<tr><td class="num">${p.f_hz}</td><td class="num">${p.gain.toFixed(3)}</td>
       <td class="num">${p.gain_db.toFixed(1)}</td>
       <td class="num">${p.phase_deg.toFixed(0)}°</td></tr>`).join('') + '</table>';
  }

  if (k === 'sweep' && r.points) {
    // std at each point is the tell: a wide spread means it had not settled.
    const wide = r.points.filter(p => p.std_hz > 0.25).length;
    $('#sw-out').innerHTML = `<div class="note ${wide ? 'warn' : 'ok'}">
      ${r.points.length} points complete.
      ${wide ? `<b>${wide} point(s) had a wide spread</b> — those may not have
        settled. Lengthen settle and re-run those.` : 'All points settled cleanly.'}
      <br><span class="dim">${r.points_csv || ''}</span></div>
      <table style="margin-top:9px"><tr><th>Set</th><th>Mean Hz</th>
      <th>σ</th><th>m/s</th><th>A</th></tr>` + r.points.map(p =>
      `<tr><td class="num">${p.setpoint_user}</td>
       <td class="num">${p.mean_hz.toFixed(2)}</td>
       <td class="num" style="color:${p.std_hz > 0.25 ? 'var(--warn)' : 'inherit'}">${p.std_hz.toFixed(3)}</td>
       <td class="num">${p.mean_mps ?? '—'}</td>
       <td class="num">${p.mean_a.toFixed(1)}</td></tr>`).join('') + '</table>';
  }

  if (k.startsWith('hold')) {
    const head = `Held <b>${r.mean_measured.toFixed(2)} ± ` +
      `${r.std_measured.toFixed(2)}</b> against a target of ` +
      `${r.target.toFixed(2)}.<br>Steady correction ` +
      `<b>${r.final_correction_hz >= 0 ? '+' : ''}${r.final_correction_hz.toFixed(2)} Hz</b>` +
      ` on a ${r.open_loop_hz.toFixed(2)} Hz open-loop guess.<br>`;
    const gains = `<span class="dim">gains kp ${r.gains.kp} ki ${r.gains.ki}, ` +
      `period ${r.gains.period}s</span>`;

    if (!r.converged) {
      // An unconverged correction is a snapshot of an approach, not a
      // measurement of the plant. Showing it as a calibration error would
      // bake a wrong number into somebody's notes.
      $('#v-out').innerHTML = `<div class="note warn">${head}
        <b>NOT CONVERGED</b> — still ${(r.relative_error * 100).toFixed(1)}%
        from target, correction drifting ${r.correction_drift_hz.toFixed(2)} Hz
        over the run. The correction is <b>not</b> a calibration error yet.
        Run longer or raise ki.<br>${gains}</div>`;
    } else {
      const e = r.implied_calibration_error;
      $('#v-out').innerHTML = `<div class="note ${Math.abs(e) < 0.05 ? 'ok' : 'warn'}">
        ${head}The calibration is off by <b>${(e * 100).toFixed(1)}%</b> under
        today's conditions. Persisting across sessions means a calibration
        error worth folding in; moving day to day means air density.<br>
        ${gains}</div>`;
    }
  }

  if (k.startsWith('verify')) {
    $('#vf-out').innerHTML = `<div class="note">
      Held ${r.hz} Hz, drive reported ${r.measured_hz} Hz.
      Predicted <b class="k-cmd">${r.predicted ? r.predicted.toFixed(2) : '—'}
      ${r.units || ''}</b>.<br>
      Enter what the anemometer actually read, then Apply.</div>`;
  }
}

$('#vf-run').onclick = async () => {
  if (!confirm('Hold the fan at this frequency while you read the anemometer?\n\n' +
               'Confirm the test section is clear.')) return;
  try {
    await api('/api/commission/verify', {
      hz: parseFloat($('#vf-hz').value),
      settle: parseFloat($('#vf-settle').value),
      hold: parseFloat($('#vf-hold').value)});
    pollJob();
  } catch (e) { $('#vf-out').innerHTML = `<div class="note fault">${e.message}</div>`; }
};

$('#vf-apply').onclick = async () => {
  const m = parseFloat($('#vf-meas').value);
  if (!isFinite(m)) { alert('Enter the measured wind speed first.'); return; }
  try {
    const r = await api('/api/commission/verify/apply', {
      hz: parseFloat($('#vf-hz').value), measured: m});
    const q = r.result;
    const near = Math.abs(q.ratio - 1) < 0.05;
    $('#vf-out').innerHTML = `<div class="note ${near ? 'ok' : 'warn'}">
      predicted ${q.predicted.toFixed(2)} · measured ${q.measured.toFixed(2)} ·
      ratio ${q.ratio.toFixed(4)}<br><b>${q.verdict}</b></div>`;
    loadCalib();
  } catch (e) { $('#vf-out').innerHTML = `<div class="note fault">${e.message}</div>`; }
};

async function runChar(sign) {
  const step = Math.abs(parseFloat($('#ch-step').value)) * sign;
  if (!confirm(`Run a step response: ${$('#ch-base').value} Hz → ` +
               `${parseFloat($('#ch-base').value) + step} Hz?\n\n` +
               `Takes about ${parseFloat($('#ch-settle').value) +
                 parseFloat($('#ch-record').value)} s with the fan running.`)) return;
  try {
    await api('/api/commission/characterize', {
      base: parseFloat($('#ch-base').value), step,
      settle: parseFloat($('#ch-settle').value),
      record: parseFloat($('#ch-record').value)});
    pollJob();
  } catch (e) { $('#ch-out').innerHTML = `<div class="note fault">${e.message}</div>`; }
}
$('#ch-up').onclick = () => runChar(+1);
$('#ch-down').onclick = () => runChar(-1);

$('#fr-run').onclick = async () => {
  const freqs = $('#fr-freqs').value;
  const cycles = parseFloat($('#fr-cycles').value);
  const est = freqs.split(',').reduce((a, f) => a + cycles / parseFloat(f), 0);
  if (!confirm(`Frequency sweep at ${freqs} Hz?\n\n` +
               `Roughly ${(est / 60).toFixed(0)} minutes with the fan running.`)) return;
  try {
    await api('/api/commission/freqresp', {
      base: parseFloat($('#fr-base').value),
      amp: parseFloat($('#fr-amp').value),
      frequencies: freqs, cycles});
    pollJob();
  } catch (e) { $('#fr-out').innerHTML = `<div class="note fault">${e.message}</div>`; }
};

$('#jb-abort').onclick = () => api('/api/profile/abort', {});

/* =========================== calibration ============================== */

async function loadCalib() {
  const r = await api('/api/calibration');
  $('#cal-status').textContent = r.status || '';
  if (!r.calibration) {
    $('#cal-body').innerHTML = '<div class="note warn">No calibration loaded.</div>';
    return;
  }
  const c = r.calibration;
  $('#cal-body').innerHTML = `
    <div class="mono" style="font-size:14px">v = ${c.coeffs[0].toFixed(4)}·Hz
      ${c.coeffs[1] >= 0 ? '+' : ''}${c.coeffs[1].toFixed(3)} ${c.units}</div>
    <div class="sm dim" style="margin-top:8px">
      R² ${c.r2 ? c.r2.toFixed(5) : '—'} ·
      ${c.rpm_per_hz ? c.rpm_per_hz.toFixed(2) + ' rpm/Hz' : 'no drive map'} ·
      domain ${c.domain}</div>
    <div class="note sm">${c.notes || ''}</div>`;
  $('#cal-table').innerHTML = '<table><tr><th>Hz</th><th>RPM</th><th>m/s</th><th>mph</th></tr>' +
    r.table.map(t => `<tr><td class="num">${t.hz}</td><td class="num">${t.rpm ?? '—'}</td>
      <td class="num">${t.mps}</td><td class="num">${t.mph}</td></tr>`).join('') + '</table>';

  const amb = STATE.ambient;
  $('#amb-body').innerHTML = amb ? `<div class="sm mono" style="margin-top:8px">
    ρ = ${amb.density} kg/m³ · ${(amb.density_ratio * 100).toFixed(1)}% of ISA</div>` : '';
}

$('#amb-save').onclick = async () => {
  const r = await api('/api/ambient', {
    temperature: parseFloat($('#amb-t').value),
    pressure: parseFloat($('#amb-p').value)});
  $('#amb-body').innerHTML = `<div class="note ok sm">ρ = ${r.ambient.density}
    kg/m³ · ${(r.ambient.density_ratio * 100).toFixed(1)}% of ISA</div>`;
};

/* =========================== diagnostics ============================== */

$('#st-run').onclick = async () => {
  $('#st-body').textContent = 'running…';
  const r = await api('/api/selftest');
  $('#st-body').innerHTML = r.checks.map(c => `
    <div class="chk"><span class="tag ${c.status}">${c.status.toUpperCase()}</span>
    <div class="body"><div class="nm">${c.name}</div>
    <div class="dt">${c.detail}</div></div></div>`).join('');
};

/* ============================== logs ================================== */

async function loadLogs() {
  const r = await api('/api/logs');
  if (!r.logs.length) { $('#lg-list').textContent = 'No runs yet.'; return; }
  $('#lg-list').innerHTML = '<table><tr><th>Run</th><th>When</th><th>Size</th></tr>' +
    r.logs.map(l => `<tr style="cursor:pointer" data-n="${l.name}">
      <td class="mono sm">${l.name}</td><td class="sm dim">${l.modified}</td>
      <td class="num sm">${(l.size / 1024).toFixed(0)}k</td></tr>`).join('') + '</table>';
  $$('#lg-list tr[data-n]').forEach(tr => tr.onclick = () => openLog(tr.dataset.n));
}

let CURRENT_LOG = null;
$('#lg-export').onclick = () => {
  if (CURRENT_LOG) window.location = `/api/logs/${encodeURIComponent(CURRENT_LOG)}/export`;
};

async function openLog(name) {
  $('#lg-name').textContent = name;
  CURRENT_LOG = name;
  $('#lg-export').disabled = false;
  const r = await api(`/api/logs/${encodeURIComponent(name)}/analyze`);
  drawPlot($('#lg-plot'), [
    {x: r.t, y: r.cmd, color: GOLD, width: 1.8},
    {x: r.t, y: r.meas, color: KEANEY, width: 1.6},
  ]);
  const q = r.result;
  let lines = [
    `Commanded ${q.cmd_peak_to_peak.toFixed(2)} Hz p-p → measured ` +
    `${q.meas_peak_to_peak.toFixed(2)} Hz (${(q.amplitude_retained * 100).toFixed(0)}% retained)`,
    `Fitted τ = ${q.tau_s ? q.tau_s.toFixed(2) : '—'} s (R² ${q.fit_r2.toFixed(3)})`,
    `Peak current ${q.peak_current_a.toFixed(1)} A`];
  let cls = '';
  if (q.unsettled_start) {
    cls = 'warn';
    lines.unshift(`RUN STARTED UNSETTLED — the flow was ${q.start_gap_hz.toFixed(1)} Hz ` +
      `from the commanded baseline at t=0. Settle time was too short; ` +
      `${q.trimmed_samples} samples trimmed. Use at least 4τ.`);
  }
  if (q.complete === false) { cls = 'fault'; lines.unshift('INCOMPLETE RUN'); }
  $('#lg-body').innerHTML = `<div class="note ${cls}">${lines.join('<br>')}</div>`;
}
$('#lg-refresh').onclick = loadLogs;

/* ============================== boot ================================== */

window.addEventListener('resize', () => { drawLive(); });
connectStream();
fetch('/api/trace?n=900').then(r => r.json()).then(d => {
  TRACE = d.points || []; drawLive();
});


/* ══════════════════════════════════════════════════════════════════════
   TURBINE — load state, the interlock, and the blade sweep
   ══════════════════════════════════════════════════════════════════════ */

function applyTurbine(s) {
  const L = s.load || {};
  const ik = s.interlock || {};

  const dot = $('#ilk-dot'), card = $('#ilk-card');
  if (dot) {
    dot.className = 'ilk-dot ' + (ik.level || 'none');
    $('#ilk-text').textContent = ik.text || '—';
    card.classList.toggle('danger', ik.level === 'danger');
  }

  if (!L.connected) {
    $('#load-ident').textContent = L.error ? ('unavailable — ' + L.error) : '—';
    return;
  }
  $('#load-ident').textContent = (L.identity || 'connected') +
    (L.on ? ' · LOAD ON' : ' · load off');
  $('#ld-v').innerHTML = fmt(L.volts, 3) + '<span class="unit">V</span>';
  $('#ld-i').innerHTML = fmt(L.amps * 1000, 1) + '<span class="unit">mA</span>';
  $('#ld-w').innerHTML = fmt(L.watts, 4) + '<span class="unit">W</span>';
  $('#ld-d').innerHTML = fmt(L.demand * 1000, 1) + '<span class="unit">mA</span>';
  $('#ld-off').disabled = !ik.unload_ok;
  $('#ld-note').textContent = ik.unload_ok ? '' :
    'load off is refused while the fan turns';

  const sw = s.sweep;
  if (!sw) return;
  $('#sw-state').textContent =
    sw.state === 'running' ? `${sw.i}/${sw.n} — ${sw.current_rpm} rpm`
                           : (sw.message || sw.state);
  $('#sw-bar').style.width = (100 * (sw.i || 0) / (sw.n || 1)) + '%';
  $('#sw-go').disabled = sw.state === 'running';
  $('#sw-abort').disabled = sw.state !== 'running';

  // Live ramp. Cleared when the wind speed changes: the old code left the
  // PREVIOUS point's curve on screen through the whole settle of the next
  // one, labelled with the new rpm.
  const ramp = sw.ramp || [];
  // RAMP_RPM must latch only when the clear actually PAINTED. drawPlot now
  // returns early on a hidden canvas, so latching first meant the one-shot
  // clear was swallowed and the previous wind speed's curve stayed on screen
  // labelled with the new rpm — exactly the round-1 bug, reintroduced by the
  // round-2 null guard.
  if (sw.current_rpm !== RAMP_RPM) {
    const painted = drawPlot($('#cv-ramp'), [],
                             { empty: `settling at ${sw.current_rpm} rpm…` });
    if (painted !== false) RAMP_RPM = sw.current_rpm;
  }
  $('#sw-ramp-lbl').textContent = sw.current_rpm
    ? `P and V vs load current at ${sw.current_rpm} rpm` : 'idle';
  if (ramp.length > 1) {
    drawPlot($('#cv-ramp'), [
      { color: '#0b6fb4', width: 2,
        x: ramp.map(r => r.a * 1000), y: ramp.map(r => r.w) },
      { color: '#b0b7bd', width: 1, dash: [3, 3],
        x: ramp.map(r => r.a * 1000), y: ramp.map(r => r.v) }
    ], { empty: 'waiting for the ramp' });
  }

  // the blade curve, accumulating
  const pts = sw.points || [];
  if (pts.length) {
    drawPlot($('#cv-curve'), [{
      color: '#00a3a1', width: 2.2,
      x: pts.map(p => p.mps), y: pts.map(p => p.p_w)
    }], { y0: 0, empty: 'no points yet' });
    $('#sw-tbl').querySelector('tbody').innerHTML = pts.map(p =>
      `<tr class="${p.clean ? '' : 'warn'}"><td>${p.rpm}</td><td>${p.mps}</td>` +
      `<td class="mono">${p.p_w.toFixed(4)}</td>` +
      `<td class="mono">${p.i_a.toFixed(3)}</td>` +
      `<td>${p.limited_by}</td></tr>`).join('');
  }
}

/**
 * api() REJECTS on {ok:false} rather than returning it. Every handler below
 * therefore has to catch, or a refused command — an interlock veto, a missing
 * blade name — becomes an unhandled rejection and the button silently does
 * nothing. Silence is the worst possible response to a safety refusal.
 */
/**
 * Refusals go to a node the telemetry loop never touches.
 *
 * `act()` wrote into #ld-note, which applyTurbine rewrites on every frame —
 * so a safety refusal was erased ~250 ms after it appeared. The operator saw
 * a flicker and concluded the button did nothing, which is the same failure
 * the round-1 fix was meant to eliminate.
 */
function refusal(msg) {
  const el = $('#refusal');
  if (el.textContent === undefined) return;
  el.textContent = msg || '';
  el.style.display = msg ? 'block' : 'none';
  clearTimeout(refusal._t);
  if (msg) refusal._t = setTimeout(() => {
    el.textContent = ''; el.style.display = 'none';
  }, 15000);
}

async function act(sel, path, body, okMsg) {
  try {
    const r = await api(path, body || {});
    note(sel, okMsg || '', 'ok');
    refusal('');
    return r;
  } catch (e) {
    refusal('REFUSED — ' + (e.message || String(e)));
    note(sel, 'refused', 'bad');
    return null;
  }
}

function wireTurbine() {
  const on = (sel, fn) => { const el = $(sel); if (el) el.onclick = fn; };

  on('#ld-apply', () => act('#ld-note', '/api/load/amps',
      { amps: parseFloat($('#ld-set').value) }, 'demand set'));
  on('#ld-on', () => act('#ld-note', '/api/load/on', {}, 'load ON'));
  on('#ld-off', () => act('#ld-note', '/api/load/off', {}, 'load OFF'));

  on('#sw-go', () => {
    const blade = $('#sw-blade').value.trim();
    if (!blade) { note('#sw-note', 'a blade name is required', 'bad'); return; }
    return act('#sw-note', '/api/sweep/start', {
      blade, notes: $('#sw-notes').value,
      start_rpm: +$('#sw-from').value, stop_rpm: +$('#sw-to').value,
      rpm_step: +$('#sw-step').value, step_amps: +$('#sw-ma').value / 1000,
      dwell: +$('#sw-dwell').value }, 'sweep running');
  });
  on('#sw-abort', () => act('#sw-note', '/api/sweep/abort', {}, 'abort requested'));
}

document.addEventListener('DOMContentLoaded', wireTurbine);


/* ══════════════════════════════════════════════════════════════════════
   BLADES — geometry beside the curve it produced

   A dependency-free STL viewer. The app vendors no libraries and has no
   build step, and an STL is only a triangle soup, so a small software
   rasteriser is a fairer trade than pulling in a 3D engine to draw one
   rotor. Flat shading, painter's algorithm, drag to rotate.

   STEP is deliberately not supported: it is a boundary representation and
   needs real CAD tessellation to become triangles at all.
   ══════════════════════════════════════════════════════════════════════ */

const MAX_TRIS = 60000;      // display cap; the file on disk is untouched

function parseSTL(buf) {
  const dv = new DataView(buf);
  // ASCII files begin "solid", but so do some binary ones — the length check
  // is what actually decides. 84 + 50*n is exact for binary.
  const n = buf.byteLength >= 84 ? dv.getUint32(80, true) : 0;
  if (buf.byteLength === 84 + n * 50) return parseSTLBinary(dv, n);
  return parseSTLAscii(new TextDecoder().decode(buf));
}

function parseSTLBinary(dv, n) {
  const stride = Math.max(1, Math.ceil(n / MAX_TRIS));
  const tris = [];
  for (let i = 0; i < n; i += stride) {
    const o = 84 + i * 50;
    const v = [];
    for (let k = 0; k < 3; k++) {
      const b = o + 12 + k * 12;
      v.push([dv.getFloat32(b, true), dv.getFloat32(b + 4, true),
              dv.getFloat32(b + 8, true)]);
    }
    tris.push(v);
  }
  return { tris, total: n, shown: tris.length };
}

function parseSTLAscii(txt) {
  const nums = [], re = /vertex\s+(\S+)\s+(\S+)\s+(\S+)/g;
  let m;
  while ((m = re.exec(txt))) nums.push([+m[1], +m[2], +m[3]]);
  const total = Math.floor(nums.length / 3);
  const stride = Math.max(1, Math.ceil(total / MAX_TRIS));
  const tris = [];
  for (let i = 0; i < total; i += stride) tris.push(nums.slice(i * 3, i * 3 + 3));
  return { tris, total, shown: tris.length };
}

let RAMP_RPM = null;
let TWIN_RADIUS = null;
let MESH = null, ROT = { x: -1.05, y: 0.6 }, DRAG = null;

function drawMesh(cv) {
  const surf = setupCanvas(cv);
  if (!surf) return;
  const { g, w, h } = surf;
  g.clearRect(0, 0, w, h);
  if (!MESH || !MESH.tris.length) {
    g.fillStyle = DIM; g.font = '13px system-ui'; g.textAlign = 'center';
    g.fillText('no geometry — drop an STL in blades/', w / 2, h / 2);
    return;
  }
  // centre and scale to fit, once
  if (!MESH.c) {
    let lo = [1e9, 1e9, 1e9], hi = [-1e9, -1e9, -1e9];
    for (const t of MESH.tris) for (const p of t) for (let k = 0; k < 3; k++) {
      if (p[k] < lo[k]) lo[k] = p[k];
      if (p[k] > hi[k]) hi[k] = p[k];
    }
    MESH.c = lo.map((v, k) => (v + hi[k]) / 2);
    MESH.r = Math.max(...hi.map((v, k) => v - lo[k])) / 2 || 1;
    MESH.size = hi.map((v, k) => +(v - lo[k]).toFixed(2));
  }

  const cx = Math.cos(ROT.x), sx = Math.sin(ROT.x);
  const cy = Math.cos(ROT.y), sy = Math.sin(ROT.y);
  const k = Math.min(w, h) * 0.40 / MESH.r;
  const L = [0.35, 0.4, 0.85];

  const faces = [];
  for (const t of MESH.tris) {
    const p = t.map(v => {
      let x = v[0] - MESH.c[0], y = v[1] - MESH.c[1], z = v[2] - MESH.c[2];
      let y1 = y * cx - z * sx, z1 = y * sx + z * cx;      // pitch
      let x1 = x * cy + z1 * sy, z2 = -x * sy + z1 * cy;   // yaw
      return [x1, y1, z2];
    });
    const u = [p[1][0] - p[0][0], p[1][1] - p[0][1], p[1][2] - p[0][2]];
    const v2 = [p[2][0] - p[0][0], p[2][1] - p[0][1], p[2][2] - p[0][2]];
    const nv = [u[1] * v2[2] - u[2] * v2[1], u[2] * v2[0] - u[0] * v2[2],
                u[0] * v2[1] - u[1] * v2[0]];
    const len = Math.hypot(...nv) || 1;
    const lam = Math.max(0.12, (nv[0] * L[0] + nv[1] * L[1] + nv[2] * L[2]) / len);
    faces.push({ p, z: (p[0][2] + p[1][2] + p[2][2]) / 3, lam });
  }
  faces.sort((a, b) => a.z - b.z);            // painter's algorithm

  const X = v => w / 2 + v * k, Y = v => h / 2 - v * k;
  for (const f of faces) {
    const c = Math.round(60 + 150 * f.lam);
    g.fillStyle = `rgb(${Math.round(c * 0.55)},${Math.round(c * 0.78)},${c})`;
    g.beginPath();
    g.moveTo(X(f.p[0][0]), Y(f.p[0][1]));
    g.lineTo(X(f.p[1][0]), Y(f.p[1][1]));
    g.lineTo(X(f.p[2][0]), Y(f.p[2][1]));
    g.closePath(); g.fill();
  }
  g.fillStyle = DIM; g.font = '11px system-ui'; g.textAlign = 'left';
  g.fillText(`${MESH.shown.toLocaleString()} of ${MESH.total.toLocaleString()} triangles`
             + (MESH.size ? ` · ${MESH.size.join(' × ')} units` : ''), 8, h - 8);
}

async function loadBlades() {
  const r = await api('/api/blades');
  const list = $('#bl-list');
  if (!r.ok || !r.blades.length) {
    list.innerHTML = '<div class="sm dim">No blades yet. Drop an STL in ' +
      '<code>blades/</code> named to match your <code>--blade</code> argument, ' +
      'or run a sweep.</div>';
    return;
  }
  list.innerHTML = r.blades.map(b => `
    <div class="blade" data-n="${b.name}">
      <div class="blade-n">${b.name}</div>
      <div class="sm dim">
        ${b.stl ? `STL ${b.stl_kb} KB` : '<span class="bad">no STL</span>'} ·
        ${b.swept ? `${b.points} pts${b.p_max != null
            ? ', peak ' + b.p_max.toFixed(3) + ' W' : ''}`
                  : '<span class="bad">never swept</span>'}
        ${b.clean === false ? ' · <span class="warn">unclean points</span>' : ''}
      </div>
      ${b.protocol ? `<div class="sm dim mono">${b.protocol}</div>` : ''}
    </div>`).join('');
  $$('.blade').forEach(el => el.onclick = () => selectBlade(el.dataset.n));
  // Open on a real rotor, not the synthetic placeholder.
  const first = r.blades.find(b => !b.name.startsWith('_')) || r.blades[0];
  if (first) selectBlade(first.name);
}

let BLADE_REQ = 0;

async function selectBlade(name) {
  // Clicking B while A's 1.3 MB STL is still downloading used to render A's
  // geometry under B's heading. Each call takes a ticket; a stale reply is
  // dropped rather than painted.
  const ticket = ++BLADE_REQ;
  const current = () => ticket === BLADE_REQ;
  $$('.blade').forEach(e => e.classList.toggle('on', e.dataset.n === name));
  $('#bl-name').textContent = name;

  MESH = null; drawMesh($('#cv-mesh'));
  try {
    const res = await fetch(`/api/blades/${encodeURIComponent(name)}/stl`);
    const buf = await res.arrayBuffer();
    if (res.ok && current()) { MESH = parseSTL(buf); drawMesh($('#cv-mesh')); }
  } catch (e) { /* geometry is optional */ }

  const c = await api(`/api/blades/${encodeURIComponent(name)}/curve`)
    .catch(() => ({ ok: false }));
  if (!current()) return;
  const tb = $('#bl-tbl').querySelector('tbody');
  if (!c.ok) {
    drawPlot($('#cv-blade'), [], { empty: 'no sweep on record' });
    tb.innerHTML = '';
    $('#bl-meta').textContent = 'no sweep on record for this blade';
    return;
  }
  drawPlot($('#cv-blade'), [{
    color: '#00a3a1', width: 2.2,
    x: c.points.map(p => p.mps), y: c.points.map(p => p.p_w)
  }], { y0: 0, empty: 'no points' });
  tb.innerHTML = c.points.map(p =>
    `<tr class="${p.clean ? '' : 'warn'}"><td>${p.rpm}</td>` +
    `<td>${p.mps.toFixed(2)}</td><td class="mono">${p.p_w.toFixed(4)}</td>` +
    `<td class="mono">${p.i_a.toFixed(3)}</td><td>${p.limited_by}</td></tr>`).join('');
  const m = c.meta || {};
  $('#bl-meta').innerHTML =
    `${m.notes ? m.notes + ' · ' : ''}protocol <span class="mono">${m.protocol || '?'}</span>` +
    (m.blade && m.blade !== name ? ` · <span class="bad">file says ${m.blade}</span>` : '');
}

function wireBlades() {
  const cv = $('#cv-mesh');
  if (!cv) return;
  cv.addEventListener('mousedown', e => {
    DRAG = { x: e.clientX, y: e.clientY, x0: ROT.x, y0: ROT.y };
    e.preventDefault();
  });
  window.addEventListener('mouseup', () => { DRAG = null; });
  // Coalesce to one redraw per animation frame. A mousemove burst fires far
  // faster than 60 Hz, and each redraw transforms, sorts and fills the whole
  // mesh — 27,056 triangles here — so dragging queued far more work than the
  // machine could retire. Unusable on a Pi.
  let dragRaf = null;
  window.addEventListener('mousemove', e => {
    if (!DRAG) return;
    ROT.x = DRAG.x0 + (e.clientY - DRAG.y) * 0.01;
    ROT.y = DRAG.y0 + (e.clientX - DRAG.x) * 0.01;
    if (dragRaf) return;
    dragRaf = requestAnimationFrame(() => { dragRaf = null; drawMesh(cv); });
  });
  window.addEventListener('resize', () => drawMesh(cv));
}

document.addEventListener('DOMContentLoaded', wireBlades);


/* ══════════════════════════════════════════════════════════════════════
   DIGITAL TWIN

   A rotor rendered from the real STL, spinning at the speed the rig is
   actually producing, coloured by the live electrical state.

   Two honest limits, both surfaced on the display rather than hidden:

   · ROTOR SPEED IS DERIVED, NOT MEASURED. Nothing on this rig reports
     rotor rpm yet - the DAQ channel is not wired in. What is shown is
     inferred from terminal voltage through the generator constant, and
     that constant is itself unmeasured. The figure is therefore an
     ILLUSTRATION of state, never a measurement, and the panel says so.

   · The mesh is ONE BLADE. blades/turbine_blade.stl is a single blade,
     not an assembled rotor, so the twin instances it n_blades times about
     the hub axis. Tip radius is unknown (TODO B3), so the hub offset is a
     drawing convention, not a dimension.

   A twin earns its name by disagreeing with reality in a visible way. The
   readouts under the render are the live measurements; the render is the
   model. When they diverge, that is the interesting part.
   ══════════════════════════════════════════════════════════════════════ */

// stale:true and rpm:null until a frame proves otherwise — the twin must
// never open on a confident '0 rpm' standstill it has not measured.
let TWIN = { mesh: null, angle: 0, blades: 3, last: 0, rpm: null,
             stale: true, aliased: false, raf: null };

async function twinLoad(name) {
  try {
    const res = await fetch(`/api/blades/${encodeURIComponent(name)}/stl`);
    if (!res.ok) return false;
    const m = parseSTL(await res.arrayBuffer());
    // Decimate hard: this redraws every frame, n_blades times over.
    // Keep the LARGEST triangles, not every Nth. Index-stride decimation on
    // an STL keeps a uniform sample of triangle *count*, and in a mesh whose
    // areas span orders of magnitude that retained under a tenth of the
    // surface — the blade rendered as a sub-pixel stipple rather than a
    // solid. Sorting by area and keeping the top N covers the form.
    const area = t => {
      const u = [t[1][0]-t[0][0], t[1][1]-t[0][1], t[1][2]-t[0][2]];
      const v = [t[2][0]-t[0][0], t[2][1]-t[0][1], t[2][2]-t[0][2]];
      return Math.hypot(u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2],
                        u[0]*v[1]-u[1]*v[0]);
    };
    // Largest-first alone leaves holes: the small triangles that stitch the
    // big ones together get dropped and you can see through the blade. Keep
    // most of the budget for area coverage and spend the rest on a uniform
    // sample of everything else, which fills the seams.
    const BUDGET = 3000;
    if (m.tris.length > BUDGET) {
      const ranked = m.tris.map((t, i) => ({ t, i, a: area(t) }))
                           .sort((x, y) => y.a - x.a);
      const nBig = Math.floor(BUDGET * 0.7);
      const big = ranked.slice(0, nBig);
      const rest = ranked.slice(nBig);
      const stride = Math.max(1, Math.ceil(rest.length / (BUDGET - nBig)));
      const filler = rest.filter((_, k) => k % stride === 0);
      m.tris = big.concat(filler).sort((x, y) => x.i - y.i).map(o => o.t);
    }
    let lo = [1e9, 1e9, 1e9], hi = [-1e9, -1e9, -1e9];
    for (const t of m.tris) for (const p of t) for (let k = 0; k < 3; k++) {
      if (p[k] < lo[k]) lo[k] = p[k];
      if (p[k] > hi[k]) hi[k] = p[k];
    }
    m.c = lo.map((v, k) => (v + hi[k]) / 2);
    m.ext = hi.map((v, k) => v - lo[k]);
    m.span = Math.max(...m.ext);
    m.axis = m.ext.indexOf(m.span);                        // longest = span
    TWIN.mesh = m;
    $('#tw-note').textContent =
      `${m.tris.length} tri × ${TWIN.blades} blades · vertical axis, ` +
      `R = ${((TWIN.radius_m || 0.1016) * 1000).toFixed(0)} mm · ${name}`;
    return true;
  } catch (e) { return false; }
}

/** Rotor speed inferred from terminal volts. Illustrative, not measured. */
/**
 * Inferred rotor speed, or null when there is nothing to infer from.
 *
 * Returning 0 for a missing measurement was the wrong call: a disconnected
 * load board rendered as a rotor at a confident, motionless standstill —
 * indistinguishable from a genuinely stopped rotor. A twin that shows a
 * plausible state when it has no data is worse than one that shows nothing,
 * because the operator believes it.
 */
function twinRpm(s) {
  const L = s.load || {};
  if (!L.connected) return null;
  if (s.load_age_s == null) return null;      // connected but never reported
  if (s.load_age_s > 3) return null;          // stale
  const v = (L.volts || 0) + (L.amps || 0) * 40;   // add back the IR drop
  return Math.max(0, v * 130);
}

function twinVisible() {
  const pg = document.getElementById('p-turbine');
  return !document.hidden && pg && pg.classList.contains('on');
}

function twinDraw(ts) {
  // The loop used to run at 60 Hz from page load on every tab, sorting and
  // filling thousands of triangles for a canvas nobody was looking at.
  if (!twinVisible()) { TWIN.raf = null; return; }
  const cv = $('#cv-twin');
  const surf = setupCanvas(cv);
  if (!surf) { TWIN.raf = requestAnimationFrame(twinDraw); return; }
  const { g, w, h } = surf;
  // Derived from the same clock the connection watchdog uses. TWIN.stale was
  // only ever written by twinUpdate, which runs only when a frame ARRIVES —
  // so a dropped stream left the rotor turning confidently at its last known
  // speed, in full interlock colour, contradicting the stale banner three
  // inches above it. The most visually authoritative element on the page was
  // asserting live motion the app already knew it could not verify.
  if (Date.now() - LAST_FRAME > 3000) TWIN.stale = true;

  const dt = TWIN.last ? Math.min((ts - TWIN.last) / 1000, 0.1) : 0;
  TWIN.last = ts;
  // A 3-blade rotor aliases once blade-passing approaches the frame rate —
  // around 1200 rpm it renders perfectly motionless, which on this rig is
  // inside the normal operating range. The animation rate is therefore
  // capped and the cap is stated on screen; the NUMBER is always the real
  // inferred value. A believable-but-wrong animation is the failure mode a
  // twin has to avoid.
  // Aliasing depends on BLADE-PASSING frequency, not rotor rpm: an n-blade
  // rotor looks stationary when n*rpm/60 approaches the frame rate. Capping
  // a flat 240 rpm left a 5-blade rotor aliasing while a 2-blade one was
  // needlessly slowed. Cap the apparent blade-passing rate instead.
  const PASS_HZ = 6;                          // apparent blade passes/second
  const spinCap = PASS_HZ * 60 / Math.max(1, TWIN.blades);
  TWIN.aliased = TWIN.rpm !== null && TWIN.rpm > spinCap;
  const shown = TWIN.stale ? 0 : Math.min(TWIN.rpm || 0, spinCap);
  TWIN.angle += (shown / 60) * 2 * Math.PI * dt;

  g.clearRect(0, 0, w, h);
  const m = TWIN.mesh;
  if (!m) {
    g.fillStyle = DIM; g.font = '13px system-ui'; g.textAlign = 'center';
    g.fillText('no geometry — put an STL in blades/', w / 2, h / 2);
    TWIN.raf = requestAnimationFrame(twinDraw);
    return;
  }

  const S = STATE || {};
  const ik = (S.interlock || {}).level;
  // 'none' means no load is connected. That used to paint the same calm blue
  // as 'ok' — a rig with no load at all looked safe.
  const base = TWIN.stale ? [120, 120, 120]
             : ik === 'danger' ? [200, 60, 60]
             : ik === 'warn' ? [190, 140, 40]
             : ik === 'none' ? [130, 110, 150]
             : [70, 130, 180];

  // ── VERTICAL-AXIS rotor (H-rotor / Darrieus) ──
  //
  // The blades stand UPRIGHT at a fixed radius and sweep a cylinder; they do
  // not radiate outward from the hub. This was drawn as a horizontal-axis
  // propeller — span pointing outward — which is a different machine.
  //
  // Local blade axes: `ax` is the span, and it is VERTICAL here. The chord
  // lies roughly tangential, the thickness roughly radial.
  //
  // R is measured: 4 inches, shaft centre to the blade mount.
  const ax = m.axis;
  let r1 = (ax + 1) % 3, r2 = (ax + 2) % 3;
  if (m.ext && m.ext[r2] > m.ext[r1]) { const t = r1; r1 = r2; r2 = t; }
  if (!m.ext) m.ext = [0, 0, 0];
  const R = TWIN.radius_m || 0.1016;   // metres, shaft centre to blade
  const k = Math.min(w, h) * 0.44 / Math.max(m.span, 2 * R + m.ext[r2]);
  const elev = 0.34, ce = Math.cos(elev), se = Math.sin(elev);
  // Chord and thickness chosen by EXTENT, not by index order.
  //
  // `(ax+1)%3, (ax+2)%3` happened to assign this blade's 24.5 mm thickness
  // axis to the chord and its 48.0 mm chord to the thickness — exactly
  // inverted. The rotor rendered permanently feathered: 48 mm of chord laid
  // down the shaft, 20 mm of thickness in the plane of rotation. Round 1
  // fixed the CYCLIC pitch error and left a static 90-degree one, which is
  // harder to see because it never changes.
  //
  // This is still a heuristic — the wider of the two remaining axes is
  // assumed to be chordwise. True for an aerofoil; it would need the facet
  // normals to be robust.
  const faces = [];

  for (let b = 0; b < TWIN.blades; b++) {
    const a = TWIN.angle + b * 2 * Math.PI / TWIN.blades;
    const ca = Math.cos(a), sa = Math.sin(a);
    for (const t of m.tris) {
      const p = t.map(v => {
        // One rigid rotation about the VERTICAL shaft, then the view.
        //
        // This previously rotated the cross-section about the span axis by
        // `a` AND the (span, chord) pair about the shaft by the same `a`.
        // The composite R_z(a)*R_x(a) is still rigid, but its axis moves with
        // `a`, so every blade rolled about its own span once per revolution —
        // fully feathered at 90 and 270 degrees, chord pointing straight down
        // the shaft. Blade twist is the one thing this geometry exists to
        // show, so rendering a cyclic-pitch propeller instead of a
        // fixed-pitch rotor was the worst possible error to make here.
        const hgt = v[ax] - m.c[ax];        // span → VERTICAL, unrotated
        const ch = v[r1] - m.c[r1];         // chord → tangential
        const th = v[r2] - m.c[r2];         // thickness → radial
        const rad = R + th;
        const X = rad * ca - ch * sa;       // horizontal plane
        const Y = rad * sa + ch * ca;
        // View from slightly above: vertical stays vertical on screen.
        return [X, hgt * ce - Y * se, hgt * se + Y * ce];
      });
      const u = [p[1][0] - p[0][0], p[1][1] - p[0][1], p[1][2] - p[0][2]];
      const q = [p[2][0] - p[0][0], p[2][1] - p[0][1], p[2][2] - p[0][2]];
      const nv = [u[1] * q[2] - u[2] * q[1], u[2] * q[0] - u[0] * q[2],
                  u[0] * q[1] - u[1] * q[0]];
      const len = Math.hypot(...nv) || 1;
      const lam = Math.max(0.20, Math.abs(nv[2]) / len);
      faces.push({ p, z: (p[0][2] + p[1][2] + p[2][2]) / 3, lam });
    }
  }
  faces.sort((a, b) => a.z - b.z);
  const X = v => w / 2 + v * k, Y = v => h / 2 - v * k;

  // The vertical shaft, so the axis of rotation is unmistakable.
  g.strokeStyle = '#9aa7b2'; g.lineWidth = 3;
  g.beginPath();
  g.moveTo(X(0), Y(m.span * 0.62)); g.lineTo(X(0), Y(-m.span * 0.62));
  g.stroke();

  for (const f of faces) {
    g.fillStyle = `rgb(${Math.round(base[0] * f.lam + 40)},` +
                  `${Math.round(base[1] * f.lam + 40)},` +
                  `${Math.round(base[2] * f.lam + 40)})`;
    g.beginPath();
    g.moveTo(X(f.p[0][0]), Y(f.p[0][1]));
    g.lineTo(X(f.p[1][0]), Y(f.p[1][1]));
    g.lineTo(X(f.p[2][0]), Y(f.p[2][1]));
    g.closePath(); g.fill();
  }

  g.fillStyle = TWIN.stale ? '#c62828' : INK;
  g.font = '600 13px system-ui'; g.textAlign = 'left';
  g.fillText(TWIN.stale ? 'NO LIVE DATA — rotor frozen, not stopped'
                        : `~${TWIN.rpm.toFixed(0)} rpm rotor (inferred)`, 10, 20);
  if (TWIN.aliased && !TWIN.stale) {
    g.fillStyle = '#8a7038'; g.font = '11px system-ui';
    g.fillText(`animation slowed to ${spinCap.toFixed(0)} rpm — the number ` +
               `above is the real inferred speed`, 10, 52);
  }
  g.font = '11px system-ui'; g.fillStyle = DIM;
  g.fillText(`fan ${fmt((S.measured || {}).hz, 0)} rpm · ` +
             `${fmt((S.load || {}).volts, 2)} V · ` +
             `${fmt(((S.load || {}).amps || 0) * 1000, 1)} mA · ` +
             `${fmt((S.load || {}).watts, 3)} W`, 10, 36);
  TWIN.raf = requestAnimationFrame(twinDraw);
}

function twinUpdate(s) {
  // Geometry from tunnel.json, not a constant in this file. R is measured:
  // 4 inches, shaft centre to the blade mount.
  const g = s.turbine || {};
  if (g.radius_m) TWIN.radius_m = g.radius_m;
  if (g.n_blades && !TWIN._bladesSet) {
    TWIN.blades = g.n_blades;
    const sel = $('#tw-blades');
    if (sel.value !== undefined) sel.value = String(g.n_blades);
    TWIN._bladesSet = true;
  }
  TWIN.rpm = twinRpm(s);
  TWIN.stale = (TWIN.rpm === null) || (s.age_s != null && s.age_s > 3);
  // Kept in step with what the canvas says. A stale frame used to leave the
  // DOM figure showing a confident number while the render said NO LIVE DATA.
  $('#tw-rpm').textContent = (TWIN.rpm === null || TWIN.stale)
    ? 'no data' : TWIN.rpm.toFixed(0);
}

async function twinInit() {
  if (!document.getElementById('cv-twin')) return;
  const r = await api('/api/blades').catch(() => null);
  const withStl = r && r.blades ? r.blades.filter(b => b.stl) : [];
  if (withStl.length) {
    // Prefer a real rotor over the synthetic placeholder. Defaulting to
    // `_demo_rotor` meant the twin — and the Blades tab — opened on a shape
    // nobody in the lab has ever printed, presented exactly like the
    // measured article.
    const real = withStl.filter(b => !b.name.startsWith('_'));
    const pick = (real[0] || withStl[0]).name;
    const sel = $('#tw-pick');
    sel.innerHTML = withStl.map(b =>
      `<option${b.name === pick ? ' selected' : ''}>${b.name}` +
      `${b.name.startsWith('_') ? ' (synthetic)' : ''}</option>`).join('');
    sel.onchange = () => twinLoad(sel.value.replace(' (synthetic)', ''));
    await twinLoad(pick);
  }
  bind('#tw-blades', 'change', e => { TWIN.blades = +e.target.value || 3; });
  // Started only when the Turbine tab is actually showing.
  if (twinVisible() && !TWIN.raf) TWIN.raf = requestAnimationFrame(twinDraw);
}

document.addEventListener('DOMContentLoaded', twinInit);
document.addEventListener('visibilitychange', () => {
  if (twinVisible() && !TWIN.raf) { TWIN.last = 0;
    TWIN.raf = requestAnimationFrame(twinDraw); }
});


/* ══════════════════════════════════════════════════════════════════════
   PARAMETERS — capability, profiles, snapshots

   The tab used to offer a Write button on every row regardless of what the
   transport underneath could do. Over a 2.0 PMC every one of them failed
   with a register-level error pointing at entirely the wrong thing, because
   that firmware is command-shaped and cannot reach a parameter at all.

   So the first thing this asks is what the link can actually do, and it
   shows the answer before anything else.
   ══════════════════════════════════════════════════════════════════════ */

let PCAP = null;

async function loadParamCapability() {
  try {
    const r = await api('/api/params/capability');
    PCAP = r.capability;
    const able = PCAP.read && PCAP.write;
    $('#pr-cap-kind').textContent =
      PCAP.kind === 'pmc' ? `PMC firmware ${PCAP.firmware}` : PCAP.kind;
    const el = $('#pr-cap');
    el.className = 'note' + (able ? '' : ' warn');
    el.innerHTML = (able ? '✓ ' : '⚠ ') + PCAP.note;
    $('#pr-diff').disabled = !PCAP.read;
    $('#pr-dry').disabled = !PCAP.read;
    const sel = $('#pr-profile');
    sel.innerHTML = (r.profiles || []).map(p =>
      `<option value="${p.name}">${p.name} — ${p.count} parameters</option>`)
      .join('') || '<option value="">no profiles found</option>';
  } catch (e) {
    $('#pr-cap').innerHTML = 'could not determine capability: ' + e.message;
  }
}

function renderDiff(d, mode) {
  const rows = d.rows || d.would_write || [];
  if (!rows.length) {
    $('#pr-diff-out').innerHTML =
      '<div class="sm dim">nothing to show</div>';
    return;
  }
  const differ = rows.filter(r => r.match === false || mode === 'plan').length;
  $('#pr-diff-out').innerHTML = `
    <div class="sm dim" style="margin-bottom:6px">
      ${mode === 'plan' ? `<b>${rows.length}</b> would be written`
                        : `<b>${differ}</b> of ${rows.length} differ from the profile`}
    </div>
    <table class="tbl"><thead><tr>
      <th>par</th><th>name</th><th>drive</th><th>profile</th><th>why</th>
    </tr></thead><tbody>
    ${rows.map(r => {
      const cls = r.refused ? 'warn' : (r.match === false ? 'differ' : '');
      const live = r.error ? `<span class="bad">${r.error}</span>`
                           : (r.live ?? r.before ?? '—');
      return `<tr class="${cls}">
        <td class="mono">${r.num}</td>
        <td>${r.name || ''}</td>
        <td class="mono">${live}</td>
        <td class="mono">${r.target}</td>
        <td class="sm dim">${r.refused
          ? '<b>firmware refuses:</b> ' + r.refused : (r.why || '')}</td>
      </tr>`;
    }).join('')}</tbody></table>`;
}

function wireParams() {
  bind('#pr-diff', 'click', async () => {
    const name = $('#pr-profile').value;
    if (!name) return;
    note('#pr-prof-note', 'reading the drive…');
    try {
      const d = await api(`/api/params/profile/${encodeURIComponent(name)}`);
      renderDiff(d, 'diff');
      const n = d.rows.filter(r => r.match === false).length;
      note('#pr-prof-note', n ? `${n} differ` : 'the drive matches this profile',
           n ? 'warn' : 'ok');
      $('#pr-apply').disabled = !(n && PCAP && PCAP.write);
    } catch (e) { note('#pr-prof-note', e.message, 'bad'); }
  });

  bind('#pr-dry', 'click', async () => {
    const name = $('#pr-profile').value;
    note('#pr-prof-note', 'planning…');
    try {
      const d = await api('/api/params/apply', { profile: name, commit: false });
      renderDiff({ would_write: d.would_write }, 'plan');
      const nref = (d.refused || []).length;
      note('#pr-prof-note',
           `DRY RUN — ${d.would_write.length} would be written` +
           (nref ? `, ${nref} refused by firmware` : '') + '. Nothing changed.',
           'ok');
      $('#pr-apply').disabled = !(d.would_write.length && PCAP && PCAP.write);
    } catch (e) { note('#pr-prof-note', e.message, 'bad'); }
  });

  bind('#pr-apply', 'click', async () => {
    const name = $('#pr-profile').value;
    // Two confirmations, and the second requires typing the profile name.
    // A parameter write is persistent with no undo; a single OK button is
    // not proportionate to that.
    if (!confirm(`Apply profile "${name}" to the drive?\n\n` +
                 `Parameter writes are PERSISTENT and have NO UNDO — the same ` +
                 `as editing on the keypad.\n\nA snapshot of the current ` +
                 `values will be saved first, and the write is refused if ` +
                 `that snapshot cannot be written.`)) return;
    if (prompt(`Type the profile name to confirm:`) !== name) {
      note('#pr-prof-note', 'aborted — name did not match', 'warn');
      return;
    }
    note('#pr-prof-note', 'writing…');
    try {
      const d = await api('/api/params/apply', { profile: name, commit: true });
      const w = d.written.length, f = d.failed.length;
      note('#pr-prof-note',
           `${w} written and verified` + (f ? `, ${f} did not take` : '') +
           ` · backup ${(d.backup || '').split('/').pop()}`, f ? 'warn' : 'ok');
      renderDiff({ rows: d.written.concat(d.failed).map(r =>
        ({ ...r, live: r.after, match: r.after === r.target })) }, 'diff');
      loadParams();
    } catch (e) { note('#pr-prof-note', e.message, 'bad'); }
  });

  bind('#pr-snap', 'click', async () => {
    note('#pr-snap-out', 'reading every known parameter…');
    try {
      const d = await api('/api/params/snapshot',
                          { note: $('#pr-snap-note').value });
      note('#pr-snap-out',
           `${d.read} read${d.failed.length ? `, ${d.failed.length} unreadable`
                                            : ''} → ${d.file.split('/').pop()}`,
           'ok');
    } catch (e) { note('#pr-snap-out', e.message, 'bad'); }
  });
}

document.addEventListener('DOMContentLoaded', wireParams);


/* ── full parameter scan, and saved configurations ──────────────────── */

let SCAN_TIMER = null;

async function pollScan() {
  try {
    const r = await api('/api/params/scan/status');
    const s = r.scan;
    if (!s) return;
    const pct = s.total ? 100 * s.done / s.total : 0;
    $('#pr-scan-bar').style.width = pct + '%';
    if (s.state === 'running') {
      note('#pr-snap-out',
           `scanning ${s.group || ''} — ${s.found} found, ${pct.toFixed(0)}%`);
      $('#pr-scan-abort').disabled = false;
    } else {
      clearInterval(SCAN_TIMER); SCAN_TIMER = null;
      $('#pr-scan-abort').disabled = true;
      $('#pr-scan').disabled = false;
      note('#pr-snap-out', s.message +
           (s.file ? ` → ${s.file.split('/').pop()}` : ''), 'ok');
      loadSnapshots();
    }
  } catch (e) { clearInterval(SCAN_TIMER); SCAN_TIMER = null; }
}

async function loadSnapshots() {
  try {
    const r = await api('/api/params/snapshots');
    $('#pr-snaps').innerHTML = (r.snapshots || []).map(s =>
      `<option value="${s.file}">${s.file} — ${s.count} params` +
      `${s.note ? ' · ' + s.note.slice(0, 40) : ''}</option>`).join('')
      || '<option value="">no snapshots yet</option>';
  } catch (e) { /* optional */ }
}

function wireScan() {
  bind('#pr-scan', 'click', async () => {
    if (!confirm('Scan every parameter on the drive?\n\n' +
                 'This is read-only and cannot change anything, but it is a ' +
                 'few thousand round trips and takes several minutes.')) return;
    try {
      await api('/api/params/scan', { all: $('#pr-scan-all').checked,
                                      note: $('#pr-snap-note').value });
      $('#pr-scan').disabled = true;
      if (SCAN_TIMER) clearInterval(SCAN_TIMER);
      SCAN_TIMER = setInterval(pollScan, 700);
    } catch (e) { note('#pr-snap-out', e.message, 'bad'); }
  });

  bind('#pr-scan-abort', 'click', () => api('/api/params/scan/abort', {}));

  bind('#pr-snap-diff', 'click', async () => {
    const f = $('#pr-snaps').value;
    if (!f) return;
    note('#pr-snap-note2', 'reading the drive…');
    try {
      const d = await api(`/api/params/snapshot/${encodeURIComponent(f)}`);
      renderDiff(d, 'diff');
      const n = d.rows.filter(r => r.match === false).length;
      note('#pr-snap-note2',
           n ? `${n} of ${d.rows.length} differ from ${f}`
             : `the drive matches ${f} exactly`, n ? 'warn' : 'ok');
    } catch (e) { note('#pr-snap-note2', e.message, 'bad'); }
  });

  bind('#pr-snap-restore', 'click', async () => {
    const f = $('#pr-snaps').value;
    if (!f) return;
    note('#pr-snap-note2', 'planning the restore…');
    try {
      const dry = await api('/api/params/apply', { snapshot: f, commit: false });
      renderDiff({ would_write: dry.would_write }, 'plan');
      if (!dry.would_write.length) {
        note('#pr-snap-note2', 'nothing to restore — the drive already matches',
             'ok');
        return;
      }
      if (!confirm(`Restore ${dry.would_write.length} parameter(s) from ` +
                   `${f}?\n\nPersistent, NO UNDO. A snapshot of the current ` +
                   `values is saved first, and the restore is refused if that ` +
                   `snapshot cannot be written.\n\n` +
                   `${dry.refused.length} parameter(s) are refused by firmware ` +
                   `and will be skipped.`)) {
        note('#pr-snap-note2', 'dry run only — nothing written', 'ok');
        return;
      }
      if (prompt('Type RESTORE to confirm:') !== 'RESTORE') {
        note('#pr-snap-note2', 'aborted', 'warn'); return;
      }
      const d = await api('/api/params/apply', { snapshot: f, commit: true });
      note('#pr-snap-note2',
           `${d.written.length} restored and verified` +
           (d.failed.length ? `, ${d.failed.length} did not take` : '') +
           ` · backup ${(d.backup || '').split('/').pop()}`,
           d.failed.length ? 'warn' : 'ok');
      loadParams(); loadSnapshots();
    } catch (e) { note('#pr-snap-note2', e.message, 'bad'); }
  });

  bind('#pr-promote', 'click', async () => {
    const f = $('#pr-snaps').value, name = $('#pr-promote-name').value.trim();
    if (!f || !name) { note('#pr-snap-note2', 'pick a snapshot and give it a name', 'bad'); return; }
    try {
      const d = await api('/api/params/promote', {
        snapshot: f, name, description: $('#pr-promote-desc').value,
        force: false });
      note('#pr-snap-note2',
           `profile '${d.name}' created — ${d.kept} parameters, ` +
           `${d.excluded} excluded as unwritable`, 'ok');
      loadParamCapability();
    } catch (e) { note('#pr-snap-note2', e.message, 'bad'); }
  });

  loadSnapshots();
}

document.addEventListener('DOMContentLoaded', wireScan);
