#!/usr/bin/env python3
"""Differential checks of high-level C numeric routines against extracted ROM.

The original ROM and CPU harness appear only in this test oracle. The C
implementation has no dependency on them. GPL-3.0-or-later.
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
    def raw(self): return bytes(self.bytes)


class Decimal(C.Structure):
    _fields_ = [('sign', C.c_int), ('exponent', C.c_int), ('mantissa', C.c_uint64), ('flags', C.c_uint8)]


class Rational(C.Structure):
    _fields_ = [('numerator', C.c_int64), ('denominator', C.c_uint64), ('flags', C.c_uint8)]


def number(raw):
    n = Number()
    for i, b in enumerate(raw): n.bytes[i] = b
    return n


def raw_decimal(mantissa, exponent, sign, flags=0):
    s = f'{mantissa:015d}'
    return bytes([int(s[0]) | flags, *(int(s[i:i+2], 16) for i in range(1, 15, 2)),
                  int(f'{exponent % 100:02d}', 16), (exponent >= 0) + (5 if sign < 0 else 0)])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--random-cases', type=int, default=2000)
    args = parser.parse_args()
    build = ROOT / 'analysis/build/numeric'
    build.mkdir(parents=True, exist_ok=True)
    source = ROOT / 'csrc/numeric/fx_numeric.c'
    library = build / 'fx-numeric.so'
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror', '-pedantic', '-fPIC', '-shared',
                    str(source), '-o', str(library)], check=True)
    lib = C.CDLL(str(library))
    ptr = C.POINTER(Number)
    lib.fx_decimal_decode.argtypes = [C.POINTER(Decimal), ptr]
    lib.fx_decimal_encode.argtypes = [ptr, C.POINTER(Decimal)]
    lib.fx_decimal_from_u8.argtypes = [ptr, C.c_uint8]
    lib.fx_decimal_parse.argtypes = [ptr, C.c_char_p]
    lib.fx_decimal_binary.argtypes = [ptr, ptr, ptr, C.c_int]
    lib.fx_decimal_sqrt.argtypes = [ptr, ptr]
    lib.fx_decimal_subtract_cancel.argtypes = [ptr, ptr, ptr]
    lib.fx_decimal_add_plain.argtypes = [ptr, ptr, ptr]
    lib.fx_number_to_decimal.argtypes = [ptr, ptr]
    lib.fx_number_sqrt.argtypes = [ptr, ptr, C.c_int]
    lib.fx_number_binary.argtypes = [ptr, ptr, ptr, C.c_int]
    lib.fx_number_negate.argtypes = [ptr, ptr]
    lib.fx_number_integer_power.argtypes = [ptr, ptr, C.c_int]
    lib.fx_number_divmod.argtypes = [ptr, ptr, ptr, ptr]
    lib.fx_decimal_integer_cleanup.argtypes = [ptr]
    lib.fx_number_fractional_status.argtypes = [ptr]
    lib.fx_number_recognize_rational.argtypes = [C.POINTER(Rational),ptr]
    lib.fx_number_exponent.argtypes = [ptr]
    lib.fx_number_has_special_marker.argtypes = [ptr]
    lib.fx_surd_unpack.argtypes = [ptr, ptr]
    lib.fx_surd_pack.argtypes = [ptr, ptr]
    lib.fx_rational_decode.argtypes = [C.POINTER(Rational), ptr]
    lib.fx_rational_encode.argtypes = [ptr, C.POINTER(Rational)]
    rom = (ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    m = Machine(rom, build / 'oracle')
    rng = random.Random(0x991e5)
    results = {}

    def reset(): m.reset(); settings(m)
    def put(address, data):
        for i, value in enumerate(data): m.ram[address + i] = value
    def check(name, actual, expected, detail=''):
        if actual != expected:
            raise AssertionError(f'{name}: {detail}: {actual!r} != {expected!r}')
        results[name] = results.get(name, 0) + 1

    for v in range(256):
        reset(); m.er(0, 0x8300); m.reg(2, v); m.call(0x1d08c)
        out = Number(); lib.fx_decimal_from_u8(C.byref(out), v)
        check('unsigned_byte_constructor_1d08c', out.raw(), bytes(m.ram[0x8300:0x830a]), str(v))

    literals = ['0', '-0', '1', '-1', '12', '-99', '998', '-0.5', '0.05',
                '123456789012345', '1234567890123456', '1.234567890123456',
                '0.000000000000001234567890123456']
    literals += [str(rng.randrange(1, 10**15)) for _ in range(100)]
    for text in literals:
        reset(); put(0x8200, text.encode() + b'\0'); m.word(0x8190, 0x8200)
        m.er(0, 0x8190); m.er(2, 0x8300); m.call(0x171f4)
        check('literal_oracle_status', m.reg(0), 0, text)
        out = Number(); check('literal_c_status', lib.fx_decimal_parse(C.byref(out), text.encode()), 0, text)
        check('decimal_literal_parser', out.raw(), bytes(m.ram[0x8300:0x830a]), text)

    for _ in range(args.random_cases):
        exponent = rng.randrange(-99, 100)
        flags = rng.choice([0, 0x40])
        raw = raw_decimal(rng.randrange(10**14, 10**15), exponent, rng.choice([-1, 1]), flags)
        n = number(raw); out = Number(); decoded = Decimal()
        check('decimal_decode_status', lib.fx_decimal_decode(C.byref(decoded), C.byref(n)), 0)
        check('decimal_encode_status', lib.fx_decimal_encode(C.byref(out), C.byref(decoded)), 0)
        check('decimal_lossless_codec', out.raw(), raw)
        reset(); put(0x8300, raw); m.er(0, 0x8300); m.call(0x1cfde)
        expected = m.er(0); expected = expected - 65536 if expected >= 32768 else expected
        check('exponent_1cfde', lib.fx_number_exponent(C.byref(n)), expected, raw.hex())
        m.er(0, 0x8300); m.call(0x1d1a2)
        check('special_marker_1d1a2', lib.fx_number_has_special_marker(C.byref(n)), m.reg(0), raw.hex())
        m.er(0, 0x8300); m.call(0x1cabe)
        check('fractional_status_1cabe', lib.fx_number_fractional_status(C.byref(n)), m.reg(0), raw.hex())
        m.er(0, 0x8300); m.call(0x1cef0)
        check('cleanup_c_status', lib.fx_decimal_integer_cleanup(C.byref(n)), 0)
        check('integer_cleanup_1cef0', n.raw(), bytes(m.ram[0x8300:0x830a]), raw.hex())

    for _ in range(args.random_cases):
        coeff = [rng.randrange(-99, 100), rng.randrange(-99, 100)]
        rad = [rng.randrange(1, 1000), rng.randrange(2, 1000)]
        den = [rng.randrange(1, 100), rng.randrange(1, 100)]
        if not coeff[0]: rad[0] = 0; den[0] = 1
        values = [coeff[0], rad[0], den[0], coeff[1], rad[1], den[1]]
        components = (Number * 6)()
        for i, value in enumerate(values):
            check('surd_component_literal', lib.fx_decimal_parse(C.byref(components[i]), str(value).encode()), 0)
        reset(); put(0x8640, bytes(components)); m.er(0, 0); m.er(2, 0x8300); m.call(0x17616)
        out = Number(); check('surd_pack_c_status', lib.fx_surd_pack(C.byref(out), components), 0)
        check('surd_pack_17616', out.raw(), bytes(m.ram[0x8300:0x830a]), str(values))
        if out.raw()[0] >> 4 != 8: continue
        m.er(0, 0x8300); m.er(2, 0); m.call(0x178ba)
        expanded = (Number * 6)()
        check('surd_unpack_c_status', lib.fx_surd_unpack(expanded, C.byref(out)), 0)
        check('surd_unpack_178ba', bytes(expanded), bytes(m.ram[0x8640:0x867c]), out.raw().hex())
        m.er(0, 0); m.er(2, 0x8320); m.call(0x17576)
        decimal_result = Number()
        check('surd_to_decimal_c_status', lib.fx_number_to_decimal(C.byref(decimal_result), C.byref(out)), 0)
        check('surd_to_decimal_17576', decimal_result.raw(), bytes(m.ram[0x8320:0x832a]), out.raw().hex())

    wide_surd_components = [[100,2,1,1,3,1], [1,1000,1,0,0,1], [1,2,100,1,3,1],
                            [0,0,1,1000,1,1000], [0,0,1,1000,2,1000],
                            [-12345,998,456,78,997,91011]]
    wide_surd_components += [[rng.choice([-1,1])*rng.randrange(0,10000000),rng.randrange(1,10000000),rng.randrange(1,10000000),
                             rng.choice([-1,1])*rng.randrange(0,10000000),rng.randrange(1,10000000),rng.randrange(1,10000000)]
                            for _ in range(args.random_cases)]
    for values in wide_surd_components:
        components=(Number*6)()
        for i,v in enumerate(values): lib.fx_decimal_parse(C.byref(components[i]),str(v).encode())
        reset();put(0x8640,bytes(components));m.er(0,0);m.er(2,0x8300);m.call(0x17616)
        out=Number();check('wide_surd_pack_c_status',lib.fx_surd_pack(C.byref(out),components),0)
        check('wide_surd_pack_17616',out.raw(),bytes(m.ram[0x8300:0x830a]),str(values))

    for _ in range(args.random_cases):
        numerator, denominator = rng.randrange(0, 256), rng.randrange(1, 256)
        sign = rng.choice([-1, 1]); rational = Rational(sign * numerator, denominator, 0)
        a, b, out = Number(), Number(), Number()
        lib.fx_decimal_from_u8(C.byref(a), numerator); lib.fx_decimal_from_u8(C.byref(b), denominator)
        if numerator and sign < 0: a.bytes[9] += 5
        reset(); put(0x8300, a.raw()); put(0x8320, b.raw())
        m.er(0, 0x8300); m.er(2, 0x8320); m.er(12, 0x8300); m.reg(6, 193); m.reg(10, 0); m.call(0x16058)
        check('rational_encode_c_status', lib.fx_rational_encode(C.byref(out), C.byref(rational)), 0)
        check('rational_encode_16058', out.raw(), bytes(m.ram[0x8300:0x830a]), str((sign*numerator, denominator)))
        if out.bytes[0] >> 4 == 2:
            decoded = Rational(); check('rational_decode_status', lib.fx_rational_decode(C.byref(decoded), C.byref(out)), 0)
            reencoded = Number(); lib.fx_rational_encode(C.byref(reencoded), C.byref(decoded))
            check('rational_lossless_codec', reencoded.raw(), out.raw())
            m.er(0, 0x8300); m.call(0x1c902)
            decimal_result = Number()
            check('rational_to_decimal_c_status', lib.fx_number_to_decimal(C.byref(decimal_result), C.byref(out)), 0)
            check('rational_to_decimal_1c902', decimal_result.raw(), bytes(m.ram[0x8300:0x830a]), out.raw().hex())

    # 19f1a includes low-mantissa cleanup; this conversion crosses its upper
    # residue boundary before inverse-trigonometric arithmetic consumes it.
    for raw in [bytes.fromhex('2717a394600000000806'),
                bytes.fromhex('2717a394600000000801')]:
        out = number(raw); decimal_result = Number()
        reset(); put(0x8300, raw); m.er(0, 0x8300); m.call(0x1c902)
        check('rational_cleanup_conversion_c_status', lib.fx_number_to_decimal(C.byref(decimal_result), C.byref(out)), 0)
        check('rational_cleanup_conversion_1c902', decimal_result.raw(), bytes(m.ram[0x8300:0x830a]), raw.hex())

    wide_rationals = [(357911,9261), (79439699582,8475810), (-50581,55116), (386859,9172553),
                      (10**14,3*10**14),(10**15,3*10**15),(10**18,3*10**18)]
    wide_rationals += [(rng.choice([-1,1])*rng.randrange(0,10**rng.randrange(1,13)),
                        rng.randrange(1,10**rng.randrange(1,9))) for _ in range(args.random_cases)]
    for numerator,denominator in wide_rationals:
        a,b,out=Number(),Number(),Number()
        lib.fx_decimal_parse(C.byref(a),str(numerator).encode());lib.fx_decimal_parse(C.byref(b),str(denominator).encode())
        reset();put(0x8300,a.raw());put(0x8320,b.raw());m.er(0,0x8300);m.er(2,0x8320);m.er(12,0x8300);m.reg(6,193);m.reg(10,0);m.call(0x16058)
        rational=Rational(numerator,denominator,0)
        check('wide_rational_encode_c_status',lib.fx_rational_encode(C.byref(out),C.byref(rational)),0)
        check('wide_rational_encode_16058',out.raw(),bytes(m.ram[0x8300:0x830a]),str((numerator,denominator)))

    recognized_decimal_inputs=[]
    for literal in ['0','.1','-.1','.333333333333333','5.05141490633743','10.0000000000001',
                    '-10.0000000000001','0.00000001','0.0000000100001','1e6','1e7','1e8','123456789']:
        a=Number();lib.fx_decimal_parse(C.byref(a),literal.encode());recognized_decimal_inputs.append(a.raw())
    recognized_decimal_inputs += [raw_decimal(rng.randrange(10**14,10**15),rng.randrange(-10,9),
                                              rng.choice([-1,1]),rng.choice([0,0,0x40]))
                                  for _ in range(args.random_cases)]
    for a_raw in recognized_decimal_inputs:
        a,out,r=number(a_raw),number(a_raw),Rational()
        if lib.fx_number_recognize_rational(C.byref(r),C.byref(a)):
            lib.fx_rational_encode(C.byref(out),C.byref(r))
        reset();put(0x8300,a_raw);m.er(0,0x8300);m.call(0x11110)
        check('rational_preprocess_11110',out.raw(),bytes(m.ram[0x8300:0x830a]),a_raw.hex())

    boundaries = [
        (raw_decimal(10**14, 99, 1), raw_decimal(10**14, 1, 1)),
        (raw_decimal(10**14, -99, 1), raw_decimal(10**14, -1, 1)),
        (raw_decimal(10**14, 0, 1), bytes(10)),
        (raw_decimal(10**15-1, 0, 1), raw_decimal(10**14, -15, 1)),
    ]
    arithmetic = [(raw_decimal(rng.randrange(10**14, 10**15), rng.randrange(-99, 100), rng.choice([-1, 1]), rng.choice([0, 0x40])),
                   raw_decimal(rng.randrange(10**14, 10**15), rng.randrange(-99, 100), rng.choice([-1, 1]), rng.choice([0, 0x40])))
                  for _ in range(args.random_cases)] + boundaries
    for op, address in enumerate([0x1bfa4, 0x1bfb8, 0x1bfcc, 0x1bfe0]):
        for a_raw, b_raw in arithmetic:
            a, b, out = number(a_raw), number(b_raw), Number()
            reset(); put(0x8300, a_raw); put(0x8320, b_raw); m.er(0, 0x8300); m.er(2, 0x8320); m.call(address)
            check(f'arithmetic_status_{address:x}', lib.fx_decimal_binary(C.byref(out), C.byref(a), C.byref(b), op), 0)
            check(f'decimal_arithmetic_{address:x}', out.raw(), bytes(m.ram[0x8300:0x830a]), f'{a_raw.hex()} {b_raw.hex()}')

    for a_raw, _ in arithmetic:
        a, out = number(a_raw), Number()
        reset(); m.ram[0x8106] = 0; put(0x8300, a_raw); m.er(0, 0x8300); m.call(0x1c780)
        check('sqrt_c_status', lib.fx_decimal_sqrt(C.byref(out), C.byref(a)), 0)
        check('decimal_sqrt_1c780_math_disabled', out.raw(), bytes(m.ram[0x8300:0x830a]), a_raw.hex())
    for _ in range(args.random_cases):
        a_raw=raw_decimal(rng.randrange(10**14,10**15),rng.randrange(-99,100),rng.choice([-1,1]))
        b_raw=raw_decimal(rng.randrange(10**14,10**15),rng.randrange(-99,100),rng.choice([1,1,1,-1]))
        a,b,rem,quot=number(a_raw),number(b_raw),Number(),Number()
        reset();put(0x8300,a_raw);put(0x8320,b_raw);m.er(0,0x8300);m.er(2,0x8320);m.call(0x1c3fa)
        check('divmod_c_status',lib.fx_number_divmod(C.byref(rem),C.byref(quot),C.byref(a),C.byref(b)),0)
        check('divmod_remainder_1c3fa',rem.raw(),bytes(m.ram[0x8300:0x830a]),f'{a_raw.hex()} {b_raw.hex()}')
        check('divmod_quotient_1c3fa',quot.raw(),bytes(m.ram[0x8320:0x832a]),f'{a_raw.hex()} {b_raw.hex()}')

    exact_roots = list(range(101)) + [rng.randrange(0, 10000000) for _ in range(args.random_cases)]
    for value in exact_roots:
        a, out = Number(), Number(); lib.fx_decimal_parse(C.byref(a), str(value).encode())
        reset(); put(0x8300, a.raw()); m.er(0, 0x8300); m.call(0x1c780)
        check('exact_sqrt_c_status', lib.fx_number_sqrt(C.byref(out), C.byref(a), 1), 0)
        check('exact_sqrt_1c780', out.raw(), bytes(m.ram[0x8300:0x830a]), str(value))
    for _ in range(args.random_cases):
        a, out = Number(), Number()
        r = Rational(rng.randrange(-1000, 1001), rng.randrange(1, 1001), 0)
        lib.fx_rational_encode(C.byref(a), C.byref(r))
        reset(); put(0x8300, a.raw()); m.er(0, 0x8300); m.call(0x1c780)
        check('rational_sqrt_c_status', lib.fx_number_sqrt(C.byref(out), C.byref(a), 1), 0)
        check('rational_sqrt_1c780', out.raw(), bytes(m.ram[0x8300:0x830a]), str((r.numerator,r.denominator)))

    decimal_roots = []
    for text in ['.5', '.1', '.25', '.75', '.333333333333333', '.999999999999999',
                 '1.00000000000001', '1e-9', '1e-8', '1e6', '1e7', '-.5', '0']:
        a = Number(); lib.fx_decimal_parse(C.byref(a), text.encode()); decimal_roots.append(a.raw())
    for _ in range(args.random_cases):
        numerator, denominator, a = Number(), Number(), Number()
        lib.fx_decimal_parse(C.byref(numerator), str(rng.randrange(1, 100000)).encode())
        lib.fx_decimal_parse(C.byref(denominator), str(rng.randrange(1, 10000)).encode())
        lib.fx_decimal_binary(C.byref(a), C.byref(numerator), C.byref(denominator), 3)
        if rng.randrange(5) == 0: a.bytes[0] |= 0x40
        decimal_roots.append(a.raw())
    for raw in decimal_roots:
        a, out = number(raw), Number()
        reset(); put(0x8300, raw); m.er(0, 0x8300); m.call(0x1c780)
        check('decimal_fraction_sqrt_c_status', lib.fx_number_sqrt(C.byref(out), C.byref(a), 1), 0)
        check('decimal_fraction_sqrt_1c780', out.raw(), bytes(m.ram[0x8300:0x830a]), raw.hex())

    exact_inputs = []
    for _ in range(args.random_cases):
        if rng.randrange(2):
            a = Number(); r = Rational(rng.randrange(-99, 100), rng.randrange(1, 100), 0)
            lib.fx_rational_encode(C.byref(a), C.byref(r))
        else:
            a = Number(); source_number = Number()
            lib.fx_decimal_parse(C.byref(source_number), str(rng.randrange(1, 1000)).encode())
            lib.fx_number_sqrt(C.byref(a), C.byref(source_number), 1)
        if rng.randrange(3):
            b = Number(); r = Rational(rng.randrange(-99, 100), rng.randrange(1, 100), 0)
            lib.fx_rational_encode(C.byref(b), C.byref(r))
        else:
            b = Number(); source_number = Number()
            lib.fx_decimal_parse(C.byref(source_number), str(rng.randrange(1, 1000)).encode())
            lib.fx_number_sqrt(C.byref(b), C.byref(source_number), 1)
        exact_inputs.append((a.raw(), b.raw()))
    for op, address in enumerate([0x15f34, 0x15f40, 0x15f4c, 0x15f58]):
        for a_raw, b_raw in exact_inputs:
            a, b, out = number(a_raw), number(b_raw), Number()
            reset(); put(0x8300, a_raw); put(0x8320, b_raw)
            m.er(0, 0x8300); m.er(2, 0x8320); m.er(12, 0x8300); m.reg(6, 193); m.reg(10, 0); m.call(address)
            check(f'exact_arithmetic_status_{address:x}', lib.fx_number_binary(C.byref(out), C.byref(a), C.byref(b), op), 0)
            check(f'exact_arithmetic_{address:x}', out.raw(), bytes(m.ram[0x8300:0x830a]), f'{a_raw.hex()} {b_raw.hex()}')
    surd_radicands = [1, 2, 3, 5, 6, 7, 10, 11, 13, 14, 15, 17, 19, 21, 22, 23]
    two_term_inputs = []
    for _ in range(args.random_cases):
        pair = []
        for _ in range(2):
            components = (Number*6)(); radicands = sorted(rng.sample(surd_radicands, 2))
            vals = [rng.choice([-1, 1])*rng.randrange(1, 10), radicands[0], rng.randrange(1, 10),
                    rng.choice([-1, 1])*rng.randrange(1, 10), radicands[1], rng.randrange(1, 10)]
            for i,v in enumerate(vals): lib.fx_decimal_parse(C.byref(components[i]), str(v).encode())
            out = Number(); lib.fx_surd_pack(C.byref(out), components); pair.append(out.raw())
        two_term_inputs.append(pair)
    # Compact records allow much larger radicals and coefficient fractions.
    # These inputs exercise partial exact-result fallbacks and the special
    # conjugate-denominator path, including prime factors above 97.
    wide_radicands = [n for n in range(1, 1000)
                      if all(n % (d*d) for d in range(2, 32))]
    for _ in range(args.random_cases):
        pair = []
        for _ in range(2):
            components = (Number*6)(); radicands = sorted(rng.sample(wide_radicands, 2))
            vals = [rng.choice([-1, 1])*rng.randrange(1, 100), radicands[0], rng.randrange(1, 100),
                    rng.choice([-1, 1])*rng.randrange(1, 100), radicands[1], rng.randrange(1, 100)]
            for i,v in enumerate(vals): lib.fx_decimal_parse(C.byref(components[i]), str(v).encode())
            out = Number(); lib.fx_surd_pack(C.byref(out), components); pair.append(out.raw())
        two_term_inputs.append(pair)
    for op,address in enumerate([0x15f34,0x15f40,0x15f4c,0x15f58]):
        for a_raw,b_raw in two_term_inputs:
            a,b,out=number(a_raw),number(b_raw),Number()
            reset();put(0x8300,a_raw);put(0x8320,b_raw)
            m.er(0,0x8300);m.er(2,0x8320);m.er(12,0x8300);m.reg(6,193);m.reg(10,0);m.call(address)
            check(f'two_term_arithmetic_status_{address:x}',lib.fx_number_binary(C.byref(out),C.byref(a),C.byref(b),op),0)
            check(f'two_term_arithmetic_{address:x}',out.raw(),bytes(m.ram[0x8300:0x830a]),f'{a_raw.hex()} {b_raw.hex()}')
    for op,address in enumerate([0x15f34,0x15f40,0x15f4c,0x15f58]):
        for i,b_raw in enumerate(recognized_decimal_inputs):
            a_raw=two_term_inputs[i%len(two_term_inputs)][0]
            a,b,out=number(a_raw),number(b_raw),Number()
            reset();put(0x8300,a_raw);put(0x8320,b_raw)
            m.er(0,0x8300);m.er(2,0x8320);m.er(12,0x8300);m.reg(6,193);m.reg(10,0);m.call(address)
            check(f'mixed_surd_decimal_status_{address:x}',lib.fx_number_binary(C.byref(out),C.byref(a),C.byref(b),op),0)
            check(f'mixed_surd_decimal_{address:x}',out.raw(),bytes(m.ram[0x8300:0x830a]),f'{a_raw.hex()} {b_raw.hex()}')
    for a_raw in [a for a,b in arithmetic]+[a for a,b in exact_inputs]+[a for a,b in two_term_inputs]:
        a,out=number(a_raw),Number();reset();put(0x8300,a_raw);m.er(0,0x8300);m.call(0x1ce70)
        check('negate_c_status',lib.fx_number_negate(C.byref(out),C.byref(a)),0)
        check('negate_1ce70',out.raw(),bytes(m.ram[0x8300:0x830a]),a_raw.hex())

    power_inputs = [a for a,b in arithmetic]+[a for a,b in exact_inputs]+[a for a,b in two_term_inputs]
    for literal in ['0','1','-1','1e-99','-1e-99','1e99','-1e99']:
        boundary=Number();lib.fx_decimal_parse(C.byref(boundary),literal.encode());power_inputs.append(boundary.raw())
    for exponent in [-1, 0, 2, 3]:
        exponent_record = Number(); lib.fx_decimal_parse(C.byref(exponent_record), str(exponent).encode())
        for a_raw in power_inputs:
            a,out=number(a_raw),Number();reset();put(0x8300,a_raw);put(0x8320,exponent_record.raw())
            m.er(0,0x8300);m.er(2,0x8320);m.er(12,0x8300);m.reg(6,193);m.reg(10,0);m.call(0x15f00)
            check('integer_power_fast_c_status',lib.fx_number_integer_power(C.byref(out),C.byref(a),exponent),0)
            check('integer_power_fast_15f00',out.raw(),bytes(m.ram[0x8300:0x830a]),f'{a_raw.hex()} exponent={exponent}')

    # The statistics/regression subtraction entry uses its own relative
    # cancellation policy. Check both sides of its leading-zero threshold.
    extra_rng = random.Random(0x1bf9017f46)
    cancellation_pairs = []
    for exponent in [-99,-98,-10,-1,0,1,6,7,98,99]:
        for mantissa in [10**14,896173312709749,10**15-1]:
            for delta in [-101,-100,-99,-98,-11,-10,-9,-2,-1,0,1,2,9,10,11,98,99,100,101]:
                if not 10**14 <= mantissa+delta < 10**15: continue
                for flags in [0,0x40]:
                    cancellation_pairs.append((raw_decimal(mantissa,exponent,1,flags),
                                               raw_decimal(mantissa+delta,exponent,1,flags)))
    for _ in range(args.random_cases):
        mantissa = extra_rng.randrange(10**14+1001,10**15-1001)
        exponent, sign, flags = extra_rng.randrange(-99,100), extra_rng.choice([-1,1]), extra_rng.choice([0,0x40])
        delta = extra_rng.randrange(-1000,1001)
        cancellation_pairs.append((raw_decimal(mantissa,exponent,sign,flags),
                                   raw_decimal(mantissa+delta,exponent,sign,flags)))
    for a_raw,b_raw in arithmetic+cancellation_pairs:
        a,b,out = number(a_raw),number(b_raw),Number()
        reset(); put(0x8300,a_raw); put(0x8320,b_raw); m.er(0,0x8300); m.er(2,0x8320); m.call(0x1bf90)
        check('cancellation_subtract_status',lib.fx_decimal_subtract_cancel(C.byref(out),C.byref(a),C.byref(b)),0)
        check('cancellation_subtract_1bf90',out.raw(),bytes(m.ram[0x8300:0x830a]),f'{a_raw.hex()} {b_raw.hex()}')
        reset();put(0x8300,a_raw);put(0x8320,b_raw);m.er(0,0x8300);m.er(2,0x8320);m.call(0x1c690)
        check('evaluator_cancellation_subtract_status',lib.fx_number_binary(C.byref(out),C.byref(a),C.byref(b),1),0)
        check('evaluator_cancellation_subtract_1c690',out.raw(),bytes(m.ram[0x8300:0x830a]),f'{a_raw.hex()} {b_raw.hex()}')
        negative_b=Number();lib.fx_number_negate(C.byref(negative_b),C.byref(b))
        reset();put(0x8300,a_raw);put(0x8320,negative_b.raw());m.er(0,0x8300);m.er(2,0x8320);m.call(0x1bfa4)
        check('cancellation_add_status',lib.fx_decimal_binary(C.byref(out),C.byref(a),C.byref(negative_b),0),0)
        check('cancellation_add_1bfa4',out.raw(),bytes(m.ram[0x8300:0x830a]),f'{a_raw.hex()} {negative_b.raw().hex()}')
        reset();put(0x8300,a_raw);put(0x8320,negative_b.raw());m.er(0,0x8300);m.er(2,0x8320);m.call(0x1bff4)
        check('plain_add_status',lib.fx_decimal_add_plain(C.byref(out),C.byref(a),C.byref(negative_b)),0)
        check('plain_add_1bff4',out.raw(),bytes(m.ram[0x8300:0x830a]),f'{a_raw.hex()} {negative_b.raw().hex()}')



    # Expand beyond normalized exact-result records: the compact format itself
    # allows square factors, equal radicands, and an inactive second coefficient.
    # The firmware retains those slots during radical sorting and may therefore
    # choose a different decimal fallback from simplified symbolic arithmetic.
    scalar_records = []
    for text in ['0','1','-1','2','-2','100','.5','-.25','1e7','1e8']:
        n=Number(); lib.fx_decimal_parse(C.byref(n),text.encode()); scalar_records.append(n.raw())
    def raw_surd(small=False):
        raw=[]
        for i in range(2):
            rad = extra_rng.choice([1,2,3,4,5,8,9,12]) if small else extra_rng.randrange(1,1000)
            coefficient = extra_rng.randrange(1 if i==0 else 0,4 if small else 100)
            denominator = extra_rng.randrange(1,4 if small else 100)
            raw.extend([rad//100,int(f'{rad%100:02d}',16),int(f'{coefficient:02d}',16),int(f'{denominator:02d}',16)])
        raw[0] |= 0x80; raw.extend([extra_rng.choice([1,6]),extra_rng.choice([1,6])]); return bytes(raw)
    raw_pairs = [(bytes.fromhex(a),bytes.fromhex(b)) for a,b in [
        ('01000000000000000001','81621149065786170606'),
        ('86772352028700540006','83288816017995820101'),
        ('86292565038615340606','86772352028700540006'),
        ('86772352028700540006','85617667001734510106'),
        ('83638443036373810606','01000000000000000201'),
        ('80416333004165600101','01000000000000000201')]]
    for small in [False,True]:
        for index in range(args.random_cases):
            a_raw=raw_surd(small); b_raw=raw_surd(small) if index%3==0 else extra_rng.choice(scalar_records)
            if index%2: a_raw,b_raw=b_raw,a_raw
            raw_pairs.append((a_raw,b_raw))
    for op,address in enumerate([0x1c6a4,0x1c690,0x1c6cc,0x1c6b8]):
        for index,(a_raw,b_raw) in enumerate(raw_pairs):
            a,b,out=number(a_raw),number(b_raw),Number()
            reset();put(0x8300,a_raw);put(0x8320,b_raw);m.er(0,0x8300);m.er(2,0x8320);m.call(address)
            expected=bytes(m.ram[0x8300:0x830a]);detail=f'{a_raw.hex()} {b_raw.hex()}'
            check(f'raw_surd_binary_status_{address:x}',lib.fx_number_binary(C.byref(out),C.byref(a),C.byref(b),op),0)
            check(f'raw_surd_binary_{address:x}',out.raw(),expected,detail)
            if index%11==0:
                check(f'raw_surd_binary_alias_status_{address:x}',lib.fx_number_binary(C.byref(a),C.byref(a),C.byref(b),op),0)
                check(f'raw_surd_binary_alias_{address:x}',a.raw(),expected,detail)
                check(f'raw_surd_binary_right_input_{address:x}',b.raw(),b_raw,detail)

    for exponent in [2,3]:
        exponent_record=Number();lib.fx_decimal_parse(C.byref(exponent_record),str(exponent).encode())
        for a_raw,_ in raw_pairs:
            if a_raw[0]&0xf0 != 0x80: continue
            a,out=number(a_raw),Number();reset();put(0x8300,a_raw);put(0x8320,exponent_record.raw())
            m.er(0,0x8300);m.er(2,0x8320);m.er(12,0x8300);m.reg(6,193);m.reg(10,0);m.call(0x15f00)
            check('raw_surd_power_status',lib.fx_number_integer_power(C.byref(out),C.byref(a),exponent),0)
            check('raw_surd_power_15f00',out.raw(),bytes(m.ram[0x8300:0x830a]),f'{a_raw.hex()} exponent={exponent}')

    metadata_inputs = [bytes(10),bytes([0x40])+bytes(9)]
    for exponent in [-99,-1,0,6,7,99]:
        for sign in [-1,1]:
            for flags in [0,0x40]: metadata_inputs.append(raw_decimal(10**14,exponent,sign,flags))
    for numerator,denominator in [(1,3),(1,7),(2,3),(-1,3),(717,3946),(-717,3946)]:
        for flags in [0,0x40]:
            value=Number();rational=Rational(numerator,denominator,flags)
            lib.fx_rational_encode(C.byref(value),C.byref(rational));metadata_inputs.append(value.raw())
    metadata_inputs += [bytes.fromhex(raw) for raw in [
        '80000001000201010100','80030201001201010106',
        '81621149065786170606','83638443036373810606','86772352028700540006']]
    metadata_pairs = [(a,b) for a in metadata_inputs for b in metadata_inputs]
    for index in range(args.random_cases):
        records=[]
        for _ in range(2):
            if extra_rng.randrange(2):
                value=Number();fraction=Rational(extra_rng.randrange(-100000,100000),extra_rng.randrange(1,100000),0)
                lib.fx_rational_encode(C.byref(value),C.byref(fraction));value.bytes[0] |= extra_rng.choice([0,0x40])
                records.append(value.raw())
            else: records.append(raw_decimal(extra_rng.randrange(10**14,10**15),extra_rng.randrange(-99,100),
                                             extra_rng.choice([-1,1]),extra_rng.choice([0,0x40])))
        if index%3==0: records[index%2] = extra_rng.choice(metadata_inputs[-5:])
        metadata_pairs.append(records)
    # Native scalar rational arithmetic truncates cross-products before GCD.
    # These ordinary inputs exercise products above both 15 digits and int64,
    # and decimals beyond the native exponent14 integral-operand limit.
    for numerator,denominator in [(-4851,6821),(1,99999999),(-1,99999999),(-717,3946)]:
        value=Number();fraction=Rational(numerator,denominator,0)
        lib.fx_rational_encode(C.byref(value),C.byref(fraction))
        for text in ['201075790269646','999999999999999','100000000000001',
                     '123456789012345','1000000000000000','9000000000000000000']:
            integer=Number();lib.fx_decimal_parse(C.byref(integer),text.encode())
            for left_flags,right_flags in [(0,0),(0x40,0),(0,0x40),(0x40,0x40)]:
                left=bytearray(value.raw());left[0]|=left_flags
                right=bytearray(integer.raw());right[0]|=right_flags
                metadata_pairs.extend([(bytes(left),bytes(right)),(bytes(right),bytes(left))])
    for op,address in enumerate([0x1c6a4,0x1c690,0x1c6cc,0x1c6b8]):
        for index,(a_raw,b_raw) in enumerate(metadata_pairs):
            a,b,out=number(a_raw),number(b_raw),Number()
            reset();put(0x8300,a_raw);put(0x8320,b_raw);m.er(0,0x8300);m.er(2,0x8320);m.call(address)
            expected=bytes(m.ram[0x8300:0x830a]);detail=f'{a_raw.hex()} {b_raw.hex()}'
            check(f'metadata_binary_status_{address:x}',lib.fx_number_binary(C.byref(out),C.byref(a),C.byref(b),op),0)
            check(f'metadata_binary_{address:x}',out.raw(),expected,detail)
            if index%11==0:
                check(f'metadata_binary_alias_status_{address:x}',lib.fx_number_binary(C.byref(b),C.byref(a),C.byref(b),op),0)
                check(f'metadata_binary_alias_{address:x}',b.raw(),expected,detail)
                check(f'metadata_binary_left_input_{address:x}',a.raw(),a_raw,detail)

    manifest = {'rom_sha256': hashlib.sha256(rom).hexdigest(), 'seed': '0x991e5',
                'random_cases_per_group': args.random_cases, 'checks': results,
                'checks_total': sum(results.values()),
                'scope': 'Finite routine-level differential tests; no claim of complete numeric firmware coverage.'}
    (build / 'results.json').write_text(json.dumps(manifest, indent=2) + '\n')
    write_report('analysis/c-verification/numeric.json', manifest,
                 ['csrc/numeric/fx_numeric.c', 'csrc/numeric/fx_numeric.h',
                  'csrc/numeric/manifest.json', 'tools/trace_natural_result.py',
                  'tools/c_verification.py'], 'tools/test_numeric_c.py')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__': main()
