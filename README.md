# TSOTS value equation

A synthetic, reproducible simulation of the value-chain equation as a currency, the Shula:

```text
TSOTS ≡ ∂(M·V) − ∂(P·O) = ΔG + ΔA + ΔI
```

Site: https://nth-member.github.io/tsots_value_equation/

The simulator tests accounting and scenarios with synthetic people and acts. A run that passes its criteria does not establish that the mechanism works in practice.

## What the site does

| Tab | Contents |
| --- | --- |
| Saved results | Acceptance criteria, measured values and epoch series for six main runs (variants A and B, seeds 0–2) and their matched honest-service references |
| Run in the browser | The unchanged `shula_simulation.py` running in Pyodide (Python compiled to WebAssembly) in a Web Worker; every `Config` field can be set; results can be downloaded |
| Design and assumptions | The corrected flowchart, the simulator's README and the correction notes |

Nothing is sent to a server. The page is static and self-contained; Pyodide's core files are included in `docs/pyodide/`.

## Files

| Path | Purpose |
| --- | --- |
| `docs/index.html`, `docs/app.js` | The page |
| `docs/worker.js` | Loads Pyodide and runs the simulator away from the page's main thread |
| `docs/py/shula_simulation.py` | The simulator, unchanged |
| `docs/py/test_shula_simulation.py` | Its regression tests |
| `docs/py/runner.py` | Bridge: coerces settings to the types `Config` declares, runs the simulator, returns JSON |
| `docs/data/` | Saved results regenerated from the published simulator, and `fidelity.json` |
| `docs/pyodide/` | Pyodide 0.28 core (Python 3.13) |
| `build.py` | Copies the simulator and documents into `docs/` and regenerates the saved results; unchanged inputs rebuild to identical files |
| `fidelity.mjs` | Runs the simulator in the published Pyodide engine and in CPython on the same settings and compares the outputs |

## Rebuild and check

```bash
python3 build.py            # simulator, documents and saved results into docs/
node fidelity.mjs           # browser engine against CPython; writes docs/data/fidelity.json
(cd docs/py && python3 -m unittest -v test_shula_simulation)   # the simulator's regression tests
(cd docs && python3 -m http.server 8000)                        # view at http://localhost:8000/
```

`build.py` reads the simulator's source folder from an untracked file, `.source`.

## Fidelity

The browser engine and CPython run the same code. Short runs are byte-for-byte identical. In longer runs the first difference appears in the last binary digit (a relative difference near 10⁻¹⁶), because the two engines' maths libraries round `sin`, `cos` and `exp` differently for some inputs; as the model branches on thresholds, later values then diverge. In every compared configuration each acceptance-criterion status was the same in both engines. `docs/data/fidelity.json` records the measurements.
