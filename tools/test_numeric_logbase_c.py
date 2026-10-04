#!/usr/bin/env python3
"""Compare readable arbitrary-base logarithm with public native routine1C082.

The extracted firmware and independent CPU are test oracles only.
GPL-3.0-or-later.
"""
import argparse
import ctypes as C
import hashlib
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
    if not mantissa: return bytes([flags]) + bytes(9)
    digits = f'{mantissa:015d}'
    return bytes([int(digits[0]) | flags,
                  *(int(digits[i:i + 2], 16) for i in range(1, 15, 2)),
                  int(f'{exponent % 100:02d}', 16), (exponent >= 0) + (5 if sign < 0 else 0)])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--random-cases', type=int, default=5000)
    parser.add_argument('--no-report', action='store_true')
    args = parser.parse_args()
    build = ROOT / 'analysis/build/numeric/logbase'
    build.mkdir(parents=True, exist_ok=True)
    sources = ['csrc/numeric/fx_numeric.c', 'csrc/numeric/fx_transcend.c',
               'csrc/numeric/fx_logbase.c']
    library = build / 'logbase.so'
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror', '-pedantic',
                    '-shared', '-fPIC', *(str(ROOT / p) for p in sources), '-o', str(library)], check=True)
    lib = C.CDLL(str(library))
    pointer = C.POINTER(Number)
    lib.fx_number_log_base.argtypes = [pointer, pointer, pointer]
    lib.fx_decimal_parse.argtypes = [pointer, C.c_char_p]
    lib.fx_rational_encode.argtypes = [pointer, C.POINTER(Rational)]
    lib.fx_surd_pack.argtypes = [pointer, pointer]
    rom = (ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    machine = Machine(rom, build / 'oracle')
    rng = random.Random(0x190ce)
    cases, counts, failures = [], {}, []

    def literal(text):
        value = Number()
        assert lib.fx_decimal_parse(C.byref(value), str(text).encode()) == 0
        return bytes(value.bytes)

    def rational(n, d, flags):
        value = Number(); fraction = Rational(n, d, flags)
        assert lib.fx_rational_encode(C.byref(value), C.byref(fraction)) == 0
        return bytes(value.bytes)

    def surd():
        components = (Number * 6)(); value = Number()
        values = [rng.randrange(-99, 100), rng.randrange(1, 1000), rng.randrange(1, 100),
                  rng.randrange(-99, 100), rng.randrange(1, 1000), rng.randrange(1, 100)]
        for component, integer in zip(components, values):
            assert lib.fx_decimal_parse(C.byref(component), str(integer).encode()) == 0
        assert lib.fx_surd_pack(C.byref(value), components) == 0
        return bytes(value.bytes)

    named = ['0', '-1', '-2', '.1', '.5', '1', '2', '3', '4', '8', '10', '16',
             '100', '1e-99', '1e-98', '1e-50', '1e99', '-1e99', '-1e-99',
             '1.00000000000001', '1.00000000000002', '.999999999999999',
             '.999999999999998', '2.71828182845904', '3.14159265358979']
    for base in named:
        for argument in named:
            cases.append(('named', base + ':' + argument, literal(base), literal(argument)))
    for exponent in range(-99, 100):
        for mantissa in [10**14, 10**14 + 1, 10**14 + 9, 10**15 - 1]:
            for flags in [0, 0x40]:
                value = decimal_record(mantissa, exponent, 1, flags)
                for other in ['.5', '1', '2', '10', '1e-99', '1e99']:
                    cases.append(('decimal_scales', f'base-{exponent}-{mantissa}-{flags}-{other}', value, literal(other)))
                    cases.append(('decimal_scales', f'argument-{exponent}-{mantissa}-{flags}-{other}', literal(other), value))
    for flags in [0, 0x40]:
        zero = decimal_record(0, 0, flags=flags)
        for other in ['0', '1', '2', '-2']:
            cases.append(('marked_zero', f'base-{flags}-{other}', zero, literal(other)))
            cases.append(('marked_zero', f'argument-{flags}-{other}', literal(other), zero))
    for index in range(args.random_cases):
        records = []
        for _ in range(2):
            records.append(decimal_record(rng.randrange(10**14, 10**15), rng.randrange(-99, 100),
                                          rng.choice([-1, 1, 1, 1]), rng.choice([0, 0x40])))
        cases.append(('random_decimal', str(index), *records))
        records = [rational(rng.randrange(-10000, 10001), rng.randrange(1, 10000), rng.choice([0, 0x40]))
                   for _ in range(2)]
        cases.append(('random_rational_tags', str(index), *records))
        # Exercise both exact/decimal operand orders and exact/exact cases.
        exact = surd()
        other = literal(rng.choice(['.5', '1', '2', '10', '100', '1e-99', '1e99']))
        cases.append(('random_surd_tags', str(index) + '-base', exact, other))
        cases.append(('random_surd_tags', str(index) + '-argument', other, exact))
        if index % 5 == 0: cases.append(('random_surd_tags', str(index) + '-both', exact, surd()))
    for record in [bytes.fromhex('80000001000201020100'),
                   bytes.fromhex('89970199099801990106'),
                   bytes.fromhex('2717a394600000000806'),
                   bytes.fromhex('6717a394600000000801')]:
        for other in ['.5', '1', '2', '10']:
            cases.append(('exact_regressions', record.hex() + '-base', record, literal(other)))
            cases.append(('exact_regressions', record.hex() + '-argument', literal(other), record))
    for code in range(16):
        error = bytes([0xf0 | code]) + bytes(9)
        for other in ['0', '1', '2', '-1']:
            cases.append(('error_records', f'base-{code}-{other}', error, literal(other)))
            cases.append(('error_records', f'argument-{code}-{other}', literal(other), error))

    def check(group, actual, expected, detail):
        counts[group] = counts.get(group, 0) + 1
        if actual != expected:
            failures.append({'group': group, 'detail': detail, 'actual': actual, 'expected': expected})

    for index, (group, name, base_raw, argument_raw) in enumerate(cases):
        base = Number.from_buffer_copy(base_raw); argument = Number.from_buffer_copy(argument_raw); out = Number()
        status = lib.fx_number_log_base(C.byref(out), C.byref(base), C.byref(argument))
        machine.reset(); settings(machine)
        for position, value in enumerate(base_raw): machine.ram[0x8300 + position] = value
        for position, value in enumerate(argument_raw): machine.ram[0x8400 + position] = value
        machine.er(0, 0x8300); machine.er(2, 0x8400); machine.call(0x1c082, limit=3000000)
        expected = bytes(machine.ram[0x8300:0x830a])
        check(group, [status, bytes(out.bytes).hex(), bytes(base.bytes).hex(), bytes(argument.bytes).hex()],
              [0, expected.hex(), base_raw.hex(), argument_raw.hex()], [name, base_raw.hex(), argument_raw.hex()])
        if index % 17 == 0:
            output_base = Number.from_buffer_copy(base_raw)
            check('output_alias_base',
                  [lib.fx_number_log_base(C.byref(output_base), C.byref(output_base), C.byref(argument)), bytes(output_base.bytes).hex()],
                  [status, bytes(out.bytes).hex()], [name, base_raw.hex(), argument_raw.hex()])
            output_argument = Number.from_buffer_copy(argument_raw)
            check('output_alias_argument',
                  [lib.fx_number_log_base(C.byref(output_argument), C.byref(base), C.byref(output_argument)), bytes(output_argument.bytes).hex()],
                  [status, bytes(out.bytes).hex()], [name, base_raw.hex(), argument_raw.hex()])
        if index % 97 == 0:
            machine.reset(); settings(machine)
            for position, value in enumerate(base_raw): machine.ram[0x8300 + position] = value
            machine.er(0, 0x8300); machine.er(2, 0x8300); machine.call(0x1c082, limit=3000000)
            expected_same = bytes(machine.ram[0x8300:0x830a])
            alias = Number.from_buffer_copy(base_raw)
            check('all_operands_alias',
                  [lib.fx_number_log_base(C.byref(alias), C.byref(alias), C.byref(alias)), bytes(alias.bytes).hex()],
                  [0, expected_same.hex()], [name, base_raw.hex()])

    # Host guards reject nonnormalized mantissas; no native malformed behavior
    # is claimed by these explicit API checks.
    malformed = Number.from_buffer_copy(bytes.fromhex('00000000000000010001'))
    valid = Number.from_buffer_copy(literal('2')); out = Number()
    check('host_malformed_guard', lib.fx_number_log_base(C.byref(out), C.byref(malformed), C.byref(valid)), -1, 'base')
    check('host_malformed_guard', lib.fx_number_log_base(C.byref(out), C.byref(valid), C.byref(malformed)), -1, 'argument')
    report = {'cases': sum(counts.values()), 'groups': counts, 'failures': len(failures),
              'mismatches': failures, 'rom_sha256': hashlib.sha256(rom).hexdigest(),
              'seed': '0x190ce', 'random_cases_per_record_family': args.random_cases,
              'scope': 'Prepared real arbitrary-base logarithm public1C082/kernel190CE, base operand0 and argument operand2',
              'input': 'Identical normalized decimal, marked decimal, rational/marked-rational and compact two-surd tags, all16 error-code records',
              'output': 'All10 numeric result bytes including domain errors, source immutability, first/second/all operand output aliases',
              'limitation': 'Real prepared COMP routine contexts; scratch RAM, nonreal/unsupported tags, malformed native BCD and expression grammar are outside this suite'}
    path = ROOT / 'analysis/c-verification/numeric_logbase.json'
    if args.no_report:
        (build / 'exploration.json').write_text(json.dumps(report, indent=2) + '\n')
    elif failures:
        report['status'] = 'fail'; path.write_text(json.dumps(report, indent=2) + '\n')
    else:
        write_report(path, report, sources + ['csrc/numeric/fx_numeric.h', 'csrc/numeric/fx_logbase.h',
                                             'csrc/numeric/fx_transcend.h', 'csrc/numeric/fx_transcend_internal.h', 'csrc/numeric/fx_transcend_guarded.h',
                                             'csrc/numeric/logbase_manifest.json',
                                             'tools/trace_natural_result.py', 'tools/c_verification.py'],
                     'tools/test_numeric_logbase_c.py')
    print(f'{sum(counts.values())} arbitrary-base logarithm checks, {len(failures)} mismatches')
    for failure in failures[:30]: print(failure)
    if failures: raise SystemExit(1)


if __name__ == '__main__': main()
