#!/usr/bin/env python3
"""Run implemented C suites and audit coverage/provenance without claiming full parity."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SUITES = ('tokens', 'platform', 'boot', 'keys', 'key_dispatch', 'key_wait', 'cursor', 'editor', 'editor_construct', 'input_codec', 'numeric', 'numeric_transcend', 'numeric_power', 'numeric_root', 'numeric_logbase', 'combinatorics', 'complex', 'complex_angles', 'complex_round', 'stats', 'stats_cache', 'stats_normal', 'trig', 'trig_math', 'trig_inverse', 'trig_hyperbolic', 'math_context', 'render', 'format', 'format_base', 'format_budget', 'eval', 'cli', 'safety')


def audit():
    scope = json.loads((ROOT / 'csrc/scope.json').read_text())
    issues = []
    results = {}
    for name in SUITES:
        path = ROOT / 'analysis/c-verification' / (name + '.json')
        if not path.exists():
            issues.append(f'{name}: no canonical verification report'); continue
        report = json.loads(path.read_text())
        if report.get('status') != 'pass': issues.append(f'{name}: report does not pass')
        inputs = report.get('tested_inputs_sha256', {})
        if not inputs: issues.append(f'{name}: missing tested-source hashes')
        for file, digest in inputs.items():
            p = ROOT / file
            if not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest() != digest:
                issues.append(f'{name}: changed or missing tested input {file}')
        cases = report.get('cases', report.get('total_cases', report.get('checks_total', 0)))
        results[name] = {'status': report.get('status'), 'cases': cases,
                         'pinned_inputs': len(inputs)}
    for requirement in scope['requirements']:
        if 'manifest' in requirement and not (ROOT / 'csrc' / requirement['manifest']).exists():
            issues.append(f"{requirement['id']}: missing implementation manifest")
    # Reject an accidental link or include of the original execution oracle.
    for p in (ROOT / 'csrc').rglob('*'):
        if p.suffix not in ('.c', '.h') or p.name == 'fx_rom_data.c': continue
        source = p.read_text()
        for forbidden in ('harness_run(', 'harness_init(', 'SimU8/', 'nxu8/machine'):
            if forbidden in source:
                issues.append(f'original execution dependency in {p.relative_to(ROOT)}: {forbidden}')
    requirements_complete = all(r['status'] == 'complete' for r in scope['requirements'])
    if scope['complete'] and not requirements_complete:
        issues.append('Completion flag contradicts pending requirements')
    result = {'implemented_subset_verified': not issues, 'full_firmware_complete': scope['complete'],
              'suites': results, 'total_reported_cases': sum(r['cases'] for r in results.values()),
              'requirements': [{k: r[k] for k in ('id', 'status')} for r in scope['requirements']],
              'issues': issues,
              'limitation': 'Routine-level finite checks and a partial expression pipeline. This does not establish full firmware or reset/key-sequence equivalence.'}
    out = ROOT / 'analysis/c-verification/aggregate.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    return not issues


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--audit-only', action='store_true', help='Validate existing reports without running tests')
    args = ap.parse_args()
    if not args.audit_only:
        subprocess.run(['cmake', '-S', 'csrc', '-B', 'analysis/build/c-port',
                        '-DCMAKE_BUILD_TYPE=Release'], cwd=ROOT, check=True)
        subprocess.run(['cmake', '--build', 'analysis/build/c-port', '-j4'], cwd=ROOT, check=True)
        for suite in SUITES:
            subprocess.run([sys.executable, str(ROOT / 'tools' / f'test_{suite}_c.py')],
                           cwd=ROOT, check=True)
    return 0 if audit() else 1


if __name__ == '__main__': raise SystemExit(main())
