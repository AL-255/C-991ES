#!/usr/bin/env python3
"""Differential checks for the high-level real power dispatcher and decimal core."""
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
from test_numeric_transcend_c import Number, Rational, number, raw_decimal
from c_verification import write_report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--random-cases', type=int, default=5000)
    parser.add_argument('--explore', action='store_true', help='Save mismatches without publishing a verification report.')
    args = parser.parse_args()
    build = ROOT / 'analysis/build/numeric'
    build.mkdir(parents=True, exist_ok=True)
    sources = ['csrc/numeric/fx_numeric.c', 'csrc/numeric/fx_transcend.c', 'csrc/numeric/fx_power.c']
    library = build / 'fx-power.so'
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror', '-pedantic',
                    '-fPIC', '-shared', *(str(ROOT / p) for p in sources), '-o', str(library)], check=True)
    lib = C.CDLL(str(library)); ptr = C.POINTER(Number)
    for name in ['fx_number_power', 'fx_transcend_power_decimal']:
        getattr(lib, name).argtypes = [ptr, ptr, ptr]
    lib.fx_decimal_parse.argtypes = [ptr, C.c_char_p]
    lib.fx_rational_encode.argtypes = [ptr, C.POINTER(Rational)]
    lib.fx_surd_pack.argtypes = [ptr, ptr]
    rom = (ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    m = Machine(rom, build / 'power-oracle')
    rng = random.Random(0x1a834)
    checks, mismatches = {}, []

    def dec(literal):
        out = Number(); assert lib.fx_decimal_parse(C.byref(out), str(literal).encode()) == 0
        return out.raw()

    def rat(n, d, marker=0):
        out = Number(); assert lib.fx_rational_encode(C.byref(out), C.byref(Rational(n, d, marker))) == 0
        return out.raw()

    def surd():
        components = (Number * 6)()
        for i in range(6):
            value = (rng.randrange(-99, 100) if i % 3 == 0 else
                     rng.randrange(1, 1000) if i % 3 == 1 else rng.randrange(1, 100))
            components[i] = number(dec(value))
        out = Number(); assert lib.fx_surd_pack(C.byref(out), components) == 0
        return out.raw()

    def native(base, exponent, address):
        m.reset(); settings(m)
        for i, byte in enumerate(base): m.ram[0x8300 + i] = byte
        for i, byte in enumerate(exponent): m.ram[0x8320 + i] = byte
        m.er(0, 0x8300); m.er(2, 0x8320); m.er(12, 0x8300); m.reg(6, 0xc1); m.reg(10, 0)
        m.call(address)
        return bytes(m.ram[0x8300:0x830a])

    def check(group, actual, expected, base, exponent):
        checks[group] = checks.get(group, 0) + 1
        if actual != expected:
            mismatch = {'group': group, 'base': base.hex(), 'exponent': exponent.hex(),
                        'actual': actual.hex() if isinstance(actual, bytes) else actual,
                        'native': expected.hex() if isinstance(expected, bytes) else expected}
            if not args.explore: raise AssertionError(json.dumps(mismatch))
            mismatches.append(mismatch)

    def test_pair(group, base, exponent, address=0x15f00, alias=False):
        name = 'fx_number_power' if address == 0x15f00 else 'fx_transcend_power_decimal'
        expected = native(base, exponent, address)
        a, e, out = number(base), number(exponent), Number()
        status = getattr(lib, name)(C.byref(out), C.byref(a), C.byref(e))
        check(group + '_status', status, 0, base, exponent)
        check(group + '_record', out.raw(), expected, base, exponent)
        if alias:
            for target in ['base', 'exponent']:
                a, e = number(base), number(exponent)
                out = a if target == 'base' else e
                status = getattr(lib, name)(C.byref(out), C.byref(a), C.byref(e))
                check(group + '_' + target + '_alias_status', status, 0, base, exponent)
                check(group + '_' + target + '_alias_record', out.raw(), expected, base, exponent)

    bases = [dec(s) for s in ['0', '1', '-1', '2', '-2', '10', '-10', '.1', '-.1',
             '1e-99', '-1e-99', '1e99', '-1e99', '999999999999999', '1.00000000000001', '.999999999999999']]
    exponents = [dec(s) for s in ['0', '1', '-1', '2', '3', '4', '-4', '.5', '-.5', '.2', '-.2',
             '.333333333333333', '.666666666666666', '1e99', '-1e99', '1e-99', '-1e-99',
             '10000000000.0001', '10000000000.0010', '99999999999999.9']]
    for base in bases:
        for exponent in exponents:
            test_pair('decimal_boundary_core', base, exponent, 0x1c648)
            test_pair('decimal_boundary_dispatch', base, exponent, alias=True)
    rational_exponents = [rat(n, d) for n, d in [(1, 2), (1, 3), (2, 3), (3, 2), (-1, 3),
             (-2, 3), (-3, 2), (717, 3946), (-717, 3946), (5, 7), (12, 5), (12345, 37)]]
    for base in bases + [rat(n, d) for n, d in [(2, 3), (-2, 3), (17, 3), (-17, 3), (99999, 997)]]:
        for exponent in exponents + rational_exponents:
            test_pair('rational_boundary_dispatch', base, exponent, alias=True)
    surds = [surd() for _ in range(24)]
    for base in surds + [bytes.fromhex('f2000000000000000000')]:
        for exponent in exponents:
            test_pair('format_boundary_dispatch', base, exponent, alias=True)
    for exponent in surds + [bytes.fromhex('f2000000000000000000')]:
        for base in bases:
            test_pair('format_boundary_dispatch', base, exponent)
    for index in range(args.random_cases):
        base = raw_decimal(rng.randrange(10**14, 10**15), rng.randrange(-99, 100),
                           rng.choice([1, -1]), rng.choice([0, 0x40]))
        exponent = raw_decimal(rng.randrange(10**14, 10**15), rng.randrange(-99, 100),
                               rng.choice([1, -1]), rng.choice([0, 0x40]))
        if index % 3 == 0: exponent = dec(rng.randrange(-200, 201))
        if index % 5 == 0: exponent = dec(rng.choice(['.5', '-.5', '.2', '-.2', '.333333333333333', '.666666666666667']))
        test_pair('random_decimal_core', base, exponent, 0x1c648, alias=index % 11 == 0)
        test_pair('random_decimal_dispatch', base, exponent, alias=index % 11 == 0)
        rational_base = rat(rng.randrange(-10**5, 10**5), rng.randrange(1, 10**5), rng.choice([0, 0x40]))
        integral_exponent = dec(rng.randrange(-30, 31))
        test_pair('random_rational_integer', rational_base, integral_exponent, alias=index % 11 == 0)
        rational_exponent = rat(rng.randrange(-10**4, 10**4), rng.randrange(1, 10**4), rng.choice([0, 0x40]))
        test_pair('random_rational_exponent', base, rational_exponent, alias=index % 11 == 0)
        test_pair('random_two_rationals', rational_base, rational_exponent)
        if index % 4 == 0:
            test_pair('random_surd_dispatch', surd(), exponent)
    report = {'rom_sha256': hashlib.sha256(rom).hexdigest(), 'seed': '0x1a834',
              'random_cases_per_group': args.random_cases, 'checks': checks, 'checks_total': sum(checks.values()),
              'scope': 'Real power external records, exact rational dispatch, decimal factor core; finite differential coverage.'}
    if args.explore:
        report['mismatches'] = mismatches
        (build / 'power-exploratory.json').write_text(json.dumps(report, indent=2) + '\n')
        print('checks', report['checks_total'], 'mismatches', len(mismatches)); print(json.dumps(mismatches[:40], indent=2))
    else:
        write_report('analysis/c-verification/numeric_power.json', report,
                     sources + ['csrc/numeric/fx_numeric.h', 'csrc/numeric/fx_transcend.h',
                                'csrc/numeric/fx_transcend_internal.h', 'csrc/numeric/power_manifest.json',
                                'tools/test_numeric_transcend_c.py', 'tools/trace_natural_result.py',
                                'tools/c_verification.py'], 'tools/test_numeric_power_c.py')
        print(json.dumps(report, indent=2))


if __name__ == '__main__': main()
