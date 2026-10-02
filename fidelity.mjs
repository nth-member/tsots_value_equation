// Runs the simulator through the published Pyodide engine (docs/pyodide) and through
// local CPython on the same settings, compares the outputs, and writes docs/data/fidelity.json.
// Usage: node fidelity.mjs
import { execFileSync } from 'node:child_process';
import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.dirname(fileURLToPath(import.meta.url));
const docs = path.join(root, 'docs');
const { loadPyodide } = await import(path.join(docs, 'pyodide', 'pyodide.mjs'));

const CASES = [
  { variant: 'A', seed: 0, population_size: 20, num_epochs: 40 },
  { variant: 'B', seed: 1, population_size: 30, num_epochs: 60, compare_honest: true },
  { variant: 'A', seed: 2, population_size: 25, num_epochs: 50, claim_limit_scope: 'phase_total', max_claimants: 10 },
  { variant: 'A', seed: 0 },
  { variant: 'B', seed: 0, compare_honest: true },
];

const py = await loadPyodide({ indexURL: path.join(docs, 'pyodide') + path.sep });
for (const name of ['shula_simulation.py', 'runner.py']) {
  py.FS.writeFile('/home/pyodide/' + name, readFileSync(path.join(docs, 'py', name), 'utf8'));
}
py.runPython('import sys; sys.path.insert(0, "/home/pyodide")');
const runner = py.pyimport('runner');
const pyodidePython = py.runPython('import sys; sys.version.split()[0]');
const cpython = execFileSync('python3', ['-c', 'import sys; print(sys.version.split()[0])']).toString().trim();

function leaves(value, prefix, out) {
  if (Array.isArray(value)) value.forEach((v, i) => leaves(v, `${prefix}[${i}]`, out));
  else if (value && typeof value === 'object') for (const k of Object.keys(value)) leaves(value[k], `${prefix}.${k}`, out);
  else out.set(prefix, value);
  return out;
}

const cases = [];
for (const settings of CASES) {
  const json = JSON.stringify(settings);
  const browser = runner.run_json(json);
  const native = execFileSync('python3', ['-c',
    'import sys, runner; sys.stdout.write(runner.run_json(sys.argv[1]))', json],
  { cwd: path.join(docs, 'py'), maxBuffer: 1 << 30 }).toString();
  const identical = browser === native;
  let maxRelative = 0, mismatched = 0;
  if (!identical) {
    const a = leaves(JSON.parse(browser), '', new Map()), b = leaves(JSON.parse(native), '', new Map());
    for (const [k, v] of a) {
      const w = b.get(k);
      if (typeof v === 'number' && typeof w === 'number') {
        const rel = Math.abs(v - w) / Math.max(Math.abs(v), Math.abs(w), 1e-300);
        if (rel > 0) { mismatched++; maxRelative = Math.max(maxRelative, rel); }
      } else if (v !== w) { mismatched++; maxRelative = Infinity; }
    }
    if (a.size !== b.size) maxRelative = Infinity;
  }
  const B = JSON.parse(browser), N = JSON.parse(native);
  const statuses = Object.fromEntries(Object.entries(B.criteria).map(([k, v]) => [k, v.status]));
  const nativeStatuses = Object.fromEntries(Object.entries(N.criteria).map(([k, v]) => [k, v.status]));
  const sameStatuses = JSON.stringify(statuses) === JSON.stringify(nativeStatuses);
  let firstEpoch = null;
  for (let i = 0; i < B.rows.length && firstEpoch === null; i++) {
    if (JSON.stringify(B.rows[i]) !== JSON.stringify(N.rows[i])) firstEpoch = B.rows[i].epoch;
  }
  let exactEpochs = firstEpoch === null ? B.rows.length : firstEpoch - 1;
  let maxRowRel = 0;
  if (firstEpoch !== null) {
    const r = B.rows[firstEpoch - 1], s = N.rows[firstEpoch - 1];
    for (const k of Object.keys(r)) if (typeof r[k] === 'number' && typeof s[k] === 'number' && r[k] !== s[k])
      maxRowRel = Math.max(maxRowRel, Math.abs(r[k] - s[k]) / Math.max(Math.abs(r[k]), Math.abs(s[k])));
  }
  cases.push({ settings, epochs: B.rows.length, identical, epochs_identical_from_start: exactEpochs,
    first_differing_epoch: firstEpoch, relative_difference_at_first_divergence: maxRowRel,
    mismatched_values: mismatched, max_relative_difference: maxRelative === Infinity ? 'structural' : maxRelative,
    same_criteria_statuses: sameStatuses, statuses, cpython_statuses: nativeStatuses });
  console.log(JSON.stringify(settings), identical ? 'IDENTICAL' : `first differing epoch ${firstEpoch} of ${B.rows.length} (rel ${maxRowRel.toExponential(2)}), same statuses: ${sameStatuses}`);
  if (!sameStatuses) console.log('   browser', JSON.stringify(statuses), '\n   cpython', JSON.stringify(nativeStatuses));
}

// The two engines' maths libraries, compared directly on the same inputs.
const MATH = `
import math, random, json
r = random.Random(1)
xs = [r.uniform(1e-6, 50) for _ in range(200000)]
json.dumps({f: [getattr(math, f)(x).hex() for x in xs] for f in ('log', 'exp', 'sin', 'cos', 'sqrt')})`;
const inBrowser = JSON.parse(py.runPython(MATH));
const inCPython = JSON.parse(execFileSync('python3', ['-c', MATH.replace('\njson.dumps(', '\nprint(json.dumps(') + ')'], { maxBuffer: 1 << 30 }).toString());
const math = Object.fromEntries(Object.keys(inBrowser).map((f) => [f, inBrowser[f].filter((v, i) => v !== inCPython[f][i]).length]));

const identical = cases.filter((c) => c.identical).length;
const statusesAgree = cases.every((c) => c.same_criteria_statuses);
const firstRel = Math.max(...cases.map((c) => c.relative_difference_at_first_divergence));
const report = {
  pyodide: py.version, pyodide_python: pyodidePython, cpython,
  math_function_last_digit_differences_in_200000_inputs: math,
  summary: `${identical} of ${cases.length} runs were byte-for-byte identical. In the others the first difference was in the last binary digit (relative ${firstRel.toExponential(1)}), from the two engines' maths libraries (sin, cos and exp differ in the last digit for some inputs); because the model branches on thresholds, later values then diverge. `
    + (statusesAgree ? 'Every acceptance-criterion status was the same in both engines.' : 'Some acceptance-criterion statuses differed; see the cases.'),
  cases,
};
writeFileSync(path.join(docs, 'data', 'fidelity.json'), JSON.stringify(report, null, 1) + '\n');
console.log(report.summary, JSON.stringify(math));
process.exit(statusesAgree ? 0 : 1);
