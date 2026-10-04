#!/usr/bin/env python3
"""Review the device JSON binding against archived original raw-key observations.

This test executes only the newly compiled C device. Original expectations are
read from a frozen, independently checked archive; no original CPU is run and no
observed output is copied into the candidate. GPL-3.0-only.
"""
import argparse
import base64
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from c_build_inputs import implementation_inputs

NATIVE = ROOT / 'analysis/native-observations/device-protocol/native-206.json'
NATIVE_SHA = 'ed30258b3ac3bf22a93e8dfbb2372b10eee23f41ba4883521349cc584b226dda'
INPUTS = ROOT / 'analysis/native-fixtures/device-protocol/inputs.json'
INPUTS_SHA = '17221a28db4c9e0c90cf5252873a3d018c2b35cb1f7d9822762a375255cc750f'
SEQUENCES = (1, 3, 13, 14, 16, 17, 23, 24)
STATUS_NAMES = {-1: 'invalid', 0: 'wait', 1: 'advanced', 2: 'export',
                3: 'timer', 4: 'request', 5: 'reset'}
FIELDS = ('runtime_status', 'phase', 'event', 'memory_status', 'steps',
          'active', 'timer_pending', 'timer_period', 'export_mask',
          'callback_pending', 'returned', 'host_wait', 'key_columns', 'key_rows',
          'main_request', 'wait_required', 'last_menu_result', 'input_action',
          'input_context_return', 'mode_result', 'bank_result', 'mode_request',
          'mode_page', 'bank_page', 'unsupported_token')
REQUEST_FIELDS = ('kind', 'operation', 'argument', 'context_return', 'action',
                  'status', 'expression_address', 'result_address',
                  'prepared_source', 'current_source', 'page')

ADAPTER = r'''/* Test ABI: observe through the public opaque device API only. */
#include "app/fx_device_session.h"
#include <stdint.h>
fx_device_session *protocol_create_seed(const uint8_t *seed)
{
    fx_device_configuration config = {seed, seed ? 65536u : 0u,
                                      seed ? seed[0xf050] : 0};
    return fx_device_session_create(seed ? &config : NULL);
}
int protocol_snapshot_fields(const fx_device_session *session, int64_t *fields)
{
    fx_device_snapshot s;
    if (!fields || fx_device_session_snapshot(session, &s)) return -1;
    const int64_t values[] = {s.last_status, s.phase, s.event, s.memory_status,
        s.steps, s.active, s.timer_pending, s.timer_period, s.export_mask,
        s.callback_pending, s.returned, s.host_wait, s.key_columns, s.key_rows,
        s.main_request, s.wait_required, s.last_menu_result, s.input_action,
        s.input_context_return, s.mode_result, s.bank_result, s.mode_request,
        s.mode_page, s.bank_page, s.unsupported_token,
        s.request.kind, s.request.operation, s.request.argument,
        s.request.context_return, s.request.action, s.request.status,
        s.request.expression_address, s.request.result_address,
        s.request.prepared_source, s.request.current_source, s.request.page};
    for (unsigned i = 0; i < sizeof values / sizeof values[0]; ++i)
        fields[i] = values[i];
    return 0;
}
'''


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def bytes_digest(data):
    return hashlib.sha256(data).hexdigest()


def unpack(data):
    raw = zlib.decompress(base64.b64decode(data, validate=True))
    assert len(raw) == 65536
    return raw


def unique_object(pairs):
    obj = {}
    for name, value in pairs:
        if name in obj:
            raise AssertionError('duplicate JSON member: ' + name)
        obj[name] = value
    return obj


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--candidate-root', type=Path, default=ROOT)
    ap.add_argument('--private-report', type=Path,
                    help='Optional report path; default is a new private UUID directory')
    args = ap.parse_args()
    if sys.flags.optimize:
        ap.error('Assertions must remain enabled')
    candidate = args.candidate_root.resolve()
    report_path = (args.private_report.resolve() if args.private_report else
                   ROOT / 'analysis/build/device-protocol-review' / uuid.uuid4().hex / 'report.json')
    build = report_path.parent
    if not build.is_relative_to((ROOT / 'analysis/build/device-protocol-review').resolve()):
        ap.error('Report must use the task-owned private review directory')
    if report_path.exists():
        ap.error('Preserve existing proofs: choose a new private report path')
    build.mkdir(parents=True, exist_ok=True)
    tmp = build / 'compiler-tmp'
    tmp.mkdir(exist_ok=True)
    assert digest(NATIVE) == NATIVE_SHA and digest(INPUTS) == INPUTS_SHA
    native = json.loads(NATIVE.read_text())
    recipes = json.loads(INPUTS.read_text())
    assert native['schema'] == recipes['schema'] == 1
    assert tuple(native['sequence_ids']) == tuple(recipes['sequence_ids']) == SEQUENCES
    expected = {}
    for row in native['rows']:
        assert set(row) == {'sequence', 'label', 'occurrence', 'original_native_pc',
                           'original_ram_sha256', 'framebuffer', 'settings_and_packet',
                           'original_callback'}
        key = row['sequence'], row['label']
        group = expected.setdefault(key, [])
        assert row['sequence'] in SEQUENCES and row['occurrence'] == len(group)
        assert re.fullmatch('[0-9a-f]{768}', row['framebuffer'])
        assert len(row['settings_and_packet']) == 6 and all(type(v) is int and 0 <= v <= 255 for v in row['settings_and_packet'])
        assert type(row['original_callback']) is int and 0 <= row['original_callback'] <= 255
        group.append(row)
    checkpoint_count = sum(map(len, expected.values()))
    assert checkpoint_count == native['checkpoint_count'] == 206
    fixture_path = ROOT / recipes['legacy_fixture']
    extensions_path = ROOT / recipes['extension_fixture']
    assert digest(fixture_path) == recipes['legacy_fixture_sha256']
    assert digest(extensions_path) == recipes['extension_fixture_sha256']
    fixture = json.loads(fixture_path.read_text())
    authored = json.loads(extensions_path.read_text())
    rom_path = ROOT / 'firmware/fx-991es-plus-c-ver4.bin'
    assert digest(rom_path) == native['original_source_pins'][str(rom_path.relative_to(ROOT))]
    rom = rom_path.read_bytes()
    # This is input key-map data, never an instruction executor.
    pairs = {rom[0x7fe + 8 * col + row]: (1 << col, 1 << row)
             for col in range(8) for row in range(8)}
    cmake = candidate / 'csrc/CMakeLists.txt'
    static = re.search(r'add_library\(fx991_firmware STATIC(.*?)\)',
                       cmake.read_text(), re.S).group(1)
    sources = ['csrc/' + name for name in re.findall(r'[\w/]+\.c', static)]
    sources = list(dict.fromkeys(sources + ['csrc/app/fx_device_session.c']))
    closed = [candidate / name for name in implementation_inputs(candidate, sources)]
    protocol = [ROOT / 'csrc/app/fx_device_protocol.c', ROOT / 'csrc/app/fx_device_protocol.h']
    inputs = closed + protocol + [cmake, Path(__file__).resolve(), ROOT / 'tools/c_build_inputs.py',
                                 NATIVE, INPUTS, fixture_path, extensions_path, rom_path]
    pins = {str(path): digest(path) for path in inputs}
    overlay = build / 'protocol-source'
    overlay.mkdir(exist_ok=True)
    for path in protocol:
        shutil.copy2(path, overlay / path.name)
    adapter = build / 'snapshot-adapter.c'
    adapter.write_text(ADAPTER)
    pins[str(adapter)] = digest(adapter)
    for path in overlay.iterdir():
        pins[str(path)] = digest(path)
    compiler = Path(subprocess.check_output(['which', 'gcc'], text=True).strip()).resolve()
    pins[str(compiler)] = digest(compiler)
    libc = C.CDLL(None)
    libc.free.argtypes = [C.c_void_p]
    libraries = []
    reports = []
    for optimization in ('O2', 'O3'):
        lib_path = build / ('protocol-' + optimization + '.so')
        protocol_object = build / ('protocol-' + optimization + '.o')
        protocol_command = [str(compiler), '-std=c99', '-pedantic-errors', '-' + optimization,
                            '-Wall', '-Wextra', '-Werror', '-Wformat=2', '-fPIC',
                            '-I', str(candidate / 'csrc'), '-I', str(candidate / 'csrc/app'),
                            '-c', str(overlay / 'fx_device_protocol.c'), '-o', str(protocol_object)]
        subprocess.run(protocol_command, cwd=ROOT, check=True,
                       env=dict(os.environ, TMPDIR=str(tmp)))
        command = [str(compiler), '-std=c99', '-' + optimization,
                   '-Wall', '-Wextra', '-Werror', '-Wformat=2', '-shared', '-fPIC',
                   '-Wl,--no-undefined', '-I', str(candidate / 'csrc'),
                   '-I', str(candidate / 'csrc/app'),
                   *[str(candidate / name) for name in sources],
                   str(protocol_object), str(adapter), '-o', str(lib_path)]
        subprocess.run(command, cwd=ROOT, check=True,
                       env=dict(os.environ, TMPDIR=str(tmp)))
        libraries.append(lib_path)
        compiled_pins = {str(path): digest(path) for path in (lib_path, protocol_object)}
        lib = C.CDLL(str(lib_path))
        lib.protocol_create_seed.argtypes = [C.c_void_p]
        lib.protocol_create_seed.restype = C.c_void_p
        lib.fx_device_session_json.argtypes = [C.c_void_p]
        lib.fx_device_session_json.restype = C.c_void_p
        lib.protocol_snapshot_fields.argtypes = [C.c_void_p, C.c_void_p]
        lib.fx_device_session_read_ram.argtypes = [C.c_void_p, C.c_uint16, C.c_void_p, C.c_size_t]
        lib.fx_device_session_step.argtypes = [C.c_void_p, C.c_void_p, C.c_uint8]
        lib.fx_device_session_submit_pair.argtypes = [C.c_void_p, C.c_uint8, C.c_uint8]
        for name in ('reset', 'release', 'ack_timer', 'take_callback', 'destroy'):
            getattr(lib, 'fx_device_session_' + name).argtypes = [C.c_void_p]
        lib.fx_device_session_ack_timer.argtypes = [C.c_void_p, C.c_void_p]
        lib.fx_device_session_destroy.restype = None
        session = None
        sequence = None
        matched = set()
        expected_positions = {}
        observations = []
        statuses = set()
        checks = {'json_schema': 0, 'native_checkpoint': 0,
                  'snapshot_binding': 0, 'read_only_ram_and_state': 0,
                  'callback_preserved_until_drain': 0, 'null_guard': 0}

        def ram():
            output = (C.c_uint8 * 65536)()
            assert lib.fx_device_session_read_ram(session, 0, output, len(output)) == 0
            return bytes(output)

        def fields():
            output = (C.c_int64 * (len(FIELDS) + len(REQUEST_FIELDS)))()
            assert lib.protocol_snapshot_fields(session, output) == 0
            return list(output)

        def observe(label):
            before_ram = ram()
            before_fields = fields()
            pointers = []
            texts = []
            try:
                for _ in range(3):
                    pointer = lib.fx_device_session_json(session)
                    assert pointer and pointer not in pointers
                    pointers.append(pointer)
                    texts.append(C.string_at(pointer).decode('ascii'))
                assert texts[0] == texts[1] == texts[2]
                obj = json.loads(texts[0], object_pairs_hook=unique_object)
                assert len(texts[0]) < 4096
                assert set(obj) == set(FIELDS) | {'status', 'mode', 'submode', 'screen',
                                                 'request', 'width', 'height', 'framebuffer'}
                assert set(obj['request']) == set(REQUEST_FIELDS)
                assert all(type(obj[name]) is int for name in FIELDS + ('mode', 'submode', 'screen', 'width', 'height'))
                assert all(type(obj['request'][name]) is int for name in REQUEST_FIELDS)
                assert obj['status'] == STATUS_NAMES[obj['runtime_status']]
                assert obj['width'] == 96 and obj['height'] == 32
                assert re.fullmatch('[0-9a-f]{768}', obj['framebuffer'])
                checks['json_schema'] += 1
                assert [obj[name] for name in FIELDS] + [obj['request'][name] for name in REQUEST_FIELDS] == before_fields
                assert bytes.fromhex(obj['framebuffer']) == b''.join(before_ram[0xf800 + 16 * y:0xf800 + 16 * y + 12] for y in range(32))
                assert (obj['mode'], obj['submode'], obj['screen']) == (before_ram[0x80f9], before_ram[0x80fa], before_ram[0x80fc])
                checks['snapshot_binding'] += 1
                assert ram() == before_ram and fields() == before_fields
                checks['read_only_ram_and_state'] += 1
                statuses.add(obj['status'])
                key = (sequence, label)
                if key in expected:
                    position = expected_positions.get(key, 0)
                    assert position < len(expected[key])
                    record = expected[key][position]
                    expected_positions[key] = position + 1
                    checkpoint = (*key, position)
                    assert checkpoint not in matched
                    assert obj['framebuffer'] == record['framebuffer']
                    assert (obj['mode'], obj['submode'], obj['screen'], obj['host_wait'], obj['key_columns'], obj['key_rows']) == tuple(record['settings_and_packet'])
                    assert obj['callback_pending'] == record['original_callback']
                    checks['native_checkpoint'] += 1
                    assert lib.fx_device_session_take_callback(session) == record['original_callback']
                    assert fields()[FIELDS.index('callback_pending')] == 0
                    checks['callback_preserved_until_drain'] += 1
                    matched.add(checkpoint)
                observations.append({'sequence': sequence, 'label': label,
                                     'json_sha256': bytes_digest(texts[0].encode()),
                                     'ram_sha256': bytes_digest(before_ram),
                                     'original_checkpoint': key in expected,
                                     'status': obj['status'], 'json': obj,
                                     'public_snapshot_fields': before_fields})
                return obj
            finally:
                for pointer in pointers:
                    libc.free(pointer)

        def step(label):
            status = lib.fx_device_session_step(session, None, 0)
            observe(label)
            return status

        def release():
            assert lib.fx_device_session_release(session) == 0

        def raw(token):
            assert lib.fx_device_session_submit_pair(session, *pairs[token]) == 0

        def boot(row):
            nonlocal session, sequence
            if session:
                lib.fx_device_session_destroy(session)
            sequence = row['id']
            if row.get('initial_image') == 'cold':
                session = lib.protocol_create_seed(None)
            else:
                seed = (C.c_uint8 * 65536).from_buffer_copy(unpack(row['initial_ram_zlib_base64']))
                session = lib.protocol_create_seed(seed)
            assert session and lib.fx_device_session_reset(session) == 1
            observe('reset-to-boot-ready')
            for k in range(8):
                step('boot-input:' + str(k))
                if fields()[FIELDS.index('event')] == 5:
                    break
            release()
            assert step('first-key-wait') == 0

        def action(token, label):
            raw(token)
            for k in range(20):
                status = step(label + ':' + str(k))
                if fields()[FIELDS.index('event')] == 5:
                    release()
                    return status
                if status == 4:
                    return status
            raise AssertionError('unbounded action ' + label)

        assert not lib.fx_device_session_json(None)
        checks['null_guard'] += 1
        session = lib.protocol_create_seed(None)
        observe('unstarted-cold-device')
        for sequence_id in SEQUENCES:
            if sequence_id <= 16:
                row = fixture['rows'][sequence_id - 1]
            else:
                row = dict(next(row for row in authored['extensions'] if row['id'] == sequence_id))
                row['initial_ram_zlib_base64'] = fixture['rows'][0]['initial_ram_zlib_base64']
            boot(row)
            if sequence_id in (1, 3):
                for token in (0x31, 0x2b, 0x32, 0xf0):
                    assert action(token, 'arithmetic:' + hex(token)) == 1
                    assert step('next-key-wait') == 0
            elif sequence_id == 13:
                raw(0xe9); assert step('SHIFT') == 0; release()
                raw(0xe4); assert step('SETUP-entry') == 1; assert step('SETUP-wait') == 0; release()
                raw(0x30); assert step('invalid-setup-key-timer') == 3; release()
                assert step('pending-timer-no-ack') == 3
                assert lib.fx_device_session_ack_timer(session, None) == 0; observe('timer-ack')
                raw(0x35); assert step('SETUP-Gra') == 1; release(); assert step('SETUP-return') == 1
                assert step('SETUP-followup-input-entry') == 1
                for k in range(8):
                    step('SETUP-followup-input:' + str(k))
                    if fields()[FIELDS.index('event')] == 5: break
                release(); assert step('SETUP-next-key-wait') == 0
                assert lib.fx_device_session_submit_pair(session, *row['export_pair']) == 0
                assert step('host-status-export') == 2; release(); assert step('export-next-idle') == 0
            elif sequence_id == 14:
                raw(0xe9); assert step('FIX:SHIFT') == 0; release()
                raw(0xe4); assert step('FIX:SETUP-entry') == 1; assert step('FIX:SETUP-wait') == 0; release()
                raw(0x36); assert step('FIX:precision-wait') == 0; release()
                raw(0x34); assert step('FIX:four-digits') == 1; release(); assert step('FIX:SETUP-return') == 1
            elif sequence_id == 16:
                raw(0xe4); assert step('STAT:MODE-entry') == 1; assert step('STAT:MODE-wait') == 0; release()
                raw(0x33); assert step('STAT:submode-wait') == 0; release()
                raw(0x31); assert step('STAT:submode-one') == 1; release(); assert step('STAT:MODE-return') == 1
                assert step('STAT:admission-request') == 4
                assert step('STAT:retain-admission') == 4
            else:
                for op_index, op in enumerate(row['operations']):
                    label = row['group'] + ':' + str(op_index)
                    if op['kind'] == 'key': raw(op['token'])
                    else: assert lib.fx_device_session_submit_pair(session, op['columns'], op['rows']) == 0
                    for k in range(40):
                        status = step(label + ':' + str(k))
                        if fields()[FIELDS.index('event')] == 5 or status in (0, 2, 3, 4, 5): break
                    else: raise AssertionError('unbounded raw operation ' + label)
                    release(); assert status != 4
                    for k in range(40):
                        status = step(label + ':released:' + str(k))
                        if status in (0, 3, 4): break
                    else: raise AssertionError('unbounded release ' + label)
                    assert status == 0
        lib.fx_device_session_destroy(session)
        all_checkpoints = {(*key, position) for key, rows in expected.items() for position in range(len(rows))}
        assert matched == all_checkpoints, sorted(all_checkpoints - matched)
        assert statuses == set(STATUS_NAMES.values()), statuses
        compiled_end_pins = {path: digest(path) for path in compiled_pins}
        assert compiled_pins == compiled_end_pins
        reports.append({'optimization': optimization, 'sequences': len(SEQUENCES),
                        'observations': len(observations), 'json_calls': 3 * len(observations),
                        'checks': checks, 'total_logical_checks': sum(checks.values()),
                        'statuses': sorted(statuses), 'observations_detail': observations,
                        'command': command, 'protocol_strict_c99_command': protocol_command,
                        'library_sha256': digest(lib_path), 'protocol_object_sha256': digest(protocol_object),
                        'artifact_pre_pins': compiled_pins, 'artifact_post_pins': compiled_end_pins})
    assert reports[0]['observations_detail'] == reports[1]['observations_detail']
    end_pins = {path: digest(path) for path in pins}
    assert pins == end_pins, [path for path in pins if pins[path] != end_pins[path]]
    report = {'status': 'pass', 'full_firmware_complete': False,
              'candidate_root': str(candidate), 'original_archive_sha256': native['original_archive']['sha256'],
              'original_proof_sha256': native['original_proof']['sha256'], 'original_executions_this_test': 0,
              'compiled_source_count': len(sources) + 2, 'closed_c_header_inputs': len(closed),
              'pre_pins': pins, 'post_pins': end_pins, 'source_changes': [],
              'optimizations': reports,
              'limits': ['Original checkpoints are frozen previous executions, not fresh original runs.',
                         'Eight exact authored raw-key recipes and 206 original checkpoints are selected.',
                         'Original comparisons cover LCD, settings, raw packet/MMIO bytes and original callback only. Named controller fields are current public-snapshot-to-JSON binding checks, not native expected outputs.',
                         'Full device completion is not claimed; STAT admission stays a typed pending request.',
                         'Archived callback observations are all zero; nonzero callbacks are not covered.',
                         'New protocol unit is pedantic strict C99; existing whole core uses its intentional unsigned __int128 formatter extension.',
                         'Allocator failure injection and real browser/WASM ABI are outside this C JSON test.']}
    report_path.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'status': 'pass', 'original_checkpoints_per_optimization': checkpoint_count,
                      'observations_per_optimization': reports[0]['observations'],
                      'json_calls_per_optimization': reports[0]['json_calls'],
                      'logical_checks_per_optimization': reports[0]['total_logical_checks'],
                      'original_executions_this_test': 0, 'source_changes': [],
                      'report': str(report_path)}))


if __name__ == '__main__':
    main()
