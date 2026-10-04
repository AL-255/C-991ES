#!/usr/bin/env python3
"""Compare readable real sum/product callbacks with full native expressions.

Original ROM/CPU are test oracles only. The host-event adapter supplies only
the timer/cancel response; all arithmetic and expression callbacks run natively.
GPL-3.0-or-later.
"""
import argparse
import ctypes as C
import json
from pathlib import Path
import random
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from c_verification import write_report


class Number(C.Structure):
    _fields_ = [('bytes', C.c_uint8 * 10)]


class Rational(C.Structure):
    _fields_ = [('numerator', C.c_int64), ('denominator', C.c_uint64), ('flags', C.c_uint8)]


Pointer = C.POINTER(Number)
Function = C.CFUNCTYPE(C.c_int, Pointer, Pointer, C.c_void_p)
Cancel = C.CFUNCTYPE(C.c_int, C.c_void_p)


class Control(C.Structure):
    _fields_ = [('cancelled', Cancel), ('userdata', C.c_void_p)]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--random-cases', type=int, default=1000)
    ap.add_argument('--no-report', action='store_true')
    args = ap.parse_args()
    build = ROOT / 'analysis/build/numeric/calculus'
    build.mkdir(parents=True, exist_ok=True)
    sources = ['csrc/numeric/fx_numeric.c', 'csrc/numeric/fx_calculus.c']
    library = build / 'calculus.so'
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror', '-pedantic',
                    '-fPIC', '-shared', *(str(ROOT / p) for p in sources), '-o', str(library)], check=True)
    lib = C.CDLL(str(library))
    for name in ('sum', 'product'):
        getattr(lib, 'fx_number_' + name).argtypes = [Pointer, Pointer, Pointer, Function,
                                                    C.c_void_p, C.POINTER(Control)]
    lib.fx_decimal_parse.argtypes = [Pointer, C.c_char_p]
    lib.fx_rational_encode.argtypes = [Pointer, C.POINTER(Rational)]
    lib.fx_number_binary.argtypes = [Pointer, Pointer, Pointer, C.c_int]
    lib.fx_number_integer_power.argtypes = [Pointer, Pointer, C.c_int]
    lib.fx_number_sqrt.argtypes = [Pointer, Pointer, C.c_int]
    lib.fx_number_to_decimal.argtypes = [Pointer, Pointer]
    lib.fx_decimal_integer_cleanup.argtypes = [Pointer]
    lib.fx_number_kind.argtypes = [Pointer]
    lib.fx_decimal_to_integer.argtypes = [C.POINTER(C.c_int64), Pointer]
    oracle_library = build / 'calculus-oracle.so'
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror', '-fPIC', '-shared',
                    str(ROOT / 'tools/nxu8/calculus_host_events.c'),
                    str(ROOT / 'tools/nxu8/vendor/SimU8/core.c'), '-o', str(oracle_library)], check=True)
    oracle = C.CDLL(str(oracle_library))
    oracle.harness_init.argtypes = [C.c_void_p, C.c_size_t]
    oracle.harness_ram.restype = C.POINTER(C.c_uint8 * 65536)
    oracle.harness_set_reg.argtypes = [C.c_uint, C.c_uint8]
    oracle.harness_get_reg.argtypes = [C.c_uint]
    oracle.harness_get_reg.restype = C.c_uint8
    oracle.calculus_oracle_call.argtypes = [C.c_uint32, C.c_uint64, C.c_uint]
    rom = (ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    rom_buffer = C.create_string_buffer(rom)
    native_x = ((C.c_uint8 * 10) * 256).in_dll(oracle, 'calculus_oracle_x')
    callback_count = C.c_uint.in_dll(oracle, 'calculus_oracle_callbacks')
    poll_count = C.c_uint.in_dll(oracle, 'calculus_oracle_polls')
    rng = random.Random(0x43a2)
    counts, failures = {}, []

    def literal(text):
        out = Number()
        assert lib.fx_decimal_parse(C.byref(out), str(text).encode()) == 0
        return bytes(out.bytes)

    def rational(numerator, denominator):
        out = Number(); value = Rational(numerator, denominator, 0)
        assert lib.fx_rational_encode(C.byref(out), C.byref(value)) == 0
        return bytes(out.bytes)

    def decimal_record(mantissa, exponent, sign, flags):
        digits = f'{mantissa:015d}'
        return bytes([int(digits[0]) | flags,
                      *(int(digits[i:i + 2], 16) for i in range(1, 15, 2)),
                      int(f'{exponent % 100:02d}', 16), (exponent >= 0) + (5 if sign < 0 else 0)])

    def check(group, actual, expected, detail):
        counts[group] = counts.get(group, 0) + 1
        if actual != expected:
            failures.append({'group': group, 'detail': detail, 'actual': actual, 'expected': expected})

    original_x = literal('37')
    formula_tokens = {'constant': b'A', 'identity': b'X', 'square': b'X\x75',
                      'cube': b'X\x76', 'reciprocal': b'1\x4fX',
                      'affine': b'A\x4eX+D', 'radical': b'\x98X)',
                      'division_error': b'1\x4f0'}

    def native(operation, lower, upper, a, d, formula, abort):
        oracle.harness_init(rom_buffer, len(rom))
        ram = oracle.harness_ram().contents
        ram[0x80f9] = 0xc1; ram[0x80f5] = 0xf0
        ram[0x8105] = 4; ram[0x8106] = 1; ram[0x8121] = 1
        ram[0x812c] = 0; ram[0x812d] = 0x82
        tokens = bytes([0x5d if operation == 'product' else 0x69]) + formula_tokens[formula] + b',B,C)\0'
        for index, byte in enumerate(tokens): ram[0x8200 + index] = byte
        for address, record in [(0x823a, a), (0x8244, lower), (0x824e, upper),
                                (0x8258, d), (0x8276, original_x)]:
            for index, byte in enumerate(record): ram[address + index] = byte
        ram[0x8190] = 0; ram[0x8191] = 0x82
        for index, byte in enumerate([0x90, 0x81, 0, 0x83]): oracle.harness_set_reg(index, byte)
        status = oracle.calculus_oracle_call(0x171f4, 30000000, abort)
        if status != 100: raise AssertionError(('oracle did not return', status, tokens.hex()))
        callbacks = [bytes(native_x[i]).hex() for i in range(callback_count.value)]
        records = bytes(ram[0x8300:0x8314])
        saved = [bytes(ram[address:address + 10]).hex() for address in (0x823a, 0x8244, 0x824e, 0x8258, 0x8276)]
        return oracle.harness_get_reg(0), records, callbacks, poll_count.value, saved, tokens

    def run(operation, lower, upper, a, d, formula, abort=0, alias=0, host_error=0):
        lower_number = Number.from_buffer_copy(lower); upper_number = Number.from_buffer_copy(upper)
        coefficient = Number.from_buffer_copy(a); offset = Number.from_buffer_copy(d)
        result = Number.from_buffer_copy(bytes.fromhex('01234567890123450001'))
        calls, polls = [], []

        def binary(out, left, right, op):
            status = lib.fx_number_binary(out, left, right, op)
            if status == 0: status = lib.fx_decimal_integer_cleanup(out)
            return status

        @Function
        def function(value, x, userdata):
            del userdata
            calls.append(bytes(x.contents.bytes).hex())
            if host_error: return host_error
            if formula == 'constant':
                # Native variable reads convert radicals in calculus mode.
                if lib.fx_number_kind(C.byref(coefficient)) == 8:
                    return lib.fx_number_to_decimal(value, C.byref(coefficient))
                C.memmove(value, C.byref(coefficient), 10); return 0
            if formula == 'identity': C.memmove(value, x, 10); return 0
            if formula in ('square', 'cube'):
                status = lib.fx_number_integer_power(value, x, 2 if formula == 'square' else 3)
            elif formula == 'radical': status = lib.fx_number_sqrt(value, x, 0)
            elif formula == 'affine':
                interim = Number()
                status = binary(C.byref(interim), C.byref(coefficient), x, 2)
                if status == 0: status = binary(value, C.byref(interim), C.byref(offset), 0)
            else:
                one = Number.from_buffer_copy(literal('1'))
                denominator = Number.from_buffer_copy(literal('0')) if formula == 'division_error' else x.contents
                status = binary(value, C.byref(one), C.byref(denominator), 3)
            if status == 0: status = lib.fx_decimal_integer_cleanup(value)
            return status

        @Cancel
        def cancel(userdata):
            del userdata
            polls.append(1)
            return int(bool(abort and len(polls) == abort))

        control = Control(cancel, None)
        target = lower_number if alias == 1 else upper_number if alias == 2 else result
        status = getattr(lib, 'fx_number_' + operation)(C.byref(target), C.byref(lower_number),
                                                        C.byref(upper_number), function, None, C.byref(control))
        return status, bytes(target.bytes), calls, len(polls), bytes(lower_number.bytes), bytes(upper_number.bytes)

    def case(group, operation, lower, upper, a, d, formula, abort=0, aliases=False):
        native_status, native_records, native_calls, native_polls, saved, tokens = native(operation, lower, upper, a, d, formula, abort)
        actual = run(operation, lower, upper, a, d, formula, abort)
        detail = [operation, tokens.hex(), lower.hex(), upper.hex(), a.hex(), d.hex(), abort]
        expected = [0, native_records[:10].hex(), native_calls, native_polls, lower.hex(), upper.hex()]
        got = [actual[0], actual[1].hex(), actual[2], actual[3], actual[4].hex(), actual[5].hex()]
        check(group, got, expected, detail)
        check('native_complete_record_and_status',
              [native_status, native_records[10:].hex(), saved],
              [native_records[0] & 15 if native_records[0] >= 0xf0 else 0, bytes(10).hex(),
               [a.hex(), lower.hex(), upper.hex(), d.hex(), original_x.hex()]], detail)
        if aliases:
            for alias in (1, 2):
                actual = run(operation, lower, upper, a, d, formula, abort, alias)
                check('output_alias_bound', [actual[0], actual[1].hex(), actual[2], actual[3]], expected[:4], detail + [alias])

    one, zero = literal('1'), literal('0')
    named = ['0', '1', '-1', '2', '-2', '.333333333333333', '.999999999999999',
             '1.00000000000001', '1e-99', '1e99', '-1e99', '9.99999999999999e99',
             '123456789012345', '9.99999999999999e-99']
    values = [literal(text) for text in named] + [rational(n, d) for n, d in [(1, 3), (-1, 3), (2, 7), (99, 13), (1, 9999)]]
    values += [bytes.fromhex(s) for s in ['80000001000201020100', '89970199099801990106']]
    values += [bytes([value[0] | 0x40]) + value[1:] for value in values[:len(named)]]
    for operation in ('sum', 'product'):
        for value in values:
            for first, last in [(0, 0), (1, 3), (-3, 3), (4, 5)]:
                case('constant_record_fixtures', operation, literal(first), literal(last), value, zero, 'constant', aliases=True)
        for first, last in [(-9999999999, -9999999999), (9999999999, 9999999999),
                            (-10000000000, -10000000000), (10000000000, 10000000000),
                            (2, 1), (0, 0), (-2, 2)]:
            case('bound_limits', operation, literal(first), literal(last), one, zero, 'identity', aliases=True)
        for bound in [literal('.5'), literal('-1.5'), rational(7, 2), literal('1e-99'), literal('1e99'),
                      literal('1.00000000000001'), literal('.999999999999999'),
                      bytes([0x40]) + bytes(9), bytes([0x41]) + literal('1')[1:]]:
            case('fractional_and_marked_bounds', operation, bound, literal('3'), one, zero, 'constant')
            case('fractional_and_marked_bounds', operation, one, bound, one, zero, 'constant')
        for formula in formula_tokens:
            for first, last in [(-2, 2), (0, 0), (1, 4), (9, 12)]:
                case('complete_expression_formulas', operation, literal(first), literal(last), rational(2, 3), literal('-5'), formula)
        for abort in range(1, 6):
            case('native_cancellation', operation, one, literal('4'), rational(1, 3), zero, 'constant', abort, aliases=True)
        for index in range(args.random_cases):
            first = rng.randrange(-15, 16); last = first + rng.randrange(0, 13)
            formula = rng.choice(list(formula_tokens))
            a = literal(rng.randrange(-999, 1000)) if index % 3 else rational(rng.randrange(-99, 100), rng.randrange(1, 100))
            d = literal(rng.randrange(-99, 100))
            case('random_complete_expressions', operation, literal(first), literal(last), a, d, formula,
                 rng.randrange(1, last-first+3) if index % 7 == 0 else 0, aliases=index % 19 == 0)
            coefficient = decimal_record(rng.randrange(10**14, 10**15), rng.randrange(-99, 100),
                                         rng.choice([-1, 1]), rng.choice([0, 0x40])) if index % 2 else \
                          rational(rng.randrange(-9999, 10000), rng.randrange(1, 10000))
            case('random_numeric_records', operation, literal(first), literal(last), coefficient, zero, 'constant',
                 aliases=index % 29 == 0)

    # A host failure has a different return channel from firmware F1..FF.
    for operation in ('sum', 'product'):
        for host_error in (-1, -2, -3):
            actual = run(operation, one, literal('3'), one, zero, 'constant', host_error=host_error)
            check('host_callback_errors', [actual[0], actual[1].hex(), len(actual[2]), actual[3]],
                  [host_error, '01234567890123450001', 1, 1], [operation, host_error])
        target = Number.from_buffer_copy(one)
        status = getattr(lib, 'fx_number_' + operation)(C.byref(target), C.byref(target), C.byref(target), Function(), None, None)
        check('host_invalid_callback', [status, bytes(target.bytes).hex()], [-1, one.hex()], operation)
        for code in range(1, 16):
            @Function
            def error_callback(value, x, userdata):
                del x, userdata
                C.memmove(value, bytes([0xf0 | code]) + bytes(9), 10)
                return 0
            target = Number()
            bound = Number.from_buffer_copy(one)
            status = getattr(lib, 'fx_number_' + operation)(C.byref(target), C.byref(bound), C.byref(bound), error_callback, None, None)
            check('host_supplied_native_status_records', [status, bytes(target.bytes).hex()],
                  [0, (bytes([0xf0 | code]) + bytes(9)).hex()], [operation, code])

    report = {'cases': sum(counts.values()), 'groups': counts, 'failures': len(failures), 'mismatches': failures,
              'seed': '0x43a2', 'random_cases_per_operation': args.random_cases,
              'scope': 'Real finite sum043A2/product042AE against complete native evaluator expressions, including bounds and callbacks',
              'input': 'Identical scalar bound and coefficient records; native A/B/C/D variables and independent C callback formulas',
              'output': 'All10 result bytes and all20 native result bytes/status; ascending callback X records, cancellation polls, source/variable immutability and output aliases',
              'oracle_host_events': 'Only clear8E00 at5564 for no-cancel timer response, or leave it set at the selected cancellation sample; no ROM/CPU instruction is patched or skipped',
              'limitation': 'Prepared real COMP context; callback expression grammar is native while C callback formulas are independent. Complex callbacks, reset/keyscan execution, malformed BCD and integration/differentiation/solver are outside this suite'}
    path = ROOT / 'analysis/c-verification/numeric_calculus.json'
    if args.no_report:
        (build / 'exploration.json').write_text(json.dumps(report, indent=2) + '\n')
    elif failures:
        report['status'] = 'fail'; path.write_text(json.dumps(report, indent=2) + '\n')
    else:
        write_report(path, report, sources + ['csrc/numeric/fx_numeric.h', 'csrc/numeric/fx_calculus.h',
                                             'csrc/numeric/calculus_manifest.json', 'tools/c_verification.py',
                                             'tools/nxu8/calculus_host_events.c'], 'tools/test_numeric_calculus_c.py')
    print(f'{sum(counts.values())} calculus checks, {len(failures)} mismatches')
    for failure in failures[:30]: print(failure)
    if failures: raise SystemExit(1)


if __name__ == '__main__': main()
