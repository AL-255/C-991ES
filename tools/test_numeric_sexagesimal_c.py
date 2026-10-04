#!/usr/bin/env python3
"""Compare prepared DMS, unit conversions and constants with the native ROM.
GPL-3.0-or-later. The original CPU/ROM are differential oracles only.
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
from nxu8.machine import Machine
from test_numeric_calculus_c import Number, Pointer, Rational


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--random-cases', type=int, default=1000)
    parser.add_argument('--no-report', action='store_true')
    args = parser.parse_args()
    build = ROOT / 'analysis/build/numeric/sexagesimal'
    build.mkdir(parents=True, exist_ok=True)
    sources = ['csrc/numeric/fx_numeric.c', 'csrc/numeric/fx_sexagesimal.c',
               'csrc/data/fx_rom_data.c']
    library = build / 'sexagesimal.so'
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror', '-pedantic',
                    '-shared', '-fPIC', *(str(ROOT / p) for p in sources), '-o', str(library)], check=True)
    lib = C.CDLL(str(library))
    lib.fx_decimal_parse.argtypes = [Pointer, C.c_char_p]
    lib.fx_rational_encode.argtypes = [Pointer, C.POINTER(Rational)]
    lib.fx_number_sexagesimal.argtypes = [Pointer, Pointer, C.c_size_t]
    lib.fx_number_unit_convert.argtypes = [Pointer, Pointer, C.c_uint]
    lib.fx_number_scientific_constant.argtypes = [Pointer, C.c_uint]
    rom = (ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    machine = Machine(rom, build / 'oracle')
    counts, failures = {}, []
    rng = random.Random(0x16a7e)

    def check(group, actual, expected, detail):
        counts[group] = counts.get(group, 0) + 1
        if actual != expected:
            failures.append({'group': group, 'detail': detail,
                             'actual': actual, 'expected': expected})

    def literal(text):
        number = Number()
        assert lib.fx_decimal_parse(C.byref(number), str(text).encode()) == 0
        return bytes(number.bytes)

    def rational(n, d, flags=0):
        number = Number()
        assert lib.fx_rational_encode(C.byref(number), C.byref(Rational(n, d, flags))) == 0
        return bytes(number.bytes)

    def marked(record):
        return bytes([record[0] | 0x40]) + record[1:]

    def put(address, record):
        for offset, value in enumerate(record): machine.ram[address + offset] = value

    def initialize():
        machine.reset()
        for address, value in [(0x80f9, 0xc1), (0x80f5, 0xf0), (0x80fc, 1),
                               (0x8105, 4), (0x8106, 1), (0x8121, 1)]:
            machine.ram[address] = value
        machine.er(12, 0x8300)

    def dms(group, records):
        initialize()
        machine.reg(10, len(records) - 1)
        machine.reg(11, len(records) - 1)
        machine.reg(6, 0)
        for index, record in enumerate(records[:-1]):
            machine.ram[0x8060 + index] = 0x73
            put(0x8078 + 10 * index, record)
        put(0x8300, records[-1])
        machine.call(0x16a7e)
        expected = bytes(machine.ram[0x8300:0x830a]).hex()
        detail = [record.hex() for record in records]
        numbers = (Number * len(records))(*(Number.from_buffer_copy(record) for record in records))
        out = Number()
        status = lib.fx_number_sexagesimal(C.byref(out), numbers, len(records))
        check(group, [status, bytes(out.bytes).hex()], [0, expected], detail)
        check('dms_native_status_and_stack', [machine.reg(2), machine.reg(10), machine.reg(11)],
              [int(expected[1], 16) if expected.startswith('f') else 0, 0, 0], detail)
        check('dms_input_immutability', bytes(numbers).hex(), b''.join(records).hex(), detail)
        for alias in range(len(records)):
            status = lib.fx_number_sexagesimal(C.byref(numbers[alias]), numbers, len(records))
            check('dms_alias', [status, bytes(numbers[alias].bytes).hex()], [0, expected], [detail, alias])
            numbers = (Number * len(records))(*(Number.from_buffer_copy(record) for record in records))

    def unit(group, record, conversion):
        initialize()
        machine.reg(0, 0xc1)
        machine.reg(1, conversion)
        put(0x8300, record)
        machine.call(0x161a6)
        expected = bytes(machine.ram[0x8300:0x830a]).hex()
        detail = [record.hex(), conversion]
        source = Number.from_buffer_copy(record)
        out = Number()
        status = lib.fx_number_unit_convert(C.byref(out), C.byref(source), conversion)
        check(group, [status, bytes(out.bytes).hex()], [0, expected], detail)
        check('unit_native_status', machine.reg(0), int(expected[1], 16) if expected.startswith('f') else 0, detail)
        check('unit_input_immutability', bytes(source.bytes).hex(), record.hex(), detail)
        status = lib.fx_number_unit_convert(C.byref(source), C.byref(source), conversion)
        check('unit_alias', [status, bytes(source.bytes).hex()], [0, expected], detail)

    zero, one = literal(0), literal(1)
    names = ['0', '-1', '1', '2', '3', '59', '60', '61', '.1', '-.1',
             '.999999999999999', '9999999', '9999999.99999999', '10000000',
             '-9999999', '-10000000', '1e-99', '-1e-99', '1e99', '-1e99', '9e99']
    specials = [rational(1, 3), rational(-2, 7), marked(one), marked(rational(1, 3)),
                bytes.fromhex('80000001000201020100'),
                bytes.fromhex('80001001000001060000')]
    errors = [bytes([0xf0 | code]) + bytes(9) for code in range(16)]
    for text in names:
        value = literal(text)
        for records in [[value], [value, one], [one, value], [value, one, one],
                        [one, value, one], [one, one, value]]:
            dms('dms_named_components', records)
    for value in specials + errors:
        for records in [[value], [value, one, one], [one, value, one], [one, one, value]]:
            dms('dms_tagged_error_components', records)
    for exponent in range(-99, 100):
        for sign in ['', '-']:
            dms('dms_exponent_marker_boundaries', [literal(sign + '1e' + str(exponent))])
    for conversion in range(40):
        for record in [literal(text) for text in names] + specials + errors:
            unit('unit_all_selectors_records', record, conversion)
    for index in range(args.random_cases):
        count = rng.randrange(1, 4)
        records = [literal(f'{rng.randrange(-999999, 1000000)}e{rng.randrange(-99, 94)}')
                   if index % 3 else rational(rng.randrange(-99, 100), rng.randrange(1, 100))
                   for _ in range(count)]
        dms('dms_random_components', records)
        unit('unit_random_scales', records[-1], rng.randrange(40))
    for index in range(40):
        initialize()
        machine.reg(0, index)
        machine.reg(7, 0)
        machine.call(0x16ff6)
        out = Number()
        status = lib.fx_number_scientific_constant(C.byref(out), index)
        check('scientific_constants', [status, bytes(out.bytes).hex(), machine.reg(2)],
              [0, bytes(machine.ram[0x8300:0x830a]).hex(), 0], index)
    for count in [0, 4, 999]:
        out = Number.from_buffer_copy(one)
        status = lib.fx_number_sexagesimal(C.byref(out), C.byref(out), count)
        check('invalid_host_api', [status, bytes(out.bytes).hex()], [-1, one.hex()], ['count', count])
    for selector in [40, 255, 2**32 - 1]:
        for api in ['unit', 'constant']:
            out = Number.from_buffer_copy(one)
            status = (lib.fx_number_unit_convert(C.byref(out), C.byref(out), selector) if api == 'unit'
                      else lib.fx_number_scientific_constant(C.byref(out), selector))
            check('invalid_host_api', [status, bytes(out.bytes).hex()], [-1, one.hex()], [api, selector])
    report = {'cases': sum(counts.values()), 'groups': counts, 'failures': len(failures),
              'mismatches': failures, 'random_cases': args.random_cases, 'seed': '0x16a7e',
              'scope': 'Prepared COMP16A7E DMS reducer,161A6 decoded unit selectors0..39 and16FF6 constant selectors0..39',
              'output': 'Complete10-byte numeric records and nativeR2/R0 statuses; pending DMS stack consumption, aliases and immutable inputs',
              'limits': ['DMS tokenizer and outer unary-sign precedence belong to the parser',
                         'Three-digit conversion-selector grammar and model capability limits are not implemented here',
                         'Complex records, rich backing contexts, malformed BCD and keyboard/display execution are excluded']}
    path = ROOT / 'analysis/c-verification/numeric_sexagesimal.json'
    if args.no_report:
        (build / 'exploration.json').write_text(json.dumps(report, indent=2) + '\n')
    elif failures:
        report['status'] = 'fail'; path.write_text(json.dumps(report, indent=2) + '\n')
    else:
        write_report(path, report, sources + ['csrc/numeric/fx_numeric.h',
                     'csrc/numeric/fx_sexagesimal.h', 'csrc/data/fx_rom_data.h',
                     'tools/c_verification.py', 'tools/test_numeric_calculus_c.py'],
                     'tools/test_numeric_sexagesimal_c.py')
    print(f'{sum(counts.values())} sexagesimal/conversion checks, {len(failures)} mismatches')
    for failure in failures[:8]: print(failure)
    if failures: raise SystemExit(1)


if __name__ == '__main__': main()
