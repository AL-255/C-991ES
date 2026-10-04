#!/usr/bin/env python3
"""Differential tests of readable C result formatting against the original ROM.

The oracle executes C060 in SimU8; the C implementation executes no firmware.
These routine-boundary tests do not claim keyscan or whole-device equivalence.
GPL-3.0-or-later.
"""
import ctypes as C
import decimal
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


class Options(C.Structure):
    _fields_ = [(n, C.c_uint8) for n in (
        'selection', 'math_output', 'mixed_fraction', 'display_mode', 'digits',
        'decimal_dot', 'format_context', 'recurring_style')]


class Result(C.Structure):
    _fields_ = [('length', C.c_size_t), ('kind', C.c_uint8), ('recognized', C.c_uint8)]


class Rational(C.Structure):
    _fields_ = [('numerator', C.c_int64), ('denominator', C.c_uint64), ('flags', C.c_uint8)]


def build():
    dest = ROOT / 'analysis/build/format'
    dest.mkdir(parents=True, exist_ok=True)
    output = dest / 'format.so'
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-fPIC', '-shared', str(ROOT / 'csrc/format/fx_format.c'),
                    str(ROOT / 'csrc/numeric/fx_numeric.c'), '-o', str(output)], check=True)
    lib = C.CDLL(str(output))
    for name in ('fx_format_number', 'fx_format_decimal'):
        f = getattr(lib, name)
        f.argtypes = [C.POINTER(Number), C.POINTER(Options), C.POINTER(C.c_uint8),
                      C.c_size_t, C.POINTER(Result)]
        f.restype = C.c_int
    lib.fx_decimal_parse.argtypes = [C.POINTER(Number), C.c_char_p]
    lib.fx_rational_encode.argtypes = [C.POINTER(Number), C.c_void_p]
    lib.fx_decimal_from_integer.argtypes = [C.POINTER(Number), C.c_int64]
    lib.fx_surd_pack.argtypes = [C.POINTER(Number), C.POINTER(Number)]
    return lib


def oracle(machine, record, options):
    machine.reset(); settings(machine)
    machine.ram[0x8100] = options.selection
    machine.ram[0x8106] = options.math_output
    machine.ram[0x8107] = options.mixed_fraction
    machine.ram[0x8102] = options.display_mode
    machine.ram[0x8103] = options.digits
    machine.ram[0x8104] = options.decimal_dot
    for i, b in enumerate(record): machine.ram[0x8300 + i] = b
    machine.er(0, 0x8300); machine.er(2, 0x8500)
    machine.word(0x8dee, options.format_context)
    machine.call(0xc060)
    return machine.reg(0), bytes(machine.ram[0x8500:0x8800]).split(b'\0', 1)[0]


def decimal_record(mantissa, exponent, sign=1):
    if not mantissa: return bytes(10)
    s = f'{mantissa:015d}'
    e = exponent % 100
    return bytes([int(s[0]), *[int(s[i:i + 2], 16) for i in range(1, 15, 2)],
                  (e // 10) * 16 + e % 10,
                  (1 if exponent >= 0 else 0) + (5 if sign < 0 else 0)])


def main():
    lib = build()
    rom = (ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    machine = Machine(rom, ROOT / 'analysis/build/format/oracle')
    cases = []
    default = Options(13, 1, 0, 0, 0, 0, 0, 0)
    for row in json.loads((ROOT / 'analysis/verification/numeric-samples.json').read_text()):
        o = Options(12 if row['name'] == 'mixed-numeric-fraction' else 13, 1, 0, 0, 0, 0, 0, 0)
        cases.append((row['name'], bytes.fromhex(row['numeric_record']), o))
    for r in ['89970199099801990106', '80020101000301010606',
              '80020103000301020101', '80020101000102010101',
              '80011322012201010601', '80020101000201010106',
              '80020101000201010601']:
        cases.append(('surd-' + r, bytes.fromhex(r), default))
        for selection in [0, 10, 11, 12, 13, 14]:
            for math in [0, 1]:
                for mode in [0, 4, 8, 9]:
                    cases.append((f'surd-fallback-{r}-{selection}-{math}-{mode}', bytes.fromhex(r),
                                  Options(selection, math, 0, mode, 3, 0, 0, 0)))
    for r in ['80000001000201030600', '80020103000301030606',
              '80020101000301010606', '80020101000301010106']:
        for context in range(7):
            cases.append((f'surd-context-{context}-{r}', bytes.fromhex(r),
                          Options(13, 1, 0, 0, 0, 0, context, 0)))
    # These valid compact records were packed identically by native17616.
    # Native exact output retains the first displayed zero coefficient,
    # skips GCD reduction around zero slots, and keeps sqrt1 on the second
    # term. Converted whole values bypass exact serialization altogether.
    surd_serialization_records = [
        '80040101000901010101', '80010101000101010101',
        '80010102000101030101', '80020101000200010001',
        '80020102000200030001', '80020101000300010001',
        '80000001000301010100']
    for record in surd_serialization_records:
        for context in range(7):
            for math in [0,1]:
                cases.append((f'surd-serialization-{record}-{context}-{math}',bytes.fromhex(record),
                              Options(13,math,0,0,0,1,context,0)))
    # These mathematically whole sums convert to a stored value immediately
    # below the integer. Native fractional-part classification keeps their
    # exact surd output; recognizing a nearby integer would change behavior.
    for record in ['80040103000901090101','80010103000102030101',
                   '80040207000901070101','80040111000903110101',
                   '80040117000905170101','80040119000117190101',
                   '80040103000901090606']:
        for context in [0,4]:
            cases.append((f'surd-near-whole-storage-{record}-{context}',bytes.fromhex(record),
                          Options(13,1,0,0,0,1,context,0)))
    for a in [-2,-1,0,1,2]:
        for b in [-2,-1,0,1,2]:
            if not a and not b: continue
            for radicand_a,radicand_b in [(1,1),(1,2),(2,1),(2,2),(2,3),(4,9)]:
                for denominator_a,denominator_b in [(1,1),(2,2),(2,3),(3,6)]:
                    values = [a,radicand_a,denominator_a,b,radicand_b,denominator_b]
                    parts = (Number * 6)(); number = Number()
                    for position,value in enumerate(values):
                        assert lib.fx_decimal_from_integer(C.byref(parts[position]),value) == 0
                    assert lib.fx_surd_pack(C.byref(number),parts) == 0
                    for context in [0,4]:
                        cases.append((f'surd-slots-{values}-{context}',bytes(number.bytes),
                                      Options(13,1,0,0,0,1,context,0)))
    for record in surd_serialization_records[:2]:
        for previous in range(16):
            for context in [0,4]:
                for mode in [0,4,8,9]:
                    cases.append((f'surd-whole-history-{record}-{previous}-{context}-{mode}',bytes.fromhex(record),
                                  Options(previous*16+13,1,0,mode,3,1,context,0)))
    for math in [0, 1]:
        for mixed in [0, 1]:
            for selection in [0, 11, 12, 13]:
                for record in ['21a30000000000000301', '22a1a300000000000501',
                               '22a1a300000000000506']:
                    cases.append((f'rational-{math}-{mixed}-{selection}-{record}',
                                  bytes.fromhex(record), Options(selection, math, mixed, 0, 0, 0, 0, 0)))
    for numerator, denominator in [(1,2),(1,3),(1,17),(1,97),(7,3),(-7,3),
                                   (1234567,997),(1,99999999), (999999999,17)]:
        rational = Rational(numerator, denominator, 0); number = Number()
        assert lib.fx_rational_encode(C.byref(number), C.byref(rational)) == 0
        for selection in [10,14]:
            for mode in [0,4,8,9]:
                cases.append((f'rational-decimal-{numerator}-{denominator}-{selection}-{mode}',
                              bytes(number.bytes), Options(selection, 1, 0, mode, 3, 0, 0, 0)))
    randomizer = random.Random(991)
    for i in range(300):
        values = [randomizer.randrange(1,100) * (-1 if i % 2 else 1),
                  randomizer.randrange(1,1000), randomizer.randrange(1,100),
                  randomizer.randrange(1,100) * (-1 if i % 3 else 1),
                  randomizer.randrange(1,1000), randomizer.randrange(1,100)]
        parts = (Number * 6)(); number = Number()
        for j, value in enumerate(values): assert lib.fx_decimal_from_integer(C.byref(parts[j]), value) == 0
        assert lib.fx_surd_pack(C.byref(number), parts) == 0
        cases.append((f'surd-random-{i}', bytes(number.bytes),
                      Options(13,1,0,0,0,0,i%7,0)))
    for i in range(200):
        values = [randomizer.randrange(1,100) * (-1 if i % 2 else 1),
                  1 if i%2 else randomizer.randrange(2,1000), randomizer.randrange(1,100),
                  randomizer.randrange(1,100) * (-1 if i % 3 else 1),
                  1 if i%2 == 0 else randomizer.randrange(2,1000), randomizer.randrange(1,100)]
        parts = (Number * 6)(); number = Number()
        for j, value in enumerate(values): assert lib.fx_decimal_from_integer(C.byref(parts[j]), value) == 0
        assert lib.fx_surd_pack(C.byref(number), parts) == 0
        cases.append((f'surd-rational-term-{i}', bytes(number.bytes),
                      Options(13,1,0,0,0,0,i%7,0)))
    for i in range(1200):
        mode = [0, 4, 8, 9][i % 4]
        o = Options(10, 1, 0, mode, randomizer.randrange(10), i % 2, 0, 0)
        exponent = randomizer.choice(list(range(-12, 13)) + [-99, -98, 98, 99])
        mantissa = randomizer.randrange(100000000000000, 1000000000000000)
        cases.append((f'decimal-{i}', decimal_record(mantissa, exponent, 1 if i % 3 else -1), o))
    for mode in [0, 4, 8, 9]:
        for digits in range(10):
            for value in ['0', '1', '-1', '9.99999999995', '0.00000000999999999995',
                          '0.499999999995', '1234567891.499999', '1234567891.5']:
                n = Number(); assert lib.fx_decimal_parse(C.byref(n), value.encode()) == 0
                cases.append((f'boundary-{mode}-{digits}-{value}', bytes(n.bytes),
                              Options(10, 1, 0, mode, digits, 0, 0, 0)))
    for context in range(7):
        for value in ['1.23456789123456e10', '1.23456789123456e-10',
                      '1.23456789123456e-3', '-1.23456789123456e10']:
            n = Number(); assert lib.fx_decimal_parse(C.byref(n), value.encode()) == 0
            cases.append((f'decimal-context-{context}-{value}', bytes(n.bytes),
                          Options(10, 1, 0, 0, 0, 0, context, 0)))
    # Narrow coefficient contexts use nine digits outside exponent +/-9.
    # Sci10 rounds twice; Norm/Fix restart from the original record. Include
    # half-up double-rounding and carry across the exponent cutoff.
    for context in range(7):
        for mode,digits in [(0,0),(4,0),(8,0),(8,3),(9,0),(9,9),(9,8)]:
            for selection in range(2,11):
                for value in ['-1e99','1.23456789495e99','1.23456789495e-99',
                              '9.99999999995e9','9.99999999995e-10',
                              '9.99999999995e99','1.23456789495e9',
                              '1.23456789495e-9']:
                    n = Number(); assert lib.fx_decimal_parse(C.byref(n),value.encode()) == 0
                    cases.append((f'decimal-context-precision-{context}-{mode}-{digits}-{selection}-{value}',bytes(n.bytes),
                                  Options(selection,1,0,mode,digits,1,context,0)))
    # BA10/BB80 only delegates Norm/Fix to fixed nine-digit Sci when digit9
    # of the rounded ten-digit coefficient is nonzero. Delegation retains
    # trailing zeroes (2.01232740), while an already short value stays short.
    for context in range(7):
        for mode,digits in [(0,0),(4,0),(8,0),(8,3),(9,0)]:
            for selection in [0,10,14,30]:
                for value in ['2.01232739742523e12','-2.01232739742523e12',
                              '2.01232739742523e-12','2.01232739742523e9',
                              '1e10','-1e10','2.1e10','1.2345678e10',
                              '1.23456780001e10','1.23456789501e10',
                              '1.23456789499e10','9.99999999995e10']:
                    n = Number(); assert lib.fx_decimal_parse(C.byref(n),value.encode()) == 0
                    cases.append((f'compact-fixed-width-{context}-{mode}-{digits}-{selection}-{value}',bytes(n.bytes),
                                  Options(selection,1,0,mode,digits,1,context,0)))
    for row in json.loads((ROOT / 'analysis/pi-result-trace/manifest.json').read_text())['cases']:
        o = Options(13, 1, 0, 0, 0, 0, 0, 0)
        for address, value in row['context_overrides'].items():
            if address == '0x8106': o.math_output = value
        if 'decimal-selection' in row['name']: o.selection = 10
        cases.append(('pi-fixture-' + row['name'], bytes.fromhex(row['numeric_record']), o))
    # Native arithmetic supplies these records; the denominator sweep covers
    # both accepted factors of25200 and rejected reduced coefficients.
    for denominator in range(1, 129):
        machine.reset(); settings(machine)
        machine.er(0, 0x8300); machine.call(0x1d16e)
        machine.reg(2, denominator); machine.er(0, 0x8310); machine.call(0x1d08c)
        machine.er(0, 0x8300); machine.er(2, 0x8310); machine.call(0x1bfe0)
        cases.append((f'pi-denominator-{denominator}', bytes(machine.ram[0x8300:0x830a]), default))
    for denominator in range(2, 151):
        machine.reset(); settings(machine)
        machine.reg(2, 1); machine.er(0, 0x8300); machine.call(0x1d08c)
        machine.reg(2, denominator); machine.er(0, 0x8310); machine.call(0x1d08c)
        machine.er(0, 0x8300); machine.er(2, 0x8310); machine.call(0x1bfe0)
        cases.append((f'recurring-denominator-{denominator}', bytes(machine.ram[0x8300:0x830a]),
                      Options(14, denominator % 2, 0, 0, 0, denominator % 2, 0, 0)))
    for record in ['21a30000000000000301', '22a1a300000000000501']:
        cases.append(('recurring-exact-' + record, bytes.fromhex(record),
                      Options(14, 1, 0, 0, 0, 0, 0, 0)))
    with decimal.localcontext() as ctx:
        ctx.prec = 40
        for i in range(500):
            numerator = randomizer.randrange(1, 10 ** randomizer.randrange(1, 8))
            denominator = randomizer.randrange(1, 10 ** randomizer.randrange(1, 9))
            if i % 2: numerator = -numerator
            value = decimal.Decimal(numerator) / decimal.Decimal(denominator)
            n = Number(); assert lib.fx_decimal_parse(C.byref(n), str(value).encode()) == 0
            cases.append((f'rational-recognition-{numerator}-{denominator}', bytes(n.bytes), default))
        for i in range(200):
            record = decimal_record(randomizer.randrange(100000000000000, 1000000000000000),
                                    randomizer.randrange(-8, 7), 1 if i % 2 else -1)
            cases.append((f'recognition-negative-{i}', record, default))
    for base in ['1', '4200', '123456', '0.5', '0.333333333333333']:
        with decimal.localcontext() as ctx:
            ctx.prec = 40
            value = decimal.Decimal(base)
            unit = decimal.Decimal(10) ** (value.adjusted() - 14)
            for offset in [-51, -50, -49, -41, -40, -39, 0, 39, 40, 41, 49, 50, 51]:
                n = Number(); assert lib.fx_decimal_parse(C.byref(n), str(value + unit * offset).encode()) == 0
                cases.append((f'recognition-boundary-{base}-{offset}', bytes(n.bytes), default))
    for i in range(350):
        value = i if i < 257 else randomizer.randrange(1, 10000000000)
        n = Number(); assert lib.fx_decimal_parse(C.byref(n), str(value).encode()) == 0
        cases.append((f'prime-factor-{value}', bytes(n.bytes), Options(15, 1, 0, 0, 0, 0, 0, 0)))
    for i in range(250):
        record = decimal_record(randomizer.randrange(100000000000000,1000000000000000),
                                randomizer.randrange(-99,100), 1 if i%2 else -1)
        cases.append((f'prime-factor-decimal-{i}', record,
                      Options(15,1,0,[0,4,8,9][i%4],i%10,i%2,0,0)))
    for value in ['0.5','1.5','12345.678','-12345.678','1e10','1e15','1e99','1e-99']:
        n = Number(); assert lib.fx_decimal_parse(C.byref(n), value.encode()) == 0
        cases.append((f'prime-factor-boundary-{value}', bytes(n.bytes),Options(15,1,0,0,0,1,0,0)))
    # Marker40 belongs to decimal metadata, not the prime-factor magnitude.
    # Include the special-view regressions and the full prime decimal sample
    # domain, while keeping the input record immutable.
    prime_cases = [case for case in cases if case[0].startswith('prime-factor-')]
    for name, record, options in prime_cases:
        marked = bytes([record[0] | 0x40]) + record[1:]
        cases.append(('marked-' + name, marked,
                      Options(15, len(cases)%2, 0, options.display_mode,
                              options.digits, options.decimal_dot, len(cases)%7, 0)))
    for previous in range(16):
        for record in ['41234500000000000701', '41234500000000000001']:
            cases.append((f'marked-prime-history-{previous}-{record}', bytes.fromhex(record),
                          Options(previous*16+15,1,0,0,0,0,0,0)))
    for i in range(400):
        record = bytearray(decimal_record(randomizer.randrange(100000000000000, 1000000000000000),
                                          randomizer.randrange(-10, 9), 1 if i % 2 else -1))
        selection = [1,0,13][i % 3]
        if selection != 1: record[0] |= 0x40
        cases.append((f'sexagesimal-{i}', bytes(record), Options(selection, i % 2, 0, 0, 0, i % 2, 0, 0)))
    for value in ['0','1','-1','1.2345','0.999999999999999','9999999.99999999',
                  '0.00000277777777777778','0.00000555555555555556']:
        n = Number(); assert lib.fx_decimal_parse(C.byref(n), value.encode()) == 0
        cases.append((f'sexagesimal-boundary-{value}', bytes(n.bytes), Options(1,1,0,0,0,0,0,0)))
    for selection in range(2,10):
        for value in ['0','1.23456789','-1.23456789','1e-7','1e8']:
            n = Number(); assert lib.fx_decimal_parse(C.byref(n), value.encode()) == 0
            cases.append((f'decimal-selection-{selection}-{value}', bytes(n.bytes),
                          Options(selection,1,0,0,0,0,0,0)))
    for i in range(500):
        record = decimal_record(randomizer.randrange(100000000000000,1000000000000000),
                                randomizer.randrange(-99,100), 1 if i%2 else -1)
        cases.append((f'engineering-{i}', record,
                      Options(2+i%8,1,0,4 if i%2 else 0,0,i%2,0,0)))
    for i in range(1000):
        record = decimal_record(randomizer.randrange(100000000000000,1000000000000000),
                                randomizer.randrange(-99,100), 1 if i%2 else -1)
        cases.append((f'engineering-mode-{i}', record,
                      Options(2+i%8,1,0,[0,4,8,9][(i//8)%4], randomizer.randrange(10),
                              i%2,(i//32)%7,0)))
    for mode in [0,4,8,9]:
        for value in ['0','1','1e3','1e-3','9.99999999995e9','9.99999999995e-10']:
            n = Number(); assert lib.fx_decimal_parse(C.byref(n), value.encode()) == 0
            for selection in range(2,10):
                cases.append((f'engineering-boundary-{mode}-{value}-{selection}', bytes(n.bytes),
                              Options(selection,1,0,mode,3,1,0,0)))
    for previous in range(16):
        for selection in range(15):
            for value in ['1.23456789123456', '1000', '0.333333333333333',
                          '0.523598775598299']:
                n = Number(); assert lib.fx_decimal_parse(C.byref(n), value.encode()) == 0
                cases.append((f'selection-history-{previous}-{selection}-{value}', bytes(n.bytes),
                              Options(previous * 16 + selection,1,0,0,0,1,0,0)))
    for previous in range(16):
        n = Number(); assert lib.fx_decimal_parse(C.byref(n), b'1.23456789123456') == 0
        n.bytes[0] |= 0x40
        cases.append((f'selection-history-dms-{previous}', bytes(n.bytes),
                      Options(previous * 16 + 13,1,0,0,0,1,0,0)))
    for mode in [0,4,8,9]:
        for digits in range(10):
            for selection in [2,5,6,9,10,13]:
                for value in ['9.99999999999999e99','-9.99999999999999e99',
                              '9.99999999999999e-99']:
                    n = Number(); assert lib.fx_decimal_parse(C.byref(n), value.encode()) == 0
                    cases.append((f'rounding-range-{mode}-{digits}-{selection}-{value}', bytes(n.bytes),
                                  Options(selection,1,0,mode,digits,1,0,0)))
    # Complex/polar coefficient contexts preserve exact parentheses, but
    # ordinary decimal fallback resets the context to0 atC154..C15C.
    for context in [4,5,6]:
        for selection in [0,1,2,5,6,9,10,11,12,13,14,15]:
            for mode in [0,4,8,9]:
                for value in ['0','1','-1','1.23456789123456e10',
                              '1.23456789123456e-10','0.333333333333333',
                              '0.523598775598299']:
                    n = Number(); assert lib.fx_decimal_parse(C.byref(n), value.encode()) == 0
                    cases.append((f'complex-context-{context}-{selection}-{mode}-{value}',bytes(n.bytes),
                                  Options(selection,1,0,mode,3,1,context,0)))
    # Prime output consumes canonical tagged storage as raw packed decimal,
    # including rational separators and the original sign fields. Numeric
    # conversion before trial division would change these output tokens.
    for index in range(400):
        rational = Rational(randomizer.randrange(-99999999,100000000),
                            randomizer.randrange(1,99999999), 0)
        number = Number(); assert lib.fx_rational_encode(C.byref(number), C.byref(rational)) == 0
        for marked in [0, 0x40]:
            record = bytes([number.bytes[0] | marked]) + bytes(number.bytes[1:])
            cases.append((f'tagged-prime-rational-{index}-{marked}',record,
                          Options((index%16)*16+15,index%2,0,[0,4,8,9][index%4],index%10,index%2,index%7,0)))
    for numerator, denominator in [(1,2),(1,3),(7,3),(-7,3),(25,7),(100,3),(717,3946),(-717,3946)]:
        number = Number(); rational = Rational(numerator, denominator, 0)
        assert lib.fx_rational_encode(C.byref(number), C.byref(rational)) == 0
        cases.append((f'tagged-prime-boundary-{numerator}-{denominator}',bytes(number.bytes),
                      Options(15,1,0,0,0,1,0,0)))
    for index in range(150):
        parts = (Number * 6)(); number = Number()
        values = [randomizer.randrange(-99,100),randomizer.randrange(1,1000),randomizer.randrange(1,100),
                  randomizer.randrange(-99,100),randomizer.randrange(1,1000),randomizer.randrange(1,100)]
        for position, value in enumerate(values):
            assert lib.fx_decimal_from_integer(C.byref(parts[position]), value) == 0
        assert lib.fx_surd_pack(C.byref(number), parts) == 0
        cases.append((f'tagged-prime-surd-{index}',bytes(number.bytes),
                      Options(15,index%2,0,[0,4,8,9][index%4],index%10,index%2,index%7,0)))
    for error in range(16):
        for selection in range(16):
            for math in [0, 1]:
                cases.append((f'error-{error}-{selection}-{math}',bytes([0xf0 | error])+bytes(9),
                              Options(selection,math,0,0,0,1,0,0)))
    failures = []
    for name, record, o in cases:
        number = Number.from_buffer_copy(record); buffer = (C.c_uint8 * 512)(); result = Result()
        status = lib.fx_format_number(C.byref(number), C.byref(o), buffer, 512, C.byref(result))
        expected_kind, expected = oracle(machine, record, o)
        actual = bytes(buffer[:result.length])
        if status or actual != expected or result.kind != expected_kind or bytes(number.bytes) != record:
            failures.append({'name': name, 'record': record.hex(), 'options': list(bytes(o)),
                             'status': status, 'kind': [result.kind, expected_kind],
                             'actual': actual.hex(), 'expected': expected.hex()})
    # Canaries validate bounded writes and required length, rather than merely
    # checking that a sufficiently large output buffer happens to work.
    overflow_cases = 0
    boundary_samples = (cases[:12] + [case for case in cases if case[0].startswith('marked-prime-history-')][:2]
                        + [case for case in cases if case[0].startswith('tagged-prime-boundary-')]
                        + [case for case in cases if case[0].startswith('error-13-')][:1]
                        + [case for case in cases if case[0].startswith('surd-serialization-') and '-0-1' in case[0]]
                        + [case for case in cases if case[0].startswith('decimal-context-precision-1-9-0-10-')])
    boundary_samples += [case for case in cases if case[0].startswith('compact-fixed-width-1-0-0-10-')]
    for name, record, o in boundary_samples:
        expected_kind, expected = oracle(machine, record, o)
        number = Number.from_buffer_copy(record)
        for capacity in range(len(expected) + 2):
            storage = (C.c_uint8 * 128)(*([0xa5] * 128)); result = Result()
            output = C.cast(C.byref(storage, 1), C.POINTER(C.c_uint8))
            status = lib.fx_format_number(C.byref(number), C.byref(o), output, capacity, C.byref(result))
            assert status == (0 if capacity > len(expected) else -2)
            assert result.length == len(expected) and result.kind == expected_kind
            assert storage[0] == 0xa5 and storage[capacity + 1] == 0xa5
            if capacity:
                assert bytes(storage[1:capacity]) == expected[:capacity - 1].ljust(capacity - 1, b'\0') or capacity > len(expected)
                assert storage[min(capacity, len(expected) + 1)] == 0
            overflow_cases += 1
    output = ROOT / 'analysis/c-verification/format.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {'rom_sha256': hashlib.sha256(rom).hexdigest(),
                         'cases': len(cases), 'failures': len(failures),
                         'buffer_boundary_cases': overflow_cases, 'mismatches': failures,
                         'scope': 'C060 result tokens and kind; prepared routine contexts, passive peripherals'}
    if failures:
        report['status'] = 'fail'; output.write_text(json.dumps(report, indent=2) + '\n')
    else:
        write_report(output, report,
                         ['csrc/format/fx_format.c', 'csrc/format/fx_format.h',
                          'csrc/numeric/fx_numeric.c', 'csrc/numeric/fx_numeric.h',
                          'tools/c_verification.py','tools/trace_natural_result.py',
                          'analysis/verification/numeric-samples.json',
                          'analysis/pi-result-trace/manifest.json'], 'tools/test_format_c.py')
    print(f'{len(cases)} formatting cases, {len(failures)} mismatches')
    for f in failures[:12]: print(f)
    if failures: raise SystemExit(1)


if __name__ == '__main__': main()
