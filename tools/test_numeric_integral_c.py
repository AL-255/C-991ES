#!/usr/bin/env python3
"""Compare handwritten Gauss-Kronrod integration with complete native expressions.
GPL-3.0-or-later. Original ROM/CPU are test oracles only.
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
from test_numeric_calculus_c import Number, Rational, Pointer, Function, Cancel, Control


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--random-cases', type=int, default=1000)
    ap.add_argument('--no-report', action='store_true')
    args = ap.parse_args()
    build = ROOT / 'analysis/build/numeric/integral'; build.mkdir(parents=True, exist_ok=True)
    sources = ['csrc/numeric/fx_numeric.c', 'csrc/numeric/fx_integral.c']
    library = build / 'integral.so'
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror', '-pedantic',
                    '-shared', '-fPIC', *(str(ROOT / p) for p in sources), '-o', str(library)], check=True)
    lib = C.CDLL(str(library))
    lib.fx_number_integral.argtypes = [Pointer, Pointer, Pointer, Pointer, Function, C.c_void_p, C.POINTER(Control)]
    lib.fx_decimal_parse.argtypes = [Pointer, C.c_char_p]
    lib.fx_rational_encode.argtypes = [Pointer, C.POINTER(Rational)]
    lib.fx_number_binary.argtypes = [Pointer, Pointer, Pointer, C.c_int]
    lib.fx_number_integer_power.argtypes = [Pointer, Pointer, C.c_int]
    lib.fx_number_sqrt.argtypes = [Pointer, Pointer, C.c_int]
    lib.fx_number_to_decimal.argtypes = [Pointer, Pointer]
    lib.fx_number_kind.argtypes = [Pointer]
    lib.fx_decimal_integer_cleanup.argtypes = [Pointer]
    event_library = build / 'integral-oracle.so'
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
                    str(ROOT / 'tools/nxu8/integral_host_events.c'), str(ROOT / 'tools/nxu8/vendor/SimU8/core.c'),
                    '-o', str(event_library)], check=True)
    oracle = C.CDLL(str(event_library)); oracle.harness_init.argtypes = [C.c_void_p, C.c_size_t]
    oracle.harness_ram.restype = C.POINTER(C.c_uint8 * 65536)
    oracle.harness_set_reg.argtypes = [C.c_uint, C.c_uint8]
    oracle.integral_oracle_call.argtypes = [C.c_uint32, C.c_uint64, C.c_uint]
    native_x = ((C.c_uint8 * 10) * 5000).in_dll(oracle, 'integral_oracle_x')
    native_count = C.c_uint.in_dll(oracle, 'integral_oracle_callbacks')
    native_polls = C.c_uint.in_dll(oracle, 'integral_oracle_polls')
    rom = (ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes(); rom_buffer = C.create_string_buffer(rom)
    counts, failures = {}, []
    rng = random.Random(0x46ee)

    def literal(text):
        value = Number(); assert lib.fx_decimal_parse(C.byref(value), str(text).encode()) == 0
        return bytes(value.bytes)

    def rational(n, d):
        value = Number(); assert lib.fx_rational_encode(C.byref(value), C.byref(Rational(n, d, 0))) == 0
        return bytes(value.bytes)

    initial_x = literal('37')
    formulas = {'constant': b'A', 'identity': b'X', 'square': b'X\x75', 'cube': b'X\x76',
                'radical': b'\x98X)', 'reciprocal': b'1\x4fX', 'division_error': b'1\x4f0',
                'shifted_pole': b'1\x4f(X-A)'}

    def native(a, b, tolerance, coefficient, formula, abort):
        oracle.harness_init(rom_buffer, len(rom)); ram = oracle.harness_ram().contents
        for address, value in [(0x80f9, 0xc1), (0x80f5, 0xf0), (0x8105, 4), (0x8106, 1), (0x8121, 1)]: ram[address] = value
        for address, value in [(0x812c, 0x8200), (0x8190, 0x8200)]: ram[address] = value & 255; ram[address+1] = value >> 8
        tokens = b'\x6a' + formulas[formula] + b',B,C' + (b',D' if tolerance is not None else b'') + b')\0'
        for index, value in enumerate(tokens): ram[0x8200 + index] = value
        for address, record in [(0x823a, coefficient), (0x8244, a), (0x824e, b),
                                (0x8258, tolerance or bytes(10)), (0x8276, initial_x)]:
            for index, value in enumerate(record): ram[address+index] = value
        for index, value in enumerate([0x90,0x81,0,0x83]): oracle.harness_set_reg(index, value)
        status = oracle.integral_oracle_call(0x171f4, 200000000, abort)
        assert status == 100, (status, tokens.hex())
        return bytes(ram[0x8300:0x8314]), [bytes(native_x[i]).hex() for i in range(native_count.value)], native_polls.value, bytes(ram[0x8276:0x8280]), tokens

    def run(a, b, tolerance, coefficient, formula, abort, alias=0, host_error=0):
        lower = Number.from_buffer_copy(a); upper = Number.from_buffer_copy(b)
        tol = Number.from_buffer_copy(tolerance) if tolerance is not None else None
        value = Number.from_buffer_copy(coefficient); out = Number.from_buffer_copy(literal('123'))
        calls, polls = [], []

        @Function
        def function(result, x, userdata):
            del userdata
            calls.append(bytes(x.contents.bytes).hex())
            if host_error: return host_error
            if formula == 'constant':
                C.memmove(result, C.byref(value), 10)
                if lib.fx_number_kind(C.byref(value)) == 8: return lib.fx_number_to_decimal(result, result)
                return 0
            if formula == 'identity': C.memmove(result, x, 10); return 0
            if formula in ('square', 'cube'):
                status = lib.fx_number_integer_power(result, x, 2 if formula == 'square' else 3)
            elif formula == 'radical': status = lib.fx_number_sqrt(result, x, 0)
            else:
                one = Number.from_buffer_copy(literal('1'))
                zero = Number.from_buffer_copy(bytes(10))
                divisor = x
                if formula == 'division_error': divisor = C.byref(zero)
                if formula == 'shifted_pole':
                    status = lib.fx_number_binary(C.byref(zero), x, C.byref(value), 1)
                    if status != 0: return status
                    status = lib.fx_decimal_integer_cleanup(C.byref(zero))
                    if status != 0: return status
                    divisor = C.byref(zero)
                status = lib.fx_number_binary(result, C.byref(one), divisor, 3)
            if status == 0: status = lib.fx_decimal_integer_cleanup(result)
            return status

        @Cancel
        def cancel(userdata):
            del userdata
            polls.append(1); return int(bool(abort and len(polls) == abort))

        control = Control(cancel, None)
        target = lower if alias == 1 else upper if alias == 2 else tol if alias == 3 else out
        status = lib.fx_number_integral(C.byref(target), C.byref(lower), C.byref(upper),
                                         C.byref(tol) if tol is not None else None, function, None, C.byref(control))
        return status, bytes(target.bytes), calls, len(polls)

    def case(group, first, last, tolerance, coefficient, formula, abort=0, aliases=False):
        records, xs, polls, restored, tokens = native(first, last, tolerance, coefficient, formula, abort)
        actual = run(first, last, tolerance, coefficient, formula, abort)
        expected = [0, records[:10].hex(), xs, polls]
        detail = [tokens.hex(), first.hex(), last.hex(), tolerance.hex() if tolerance is not None else None, coefficient.hex(), abort]
        def check(name, got, wanted):
            counts[name] = counts.get(name, 0) + 1
            if got != wanted: failures.append({'group': name, 'detail': detail, 'actual': got, 'expected': wanted})
        check(group, [actual[0], actual[1].hex(), actual[2], actual[3]], expected)
        check('native_imaginary_zero_and_X_restore', [records[10:].hex(), restored.hex()], [bytes(10).hex(), initial_x.hex()])
        if aliases:
            for alias in range(1, 4 if tolerance is not None else 3):
                actual = run(first, last, tolerance, coefficient, formula, abort, alias)
                check('output_alias', [actual[0], actual[1].hex(), actual[2], actual[3]], expected)

    one, zero = literal('1'), literal('0')
    for formula in formulas:
        for lower, upper in [('0','1'), ('1','0'), ('-1','1'), ('1','1'), ('1','3'), ('-3','-1'), ('.01','10')]:
            case('formula_fixtures', literal(lower), literal(upper), None, one, formula, aliases=True)
    for tolerance in ['0', '-.01', '1e-99', '1e-10', '1e-5', '.1', '1', '1e99']:
        for formula in ['constant', 'square', 'radical']:
            case('tolerance_fixtures', zero, one, literal(tolerance), one, formula, aliases=True)
    for coefficient in [literal(s) for s in ['0','1','-1','.333333333333333','1e-99','1e99','9e99']] + \
                       [rational(1,3), rational(-2,7), bytes.fromhex('80000001000201020100')]:
        case('coefficient_records', zero, one, None, coefficient, 'constant', aliases=True)
    def marked(record):
        return bytes([record[0] | 0x40]) + record[1:]
    for first, last in [(rational(1,3),rational(2,3)),
                        (rational(-2,7),rational(3,7)),
                        (bytes.fromhex('80000001000201020100'),literal('2')),
                        (marked(zero),marked(one)),
                        (literal('1e-99'),literal('2e-99')),
                        (literal('1e-80'),literal('2e-80')),
                        (literal('1e40'),literal('2e40')),
                        (literal('1e99'),literal('2e99')),
                        (literal('1'),literal('1.00000000000001'))]:
        for formula in ['constant','identity','square']:
            case('bound_records_and_range',first,last,None,one,formula,aliases=True)
    for coefficient in [marked(one),marked(literal('.123456789012345')),marked(rational(1,3))]:
        # Marked rational variables are rejected by the expression's scan
        # pass, before the scalar integration API is entered.
        if coefficient[0] & 0x20: continue
        case('marked_callback_records',zero,one,None,coefficient,'constant',aliases=True)
    for coefficient in [literal('.314159265358979'),literal('.1'),rational(1,3)]:
        case('interior_pole_refinement',zero,one,literal('0'),coefficient,'shifted_pole',aliases=True)
    for tolerance in [rational(1,1000),marked(literal('1e-5')),bytes.fromhex('80000001000201020100')]:
        case('tolerance_records',zero,one,tolerance,one,'radical',aliases=True)
    for formula in ['constant', 'radical']:
        for abort in [1,2,7,8,20]: case('native_cancellation', zero, one, None, one, formula, abort, True)
    for index in range(args.random_cases):
        a = rng.randrange(-20,21); b = rng.randrange(-20,21)
        coefficient = rational(rng.randrange(-99,100), rng.randrange(1,100)) if index % 2 else literal(rng.randrange(-99,100))
        case('random_formulas', literal(a), literal(b), None, coefficient, rng.choice(list(formulas)), aliases=index % 13 == 0)
        scale = rng.randrange(-80,41)
        first = literal(f'{rng.randrange(-99999,100000)}e{scale}')
        last = literal(f'{rng.randrange(-99999,100000)}e{scale}')
        case('random_scaled_intervals',first,last,None,coefficient,
             rng.choice(['constant','identity','square','cube','radical','reciprocal']),aliases=index % 29 == 0)
    for host_error in [-1,-2,-3]:
        actual = run(zero, one, None, one, 'constant', 0, host_error=host_error)
        counts['host_callback_errors'] = counts.get('host_callback_errors', 0) + 1
        if actual != (host_error, literal('123'), [zero.hex()], 0):
            failures.append({'group': 'host_callback_errors', 'actual': str(actual), 'expected': str(host_error)})
    report = {'cases': sum(counts.values()), 'groups': counts, 'failures': len(failures), 'mismatches': failures,
              'seed': '0x46ee', 'random_cases': args.random_cases,
              'scope': 'Prepared real native046EE full-expression integration against independent C callback formulas',
              'output': 'All10 output bytes; complete native20-byte records, callback X order, timer/cancel polls, variable restoration and aliases',
              'oracle_host_events': 'Only supply no-cancel timer response at5564 or selected cancellation event; every original instruction executes',
              'limitation': 'Prepared COMP only; complex callbacks, parser integration, malformed BCD and reset/keyscan execution excluded'}
    path = ROOT / 'analysis/c-verification/numeric_integral.json'
    if args.no_report: (build / 'exploration.json').write_text(json.dumps(report, indent=2)+'\n')
    elif failures: report['status'] = 'fail'; path.write_text(json.dumps(report, indent=2)+'\n')
    else: write_report(path, report, sources + ['csrc/numeric/fx_numeric.h', 'csrc/numeric/fx_calculus.h',
                                              'csrc/numeric/fx_integral.h', 'tools/c_verification.py',
                                              'tools/test_numeric_calculus_c.py', 'tools/nxu8/integral_host_events.c'], 'tools/test_numeric_integral_c.py')
    print(f'{sum(counts.values())} integral checks, {len(failures)} mismatches')
    for failure in failures[:6]:
        summary = dict(failure)
        for key in ('actual','expected'):
            if isinstance(summary.get(key), list) and len(summary[key]) > 2 and isinstance(summary[key][2], list):
                summary[key] = list(summary[key]); summary[key][2] = {'count': len(summary[key][2]), 'prefix': summary[key][2][:20]}
        print(summary)
    if failures: raise SystemExit(1)


if __name__ == '__main__': main()
