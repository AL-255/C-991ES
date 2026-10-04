#!/usr/bin/env python3
"""Compare native3500 budget6/table and budget12/inequality formatting.

GPL-3.0-or-later. The original ROM executes only in the independent oracle.
"""
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


class Result(C.Structure):
    _fields_ = [('length', C.c_size_t), ('kind', C.c_uint8), ('recognized', C.c_uint8)]


class Rational(C.Structure):
    _fields_ = [('numerator', C.c_int64), ('denominator', C.c_uint64), ('flags', C.c_uint8)]


def record(mantissa, exponent, sign=1):
    if not mantissa: return bytes(10)
    digits = f'{mantissa:015d}'
    return bytes([int(digits[0]), *(int(digits[i:i + 2], 16) for i in range(1, 15, 2)),
                  int(f'{exponent % 100:02d}', 16), (exponent >= 0) + (5 if sign < 0 else 0)])


def main():
    directory = ROOT / 'analysis/build/format/budget'
    directory.mkdir(parents=True, exist_ok=True)
    library = directory / 'budget.so'
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror', '-pedantic',
                    '-shared', '-fPIC', str(ROOT / 'csrc/format/fx_format_budget.c'),
                    str(ROOT / 'csrc/numeric/fx_numeric.c'), '-o', str(library)], check=True)
    lib = C.CDLL(str(library))
    lib.fx_format_budget.argtypes = [C.POINTER(Number), C.c_uint8, C.c_uint8, C.c_uint8,
                                     C.c_uint8, C.POINTER(C.c_uint8), C.c_size_t, C.POINTER(Result)]
    lib.fx_decimal_parse.argtypes = [C.POINTER(Number), C.c_char_p]
    lib.fx_rational_encode.argtypes = [C.POINTER(Number), C.POINTER(Rational)]
    lib.fx_surd_pack.argtypes = [C.POINTER(Number), C.POINTER(Number)]
    lib.fx_decimal_from_integer.argtypes = [C.POINTER(Number), C.c_int64]
    machine = Machine((ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes(), directory / 'oracle')
    rng = random.Random(0x3500)
    cases, failures, writes = [], [], set()

    def literal(text):
        value = Number(); assert lib.fx_decimal_parse(C.byref(value), str(text).encode()) == 0
        return bytes(value.bytes)

    for text in ['0','1','-1','1.23456789123456','-1.23456789123456',
                 '123456789.123456','-123456789.123456','1.23456789123456e9',
                 '-1.23456789123456e9','1.23456789123456e10','-1.23456789123456e10',
                 '1.23456789123456e-3','-1.23456789123456e-3',
                 '1.23456789123456e-99','-1.23456789123456e-99',
                 '9.99999999994','9.99999999949','9.99999999995e99']:
        for budget in [6, 12]:
            for small in [0, 1]:
                for norm in [0, 1]:
                    for dot in [0, 1]:
                        cases.append((text, literal(text), budget, small, norm, dot, 0, 0))
    for exponent in range(-99, 100):
        for sign in [-1, 1]:
            for budget in [6, 12]:
                for mantissa in [100000000000000, 123456789123456, 999999999949999,
                                 999999999950000, 999999999999999]:
                    cases.append((f'boundary-{exponent}-{sign}-{budget}-{mantissa}',
                                  record(mantissa, exponent, sign), budget,
                                  len(cases) % 2, (len(cases) // 2) % 2, (len(cases) // 4) % 2, 0, 0))
    for index in range(4000):
        value = record(rng.randrange(10**14, 10**15), rng.randrange(-99, 100), rng.choice([-1, 1]))
        if index % 3 == 0: value = bytes([value[0] | 0x40]) + value[1:]
        cases.append((f'random-{index}', value, [6, 12][index % 2], (index // 2) % 2,
                      (index // 4) % 2, (index // 8) % 2, [0, 4, 8, 9][index % 4], index % 10))
    for index in range(300):
        rational = Rational(rng.randrange(-999999, 1000000), rng.randrange(1, 999999), 0)
        value = Number(); assert lib.fx_rational_encode(C.byref(value), C.byref(rational)) == 0
        for budget in [6, 12]:
            cases.append((f'rational-{index}', bytes(value.bytes), budget, index % 2,
                          (index // 2) % 2, (index // 4) % 2, 0, 0))
            marked = bytes([value.bytes[0] | 0x40]) + bytes(value.bytes[1:])
            cases.append((f'marked-rational-{index}', marked, budget, index % 2,
                          (index // 2) % 2, (index // 4) % 2, 0, 0))
    for index in range(100):
        parts = (Number * 6)(); value = Number()
        for position, integer in enumerate([rng.randrange(-99,100), rng.randrange(1,1000), rng.randrange(1,100),
                                           rng.randrange(-99,100), rng.randrange(1,1000), rng.randrange(1,100)]):
            assert lib.fx_decimal_from_integer(C.byref(parts[position]), integer) == 0
        assert lib.fx_surd_pack(C.byref(value), parts) == 0
        for budget in [6, 12]:
            cases.append((f'surd-{index}', bytes(value.bytes), budget, index % 2,
                          (index // 2) % 2, (index // 4) % 2, 0, 0))
    for error in range(1, 16):
        for budget in [6, 12]:
            cases.append((f'error-{error}', bytes([0xf0 | error]) + bytes(9), budget, 0, 0, 1, 0, 0))
    for budget in [6, 12]:
        cases.append(('null', None, budget, 0, 0, 0, 0, 0))

    def oracle(value, budget, small, norm, dot, mode, digits):
        machine.reset(); settings(machine)
        machine.ram[0x8127] = small; machine.ram[0x80ff] = 20 if norm else 0
        machine.ram[0x8104] = dot; machine.ram[0x8102] = mode; machine.ram[0x8103] = digits
        if value is not None: machine.ram[0x8300:0x830a] = value
        machine.er(0, 0x8300 if value is not None else 0); machine.er(2, 0x8500)
        machine.ram[0x8dee] = budget; machine.call(0x3500)
        return bytes(machine.ram[0x8500:0x8700]).split(b'\0', 1)[0]

    for index, (name, value, budget, small, norm, dot, mode, digits) in enumerate(cases):
        source = Number.from_buffer_copy(value) if value is not None else None
        output = (C.c_uint8 * 64)(); result = Result()
        status = lib.fx_format_budget(C.byref(source) if source is not None else None, budget,
                                      small, norm, dot, output, len(output), C.byref(result))
        expected = oracle(value, budget, small, norm, dot, mode, digits)
        actual = bytes(output[:result.length])
        if (status, actual, result.kind, result.recognized) != (0, expected, 10, 0):
            failures.append({'case': name, 'record': value.hex() if value is not None else None,
                             'budget': budget, 'small_exponent': small, 'extended_norm': norm,
                             'dot': dot, 'status': status, 'actual': actual.hex(), 'expected': expected.hex()})
        assert source is None or bytes(source.bytes) == value
        if index < 288:
            writes.update(address for address, count in enumerate(machine.ram_writes) if count)
    bounds = 0
    for name, value, budget, small, norm, dot, mode, digits in cases[:288]:
        source = Number.from_buffer_copy(value); expected = oracle(value, budget, small, norm, dot, mode, digits)
        for capacity in range(len(expected) + 2):
            storage = (C.c_uint8 * 80)(*([0xa5] * 80)); result = Result()
            pointer = C.cast(C.byref(storage, 1), C.POINTER(C.c_uint8))
            status = lib.fx_format_budget(C.byref(source), budget, small, norm, dot, pointer,
                                          capacity, C.byref(result))
            assert status == (0 if capacity > len(expected) else -2)
            assert result.length == len(expected) and result.kind == 10
            assert storage[0] == 0xa5 and storage[capacity + 1] == 0xa5
            if capacity: assert storage[min(capacity, len(expected) + 1)] == 0
            bounds += 1
    persistent = sorted(address for address in writes if not (
        0x8000 <= address < 0x8070 or 0x8500 <= address < 0x8520 or 0x8b00 <= address < 0x8df0))
    report = {'cases': len(cases), 'failures': len(failures), 'mismatches': failures,
              'buffer_boundary_cases': bounds,
              'native_writes_outside_numeric_workspace_output_and_call_stack': [hex(a) for a in persistent],
              'scope': '3500 budget6/table and budget12/inequality decimal serialization for both exponent font states',
              'input': 'decimal exponents-99..99, signs, marked decimals, canonical rational/surd records, errors and null pointer; 80FF low threshold and 8104 punctuation; Norm/Fix/Sci independent',
              'output': 'exact tokens, required length, error strings, empty null output, immutable input and bounded NUL writes',
              'limitation': 'routine boundary with prepared RAM; numeric CPU scratch/call-stack writes are not implementation outputs; budgets other than6/12 have no native callers'}
    path = ROOT / 'analysis/c-verification/format_budget.json'
    if failures:
        report['status'] = 'fail'; path.write_text(json.dumps(report, indent=2) + '\n')
    else:
        write_report(path, report, ['csrc/format/fx_format_budget.c', 'csrc/format/fx_format_budget.h',
                                   'csrc/format/fx_format.h', 'csrc/numeric/fx_numeric.c',
                                   'csrc/numeric/fx_numeric.h', 'tools/trace_natural_result.py',
                                   'tools/c_verification.py'], 'tools/test_format_budget_c.py')
    print(f'{len(cases)} budget-format cases and {bounds} bounded-write checks, {len(failures)} mismatches')
    for failure in failures[:12]: print(failure)
    print('Native writes outside numeric workspace, output and call stack:', report['native_writes_outside_numeric_workspace_output_and_call_stack'])
    if failures: raise SystemExit(1)


if __name__ == '__main__': main()
