#!/usr/bin/env python3
"""Publish both complete runtime-owned EQN/TABLE builds. GPL-3.0-only.

The unchanged single-pass verifier owns execution and observations. This driver
owns workload selection, cross-build comparison, provenance and publication.
Default execution preserves all 89 input recipes at O2 and O3. All 54 historical
error/cancellation prefixes continue through actual coefficient-input recovery.
"""
import argparse
import base64
from collections import Counter
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from c_build_inputs import implementation_inputs
from c_verification import write_report

TEST = 'tools/test_runtime_owned_error_canonical_c.py'
WORKER = 'tools/test_runtime_owned_error_private.py'
REPORT = 'analysis/c-verification/runtime_owned_error_canonical.json'
SUPPORT = ('tools/runtime_owned_support/adapter.c',
           'tools/runtime_owned_support/native.c')
FIXTURE = 'analysis/native-fixtures/runtime-owned-error/inputs.json'
FROZEN_HASHES = {
    WORKER: '87f1f1f15efa9fef08a4635b3c7b9df54bf1e2655c12d240b564787851f8b4bb',
    SUPPORT[0]: 'c824a666882a9fb1ed70804f8c2ff7f667549a171a4fff468dafa51d8617bd33',
    SUPPORT[1]: '2a3791de2fbb3fe2ab96ddf37c8f6ca328705f66c53014e05d31857a550306b2',
    FIXTURE: '3c97ffaff9d169a0757820e067274dfc1097c0830449e630be1421b11d8846d2',
}
EXPECTED = {
    'equation': dict(sequences=4, observations=554, checks=1719, poll_count=82),
    'error': dict(sequences=82, observations=12012, checks=36465, poll_count=1131),
    'table': dict(sequences=3, observations=372, checks=1172, poll_count=10),
    'all': dict(sequences=89, observations=12938, checks=39250, poll_count=1223),
}
COHORT_COUNTS = {'equation': 4, 'table': 3, 'error': 82}
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
    if sys.flags.optimize:
        raise RuntimeError('Optimized Python disables worker assertions; run without -O or PYTHONOPTIMIZE')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--optimization', choices=('O2', 'O3'))
    parser.add_argument('--corpus', choices=tuple(EXPECTED), default='all',
                        help='Default all 89 recipes; a single corpus requires private output')
    parser.add_argument('--candidate-root', type=Path,
                        help='Run a private source/fixture tree with its own frozen worker')
    parser.add_argument('--build-dir', type=Path,
                        help='Private diagnostic artifact location; requires private output')
    output = parser.add_mutually_exclusive_group()
    output.add_argument('--private-report', type=Path)
    output.add_argument('--no-report', action='store_true')
    args = parser.parse_args(argv)
    if args.candidate_root and not args.private_report:
        parser.error('--candidate-root requires --private-report')
    if (args.optimization or args.corpus != 'all' or args.build_dir) and not (args.private_report or args.no_report):
        parser.error('Single-optimization/corpus runs require --private-report or --no-report')
    candidate = args.candidate_root.resolve() if args.candidate_root else ROOT
    if args.private_report:
        private = args.private_report.resolve()
        for root in (ROOT, candidate):
            if private.is_relative_to((root / 'analysis/c-verification').resolve()):
                parser.error('Private reports cannot replace canonical verification reports')
        args.private_report = private
    return args, candidate


def validate_fixture(fixture):
    if (set(fixture) != {'instruction_budget', 'basis', 'scenarios'} or
            type(fixture['instruction_budget']) is not int or fixture['instruction_budget'] != 50000000 or
            type(fixture['basis']) is not str or not fixture['basis'] or
            type(fixture['scenarios']) is not list):
        raise ValueError('Malformed input-only fixture metadata')
    scenarios = fixture['scenarios']
    if any(type(row) is not dict for row in scenarios):
        raise ValueError('Fixture scenarios must be input objects')
    if [row.get('corpus') for row in scenarios] != ['equation'] * 4 + ['table'] * 3 + ['error'] * 82:
        raise ValueError('The ordered 4 + 3 + 82 complete recipe fixture is required')
    labels = set()
    preserved = []
    variants = Counter()
    host_pairs = {256: [128, 128], 257: [64, 128], 258: [32, 128]}
    suffixes = ((0x31, 0xe6), (0xe0, 0xe6), (0xe2,), (0xe3,),
                (256, 0xe6), (257, 0xe6), (258, 0xe6))
    common = {'label', 'corpus', 'physical_tokens', 'initial_ram_zlib_base64', 'initial_ram_sha256'}
    for index, row in enumerate(scenarios):
        expected = common if row['corpus'] == 'table' else common | {'selector', 'coefficients'}
        if row['corpus'] == 'error':
            expected |= {'cancel_at', 'cancel_token_index'}
            if index >= 77:
                expected |= {'host_pairs'}
        if set(row) != expected:
            raise ValueError('Unexpected fixture field; native outcomes are not inputs')
        if type(row['label']) is not str or not row['label'] or row['label'] in labels:
            raise ValueError('Recipe labels must be distinct nonempty strings')
        labels.add(row['label'])
        seed = zlib.decompress(base64.b64decode(row['initial_ram_zlib_base64'], validate=True))
        if len(seed) != 65536 or hashlib.sha256(seed).hexdigest() != row['initial_ram_sha256']:
            raise ValueError('Invalid cold-boot RAM seed/hash')
        tokens = row['physical_tokens']
        if type(tokens) is not list or not tokens or any(type(token) is not int or not 0 <= token <= 258 for token in tokens):
            raise ValueError('Invalid physical token recipe')
        if row['corpus'] == 'table':
            if any(token > 255 for token in tokens):
                raise ValueError('Host transport labels are not ROM key tokens')
            preserved.append({key: row[key] for key in ('physical_tokens', 'initial_ram_sha256')})
            continue
        selector, coefficients = row['selector'], row['coefficients']
        if (type(selector) is not int or selector not in (1, 2) or
                type(coefficients) is not list or len(coefficients) != (selector + 1) * (selector + 2) or
                any(type(value) is not str or not value for value in coefficients)):
            raise ValueError('Invalid EQN selector/coefficient input dimensions')
        derived = [0xe4, 0x35, 0x30 + selector]
        for value in coefficients:
            derived.extend(ord(character) for character in value)
            derived.append(0xf0)
        derived.extend([0xf0] * (1 if row['corpus'] == 'error' else selector + 2))
        if row['corpus'] == 'equation' and derived != tokens:
            raise ValueError('EQN physical tokens differ from the coefficient recipe')
        normalized = {key: row[key] for key in ('selector', 'coefficients', 'physical_tokens', 'initial_ram_sha256')}
        if row['corpus'] == 'equation':
            preserved.append(normalized)
        if row['corpus'] == 'error':
            ordinal = row['cancel_at']
            maximum = 16 if selector == 1 else 34
            if type(ordinal) is not int or not 0 <= ordinal <= maximum:
                raise ValueError('Invalid cancellation ordinal')
            if type(row['cancel_token_index']) is not int or row['cancel_token_index'] != len(derived):
                raise ValueError('Cancellation token boundary differs from input prefix')
            suffix = tuple(tokens[len(derived):])
            if tokens[:len(derived)] != derived:
                raise ValueError('Error recipe changed its historical physical prefix')
            if index < 61:
                if suffix != (0xe6,):
                    raise ValueError('All 54 historical prefixes require actual AC recovery')
                normalized['cancel_at'] = ordinal
                normalized['physical_tokens'] = derived
                preserved.append(normalized)
            else:
                anchors = {(1, 1), (1, 16), (2, 1), (2, 34)}
                if (selector, ordinal) not in anchors or suffix not in suffixes:
                    raise ValueError('Unexpected ignored/cursor/export error variant')
                if index < 77 and suffix not in suffixes[:4] or index >= 77 and suffix not in suffixes[4:]:
                    raise ValueError('Error variant cohort order changed')
                variants[selector, ordinal, suffix] += 1
                reference = next((s for s in scenarios[7:61] if s['selector'] == selector and s['cancel_at'] == ordinal), None)
                if reference is None:
                    raise ValueError('Error variant lost its historical cancellation input')
                if any(row[key] != reference[key] for key in ('coefficients', 'initial_ram_sha256')):
                    raise ValueError('Variant changed its historical coefficient or RAM input')
            if index >= 77 and row['host_pairs'] != {str(suffix[0]): host_pairs[suffix[0]]}:
                raise ValueError('Host labels 256..258 require the exact explicit export pair')
    historical_digest = hashlib.sha256(json.dumps(preserved, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if historical_digest != 'fe27407971db3e2f0297a2cc478bb0ca5a06d943be6aeb8aada5f707f311f6d6':
        raise ValueError('Original 61 input seeds/keys/coefficients/cancellations were changed')
    if variants != Counter({(selector, ordinal, suffix): 1 for selector, ordinal in ((1, 1), (1, 16), (2, 1), (2, 34)) for suffix in suffixes}):
        raise ValueError('Missing or repeated ignored/cursor/export variant')
    return scenarios


def assert_no_original_execution(candidate, closure):
    forbidden = re.compile(r'\b(?:harness_run|harness_init|runtime_run_to)\s*\(|SimU8/|nxu8/machine')
    for name in closure:
        if name.endswith(('.c', '.h')) and forbidden.search((candidate / name).read_text()):
            raise RuntimeError('Original execution dependency in production input: ' + name)


def capture_inputs(candidate, canonical):
    cmake_path = candidate / 'csrc/CMakeLists.txt'
    cmake_bytes = cmake_path.read_bytes()
    sources = ['csrc/' + name for name in re.findall(
        r'(?<![\w/])([\w/]+\.c)(?!\w)',
        cmake_bytes.decode().split('target_include_directories')[0])]
    if len(sources) != len(set(sources)):
        raise ValueError('Duplicate CMake source inputs')
    closure = implementation_inputs(candidate, sources)
    fixture_bytes = (candidate / FIXTURE).read_bytes()
    fixture = json.loads(fixture_bytes)
    scenarios = validate_fixture(fixture)
    assert_no_original_execution(candidate, closure)
    common = [candidate / name for name in closure]
    common += [cmake_path, *[candidate / name for name in SUPPORT], candidate / WORKER,
               candidate / 'tools/c_build_inputs.py', candidate / 'tools/nxu8/machine.py',
               candidate / 'tools/nxu8/harness.c', candidate / 'tools/nxu8/vendor/SimU8/core.c',
               candidate / 'firmware/fx-991es-plus-c-ver4.bin']
    common += sorted((candidate / 'tools/nxu8/vendor/SimU8').glob('*.h'))
    paths = common + [candidate / FIXTURE]
    paths += [Path(__file__).resolve(), ROOT / 'tools/c_build_inputs.py',
              ROOT / 'tools/c_verification.py']
    pins = {path.resolve(): digest(path) for path in paths}
    if pins[cmake_path] != hashlib.sha256(cmake_bytes).hexdigest():
        raise RuntimeError('Parsed CMake changed before input capture')
    if pins[candidate / FIXTURE] != hashlib.sha256(fixture_bytes).hexdigest():
        raise RuntimeError('Parsed fixture changed before input capture')
    # The worker is immutable in private runs too. Fixtures/support may differ
    # only in an explicitly private candidate tree, never in canonical evidence.
    frozen_names = FROZEN_HASHES if canonical else {WORKER: FROZEN_HASHES[WORKER]}
    for name, expected in frozen_names.items():
        if pins[candidate / name] != expected:
            raise RuntimeError('Frozen input changed: ' + name)
    assert_stable(pins)
    if implementation_inputs(candidate, sources) != closure:
        raise RuntimeError('Implementation closure changed before execution')
    return sources, closure, common, pins, scenarios


def validate_proof(report, corpus, optimization, expected_pins, scenarios):
    if report.get('status') != 'pass-with-numeric-residuals' or report.get('failures'):
        raise AssertionError('Single-pass verifier did not pass')
    if report.get('optimization') != optimization or report.get('corpus') != corpus:
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
    if report.get('successful_external_body_completion_calls') != 0:
        raise AssertionError('Successful runtime-owned routes may not use external completion')
    selected = [row for row in scenarios if corpus == 'all' or row['corpus'] == corpus]
    checkpoints_by_sequence = Counter(row['sequence'] for row in report['rows'])
    if set(checkpoints_by_sequence) != set(range(1, len(selected) + 1)):
        raise AssertionError('Missing or unexpected physical sequence observations')
    for row in report['rows']:
        if (row['unexpected'] or row['semantic'] or row['native_status'] != 100 or
                row['callback'] != row['native_callback']):
            raise AssertionError('Nonmatching checkpoint in passing proof')
    for sequence, recipe in enumerate(selected, 1):
        final = next(row for row in reversed(report['rows']) if row['sequence'] == sequence)
        sequence_polls = [row for row in report['poll_rows'] if row['sequence'] == sequence]
        if (type(final['native_polls']) is not int or
                [row['index'] for row in sequence_polls] != list(range(final['native_polls'])) or
                any(type(row['index']) is not int or row['label'] != recipe['label'] for row in sequence_polls)):
            raise AssertionError('Timer snapshots must preserve every contiguous actual poll in each recipe')
    if any(row['persistent_differences'] for row in report['poll_rows']):
        raise AssertionError('Nonmatching persistent timer snapshot in passing proof')
    errors = {index: recipe for index, recipe in enumerate(selected, 1) if recipe['corpus'] == 'error'}
    controls = report.get('gap_controls', [])
    expected_controls = Counter()
    for sequence, recipe in errors.items():
        suffix = recipe['physical_tokens'][recipe['cancel_token_index']:]
        if recipe['cancel_at']:
            expected_controls[sequence] = 2 if len(suffix) == 2 else 1
        last = next(row for row in reversed(report['rows']) if row['sequence'] == sequence)
        if tuple(last[key] for key in ('status', 'phase', 'event', 'wait', 'body_kind', 'body_operation', 'native_pc')) != (0, 2, 6, 1, 0, 0, 0x1d8a4):
            raise AssertionError('Every error recipe must finish actual coefficient-input recovery')
    if Counter(row['sequence'] for row in controls) != expected_controls:
        raise AssertionError('Every owned error wait needs its exact forged-reply rejection controls')
    for control in controls:
        recipe = errors[control['sequence']]
        if (set(control) != {'sequence', 'label', 'type', 'ram_sha256'} or
                not control['label'].startswith(recipe['label'] + ':physical-') or
                control['type'] != 'owned-error-forged-reply-rejected' or
                not re.fullmatch('[0-9a-f]{64}', control['ram_sha256'])):
            raise AssertionError('Malformed owned error wait rejection control')
        if not any(row['sequence'] == control['sequence'] and row['status'] == 0 and
                   row['label'].startswith(control['label'] + ':') and
                   row['c_ram_sha256'] == control['ram_sha256'] for row in report['rows']):
            raise AssertionError('Forged-reply control is not bound to a witnessed owned wait')
    if any(row['status'] not in (0, 1, 2) or row['body_kind'] == 7 or row['native_pc'] == 0xe884 for row in report['rows']):
        raise AssertionError('The owned error recovery proof may not retain the old E884 gap')
    export_rows = [row for row in report['rows'] if row['status'] == 2]
    expected_exports = sum('host_pairs' in recipe for recipe in selected)
    if len(export_rows) != expected_exports:
        raise AssertionError('Missing or extra actual host-export callback')
    for row in export_rows:
        recipe = selected[row['sequence'] - 1]
        if 'host_pairs' not in recipe or row['native_pc'] not in (0x1db86, 0x1db9c):
            raise AssertionError('Export checkpoint is outside an explicit host-pair recipe')
    if corpus == 'all':
        cohorts = Counter()
        polls = Counter()
        for row in report['rows']:
            cohorts[selected[row['sequence'] - 1]['corpus']] += 1
        for row in report['poll_rows']:
            if type(row['sequence']) is not int or not 1 <= row['sequence'] <= len(selected):
                raise AssertionError('Invalid timer snapshot sequence')
            polls[selected[row['sequence'] - 1]['corpus']] += 1
        if (dict(cohorts) != {name: EXPECTED[name]['observations'] for name in COHORT_COUNTS} or
                dict(polls) != {name: EXPECTED[name]['poll_count'] for name in COHORT_COUNTS}):
            raise AssertionError('Combined proof changed a retained cohort workload')


def compare_optimizations(runs, corpus):
    for key in ('rows', 'poll_rows', 'gap_controls', 'invalid_admission_controls', 'scope'):
        if runs[corpus, 'O2'][key] != runs[corpus, 'O3'][key]:
            raise AssertionError(f'{corpus}: {key} differs between O2 and O3')


def validate_archive(archive, report):
    checkpoints, polls = iter(report['rows']), iter(report['poll_rows'])
    checkpoint_count = poll_count = 0
    final_frames = {}
    with gzip.open(archive, 'rt') as source:
        metadata = json.loads(next(source))
        if (metadata.get('type') != 'archive-encoding' or metadata.get('ram_size') != 65536 or
                metadata.get('ram_encoding') != 'zlib-base64-xor-initial-seed'):
            raise ValueError('Unsupported lossless RAM archive encoding')
        seed = zlib.decompress(base64.b64decode(metadata['initial_ram'], validate=True))
        if len(seed) != 65536 or hashlib.sha256(seed).hexdigest() != metadata['initial_ram_sha256']:
            raise ValueError('Invalid archive initial seed')
        seed_integer = int.from_bytes(seed, 'little')
        for line in source:
            row = json.loads(line)
            is_poll = row.get('type') == 'actual5550-poll-comparison'
            expected = next(polls if is_poll else checkpoints)
            keys = set(expected) | {'c_ram', 'native_ram'} | ({'type'} if is_poll else {'frame_writes'})
            if set(row) != keys or any(row[key] != value for key, value in expected.items()):
                raise ValueError('Archive row differs from its proof')
            ram_images = {}
            ram_integers = {}
            for key in ('c_ram', 'native_ram'):
                delta = zlib.decompress(base64.b64decode(row[key], validate=True))
                if len(delta) != 65536:
                    raise ValueError('Invalid archived RAM size')
                ram_integer = int.from_bytes(delta, 'little') ^ seed_integer
                ram = ram_integer.to_bytes(65536, 'little')
                ram_images[key] = ram
                ram_integers[key] = ram_integer
                if not is_poll and hashlib.sha256(ram).hexdigest() != row[key + '_sha256']:
                    raise ValueError('Archived RAM bytes differ from the checkpoint hash')
            if not is_poll:
                frame = zlib.decompress(base64.b64decode(row['frame_writes'], validate=True))
                if len(frame) != 65536:
                    raise ValueError('Invalid archived witnessed-frame mask')
                final_frames[row['sequence']] = frame
            elif row['sequence'] not in final_frames:
                raise ValueError('Timer snapshot precedes its actual sequence frame witness')
            frame = final_frames[row['sequence']]
            difference_bytes = (ram_integers['c_ram'] ^ ram_integers['native_ram']).to_bytes(65536, 'little')
            # The regex scans unchanged bytes in C; iterate only actual differences.
            residuals, persistent = [], []
            for difference in re.finditer(rb'[^\x00]', difference_bytes):
                address = difference.start()
                numeric = 0x8000 <= address < 0x80dc or 0x8640 <= address < 0x87d0
                value = [address, ram_images['c_ram'][address], ram_images['native_ram'][address]]
                if frame[address] or numeric:
                    residuals.append(value)
                else:
                    persistent.append(value)
            if is_poll:
                if persistent != row['persistent_differences'] or persistent:
                    raise ValueError('Archived timer RAM has an unexpected persistent difference')
                poll_count += 1
            else:
                residual_digest = hashlib.sha256(json.dumps(residuals, separators=(',', ':')).encode()).hexdigest()
                if (persistent != row['unexpected'] or persistent or
                        len(residuals) != row['residual_count'] or residual_digest != row['residual_sha256']):
                    raise ValueError('Archived RAM scoped differences disagree with checkpoint proof')
                checkpoint_count += 1
    if (next(checkpoints, None) is not None or next(polls, None) is not None or
            checkpoint_count != report['observations'] or poll_count != report['poll_count']):
        raise ValueError('Incomplete checkpoint/poll archive')
    return dict(checkpoints=checkpoint_count, timer_snapshots=poll_count)


def run_worker(candidate, corpus, optimization, common, pins, scenarios, log_directory, build_root):
    before = set(build_root.glob('*/' + optimization + '/proof.json'))
    command = [sys.executable, str(candidate / WORKER), '--optimization', optimization,
               '--corpus', corpus, '--build-dir', str(build_root)]
    print(f'Running {corpus} corpus at {optimization}', flush=True)
    scratch = log_directory / 'compiler-scratch'
    scratch.mkdir(exist_ok=True)
    environment = dict(os.environ, TMPDIR=str(scratch), PYTHONOPTIMIZE='0')
    result = subprocess.run(command, cwd=candidate, check=False, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=environment)
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
    expected_paths = set(common + [candidate / FIXTURE])
    expected_pins = {str(path): pins[path] for path in expected_paths}
    validate_proof(report, corpus, optimization, expected_pins, scenarios)
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
    archive_counts = validate_archive(archive, report)
    assert_stable(artifact_pins)
    print(f'Passed {corpus} {optimization}: {report["observations"]} checkpoints, '
          f'{report["checks"]} checks, {report["poll_count"]} persistent timer snapshots', flush=True)
    return report, proof, artifact_pins, archive_counts


def summarize(report, proof, artifacts, candidate, archive_counts):
    def location(path):
        return str(path.relative_to(candidate)) if path.is_relative_to(candidate) else str(path)
    return {
        'corpus': report['corpus'],
        'optimization': report['optimization'],
        'sequences': report['sequences'],
        'checkpoints': report['observations'],
        'checks': report['checks'],
        'persistent_timer_snapshots': report['poll_count'],
        'source_pin_count': len(report['source_pins']),
        'invalid_admission_controls': report['invalid_admission_controls'],
        'owned_error_forged_reply_rejection_controls': len(report['gap_controls']),
        'successful_external_body_completion_calls': report['successful_external_body_completion_calls'],
        'checkpoint_residual_observations': sum(bool(row['residual_count']) for row in report['rows']),
        'actual_export_callbacks': sum(row['status'] == 2 for row in report['rows']),
        'proof': location(proof),
        'proof_artifacts_sha256': {location(path): value for path, value in artifacts.items()},
        'archive_roundtrip': archive_counts,
        'scope': report['scope'],
    }


def main(argv=None):
    args, candidate = parse_arguments(argv)
    canonical = not (args.private_report or args.no_report)
    sources, closure, common, pins, scenarios = capture_inputs(candidate, canonical)
    optimizations = (args.optimization,) if args.optimization else ('O2', 'O3')
    log_directory = candidate / 'analysis/build/runtime-owned-error-canonical' / uuid.uuid4().hex
    log_directory.mkdir(parents=True)
    build_root = args.build_dir.resolve() if args.build_dir else log_directory / 'runs'
    runs = {}
    all_artifacts = {}
    summaries = []
    for optimization in optimizations:
        report, proof, artifacts, archive_counts = run_worker(candidate, args.corpus,
            optimization, common, pins, scenarios, log_directory, build_root)
        runs[args.corpus, optimization] = report
        all_artifacts.update(artifacts)
        summaries.append(summarize(report, proof, artifacts, candidate, archive_counts))
    if len(optimizations) == 2:
        compare_optimizations(runs, args.corpus)
    assert_stable(pins)
    assert_stable(all_artifacts)
    if implementation_inputs(candidate, sources) != closure:
        raise RuntimeError('Implementation closure changed during execution')
    assert_no_original_execution(candidate, closure)
    selected = [row for row in scenarios if args.corpus == 'all' or row['corpus'] == args.corpus]
    result = {
        'status': 'pass', 'full_firmware_complete': False,
        'cases': EXPECTED[args.corpus]['sequences'],
        'count_units': 'cases count distinct physical key/readiness recipes once; each optimization repeats the selected complete workload',
        'optimizations': list(optimizations), 'corpus': args.corpus,
        'recipe_counts': dict(Counter(row['corpus'] for row in selected)),
        'checkpoints_per_optimization': EXPECTED[args.corpus]['observations'],
        'checks_per_optimization': EXPECTED[args.corpus]['checks'],
        'persistent_timer_snapshots_per_optimization': EXPECTED[args.corpus]['poll_count'],
        'invalid_admission_control_executions_per_optimization': 11,
        'owned_error_forged_reply_rejection_controls_per_optimization': 98 if args.corpus in ('all', 'error') else 0,
        'successful_external_body_completion_calls': 0,
        'persistent_timer_snapshot_gaps': 0,
        'optimization_reports': summaries,
        'limits': [
            'Default all retains the original four complete EQN workflows and three TABLE workflows; all 54 error/cancellation prefixes now complete recovery, with 16 ignored/cursor and 12 real host-export restart variants.',
            'Host labels 256..258 identify explicit physical key pairs; they are never supplied to firmware as byte tokens.',
            'The 89 recipes cover bounded integer coefficients and actual AC/cursor/export recovery. Full rich coefficient input, arbitrary raw8 sign encodings, host reset and polynomial EQN remain outside this corpus.',
            'All successful main bodies are owned by the runtime; no external body completion is supplied.',
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
          'corpus', 'recipe_counts', 'checkpoints_per_optimization', 'checks_per_optimization',
          'persistent_timer_snapshots_per_optimization')}), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
