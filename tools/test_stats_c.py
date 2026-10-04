#!/usr/bin/env python3
"""Differential tests for the original statistics decimal accumulators."""
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
    def raw(self): return bytes(self.bytes)


class Table(C.Structure):
    _fields_ = [('cells', C.POINTER(Number)), ('rows', C.c_uint8),
                ('variables', C.c_uint8), ('frequency', C.c_uint8)]


class Fit(C.Structure):
    _fields_ = [('a', Number), ('b', Number), ('c', Number), ('correlation', Number)]


class Rational(C.Structure):
    _fields_ = [('numerator', C.c_int64), ('denominator', C.c_uint64), ('flags', C.c_uint8)]


def number(raw): return Number((C.c_uint8 * 10)(*raw))


def raw_decimal(mantissa, exponent, sign=1, flags=0):
    s = f'{mantissa:015d}'
    return bytes([int(s[0]) | flags, *(int(s[i:i+2], 16) for i in range(1, 15, 2)),
                  int(f'{exponent % 100:02}', 16), (exponent >= 0) + 5 * (sign < 0)])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--random-cases', type=int, default=600)
    args = parser.parse_args()
    build = ROOT / 'analysis/build/stats'
    build.mkdir(parents=True, exist_ok=True)
    library = build / 'fx-stats.so'
    sources = ['csrc/numeric/fx_numeric.c', 'csrc/numeric/fx_transcend.c', 'csrc/stats/fx_stats.c']
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror', '-pedantic',
                    '-fPIC', '-shared', *(str(ROOT / p) for p in sources), '-o', str(library)], check=True)
    lib = C.CDLL(str(library))
    ptr = C.POINTER(Number)
    tableptr = C.POINTER(Table)
    lib.fx_decimal_parse.argtypes = [ptr, C.c_char_p]
    lib.fx_rational_encode.argtypes = [ptr, C.POINTER(Rational)]
    lib.fx_number_sqrt.argtypes = [ptr, ptr, C.c_int]
    lib.fx_stats_count.argtypes = [ptr, tableptr]
    lib.fx_stats_extreme.argtypes = [ptr, tableptr, C.c_uint, C.c_int, C.c_int]
    lib.fx_stats_moments.argtypes = [ptr, ptr, tableptr, C.c_uint, C.c_int, ptr]
    lib.fx_stats_cross.argtypes = [ptr, tableptr, C.c_int, C.c_int, ptr, ptr]
    lib.fx_stats_higher_moments.argtypes = [ptr, ptr, tableptr, ptr]
    lib.fx_stats_square_cross.argtypes = [ptr, tableptr, ptr, ptr]
    lib.fx_stats_mean.argtypes = [ptr, tableptr, C.c_uint]
    lib.fx_stats_deviations.argtypes = [ptr, ptr, tableptr, C.c_uint]
    lib.fx_stats_regression.argtypes = [C.POINTER(Fit), tableptr, C.c_int]
    lib.fx_stats_predict.argtypes = [ptr, C.POINTER(Fit), C.c_int, ptr, C.c_int, C.c_int]
    rom = (ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    m = Machine(rom, build / 'stats-oracle')
    event_library = build / 'stats-events.so'
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror', '-fPIC', '-shared',
                    str(ROOT / 'tools/nxu8/stats_host_events.c'),
                    str(ROOT / 'tools/nxu8/vendor/SimU8/core.c'), '-o', str(event_library)], check=True)
    event = C.CDLL(str(event_library))
    event.stats_oracle_call.argtypes = [C.c_uint32, C.c_uint64, C.c_uint]
    event.harness_init.argtypes = [C.c_void_p, C.c_size_t]
    event.harness_ram.restype = C.POINTER(C.c_uint8 * 65536)
    event.harness_set_reg.argtypes = [C.c_uint, C.c_uint8]
    event.harness_get_reg.argtypes = [C.c_uint]
    event.harness_get_reg.restype = C.c_uint8
    rng = random.Random(0x13150)
    checks = {}
    frame = 0x8b00

    def literal(text):
        out = Number()
        assert lib.fx_decimal_parse(C.byref(out), text.encode()) == 0
        return out.raw()

    def check(group, actual, expected, detail):
        if actual != expected:
            raise AssertionError(f'{group}: {detail}: {actual!r} != {expected!r}')
        checks[group] = checks.get(group, 0) + 1

    def prepare(raws, variables, frequency):
        m.reset(); settings(m)
        m.ram[0x80fa] = 1 if variables == 1 else 2
        m.ram[0x8109] = frequency
        m.ram[0x80de] = len(raws) // (variables + frequency)
        m.ram[0x82ee:0x82ee + 10 * len(raws)] = b''.join(raws)
        m.er(14, frame)

    def native(address, raws, variables, frequency, flags=0, centers=()):
        prepare(raws, variables, frequency)
        for offset, value in centers:
            m.ram[frame + offset:frame + offset + 10] = value
        m.reg(12, flags)
        m.call(address, 3000000)
        return m.reg(0)

    def record(offset): return bytes(m.ram[frame + offset:frame + offset + 10]).hex()

    values = [literal(s) for s in ['0', '1', '-1', '2', '-2', '.1', '-.1',
              '3.14159265358979', '1e-99', '1e99', '999999999999999',
              '1.00000000000001', '.999999999999999', '99.9999999999999']]
    errors = [bytes([0xf0 | i]) + bytes(9) for i in [0, 1, 2, 3, 15]]
    exact_values = []
    for n, d in [(1, 2), (-3, 7), (717, 3946)]:
        for flags in [0, 0x40]:
            out = Number(); value = Rational(n, d, flags)
            assert lib.fx_rational_encode(C.byref(out), C.byref(value)) == 0
            exact_values.append(out.raw())
    for value in ['2', '3']:
        source = number(literal(value)); out = Number()
        assert lib.fx_number_sqrt(C.byref(out), C.byref(source), 1) == 0
        exact_values.append(out.raw())
    datasets = []
    for variables in [1, 2]:
        for frequency in [0, 1]:
            datasets.append(([], variables, frequency, 'empty'))
            for raw in values + errors + exact_values:
                datasets.append(([raw] * variables + ([literal('1')] if frequency else []),
                                 variables, frequency, 'singleton-' + raw.hex()))
            for rows in [2, 3, 10, 20]:
                raws = []
                for i in range(rows):
                    raws += [literal(str(i - rows // 2))] * variables
                    if frequency: raws.append(literal(str(i % 4)))
                datasets.append((raws, variables, frequency, f'zero-weights-{rows}'))
            # The prepared native table's600-byte cell allocation supports
            #60 one-column,30 two-column, or20 three-column rows.
            raws = []
            for row in range(60 // (variables + frequency)):
                raws += [literal(str(row + 1))] * variables
                if frequency: raws.append(literal(str(row % 4 + 1)))
            datasets.append((raws, variables, frequency, 'full600byte-table'))
    for i in range(args.random_cases):
        variables = rng.choice([1, 2]); frequency = rng.choice([0, 1])
        rows = rng.randrange(1, 21)
        raws = []
        for row in range(rows):
            for axis in range(variables):
                raws.append(raw_decimal(rng.randrange(10**14, 10**15),
                                       rng.randrange(-99, 100) if i % 4 == 0 else rng.randrange(-6, 7),
                                       rng.choice([1, -1]), rng.choice([0, 0x40])))
            if frequency:
                raws.append(literal(str(rng.randrange(0, 10))) if i % 3 else
                            raw_decimal(rng.randrange(10**14, 10**15), rng.randrange(-5, 6),
                                        rng.choice([1, 1, -1]), rng.choice([0, 0x40])))
        datasets.append((raws, variables, frequency, f'random-{i}'))
    for frequency in [0, 1]:
        for row_count in [2, 3, 4, 10, 20]:
            for pattern in ['linear', 'quadratic', 'positive']:
                raws = []
                for row in range(row_count):
                    x = row + 1
                    y = 2 + 3*x if pattern == 'linear' else 2 + 3*x + 5*x*x if pattern == 'quadratic' else rng.randrange(1, 1000)
                    raws += [literal(str(x)), literal(str(y))]
                    if frequency: raws.append(literal(str((row % 4) + 1) + '.25'))
                datasets.append((raws, 2, frequency, f'positive-{pattern}-{row_count}'))

    for dataset_index, (raws, variables, frequency, name) in enumerate(datasets):
        cells = (Number * len(raws))(*(number(raw) for raw in raws))
        table = Table(cells, len(raws) // (variables + frequency), variables, frequency)
        before = bytes(cells)
        detail = [name, variables, frequency, [raw.hex() for raw in raws]]
        out = Number()
        expected = native(0x13150, raws, variables, frequency)
        actual = lib.fx_stats_count(C.byref(out), C.byref(table))
        check('count', [actual, out.raw().hex()], [expected, record(-70)], detail)
        for axis in range(variables):
            expected = native(0x12d8e, raws, variables, frequency, axis)
            actual = lib.fx_stats_mean(C.byref(out), C.byref(table), axis)
            check('mean', [actual, out.raw().hex()], [expected, record(-80)], detail + [axis])
            expected = native(0x12c2c, raws, variables, frequency, axis)
            pop, sample = Number(), Number()
            actual = lib.fx_stats_deviations(C.byref(pop), C.byref(sample), C.byref(table), axis)
            check('deviations', [actual, pop.raw().hex(), sample.raw().hex()],
                  [expected, record(-100), record(-110)], detail + [axis])
            for transform in range(4):
                flags = axis | (0x20 if transform & 1 else 0) | (0x40 if transform & 2 else 0)
                for maximum in [0, 1]:
                    expected = native(0x12ef4, raws, variables, frequency, flags | maximum * 0x80)
                    actual = lib.fx_stats_extreme(C.byref(out), C.byref(table), axis, transform, maximum)
                    check('extreme', [actual, out.raw().hex()],
                          [expected, record(-80 if axis == 0 else -90)], detail + [axis, transform, maximum])
                for centered in [False, True]:
                    center = number(literal('1.23456789012345'))
                    centers = [(-80 if axis == 0 else -90, center.raw())] if centered else []
                    expected = native(0x12fe2, raws, variables, frequency, flags | (0x10 if centered else 0), centers)
                    total, square = Number(), Number()
                    actual = lib.fx_stats_moments(C.byref(total), C.byref(square), C.byref(table), axis,
                                                 transform, C.byref(center) if centered else None)
                    offsets = [-100, -110] if axis == 0 else [-120, -130]
                    check('moments', [actual, total.raw().hex(), square.raw().hex()],
                          [expected, *(record(offset) for offset in offsets)], detail + [axis, transform, centered])
        for centered in [False, True]:
            xc, yc = number(literal('1.23456789012345')), number(literal('-9.87654321098765'))
            centers = [(-80, xc.raw()), (-90, yc.raw())] if centered else []
            expected = native(0x12afc, raws, variables, frequency, 0x10 if centered else 0, centers)
            third, fourth = Number(), Number()
            actual = lib.fx_stats_higher_moments(C.byref(third), C.byref(fourth), C.byref(table),
                                               C.byref(xc) if centered else None)
            check('higher_moments', [actual, third.raw().hex(), fourth.raw().hex()],
                  [expected, record(-150), record(-160)], detail + [centered])
            if variables == 2:
                expected = native(0x12a22, raws, variables, frequency, 0x10 if centered else 0, centers)
                actual = lib.fx_stats_square_cross(C.byref(out), C.byref(table),
                                                  C.byref(xc) if centered else None, C.byref(yc) if centered else None)
                check('square_cross', [actual, out.raw().hex()], [expected, record(-170)], detail + [centered])
                for transform in range(4):
                    for log_y in [0, 1]:
                        flags = ((0x20 if transform & 1 else 0) | (0x40 if transform & 2 else 0) |
                                 0x80 * log_y | (0x10 if centered else 0))
                        expected = native(0x12de6, raws, variables, frequency, flags, centers)
                        actual = lib.fx_stats_cross(C.byref(out), C.byref(table), transform, log_y,
                                                   C.byref(xc) if centered else None, C.byref(yc) if centered else None)
                        check('cross', [actual, out.raw().hex()], [expected, record(-140)],
                              detail + [centered, transform, log_y])
        check('source_immutable', bytes(cells), before, name)
        if variables == 2:
            for model in range(2, 9):
                expected = []
                for address in [0x1330a, 0x132ce, 0x13290] + ([0x13350] if model == 3 else []):
                    prepare(raws, variables, frequency); m.ram[0x80fa] = model
                    event.harness_init(C.create_string_buffer(rom), len(rom))
                    event_ram = event.harness_ram().contents
                    C.memmove(event_ram, m.ram, 65536)
                    event.harness_set_reg(0, 0); event.harness_set_reg(1, 0x86)
                    run = event.stats_oracle_call(address, 3000000, 0)
                    assert run == 100, (hex(address), run, detail)
                    expected.append((event.harness_get_reg(0), bytes(event_ram[0x8600:0x860a]).hex()))
                result = Fit()
                actual = lib.fx_stats_regression(C.byref(result), C.byref(table), model)
                check('regression', [actual, result.a.raw().hex(), result.b.raw().hex(), result.correlation.raw().hex()],
                      [expected[0][0], expected[0][1], expected[1][1], expected[2][1]], detail + [model, expected])
                if model == 3:
                    check('quadratic_coefficient_c', result.c.raw().hex(), expected[3][1], detail)
                if dataset_index % 13 == 0 or name.startswith('positive-'):
                    marked_input = bytearray(literal('2.34567890123456')); marked_input[0] |= 0x40
                    for input_raw in [literal('2.34567890123456'), bytes(marked_input), literal('0'),
                                      literal('-2'), errors[0], errors[1], errors[2]] + exact_values:
                        source = number(input_raw)
                        for inverse, second in [(0, 0), (1, 0)] + ([(1, 1)] if model == 3 else []):
                            address = 0x13266 if not inverse else (0x131fc if second else 0x131ea) if model == 3 else 0x13218
                            prepare(raws, variables, frequency); m.ram[0x80fa] = model
                            event.harness_init(C.create_string_buffer(rom), len(rom))
                            event_ram = event.harness_ram().contents
                            C.memmove(event_ram, m.ram, 65536)
                            event_ram[0x8600:0x860a] = input_raw
                            event.harness_set_reg(0, 0); event.harness_set_reg(1, 0x86)
                            run = event.stats_oracle_call(address, 3000000, 0)
                            assert run == 100, (hex(address), run, detail)
                            actual = lib.fx_stats_predict(C.byref(out), C.byref(result), model, C.byref(source), inverse, second)
                            expected_result = [event.harness_get_reg(0), bytes(event_ram[0x8600:0x860a]).hex()]
                            check('prediction', [actual, out.raw().hex()], expected_result,
                                  detail + [model, input_raw.hex(), inverse, second])
                            check('prediction_source_immutable', source.raw(), input_raw, name)
                check('regression_source_immutable', bytes(cells), before, name)

    # Host API validation is separate from native malformed-memory behavior.
    sentinel = number(bytes.fromhex('05987654321098769905'))
    for table in [Table(None, 1, 1, 0), Table(None, 0, 0, 0), Table(None, 0, 3, 0), Table(None, 0, 1, 2)]:
        out = number(sentinel.raw())
        check('host_table_guard', lib.fx_stats_count(C.byref(out), C.byref(table)), -1, bytes(table).hex())
        check('host_guard_output_immutable', out.raw(), sentinel.raw(), bytes(table).hex())
    empty = Table(None, 0, 1, 0)
    check('host_null_output_guard', lib.fx_stats_count(None, C.byref(empty)), -1, 'count')
    check('host_null_table_guard', lib.fx_stats_count(C.byref(sentinel), None), -1, 'count')

    report = {'status': 'pass', 'rom_sha256': hashlib.sha256(rom).hexdigest(),
              'random_seed': '0x13150', 'random_datasets': args.random_cases,
              'datasets': len(datasets), 'checks': checks, 'checks_total': sum(checks.values()),
              'scope': 'Prepared one/two variable statistics tables with optional frequency; accumulator transforms/centers, mean/deviation, all7 model A/B/C/correlation records and forward/inverse predictions including both quadratic roots and rational/surd inputs; original status and every output record, finite differential coverage.',
              'oracle_host_events': 'No-cancel response clears8e00 before native5564 without patching/skipping firmware instructions.',
              'excluded': 'CPU scratch/workspace RAM, table UI/mode lifecycle, interrupt polling and connecting cached moments to mode queries'}
    write_report('analysis/c-verification/stats.json', report,
                 sources + ['csrc/numeric/fx_numeric.h', 'csrc/numeric/fx_transcend.h',
                            'csrc/numeric/fx_transcend_internal.h', 'csrc/stats/fx_stats.h',
                            'csrc/stats/stats_manifest.json', 'tools/trace_natural_result.py',
                            'tools/c_verification.py', 'tools/nxu8/stats_host_events.c'], 'tools/test_stats_c.py')
    print(json.dumps(report, indent=2))


if __name__ == '__main__': main()
