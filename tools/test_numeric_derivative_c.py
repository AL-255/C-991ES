#!/usr/bin/env python3
"""Compare handwritten Richardson differentiation with complete native expressions.
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
    build = ROOT / 'analysis/build/numeric/derivative'; build.mkdir(parents=True, exist_ok=True)
    sources = ['csrc/numeric/fx_numeric.c', 'csrc/numeric/fx_derivative.c']
    library = build / 'derivative.so'
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror', '-pedantic',
                    '-shared', '-fPIC', *(str(ROOT / p) for p in sources), '-o', str(library)], check=True)
    lib = C.CDLL(str(library))
    lib.fx_number_derivative.argtypes = [Pointer, Pointer, Pointer, Function, C.c_void_p, C.POINTER(Control)]
    lib.fx_decimal_parse.argtypes = [Pointer, C.c_char_p]
    lib.fx_rational_encode.argtypes = [Pointer, C.POINTER(Rational)]
    lib.fx_number_binary.argtypes = [Pointer, Pointer, Pointer, C.c_int]
    lib.fx_number_integer_power.argtypes = [Pointer, Pointer, C.c_int]
    lib.fx_number_sqrt.argtypes = [Pointer, Pointer, C.c_int]
    lib.fx_number_negate.argtypes = [Pointer, Pointer]
    lib.fx_number_to_decimal.argtypes = [Pointer, Pointer]
    lib.fx_number_kind.argtypes = [Pointer]
    lib.fx_decimal_integer_cleanup.argtypes = [Pointer]
    event_library = build / 'derivative-oracle.so'
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
                    str(ROOT / 'tools/nxu8/derivative_host_events.c'), str(ROOT / 'tools/nxu8/vendor/SimU8/core.c'),
                    '-o', str(event_library)], check=True)
    oracle = C.CDLL(str(event_library)); oracle.harness_init.argtypes = [C.c_void_p, C.c_size_t]
    oracle.harness_ram.restype = C.POINTER(C.c_uint8 * 65536)
    oracle.harness_set_reg.argtypes = [C.c_uint, C.c_uint8]
    oracle.derivative_oracle_call.argtypes = [C.c_uint32, C.c_uint64, C.c_uint]
    native_x = ((C.c_uint8 * 10) * 512).in_dll(oracle, 'derivative_oracle_x')
    native_count = C.c_uint.in_dll(oracle, 'derivative_oracle_callbacks')
    native_polls = C.c_uint.in_dll(oracle, 'derivative_oracle_polls')
    rom = (ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes(); rom_buffer = C.create_string_buffer(rom)
    counts, failures, outcomes = {}, [], {}
    trace_limits = {'maximum_callbacks': 0, 'maximum_cancel_polls': 0}
    rng = random.Random(0x4aee)

    def literal(text):
        value = Number(); assert lib.fx_decimal_parse(C.byref(value), str(text).encode()) == 0
        return bytes(value.bytes)

    def rational(n, d):
        value = Number(); assert lib.fx_rational_encode(C.byref(value), C.byref(Rational(n, d, 0))) == 0
        return bytes(value.bytes)

    initial_x = literal('37')
    formulas = {'constant': b'A', 'identity': b'X', 'square': b'X\x75', 'cube': b'X\x76',
                'radical': b'\x98X)', 'reciprocal': b'1\x4fX', 'division_error': b'1\x4f0',
                'shifted_pole': b'1\x4f(X-A)', 'absolute': b'\x63X-A)',
                'ratio_overflow': b'(X-A)\x4eD+E', 'scaled_cube': b'X\x76\x4eD',
                'offset_cube': b'X\x76+D'}

    def native(point, tolerance, coefficient, formula, abort,evaluation_mode=0,reference_dimensions=False):
        oracle.harness_init(rom_buffer, len(rom)); ram = oracle.harness_ram().contents
        for address, value in [(0x80f9, 0xc1), (0x80f5, 0xf0), (0x8105, 4), (0x8106, 1), (0x8121, 1)]: ram[address] = value
        ram[0x80fc] = int(bool(evaluation_mode))
        for address, value in [(0x812c, 0x8200), (0x8190, 0x8200)]: ram[address] = value & 255; ram[address+1] = value >> 8
        tokens = b'\x6b' + formulas[formula] + b',B' + (b',C' if tolerance is not None else b'') + b')\0'
        for index, value in enumerate(tokens): ram[0x8200 + index] = value
        for address, record in [(0x823a, coefficient), (0x8244, point),
                                (0x824e, tolerance or bytes(10)), (0x8276, initial_x),
                                (0x8258, literal('1e-99' if formula == 'scaled_cube' else '1e5' if formula == 'offset_cube' else '1e99')),
                                (0x8262, literal('1e-99'))]:
            for index, value in enumerate(record): ram[address+index] = value
        if reference_dimensions:
            identity = coefficient[0] & 15
            ram[0x80e0+2*identity] = ram[0x80e1+2*identity] = 1
            for index,value in enumerate(literal('1')): ram[0x829e+90*identity+index] = value
        for index, value in enumerate([0x90,0x81,0,0x83]): oracle.harness_set_reg(index, value)
        status = oracle.derivative_oracle_call(0x171f4, 30000000, abort)
        assert status == 100, (status, tokens.hex())
        assert native_count.value <= 512
        return bytes(ram[0x8300:0x8314]), [bytes(native_x[i]).hex() for i in range(native_count.value)], native_polls.value, bytes(ram[0x8276:0x8280]), tokens

    def run(point, tolerance, coefficient, formula, abort, alias=0, host_error=0,evaluation_mode=0,reference_dimensions=False):
        input_point = Number.from_buffer_copy(point)
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
            if formula == 'offset_cube':
                offset = Number.from_buffer_copy(literal('1e5'))
                status = lib.fx_number_integer_power(result,x,3)
                if status == 0: status = lib.fx_decimal_integer_cleanup(result)
                if status == 0: status = lib.fx_number_binary(result,result,C.byref(offset),0)
                if status == 0: status = lib.fx_decimal_integer_cleanup(result)
                return status
            if formula in ('ratio_overflow','scaled_cube'):
                scale = Number.from_buffer_copy(literal('1e-99' if formula == 'scaled_cube' else '1e99'))
                residue = Number.from_buffer_copy(literal('1e-99'))
                if formula == 'scaled_cube': status = lib.fx_number_integer_power(result,x,3)
                else: status = lib.fx_number_binary(result,x,C.byref(value),1)
                if status == 0: status = lib.fx_decimal_integer_cleanup(result)
                if status == 0: status = lib.fx_number_binary(result,result,C.byref(scale),2)
                if status == 0: status = lib.fx_decimal_integer_cleanup(result)
                if status == 0 and formula == 'ratio_overflow':
                    status = lib.fx_number_binary(result,result,C.byref(residue),0)
                    if status == 0: status = lib.fx_decimal_integer_cleanup(result)
                return status
            if formula == 'absolute':
                status = lib.fx_number_binary(result, x, C.byref(value), 1)
                if status != 0: return status
                if result.contents.bytes[9] >= 5: status = lib.fx_number_negate(result, result)
                return status
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
        legacy_function = function
        if evaluation_mode:
            @Function
            def function(result,x,userdata):
                status = legacy_function(result,x,userdata)
                if status != 0: return status
                if formula == 'constant':
                    # Native1415A cleanup precedes the successful callback
                    # return. F headers become F3; zero-size6/9 become F9.
                    header = coefficient[0] >> 4
                    if header == 15 or header in (6,9) and not reference_dimensions:
                        C.memset(result,0,10); result.contents.bytes[0] = 0xf9 if header in (6,9) else 0xf3
                return 1 if formula == 'constant' or lib.fx_number_kind(result) != 15 else 2
        target = input_point if alias == 1 else tol if alias == 2 else out
        status = lib.fx_number_derivative(C.byref(target), C.byref(input_point),
                                         C.byref(tol) if tol is not None else None, function, None, C.byref(control))
        return status, bytes(target.bytes), calls, len(polls)

    def case(group, point, tolerance, coefficient, formula, abort=0, aliases=False,evaluation_mode=0,reference_dimensions=False):
        records, xs, polls, restored, tokens = native(point, tolerance, coefficient, formula, abort,evaluation_mode,reference_dimensions)
        outcome = f'F{records[0]&15:X}' if records[0] >= 0xf0 else 'number'
        outcomes[outcome] = outcomes.get(outcome, 0)+1
        trace_limits['maximum_callbacks'] = max(trace_limits['maximum_callbacks'],len(xs))
        trace_limits['maximum_cancel_polls'] = max(trace_limits['maximum_cancel_polls'],polls)
        actual = run(point, tolerance, coefficient, formula, abort,evaluation_mode=evaluation_mode,reference_dimensions=reference_dimensions)
        expected = [0, records[:10].hex(), xs, polls]
        detail = [tokens.hex(), point.hex(), tolerance.hex() if tolerance is not None else None, coefficient.hex(), abort]
        def check(name, got, wanted):
            counts[name] = counts.get(name, 0) + 1
            if got != wanted: failures.append({'group': name, 'detail': detail, 'actual': got, 'expected': wanted})
        check(group, [actual[0], actual[1].hex(), actual[2], actual[3]], expected)
        check('native_imaginary_zero_and_X_restore', [records[10:].hex(), restored.hex()], [bytes(10).hex(), initial_x.hex()])
        if aliases:
            for alias in range(1, 3 if tolerance is not None else 2):
                actual = run(point, tolerance, coefficient, formula, abort, alias,evaluation_mode=evaluation_mode,reference_dimensions=reference_dimensions)
                check('output_alias', [actual[0], actual[1].hex(), actual[2], actual[3]], expected)

    one, zero = literal('1'), literal('0')
    def marked(record):
        return bytes([record[0] | 0x40]) + record[1:]
    for formula in formulas:
        for point in ['0','1','-1','3.14159','-3.14159','.001','1e-93','1e-80','1e-40','1e40','1e80','1e99']:
            case('formula_fixtures',literal(point),None,one,formula,aliases=True)
    for tolerance in ['0','-.01','1e-99','1e-10','1e-5','.1','1','1e99']:
        for formula in ['constant','square','radical','reciprocal']:
            case('tolerance_fixtures',one,literal(tolerance),one,formula,aliases=True)
    for coefficient in [literal(s) for s in ['0','1','-1','.333333333333333','1e-99','1e99','9e99']] + \
                       [rational(1,3),rational(-2,7),marked(one),bytes.fromhex('80000001000201020100')]:
        case('coefficient_records',one,None,coefficient,'constant',aliases=True)
    for point in [rational(1,3),rational(-2,7),marked(one),bytes.fromhex('80000001000201020100')]:
        for formula in ['constant','identity','square','cube','radical','reciprocal']:
            case('point_records',point,None,one,formula,aliases=True)
    for tolerance in [rational(1,1000),marked(literal('1e-5')),bytes.fromhex('80000001000201020100')]:
        case('tolerance_records',one,tolerance,one,'radical',aliases=True)
    for coefficient in [literal('1.01'),literal('1.000001'),literal('1.000000001')]:
        case('step_selection_domain_retry',one,None,coefficient,'shifted_pole',aliases=True)
    for point in [one,literal('-1')]:
        case('step_selection_ratio_overflow',point,None,point,'ratio_overflow',aliases=True)
    for tolerance in [None,literal('1e-10')]:
        case('default_and_explicit_exhaustion',one,tolerance,literal('.9999999999'),'absolute',aliases=True)
        case('default_best_estimate_fallback',one,tolerance,one,'offset_cube',aliases=True)
    for point in [literal('1e30'),literal('-1e30')]:
        for tolerance in [None,literal('1e-10'),literal('.1')]:
            case('tiny_derivative_guard_order',point,tolerance,one,'scaled_cube',aliases=True)
    for formula in ['constant','radical','reciprocal']:
        for abort in [1,2,3,5,10,15]:case('native_cancellation',one,None,one,formula,abort,True)
    for code in range(16):
        coefficient = bytes([0xf0|code])+bytes(9)
        for tolerance in [None,literal('1e-10')]:
            case('native_success_with_F_variable',one,tolerance,coefficient,'constant',aliases=True,evaluation_mode=1)
    for header in [0x61,0x91]:
        coefficient = bytes([header])+bytes.fromhex('a30000000000000301')
        case('native_success_with_zero_dimension_reference',one,None,coefficient,'constant',aliases=True,evaluation_mode=1)
        case('native_backed_reference_arithmetic',one,None,coefficient,'constant',aliases=True,evaluation_mode=1,reference_dimensions=True)
    for formula in ['constant','identity','square','radical','division_error']:
        case('extended_evaluation_status',one,None,one,formula,aliases=True,evaluation_mode=1)
    for index in range(args.random_cases):
        coefficient = rational(rng.randrange(-99,100),rng.randrange(1,100)) if index % 2 else literal(rng.randrange(-99,100))
        point = literal(f'{rng.randrange(-99999,100000)}e{rng.randrange(-80,81)}')
        tolerance = literal(f'1e{rng.randrange(-15,1)}') if index % 3 else None
        case('random_points',point,tolerance,coefficient,rng.choice(list(formulas)),aliases=index % 13 == 0)
    for host_error in [-1,-2,-3]:
        actual = run(one,None,one,'constant',0,host_error=host_error)
        counts['host_callback_errors'] = counts.get('host_callback_errors',0)+1
        if actual != (host_error,literal('123'),[one.hex()],0):
            failures.append({'group':'host_callback_errors','actual':str(actual),'expected':str(host_error)})
    report = {'cases': sum(counts.values()), 'groups': counts, 'failures': len(failures), 'mismatches': failures,
              'seed': '0x4aee', 'random_cases': args.random_cases,
              'native_outcomes': outcomes, 'trace_limits': trace_limits,
              'scope': 'Prepared real native04AEE full-expression differentiation against independent C callback formulas',
              'output': 'All10 output bytes; complete native20-byte records, callback X order, timer/cancel polls, variable restoration and aliases',
              'oracle_host_events': 'Only supply no-cancel timer response at5564 or selected cancellation event; every original instruction executes',
              'limitation': 'Prepared COMP only; complex callbacks, parser integration, malformed BCD and reset/keyscan execution excluded'}
    path = ROOT / 'analysis/c-verification/numeric_derivative.json'
    if args.no_report: (build / 'exploration.json').write_text(json.dumps(report, indent=2)+'\n')
    elif failures: report['status'] = 'fail'; path.write_text(json.dumps(report, indent=2)+'\n')
    else: write_report(path, report, sources + ['csrc/numeric/fx_numeric.h', 'csrc/numeric/fx_calculus.h',
                                              'csrc/numeric/fx_derivative.h', 'tools/c_verification.py',
                                              'tools/test_numeric_calculus_c.py', 'tools/nxu8/derivative_host_events.c'], 'tools/test_numeric_derivative_c.py')
    print(f'{sum(counts.values())} derivative checks, {len(failures)} mismatches')
    for failure in failures[:6]:
        summary = dict(failure)
        for key in ('actual','expected'):
            if isinstance(summary.get(key), list) and len(summary[key]) > 2 and isinstance(summary[key][2], list):
                summary[key] = list(summary[key]); summary[key][2] = {'count': len(summary[key][2]), 'prefix': summary[key][2][:20]}
        print(summary)
    if failures: raise SystemExit(1)


if __name__ == '__main__': main()
