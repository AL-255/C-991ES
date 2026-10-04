#!/usr/bin/env python3
"""Compare high-level inverse trigonometry with original decimal routines.

The firmware/CPU are independent test oracles, never C implementation inputs.
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


class Number(C.Structure):
    _fields_ = [('bytes', C.c_uint8 * 10)]


class Rational(C.Structure):
    _fields_ = [('numerator', C.c_int64), ('denominator', C.c_uint64), ('flags', C.c_uint8)]


def decimal_record(mantissa, exponent, sign=1, flags=0):
    if not mantissa: return bytes(10)
    digits = f'{mantissa:015d}'
    return bytes([int(digits[0]) | flags,
                  *(int(digits[i:i+2], 16) for i in range(1, 15, 2)),
                  int(f'{exponent % 100:02d}', 16), (exponent >= 0) + (5 if sign < 0 else 0)])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--random-cases', type=int, default=6000)
    args = parser.parse_args()
    directory = ROOT / 'analysis/build/trig'
    directory.mkdir(parents=True, exist_ok=True)
    library = directory / 'inverse.so'
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror', '-pedantic',
                    '-shared', '-fPIC', str(ROOT / 'csrc/trig/fx_trig_inverse.c'),
                    str(ROOT / 'csrc/numeric/fx_numeric.c'), '-o', str(library)], check=True)
    lib = C.CDLL(str(library))
    pointer = C.POINTER(Number)
    lib.fx_atan_quarter_fraction.argtypes = [pointer, pointer]
    lib.fx_trig_inverse_decimal.argtypes = [pointer, pointer, C.c_int, C.c_int]
    lib.fx_decimal_parse.argtypes = [pointer, C.c_char_p]
    lib.fx_decimal_from_integer.argtypes = [pointer, C.c_int64]
    lib.fx_rational_encode.argtypes = [pointer, C.POINTER(Rational)]
    lib.fx_surd_pack.argtypes = [pointer, pointer]
    machine = Machine((ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes(), directory / 'oracle')
    randomizer = random.Random(0x1a3ac)
    counts, failures = {}, []

    def put(record):
        for index, value in enumerate(record): machine.ram[0x8300 + index] = value

    def literal(text):
        result = Number(); assert lib.fx_decimal_parse(C.byref(result), str(text).encode()) == 0
        return bytes(result.bytes)

    def check(group, actual, expected, detail):
        counts[group] = counts.get(group, 0) + 1
        if actual != expected:
            failures.append({'category': group, 'detail': detail,
                             'actual': actual, 'expected': expected})

    kernel_cases = [literal(text) for text in ['0','1','.5','.1','.123456','1e-20','1e-98','1e-99']]
    for _ in range(args.random_cases // 3):
        kernel_cases.append(decimal_record(randomizer.randrange(10**14, 10**15),
                                           randomizer.randrange(-99, 0)))
    for index, record in enumerate(kernel_cases):
        source = Number.from_buffer_copy(record); output = Number()
        status = lib.fx_atan_quarter_fraction(C.byref(output), C.byref(source))
        machine.reset(); settings(machine); put(record)
        machine.er(0, 0x8300); machine.call(0x1bac4)
        # 1A410 prepares the fixed coordinate1 with an empty index/guard
        # field; it is not the ordinary external floating decimal1 record.
        for position in range(10): machine.ram[0x8010 + position] = 0
        machine.ram[0x8019] = 1
        machine.call(0x1aca2)
        expected = bytes(machine.ram[0x8002:0x800a])[::-1] + bytes(machine.ram[0x8000:0x8002])
        check('atan_fraction_1aca2', [status, bytes(output.bytes).hex(), bytes(source.bytes).hex()],
              [0, expected.hex(), record.hex()], record.hex())
        if index < 100:
            alias = Number.from_buffer_copy(record)
            alias_status = lib.fx_atan_quarter_fraction(C.byref(alias), C.byref(alias))
            check('kernel_alias', [alias_status, bytes(alias.bytes).hex()],
                  [status, bytes(output.bytes).hex()], record.hex())

    named = ['0','1','-1','2','-2','.5','-.5','.707106781186547','-.707106781186547',
             '.999999999999999','-.999999999999999','1.00000000000001',
             '-1.00000000000001','1e-99','1e-98','1e-50','1e-11','1e-10','1e8','1e99','-1e99']
    cases = []
    for function in range(3):
        for unit in range(3):
            cases.append(('rational-cleanup-minus717over3946',
                          bytes.fromhex('2717a394600000000806'), function, unit))
            # The evaluator preserves sqrt(.5) as sqrt(2)/2 in Math mode.
            # Its conversion differs in the last digits from decimal sqrt(.5).
            cases.append(('exact-sqrt2-over2',
                          bytes.fromhex('80000001000201020100'), function, unit))
    for text in named:
        for function in range(3):
            for unit in range(3): cases.append((text, literal(text), function, unit))
    with localcontext() as context:
        context.prec = 50
        for center in [Decimal(-1), Decimal('-0.707106781186547'), Decimal('-.5'),
                       Decimal(0), Decimal('.5'), Decimal('.707106781186547'), Decimal(1)]:
            for exponent in range(-17, -9):
                for direction in [-1, 0, 1]:
                    record = literal(center + Decimal(direction) * Decimal(10) ** exponent)
                    for function in range(3):
                        for unit in range(3):
                            cases.append((f'boundary-{center}-{exponent}-{direction}', record, function, unit))
    for index in range(args.random_cases):
        # Half the cases exercise ordinary domain interiors; the other half
        # spans tiny/huge arguments, endpoint/domain errors and reciprocals.
        exponent = randomizer.randrange(-3, 0) if index % 2 else randomizer.randrange(-99, 100)
        record = decimal_record(randomizer.randrange(10**14, 10**15), exponent,
                                randomizer.choice([-1, 1]), 0x40 if index % 7 == 0 else 0)
        cases.append((f'decimal-{index}', record, randomizer.randrange(3), randomizer.randrange(3)))
    for index in range(300):
        denominator = randomizer.randrange(1, 10000)
        numerator = randomizer.randrange(-denominator, denominator + 1) if index % 2 else randomizer.randrange(-999999, 1000000)
        rational = Rational(numerator, denominator, 0); number = Number()
        assert lib.fx_rational_encode(C.byref(number), C.byref(rational)) == 0
        cases.append((f'rational-{index}', bytes(number.bytes), index % 3, (index // 3) % 3))
    for index in range(300):
        if index % 2:
            values = [randomizer.choice([-1, 1]), randomizer.randrange(1, 1000), randomizer.randrange(50, 100),
                      randomizer.choice([-1, 1]), randomizer.randrange(1, 1000), randomizer.randrange(50, 100)]
        else:
            values = [randomizer.randrange(-99, 100), randomizer.randrange(1, 1000), randomizer.randrange(1, 100),
                      randomizer.randrange(-99, 100), randomizer.randrange(1, 1000), randomizer.randrange(1, 100)]
        parts = (Number * 6)(); number = Number()
        for component, value in enumerate(values):
            assert lib.fx_decimal_from_integer(C.byref(parts[component]), value) == 0
        assert lib.fx_surd_pack(C.byref(number), parts) == 0
        cases.append((f'surd-{index}', bytes(number.bytes), index % 3, (index // 3) % 3))
    for code in [1, 2, 3, 5, 10, 15]:
        for function in range(3):
            cases.append((f'error-{code}', bytes([0xf0 | code]) + bytes(9), function, function))

    for index, (name, record, function, unit) in enumerate(cases):
        source = Number.from_buffer_copy(record); output = Number()
        status = lib.fx_trig_inverse_decimal(C.byref(output), C.byref(source), function, unit)
        machine.reset(); settings(machine); put(record)
        machine.er(0, 0x8300); machine.reg(2, unit + 4)
        machine.call([0x1c568, 0x1c556, 0x1c544][function])
        expected = bytes(machine.ram[0x8300:0x830a])
        check(f'inverse_core_{function}_{unit}', [status, bytes(output.bytes).hex(), bytes(source.bytes).hex()],
              [0, expected.hex(), record.hex()], [name, record.hex()])
        if index < 200:
            alias = Number.from_buffer_copy(record)
            alias_status = lib.fx_trig_inverse_decimal(C.byref(alias), C.byref(alias), function, unit)
            check('core_alias', [alias_status, bytes(alias.bytes).hex()],
                  [status, bytes(output.bytes).hex()], [name, record.hex()])
        if index < 100:
            machine.reset(); settings(machine); machine.ram[0x8105] = unit + 4; put(record)
            machine.er(0, 0x8300); machine.reg(2, 0)
            machine.call([0x1c568, 0x1c556, 0x1c544][function])
            default_unit = bytes(machine.ram[0x8300:0x830a])
            check('resolved_global_unit', default_unit.hex(), expected.hex(), [name, function, unit])

    report = {'cases': sum(counts.values()), 'groups': counts, 'failures': len(failures),
              'mismatches': failures, 'seed': '0x1a3ac', 'random_cases': args.random_cases,
              'scope': 'original1ACA2 atan-fraction kernel and complete inverse sine/cosine/tangent cores1C568/1C556/1C544',
              'input': 'identical decimal, rational, two-term surd and error records, function and output unit',
              'output': 'all10 kernel/core result bytes, source immutability, aliases and explicit-vs-global unit resolution',
              'limitation': 'prepared numeric routine contexts; global UI, malformedBCD, hyperbolic functions and reset-to-keypress I/O are outside this suite'}
    path = ROOT / 'analysis/c-verification/trig_inverse.json'
    if failures:
        report['status'] = 'fail'; path.write_text(json.dumps(report, indent=2) + '\n')
    else:
        write_report(path, report, ['csrc/trig/fx_trig_inverse.c', 'csrc/trig/fx_trig_inverse.h',
                                   'csrc/trig/fx_trig_math.h', 'csrc/trig/fx_trig.h',
                                   'csrc/numeric/fx_numeric.c', 'csrc/numeric/fx_numeric.h',
                                   'tools/trace_natural_result.py', 'tools/c_verification.py'],
                     'tools/test_trig_inverse_c.py')
    print(f'{sum(counts.values())} inverse trig checks, {len(failures)} mismatches')
    for failure in failures[:12]: print(failure)
    if failures: raise SystemExit(1)


if __name__ == '__main__': main()
