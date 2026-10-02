// Runs shula_simulation.py, unchanged, in Pyodide, away from the page's main thread.
import { loadPyodide } from './pyodide/pyodide.mjs';

let runner;
const ready = (async () => {
  const py = await loadPyodide({ indexURL: new URL('./pyodide/', import.meta.url).href });
  for (const name of ['shula_simulation.py', 'runner.py']) {
    const response = await fetch(new URL('./py/' + name, import.meta.url));
    if (!response.ok) throw new Error('Could not load ' + name);
    py.FS.writeFile('/home/pyodide/' + name, await response.text());
  }
  py.runPython('import sys; sys.path.insert(0, "/home/pyodide")');
  runner = py.pyimport('runner');
  return {
    pyodide: py.version,
    python: py.runPython('import sys; sys.version.split()[0]'),
    config: JSON.parse(runner.describe_json()),
  };
})();

ready.then(
  (info) => postMessage({ type: 'ready', ...info }),
  (error) => postMessage({ type: 'boot-error', error: String((error && error.message) || error) }),
);

function lastLine(error) {
  const text = String((error && error.message) || error).trim().split('\n');
  return text[text.length - 1];
}

onmessage = async ({ data }) => {
  await ready;
  if (data.type !== 'run') return;
  const start = performance.now();
  try {
    const json = runner.run_json(JSON.stringify(data.settings));
    postMessage({ type: 'result', json, seconds: (performance.now() - start) / 1000 });
  } catch (error) {
    postMessage({ type: 'run-error', error: lastLine(error) });
  }
};
