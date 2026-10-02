#!/usr/bin/env python3
"""Build docs/ from the simulator's source folder.

The source folder's path is read from the untracked file `.source`, so no
local path is published. The saved scenarios are regenerated here with the
command given in SIMULATION_README.md, so the published results always come
from the published simulator. Unchanged inputs rebuild to identical files.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / 'docs'
SOURCE = Path((ROOT / '.source').read_text().strip()).expanduser()
RESULTS = ROOT / '.results'

FILES = {
    'shula_simulation.py': 'py/shula_simulation.py',
    'test_shula_simulation.py': 'py/test_shula_simulation.py',
    'SIMULATION_README.md': 'SIMULATION_README.md',
    'simulation_flowchart_corrected.pdf': 'flowchart.pdf',
    'simulation_flowchart_correction_notes.md': 'flowchart_notes.md',
}
RUN_FILES = ('config.json', 'summary.json', 'epochs.csv')
README_COMMAND = ['--variant', 'both', '--epochs', '200', '--population', '100',
                  '--seeds', '0,1,2', '--compare-honest']


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_bytes() != data:
        path.write_bytes(data)
        print('wrote', path.relative_to(ROOT))


def main():
    for name, target in FILES.items():
        write(DOCS / target, (SOURCE / name).read_bytes())

    simulator = DOCS / 'py' / 'shula_simulation.py'
    digest = hashlib.sha256(simulator.read_bytes()).hexdigest()
    stamp = RESULTS / 'simulator.sha256'
    if not stamp.exists() or stamp.read_text() != digest:
        subprocess.run([sys.executable, str(simulator), *README_COMMAND, '--output', str(RESULTS)],
                       check=True, cwd=DOCS / 'py')
        stamp.write_text(digest)

    runs = sorted(p.name for p in RESULTS.iterdir() if p.is_dir())
    for run in runs:
        for name in RUN_FILES:
            write(DOCS / 'data' / 'runs' / run / name, (RESULTS / run / name).read_bytes())
    for name in ('report.md', 'comparison.json'):
        write(DOCS / 'data' / name, (RESULTS / name).read_bytes())

    manifest = dict(runs=runs, main=[r for r in runs if not r.endswith('_honest')],
                    simulator_sha256=digest, command='python3 shula_simulation.py ' + ' '.join(README_COMMAND))
    write(DOCS / 'data' / 'manifest.json', (json.dumps(manifest, indent=1, sort_keys=True) + '\n').encode())


if __name__ == '__main__':
    main()
