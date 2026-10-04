#!/usr/bin/env python3
"""Compare readable normal P/Q/R and t conversion to the original firmware."""
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
from c_verification import write_report
from nxu8.machine import Machine
from trace_natural_result import settings


class Number(C.Structure):
    _fields_ = [('bytes', C.c_uint8 * 10)]
    def raw(self): return bytes(self.bytes)


class Table(C.Structure):
    _fields_ = [('cells', C.POINTER(Number)), ('rows', C.c_uint8),
                ('variables', C.c_uint8), ('frequency', C.c_uint8)]


class Rational(C.Structure):
    _fields_ = [('numerator', C.c_int64), ('denominator', C.c_uint64), ('flags', C.c_uint8)]


def number(raw): return Number((C.c_uint8 * 10)(*raw))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--random-cases', type=int, default=600)
    parser.add_argument('--random-tables', type=int, default=100)
    args = parser.parse_args()
    build = ROOT / 'analysis/build/stats-normal'
    build.mkdir(parents=True, exist_ok=True)
    sources = ['csrc/numeric/fx_numeric.c', 'csrc/numeric/fx_transcend.c',
               'csrc/stats/fx_stats.c', 'csrc/stats/normal/fx_stats_normal.c']
    library = build / 'fx-stats-normal.so'
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror', '-pedantic',
                    '-fPIC', '-shared', *(str(ROOT / p) for p in sources), '-o', str(library)], check=True)
    lib = C.CDLL(str(library))
    ptr = C.POINTER(Number)
    lib.fx_decimal_parse.argtypes = [ptr, C.c_char_p]
    lib.fx_rational_encode.argtypes = [ptr, C.POINTER(Rational)]
    lib.fx_number_sqrt.argtypes = [ptr, ptr, C.c_int]
    lib.fx_stats_normal_probability.argtypes = [ptr, ptr, C.c_int]
    lib.fx_stats_standardize.argtypes = [ptr, C.POINTER(Table), ptr]
    rom = (ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    machine = Machine(rom, build / 'oracle')
    rng = random.Random(0x13662)
    checks = {}

    def literal(text):
        out = Number()
        assert lib.fx_decimal_parse(C.byref(out), str(text).encode()) == 0
        return out.raw()

    def rational(numerator, denominator, flags=0):
        out = Number()
        assert lib.fx_rational_encode(C.byref(out), C.byref(Rational(numerator, denominator, flags))) == 0
        return out.raw()

    def check(group, actual, expected, detail):
        if actual != expected:
            raise AssertionError(f'{group}: {detail}: {actual!r} != {expected!r}')
        checks[group] = checks.get(group, 0) + 1

    def prepare(raw, table=None):
        machine.reset(); settings(machine)
        machine.ram[0x8600:0x860a] = raw
        machine.er(0, 0x8600)
        if table is not None:
            rows, variables, frequency, cells = table
            machine.ram[0x80de] = rows
            machine.ram[0x80fa] = 1 if variables == 1 else 2
            machine.ram[0x8109] = frequency
            payload = b''.join(cells)
            machine.ram[0x82ee:0x82ee+len(payload)] = payload

    def expected(entry):
        regs = machine.call(entry, 8000000)
        return regs[0], bytes(machine.ram[0x8600:0x860a])

    inputs = [literal(s) for s in (
        '0', '1', '-1', '2', '-2', '0.5', '-0.5', '0.000000000000001',
        '-0.000000000000001', '0.123456789012345', '-0.123456789012345',
        '5', '-5', '9.99', '-9.99', '20', '-20', '21.5', '-21.5',
        '100', '-100', '999.999999999999', '-999.999999999999',
        '1000', '-1000', '1e99', '-1e99', '1e-99', '-1e-99')]
    for _ in range(args.random_cases):
        inputs.append(literal(f'{rng.choice((-1,1))*rng.randrange(10**14,10**15)}e{rng.randrange(-20,-10)}'))
    # Evaluation markers, exact rationals/surds, and every early error nibble.
    inputs += [bytes([0x40 | raw[0], *raw[1:]]) for raw in inputs[:29]]
    inputs += [rational(n, d, f) for n, d in ((1,2),(-1,2),(5,3),(-5,3),(0,1),(1000,1)) for f in (0,0x40)]
    for s in ('2','3'):
        root = number(literal(s)); assert lib.fx_number_sqrt(C.byref(root), C.byref(root), 1) == 0
        inputs.append(root.raw())
    inputs += [bytes([0xf0 | code, *range(1,10)]) for code in range(16)]
    entries = (0x13662, 0x13702, 0x1371c)
    for raw in inputs:
        source = number(raw)
        for function, entry in enumerate(entries):
            prepare(raw)
            native = expected(entry)
            out = Number()
            status = lib.fx_stats_normal_probability(C.byref(out), C.byref(source), function)
            check('normal_probability', (status, out.raw()), native,
                  f'function={function}, input={raw.hex()}')
            check('normal_source_immutable', source.raw(), raw, raw.hex())
            alias = number(raw)
            alias_status = lib.fx_stats_normal_probability(C.byref(alias), C.byref(alias), function)
            check('normal_output_alias', (alias_status, alias.raw()), native, raw.hex())

    datasets = [(0,1,0,[]), (1,1,0,[literal(1)]),
                (3,1,0,[literal(s) for s in ('1','2','3')]),
                (3,1,1,[literal(s) for s in ('1','2','2','3','3','4')]),
                (2,1,1,[literal(s) for s in ('1','0','2','0')]),
                (2,1,1,[literal(s) for s in ('1','1','2','-1')])]
    for _ in range(args.random_tables):
        variables = rng.choice((1,2)); frequency = rng.randrange(2)
        rows = rng.randrange(1, min(20, 60//(variables+frequency))+1)
        cells = []
        for row in range(rows):
            cells.extend(literal(f'{rng.randrange(-100000,100001)}e-3') for axis in range(variables))
            if frequency: cells.append(literal(rng.randrange(5)))
        datasets.append((rows,variables,frequency,cells))
    for variables, frequency in ((1,0),(1,1),(2,0),(2,1)):
        rows = 60//(variables+frequency)
        cells = [literal((row%11)-4 if axis < variables else row%5)
                 for row in range(rows) for axis in range(variables+frequency)]
        datasets.append((rows,variables,frequency,cells))
    arguments = [literal(s) for s in ('0','1','-1','0.123456789012345')]
    arguments += [rational(1,2), rational(1,2,0x40), inputs[-17]]
    arguments += [bytes([0xf0 | code, *range(1,10)]) for code in range(16)]
    for data in datasets:
        rows,variables,frequency,cells = data
        storage = (Number * len(cells))(*(number(raw) for raw in cells))
        table = Table(storage,rows,variables,frequency)
        for raw in arguments:
            prepare(raw, data)
            native = expected(0x13740)
            source = number(raw); out = Number()
            status = lib.fx_stats_standardize(C.byref(out), C.byref(table), C.byref(source))
            check('standardize', (status,out.raw()), native, f'table={data}, input={raw.hex()}')
            check('standardize_source_immutable', source.raw(), raw, raw.hex())
        check('standardize_table_immutable', bytes(storage), b''.join(cells), str(data))
    guard = number(literal(123)); original = guard.raw()
    for out, source, function in ((None,C.byref(guard),0),(C.byref(guard),None,0),
                                  (C.byref(guard),C.byref(guard),-1),
                                  (C.byref(guard),C.byref(guard),3)):
        check('normal_host_guard', lib.fx_stats_normal_probability(out,source,function), -1, str(function))
    check('normal_guard_immutable', guard.raw(), original, 'host guard output')
    report = {'status':'pass', 'rom_sha256':hashlib.sha256(rom).hexdigest(),
              'random_seed':'0x13662', 'probability_inputs':len(inputs), 'datasets':len(datasets),
              'checks':checks, 'checks_total':sum(checks.values()),
              'scope':'Complete P/Q/R record/status results, early error preservation, five-significant-digit rounding and prepared t conversion; finite differential fixtures.',
              'excluded':'Statistics mode lifecycle, live interrupts, CPU scratch RAM, malformed numeric records'}
    pinned = sources + ['csrc/numeric/fx_numeric.h', 'csrc/numeric/fx_transcend.h',
                        'csrc/numeric/fx_transcend_internal.h', 'csrc/stats/fx_stats.h',
                        'csrc/stats/normal/fx_stats_normal.h', 'tools/trace_natural_result.py']
    write_report('analysis/c-verification/stats_normal.json', report, pinned, 'tools/test_stats_normal_c.py')
    print(json.dumps(report,indent=2))


if __name__ == '__main__': main()
