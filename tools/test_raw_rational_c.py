#!/usr/bin/env python3
"""Prepared rational arithmetic against the unchanged original ROM.

Fixtures contain input bytes only. Every expected result/status and boundary
is observed afresh. Original CPU tools are linked only into the test oracle.
GPL-3.0-or-later.
"""
import argparse
import ctypes as C
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if not (ROOT / 'csrc').is_dir():
    ROOT = Path.cwd().resolve()
sys.path.insert(0, str(ROOT / 'tools'))
from nxu8.machine import Machine
import c_build_inputs
from c_verification import write_report

SOURCES = ['csrc/numeric/fx_raw_rational.c', 'csrc/numeric/fx_numeric.c',
           'csrc/numeric/fx_raw_decimal_parts.c',
           'csrc/numeric/fx_raw_decimal_multiply_add.c',
           'csrc/numeric/fx_raw_decimal_divide.c',
           'csrc/numeric/fx_raw_fraction_convert.c']
FIXTURE = 'analysis/native-fixtures/raw-rational/inputs.json'
CANONICAL_FIXTURE_SHA256 = '4118555923f281ca01d8f883165dbdb62ced0c2a5905af69597e525ad80c65ef'
CANONICAL_GROUP_COUNTS = {'fixed': 3280, 'random': 2000, 'wide': 7600,
                          'focused': 1100, 'marked-prefix': 675,
                          'aligned-source-alias': 160}
ENTRIES = {'add': (0x1c6a4, 0, 0), 'subtract': (0x1c690, 1, 0),
           'multiply': (0x1c6cc, 2, 0), 'divide': (0x1c6b8, 3, 0),
           'fraction-preferred-divide': (0x1ca3e, 3, 1)}
OUTPUT_ALIASES = [('separate', 88), ('left', 16), ('right', 48),
                  ('left-before', 14), ('left+2', 18), ('left+4', 20),
                  ('left+8', 24), ('right-before', 46), ('right+2', 50),
                  ('right+4', 52), ('right+8', 56)]

class Number(C.Structure):
    _fields_ = [('bytes', C.c_uint8 * 10)]

def pointer(memory, offset):
    return C.cast(C.byref(memory, offset), C.POINTER(Number))

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def validate_fixture(fixture, canonical):
    """Validate input-only schema before any build or original execution."""
    if not isinstance(fixture, dict) or set(fixture) != {'basis', 'instruction_budget', 'rows'}:
        raise ValueError('Fixture must contain only basis, instruction_budget and rows')
    if not isinstance(fixture['basis'], str):
        raise ValueError('Fixture basis must be a string')
    budget = fixture['instruction_budget']
    if type(budget) is not int or budget <= 0:
        raise ValueError('Instruction budget must be a positive integer')
    rows = fixture['rows']
    if not isinstance(rows, list) or not rows:
        raise ValueError('Fixture rows must be a nonempty list')
    required = {'group', 'source_index', 'operation', 'left', 'right',
                'context', 'display', 'digits'}
    allowed = required | {'label', 'source_distance', 'api_domain'}
    counts = {}
    indices = {}
    outside_domain = 0
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or not required <= set(row) or not set(row) <= allowed:
            raise ValueError(f'Row{index} has missing fields or non-input fields')
        group = row['group']
        if not isinstance(group, str) or group not in CANONICAL_GROUP_COUNTS:
            raise ValueError(f'Row{index} has unknown input group')
        if group != 'marked-prefix' and not isinstance(row.get('label'), str):
            raise ValueError(f'Row{index} is missing its input label')
        if 'label' in row and not isinstance(row['label'], str):
            raise ValueError(f'Row{index} has a non-string label')
        source_index = row['source_index']
        if type(source_index) is not int or source_index < 0:
            raise ValueError(f'Row{index} has an invalid source index')
        if not isinstance(row['operation'], str) or row['operation'] not in ENTRIES:
            raise ValueError(f'Row{index} has an invalid operation')
        for key in ['left', 'right']:
            value = row[key]
            if not isinstance(value, str) or len(value) != 20 or any(c not in '0123456789abcdef' for c in value):
                raise ValueError(f'Row{index} has an invalid10-byte input')
        for key in ['context', 'display', 'digits']:
            if type(row[key]) is not int or not 0 <= row[key] <= 255:
                raise ValueError(f'Row{index} has an invalid byte setting')
        if 'source_distance' in row:
            if group != 'aligned-source-alias' or type(row['source_distance']) is not int or row['source_distance'] not in [0, 2, 4, 8]:
                raise ValueError(f'Row{index} has an invalid aligned-source alias')
        elif group == 'aligned-source-alias':
            raise ValueError(f'Row{index} is missing its aligned-source distance')
        if 'api_domain' in row:
            domain = row['api_domain']
            header = row['left'][:2]
            if group != 'focused' or (domain, header) not in [
                    ('separate-compact-surd', '80'), ('unsupported-scalar-header', '11')]:
                raise ValueError(f'Row{index} has an invalid outside-domain label')
            outside_domain += 1
        counts[group] = counts.get(group, 0) + 1
        indices.setdefault(group, []).append(source_index)
    if canonical:
        if len(rows) != 14815 or counts != CANONICAL_GROUP_COUNTS or budget != 1000000 or outside_domain != 20:
            raise ValueError('Canonical input corpus count/groups/budget/domain controls differ')
        for group, count in CANONICAL_GROUP_COUNTS.items():
            if sorted(indices[group]) != list(range(count)):
                raise ValueError('Canonical source-index inventory differs: ' + group)
    return rows

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', type=Path, default=ROOT / FIXTURE)
    parser.add_argument('--candidate-source', type=Path,
                        help='Private proposal only; canonical report publication is disabled.')
    parser.add_argument('--private-report', type=Path)
    parser.add_argument('--no-report', action='store_true')
    parser.add_argument('--build-dir', type=Path, default=ROOT / 'analysis/build/raw_rational')
    args = parser.parse_args()
    if args.candidate_source and not args.private_report:
        parser.error('--candidate-source requires --private-report')
    canonical_fixture = args.fixture.resolve() == (ROOT / FIXTURE).resolve()
    if not canonical_fixture and not (args.no_report or args.private_report):
        parser.error('A custom --fixture requires --no-report or --private-report')
    if args.private_report and args.private_report.resolve().is_relative_to(
            (ROOT / 'analysis/c-verification').resolve()):
        parser.error('A private report must be outside analysis/c-verification')
    try:
        fixture = json.loads(args.fixture.read_text())
        rows = validate_fixture(fixture, canonical_fixture)
        if canonical_fixture and digest(args.fixture) != CANONICAL_FIXTURE_SHA256:
            raise ValueError('Canonical input-only fixture hash differs')
    except (ValueError, OSError) as error:
        parser.error(str(error))
    build = args.build_dir.resolve()
    build.mkdir(parents=True, exist_ok=True)
    source_paths = [ROOT / s for s in SOURCES]
    if args.candidate_source:
        source_paths[0] = args.candidate_source.resolve()
    declared = SOURCES[1:] if args.candidate_source else SOURCES
    inputs = [*[ROOT / p for p in c_build_inputs.implementation_inputs(ROOT, declared)],
              args.fixture.resolve(), Path(__file__).resolve(),
              ROOT / 'tools/c_verification.py', ROOT / 'tools/c_build_inputs.py',
              ROOT / 'tools/nxu8/machine.py', ROOT / 'tools/nxu8/harness.c',
              ROOT / 'tools/nxu8/vendor/SimU8/core.c',
              ROOT / 'firmware/fx-991es-plus-c-ver4.bin',
              *sorted((ROOT / 'tools/nxu8/vendor/SimU8').glob('*.h'))]
    if args.candidate_source:
        inputs += [source_paths[0], source_paths[0].with_suffix('.h')]
    pins = {str(p): digest(p) for p in inputs}
    implementations = {}
    abi_observations = {}
    abi_source = build / 'number-abi.c'
    abi_source.write_text('#include <stddef.h>\n#include "' +
                          str(source_paths[0].with_suffix('.h')) + '"\n' +
                          'size_t raw_number_size(void) { return sizeof(fx_number); }\n' +
                          'size_t raw_number_offset(void) { return offsetof(fx_number, bytes); }\n' +
                          'size_t raw_number_bytes(void) { return sizeof(((fx_number *)0)->bytes); }\n')
    artifact_pins = {str(abi_source): digest(abi_source)}
    for optimization in ['O2', 'O3']:
        path = build / ('raw-rational-' + optimization + '.so')
        subprocess.run(['gcc', '-std=c99', '-' + optimization, '-Wall', '-Wextra',
                        '-Werror', '-pedantic', '-I', str(ROOT / 'csrc/numeric'),
                        '-shared', '-fPIC', *map(str, source_paths), str(abi_source), '-o', str(path)],
                       check=True)
        library = C.CDLL(str(path))
        call = library.fx_raw_rational_binary
        call.argtypes = [C.POINTER(Number)] * 3 + [C.c_int, C.c_uint,
                                                 C.POINTER(C.c_uint)]
        call.restype = C.c_int
        abi_observations[optimization] = {}
        for name in ['raw_number_size', 'raw_number_offset', 'raw_number_bytes']:
            probe = getattr(library, name)
            probe.argtypes = []
            probe.restype = C.c_size_t
            abi_observations[optimization][name] = probe()
        implementations[optimization] = call
        artifact_pins[str(path)] = digest(path)
    machine = Machine((ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes(),
                      build / 'oracle')
    oracle_artifact = build / 'oracle/nxu8-harness.so'
    artifact_pins[str(oracle_artifact)] = digest(oracle_artifact)
    counts = {}
    failure_count = 0
    failures = []
    boundaries = []
    unsupported = []
    original_instructions = 0
    handled = {'O2': 0, 'O3': 0}

    def check(group, condition, detail):
        nonlocal failure_count
        counts[group] = counts.get(group, 0) + 1
        if not condition:
            failure_count += 1
            if len(failures) < 40:
                failures.append(dict(group=group, **detail))
                print(json.dumps(failures[-1]), flush=True)

    for optimization, abi in abi_observations.items():
        check('abi-number-size', abi['raw_number_size'] == C.sizeof(Number),
              dict(optimization=optimization, actual=abi['raw_number_size']))
        check('abi-number-offset', abi['raw_number_offset'] == Number.bytes.offset,
              dict(optimization=optimization, actual=abi['raw_number_offset']))
        check('abi-number-payload', abi['raw_number_bytes'] == 10,
              dict(optimization=optimization, actual=abi['raw_number_bytes']))

    def host_check(call, optimization, row, expected, native_status, returned,
                   source_distance=None):
        operation, preferred = ENTRIES[row['operation']][1:]
        layouts = [('source-overlap', 16)] if source_distance is not None else OUTPUT_ALIASES
        for alias, output_offset in layouts:
            memory = (C.c_uint8 * 112)(*([0xa7] * 112))
            left_offset = 16
            right_offset = 16 + source_distance if source_distance is not None else 48
            memory[left_offset:left_offset + 10] = bytes.fromhex(row['left'])
            memory[right_offset:right_offset + 10] = bytes.fromhex(row['right'])
            before = bytes(memory)
            # Surround the independent status word with two guard words.
            status_words = (C.c_uint * 3)(0x12345678, 0xdeadbeef, 0x87654321)
            status_pointer = C.cast(C.byref(status_words, C.sizeof(C.c_uint)),
                                    C.POINTER(C.c_uint))
            host = call(pointer(memory, output_offset), pointer(memory, left_offset),
                        pointer(memory, right_offset), operation, preferred,
                        status_pointer)
            detail = dict(optimization=optimization, index=row['index'], alias=alias,
                          operation=row['operation'], host=host,
                          native_status=status_words[1])
            out_of_domain = row.get('api_domain') is not None
            if returned and not out_of_domain:
                wanted = bytearray(before)
                wanted[output_offset:output_offset + 10] = expected
                check('host-status', host == 0, detail)
                check('record-inputs-guards', bytes(memory) == wanted, detail)
                check('native-status', status_words[1] == native_status, detail)
            else:
                check('explicit-boundary-status', host == -3, detail)
                check('boundary-no-record-commit', bytes(memory) == before, detail)
                check('boundary-no-status-commit', status_words[1] == 0xdeadbeef, detail)
            check('status-word-guards', status_words[0] == 0x12345678 and
                  status_words[2] == 0x87654321, detail)
        if returned and not row.get('api_domain'):
            handled[optimization] += 1

    for index, original_input in enumerate(rows):
        row = dict(original_input, index=index)
        machine.reset()
        for address, value in [(0x80f9, row['context']), (0x80fc, 1),
                               (0x8105, row['display']), (0x8106, 1),
                               (0x8107, row['digits'])]:
            machine.ram[address] = value
        right_address = 0x8300 + row['source_distance'] if 'source_distance' in row else 0x8320
        machine.ram[0x8300:0x830a] = bytes.fromhex(row['left'])
        machine.ram[right_address:right_address + 10] = bytes.fromhex(row['right'])
        # The same overlapping physical bytes are consumed by the high-level
        # value API. Original outputs below are never derived from the C code.
        check('fixture-physical-left', bytes(machine.ram[0x8300:0x830a]).hex() == row['left'],
              dict(index=index))
        check('fixture-physical-right', bytes(machine.ram[right_address:right_address + 10]).hex() == row['right'],
              dict(index=index))
        machine.er(0, 0x8300)
        machine.er(2, right_address)
        machine.lib.harness_set_sp(0x8dee)
        machine.lib.harness_set_lr(0x2fffe)
        machine.lib.harness_set_pc(ENTRIES[row['operation']][0])
        stop = machine.lib.harness_run(fixture['instruction_budget'], 0x2fffe, False)
        expected = bytes(machine.ram[0x8300:0x830a])
        native_status = machine.reg(0)
        instructions = sum(machine.counts)
        original_instructions += instructions
        returned = stop == 100
        detail = dict(index=index, group=row['group'], source_index=row['source_index'],
                      operation=row['operation'], left=row['left'], right=row['right'],
                      stop=stop, pc=f'{machine.lib.harness_get_pc():05x}',
                      instructions=instructions, result=expected.hex(),
                      native_status=native_status)
        if not returned:
            check('native-budget-boundary', stop == 103 and instructions == fixture['instruction_budget'], detail)
            boundaries.append(detail)
        if row.get('api_domain'):
            check('unsupported-control-native-return', returned, detail)
            unsupported.append(dict(detail, api_domain=row['api_domain']))
        for optimization, call in implementations.items():
            host_check(call, optimization, row, expected, native_status, returned,
                       row.get('source_distance'))
        if index % 500 == 0:
            print('native', index + 1, 'boundaries', len(boundaries),
                  'failures', failure_count, flush=True)

    for optimization, call in implementations.items():
        memory = (C.c_uint8 * 112)(*([0x97] * 112))
        for operation, preferred in [(-2147483648, 0), (-1, 0), (4, 0),
                                     (2147483647, 0), (0, 1), (1, 1), (2, 1),
                                     (3, 2), (3, 4294967295)]:
            before = bytes(memory)
            status = C.c_uint(0xdeadbeef)
            host = call(pointer(memory, 88), pointer(memory, 16), pointer(memory, 48),
                        operation, preferred, C.byref(status))
            check('invalid-request-status', host == -1, dict(optimization=optimization))
            check('invalid-request-no-commit', bytes(memory) == before and
                  status.value == 0xdeadbeef, dict(optimization=optimization))
        for null_parameter in range(4):
            status = C.c_uint(0xdeadbeef)
            params = [pointer(memory, 88), pointer(memory, 16), pointer(memory, 48),
                      C.pointer(status)]
            params[null_parameter] = None
            before = bytes(memory)
            host = call(params[0], params[1], params[2], 0, 0, params[3])
            check('null-request-status', host == -1, dict(optimization=optimization))
            check('null-request-no-commit', bytes(memory) == before and
                  status.value == 0xdeadbeef, dict(optimization=optimization))
    changed = [p for p, value in pins.items() if digest(p) != value]
    artifact_changes = [p for p, value in artifact_pins.items() if digest(p) != value]
    report = dict(status='pass' if not failure_count and not changed and not artifact_changes else 'fail',
                  cases=sum(counts.values()), native_calls=len(rows),
                  native_returned=len(rows) - len(boundaries),
                  original_instructions=original_instructions,
                  handled_by_optimization=handled, checks=counts,
                  optimization_builds=['O2', 'O3'], output_alias_layouts=11,
                  compiled_number_abi=abi_observations,
                  native_budget_boundaries=boundaries,
                  unsupported_input_controls=unsupported,
                  failure_count=failure_count, failures=failures,
                  source_changes=changed, artifacts_sha256=artifact_pins,
                  artifact_changes=artifact_changes,
                  contract='Scalar records/status/value aliases; physical numerical scratch/MMIO is outside this API.',
                  full_firmware_complete=False)
    if args.private_report:
        report['private_tested_inputs_sha256'] = pins
        args.private_report.write_text(json.dumps(report, indent=2) + '\n')
    elif not args.no_report and report['status'] == 'pass':
        write_report('analysis/c-verification/raw_rational.json', report,
                     SOURCES + [str(args.fixture.relative_to(ROOT))],
                     'tools/test_raw_rational_c.py')
    print(json.dumps({k: v for k, v in report.items() if k not in [
        'private_tested_inputs_sha256', 'artifacts_sha256', 'native_budget_boundaries',
        'unsupported_input_controls']}), flush=True)
    return int(report['status'] != 'pass')

if __name__ == '__main__':
    raise SystemExit(main())
