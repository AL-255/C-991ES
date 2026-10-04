#!/usr/bin/env python3
"""Compare coordinate/postfix/retained-pair grammar with live original171F4."""
import argparse
import ctypes as C
import gzip
import hashlib
import json
import random
import subprocess
from pathlib import Path

import c_verification
from c_verification import ROOT, write_report
from c_build_inputs import implementation_inputs
from nxu8.machine import Machine
from trace_natural_result import settings
from test_eval_complex_c import Number, Options, Result
from test_eval_variables_c import SOURCES, Variables

BASE = ROOT / 'analysis/native-fixtures/parser-coordinate-grammar'
TERMINAL = ROOT / 'analysis/native-fixtures/parser-coordinate-terminal'
WATCH = (0x1603e, 0x1615a, 0x16162, 0x161a6, 0x161ac, 0x161f2,
         0x16a7e, 0x16336, 0x16562, 0x16588, 0x18352, 0x18708,
         0x18d78, 0x171ea, 0x171f4, 0x1c138, 0x522a, 0x5550, 0x5564)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def variables_from_ram(machine):
    values = Variables()
    for slot in range(10):
        for part, base in ((0, 0x8226), (1, 0x8408)):
            values.values[slot][part] = Number.from_buffer_copy(
                bytes(machine.ram[base+10*slot:base+10*slot+10]))
    return values


def xy(values, part):
    return bytes(values.values[8][part])+bytes(values.values[9][part])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-report', action='store_true')
    parser.add_argument('--random-cases', type=int, default=0)
    args = parser.parse_args()
    if args.random_cases < 0:
        parser.error('--random-cases must be nonnegative')
    paths = [BASE/'fixtures.json', BASE/'cleanup-order.json', TERMINAL/'fixtures.json.gz']
    fixture_hashes = {str(p.relative_to(ROOT)): digest(p) for p in paths}
    # The common recorder captures JSON inputs automatically. Register this
    # compressed immutable fixture BEFORE compilation so its existing mutation
    # guard pins the exact gzip input too; the shared helper is unchanged.
    gzip_key = str(paths[2].relative_to(ROOT))
    c_verification._BASELINE[gzip_key] = fixture_hashes[gzip_key]
    baseline = json.loads(paths[0].read_text())
    cleanup = json.loads(paths[1].read_text())
    terminal = json.loads(gzip.decompress(paths[2].read_bytes()))
    for name, expected in baseline['provenance'].items():
        if digest(ROOT/name) != expected:
            raise RuntimeError(f'Original baseline evidence changed: {name}')
    rom_path = ROOT/'firmware/fx-991es-plus-c-ver4.bin'
    rom = rom_path.read_bytes()
    if cleanup['rom_sha256'] != digest(rom_path):
        raise RuntimeError('Cleanup fixture ROM differs')
    if terminal['provenance']['rom_sha256'] != digest(rom_path):
        raise RuntimeError('Terminal fixture ROM differs')
    for name, expected in terminal['provenance']['sources'].items():
        if digest(ROOT/name) != expected:
            raise RuntimeError(f'Original terminal evidence changed: {name}')
    rows = [('baseline', row, row) for row in baseline['fixtures']]
    rows += [('cleanup', {'id': f'cleanup-{i:03d}', **row}, row)
             for i, row in enumerate(cleanup['rows'])]
    rows += [('terminal', row['setup'], row['result']) for row in terminal['fixtures']]
    build = ROOT/'analysis/build/eval-coordinate'
    build.mkdir(parents=True, exist_ok=True)
    shared = build/'eval-coordinate.so'
    compiled_inputs = implementation_inputs(ROOT, ['csrc/'+name for name in SOURCES])
    compiled_input_hashes = {name: c_verification._BASELINE[name]
                             for name in compiled_inputs}
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-pedantic', '-shared', '-fPIC',
                    *[str(ROOT/'csrc'/name) for name in SOURCES],
                    '-o', str(shared)], check=True)
    lib = C.CDLL(str(shared))
    lib.fx_evaluate_with_variables.argtypes = [C.POINTER(C.c_uint8), C.c_size_t,
        C.POINTER(Options), C.POINTER(Variables), C.POINTER(Result)]
    lib.fx_evaluate_with_variables.restype = C.c_int
    lib.fx_evaluate_base_n.argtypes = [C.POINTER(C.c_uint8), C.c_size_t, C.c_uint8,
        C.POINTER(Options), C.POINTER(Variables), C.POINTER(Number), C.POINTER(Result)]
    lib.fx_evaluate_base_n.restype = C.c_int
    machine = Machine(rom, build/'oracle')
    failures, counts, native_status_counts = [], {}, {}
    checks = native_fields = 0

    def failure(kind, setup, expected, actual):
        item = {'kind': kind, 'fixture': setup, 'expected': expected, 'actual': actual}
        failures.append(item)
        if len(failures) <= 20:
            print(json.dumps({'kind': kind, 'id': setup['id'], 'input': setup['input'],
                'context': setup['context'], 'selected': setup.get('selected', 0),
                'expected': expected, 'actual': actual}))

    def check(group, setup, saved=None):
        nonlocal checks, native_fields
        raw = bytes.fromhex(setup['input'])
        if not raw.endswith(b'\0'):
            raise ValueError(f"Fixture lacks terminator: {setup['id']}")
        machine.reset(); settings(machine)
        for address, data in setup.get('initial_RAM', {}).items():
            for index, value in enumerate(bytes.fromhex(data)):
                machine.ram[int(address, 16)+index] = value
        for address, value in ((0x80f9, setup['context']),
                (0x80fa, setup.get('selected', 0)), (0x8105, setup.get('unit', 4)),
                (0x8106, setup.get('math', 1)), (0x80fc, setup.get('screen', 1))):
            machine.ram[address] = value
        if group == 'terminal':
            for index in range(24): machine.ram[0x8060+index] = 0xa9
        start = int(setup.get('input_start', '0x8200'), 16)
        output = int(setup.get('output_start', '0x8300'), 16)
        for index, value in enumerate(raw): machine.ram[start+index] = value
        machine.word(0x8190, start); machine.er(0, 0x8190); machine.er(2, output)
        values = variables_from_ram(machine)
        initial_values = bytes(values).hex()
        secondary = Number.from_buffer_copy(bytes(machine.ram[output+10:output+20]))
        try:
            machine.call(0x171f4, limit=5000000)
        except RuntimeError as error:
            failure('original_return', setup, 'normal original171F4 return', str(error))
            counts[group] = counts.get(group, 0)+1
            return
        expected_variables = variables_from_ram(machine)
        expected = {'status': machine.reg(0),
            'records': bytes(machine.ram[output:output+20]).hex(),
            'consumed': (machine.word(0x8190)-start) & 65535,
            'variables_X_Y': xy(expected_variables, 0).hex(),
            'variables_X_Y_imaginary': xy(expected_variables, 1).hex(),
            'variables_all': bytes(expected_variables).hex(),
            'input_unchanged': bytes(machine.ram[start:start+len(raw)]) == raw}
        if saved is not None:
            observed = {key: expected[key] for key in ('status', 'records', 'consumed',
                        'variables_X_Y', 'variables_X_Y_imaginary')}
            observed.update(metadata=bytes(machine.ram[0x8100:0x810b]).hex(),
                            operator_bottom=machine.ram[0x8060])
            if group == 'terminal':
                observed.update(stop=100,
                    final_operators24=bytes(machine.ram[0x8060:0x8078]).hex(),
                    selected_base=machine.ram[0x80fa],
                    polls=int(machine.counts[0x5564//2]),
                    final_pc=f'{machine.lib.harness_get_pc():06x}',
                    final_sp=f'{machine.lib.harness_get_sp():04x}',
                    final_registers16=bytes(machine.reg(i) for i in range(16)).hex(),
                    selected_calls={key: int(machine.counts[int(key, 16)//2])
                                    for key in saved['selected_calls']})
            else:
                observed.update(callbacks={hex(a): int(machine.counts[a//2])
                                           for a in (0x5550, 0x5564)},
                    selected_calls={hex(a): int(machine.counts[a//2])
                                    for a in WATCH if machine.counts[a//2]})
            for key, value in observed.items():
                native_fields += 1
                if saved[key] != value:
                    failure('saved_original_observation', setup,
                            {key: saved[key]}, {key: value})
        guarded = (C.c_uint8*(len(raw)+2))(*([0xa5]+list(raw)+[0x5a]))
        pointer = C.cast(C.byref(guarded, 1), C.POINTER(C.c_uint8))
        result = Result()
        options = Options(setup['context'], setup.get('math', 1), setup.get('unit', 4))
        if setup['context'] == 2:
            status = lib.fx_evaluate_base_n(pointer, len(raw), setup['selected'],
                C.byref(options), C.byref(values), C.byref(secondary), C.byref(result))
        else:
            status = lib.fx_evaluate_with_variables(pointer, len(raw), C.byref(options),
                                                    C.byref(values), C.byref(result))
        actual = {'status': status, 'records': bytes(result.value).hex(),
            'consumed': result.consumed, 'variables_X_Y': xy(values, 0).hex(),
            'variables_X_Y_imaginary': xy(values, 1).hex(),
            'variables_all': bytes(values).hex(),
            'input_unchanged': bytes(guarded)[1:-1] == raw}
        for key in expected:
            checks += 1
            if actual[key] != expected[key]:
                failure('native_vs_c', {**setup, 'initial_variables': initial_values,
                    'unsupported_token': result.unsupported_token},
                    {key: expected[key]}, {key: actual[key]})
        checks += 1
        if guarded[0] != 0xa5 or guarded[-1] != 0x5a:
            failure('input_canaries', setup, [0xa5, 0x5a], [guarded[0], guarded[-1]])
        counts[group] = counts.get(group, 0)+1
        key = str(expected['status'])
        native_status_counts[key] = native_status_counts.get(key, 0)+1

    for group, setup, saved in rows:
        check(group, setup, saved)
    rng = random.Random(0x171f48060)
    for index in range(args.random_cases):
        first, second = rng.randrange(0, 100), rng.randrange(0, 100)
        core = rng.choice([b'\x6c', b'\x6d'])+str(first).encode()+b','+str(second).encode()+b')'
        tokens = rng.choice([core, b'('+core+b')', b'1+'+core, core+b'+1',
                            core+b'\x75', core+b'\xd7', core+b'\x47',
                            core+b',1', core+b'\x47)', b'10\x5f'+core])
        check('random_coordinate_transactions', {'id': f'random-{index:04d}',
              'input': (tokens+b'\0').hex(), 'context': rng.choice((0xc1, 0xc4)),
              'math': rng.randrange(2), 'unit': rng.choice((4, 5, 6)), 'screen': 1,
              'input_start': '0x8600', 'output_start': '0x8900',
              'initial_RAM': {'0x8276': '0900000000000000000108000000000000000006',
                              '0x8458': '0700000000000000000106000000000000000001'}})
    data = {'cases': sum(counts.values()), 'domains': counts, 'checks': checks,
        'live_original_saved_fields': native_fields, 'native_status_counts': native_status_counts,
        'failures': failures, 'fixture_inputs_sha256': fixture_hashes,
        'compiled_inputs_sha256': compiled_input_hashes,
        'compiled_library_sha256': digest(shared),
        'comparison': 'Live original 171F4 status, complete 20-byte caller result, consumed cursor, all ten real/imaginary variable pairs, immutable input and guard canaries; saved native fixture outputs independently rechecked.',
        'scope': 'All 822 baseline, 10 cleanup and 1956 retained-terminal fixtures without unsupported or mismatch filtering. Prepared COMP/CMPLX and selected BASE-N masks; no UI/history or complete CPU-state C parity claim.'}
    (build/'diagnostics.json').write_text(json.dumps(data, indent=2)+'\n')
    if failures:
        raise AssertionError(f'{len(failures)} coordinate-expression mismatches across {data["cases"]} cases')
    if not args.no_report:
        sources = compiled_inputs + [
            'tools/test_eval_variables_c.py', 'tools/test_eval_complex_c.py',
            'tools/trace_natural_result.py', 'tools/verify_firmware.py',
            'tools/nxu8/decoder.py', 'tools/c_build_inputs.py',
            'tools/c_verification.py', *fixture_hashes,
        ]
        data = write_report('analysis/c-verification/eval_coordinate.json',
                            data, sources, 'tools/test_eval_coordinate_c.py')
    print(json.dumps({'status': 'pass', 'cases': data['cases'], 'domains': counts,
                      'checks': checks, 'live_original_saved_fields': native_fields}, indent=2))


if __name__ == '__main__':
    main()
