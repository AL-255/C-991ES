#!/usr/bin/env python3
"""Compare handwritten scalar combinatorics with the extracted native ROM.

Original firmware execution is confined to this independent test oracle.
GPL-3.0-or-later.
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
    parser.add_argument('--random-cases', type=int, default=3000)
    parser.add_argument('--no-report', action='store_true')
    args = parser.parse_args()
    build = ROOT / 'analysis/build/numeric/combinatorics'
    build.mkdir(parents=True, exist_ok=True)
    sources = ['csrc/numeric/fx_numeric.c', 'csrc/numeric/fx_combinatorics.c']
    library = build / 'combinatorics.so'
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror', '-pedantic',
                    '-shared', '-fPIC', *(str(ROOT / p) for p in sources), '-o', str(library)], check=True)
    lib = C.CDLL(str(library))
    pointer = C.POINTER(Number)
    for name in ['factorial', 'percent']:
        getattr(lib, 'fx_number_' + name).argtypes = [pointer, pointer]
    for name in ['permutation', 'combination']:
        getattr(lib, 'fx_number_' + name).argtypes = [pointer, pointer, pointer]
    lib.fx_decimal_parse.argtypes = [pointer, C.c_char_p]
    lib.fx_rational_encode.argtypes = [pointer, C.POINTER(Rational)]
    lib.fx_surd_pack.argtypes = [pointer, pointer]
    rom = (ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    machine = Machine(rom, build / 'oracle')
    rng = random.Random(0x1929e)
    cases, counts, failures = [], {}, []

    def literal(text):
        record = Number()
        assert lib.fx_decimal_parse(C.byref(record), str(text).encode()) == 0
        return bytes(record.bytes)

    def rational(n, d, flags=0):
        record = Number(); value = Rational(n, d, flags)
        assert lib.fx_rational_encode(C.byref(record), C.byref(value)) == 0
        return bytes(record.bytes)

    def add_unary(name, raw):
        for function in ['factorial', 'percent']: cases.append((name, function, raw, None))

    def add_binary(name, n, r):
        for function in ['permutation', 'combination']: cases.append((name, function, n, r))

    for value in range(-5, 101):
        add_unary(f'integer-{value}', literal(value))
        for selected in [0, 1, 2, value // 2, value - 1, value, value + 1]:
            add_binary(f'grid-{value}-{selected}', literal(value), literal(selected))
    for n in [0, 1, 2, 5, 10, 20, 30, 50, 68, 69, 70, 71, 99, 100,
              200, 1000, 999999, 9999999999, 10000000000, 99999999999999, 999999999999999, 1000000000000000,
              9999999999999990, 10000000000000000]:
        add_unary(f'boundary-{n}', literal(n))
        for r in [0, 1, 2, 3, 6, 10, 30, 69, 70, 100, n // 2, n - 1, n]:
            add_binary(f'boundary-{n}-{r}', literal(n), literal(r))
    for text in ['.5', '-.5', '.999999999999999', '1.00000000000001',
                 '68.9999999999999', '69.0000000000001', '69.9999999999999',
                 '70.0000000000001', '1e-99', '-1e-99', '1e99', '-1e99']:
        add_unary(text, literal(text))
        add_binary(text, literal(text), literal(1))
        add_binary(text + '-r', literal(5), literal(text))
    for exponent in range(-99, 100):
        for mantissa in [10**14, 10**14 + 1, 10**15 - 1]:
            for flags in [0, 0x40]:
                record = decimal_record(mantissa, exponent, 1, flags)
                add_unary(f'scale-{exponent}-{mantissa}-{flags}', record)
                add_binary(f'scale-n-{exponent}-{mantissa}-{flags}', record, literal(1))
                add_binary(f'scale-r-{exponent}-{mantissa}-{flags}', literal(5), record)
    for index in range(args.random_cases):
        if index % 3 == 0:
            n = literal(rng.randrange(-10, 101)); r = literal(rng.randrange(-5, 102))
        else:
            n = decimal_record(rng.randrange(10**14, 10**15), rng.randrange(-99, 100),
                               rng.choice([-1, 1]), rng.choice([0, 0x40]))
            r = decimal_record(rng.randrange(10**14, 10**15), rng.randrange(-99, 100),
                               rng.choice([-1, 1]), rng.choice([0, 0x40]))
        add_unary(f'random-{index}', n); add_binary(f'random-{index}', n, r)
    for index in range(300):
        n = rational(rng.randrange(-1000, 1001), rng.randrange(1, 100), rng.choice([0, 0x40]))
        r = rational(rng.randrange(-1000, 1001), rng.randrange(1, 100), rng.choice([0, 0x40]))
        add_unary(f'rational-{index}', n); add_binary(f'rational-{index}', n, r)
    for index in range(200):
        components = (Number * 6)(); out = Number()
        values = [rng.randrange(-99, 100), rng.randrange(1, 1000), rng.randrange(1, 100),
                  rng.randrange(-99, 100), rng.randrange(1, 1000), rng.randrange(1, 100)]
        for component, value in zip(components, values):
            assert lib.fx_decimal_parse(C.byref(component), str(value).encode()) == 0
        assert lib.fx_surd_pack(C.byref(out), components) == 0
        add_unary(f'surd-{index}', bytes(out.bytes))
        add_binary(f'surd-{index}', bytes(out.bytes), literal(rng.randrange(5)))
    for code in [1, 2, 3, 5, 10, 15]:
        raw = bytes([0xf0 | code]) + bytes(9)
        add_unary(f'error-{code}', raw)
        add_binary(f'error-n-{code}', raw, literal(1))
        add_binary(f'error-r-{code}', literal(5), raw)

    def check(group, actual, expected, detail):
        counts[group] = counts.get(group, 0) + 1
        if actual != expected:
            failures.append({'group': group, 'detail': detail, 'actual': actual, 'expected': expected})

    entries = {'factorial': 0x1c1a2, 'permutation': 0x1c0aa,
               'combination': 0x1c096, 'percent': 0x16182}
    for index, (name, function, n, r) in enumerate(cases):
        source = Number.from_buffer_copy(n); output = Number()
        second = Number.from_buffer_copy(r) if r is not None else None
        api = getattr(lib, 'fx_number_' + function)
        arguments = [C.byref(output), C.byref(source)] + ([C.byref(second)] if second else [])
        status = api(*arguments)
        machine.reset(); settings(machine)
        for position, value in enumerate(n): machine.ram[0x8300 + position] = value
        if r is not None:
            for position, value in enumerate(r): machine.ram[0x8400 + position] = value
        machine.er(0, 0x8300); machine.er(2, 0x8400)
        machine.call(entries[function], limit=3000000)
        expected = bytes(machine.ram[0x8300:0x830a])
        check(function, [status, bytes(output.bytes).hex(), bytes(source.bytes).hex(),
                         bytes(second.bytes).hex() if second else None],
              [0, expected.hex(), n.hex(), r.hex() if r is not None else None], [name, n.hex(), r.hex() if r is not None else None])
        if index < 600:
            alias = Number.from_buffer_copy(n)
            alias_args = [C.byref(alias), C.byref(alias)] + ([C.byref(second)] if second else [])
            check('output_alias', [api(*alias_args), bytes(alias.bytes).hex()],
                  [status, bytes(output.bytes).hex()], [name, function])
            if second:
                alias_second = Number.from_buffer_copy(r)
                check('second_output_alias',
                      [api(C.byref(alias_second), C.byref(source), C.byref(alias_second)), bytes(alias_second.bytes).hex()],
                      [status, bytes(output.bytes).hex()], [name, function])
    report = {'cases': sum(counts.values()), 'groups': counts, 'failures': len(failures),
              'mismatches': failures, 'seed': '0x1929e', 'random_cases': args.random_cases,
              'scope': 'Canonical real factorial1C1A2, permutation1C0AA, combination1C096 and exact percent16182 leaves',
              'input': 'Identical normalized decimal, rational, compact two-surd and error records',
              'output': 'All10 numeric result bytes, F3 domain/intermediate-overflow errors, source immutability and output aliases',
              'limitation': 'Prepared COMP routine contexts; scratch RAM, malformed BCD and expression grammar are outside this suite'}
    path = ROOT / 'analysis/c-verification/combinatorics.json'
    if args.no_report:
        (build / 'exploration.json').write_text(json.dumps(report, indent=2) + '\n')
    elif failures:
        report['status'] = 'fail'; path.write_text(json.dumps(report, indent=2) + '\n')
    else:
        write_report(path, report, sources + ['csrc/numeric/fx_numeric.h', 'csrc/numeric/fx_combinatorics.h',
                                             'csrc/numeric/combinatorics_manifest.json',
                                             'tools/trace_natural_result.py', 'tools/c_verification.py'],
                     'tools/test_combinatorics_c.py')
    print(f'{sum(counts.values())} combinatorics checks, {len(failures)} mismatches')
    for failure in failures[:30]: print(failure)
    if failures: raise SystemExit(1)


if __name__ == '__main__': main()
