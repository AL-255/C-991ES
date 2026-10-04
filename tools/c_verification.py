"""Reproducibility metadata shared by high-level C differential suites."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# Capture before a suite compiles or runs. Other agents may edit shared files;
# hashing only at report publication could attribute old test results to new
# code. Refuse publication when a declared input changed during the run.
_BASELINE = {}
for directory in ('csrc', 'tools', 'firmware', 'analysis'):
    for path in (ROOT / directory).rglob('*'):
        if directory == 'analysis' and path.suffix != '.json': continue
        if path.is_file() and (path.suffix in ('.c', '.h', '.py', '.json', '.bin') or
                               path.name == 'CMakeLists.txt'):
            _BASELINE[str(path.relative_to(ROOT))] = _digest(path)


def write_report(path, report, sources, test):
    """Pin tested implementation and oracle inputs; never infer completeness."""
    if report.get('failures') or report.get('mismatches') or report.get('status') in ('fail', 'failed'):
        raise ValueError('A failing suite cannot publish a passing verification report')
    dependencies = [Path(p) for p in sources] + [Path(test), Path('tools/nxu8/machine.py'),
                    Path('tools/nxu8/harness.c'), Path('tools/nxu8/vendor/SimU8/core.c'),
                    Path('firmware/fx-991es-plus-c-ver4.bin')]
    dependencies += [p.relative_to(ROOT) for p in (ROOT / 'tools/nxu8/vendor/SimU8').glob('*.h')]
    report = dict(report)
    hashes = {}
    for p in dependencies:
        key = str(p)
        current = _digest(ROOT / p)
        if key not in _BASELINE or current != _BASELINE[key]:
            raise RuntimeError(f'Tested input changed during this run: {key}; rerun this suite')
        hashes[key] = current
    report['tested_inputs_sha256'] = hashes
    report['status'] = 'pass'
    report['full_firmware_complete'] = False
    target = Path(path)
    if not target.is_absolute(): target = ROOT / target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + '\n')
    return report
