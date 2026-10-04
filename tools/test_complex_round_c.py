#!/usr/bin/env python3
"""Compare scalar/CMPLX display rounding with native15CBE/15D36.

CPU and extracted ROM are oracle-only. GPL-3.0-or-later.
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
from nxu8.machine import Machine
from trace_natural_result import settings
from c_verification import write_report


class Number(C.Structure):
    _fields_ = [('bytes', C.c_uint8 * 10)]


class Complex(C.Structure):
    _fields_ = [('real', Number), ('imaginary', Number)]


class Rational(C.Structure):
    _fields_ = [('numerator', C.c_int64), ('denominator', C.c_uint64), ('flags', C.c_uint8)]


def decimal_record(mantissa, exponent, sign=1, flags=0):
    if not mantissa: return bytes([flags]) + bytes(9)
    digits = f'{mantissa:015d}'
    return bytes([int(digits[0]) | flags,
                  *(int(digits[i:i + 2], 16) for i in range(1, 15, 2)),
                  int(f'{exponent % 100:02d}', 16), (exponent >= 0) + (5 if sign < 0 else 0)])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--random-cases', type=int, default=8000)
    parser.add_argument('--no-report', action='store_true')
    args = parser.parse_args()
    build = ROOT / 'analysis/build/complex-round'
    build.mkdir(parents=True, exist_ok=True)
    library = build / 'complex-round.so'
    sources = ['csrc/complex/fx_complex_round.c', 'csrc/numeric/fx_numeric.c']
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror', '-pedantic',
                    '-shared', '-fPIC', *(str(ROOT / path) for path in sources), '-o', str(library)], check=True)
    lib = C.CDLL(str(library))
    lib.fx_scalar_display_round.argtypes = [C.POINTER(Number), C.POINTER(Number), C.c_uint8,
                                           C.c_uint8, C.POINTER(C.c_uint8)]
    lib.fx_complex_display_round.argtypes = [C.POINTER(Complex), C.POINTER(Complex), C.c_uint8,
                                            C.c_uint8, C.POINTER(C.c_uint8)]
    lib.fx_decimal_parse.argtypes = [C.POINTER(Number), C.c_char_p]
    lib.fx_rational_encode.argtypes = [C.POINTER(Number), C.POINTER(Rational)]
    lib.fx_surd_pack.argtypes = [C.POINTER(Number), C.POINTER(Number)]
    machine = Machine((ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes(), build / 'oracle')
    rng = random.Random(0x15cbe)
    failures, counts = [], {}

    def literal(text):
        value = Number()
        assert lib.fx_decimal_parse(C.byref(value), str(text).encode()) == 0
        return bytes(value)

    def rational(numerator, denominator, flags=0):
        value = Number(); fraction = Rational(numerator, denominator, flags)
        assert lib.fx_rational_encode(C.byref(value), C.byref(fraction)) == 0
        return bytes(value)

    def surd(values):
        parts = (Number * 6)(); value = Number()
        for index, component in enumerate(values):
            assert lib.fx_decimal_parse(C.byref(parts[index]), str(component).encode()) == 0
        assert lib.fx_surd_pack(C.byref(value), parts) == 0
        return bytes(value)

    def oracle(record, mode, digits, entry):
        machine.reset(); settings(machine)
        machine.ram[0x80f9] = 0xc4
        machine.ram[0x8102] = mode; machine.ram[0x8103] = digits
        for index, byte in enumerate(record): machine.ram[0x8300 + index] = byte
        machine.er(0, 0x8300); machine.er(12, 0x8300)
        machine.call(entry, limit=3000000)
        return bytes(machine.ram[0x8300:0x8300 + len(record)]), machine.reg(0)

    def check(group, actual, expected, detail):
        counts[group] = counts.get(group, 0) + 1
        if actual != expected:
            failures.append({'group':group, 'actual':actual, 'expected':expected, 'detail':detail})

    def scalar_case(name, record, mode, digits, alias=False):
        source = Number.from_buffer_copy(record); output = Number(); numerical_status = C.c_uint8(0xab)
        status = lib.fx_scalar_display_round(C.byref(output), C.byref(source), mode, digits,
                                              C.byref(numerical_status))
        expected, expected_status = oracle(record, mode, digits, 0x15cbe)
        check('scalar_' + name, [status, bytes(output).hex(), numerical_status.value, bytes(source).hex()],
              [0, expected.hex(), expected_status, record.hex()], [record.hex(), mode, digits])
        if alias:
            numerical_status.value = 0xab
            status = lib.fx_scalar_display_round(C.byref(source), C.byref(source), mode, digits,
                                                  C.byref(numerical_status))
            check('scalar_output_alias', [status, bytes(source).hex(), numerical_status.value],
                  [0, expected.hex(), expected_status], [record.hex(), mode, digits])

    def complex_case(name, record, mode, digits, alias=False):
        source = Complex.from_buffer_copy(record); output = Complex(); numerical_status = C.c_uint8(0xab)
        status = lib.fx_complex_display_round(C.byref(output), C.byref(source), mode, digits,
                                               C.byref(numerical_status))
        expected, expected_status = oracle(record, mode, digits, 0x15d36)
        check('complex_' + name, [status, bytes(output).hex(), numerical_status.value, bytes(source).hex()],
              [0, expected.hex(), expected_status, record.hex()], [record.hex(), mode, digits])
        if alias:
            numerical_status.value = 0xab
            status = lib.fx_complex_display_round(C.byref(source), C.byref(source), mode, digits,
                                                   C.byref(numerical_status))
            check('complex_output_alias', [status, bytes(source).hex(), numerical_status.value],
                  [0, expected.hex(), expected_status], [record.hex(), mode, digits])

    boundaries = ['0', '1', '-1', '1.23456789012345', '-1.23456789012345',
                  '.499999999999999', '.5', '.500000000000001', '-.5', '-1.5',
                  '.000000000005', '.00000000000499999', '123456789.999999',
                  '999999999999999', '999999999.999999', '9.99999999999999e99',
                  '-9.99999999999999e99', '1e-99', '-1e-99', '9.99999999995',
                  '0.00000000999999999995', '1234567891.49999', '1234567891.5']
    records = [(literal(value), 'boundary') for value in boundaries]
    records += [(decimal_record(0,0,flags=0x40), 'marked_zero')]
    records += [(decimal_record(m,e,s,flags=0x40),'marked_decimal') for m,e,s in
                [(123456789012345,0,1),(999999999999999,99,-1),(100000000000000,-99,1)]]
    for numerator, denominator in [(1,3),(-1,3),(7,3),(-717,3946),(1,99999999),(99999999,97)]:
        records.append((rational(numerator,denominator),'rational'))
        records.append((rational(numerator,denominator,0x40),'rejected_marked_rational'))
    for components in [[1,2,1,0,1,1],[-1,2,1,0,1,1],[1,998,99,-1,997,99],
                       [99,999,1,-99,998,1],[1,2,3,1,3,7]]:
        records.append((surd(components),'surd'))
    for code in range(16): records.append((bytes([0xf0 | code]) + bytes(9),'rejected_error'))
    for record, name in records:
        for mode in [0,4,8,9]:
            for digits in range(10):
                scalar_case(name,record,mode,digits,alias=digits==0)
                if name in ('rejected_error','rejected_marked_rational','surd'):
                    for imaginary in [False,True]:
                        ordinary = literal('1.23456789012345')
                        pair = ordinary+record if imaginary else record+ordinary
                        complex_case(name + ('_imaginary' if imaginary else '_real'),pair,mode,digits,
                                     alias=digits==0)
    for index in range(args.random_cases):
        mode = [0,4,8,9][index % 4]; digits = rng.randrange(10)
        exponent = rng.randrange(-99,100) if index % 3 else rng.randrange(-12,15)
        record = decimal_record(rng.randrange(10**14,10**15),exponent,rng.choice([-1,1]),
                                0x40 if index % 7 == 0 else 0)
        scalar_case('random_decimal',record,mode,digits,alias=index<100)
        other = records[rng.randrange(len(records))][0] if index % 4 == 0 else decimal_record(
            rng.randrange(10**14,10**15),rng.randrange(-99,100),rng.choice([-1,1]))
        complex_case('random_components', record+other if index % 2 else other+record,mode,digits,
                     alias=index<100)
    for mode in [0,4,8,9]:
        for digits in [10,16,99,255]:
            source = Number.from_buffer_copy(literal('1.5')); output = Number.from_buffer_copy(bytes([0x55])*10)
            numerical_status = C.c_uint8(0xab)
            status = lib.fx_scalar_display_round(C.byref(output),C.byref(source),mode,digits,
                                                  C.byref(numerical_status))
            check('host_context_guard',[status,bytes(output).hex(),numerical_status.value],
                  [-1,'55'*10,0xab],[mode,digits])
    report = {'cases':sum(counts.values()), 'groups':counts, 'failures':len(failures),
              'mismatches':failures, 'seed':'0x15cbe', 'random_cases':args.random_cases,
              'scope':'Canonical scalar15CBE and complex15D36 display rounding with native imaginary-first short-circuit and native return status',
              'input':'Prepared CMPLX context, Norm1/Norm2/Fix/Sci, precision0..9, ordinary/marked decimals, rational/surd and all16 error headers',
              'output':'All10/20 result bytes, original R0 numerical status, immutable input and output aliases',
              'limitation':'Scalar scratch RAM/register effects, malformed BCD and noncanonical precision bytes excluded; not full CMPLX evaluator/key UI'}
    path = ROOT / 'analysis/c-verification/complex_round.json'
    if not args.no_report:
        if failures:
            report['status'] = 'fail'; path.write_text(json.dumps(report,indent=2)+'\n')
        else:
            write_report(path,report,[*sources,'csrc/complex/fx_complex_round.h','csrc/complex/fx_complex.h',
                                      'csrc/numeric/fx_numeric.h','tools/trace_natural_result.py',
                                      'tools/c_verification.py'], 'tools/test_complex_round_c.py')
    print(f'{sum(counts.values())} scalar/complex rounding checks, {len(failures)} mismatches')
    for failure in failures[:20]: print(failure)
    if failures: raise SystemExit(1)


if __name__ == '__main__': main()
