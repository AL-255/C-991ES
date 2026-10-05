#!/usr/bin/env python3
"""Fresh original171F4 proof of pending mathematical operand publication.

Inputs are fixed authored recipes. No archived result is read by this tool.
The one known C4 out-of-ROM continuation is retained as a prefix boundary,
separate from all original normal returns. Default runs execute O2 and O3.
"""
import sys
if not __debug__:
    raise SystemExit('Optimized Python (-O/-OO) is rejected unconditionally')

import argparse
import base64
import copy
import ctypes as C
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import uuid
import zlib

SELF = Path(__file__).resolve()
ROOT = SELF.parents[1]
if not (ROOT / 'tools/nxu8/harness.c').is_file():
    ROOT = Path.cwd().resolve()
sys.path.insert(0, str(ROOT / 'tools'))
from c_build_inputs import implementation_inputs
from c_verification import write_report

TEST = 'tools/test_eval_saved_operands_c.py'
FIXTURE = 'analysis/native-fixtures/saved-operands/inputs.json'
FIXTURE_SHA = '251d9877af5a413ad01cb2612a9f0a6bc4f66086545a3448107e27730dbaba91'
ADAPTER = 'tools/saved_operand_support/adapter.c'
ORACLE = 'tools/saved_operand_support/native.c'
ROM = 'firmware/fx-991es-plus-c-ver4.bin'
BOUNDARY_ID = 'c4-integral-8154'
SENTINEL = 0x2fffe

class Number(C.Structure):
    _fields_ = [('bytes', C.c_uint8 * 10)]
class Result(C.Structure):
    _fields_ = [('value', Number * 2), ('consumed', C.c_size_t),
               ('unsupported_token', C.c_uint8)]
class Storage(C.Structure):
    _fields_ = [('ram', C.c_void_p), ('ram_size', C.c_size_t),
               ('rom', C.c_void_p), ('rom_size', C.c_size_t)]
class Source(C.Structure):
    _fields_ = [('input_address', C.c_uint16), ('output_address', C.c_uint16),
               ('before_sample', C.c_void_p), ('userdata', C.c_void_p)]
class Control(C.Structure):
    _fields_ = [('cancelled', C.c_void_p), ('userdata', C.c_void_p)]
class Event(C.Structure):
    _fields_ = [('pc', C.c_uint32), ('argument_address', C.c_uint16),
               ('depth', C.c_uint8), ('data', C.c_uint8 * 100)]
class GuardedRam(C.Structure):
    _fields_ = [('before', C.c_uint8 * 16), ('value', C.c_uint8 * 65536),
               ('after', C.c_uint8 * 16)]
class GuardedResult(C.Structure):
    _fields_ = [('before', C.c_uint8 * 16), ('value', Result), ('after', C.c_uint8 * 16)]
class GuardedCursor(C.Structure):
    _fields_ = [('before', C.c_uint8 * 16), ('value', C.c_uint16), ('after', C.c_uint8 * 16)]

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def state(paths):
    return {str(Path(path).resolve()): digest(path) for path in sorted(set(paths))}

def unchanged(before, label):
    changed = {path: digest(path) if Path(path).is_file() else None
               for path, expected in before.items()
               if not Path(path).is_file() or digest(path) != expected}
    if changed:
        raise RuntimeError(label + ' changed during execution: ' + json.dumps(changed))

def validate_fixture(data):
    if not isinstance(data, dict) or set(data) != {'schema', 'provenance', 'initial_ram_hex', 'cases'}:
        raise ValueError('Unknown or incomplete input-only fixture schema')
    if type(data['schema']) is not int or data['schema'] != 1 or not isinstance(data['provenance'], str):
        raise ValueError('Unsupported fixture metadata')
    if not isinstance(data['initial_ram_hex'], str) or not re.fullmatch(r'[0-9a-f]{131072}', data['initial_ram_hex']):
        raise ValueError('Initial RAM must be exactly65536 authored bytes')
    if not isinstance(data['cases'], list) or len(data['cases']) != 47:
        raise ValueError('All47 fixed input-only controls are required')
    seen = set()
    for row in data['cases']:
        if not isinstance(row, dict) or set(row) != {'id', 'mode', 'source', 'output', 'cursor_address', 'tokens'}:
            raise ValueError('Unknown recipe fields, including expected outputs, are rejected')
        if not isinstance(row['id'], str) or row['id'] in seen:
            raise ValueError('Every input recipe requires a unique string identity')
        seen.add(row['id'])
        if any(type(row[key]) is not int for key in ('mode', 'source', 'output', 'cursor_address')):
            raise ValueError('Integer settings cannot be booleans or floats')
        if row['mode'] not in (0xc1, 0xc4) or row['source'] not in (0x8154, 0x8076):
            raise ValueError('Recipe outside this fixed prepared scope')
        if row['output'] != 0x89a0 or row['cursor_address'] != 0x9900:
            raise ValueError('Unexpected caller-owned address')
        if not re.fullmatch(r'(c1|c4)-[a-z][a-z-]*-(8076|8154)', row['id']):
            raise ValueError('Unexpected fixed recipe identity')
        if row['id'][:2] != f'{row["mode"]:02x}' or row['id'][-4:] != f'{row["source"]:04x}':
            raise ValueError('Recipe identity disagrees with input settings')
        if not isinstance(row['tokens'], str) or not re.fullmatch(r'(?:[0-9a-f]{2}){2,128}', row['tokens']):
            raise ValueError('Invalid raw input token recipe')
        tokens = bytes.fromhex(row['tokens'])
        if tokens[-1] != 0 or 0 in tokens[:-1]:
            raise ValueError('A single final terminating byte is required')
    if BOUNDARY_ID not in seen:
        raise ValueError('The separately retained C4 continuation control is required')
    return bytes.fromhex(data['initial_ram_hex']), data['cases']

def production_sources(source_root):
    cmake = source_root / 'csrc/CMakeLists.txt'
    match = re.search(r'add_library\(fx991_firmware\s+STATIC\s+(.*?)\)', cmake.read_text(), re.S)
    if not match:
        raise ValueError('Cannot identify the actual fx991_firmware source list')
    names = re.findall(r'(?<![\w/])([\w/]+\.c)(?!\w)', match.group(1))
    if not names or len(names) != len(set(names)):
        raise ValueError('Invalid or repeated source list')
    return cmake, ['csrc/' + name for name in names]

def resolve_program(name):
    path = shutil.which(name)
    if not path:
        raise RuntimeError('Missing compiler component: ' + name)
    return Path(path).resolve()

def compiler_inputs(cc):
    paths = {cc, Path(sys.executable).resolve()}
    def output(*args):
        return subprocess.check_output([str(cc), *args], text=True).strip()
    metadata = {'version': output('--version'), 'target': output('-dumpmachine')}
    if 'gcc' not in metadata['version'].lower():
        raise RuntimeError('This guarded canonical build requires the recorded GNU C compiler')
    for name in ('cc1', 'collect2', 'lto-wrapper', 'as', 'ld'):
        value = output('-print-prog-name=' + name)
        path = Path(value)
        if not path.is_file(): path = resolve_program(value)
        paths.add(path.resolve())
    for name in ('liblto_plugin.so', 'crtbeginS.o', 'crtendS.o', 'crti.o', 'crtn.o',
                 'libgcc.a', 'libgcc_s.so.1', 'libc.so', 'libc_nonshared.a'):
        path = Path(output('-print-file-name=' + name))
        if not path.is_file(): raise RuntimeError('Missing compiler input: ' + name)
        paths.add(path.resolve())
    return paths, metadata

def preprocessor_inputs(command):
    raw = subprocess.check_output(command, text=True)
    tokens = shlex.split(raw.replace('\\\n', ' '))
    paths = set()
    for token in tokens:
        if token.endswith(':'): continue
        path = Path(token).resolve()
        if not path.is_file(): raise RuntimeError('Unresolved compiled dependency: ' + token)
        paths.add(path)
    return paths

def u(lib, name):
    return C.c_uint.in_dll(lib, name).value

def guard_ok(value):
    return bytes(value.before) == b'\xad' * 16 and bytes(value.after) == b'\xad' * 16

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path)
    parser.add_argument('--fixture', type=Path)
    parser.add_argument('--adapter-source', type=Path)
    parser.add_argument('--oracle-source', type=Path)
    parser.add_argument('--optimization', choices=('O2', 'O3'))
    parser.add_argument('--private-report', type=Path)
    parser.add_argument('--no-report', action='store_true')
    args = parser.parse_args()
    private = bool(args.private_report or args.no_report)
    source_root = args.source_root.resolve() if args.source_root else ROOT
    fixture = args.fixture.resolve() if args.fixture else ROOT / FIXTURE
    adapter = args.adapter_source.resolve() if args.adapter_source else ROOT / ADAPTER
    oracle = args.oracle_source.resolve() if args.oracle_source else ROOT / ORACLE
    if (args.source_root or args.fixture or args.adapter_source or args.oracle_source or
        args.optimization or SELF != ROOT / TEST) and not private:
        parser.error('Custom source, fixture, support or single-optimization runs cannot publish canonical reports')
    if args.private_report and args.private_report.resolve().is_relative_to(ROOT / 'analysis/c-verification'):
        parser.error('Private reports cannot replace canonical reports')
    if digest(fixture) != FIXTURE_SHA:
        parser.error('The exact frozen input-only fixture identity is required')
    data = json.loads(fixture.read_text())
    seed, recipes = validate_fixture(data)
    cmake, sources = production_sources(source_root)
    cc = resolve_program('gcc')
    compiler_paths, compiler_metadata = compiler_inputs(cc)
    implementation = [source_root / name for name in implementation_inputs(source_root, sources)]
    python_helpers = {Path(module.__file__).resolve() for module in list(sys.modules.values())
        if getattr(module, '__file__', None) and Path(module.__file__).suffix == '.py'
        and Path(module.__file__).resolve().is_relative_to(ROOT / 'tools')}
    paths = {*implementation, cmake, fixture, SELF, adapter, oracle, ROOT / ROM,
             ROOT / 'tools/nxu8/harness.c', ROOT / 'tools/nxu8/vendor/SimU8/core.c',
             *sorted((ROOT / 'tools/nxu8/vendor/SimU8').glob('*.h')), *python_helpers}
    candidate_flags = ['-std=c99', '-Wall', '-Wextra', '-Werror', '-fPIC',
                       '-I', str(source_root / 'csrc')]
    oracle_flags = ['-std=c99', '-Wall', '-Wextra', '-Werror', '-fPIC',
                    '-I', str(ROOT / 'tools/nxu8')]
    candidate_files = [*[str(source_root / name) for name in sources], str(adapter)]
    oracle_files = [str(oracle), str(ROOT / 'tools/nxu8/vendor/SimU8/core.c')]
    deps_commands = [[str(cc), *candidate_flags, '-M', *candidate_files],
                     [str(cc), *oracle_flags, '-M', *oracle_files]]
    for command in deps_commands: compiler_paths.update(preprocessor_inputs(command))
    source_before = state(paths)
    compiler_before = state(compiler_paths)
    build_base = args.private_report.resolve().parent if args.private_report else ROOT / 'analysis/build/eval-saved-operands'
    build = build_base / ('saved-operands-' + uuid.uuid4().hex)
    build.mkdir(parents=True)
    rom = (ROOT / ROM).read_bytes()
    if len(rom) != 0x20000: raise ValueError('Unexpected original firmware extent')
    rombuf = (C.c_uint8 * len(rom)).from_buffer_copy(rom)
    variants = []
    failures = []
    artifacts = {}
    commands = []
    optimizations = [args.optimization] if args.optimization else ['O2', 'O3']
    total_checks = 0
    def check(label, actual, expected):
        nonlocal total_checks
        total_checks += 1
        if actual != expected:
            failures.append({'label': label, 'actual': actual, 'expected': expected})

    # Real owned-file mutations verify that source/compiler/artifact pin maps
    # reject changes. No production or compiler file is altered by these guards.
    for label in ('source', 'compiler', 'artifact'):
        path = build / ('mutation-guard-' + label)
        path.write_bytes(b'before')
        pins = state([path])
        unchanged(pins, label)
        path.write_bytes(b'changed')
        rejected = False
        try: unchanged(pins, label)
        except RuntimeError: rejected = True
        check('mutation/' + label, rejected, True)
    for flag in ('-O', '-OO'):
        completed = subprocess.run([sys.executable, flag, str(SELF), '--no-report'],
                                   capture_output=True, text=True)
        check('python/' + flag, (completed.returncode != 0 and 'rejected unconditionally' in
                                (completed.stdout + completed.stderr)), True)
    mutations = []
    modified = copy.deepcopy(data); modified['expected_result'] = '3'; mutations.append(modified)
    modified = copy.deepcopy(data); modified['cases'].pop(); mutations.append(modified)
    modified = copy.deepcopy(data); modified['cases'][0]['mode'] = True; mutations.append(modified)
    modified = copy.deepcopy(data); modified['cases'][0]['tokens'] = '31003200'; mutations.append(modified)
    modified = copy.deepcopy(data); modified['cases'][1]['id'] = modified['cases'][0]['id']; mutations.append(modified)
    modified = copy.deepcopy(data); modified['cases'][0]['expected_status'] = 0; mutations.append(modified)
    for index, modified in enumerate(mutations):
        rejected = False
        try: validate_fixture(modified)
        except ValueError: rejected = True
        check(f'schema/{index}', rejected, True)

    for optimization in optimizations:
        work = build / optimization
        work.mkdir()
        candidate_path = work / 'candidate.so'
        native_path = work / 'original.so'
        compile_commands = [
            [str(cc), '-' + optimization, *candidate_flags, '-shared', '-Wl,--no-undefined',
             *candidate_files, '-o', str(candidate_path)],
            [str(cc), '-' + optimization, *oracle_flags, '-shared', '-Wl,--no-undefined',
             *oracle_files, '-o', str(native_path)]]
        for command in compile_commands:
            commands.append(command); subprocess.run(command, check=True)
        artifact_before = state([candidate_path, native_path])
        lib = C.CDLL(str(candidate_path)); native = C.CDLL(str(native_path))
        lib.fx_saved_operand_probe.argtypes = [C.c_void_p, C.c_void_p, C.c_size_t,
            C.c_uint16, C.c_size_t, C.c_uint16, C.POINTER(C.c_uint16), C.POINTER(Result)]
        lib.fx_saved_operand_probe.restype = C.c_int
        lib.fx_saved_operand_abi.argtypes = [C.c_uint]; lib.fx_saved_operand_abi.restype = C.c_size_t
        native.harness_init.argtypes = [C.c_void_p, C.c_size_t]
        native.harness_ram.restype = C.POINTER(C.c_uint8 * 65536)
        native.harness_get_reg.argtypes = [C.c_uint]; native.harness_get_reg.restype = C.c_uint8
        native.fx_saved_native_run.argtypes = [C.c_uint16, C.c_uint16, C.c_uint64]
        native.fx_saved_native_run.restype = C.c_int
        native.fx_saved_native_abi.argtypes = [C.c_uint]; native.fx_saved_native_abi.restype = C.c_size_t
        candidate_abi = [C.sizeof(Number), C.sizeof(Result), Result.consumed.offset,
            Result.unsupported_token.offset, C.sizeof(Storage), Storage.ram.offset,
            Storage.ram_size.offset, Storage.rom.offset, Storage.rom_size.offset,
            C.sizeof(Source), Source.input_address.offset, Source.output_address.offset,
            Source.before_sample.offset, Source.userdata.offset, C.sizeof(Control),
            Control.cancelled.offset, Control.userdata.offset, C.sizeof(C.c_int)]
        for index, value in enumerate(candidate_abi):
            check(f'{optimization}/candidate-ABI/{index}', lib.fx_saved_operand_abi(index), value)
        native_abi = [C.sizeof(Event), Event.pc.offset, Event.argument_address.offset,
                      Event.depth.offset, Event.data.offset]
        for index, value in enumerate(native_abi):
            check(f'{optimization}/native-ABI/{index}', native.fx_saved_native_abi(index), value)
        rows = []
        returned = boundaries = 0
        with gzip.open(work / 'observations.jsonl.gz', 'wt') as archive:
            for recipe in recipes:
                raw = bytearray(seed)
                for address, value in ((0x80f9, recipe['mode']), (0x80fc, 1), (0x80fd, 0),
                    (0x80fe, 1), (0x80ff, 0), (0x80f5, 0xf0), (0x8100, 0), (0x8101, 0),
                    (0x8130, 0), (0x8106, 1), (0x810c, 0), (0x8105, 4)):
                    raw[address] = value
                tokens = bytes.fromhex(recipe['tokens'])
                output, source, cursor_address = recipe['output'], recipe['source'], recipe['cursor_address']
                raw[output:output + 20] = b'\xa5' * 20
                raw[source:source + len(tokens)] = tokens
                raw[cursor_address:cursor_address + 2] = source.to_bytes(2, 'little')
                guarded_ram = GuardedRam(); guarded_result = GuardedResult(); guarded_cursor = GuardedCursor()
                for guard in (guarded_ram, guarded_result, guarded_cursor):
                    C.memset(C.byref(guard), 0xad, C.sizeof(guard))
                C.memmove(guarded_ram.value, bytes(raw), 65536)
                guarded_cursor.value = source
                # C is executed first, from input-only RAM. The fresh original
                # runs afterward; there is no channel for feeding it back to C.
                status = lib.fx_saved_operand_probe(guarded_ram.value, rombuf, len(rom), source,
                    len(tokens), output, C.cast(C.byref(guarded_cursor, GuardedCursor.value.offset),
                    C.POINTER(C.c_uint16)), C.byref(guarded_result.value))
                actual = bytes(guarded_ram.value)
                polls = u(lib, 'fx_saved_polls')
                poll_data = (C.c_uint8 * (1024 * 100)).in_dll(lib, 'fx_saved_poll_data')
                c_poll_data = [bytes(poll_data[index * 100:(index + 1) * 100]).hex()
                               for index in range(min(polls, 1024))]
                native.harness_init(rombuf, len(rom))
                ram = native.harness_ram().contents
                C.memmove(ram, bytes(raw), 65536)
                stop = native.fx_saved_native_run(cursor_address, output, 5_000_000)
                expected = bytes(ram)
                native_polls = u(native, 'fx_saved_native_polls')
                native_poll_data = (C.c_uint8 * (1024 * 100)).in_dll(native, 'fx_saved_native_poll_data')
                n_poll_data = [bytes(native_poll_data[index * 100:(index + 1) * 100]).hex()
                              for index in range(min(native_polls, 1024))]
                candidate = {'status': status, 'cursor': guarded_cursor.value,
                    'result': actual[output:output + 20].hex(), 'saved_data': actual[0x8078:0x80dc].hex(),
                    'polls': polls, 'poll_data': c_poll_data}
                original = {'status': native.harness_get_reg(0),
                    'cursor': int.from_bytes(expected[cursor_address:cursor_address + 2], 'little'),
                    'result': expected[output:output + 20].hex(), 'saved_data': expected[0x8078:0x80dc].hex(),
                    'polls': native_polls, 'poll_data': n_poll_data}
                label = optimization + '/' + recipe['id']
                stop_pc = C.c_uint32.in_dll(native, 'fx_saved_native_stop_pc').value
                if recipe['id'] == BOUNDARY_ID:
                    boundaries += 1
                    check(label + '/native-prefix', (stop, stop_pc, original['status'], native_polls),
                          (101, 0x95076, 3, 7))
                    check(label + '/host-boundary', status, -1)
                else:
                    returned += 1
                    check(label + '/native-return', (stop, stop_pc), (100, SENTINEL))
                    check(label + '/status', status, original['status'])
                for field in ('cursor', 'result', 'saved_data', 'polls', 'poll_data'):
                    check(label + '/' + field, candidate[field], original[field])
                for name, guard in (('ram', guarded_ram), ('result', guarded_result), ('cursor', guarded_cursor)):
                    check(label + '/canary-' + name, guard_ok(guard), True)
                check(label + '/observer-capacity',
                    (u(lib, 'fx_saved_poll_overflow'), u(native, 'fx_saved_native_poll_overflow'),
                     u(native, 'fx_saved_event_overflow')), (0, 0, 0))
                event_count = u(native, 'fx_saved_event_count')
                events = (Event * 1024).in_dll(native, 'fx_saved_events')
                row = {'id': recipe['id'], 'native_stop': stop, 'native_stop_pc': f'{stop_pc:06x}',
                    'candidate': candidate, 'original': original,
                    'instructions': u(native, 'fx_saved_native_steps'),
                    'events': [{'pc': f'{event.pc:06x}', 'argument_address': event.argument_address,
                                'depth': event.depth, 'data': bytes(event.data).hex()}
                               for event in events[:event_count]]}
                rows.append(row)
                full = dict(row, input=recipe,
                    initial_ram=base64.b64encode(zlib.compress(bytes(raw))).decode(),
                    candidate_ram=base64.b64encode(zlib.compress(actual)).decode(),
                    original_ram=base64.b64encode(zlib.compress(expected)).decode())
                archive.write(json.dumps(full) + '\n')
        check(optimization + '/normal-count', returned, 46)
        check(optimization + '/boundary-count', boundaries, 1)
        unchanged(artifact_before, optimization + ' compiled artifacts')
        artifacts.update(artifact_before)
        artifacts.update(state([work / 'observations.jsonl.gz']))
        variants.append({'optimization': optimization, 'cases': len(rows), 'normal_returns': returned,
            'native_prefix_boundaries': boundaries, 'instructions': sum(row['instructions'] for row in rows),
            'rows': rows, 'archive': str(work / 'observations.jsonl.gz'),
            'candidate_abi': candidate_abi, 'native_abi': native_abi})
    unchanged(source_before, 'source/tool/fixture inputs')
    unchanged(compiler_before, 'compiler and actual preprocessing inputs')
    unchanged(artifacts, 'compiled artifacts and captured observations')
    report = {'status': 'pass' if not failures else 'fail', 'checks': total_checks,
        'cases': sum(variant['cases'] for variant in variants),
        'normal_native_returns': sum(variant['normal_returns'] for variant in variants),
        'native_prefix_boundaries': sum(variant['native_prefix_boundaries'] for variant in variants),
        'native_boundary_case_id': BOUNDARY_ID,
        'boundary_policy': 'Only this frozen C4 input reaches originalPC95076/harness101. '
            'Host-1 is preserved; cursor/output/saved data/poll snapshots match the prefix. '
            'No normal return or whole C4 completion is inferred.',
        'comparison': 'Fresh original171F4 native status/return, caller cursor, complete20-byte output, '
            'all100 saved operand bytes, exact real5550 poll counts and saved-data snapshots, compiled ABI and canaries. '
            'Full RAM is retained; unrelated numeric flags/operator-byte scratch are not claimed matched.',
        'full_firmware_complete': False, 'failures': failures, 'source_pins': source_before,
        'compiler_pins': compiler_before, 'compiler': compiler_metadata,
        'artifact_pins': artifacts, 'commands': commands, 'dependency_commands': deps_commands,
        'fixture_sha256': FIXTURE_SHA, 'variants': variants,
        'source_changes': {}, 'compiler_changes': {}, 'artifact_changes': {}}
    private_output = args.private_report.resolve() if args.private_report else build / 'proof.json'
    private_output.parent.mkdir(parents=True, exist_ok=True)
    private_output.write_text(json.dumps(report, indent=2) + '\n')
    if failures:
        raise RuntimeError(f'{len(failures)} unfiltered differences; see {private_output}')
    if not private:
        dependencies = [str(Path(path).relative_to(ROOT)) for path in source_before
                        if Path(path).is_relative_to(ROOT)]
        write_report('analysis/c-verification/eval_saved_operands.json', report, dependencies, TEST)
    print(json.dumps({key: report[key] for key in ('status', 'checks', 'cases',
        'normal_native_returns', 'native_prefix_boundaries', 'source_changes', 'compiler_changes',
        'artifact_changes')}, indent=2))
    print('Report:', private_output)

if __name__ == '__main__':
    main()
