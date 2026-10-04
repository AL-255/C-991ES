#!/usr/bin/env python3
"""Compare complete finite sum/product expressions and cancellation with ROM."""
import argparse
import ctypes as C
import json
import random
import subprocess

from c_verification import ROOT, write_report
from c_build_inputs import implementation_inputs
from test_eval_variables_c import Number, Options, Result, Variables, SOURCES
from test_numeric_calculus_c import Control, Cancel


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--random-cases', type=int, default=1000)
    ap.add_argument('--no-report', action='store_true')
    args = ap.parse_args()
    build = ROOT / 'analysis/build/eval-calculus'
    build.mkdir(parents=True, exist_ok=True)
    target = build / 'eval-calculus.so'
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-shared', '-fPIC', *[str(ROOT / 'csrc' / p) for p in SOURCES],
                    '-o', str(target)], check=True)
    lib = C.CDLL(str(target))
    lib.fx_evaluate_controlled.argtypes = [C.POINTER(C.c_uint8), C.c_size_t,
                                         C.POINTER(Options), C.POINTER(Variables),
                                         C.POINTER(Control), C.POINTER(Result)]
    lib.fx_evaluate_controlled.restype = C.c_int
    lib.fx_decimal_parse.argtypes = [C.POINTER(Number), C.c_char_p]
    native_path = build / 'calculus-oracle.so'
    adapter = 'tools/nxu8/calculus_host_events.c'
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
                    str(ROOT / adapter), str(ROOT / 'tools/nxu8/vendor/SimU8/core.c'),
                    '-o', str(native_path)], check=True)
    native = C.CDLL(str(native_path))
    native.harness_init.argtypes = [C.c_void_p, C.c_size_t]
    native.harness_ram.restype = C.POINTER(C.c_uint8 * 65536)
    native.harness_set_reg.argtypes = [C.c_uint, C.c_uint8]
    native.harness_get_reg.argtypes = [C.c_uint]
    native.harness_get_reg.restype = C.c_uint8
    native.calculus_oracle_call.argtypes = [C.c_uint32, C.c_uint64, C.c_uint]
    native_x = ((C.c_uint8 * 10) * 256).in_dll(native, 'calculus_oracle_x')
    callback_count = C.c_uint.in_dll(native, 'calculus_oracle_callbacks')
    poll_count = C.c_uint.in_dll(native, 'calculus_oracle_polls')
    rom = (ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    rom_buffer = C.create_string_buffer(rom)
    rng = random.Random(0x69c43a2)
    failures, counts = [], {}

    def decimal(text):
        n = Number(); assert lib.fx_decimal_parse(C.byref(n), str(text).encode()) == 0
        return bytes(n)

    def check(tokens, group, math_output=1, unit=4, initial_x=None, initial_a=None, abort=0, fixture=None):
        native.harness_init(rom_buffer, len(rom))
        ram = native.harness_ram().contents
        for address, byte in ((0x80f9, 0xc1), (0x80fc, 1), (0x80f5, 0xf0),
                              (0x8105, unit), (0x8106, math_output), (0x8121, 1)):
            ram[address] = byte
        raw = tokens+b'\0'
        for i, byte in enumerate(raw): ram[0x8200+i] = byte
        ram[0x8190] = 0; ram[0x8191] = 0x82
        ram[0x812c] = 0; ram[0x812d] = 0x82
        values = Variables()
        values.values[8][0] = Number.from_buffer_copy(initial_x or decimal(37))
        values.values[2][0] = Number.from_buffer_copy(initial_a or decimal(2))
        before = bytes(values)
        for slot in range(10):
            for part, base in ((0, 0x8226), (1, 0x8408)):
                for i, byte in enumerate(bytes(values.values[slot][part])): ram[base+10*slot+i] = byte
        for i, byte in enumerate((0x90, 0x81, 0, 0x83)): native.harness_set_reg(i, byte)
        assert native.calculus_oracle_call(0x171f4, 30000000, abort) == 100, tokens.hex()
        expected_bank = Variables()
        for slot in range(10):
            for part, base in ((0, 0x8226), (1, 0x8408)):
                expected_bank.values[slot][part] = Number.from_buffer_copy(bytes(ram[base+10*slot:base+10*slot+10]))
        expected = [native.harness_get_reg(0), bytes(ram[0x8300:0x8314]).hex(),
                    ram[0x8190]+256*ram[0x8191]-0x8200, bytes(expected_bank).hex(), poll_count.value]
        observed = []

        def cancel(_):
            observed.append(bytes(values.values[8][0]).hex())
            return bool(abort and len(observed) == abort)

        cancel_callback = Cancel(cancel)
        control = Control(cancel_callback, None)
        input_buffer = (C.c_uint8 * len(raw)).from_buffer_copy(raw)
        result = Result()
        status = lib.fx_evaluate_controlled(input_buffer, len(raw), C.byref(Options(0xc1, math_output, unit)),
                                           C.byref(values), C.byref(control), C.byref(result))
        actual = [status, bytes(result.value).hex(), result.consumed, bytes(values).hex(), len(observed)]
        callback_x = [bytes(native_x[i]).hex() for i in range(callback_count.value)]
        if fixture:
            saved = [fixture['native_status'], fixture['value'], fixture['consumed'],
                     fixture['final_x'], fixture['callback_x'], fixture['polls']]
            rerun = [expected[0], expected[1], expected[2], bytes(expected_bank.values[8][0]).hex(),
                     callback_x, expected[4]]
            assert saved == rerun, (fixture['name'], 'saved native fixture is not reproducible', saved, rerun)
        assert bytes(input_buffer) == raw
        counts[group] = counts.get(group, 0)+1
        if actual != expected or observed[:len(callback_x)] != callback_x:
            failure = {'tokens': tokens.hex(), 'group': group, 'math_output': math_output,
                       'angle_unit': unit, 'abort': abort, 'initial_variables': before.hex(),
                       'actual': actual, 'expected': expected, 'native_callback_x': callback_x,
                       'host_poll_x': observed, 'unsupported_token': result.unsupported_token}
            failures.append(failure)
            if len(failures) <= 15: print(json.dumps(failure))

    fixture_path = ROOT / 'analysis/regressions/calculus-grammar.json'
    for row in json.loads(fixture_path.read_text())['fixtures']:
        check(bytes.fromhex(row['tokens']), 'native_grammar_and_cursor_regressions',
              row['math_output'], initial_x=bytes.fromhex(row['initial_x']),
              initial_a=bytes.fromhex(row['initial_A']), abort=row['abort_poll'], fixture=row)
    bodies = [b'X', b'X\x75', b'X\x76', b'1\x4fX', b'\x98X)', b'\xa0X)',
              b'\xa3X)', b'\x731\x4fX)', b'A\x4eX+A', b'(X+1)\x4f(X-1)',
              b'\x682,X+3)', b'\x88X)', b'(X^2)+1)', b'X\x57', b'X\x25', b'X\xbf2']
    for index in range(args.random_cases):
        low = rng.randrange(-5, 6)
        high = low+rng.randrange(0, 8)
        left = str(low).encode().replace(b'-', b'\x60')
        right = str(high).encode().replace(b'-', b'\x60')
        # Stored bounds and nested ordinary functions use the same grammar.
        body = rng.choice(bodies)
        operation = rng.choice((0x69, 0x5d))
        expression = bytes([operation])+body+b','+left+b','+right+b')'
        x = rng.choice([decimal(37), bytes.fromhex('80000001000201020100'),
                        bytes.fromhex('21a30000000000000301')])
        a = rng.choice([decimal('1.23456789012345'), decimal('1e99'), decimal(-3),
                        bytes.fromhex('80000001000201010100')])
        math_output, unit = index % 2, 4+index % 3
        check(expression, 'random_complete_calculus_expressions', math_output, unit, x, a)
        check(expression+b'+A', 'random_outer_arithmetic', math_output, unit, x, a)
        check(expression, 'random_cancellation', math_output, unit, x, a, rng.randrange(1, high-low+3))
    data = {'cases': sum(counts.values()), 'domains': counts, 'failures': failures,
            'comparison': 'Complete171F4 native status, both records, consumed pointer, all variable records, callback X order and cancellation-poll count.',
            'scope': 'Prepared COMP finite sum/product expressions through shared variable grammar; preflight, bound evaluation, implicit closing, errors, native X restoration and explicit host cancellation. Integral/derivative/solver and physical scheduling remain pending.'}
    if failures:
        (build / 'failures.json').write_text(json.dumps(data, indent=2)+'\n')
        raise AssertionError(f'{len(failures)} full calculus-expression mismatches')
    if not args.no_report:
        data = write_report('analysis/c-verification/eval_calculus.json', data,
                            implementation_inputs(ROOT, ['csrc/'+p for p in SOURCES])+
                            [adapter, str(fixture_path.relative_to(ROOT)), 'tools/test_eval_variables_c.py',
                             'tools/test_eval_complex_c.py', 'tools/test_numeric_calculus_c.py', 'tools/c_verification.py',
                             'tools/c_build_inputs.py', 'tools/trace_natural_result.py', 'tools/verify_firmware.py', 'tools/nxu8/decoder.py'],
                            'tools/test_eval_calculus_c.py')
    print(json.dumps({'status': 'pass', 'cases': data['cases'], 'domains': counts}, indent=2))


if __name__ == '__main__': main()
