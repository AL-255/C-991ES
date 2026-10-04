#!/usr/bin/env python3
"""Compare readable hyperbolic formulas with the original numeric wrappers.

The original firmware/CPU serve only as an independent test oracle.
GPL-3.0-or-later.
"""
import argparse
import ctypes as C
from decimal import Decimal, localcontext
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
from c_build_inputs import implementation_inputs


class Number(C.Structure):
    _fields_ = [('bytes', C.c_uint8 * 10)]


class Rational(C.Structure):
    _fields_ = [('numerator', C.c_int64), ('denominator', C.c_uint64), ('flags', C.c_uint8)]


def decimal_record(mantissa, exponent, sign=1, flags=0):
    if not mantissa: return bytes(10)
    digits = f'{mantissa:015d}'
    return bytes([int(digits[0]) | flags,
                  *(int(digits[i:i + 2], 16) for i in range(1, 15, 2)),
                  int(f'{exponent % 100:02d}', 16), (exponent >= 0) + (5 if sign < 0 else 0)])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--random-cases', type=int, default=12000)
    parser.add_argument('--no-report', action='store_true', help='Explore a changing dependency without publishing evidence')
    args = parser.parse_args()
    build = ROOT / 'analysis/build/trig/hyperbolic'
    build.mkdir(parents=True, exist_ok=True)
    library = build / 'hyperbolic.so'
    sources = ['csrc/trig/fx_trig_hyperbolic.c', 'csrc/numeric/fx_numeric.c',
               'csrc/numeric/fx_transcend.c']
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror', '-pedantic',
                    '-shared', '-fPIC', *(str(ROOT / p) for p in sources),
                    '-o', str(library)], check=True)
    lib = C.CDLL(str(library))
    pointer = C.POINTER(Number)
    lib.fx_hyperbolic_decimal.argtypes = [pointer, pointer, C.c_int, C.c_int]
    lib.fx_decimal_parse.argtypes = [pointer, C.c_char_p]
    lib.fx_decimal_from_integer.argtypes = [pointer, C.c_int64]
    lib.fx_rational_encode.argtypes = [pointer, C.POINTER(Rational)]
    lib.fx_surd_pack.argtypes = [pointer, pointer]
    rom = (ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    machine = Machine(rom, build / 'oracle')
    rng = random.Random(0x1a10a)
    cases, counts, failures = [], {}, []

    def literal(text):
        value = Number()
        assert lib.fx_decimal_parse(C.byref(value), str(text).encode()) == 0
        return bytes(value.bytes)

    def add_all(name, record):
        for inverse in [0, 1]:
            for function in range(3): cases.append((name, record, function, inverse))

    named = ['0','1','-1','2','-2','.5','-.5','.013','-.013',
             '.0129999999999999','-.0129999999999999',
             '0.999999999999999','-0.999999999999999',
             '1.00000000000001','-1.00000000000001',
             '1e-99','-1e-99','1e-98','1e-50','1e-11','1e-10',
             '10','-10','50','100','200','230','231','232','1000','1e99','-1e99']
    for text in named: add_all(text, literal(text))
    with localcontext() as context:
        context.prec = 50
        for center in [Decimal('-1'), Decimal('-.013'), Decimal(0), Decimal('.013'), Decimal(1)]:
            for exponent in range(-17, -9):
                for direction in [-1, 0, 1]:
                    value = center + Decimal(direction) * Decimal(10) ** exponent
                    add_all(f'boundary-{center}-{exponent}-{direction}', literal(value))
        for center in ['230.258509299404', '-230.258509299404']:
            for offset in range(-40, 41):
                add_all(f'exp-range-{center}-{offset}', literal(Decimal(center) + Decimal(offset) * Decimal('1e-12')))

    for index in range(args.random_cases):
        # Sample the small-series threshold, ordinary general formulas, tiny
        # underflow, large-input reciprocal roots and exp overflow controls.
        if index % 4 == 0: exponent = rng.randrange(-99, -2)
        elif index % 4 == 1: exponent = rng.randrange(-3, 3)
        else: exponent = rng.randrange(-99, 100)
        record = decimal_record(rng.randrange(10**14, 10**15), exponent,
                                rng.choice([-1, 1]), 0x40 if index % 7 == 0 else 0)
        cases.append((f'decimal-{index}', record, rng.randrange(3), rng.randrange(2)))
    for index in range(600):
        denominator = rng.randrange(1, 10000)
        numerator = rng.randrange(-denominator, denominator + 1) if index % 2 else rng.randrange(-999999, 1000000)
        number = Number(); rational = Rational(numerator, denominator, 0)
        assert lib.fx_rational_encode(C.byref(number), C.byref(rational)) == 0
        cases.append((f'rational-{index}', bytes(number.bytes), index % 3, (index // 3) % 2))
    for index in range(600):
        values = [rng.randrange(-99, 100), rng.randrange(1, 1000), rng.randrange(1, 100),
                  rng.randrange(-99, 100), rng.randrange(1, 1000), rng.randrange(1, 100)]
        components = (Number * 6)(); number = Number()
        for position, value in enumerate(values):
            assert lib.fx_decimal_from_integer(C.byref(components[position]), value) == 0
        assert lib.fx_surd_pack(C.byref(number), components) == 0
        cases.append((f'surd-{index}', bytes(number.bytes), index % 3, (index // 3) % 2))
    add_all('exact-sqrt2-over2', bytes.fromhex('80000001000201020100'))
    for code in [1, 2, 3, 5, 10, 15]: add_all(f'error-{code}', bytes([0xf0 | code]) + bytes(9))

    def check(group, actual, expected, detail):
        counts[group] = counts.get(group, 0) + 1
        if actual != expected:
            failures.append({'group': group, 'detail': detail, 'actual': actual, 'expected': expected})

    entries = [[0x1c532, 0x1c520, 0x1c50e], [0x1c4fc, 0x1c4ea, 0x1c4d8]]
    for index, (name, record, function, inverse) in enumerate(cases):
        source = Number.from_buffer_copy(record); output = Number()
        status = lib.fx_hyperbolic_decimal(C.byref(output), C.byref(source), function, inverse)
        machine.reset(); settings(machine)
        for position, value in enumerate(record): machine.ram[0x8300 + position] = value
        machine.er(0, 0x8300); machine.reg(2, 0)
        machine.call(entries[inverse][function], limit=3000000)
        expected = bytes(machine.ram[0x8300:0x830a])
        check(f'core_{inverse}_{function}', [status, bytes(output.bytes).hex(), bytes(source.bytes).hex()],
              [0, expected.hex(), record.hex()], [name, record.hex()])
        if index < 300:
            alias = Number.from_buffer_copy(record)
            alias_status = lib.fx_hyperbolic_decimal(C.byref(alias), C.byref(alias), function, inverse)
            check('output_alias', [alias_status, bytes(alias.bytes).hex()],
                  [status, bytes(output.bytes).hex()], [name, function, inverse])

    report = {'cases': sum(counts.values()), 'groups': counts, 'failures': len(failures),
              'mismatches': failures, 'seed': '0x1a10a', 'random_cases': args.random_cases,
              'scope': 'complete real sinh/cosh/tanh and asinh/acosh/atanh wrappers1C532/1C520/1C50E/1C4FC/1C4EA/1C4D8',
              'input': 'identical decimal, rational, two-term surd and error records, function and inverse flag',
              'output': 'all10 result bytes including errors and sign metadata, source immutability and output aliases',
              'limitation': 'prepared routine contexts; malformedBCD, scratchRAM side effects and reset-to-keypress I/O are outside this suite'}
    path = ROOT / 'analysis/c-verification/trig_hyperbolic.json'
    if args.no_report:
        pass
    elif failures:
        report['status'] = 'fail'; path.write_text(json.dumps(report, indent=2) + '\n')
    else:
        write_report(path, report, implementation_inputs(ROOT, sources) + [
                                   'tools/trace_natural_result.py',
                                   'tools/c_build_inputs.py',
                                   'tools/c_verification.py'], 'tools/test_trig_hyperbolic_c.py')
    print(f'{sum(counts.values())} hyperbolic checks, {len(failures)} mismatches')
    for failure in failures[:20]: print(failure)
    if failures: raise SystemExit(1)


if __name__ == '__main__': main()
