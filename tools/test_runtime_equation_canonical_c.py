#!/usr/bin/env python3
"""Publish a guarded, four-run runtime/EQN report. GPL-3.0-only.

The unchanged single-pass verifier owns execution and observations. This driver
owns workload selection, cross-build comparison, provenance and publication.
Default execution runs both complete and retained-prefix corpora at O2 and O3.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from c_build_inputs import implementation_inputs
from c_verification import write_report

TEST = 'tools/test_runtime_equation_canonical_c.py'
WORKER = 'tools/test_runtime_equation_c.py'
REPORT = 'analysis/c-verification/runtime_equation_canonical.json'
SUPPORT = ('tools/runtime_equation_support/adapter.c',
           'tools/runtime_equation_support/native.c')
FIXTURES = {
    'success': 'analysis/native-fixtures/runtime-equation/inputs.json',
    'prefix': 'analysis/native-fixtures/runtime-equation/prefix-inputs.json',
}
FROZEN_HASHES = {
    WORKER: 'cb7d78bf957285180389ca3b95892cdf6d54fabba74d39a290a8ba4f4ab10556',
    SUPPORT[0]: 'efd3886a67c48f75879d4d78a0a0ca2adde4fa1a1315988a055e8612d42eb4da',
    SUPPORT[1]: '2a3791de2fbb3fe2ab96ddf37c8f6ca328705f66c53014e05d31857a550306b2',
    FIXTURES['success']: '2f988fa96719a2bfb590369347833a26c9bd08e2a372f2a1922d2ba0970175d3',
    FIXTURES['prefix']: 'f3eed7afb7b4110da2d5242f76ffaddb4407260ce23f5e30dcc136dbbedefee6',
}
EXPECTED = {
    'success': dict(sequences=4, observations=554, checks=1799, poll_count=82),
    'prefix': dict(sequences=54, observations=7938, checks=25325, poll_count=767),
}
ADMISSION_CONTROLS = ['mode', 'selector-zero', 'selector-polynomial', 'screen',
                      'state', 'key', 'busy', 'null-platform', 'null-ram',
                      'null-action', 'null-result']


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def assert_stable(pins):
    changed = [str(path) for path, expected in pins.items()
               if not path.is_file() or digest(path) != expected]
    if changed:
        raise RuntimeError('Tested inputs changed during execution: ' + ', '.join(changed))


def parse_arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--optimization', choices=('O2', 'O3'))
    parser.add_argument('--prefix-controls', action='store_true',
                        help='Run only the prefix corpus; requires private output')
    parser.add_argument('--candidate-root', type=Path,
                        help='Run a private source/fixture tree with its own frozen worker')
    output = parser.add_mutually_exclusive_group()
    output.add_argument('--private-report', type=Path)
    output.add_argument('--no-report', action='store_true')
    args = parser.parse_args(argv)
    if args.candidate_root and not args.private_report:
        parser.error('--candidate-root requires --private-report')
    if (args.optimization or args.prefix_controls) and not (args.private_report or args.no_report):
        parser.error('Single-optimization/corpus runs require --private-report or --no-report')
    candidate = args.candidate_root.resolve() if args.candidate_root else ROOT
    if args.private_report:
        private = args.private_report.resolve()
        for root in (ROOT, candidate):
            if private.is_relative_to((root / 'analysis/c-verification').resolve()):
                parser.error('Private reports cannot replace canonical verification reports')
        args.private_report = private
    return args, candidate


def capture_inputs(candidate, canonical):
    cmake_path = candidate / 'csrc/CMakeLists.txt'
    cmake_bytes = cmake_path.read_bytes()
    sources = ['csrc/' + name for name in re.findall(
        r'(?<![\w/])([\w/]+\.c)(?!\w)',
        cmake_bytes.decode().split('target_include_directories')[0])]
    if len(sources) != len(set(sources)):
        raise ValueError('Duplicate CMake source inputs')
    closure = implementation_inputs(candidate, sources)
    common = [candidate / name for name in closure]
    common += [cmake_path, *[candidate / name for name in SUPPORT], candidate / WORKER,
               candidate / 'tools/c_build_inputs.py', candidate / 'tools/nxu8/machine.py',
               candidate / 'tools/nxu8/harness.c', candidate / 'tools/nxu8/vendor/SimU8/core.c',
               candidate / 'firmware/fx-991es-plus-c-ver4.bin']
    common += sorted((candidate / 'tools/nxu8/vendor/SimU8').glob('*.h'))
    paths = common + [candidate / name for name in FIXTURES.values()]
    paths += [Path(__file__).resolve(), ROOT / 'tools/c_build_inputs.py',
              ROOT / 'tools/c_verification.py']
    pins = {path.resolve(): digest(path) for path in paths}
    if pins[cmake_path] != hashlib.sha256(cmake_bytes).hexdigest():
        raise RuntimeError('Parsed CMake changed before input capture')
    # The worker is immutable in private runs too. Fixtures/support may differ
    # only in an explicitly private candidate tree, never in canonical evidence.
    frozen_names = FROZEN_HASHES if canonical else {WORKER: FROZEN_HASHES[WORKER]}
    for name, expected in frozen_names.items():
        if pins[candidate / name] != expected:
            raise RuntimeError('Frozen input changed: ' + name)
    assert_stable(pins)
    if implementation_inputs(candidate, sources) != closure:
        raise RuntimeError('Implementation closure changed before execution')
    return sources, closure, common, pins


def validate_proof(report, corpus, optimization, expected_pins):
    if report.get('status') != 'pass-with-numeric-residuals' or report.get('failures'):
        raise AssertionError('Single-pass verifier did not pass')
    if report.get('optimization') != optimization or report.get('prefix_controls') != (corpus == 'prefix'):
        raise AssertionError('Proof workload identity differs from requested run')
    if report.get('full_firmware_complete') is not False:
        raise AssertionError('Unexpected firmware completeness claim')
    if report.get('poll_publication_complete') is not True or report.get('poll_snapshot_persistent_gap_count') != 0:
        raise AssertionError('Persistent timer snapshot gap')
    for key, value in EXPECTED[corpus].items():
        if report.get(key) != value:
            raise AssertionError(f'{corpus}: {key} differs from complete workload ({value})')
    if len(report.get('rows', [])) != report['observations'] or len(report.get('poll_rows', [])) != report['poll_count']:
        raise AssertionError('Proof observation counts are inconsistent')
    if report.get('invalid_admission_controls') != ADMISSION_CONTROLS:
        raise AssertionError('Missing or reordered no-write admission controls')
    if report.get('source_changes') or report.get('source_pins') != expected_pins:
        raise AssertionError('Worker tested-input closure differs from captured inputs')
    for row in report['rows']:
        if (row['unexpected'] or row['semantic'] or row['native_status'] != 100 or
                row['callback'] != row['native_callback']):
            raise AssertionError('Nonmatching checkpoint in passing proof')
    if any(row['persistent_differences'] for row in report['poll_rows']):
        raise AssertionError('Nonmatching persistent timer snapshot in passing proof')


def compare_optimizations(runs, corpus):
    for key in ('rows', 'poll_rows', 'invalid_admission_controls', 'scope'):
        if runs[corpus, 'O2'][key] != runs[corpus, 'O3'][key]:
            raise AssertionError(f'{corpus}: {key} differs between O2 and O3')


def run_worker(candidate, corpus, optimization, common, pins, log_directory):
    build_root = candidate / 'analysis/build/runtime-equation'
    before = set(build_root.glob('*/' + optimization + '/proof.json'))
    command = [sys.executable, str(candidate / WORKER), '--optimization', optimization]
    if corpus == 'prefix':
        command.append('--prefix-controls')
    print(f'Running {corpus} corpus at {optimization}', flush=True)
    result = subprocess.run(command, cwd=candidate, check=False, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (log_directory / f'{corpus}-{optimization}.log').write_text(result.stdout)
    result.check_returncode()
    matches = re.findall(r'^REPORT (.+) polls (\d+) snapshot-gaps (\d+)$', result.stdout, re.MULTILINE)
    if len(matches) != 1:
        raise RuntimeError('Worker did not identify exactly one fresh proof')
    proof = Path(matches[0][0]).resolve()
    if (not proof.is_relative_to(build_root.resolve()) or proof in before or
            proof.parent.name != optimization or proof.name != 'proof.json'):
        raise RuntimeError('Worker output is not a fresh isolated proof')
    proof_hash = digest(proof)
    report = json.loads(proof.read_text())
    expected_paths = set(common + [candidate / FIXTURES[corpus]])
    expected_pins = {str(path): pins[path] for path in expected_paths}
    validate_proof(report, corpus, optimization, expected_pins)
    if [int(matches[0][1]), int(matches[0][2])] != [report['poll_count'], 0]:
        raise AssertionError('Worker summary differs from its proof')
    archive = proof.parent / 'observations.jsonl.gz'
    artifact_pins = {proof: proof_hash, archive: digest(archive)}
    expected_artifacts = {proof.parent / 'candidate.so', proof.parent / 'native/nxu8-harness.so'}
    if set(map(Path, report.get('artifacts', {}))) != expected_artifacts:
        raise AssertionError('Unexpected compiled artifact set')
    artifact_pins.update({Path(name): value for name, value in report['artifacts'].items()})
    assert_stable(pins)
    assert_stable(artifact_pins)
    print(f'Passed {corpus} {optimization}: {report["observations"]} checkpoints, '
          f'{report["checks"]} checks, {report["poll_count"]} persistent timer snapshots', flush=True)
    return report, proof, artifact_pins


def summarize(report, proof, artifacts, candidate):
    return {
        'corpus': 'prefix' if report['prefix_controls'] else 'success',
        'optimization': report['optimization'],
        'sequences': report['sequences'],
        'checkpoints': report['observations'],
        'checks': report['checks'],
        'persistent_timer_snapshots': report['poll_count'],
        'source_pin_count': len(report['source_pins']),
        'invalid_admission_controls': report['invalid_admission_controls'],
        'checkpoint_residual_observations': sum(bool(row['residuals']) for row in report['rows']),
        'known_8001_residual_observations': sum(any(value[0] == 0x8001 for value in row['residuals']) for row in report['rows']),
        'proof': str(proof.relative_to(candidate)),
        'proof_artifacts_sha256': {str(path.relative_to(candidate)): value for path, value in artifacts.items()},
        'scope': report['scope'],
    }


def main(argv=None):
    args, candidate = parse_arguments(argv)
    canonical = not (args.private_report or args.no_report)
    sources, closure, common, pins = capture_inputs(candidate, canonical)
    optimizations = (args.optimization,) if args.optimization else ('O2', 'O3')
    corpora = ('prefix',) if args.prefix_controls else ('success', 'prefix')
    log_directory = candidate / 'analysis/build/runtime-equation-canonical' / uuid.uuid4().hex
    log_directory.mkdir(parents=True)
    runs = {}
    all_artifacts = {}
    summaries = []
    for corpus in corpora:
        for optimization in optimizations:
            report, proof, artifacts = run_worker(candidate, corpus, optimization, common, pins, log_directory)
            runs[corpus, optimization] = report
            all_artifacts.update(artifacts)
            summaries.append(summarize(report, proof, artifacts, candidate))
        if len(optimizations) == 2:
            compare_optimizations(runs, corpus)
    assert_stable(pins)
    assert_stable(all_artifacts)
    if implementation_inputs(candidate, sources) != closure:
        raise RuntimeError('Implementation closure changed during execution')
    result = {
        'status': 'pass', 'full_firmware_complete': False,
        'cases': sum(EXPECTED[corpus]['sequences'] for corpus in corpora),
        'count_units': 'cases are distinct physical input recipes; counts per optimization include each selected corpus once',
        'optimizations': list(optimizations), 'corpora': list(corpora),
        'checkpoints_per_optimization': sum(EXPECTED[corpus]['observations'] for corpus in corpora),
        'checks_per_optimization': sum(EXPECTED[corpus]['checks'] for corpus in corpora),
        'persistent_timer_snapshots_per_optimization': sum(EXPECTED[corpus]['poll_count'] for corpus in corpora),
        'invalid_admission_controls_per_corpus': 11,
        'invalid_admission_control_executions_per_optimization': 11 * len(corpora),
        'persistent_timer_snapshot_gaps': 0,
        'optimization_reports': summaries,
        'limits': [
            'The four success recipes complete boot, coefficient entry, linear solve, root replay and return.',
            'The 54 prefix recipes retain the pending typed EQN body before original E884; error UI continuation is incomplete.',
            'Numeric RAM 8000..80DB, inactive linalg RAM 8640..87CF and individually witnessed original frame bytes are explicit retained residuals.',
            'Finite recipe checks do not establish full firmware equivalence.',
        ],
    }
    if args.private_report:
        result['tested_inputs_sha256'] = {str(path): value for path, value in pins.items()}
        args.private_report.parent.mkdir(parents=True, exist_ok=True)
        args.private_report.write_text(json.dumps(result, indent=2) + '\n')
    elif canonical:
        declared = [str(path.relative_to(ROOT)) for path in pins]
        result = write_report(REPORT, result, declared, TEST)
    print(json.dumps({key: result[key] for key in ('status', 'cases', 'optimizations',
          'corpora', 'checkpoints_per_optimization', 'checks_per_optimization',
          'persistent_timer_snapshots_per_optimization')}), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
