"""Real prebuild publication/schema refusals; changes touch owned copies only."""
import json
from pathlib import Path
import shutil
import subprocess
import sys


def run(tool, fixture, observed, output):
    root = output / 'publication-controls'
    (root / 'tools').mkdir(parents=True)
    installed = root / 'tools/test_verify_workflow_c.py'
    shutil.copy2(tool, installed)
    inputs = root / 'analysis/native-fixtures/verify-workflow'
    native = root / 'analysis/native-observations/verify-workflow'
    shutil.copytree(fixture, inputs)
    shutil.copytree(observed, native)
    original = (inputs / 'relation-inputs.json').read_bytes()
    rows = []

    def refuse(label, arguments=(), optimized=False, message=None):
        build = root / ('must-not-build-' + label)
        canonical = root / 'analysis/c-verification/verify_workflow.json'
        command = [sys.executable, *(['-O'] if optimized else []), str(installed),
                   '--build-dir', str(build), *map(str, arguments)]
        result = subprocess.run(command, text=True, capture_output=True)
        ok = result.returncode != 0 and not build.exists() and not canonical.exists()
        if message is not None: ok &= message in result.stderr
        rows.append({'label': label, 'pass': bool(ok), 'command': command,
            'returncode': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr,
            'build_created': build.exists(), 'canonical_created': canonical.exists()})

    refusal = 'Canonical publication requires'
    refuse('optimization', ('--optimization', 'O2'), message=refusal)
    refuse('source-root', ('--source-root', root / 'other-source'), message=refusal)
    custom = root / 'custom-fixtures'; shutil.copytree(inputs, custom)
    refuse('custom-fixture-location', ('--fixture-dir', custom), message=refusal)
    custom_native = root / 'custom-observations'; shutil.copytree(native, custom_native)
    refuse('custom-observation-location', ('--observations-dir', custom_native), message=refusal)
    reduced = json.loads(original); reduced['cases'].pop()
    (inputs / 'relation-inputs.json').write_text(json.dumps(reduced))
    refuse('canonical-reduced-corpus', message=refusal)
    refuse('private-reduced-corpus', ('--no-report',), message='Expected complete384')
    (inputs / 'relation-inputs.json').write_bytes(original)
    for label, mutate in (
        ('float-token', lambda row: row.update(token=float(row['token']))),
        ('float-entry', lambda row: row.update(entry=float(row['entry']))),
        ('unrecognized-token-null-entry', lambda row: row.update(token='invalid', entry=None)),
        ('expected-output-field', lambda row: row.update(expected=True)),
    ):
        value = json.loads(original); mutate(value['cases'][0])
        (inputs / 'relation-inputs.json').write_text(json.dumps(value))
        refuse(label, ('--no-report',))
        (inputs / 'relation-inputs.json').write_bytes(original)
    main_original = (inputs / 'inputs.json').read_bytes()
    for label, mutate in (
        ('word-crosses-ram', lambda data: data['initial_words'].update(ffff=1)),
        ('recovery-string', lambda data: data['cases'][0]['steps'][0].update(recovery_keys='')),
        ('oversized-initial-expression', lambda data: data.update(initial_expression='31' * 100)),
        ('unknown-main-scenario', lambda data: data['cases'][0].update(id='unknown-scenario')),
    ):
        value = json.loads(main_original); mutate(value)
        (inputs / 'inputs.json').write_text(json.dumps(value))
        refuse(label, ('--no-report',))
        (inputs / 'inputs.json').write_bytes(main_original)
    refuse('python-optimized', optimized=True, message='Python optimization is unsupported')
    (output / 'publication-controls.json').write_text(json.dumps(rows, indent=2) + '\n')
    return rows
