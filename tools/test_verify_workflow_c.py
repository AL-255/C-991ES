#!/usr/bin/env python3
"""Bounded VERIFY predicates, actual137 operands and prepared main events.

Relation and chain cohorts run the original ROM freshly. Main-event C replay
uses two unchanged genuine original archives; returned native values never
feed the C implementation. Input recipes and observations stay separate.
"""
import argparse
import ctypes as C
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid

EXPECTED = {
    'chain-inputs.json': '2f4e3284693f6442d7df23a7554196545800839ce09f9d5e2a6dd4ffe1e46bfb',
    'inputs-syntax-successor.json': '85d15723bb65e36ae4eb0e4f59e62d05842cd0e08d9efbbda3e448bbe05f3ccb',
    'inputs.json': 'a926d9e3565694b7c9ee83cecfa533c616f1da561c3d049c8b570358bd54f818',
    'relation-inputs.json': '122371fb179c25aa50ccc715dfe4e8cae29b0f940927f7396215f1887b4a2de4',
}
OBSERVATIONS = {
    'run-3edee2aa5f89439faff24ae3f5aa93b8/observations.jsonl.gz': '19321570176ceab39389b4dfe10c12fec3b39eb2c7d8dc7b5f70c965103a7550',
    'run-3edee2aa5f89439faff24ae3f5aa93b8/report.json': '811c582abebf7302df06ab295a598bbe17877fd7cf373a6a1b801f5ac16ef274',
    'run-5e700a0a9f8f4e73a60a11b812adf116/observations.jsonl.gz': '8939081f32416782cfded3036a891a2fc7c97085dc495b28a23c8f6b1abd5337',
    'run-5e700a0a9f8f4e73a60a11b812adf116/report.json': 'f63df88d147cef41c8ffe2a17fb7a8eb9875c1149b9aff4bdb0f164956811d7b',
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def changes(pins):
    return {str(p): {'before': h, 'after': digest(p)}
            for p, h in pins.items() if digest(p) != h}


def keys(value, wanted):
    if type(value) is not dict or set(value) != set(wanted):
        raise ValueError('Unexpected fixture fields')


def uint(value, maximum=255):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError('Invalid unsigned fixture value')


def raw(text, length=None):
    if type(text) is not str or not re.fullmatch(r'(?:[0-9a-f]{2})*', text):
        raise ValueError('Invalid input byte string')
    value = bytes.fromhex(text)
    if length is not None and len(value) != length:
        raise ValueError('Invalid input record length')
    return value


def validate(fixture):
    relation = json.loads((fixture / 'relation-inputs.json').read_text())
    keys(relation, ('schema', 'cases'))
    if relation['schema'] != 'verify-relation-input-v1' or len(relation['cases']) != 384:
        raise ValueError('Expected complete384 relation corpus')
    entries = {0x94: 0x18a12, 0x95: 0x18acc, 0x96: 0x18a02,
               0x3c: 0x18a32, 0x3d: 0x18a42, 0x3e: 0x18a22}
    for index, row in enumerate(relation['cases']):
        keys(row, ('id', 'entry', 'token', 'left', 'right', 'alias'))
        uint(row['id'], 383); uint(row['token']); uint(row['entry'], 0x1ffff)
        if row['id'] != index or row['entry'] != entries.get(row['token']) or row['alias'] is not False:
            raise ValueError('Unsupported relation recipe')
        raw(row['left'], 10); raw(row['right'], 10)
    chain = json.loads((fixture / 'chain-inputs.json').read_text())
    keys(chain, ('schema', 'cases'))
    if chain['schema'] != 'verify-chain-input-v2' or len(chain['cases']) != 180:
        raise ValueError('Expected complete180 chain corpus')
    for index, row in enumerate(chain['cases']):
        keys(row, ('id', 'input', 'math', 'source', 'output', 'cancel_at'))
        uint(row['id'], 179); uint(row['math'], 1); uint(row['cancel_at'], 255)
        uint(row['source'], 65535); uint(row['output'], 65516)
        value = raw(row['input'])
        if row['id'] != index or not value or value[-1] or len(value) > 1024 or \
                row['source'] < 32768 or row['output'] < 32768 or \
                row['source'] + len(value) > 65536:
            raise ValueError('Unsupported chain recipe')
    scenarios = set(); counts = []
    for name in ('inputs.json', 'inputs-syntax-successor.json'):
        data = json.loads((fixture / name).read_text())
        keys(data, ('schema', 'startup', 'initial_globals', 'initial_words',
                    'initial_expression', 'cases'))
        if data['schema'] != 'verify-main-original-key-input-v1':
            raise ValueError('Unknown main recipe schema')
        keys(data['startup'], ('entry', 'stop'))
        if data['startup'] != {'entry': 0x6f86, 'stop': 0x6fd8}:
            raise ValueError('Unsupported startup boundary')
        for mapping, limit in ((data['initial_globals'], 255), (data['initial_words'], 65535)):
            for address, value in mapping.items():
                if not re.fullmatch(r'[0-9a-f]{4}', address) or int(address, 16) < 0x8000:
                    raise ValueError('Invalid authored RAM address')
                uint(value, limit)
                if limit == 65535 and int(address, 16) == 65535:
                    raise ValueError('Word seed crosses RAM boundary')
        if len(raw(data['initial_expression'])) >= 100:
            raise ValueError('Initial expression exceeds editor capacity')
        calls = 0
        for case in data['cases']:
            keys(case, ('id', 'math', 'steps'))
            if type(case['id']) is not str or not case['id'] or case['id'] in scenarios:
                raise ValueError('Duplicate main scenario')
            scenarios.add(case['id']); uint(case['math'], 1)
            if type(case['steps']) is not list or not case['steps']:
                raise ValueError('Empty main scenario')
            for step in case['steps']:
                if type(step) is not dict or 'token' not in step or \
                        set(step) - {'token', 'trace', 'modifier', 'cancel_at', 'recovery_keys'}:
                    raise ValueError('Unexpected key recipe fields')
                for field in ('token', 'modifier', 'cancel_at'):
                    if field in step: uint(step[field])
                if 'trace' in step and type(step['trace']) is not bool:
                    raise ValueError('Invalid trace recipe flag')
                if 'recovery_keys' in step and type(step['recovery_keys']) is not list:
                    raise ValueError('Invalid physical recovery key list')
                for token in step.get('recovery_keys', []): uint(token)
                calls += 1
        counts.append(calls)
    # The original79 archive retains one genuine unresolved wait; the17
    # successor is a separate complete syntax/key recovery cohort.
    if counts != [79, 17]:
        raise ValueError('Expected unchanged79+17 main recipes')


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    if not __debug__:
        raise SystemExit('Python optimization is unsupported')
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo-root', type=Path)
    parser.add_argument('--source-root', type=Path)
    parser.add_argument('--fixture-dir', type=Path)
    parser.add_argument('--observations-dir', type=Path)
    parser.add_argument('--build-dir', type=Path)
    parser.add_argument('--optimization', choices=('O2', 'O3', 'both'), default='both')
    parser.add_argument('--report', type=Path)
    parser.add_argument('--no-report', action='store_true')
    args = parser.parse_args()
    tool = Path(__file__).resolve(); root = (args.repo_root or tool.parents[1]).resolve()
    source = (args.source_root or root).resolve()
    fixture = (args.fixture_dir or root / 'analysis/native-fixtures/verify-workflow').resolve()
    observed = (args.observations_dir or root / 'analysis/native-observations/verify-workflow').resolve()
    canonical = root / 'analysis/c-verification/verify_workflow.json'
    target = args.report.resolve() if args.report else canonical
    publication = (source == root and tool == root / 'tools/test_verify_workflow_c.py' and
        fixture == root / 'analysis/native-fixtures/verify-workflow' and
        observed == root / 'analysis/native-observations/verify-workflow' and args.optimization == 'both')
    exact = all(digest(fixture / name) == value for name, value in EXPECTED.items()) and \
            all(digest(observed / name) == value for name, value in OBSERVATIONS.items())
    if not args.no_report and target == canonical and not (publication and exact):
        parser.error('Canonical publication requires installed tool/source, exact full fixtures/observations and both builds; use --no-report or a private --report')
    validate(fixture)
    # Main replay has no fresh key oracle inside this driver. Its authored
    # inputs must bind byte-for-byte to the genuine archived observations,
    # including private/custom math runs; fabricated observation successors
    # cannot be labeled original main outcomes by this verifier.
    if any(digest(observed / name) != value for name, value in OBSERVATIONS.items()) or \
       any(digest(fixture / name) != EXPECTED[name] for name in ('inputs.json', 'inputs-syntax-successor.json')):
        raise ValueError('Main authored inputs/observations do not match their original custody')
    run = (args.build_dir or root / ('analysis/build/verify-workflow/' + uuid.uuid4().hex)).resolve()
    run.mkdir(parents=True, exist_ok=True)
    support = tool.parent / 'verify_workflow_support'
    os.environ.update(VERIFY_ROOT=str(root), VERIFY_SOURCE_ROOT=str(source),
        VERIFY_FIXTURE_DIR=str(fixture), VERIFY_OBSERVATION_DIR=str(observed),
        VERIFY_BUILD_DIR=str(run), VERIFY_OPTIMIZATIONS='O2,O3' if args.optimization == 'both' else args.optimization)
    tmp = run / 'compiler-tmp'; tmp.mkdir(exist_ok=True); os.environ['TMPDIR'] = str(tmp)
    sys.path.insert(0, str(root / 'tools'))
    from c_build_inputs import implementation_inputs
    writer = None
    if not args.no_report and target == canonical:
        from c_verification import write_report
        writer = write_report
    cmake = root / 'csrc/CMakeLists.txt'
    body = cmake.read_text().split('add_library(fx991_firmware STATIC', 1)[1].split(')', 1)[0]
    modules = list(dict.fromkeys(re.findall(r'\b[\w/]+\.c\b', body) +
        ['numeric/fx_verify_relation.c', 'parse/fx_verify_chain.c', 'ui/fx_verify_controller.c']))
    closure = implementation_inputs(source, ['csrc/' + path for path in modules])
    paths = [source / p for p in closure] + [tool, cmake, root / 'tools/test_eval_c.py',
        root / 'tools/c_build_inputs.py', root / 'tools/c_verification.py',
        root / 'firmware/fx-991es-plus-c-ver4.bin', root / 'analysis/disassembly/complete.asm']
    paths += list(support.glob('*.py')) + list(support.glob('*.c'))
    paths += [fixture / name for name in EXPECTED] + [observed / name for name in OBSERVATIONS]
    paths += [p for p in (root / 'tools/nxu8').rglob('*') if p.is_file() and p.suffix in ('.c', '.h', '.py', '.txt')]
    pins = {p.resolve(): digest(p) for p in paths}
    if any(pins[(observed / name).resolve()] != value for name, value in OBSERVATIONS.items()) or \
       any(pins[(fixture / name).resolve()] != EXPECTED[name] for name in ('inputs.json', 'inputs-syntax-successor.json')):
        raise RuntimeError('Original main custody changed before source snapshot')
    if writer and any(pins[(fixture / name).resolve()] != value for name, value in EXPECTED.items()):
        raise RuntimeError('Canonical fixture changed before source snapshot')
    compiler = Path(shutil.which('gcc')).resolve()
    compiler_paths = {compiler}
    for name in ('cc1', 'as', 'collect2', 'ld'):
        name = subprocess.check_output([str(compiler), '-print-prog-name=' + name], text=True).strip()
        path = Path(name) if '/' in name else Path(shutil.which(name))
        compiler_paths.add(path.resolve())
    compiler_pins = {p: digest(p) for p in compiler_paths}
    version = subprocess.check_output([str(compiler), '--version'], text=True)
    publication_controls = load(support / 'guards.py', 'verify_guards').run(tool, fixture, observed, run)
    modules_loaded = {name: load(support / (name + '.py'), 'verify_' + name)
                      for name in ('relation', 'chain', 'main')}
    failed = not all(row['pass'] for row in publication_controls)
    for module in modules_loaded.values(): failed |= bool(module.main())
    variants = {name: json.loads((run / name / 'report.json').read_text())
                for name in modules_loaded}
    # Final guards run after ABI observations below.
    artifacts = {Path(path): value for report in variants.values()
        for detail in report['artifacts'].values() for path, value in detail['sha256'].items()}
    # ABI functions are compiled into the actual main candidate library.
    abi_rows = []
    for opt in os.environ['VERIFY_OPTIMIZATIONS'].split(','):
        lib = C.CDLL(str(run / 'main' / (opt + '.so')))
        fn = lib.verify_main_abi; fn.argtypes = [C.c_uint]; fn.restype = C.c_size_t
        chain = modules_loaded['chain']; relation = modules_loaded['relation']
        expected_abi = [C.sizeof(relation.Number), relation.Number.bytes.offset,
            C.sizeof(chain.Storage), *[getattr(chain.Storage, n).offset for n, _ in chain.Storage._fields_],
            C.sizeof(chain.Result), *[getattr(chain.Result, n).offset for n, _ in chain.Result._fields_],
            C.sizeof(chain.Control), *[getattr(chain.Control, n).offset for n, _ in chain.Control._fields_]]
        actual = [fn(index) for index in range(len(expected_abi))]
        abi_rows.append({'optimization': opt, 'expected': expected_abi, 'actual': actual})
        failed |= expected_abi != actual
    source_changes = changes(pins); compiler_changes = changes(compiler_pins)
    artifact_changes = changes(artifacts)
    failed |= bool(source_changes or compiler_changes or artifact_changes) or any(
        row['status'] != 'pass' for row in variants.values())
    report = {'schema': 1, 'status': 'FAIL' if failed else 'PASS',
        'full_firmware_complete': False, 'variants': variants,
        'fresh_original_calls': len(variants['relation']['rows']) + len(variants['chain']['rows']),
        'archived_original_main_calls': 96, 'C_compared_calls': sum(len(row['rows']) for row in variants.values()),
        'checks': variants['relation']['checks'] + 8 * len(variants['chain']['rows']) +
            4 * len(variants['main']['rows']) + sum(len(row['actual']) for row in abi_rows) +
            len(publication_controls),
        'publication_controls': publication_controls,
        'abi': abi_rows, 'failures': [] if not failed else ['A bounded cohort or provenance/ABI guard failed'],
        'source_pins': {str(p): h for p, h in pins.items()}, 'source_changes': source_changes,
        'compiler_pins': {str(p): h for p, h in compiler_pins.items()}, 'compiler_version': version,
        'compiler_changes': compiler_changes, 'artifact_changes': artifact_changes,
        'compiled_artifacts': {str(p): h for p, h in artifacts.items()},
        'scope': 'Prepared384 finite predicates and180 original138EE chains per build, plus96 genuine originalD9EE main outcomes replayed in C per build (95 returns+1 retained wait). Relation/chain compare selected numerical fields/pools/cursors/polls, not fullRAM. Main compares remainingRAM/LCD/MMIO/outputs outside8000..80DB,8640..87CF and measured cumulative original CPU stack; no wholeboot/keyscan/generalphysical aliases or advanced calculus claim.'}
    (run / 'proof.json').write_text(json.dumps(report, indent=2) + '\n')
    if not failed and not args.no_report:
        if writer:
            if any(digest(fixture / name) != value for name, value in EXPECTED.items()) or \
               any(digest(observed / name) != value for name, value in OBSERVATIONS.items()):
                raise RuntimeError('Canonical literal custody changed before publication')
            eligible = [p.relative_to(root) for p in pins if p.is_relative_to(root) and
                (p.suffix in ('.c', '.h', '.py', '.json', '.bin') or p.name == 'CMakeLists.txt')]
            staged = writer(run / 'canonical-staging.json', report, eligible, tool.relative_to(root))
            # The unchanged common writer excludes ASM/ISA/gzip. Exact guarded
            # extra-input pins remain separate and are appended after staging.
            staged['tested_inputs_sha256'].update({str(p.relative_to(root)): h for p, h in pins.items()
                if p.is_relative_to(root) and p.relative_to(root) not in eligible})
            if changes(pins) or changes(artifacts) or changes(compiler_pins):
                raise RuntimeError('Inputs changed before canonical publication')
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix('.json.new')
            temporary.write_text(json.dumps(staged, indent=2) + '\n'); temporary.replace(target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: report[key] for key in ('status', 'fresh_original_calls',
        'archived_original_main_calls', 'C_compared_calls', 'checks')}))
    print(run / 'proof.json')
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
