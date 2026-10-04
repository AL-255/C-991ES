#!/usr/bin/env python3
"""Compare complete prepared BASE-N expressions with original171F4."""
import argparse
import ctypes as C
import json
import random
import subprocess
from collections import Counter

from c_build_inputs import implementation_inputs
from c_verification import ROOT, write_report
from nxu8.machine import Machine
from trace_natural_result import settings
from test_eval_variables_c import Number, Options, Result, Variables, SOURCES

FIXTURES = 'analysis/regressions/base-expression-grammar.json'


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--random-cases', type=int, default=2000)
    ap.add_argument('--fixture-only', action='store_true')
    ap.add_argument('--no-report', action='store_true')
    args = ap.parse_args()
    if args.fixture_only and not args.no_report:
        ap.error('Partial fixture runs cannot publish the canonical report')
    build = ROOT / 'analysis/build/eval-base'
    build.mkdir(parents=True, exist_ok=True)
    shared = build / 'eval-base.so'
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-shared', '-fPIC', *[str(ROOT / 'csrc' / p) for p in SOURCES],
                    '-o', str(shared)], check=True)
    lib = C.CDLL(str(shared))
    lib.fx_evaluate_base_n.argtypes = [C.POINTER(C.c_uint8), C.c_size_t,
        C.c_uint8, C.POINTER(Options), C.POINTER(Variables), C.POINTER(Number), C.POINTER(Result)]
    lib.fx_evaluate_base_n.restype = C.c_int
    lib.fx_evaluate_with_variables.argtypes = [C.POINTER(C.c_uint8), C.c_size_t,
        C.POINTER(Options), C.POINTER(Variables), C.POINTER(Result)]
    lib.fx_evaluate_with_variables.restype = C.c_int
    lib.fx_decimal_parse.argtypes = [C.POINTER(Number), C.c_char_p]
    corpus = json.loads((ROOT / FIXTURES).read_text())
    failures = []
    groups = Counter()

    def variable_bank(records):
        bank = Variables()
        for slot, pair in enumerate(records):
            for part, record in enumerate(pair):
                bank.values[slot][part] = Number.from_buffer_copy(bytes.fromhex(record))
        return bank

    def evaluate(raw, base, math_output, bank, secondary, unit=4):
        input_buffer = (C.c_uint8 * len(raw)).from_buffer_copy(raw)
        result = Result()
        status = lib.fx_evaluate_base_n(input_buffer, len(raw), base,
            C.byref(Options(2, math_output, unit)), C.byref(bank), C.byref(secondary), C.byref(result))
        assert bytes(input_buffer) == raw, 'C evaluator changed input tokens'
        return [status, bytes(result.value).hex(), result.consumed, bytes(bank).hex()]

    def check_fixture(case):
        raw = bytes.fromhex(case['tokens']) + b'\0'
        bank = variable_bank(case['initial_variables'])
        secondary = Number.from_buffer_copy(b'\xee' * 10)
        actual = evaluate(raw, case['selected_base'], case['math_output'], bank, secondary)
        expected = [case['firmware_status'], case['result20'], case['consumed'],
                    bytes(variable_bank(case['final_variables'])).hex()]
        assert case['native_exception'] is None and case['final_pc'] == '0x2fffe'
        assert case['input_immutable'] and case['final_temporary_mask'] == 0
        assert case['final_selected_base'] == case['selected_base']
        groups['saved:' + case['label']] += 1
        if actual != expected:
            failures.append({'tokens': case['tokens'], 'base': case['selected_base'],
                'group': case['label'], 'math_output': case['math_output'],
                'expected': expected, 'actual': actual})

    for case in corpus['cases']:
        check_fixture(case)

    if not args.fixture_only:
        oracle = Machine((ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes(), build / 'oracle')
        rng = random.Random(0x215171f4)

        def decimal(value):
            record = Number()
            assert lib.fx_decimal_parse(C.byref(record), str(value).encode()) == 0
            return record

        def live(tokens, base, bank, group, math_output=1, unit=4):
            raw = tokens + b'\0'
            original_bank = bytes(bank)
            secondary_bytes = bytes(rng.randrange(256) for _ in range(10))
            secondary = Number.from_buffer_copy(secondary_bytes)
            oracle.reset(); settings(oracle)
            oracle.ram[0x80f9] = 2; oracle.ram[0x80fc] = 1
            oracle.ram[0x80fa] = base; oracle.ram[0x8106] = math_output
            oracle.ram[0x8105] = unit
            for slot in range(10):
                for part, address in ((0, 0x8226), (1, 0x8408)):
                    for index, byte in enumerate(bytes(bank.values[slot][part])):
                        oracle.ram[address + 10 * slot + index] = byte
            for index, byte in enumerate(raw): oracle.ram[0x8600 + index] = byte
            for index in range(20): oracle.ram[0x8900 + index] = 0xee
            for index, byte in enumerate(secondary_bytes): oracle.ram[0x890a + index] = byte
            oracle.word(0x8190, 0x8600)
            oracle.er(0, 0x8190); oracle.er(2, 0x8900)
            oracle.call(0x171f4, limit=3000000)
            native_bank = Variables()
            for slot in range(10):
                for part, address in ((0, 0x8226), (1, 0x8408)):
                    native_bank.values[slot][part] = Number.from_buffer_copy(
                        bytes(oracle.ram[address + 10 * slot:address + 10 * slot + 10]))
            expected = [oracle.reg(0), bytes(oracle.ram[0x8900:0x8914]).hex(),
                        oracle.word(0x8190) - 0x8600, bytes(native_bank).hex()]
            actual = evaluate(raw, base, math_output, bank, secondary, unit)
            assert bytes(oracle.ram[0x8600:0x8600+len(raw)]) == raw
            assert oracle.ram[0x80fa] == base and oracle.ram[0x8125] == 0
            groups[group] += 1
            if actual != expected:
                failures.append({'tokens': tokens.hex(), 'base': base, 'group': group,
                    'math_output': math_output, 'angle_unit': unit,
                    'initial_variables': original_bank.hex(), 'expected': expected, 'actual': actual})

        loads = [0x54, 0x8b, 0x41, 0x42, 0x43, 0x44, 0x45, 0x46, 0x58, 0x59]
        stores = [0x4b, 0x47, 0x48, 0x49, 0x4a, 0x83, 0x84, 0x4c, 0x4d, 0x99, 0xa9]
        functions = [0x61, 0x62, 0x63, 0x98, 0xa8, 0xa0, 0xa1, 0xa2, 0x68, 0xa3, 0x73, 0x93]
        for base in (1, 7, 9, 15):
            bank = variable_bank(corpus['cases'][0]['initial_variables'])
            for tokens in (b'1\xae1\xae2', b'\x601\xae1\xae2', b'1\xae2\xae3',
                           b'1\xae(1\x4f2)\xae3', b'(1\xae2)\x75',
                           b'\x63\x601\xae2)', b'1\xae2\x511',
                           b'\xc01)', b'\xc01,2)', b'\xc11)', b'\xc11,2)',
                           b'\xb31\xae3)', b'\xb3\x982))'):
                live(tokens, base, Variables.from_buffer_copy(bytes(bank)), 'mixed-fraction-and-function-admission')
        for index in range(args.random_cases):
            base = (1, 7, 9, 15)[index % 4]
            bank = Variables()
            for slot in range(10):
                bank.values[slot][0] = decimal(str(rng.randrange(-100, 101)) + '.' + str(rng.randrange(10)))
                bank.values[slot][1] = decimal(rng.randrange(-99, 100))
            atoms = [b'\x51' + str(rng.randrange(0, 100)).encode() for _ in range(3)]
            atoms += [bytes([rng.choice(loads)])]
            left, right = rng.choice(atoms), rng.choice(atoms)
            expression = b'(' + left + bytes([rng.choice([0x2b, 0x2d, 0x4e, 0x4f, 0x6e, 0x6f, 0x7e, 0x7f])]) + right + b')'
            live(expression, base, Variables.from_buffer_copy(bytes(bank)), 'random-binary', index % 2)
            live(bytes([rng.choice(functions)]) + expression + b')', base,
                 Variables.from_buffer_copy(bytes(bank)), 'random-prefix', index % 2, 4 + index % 3)
            live(expression + bytes([rng.choice(stores)]), base,
                 Variables.from_buffer_copy(bytes(bank)), 'random-store', index % 2)

    data = {'cases': sum(groups.values()), 'groups': dict(groups), 'failures': failures,
        'comparison': 'Original171F4 status, complete20-byte caller output including retained secondary, consumed cursor, all200 variable bytes, immutable input and mode2 reservation/radix invariants.',
        'scope': 'Prepared BASE-N screen1 with all four radices; value API excludes CPU stack/scratch and bus aliases. Saved fixtures retain their historical constructor hashes and original-ROM results.',
        'saved_native_fixtures': len(corpus['cases'])}
    if failures:
        (build / 'failures.json').write_text(json.dumps(data, indent=2) + '\n')
        print(json.dumps({'cases': data['cases'], 'mismatches': len(failures), 'first_failures': failures[:15]}, indent=2))
        raise AssertionError(f'{len(failures)} BASE-N expression mismatches')
    if not args.no_report:
        data = write_report('analysis/c-verification/eval_base.json', data,
            implementation_inputs(ROOT, ['csrc/' + p for p in SOURCES]) +
            [FIXTURES, 'tools/test_eval_variables_c.py', 'tools/test_eval_complex_c.py',
             'tools/trace_natural_result.py', 'tools/c_verification.py', 'tools/c_build_inputs.py', 'tools/trace_natural_result.py', 'tools/verify_firmware.py', 'tools/nxu8/decoder.py'],
            'tools/test_eval_base_c.py')
    print(json.dumps({'status': 'pass', 'cases': data['cases'], 'groups': dict(groups)}, indent=2))


if __name__ == '__main__': main()
