#!/usr/bin/env python3
"""Compare high-level decimal trigonometry with original numeric/wrapper entries.

The extracted firmware and CPU occur only in this independent test oracle.
The implementation performs decimal coordinate rotations and arithmetic in C.
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
    library = directory / 'math.so'
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror', '-pedantic',
                    '-shared', '-fPIC', str(ROOT / 'csrc/trig/fx_trig_math.c'),
                    str(ROOT / 'csrc/trig/fx_trig.c'), str(ROOT / 'csrc/numeric/fx_numeric.c'),
                    '-o', str(library)], check=True)
    lib = C.CDLL(str(library))
    pointer = C.POINTER(Number)
    lib.fx_trig_decimal_pair.argtypes = [pointer, pointer, pointer]
    lib.fx_trig_decimal.argtypes = [pointer, pointer, C.c_int, C.c_int]
    lib.fx_angle_convert.argtypes = [pointer, pointer, C.c_int, C.c_int]
    lib.fx_trig_evaluate.argtypes = [pointer, pointer, C.c_int, C.c_int, C.c_int, C.POINTER(C.c_uint)]
    lib.fx_decimal_parse.argtypes = [pointer, C.c_char_p]
    lib.fx_decimal_from_integer.argtypes = [pointer, C.c_int64]
    lib.fx_rational_encode.argtypes = [pointer, C.POINTER(Rational)]
    lib.fx_surd_pack.argtypes = [pointer, pointer]
    machine = Machine((ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes(), directory / 'oracle')
    randomizer = random.Random(0x1a2d4)
    counts, failures = {}, []

    def put(record):
        for index, value in enumerate(record): machine.ram[0x8300 + index] = value

    def literal(text):
        value = Number()
        assert lib.fx_decimal_parse(C.byref(value), str(text).encode()) == 0
        return bytes(value.bytes)

    def check(category, actual, expected, detail):
        counts[category] = counts.get(category, 0) + 1
        if actual != expected:
            failures.append({'category': category, 'detail': detail,
                             'actual': actual, 'expected': expected})

    # The internal coordinate pair has an independent original routine
    # boundary, so errors in later angle reduction cannot hide its behavior.
    pair_cases = [bytes(10), literal('.5'), literal('.499999999999999'),
                  literal('.1'), literal('.123456'), literal('1e-99')]
    for _ in range(args.random_cases // 3):
        pair_cases.append(decimal_record(randomizer.randrange(10**14, 5*10**14+1),
                                         randomizer.randrange(-99, 0)))
    for record in pair_cases:
        source = Number.from_buffer_copy(record); cosine = Number(); sine = Number()
        status = lib.fx_trig_decimal_pair(C.byref(cosine), C.byref(sine), C.byref(source))
        machine.reset(); settings(machine); put(record)
        machine.er(0, 0x8300); machine.call(0x1bac4); machine.call(0x1acec)
        expected_cosine = bytes(machine.ram[0x8002:0x800a])[::-1] + bytes(machine.ram[0x8000:0x8002])
        expected_sine = bytes(machine.ram[0x8012:0x801a])[::-1] + bytes(machine.ram[0x8010:0x8012])
        check('decimal_pair_1acec', [status, bytes(cosine.bytes).hex(), bytes(sine.bytes).hex(), bytes(source.bytes).hex()],
              [0, expected_cosine.hex(), expected_sine.hex(), record.hex()], record.hex())

    cases = []
    named = ['0', '1', '-1', '1e-99', '1e-98', '1e-50', '1e-11', '1e-10',
             '15', '30', '45', '60', '90', '180', '270', '360', '-450',
             '89.9999999999999', '90.0000000000001', '99999999', '1e8', '1e99',
             '1.57079632679490', '3.14159265358979', '6.28318530717959']
    for text in named:
        for function in range(3):
            for unit in range(3): cases.append((text, literal(text), function, unit))
    for angle in range(-1080, 1081, 15):
        for function in range(3): cases.append((f'degree-{angle}', literal(angle), function, 0))
    with localcontext() as context:
        context.prec = 50
        for unit, quarter in enumerate([Decimal(90), Decimal('1.57079632679490'), Decimal(100)]):
            for turn in [-1000000, -17, -4, -3, -2, -1, 0, 1, 2, 3, 4, 17, 1000000]:
                for half in [Decimal(0), Decimal('.5')]:
                    center = (Decimal(turn) + half) * quarter
                    for exponent in [-10, -11, -12, -13, -14, -15]:
                        for direction in [-1, 0, 1]:
                            record = literal(center + Decimal(direction) * Decimal(10) ** exponent)
                            for function in range(3):
                                cases.append((f'boundary-{unit}-{turn}-{half}-{exponent}-{direction}',
                                              record, function, unit))
    for index in range(args.random_cases):
        exponent = randomizer.choice(list(range(-99, 11)) + [98, 99])
        record = decimal_record(randomizer.randrange(10**14, 10**15), exponent,
                                randomizer.choice([-1, 1]), 0x40 if index % 7 == 0 else 0)
        cases.append((f'decimal-{index}', record, randomizer.randrange(3), randomizer.randrange(3)))
    for index in range(300):
        rational = Rational(randomizer.randrange(-999999, 1000000), randomizer.randrange(1, 10000), 0)
        number = Number(); assert lib.fx_rational_encode(C.byref(number), C.byref(rational)) == 0
        cases.append((f'rational-{index}', bytes(number.bytes), index % 3, (index // 3) % 3))
    for index in range(300):
        values = [randomizer.randrange(-99, 100), randomizer.randrange(1, 1000), randomizer.randrange(1, 100),
                  randomizer.randrange(-99, 100), randomizer.randrange(1, 1000), randomizer.randrange(1, 100)]
        parts = (Number * 6)(); number = Number()
        for component, value in enumerate(values):
            assert lib.fx_decimal_from_integer(C.byref(parts[component]), value) == 0
        assert lib.fx_surd_pack(C.byref(number), parts) == 0
        cases.append((f'surd-{index}', bytes(number.bytes), index % 3, (index // 3) % 3))
    for code in [1, 2, 3, 5, 10, 15]:
        for function in range(3):
            record = bytes([0xf0 | code]) + bytes(9)
            cases.append((f'error-{code}', record, function, function))

    wrapper_cases = []
    for index, (name, record, function, unit) in enumerate(cases):
        source = Number.from_buffer_copy(record); output = Number()
        status = lib.fx_trig_decimal(C.byref(output), C.byref(source), function, unit)
        machine.reset(); settings(machine); put(record)
        machine.er(0, 0x8300); machine.reg(2, unit + 4)
        machine.call([0x1c59e, 0x1c58c, 0x1c57a][function])
        expected = bytes(machine.ram[0x8300:0x830a])
        check(f'numeric_core_{function}_{unit}', [status, bytes(output.bytes).hex(), bytes(source.bytes).hex()],
              [0, expected.hex(), record.hex()], [name, record.hex()])
        if index < len(named)*9 + 435 or index % 13 == 0:
            for exact in [0, 1]: wrapper_cases.append((name, record, function, unit, exact))
        if index < 200:
            alias = Number.from_buffer_copy(record)
            alias_status = lib.fx_trig_decimal(C.byref(alias), C.byref(alias), function, unit)
            check('numeric_alias', [alias_status, bytes(alias.bytes).hex()],
                  [status, bytes(output.bytes).hex()], [name, record.hex()])

    # Explicit degree/radian/grad postfix conversion, including the native
    # same-unit record-preservation branch and surd preconversion.
    conversion_cases = cases[:len(named)*9] + cases[-618:]
    conversion_cases += [case for index, case in enumerate(cases) if index % 19 == 0]
    for name, record, _, _ in conversion_cases:
        for from_unit in range(3):
            for to_unit in range(3):
                source = Number.from_buffer_copy(record); output = Number()
                status = lib.fx_angle_convert(C.byref(output), C.byref(source), from_unit, to_unit)
                machine.reset(); settings(machine); machine.ram[0x8105] = to_unit + 4; put(record)
                machine.er(0, 0x8300); machine.reg(2, from_unit + 4); machine.call(0x1c340)
                expected = bytes(machine.ram[0x8300:0x830a])
                check('angle_conversion_1c340', [status, bytes(output.bytes).hex(), bytes(source.bytes).hex()],
                      [0, expected.hex(), record.hex()], [name, record.hex(), from_unit, to_unit])

    # These run complete original wrappers, including numeric trig and the
    # permission-dependent exact/decimal replacement. Permission is resolved
    # through the same prepared evaluator configuration used by other suites.
    for name, record, function, unit, exact in wrapper_cases:
        source = Number.from_buffer_copy(record); output = Number(); matched = C.c_uint()
        status = lib.fx_trig_evaluate(C.byref(output), C.byref(source), function, unit,
                                      exact, C.byref(matched))
        machine.reset(); settings(machine); machine.ram[0x8106] = exact; put(record)
        machine.er(0, 0x8300); machine.reg(2, unit + 4)
        machine.call([0x16268, 0x16272, 0x16308][function])
        expected = bytes(machine.ram[0x8300:0x830a])
        native_match = bool(machine.counts[0x162de // 2])
        check('complete_wrapper', [status, bytes(output.bytes).hex(), bool(matched.value), bytes(source.bytes).hex()],
              [0, expected.hex(), native_match, record.hex()], [name, record.hex(), function, unit, exact])

    report = {'cases': sum(counts.values()), 'groups': counts, 'failures': len(failures),
              'mismatches': failures, 'seed': '0x1a2d4', 'random_cases': args.random_cases,
              'scope': 'native1ACEC coordinate pairs, all9 explicit angle conversions1C340, complete forward numeric cores1C59E/1C58C/1C57A and full wrappers16268/16272/16308',
              'input': 'identical decimal, rational, two-term surd and error records; function, resolved unit and output permission',
              'output': 'all10 result bytes, wrapper match branch, immutable source and aliases',
              'limitation': 'prepared routine/evaluator contexts; inverse/hyperbolic functions, global UI effects and reset-to-keypress I/O are outside this suite'}
    path = ROOT / 'analysis/c-verification/trig_math.json'
    if failures:
        report['status'] = 'fail'; path.write_text(json.dumps(report, indent=2) + '\n')
    else:
        write_report(path, report, ['csrc/trig/fx_trig_math.c', 'csrc/trig/fx_trig_math.h',
                                   'csrc/trig/fx_trig.c', 'csrc/trig/fx_trig.h',
                                   'csrc/numeric/fx_numeric.c', 'csrc/numeric/fx_numeric.h',
                                   'tools/trace_natural_result.py', 'tools/c_verification.py'],
                     'tools/test_trig_math_c.py')
    print(f'{sum(counts.values())} trig arithmetic checks, {len(failures)} mismatches')
    for failure in failures[:12]: print(failure)
    if failures: raise SystemExit(1)


if __name__ == '__main__': main()
