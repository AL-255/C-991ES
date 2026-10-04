#!/usr/bin/env python3
"""Check decimal transcendental C kernels against original native routines."""
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


class Rational(C.Structure):
    _fields_ = [('numerator', C.c_int64), ('denominator', C.c_uint64), ('flags', C.c_uint8)]


def number(raw): return Number((C.c_uint8 * 10)(*raw))


def raw_decimal(mantissa, exponent, sign=1, flags=0):
    s = f'{mantissa:015d}'
    return bytes([int(s[0]) | flags, *(int(s[i:i+2], 16) for i in range(1, 15, 2)),
                  int(f'{exponent % 100:02}', 16), (exponent >= 0) + 5 * (sign < 0)])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--random-cases', type=int, default=5000)
    args = parser.parse_args()
    build = ROOT / 'analysis/build/numeric'
    build.mkdir(parents=True, exist_ok=True)
    library = build / 'fx-transcend.so'
    sources = ['csrc/numeric/fx_numeric.c', 'csrc/numeric/fx_transcend.c']
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror', '-pedantic',
                    '-fPIC', '-shared', *(str(ROOT / p) for p in sources), '-o', str(library)], check=True)
    lib = C.CDLL(str(library))
    ptr = C.POINTER(Number)
    for name in ('fx_number_ln', 'fx_number_log10', 'fx_number_exp', 'fx_number_exp10', 'fx_number_negate'):
        getattr(lib, name).argtypes = [ptr, ptr]
    lib.fx_decimal_parse.argtypes = [ptr, C.c_char_p]
    lib.fx_rational_encode.argtypes = [ptr, C.POINTER(Rational)]
    lib.fx_surd_pack.argtypes = [ptr, ptr]
    rom = (ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    m = Machine(rom, build / 'transcend-oracle')
    rng = random.Random(0x1acb6)
    checks = {}

    def check(group, actual, expected, context):
        if actual != expected:
            raise AssertionError(f'{group}: {context}: {actual!r} != {expected!r}')
        checks[group] = checks.get(group, 0) + 1

    # Malformed external records are rejected before entering unsigned factor
    # arithmetic; no native behavior is claimed outside normalized records.
    for raw in [bytes.fromhex('00000000000000010001'),
                bytes.fromhex('00999999999999990001')]:
        source, out = number(raw), Number()
        for name in ['ln', 'log10', 'exp', 'exp10']:
            check(name + '_noncanonical_guard',
                  getattr(lib, 'fx_number_' + name)(C.byref(out), C.byref(source)), -1, raw.hex())

    inputs = [bytes(10), bytes.fromhex('f2000000000000000000'),
              bytes.fromhex('2717a394600000000806'), bytes.fromhex('2717a394600000000801')]
    for literal in ['1', '-1', '1e-99', '1e99', '1.00000000000001', '.999999999999999',
                    '2', '10', '.1', '3.14159265358979', '2.71828182845904',
                    '.5', '-.5', '.00000000000001', '-.00000000000001',
                    '99', '-99', '99.9999999999999', '-99.9999999999999',
                    '100', '-100', '101', '-101', '230', '-230', '1000', '-1000', '-1e99']:
        out = Number(); lib.fx_decimal_parse(C.byref(out), literal.encode()); inputs.append(out.raw())
    for exponent in range(-99, 100):
        for mantissa in [10**14, 10**14+1, 10**14+2, 10**14+9, 10**14+100,
                         10**14+10**7, 10**14+10**12, 10**15-2, 10**15-1]:
            inputs.append(raw_decimal(mantissa, exponent))
    for _ in range(args.random_cases):
        inputs.append(raw_decimal(rng.randrange(10**14, 10**15), rng.randrange(-99, 100),
                                  rng.choice([1, 1, 1, -1]), rng.choice([0, 0x40])))
        rational = Rational(rng.randrange(-10**6, 10**6), rng.randrange(1, 10**5), rng.choice([0, 0x40]))
        out = Number(); lib.fx_rational_encode(C.byref(out), C.byref(rational)); inputs.append(out.raw())
        components = (Number * 6)()
        for j in range(6):
            value = (rng.randrange(-99, 100) if j % 3 == 0 else
                     rng.randrange(1, 1000) if j % 3 == 1 else rng.randrange(1, 100))
            lib.fx_decimal_parse(C.byref(components[j]), str(value).encode())
        out = Number(); lib.fx_surd_pack(C.byref(out), components); inputs.append(out.raw())

    for index, raw in enumerate(inputs):
        for name, address in [('ln', 0x1c242), ('log10', 0x1c256), ('exp', 0x1c22e), ('exp10', 0x1c21a)]:
            m.reset(); settings(m)
            for i, byte in enumerate(raw): m.ram[0x8300 + i] = byte
            m.er(0, 0x8300); m.call(address)
            expected = bytes(m.ram[0x8300:0x830a])
            source, out = number(raw), Number()
            status = getattr(lib, 'fx_number_' + name)(C.byref(out), C.byref(source))
            check(name + '_c_status', status, 0, raw.hex())
            check(name + '_record', out.raw(), expected, raw.hex())
            if index % 11 == 0:
                status = getattr(lib, 'fx_number_' + name)(C.byref(source), C.byref(source))
                check(name + '_inplace_status', status, 0, raw.hex())
                check(name + '_inplace_record', source.raw(), expected, raw.hex())

    report = {'rom_sha256': hashlib.sha256(rom).hexdigest(), 'seed': '0x1acb6',
              'random_cases_per_group': args.random_cases, 'inputs': len(inputs),
              'checks': checks, 'checks_total': sum(checks.values()),
              'scope': 'Real ln/log10/exp/exp10 external numeric records; finite differential coverage.'}
    write_report('analysis/c-verification/numeric_transcend.json', report,
                 sources + ['csrc/numeric/fx_numeric.h', 'csrc/numeric/fx_transcend.h',
                            'csrc/numeric/fx_transcend_internal.h',
                            'csrc/numeric/transcend_manifest.json', 'tools/trace_natural_result.py',
                            'tools/c_verification.py'], 'tools/test_numeric_transcend_c.py')
    print(json.dumps(report, indent=2))


if __name__ == '__main__': main()
