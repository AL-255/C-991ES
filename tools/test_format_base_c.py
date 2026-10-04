#!/usr/bin/env python3
"""Differential BASE-N result serialization against original158B8.

GPL-3.0-or-later. The firmware/CPU execute only in the independent oracle.
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


def decimal_record(mantissa, exponent, sign=1):
    if not mantissa: return bytes(10)
    digits = f'{mantissa:015d}'
    return bytes([int(digits[0]), *(int(digits[i:i + 2], 16) for i in range(1, 15, 2)),
                  int(f'{exponent % 100:02d}', 16), (exponent >= 0) + (5 if sign < 0 else 0)])


def main():
    directory = ROOT / 'analysis/build/format/base'
    directory.mkdir(parents=True, exist_ok=True)
    library = directory / 'base.so'
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror', '-pedantic',
                    '-shared', '-fPIC', str(ROOT / 'csrc/format/fx_format_base.c'),
                    str(ROOT / 'csrc/numeric/fx_numeric.c'), '-o', str(library)], check=True)
    lib = C.CDLL(str(library))
    lib.fx_format_base.argtypes = [C.POINTER(Number), C.c_uint8, C.POINTER(C.c_uint8),
                                   C.c_size_t, C.POINTER(Result)]
    lib.fx_decimal_parse.argtypes = [C.POINTER(Number), C.c_char_p]
    rom = (ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    machine = Machine(rom, directory / 'oracle')
    rng = random.Random(0x158b8)
    cases, failures, writes = [], [], set()
    bases = [1, 7, 9, 15]

    def literal(text):
        value = Number()
        assert lib.fx_decimal_parse(C.byref(value), str(text).encode()) == 0
        return bytes(value.bytes)

    for text in ['0','1','-1','255','-255','32767','32768','-32768','-32769',
                 '4294967295','4294967296','-2147483648','-4294967295',
                 '1.5','-.5','1e20','1e-99','1e99','-1e99']:
        for base in bases: cases.append((text, literal(text), base))
    for center in [32768, 2**31, 2**32, 2**33, 10**10]:
        for offset in range(-20, 21):
            for sign in [-1, 1]:
                for base in bases:
                    value = sign * (center + offset)
                    cases.append((f'range-{value}', literal(value), base))
    for index in range(6000):
        if index % 2:
            record = literal(rng.randrange(-9999999999, 10000000000))
        else:
            record = decimal_record(rng.randrange(10**14, 10**15), rng.randrange(-99, 100),
                                    rng.choice([-1, 1]))
        cases.append((f'decimal-{index}', record, bases[index % 4]))
    for record in ['21a30000000000000301','80000001000201020100',
                   '41000000000000000001','f3000000000000000000',
                   '00000000000000000005','00000000000000000006']:
        for base in bases: cases.append(('record-' + record, bytes.fromhex(record), base))

    def oracle(record, base):
        machine.reset(); settings(machine)
        machine.ram[0x80f9] = 2; machine.ram[0x80fa] = base
        for position, value in enumerate(record): machine.ram[0x8300 + position] = value
        machine.er(0, 0x8300); machine.er(2, 0x8500); machine.call(0x158b8)
        return bytes(machine.ram[0x8500:0x8600]).split(b'\0', 1)[0]

    for index, (name, record, base) in enumerate(cases):
        source = Number.from_buffer_copy(record); output = (C.c_uint8 * 64)(); result = Result()
        status = lib.fx_format_base(C.byref(source), base, output, len(output), C.byref(result))
        expected = oracle(record, base)
        actual = bytes(output[:result.length])
        if (status, actual, result.kind, result.recognized, bytes(source.bytes)) != (0, expected, 0, 0, record):
            failures.append({'case': name, 'record': record.hex(), 'base': base, 'status': status,
                             'actual': actual.hex(), 'expected': expected.hex(), 'kind': result.kind,
                             'immutable': bytes(source.bytes) == record})
        if index < 76:
            writes.update(address for address, count in enumerate(machine.ram_writes) if count)
    bounds = 0
    for name, record, base in cases[:24]:
        source = Number.from_buffer_copy(record); expected = oracle(record, base)
        for capacity in range(len(expected) + 2):
            storage = (C.c_uint8 * 80)(*([0xa5] * 80)); result = Result()
            pointer = C.cast(C.byref(storage, 1), C.POINTER(C.c_uint8))
            status = lib.fx_format_base(C.byref(source), base, pointer, capacity, C.byref(result))
            assert status == (0 if capacity > len(expected) else -2)
            assert result.length == len(expected) and result.kind == 0
            assert storage[0] == 0xa5 and storage[capacity + 1] == 0xa5
            if capacity: assert storage[min(capacity, len(expected) + 1)] == 0
            bounds += 1
    for base in set(range(256)) - set(bases):
        source = Number.from_buffer_copy(literal(1)); output = (C.c_uint8 * 64)(); result = Result()
        assert lib.fx_format_base(C.byref(source), base, output, len(output), C.byref(result)) == -3
    persistent = sorted(address for address in writes
                        if not (0x8000 <= address < 0x8070 or 0x8500 <= address < 0x8520 or
                                0x8b00 <= address < 0x8df0))
    report = {'cases': len(cases), 'failures': len(failures), 'mismatches': failures,
              'buffer_boundary_cases': bounds, 'explicit_unsupported_base_values': 252,
              'native_writes_outside_numeric_workspace_output_and_call_stack': [hex(a) for a in persistent],
              'scope': '158B8 decimal BASE-N token serialization for valid80FA masks1/7/9/15',
              'input': 'canonical decimal records across exponents-99..99, signs, radix range/wrap boundaries, fractional and tagged/error controls',
              'output': 'exact tokens, required length, empty rejection outputs, immutable source and bounded NUL termination',
              'limitation': 'invalid base settings/malformedBCD are explicit unsupported paths; LCD mode header and native numeric scratch/call-stack writes belong to controllers'}
    path = ROOT / 'analysis/c-verification/format_base.json'
    if failures:
        report['status'] = 'fail'; path.write_text(json.dumps(report, indent=2) + '\n')
    else:
        write_report(path, report, ['csrc/format/fx_format_base.c', 'csrc/format/fx_format_base.h',
                                   'csrc/format/fx_format.h', 'csrc/numeric/fx_numeric.c',
                                   'csrc/numeric/fx_numeric.h', 'tools/trace_natural_result.py',
                                   'tools/c_verification.py'], 'tools/test_format_base_c.py')
    print(f'{len(cases)} BASE-N cases and{bounds} bounded-write checks, {len(failures)} mismatches')
    for failure in failures[:12]: print(failure)
    print('Native writes outside numeric workspace, output and call stack:', report['native_writes_outside_numeric_workspace_output_and_call_stack'])
    if failures: raise SystemExit(1)


if __name__ == '__main__': main()
