// Page logic: saved results, in-browser runs through worker.js, and the design documents.

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);

const CRITERIA = {
  price_within_band: 'Price within band',
  supply_stable: 'Supply stable',
  fabrication_less_rewarded: 'Fabrication less rewarded',
  calibration_improves: 'Calibration improves',
  handover_converges: 'Handover converges',
  selflessness_tracks_truth: 'Selflessness index tracks truth',
  ledger_integrity: 'Ledger integrity',
  equation_residual: 'Equation residual',
};

const SERIES = {
  M: 'Supply M',
  P: 'Price P (Shula per basket)',
  V: 'Velocity V',
  R: 'Judged service value R',
  dM: 'Supply change ΔM',
  requested_dM: 'Requested ΔM (before caps)',
  equation_residual: 'Equation residual',
  S_t: 'Selflessness index S_t (provisional)',
  true_S: 'True selfless share',
  lambda: 'Agent weight λ',
  a_t: 'Agent–human agreement a_t',
  claimants: 'Claimants',
  unclaimed_share: 'Unclaimed share of supply',
  pending_acts: 'Pending acts',
  calibration_error: 'Calibration error',
  ring_capture: 'Ring share of minting',
};

const fmt = (v) => (v === null || v === undefined || v === '' ? '—'
  : typeof v === 'number' ? (Math.abs(v) >= 1e5 || (Math.abs(v) < 1e-3 && v !== 0) ? v.toExponential(3) : v.toLocaleString(undefined, { maximumSignificantDigits: 4 }))
  : esc(v));
const badge = (status) => `<span class="badge ${esc(status)}">${esc(status.replace('_', ' '))}</span>`;
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

// ------------------------------------------------------------------ tabs
document.querySelectorAll('nav button').forEach((button) => {
  button.addEventListener('click', () => {
    document.querySelectorAll('nav button').forEach((b) => b.setAttribute('aria-selected', String(b === button)));
    for (const tab of ['saved', 'run', 'design']) $('tab-' + tab).hidden = tab !== button.dataset.tab;
    if (button.dataset.tab === 'run') startEngine();
    redrawAll();
  });
});

// ------------------------------------------------------------------ data helpers
async function getJSON(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(path + ': ' + r.status);
  return r.json();
}

function parseCSV(text) {
  const lines = text.trim().split(/\r?\n/);
  const head = lines[0].split(',');
  return lines.slice(1).map((line) => {
    const cells = line.split(',');
    const row = {};
    head.forEach((key, i) => {
      const raw = cells[i];
      row[key] = raw === '' || raw === undefined ? null : raw === 'True' ? true : raw === 'False' ? false
        : Number.isFinite(Number(raw)) ? Number(raw) : raw;
    });
    return row;
  });
}

// ------------------------------------------------------------------ chart
const charts = [];

function drawChart(canvas, lines, scaleNote) {
  const dpr = window.devicePixelRatio || 1;
  const width = canvas.clientWidth, height = canvas.clientHeight;
  if (!width) return;
  canvas.width = width * dpr; canvas.height = height * dpr;
  const g = canvas.getContext('2d');
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, width, height);
  const points = lines.flatMap((l) => l.ys.filter((y) => typeof y === 'number' && Number.isFinite(y)));
  const xs = lines.flatMap((l) => l.xs);
  if (!points.length) {
    g.fillStyle = css('--muted'); g.font = '13px system-ui';
    g.fillText('No values for this series.', 12, 24);
    scaleNote.textContent = '';
    return;
  }
  let lo = Math.min(...points), hi = Math.max(...points);
  const log = lo > 0 && hi / lo >= 100;
  const f = log ? Math.log10 : (v) => v;
  let ylo = f(lo), yhi = f(hi);
  if (ylo === yhi) { ylo -= 1; yhi += 1; }
  const xlo = Math.min(...xs), xhi = Math.max(...xs);
  const pad = { l: 64, r: 12, t: 10, b: 28 };
  const X = (x) => pad.l + ((x - xlo) / ((xhi - xlo) || 1)) * (width - pad.l - pad.r);
  const Y = (y) => height - pad.b - ((f(y) - ylo) / (yhi - ylo)) * (height - pad.t - pad.b);
  g.strokeStyle = css('--line'); g.fillStyle = css('--muted'); g.lineWidth = 1;
  g.font = '11px ui-monospace, monospace';
  for (let i = 0; i <= 4; i++) {
    const v = ylo + (i / 4) * (yhi - ylo);
    const y = height - pad.b - (i / 4) * (height - pad.t - pad.b);
    g.beginPath(); g.moveTo(pad.l, y); g.lineTo(width - pad.r, y); g.stroke();
    const label = log ? 10 ** v : v;
    g.textAlign = 'right'; g.fillText(fmt(label).replace(/<[^>]+>/g, ''), pad.l - 6, y + 4);
  }
  g.textAlign = 'center';
  for (let i = 0; i <= 4; i++) {
    const x = xlo + (i / 4) * (xhi - xlo);
    g.fillText(String(Math.round(x)), X(x), height - 8);
  }
  for (const line of lines) {
    g.strokeStyle = line.color; g.lineWidth = 1.6; g.setLineDash(line.dashed ? [5, 4] : []);
    g.beginPath();
    let open = false;
    line.xs.forEach((x, i) => {
      const y = line.ys[i];
      if (typeof y !== 'number' || !Number.isFinite(y) || (log && y <= 0)) { open = false; return; }
      if (open) g.lineTo(X(x), Y(y)); else { g.moveTo(X(x), Y(y)); open = true; }
    });
    g.stroke();
  }
  g.setLineDash([]);
  scaleNote.textContent = 'Horizontal axis: epoch. ' + (log ? 'Vertical axis logarithmic (values span more than a factor of 100).' : 'Vertical axis linear.');
}

function legend(el, lines) {
  el.innerHTML = lines.map((l) => `<span><i style="background:${l.color};${l.dashed ? 'opacity:.6' : ''}"></i>${esc(l.label)}</span>`).join('');
}

function redrawAll() { charts.forEach((draw) => draw()); }
window.addEventListener('resize', redrawAll);
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', redrawAll);

function seriesOptions(select, header) {
  select.innerHTML = Object.entries(SERIES).filter(([k]) => header.includes(k))
    .map(([k, label]) => `<option value="${k}">${esc(label)}</option>`).join('');
}

// ------------------------------------------------------------------ saved results
const epochCache = {};
async function epochs(run) {
  if (!epochCache[run]) epochCache[run] = fetch(`data/runs/${run}/epochs.csv`).then((r) => r.text()).then(parseCSV);
  return epochCache[run];
}

async function loadSaved() {
  const [manifest, comparison] = await Promise.all([getJSON('data/manifest.json'), getJSON('data/comparison.json')]);
  const cfg = await getJSON(`data/runs/${manifest.main[0]}/config.json`);
  $('saved-command').innerHTML = `Regenerated from the published simulator with <code>${esc(manifest.command)}</code>. Each run: synthetic population of ${cfg.population_size}, ${cfg.num_epochs} epochs of ${cfg.epoch_length} days. Simulator SHA-256 <code>${esc(manifest.simulator_sha256.slice(0, 16))}…</code>`;
  const keys = Object.keys(CRITERIA).filter((k) => comparison[0].criteria[k]);
  $('criteria-table').innerHTML = '<tr><th>Run</th>' + keys.map((k) => `<th>${esc(CRITERIA[k])}</th>`).join('') + '</tr>'
    + comparison.map((s) => `<tr><td>${esc(s.run)}</td>` + keys.map((k) => `<td title="${esc(s.criteria[k].detail)}">${badge(s.criteria[k].status)}</td>`).join('') + '</tr>').join('');
  $('measured-table').innerHTML = '<tr><th>Run</th><th>Observed price range</th><th>Maximum supply multiple</th><th>Final agent weight</th><th>Classification error</th><th>Maximum equation residual</th><th>Capped epochs</th><th>Ring mint / honest mint</th></tr>'
    + comparison.map((s) => {
      const c = s.criteria, fab = c.fabrication_less_rewarded;
      return `<tr><td>${esc(s.run)}</td><td class="num">${fmt(c.price_within_band.minimum)} – ${fmt(c.price_within_band.maximum)}</td>`
        + `<td class="num">${fmt(c.supply_stable.maximum_multiple)}</td><td class="num">${fmt(c.handover_converges.final_weight)}</td>`
        + `<td class="num">${fmt(c.selflessness_tracks_truth.classification_error)}</td><td class="num">${fmt(c.equation_residual.maximum_absolute)}</td>`
        + `<td class="num">${fmt(c.equation_residual.constrained_epochs)}</td>`
        + `<td class="num">${fab.ring_gross_mint ? fmt(fab.ring_gross_mint / fab.honest_gross_mint) : '—'}</td></tr>`;
    }).join('');
  const seeds = [...new Set(manifest.main.map((r) => r.split('_seed')[1]))];
  $('saved-seed').innerHTML = seeds.map((s) => `<option value="${esc(s)}">${esc(s)}</option>`).join('');
  const header = Object.keys((await epochs(manifest.main[0]))[0]);
  seriesOptions($('saved-series'), header);
  const draw = async () => {
    const seed = $('saved-seed').value, key = $('saved-series').value;
    const wanted = [['A', css('--accent'), false], ['B', css('--series-2'), false]];
    if ($('saved-honest').checked) wanted.push(['A', css('--accent'), true], ['B', css('--series-2'), true]);
    const lines = [];
    for (const [variant, color, honest] of wanted) {
      const run = `${variant}_seed${seed}${honest ? '_honest' : ''}`;
      if (!manifest.runs.includes(run)) continue;
      const rows = await epochs(run);
      lines.push({ label: `Variant ${variant}${honest ? ', honest reference' : ''}`, color, dashed: honest,
        xs: rows.map((r) => r.epoch), ys: rows.map((r) => r[key]) });
    }
    legend($('saved-legend'), lines);
    drawChart($('saved-chart'), lines, $('saved-scale'));
  };
  ['saved-seed', 'saved-series', 'saved-honest'].forEach((id) => $(id).addEventListener('change', draw));
  charts.push(draw);
  draw();
}

// ------------------------------------------------------------------ in-browser runs
const MAIN_FIELDS = ['variant', 'seed', 'population_size', 'num_epochs', 'epoch_length', 'kappa', 'V_min',
  'genesis_cap', 'fabricator_share', 'bringer_share', 'discovery_probability', 'phase_two_date'];
const CHOICES = { variant: ['A', 'B'], claim_limit_scope: ['per_person_per_epoch', 'per_person_lifetime', 'phase_total'] };

let worker, describe, lastResult, runTimer, runDraw = null;
charts.push(() => runDraw && runDraw());

function fieldInput(name) {
  const type = describe.types[name], value = describe.defaults[name];
  const id = 'cfg-' + name;
  if (type.startsWith('bool')) {
    return `<label class="check"><input type="checkbox" id="${id}" ${value ? 'checked' : ''}> ${esc(name)}</label>`;
  }
  if (CHOICES[name]) {
    return `<label class="field">${esc(name)}<select id="${id}">${CHOICES[name].map((c) => `<option ${c === value ? 'selected' : ''}>${esc(c)}</option>`).join('')}</select></label>`;
  }
  const numeric = /^(int|float)/.test(type);
  const shown = value === null ? '' : value;
  return `<label class="field">${esc(name)}<input id="${id}" ${numeric ? 'inputmode="decimal"' : ''} value="${esc(shown)}" placeholder="${type.includes('None') ? 'none' : ''}" data-type="${esc(type)}"></label>`;
}

function readSettings() {
  const settings = {};
  for (const name of describe.order) {
    const el = $('cfg-' + name), type = describe.types[name];
    if (type.startsWith('bool')) { settings[name] = el.checked; continue; }
    const raw = el.value.trim();
    if (raw === '') {
      if (!type.includes('None')) throw new Error(name + ' requires a value');
      settings[name] = null;
    } else if (/^(int|float)/.test(type)) {
      const n = Number(raw);
      if (!Number.isFinite(n)) throw new Error(name + ' must be a number');
      settings[name] = n;
    } else settings[name] = raw;
  }
  settings.compare_honest = $('compare-honest').checked;
  return settings;
}

function buildForm() {
  $('main-fields').innerHTML = MAIN_FIELDS.filter((n) => describe.types[n]).map(fieldInput).join('');
  $('all-fields').innerHTML = describe.order.filter((n) => !MAIN_FIELDS.includes(n)).map(fieldInput).join('');
  $('compare-honest').checked = false;
}

function startEngine() {
  if (worker) return;
  worker = new Worker('worker.js', { type: 'module' });
  worker.onmessage = ({ data }) => {
    if (data.type === 'ready') {
      describe = data.config;
      $('engine-status').textContent = `Ready: Python ${data.python} in Pyodide ${data.pyodide}. Defaults below are read from the simulator's Config.`;
      buildForm();
      $('run-form').hidden = false;
    } else if (data.type === 'boot-error') {
      $('engine-status').textContent = 'The Python engine could not start in this browser: ' + data.error;
    } else if (data.type === 'result') {
      finishRun();
      showResult(JSON.parse(data.json), data.seconds);
    } else if (data.type === 'run-error') {
      finishRun();
      $('run-status').textContent = 'The simulator stopped: ' + data.error;
    }
  };
  worker.onerror = (e) => { $('engine-status').textContent = 'The Python engine could not start: ' + (e.message || 'worker error'); };
}

function finishRun() {
  clearInterval(runTimer);
  $('run-button').disabled = false;
}

$('run-form').addEventListener('submit', (event) => {
  event.preventDefault();
  let settings;
  try { settings = readSettings(); } catch (error) { $('run-status').textContent = error.message; return; }
  $('run-button').disabled = true;
  const start = performance.now();
  const tick = () => { $('run-status').textContent = `Running… ${((performance.now() - start) / 1000).toFixed(0)} s`; };
  tick(); runTimer = setInterval(tick, 1000);
  worker.postMessage({ type: 'run', settings });
});

$('reset-button').addEventListener('click', buildForm);

function showResult(result, seconds) {
  lastResult = result;
  const c = result.config;
  $('run-results').hidden = false;
  $('run-status').textContent = `Finished in ${seconds.toFixed(1)} s.`;
  $('run-summary').textContent = `Variant ${c.variant}, seed ${c.seed}, population ${c.population_size}, ${c.num_epochs} epochs of ${c.epoch_length} days. Short runs report NOT EVALUATED where the observation window is insufficient.`;
  $('run-criteria').innerHTML = '<tr><th>Criterion</th><th>Status</th><th>Meaning</th></tr>'
    + Object.entries(result.criteria).map(([k, v]) => `<tr><td>${esc(CRITERIA[k] || k)}</td><td>${badge(v.status)}</td><td>${esc(v.detail)}</td></tr>`).join('');
  seriesOptions($('run-series'), Object.keys(result.rows[0]));
  const draw = () => {
    const key = $('run-series').value;
    const lines = [{ label: `Variant ${c.variant}, seed ${c.seed}`, color: css('--accent'),
      xs: result.rows.map((r) => r.epoch), ys: result.rows.map((r) => r[key]) }];
    legend($('run-legend'), lines);
    drawChart($('run-chart'), lines, $('run-scale'));
  };
  $('run-series').onchange = draw;
  runDraw = draw;
  draw();
}

function download(name, text, type) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = Object.assign(document.createElement('a'), { href: url, download: name });
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

$('download-csv').addEventListener('click', () => {
  const rows = lastResult.rows, head = Object.keys(rows[0]);
  const cell = (v) => (v === null ? '' : v === true ? 'True' : v === false ? 'False' : String(v));
  download('epochs.csv', [head.join(','), ...rows.map((r) => head.map((k) => cell(r[k])).join(','))].join('\n') + '\n', 'text/csv');
});
$('download-json').addEventListener('click', () => download('result.json', JSON.stringify(lastResult, null, 1), 'application/json'));

// ------------------------------------------------------------------ design documents
function inline(text) {
  return esc(text).replace(/`([^`]+)`/g, '<code>$1</code>').replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (m, t, u) => /^(https?:|#|[\w./-]+$)/.test(u) ? `<a href="${u}">${t}</a>` : m);
}

function markdown(source) {
  const lines = source.replace(/\r/g, '').split('\n');
  let html = '', i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (line.startsWith('```')) {
      const body = [];
      for (i++; i < lines.length && !lines[i].startsWith('```'); i++) body.push(lines[i]);
      html += `<pre><code>${esc(body.join('\n'))}</code></pre>`; i++; continue;
    }
    const h = line.match(/^(#{1,4})\s+(.*)/);
    if (h) { const n = Math.min(4, h[1].length + 1); html += `<h${n}>${inline(h[2])}</h${n}>`; i++; continue; }
    if (line.startsWith('|')) {
      const rows = [];
      for (; i < lines.length && lines[i].startsWith('|'); i++) rows.push(lines[i]);
      const cells = (r) => r.replace(/^\||\|$/g, '').split('|').map((c) => c.trim());
      const body = rows.filter((r, k) => !(k === 1 && /^\|[\s:|-]+\|$/.test(r)));
      html += '<div class="scroll"><table>' + body.map((r, k) => '<tr>' + cells(r).map((c) => k === 0 ? `<th>${inline(c)}</th>` : `<td>${inline(c)}</td>`).join('') + '</tr>').join('') + '</table></div>';
      continue;
    }
    if (/^\s*[-*]\s+/.test(line)) {
      const items = [];
      for (; i < lines.length && /^\s*[-*]\s+/.test(lines[i]); i++) items.push(lines[i].replace(/^\s*[-*]\s+/, ''));
      html += '<ul>' + items.map((t) => `<li>${inline(t)}</li>`).join('') + '</ul>'; continue;
    }
    if (!line.trim()) { i++; continue; }
    const para = [];
    for (; i < lines.length && lines[i].trim() && !/^(#|```|\||\s*[-*]\s)/.test(lines[i]); i++) para.push(lines[i]);
    html += `<p>${inline(para.join(' '))}</p>`;
  }
  return html;
}

async function loadDesign() {
  const [readme, notes] = await Promise.all(['SIMULATION_README.md', 'flowchart_notes.md'].map((f) => fetch(f).then((r) => r.text())));
  $('readme').innerHTML = markdown(readme);
  $('notes').innerHTML = markdown(notes);
  try {
    const fid = await getJSON('data/fidelity.json');
    $('fidelity-note').textContent = `Fidelity: the in-browser engine (Python ${fid.pyodide_python}, Pyodide ${fid.pyodide}) was run against CPython ${fid.cpython} on ${fid.cases.length} configurations; ${fid.summary}`;
  } catch { $('fidelity-note').textContent = ''; }
}

loadSaved().catch((e) => { $('saved-command').textContent = 'Saved results could not be loaded: ' + e.message; });
loadDesign().catch(() => {});
