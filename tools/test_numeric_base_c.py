#!/usr/bin/env python3
"""Native differential checks for high-level prepared BASE-N numeric kernels.

The original firmware is executed only by the independent test oracle.
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
RAW_FIXTURE = ROOT / 'analysis/regressions/base-raw-scalar-arithmetic.json'
RAW_FIXTURE_SHA256 = '3f65e32b828b7a74aa82ec35acbd82f711767da6ce03770198d33a1061a36c8d'
sys.path.insert(0, str(ROOT / 'tools'))
from nxu8.machine import Machine
from trace_natural_result import settings
from c_verification import write_report


class Number(C.Structure):
    _fields_ = [('bytes', C.c_uint8 * 10)]
    def raw(self): return bytes(self.bytes)


class Rational(C.Structure):
    _fields_ = [('numerator', C.c_int64), ('denominator', C.c_uint64), ('flags', C.c_uint8)]


class NativeRegisters(C.Structure):
    _fields_ = [('pc', C.c_uint16), ('csr', C.c_uint8),
                ('lr', C.c_uint16 * 4), ('lcsr', C.c_uint8 * 4),
                ('dsr', C.c_uint8), ('ea', C.c_uint16), ('sp', C.c_uint16),
                ('psw', C.c_uint8), ('epsw', C.c_uint8 * 3),
                ('gr', C.c_uint64 * 2)]


class LiteralResult(C.Structure):
    _fields_ = [('consumed', C.c_size_t), ('native_status', C.c_uint),
                ('native_kind', C.c_uint8)]


def raw_decimal(mantissa, exponent, sign=1):
    if not mantissa: return bytes(10)
    digits = f'{mantissa:015d}'
    return bytes([int(digits[0]), *(int(digits[i:i+2], 16) for i in range(1, 15, 2)),
                  int(f'{exponent % 100:02d}', 16), (exponent >= 0) + (5 if sign < 0 else 0)])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--random-cases', type=int, default=8000)
    parser.add_argument('--explore', action='store_true')
    parser.add_argument('--exhaustive-bin', action='store_true', help='Check every signed 16-bit serializer input.')
    args = parser.parse_args()
    build = ROOT / 'analysis/build/numeric/base'; build.mkdir(parents=True, exist_ok=True)
    source_files = ['csrc/numeric/fx_base.c', 'csrc/numeric/fx_base_literal.c',
                    'csrc/numeric/fx_numeric.c', 'csrc/parse/fx_tokens.c', 'csrc/data/fx_rom_data.c']
    library = build / 'base.so'
    subprocess.run(['gcc', '-std=c99', '-O3', '-Wall', '-Wextra', '-Werror', '-pedantic',
                    '-shared', '-fPIC', *(str(ROOT / path) for path in source_files),
                    '-o', str(library)], check=True)
    lib = C.CDLL(str(library)); ptr = C.POINTER(Number); unsigned = C.POINTER(C.c_uint)
    lib.fx_decimal_parse.argtypes = [ptr, C.c_char_p]
    lib.fx_rational_encode.argtypes = [ptr, C.POINTER(Rational)]
    lib.fx_surd_pack.argtypes = [ptr, ptr]
    lib.fx_base_decode_word.argtypes = [C.POINTER(C.c_uint32), unsigned, ptr, C.c_uint8]
    lib.fx_base_encode_word.argtypes = [ptr, C.c_uint32, C.c_uint8, unsigned]
    lib.fx_base_validate.argtypes = [ptr, C.c_uint8, unsigned]
    lib.fx_base_validate_raw.argtypes = [ptr, C.c_uint8, unsigned]
    lib.fx_base_prepare.argtypes = [ptr, ptr, C.c_uint8, unsigned]
    lib.fx_base_prepare_scalar.argtypes = [ptr, ptr, C.c_uint8, unsigned]
    lib.fx_base_unary.argtypes = [ptr, ptr, C.c_uint8, C.c_int, unsigned]
    lib.fx_base_binary.argtypes = [ptr, ptr, ptr, C.c_uint8, C.c_int, unsigned]
    lib.fx_base_parse_literal.argtypes = [ptr, C.POINTER(C.c_uint8), C.c_size_t,
                                        C.c_uint8, C.c_uint8, C.POINTER(LiteralResult)]
    rom = (ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    machine = Machine(rom, build / 'oracle')
    registers = NativeRegisters.in_dll(machine.lib, 'CoreRegister')
    rng = random.Random(0x15a94); checks, failures = {}, []
    bases = [1, 7, 9, 15]
    unary_entries = [0x15c1c, 0x15c46]
    binary_entries = [0x15f34, 0x15f40, 0x15f4c, 0x15f58,
                      0x15d62, 0x15d9e, 0x15dda, 0x15e1e]
    assert hashlib.sha256(RAW_FIXTURE.read_bytes()).hexdigest() == RAW_FIXTURE_SHA256
    raw_fixture = json.loads(RAW_FIXTURE.read_text())
    assert hashlib.sha256(rom).hexdigest() == raw_fixture['firmware_sha256']
    raw_witnesses = {(case['selected_base'], case['left'], case['right'], case['operation']): case
                     for case in raw_fixture['arithmetic_witnesses']}

    def decimal(text):
        out = Number(); assert lib.fx_decimal_parse(C.byref(out), str(text).encode()) == 0
        return out.raw()

    def reset(base):
        machine.reset(); settings(machine)
        machine.ram[0x80f9] = 2; machine.ram[0x80fa] = base

    def rational(numerator, denominator, marked=0):
        out = Number()
        assert lib.fx_rational_encode(C.byref(out), C.byref(Rational(numerator, denominator, marked))) == 0
        return out.raw()

    def surd():
        components = (Number * 6)()
        for i in range(6):
            integer = (rng.randrange(-99, 100) if i % 3 == 0 else
                       rng.randrange(1, 1000) if i % 3 == 1 else rng.randrange(1, 100))
            components[i] = Number.from_buffer_copy(decimal(integer))
        out = Number(); assert lib.fx_surd_pack(C.byref(out), components) == 0
        return out.raw()

    def put(address, record):
        for i, value in enumerate(record): machine.ram[address + i] = value

    def check(group, actual, expected, detail):
        checks[group] = checks.get(group, 0) + 1
        if actual != expected:
            def serial(value):
                if isinstance(value, bytes): return value.hex()
                if isinstance(value, tuple): return [serial(item) for item in value]
                return value
            failures.append({'group': group, 'actual': serial(actual),
                             'native': serial(expected), 'input': detail})
            if not args.explore: raise AssertionError(json.dumps(failures[-1]))

    def native_decode(record, base):
        reset(base); put(0x8300, record)
        machine.er(0, 0x8300); machine.er(12, 0x8300); machine.call(0x15a1e)
        machine.call(0x15a94)
        word = sum(machine.reg(i) << (8 * i) for i in range(4))
        return word, int(bool(registers.psw & 0x80))

    def test_decode(group, record, base):
        source = Number.from_buffer_copy(record); word, carry = C.c_uint32(), C.c_uint()
        status = lib.fx_base_decode_word(C.byref(word), C.byref(carry), C.byref(source), base)
        check(group, (status, word.value, carry.value, source.raw()),
              (0, *native_decode(record, base), record), f'{record.hex()} base={base}')

    def native_encode(word, base):
        reset(base); put(0x8300, b'\xa5' * 10)
        for i in range(4): machine.reg(i, (word >> (8 * i)) & 255)
        machine.call(0x15b00)
        if machine.reg(9) == 255: return 3, b'\xa5' * 10
        machine.er(14, 0x8300); machine.call(0x15a64)
        return 0, bytes(machine.ram[0x8300:0x830a])

    def test_encode(group, word, base):
        out = Number.from_buffer_copy(b'\xa5' * 10); native_status = C.c_uint()
        status = lib.fx_base_encode_word(C.byref(out), word, base, C.byref(native_status))
        check(group, (status, native_status.value, out.raw()),
              (0, *native_encode(word, base)), f'word={word:08x} base={base}')

    def native_validate(record, base, prepare):
        reset(base); put(0x8300, record)
        if prepare:
            machine.er(0, 0x8300); machine.call(0x1d040)
        machine.er(12, 0x8300); machine.reg(6, 2); machine.reg(0, 0)
        machine.call(0x15e82)
        return machine.reg(0), bytes(machine.ram[0x8300:0x830a])

    def test_validate(group, record, base, prepare=False, alias=False):
        source = Number.from_buffer_copy(record); out = Number(); native_status = C.c_uint()
        expected = native_validate(record, base, prepare)
        if prepare:
            status = lib.fx_base_prepare(C.byref(out), C.byref(source), base, C.byref(native_status))
            check(group, (status, native_status.value, out.raw(), source.raw()),
                  (0, *expected, record), f'{record.hex()} base={base}')
            if alias:
                status = lib.fx_base_prepare(C.byref(source), C.byref(source), base, C.byref(native_status))
                check(group + '_alias', (status, native_status.value, source.raw()),
                      (0, *expected), f'{record.hex()} base={base}')
        else:
            status = lib.fx_base_validate(C.byref(source), base, C.byref(native_status))
            check(group, (status, native_status.value, source.raw()),
                  (0, *expected), f'{record.hex()} base={base}')

    def test_scalar_prepare(group, record, base):
        reset(base); put(0x8226, record)
        machine.reg(0, 0); machine.er(2, 0x8300); machine.er(12, 0x8300); machine.reg(6, 77)
        machine.call(0x15ed6)
        expected = (machine.reg(2), bytes(machine.ram[0x8300:0x830a]))
        detail = f'{record.hex()} base={base}'
        for alias in [False, True]:
            source = Number.from_buffer_copy(record); out = source if alias else Number(); native_status = C.c_uint()
            status = lib.fx_base_prepare_scalar(C.byref(out), C.byref(source), base, C.byref(native_status))
            check(group + ('_alias' if alias else ''), (status, native_status.value, out.raw()),
                  (0, *expected), detail)
            if not alias: check(group + '_immutable', source.raw(), record, detail)
        check(group + '_native_control', (machine.reg(6), bytes(machine.ram[0x8226:0x8230]),
                                         bytes(machine.ram[0x830a:0x8314])),
              (77, record, bytes(10)), detail)

    def native_operation(a, b, base, operation, unary=False, raw_domain=False):
        reset(base)
        put(0x8300, a + b'\xee' * 10 if raw_domain else a)
        put(0x8350, b + b'\x55' * 10 if raw_domain else b)
        machine.er(0, 0x8300); machine.er(12, 0x8300); machine.er(2, 0x8350); machine.reg(6, 2)
        machine.call((unary_entries if unary else binary_entries)[operation])
        result = machine.reg(0), bytes(machine.ram[0x8300:0x830a])
        if raw_domain:
            detail = f'{a.hex()} {b.hex()} base={base} operation={operation}'
            check('raw_arithmetic_native_storage',
                  (bytes(machine.ram[0x830a:0x8314]), bytes(machine.ram[0x8350:0x8364])),
                  (b'\xee' * 10, b + b'\x55' * 10), detail)
            witness = raw_witnesses.get((base, a.hex(), b.hex(), operation))
            if witness:
                check('raw_arithmetic_immutable_witness', result,
                      (witness['native_status'], bytes.fromhex(witness['native_result'])), detail)
        return result

    def test_operation(group, a, b, base, operation, unary=False, aliases=False, raw_domain=False):
        expected = native_operation(a, b, base, operation, unary, raw_domain)
        detail = f'{a.hex()} {b.hex()} base={base} operation={operation} unary={unary}'
        for target in range(3 if aliases and not unary else 2 if aliases else 1):
            left, right = Number.from_buffer_copy(a), Number.from_buffer_copy(b)
            out = Number() if target == 0 else left if target == 1 else right
            native_status = C.c_uint()
            if unary:
                status = lib.fx_base_unary(C.byref(out), C.byref(left), base, operation,
                                           C.byref(native_status))
            else:
                status = lib.fx_base_binary(C.byref(out), C.byref(left), C.byref(right), base,
                                            operation, C.byref(native_status))
            check(group + ('' if target == 0 else '_alias'),
                  (status, native_status.value, out.raw()), (0, *expected), detail)
            if target != 1: check(group + '_left_immutable', left.raw(), a, detail)
            if target != 2: check(group + '_right_immutable', right.raw(), b, detail)

    def radix_tokens(value, base):
        radix = {1: 2, 7: 8, 9: 10, 15: 16}[base]
        digits = []
        while value:
            value, digit = divmod(value, radix)
            digits.append(digit + (48 if digit < 10 else 174))
        return bytes(reversed(digits)) if digits else b'0'

    def test_literal(group, tokens, input_base, selected_base):
        reset(selected_base); put(0x8300, b'\xa5' * 80); put(0x8500, tokens)
        machine.er(12, 0x8300); machine.er(14, 0x8500)
        machine.reg(0, {1: 96, 7: 97, 9: 98, 15: 99}[input_base])
        machine.reg(6, 2); machine.reg(7, 0); machine.call(0x16828)
        expected = (machine.reg(2), machine.reg(7), machine.er(14) - 0x8500,
                    bytes(machine.ram[0x8300:0x830a]))
        storage = (C.c_uint8 * 12)(*([0xa5] * 12))
        out = C.cast(C.byref(storage, 1), ptr)
        source = (C.c_uint8 * len(tokens)).from_buffer_copy(tokens); result = LiteralResult()
        status = lib.fx_base_parse_literal(out, source, len(tokens), input_base, selected_base,
                                           C.byref(result))
        detail = f'{tokens.hex()} input_base={input_base} selected_base={selected_base}'
        check(group, (status, result.native_status, result.native_kind, result.consumed,
                      bytes(storage[1:11])), (0, *expected), detail)
        check(group + '_bounded', (storage[0], storage[11], bytes(source)),
              (0xa5, 0xa5, tokens), detail)

    boundary_text = ['0', '1', '-1', '.9', '-.9', '1.9', '-1.9',
        '32767', '32768', '-32768', '-32769', '32767.9999999999', '-32768.0000000001',
        '2147483647', '2147483648', '-2147483648', '-2147483649',
        '2147483647.99999', '-2147483648.00001', '4294967295', '4294967296',
        '-4294967295', '-4294967296', '9999999999', '10000000000',
        '1e-99', '-1e-99', '1e20', '-1e20', '1e99', '-1e99']
    for text in boundary_text:
        record = decimal(text)
        for base in bases:
            test_decode('conversion_boundary', record, base)
            test_validate('range_boundary', record, base)
            test_validate('preparation_boundary', record, base, True, True)
            test_operation('negation_boundary', record, bytes(10), base, 1, True, True)
    scalar_records = [decimal(text) for text in boundary_text]
    scalar_records += [bytes([record[0] | 0x40]) + record[1:] for record in scalar_records]
    scalar_records += [rational(n, d, mark) for n, d in
                      [(1, 2), (-1, 2), (7, 3), (-7, 3), (717, 3946), (-717, 3946),
                       (32768, 3), (2147483647, 3)] for mark in [0, 0x40]]
    scalar_records += [bytes.fromhex(raw) for raw in ['80000001000201010100',
                      '80000001000201020100', '80011322012201010601', '83638443036373810606']]
    scalar_records += [bytes([0xf0 | code]) + bytes(9) for code in range(16)]
    for record in scalar_records:
        for base in bases: test_scalar_prepare('scalar_preparation_boundary', record, base)
    words = [0, 1, 2, 32767, 32768, 32769, 65535, 65536, 0x7ffffffe, 0x7fffffff,
             0x80000000, 0x80000001, 0xffff7fff, 0xffff8000, 0xffff8001, 0xfffffffe, 0xffffffff]
    for word in words:
        for base in bases: test_encode('serialization_boundary', word, base)
    for exponent in range(-99, 100):
        for mantissa in [10**14, 10**14 + 1, 214748364800000, 327680000000000, 10**15 - 1]:
            for sign in [-1, 1]:
                raw = raw_decimal(mantissa, exponent, sign)
                for base in bases:
                    test_decode('conversion_exponent', raw, base)
                    test_validate('range_exponent', raw, base)
                    test_validate('preparation_exponent', raw, base, True)
    for base in bases:
        integers = [-32768, -32767, -255, -2, -1, 0, 1, 2, 255, 32766, 32767]
        if base != 1: integers += [-2147483648, -2147483647, -65536, 65535, 2147483646, 2147483647]
        for first in integers:
            a = decimal(first)
            for operation in range(2):
                test_operation('unary_integer_boundary', a, bytes(10), base, operation, True, True)
            for second in integers:
                b = decimal(second)
                for operation in range(8):
                    test_operation('binary_integer_boundary', a, b, base, operation, aliases=True)
        for first in ['-1.9', '-.9', '0', '.9', '1.9', '32767.9', '-32768']:
            for second in ['-1.9', '-.9', '0', '.9', '1.9', '1e-99']:
                for operation in range(8):
                    test_operation('binary_fraction_boundary', decimal(first), decimal(second), base,
                                   operation, aliases=True)
    for input_base in bases:
        width = {1: 16, 7: 11, 9: 10, 15: 8}[input_base]
        texts = [b'', b'0', b'00', b'0' * 256, b'0' * 256 + b'1', b'1' + b'0' * width,
                 b'2', b'8', b'1.1', b'1\x74', b'1\xa4', b'32768', b'2147483648',
                 b'37777777777', b'40000000000', b'80000000', b'\xbd' * 8,
                 b'1111111111111111']
        for selected_base in bases:
            for tokens in texts:
                test_literal('literal_boundary', tokens + b'\0', input_base, selected_base)
            for token in range(256):
                for start in [b'0', b'1']:
                    test_literal('literal_all_terminators', start + bytes([token, 0]),
                                 input_base, selected_base)
    for index in range(args.random_cases):
        base = bases[index % 4]
        if index % 3 == 0:
            a = raw_decimal(rng.randrange(10**14, 10**15), rng.randrange(-99, 100), rng.choice([-1, 1]))
            b = raw_decimal(rng.randrange(10**14, 10**15), rng.randrange(-99, 100), rng.choice([-1, 1]))
            for operation in range(4): test_operation('arithmetic_random_decimal', a, b, base, operation)
            test_decode('conversion_random_decimal', a, base)
            test_validate('preparation_random_decimal', a, base, True, True)
        else:
            bound = 32768 if base == 1 else 2147483648
            a, b = decimal(rng.randrange(-bound, bound)), decimal(rng.randrange(-bound, bound))
            for operation in range(8): test_operation('binary_random_integer', a, b, base, operation)
            for operation in range(2): test_operation('unary_random_integer', a, bytes(10), base, operation, True)
        test_encode('serialization_random_word', rng.randrange(2**32), base)
        input_base = bases[(index // 4) % 4]
        limit = 2**16 if input_base == 1 else 2**31 if input_base == 9 else 2**32
        value = rng.randrange(limit)
        digits = b'0' * rng.randrange(40) + radix_tokens(value, input_base)
        if index % 4 == 0: digits += bytes([rng.choice([32, 46, 116, 164, 255])])
        test_literal('literal_random', digits + b'\0', input_base, base)
        if index % 4 == 0: scalar = rational(rng.randrange(-999999, 1000000), rng.randrange(1, 1000), rng.choice([0, 0x40]))
        elif index % 4 == 1: scalar = surd()
        else:
            scalar = raw_decimal(rng.randrange(10**14, 10**15), rng.randrange(-99, 100), rng.choice([-1, 1]))
            if index % 4 == 2: scalar = bytes([scalar[0] | 0x40]) + scalar[1:]
        test_scalar_prepare('scalar_preparation_random', scalar, base)
    if args.exhaustive_bin:
        for integer in range(-32768, 32768):
            test_encode('serialization_exhaustive_signed16', integer % 2**32, 1)
    unsupported = 0
    for base in set(range(256)) - set(bases):
        source = Number.from_buffer_copy(decimal(1)); out = Number(); native_status = C.c_uint()
        assert lib.fx_base_prepare(C.byref(out), C.byref(source), base, C.byref(native_status)) == -3
        unsupported += 1
    for raw in ['41000000000000000001', '21a30000000000000301', '80000001000201020100',
                'f3000000000000000000']:
        source = Number.from_buffer_copy(bytes.fromhex(raw)); out = Number(); native_status = C.c_uint()
        assert lib.fx_base_prepare(C.byref(out), C.byref(source), 9, C.byref(native_status)) == -3
        unsupported += 1
    source = (C.c_uint8 * 2)(49, 50); out = Number.from_buffer_copy(b'\xa5' * 10); result = LiteralResult()
    assert lib.fx_base_parse_literal(C.byref(out), source, 2, 9, 9, C.byref(result)) == -1
    assert out.raw() == b'\xa5' * 10 and bytes(source) == b'12' and result.consumed == 2
    unsupported += 1
    # Preserve the existing canonical workload and its random stream. The
    # fixed raw records are appended only after every original check ran.
    canonical_cases = sum(checks.values()) + unsupported
    raw_stage_native_calls = 0
    for row in raw_fixture['records']:
        record = bytes.fromhex(row['record'])
        reset(9); put(0x8300, record); machine.er(0, 0x8300)
        machine.call(0x1ccf6, limit=3000000); raw_stage_native_calls += 1
        check('raw_scalar_classification_witness',
              (machine.reg(0), bytes(machine.ram[0x8300:0x830a])),
              (row['native_classification'], record), row['label'])
        for base in bases:
            native_stage = row['radices'][str(base)]
            for sign, field in [(1, 'compare_positive_limit'), (-1, 'compare_negative_limit')]:
                reset(base); put(0x8300, record)
                put(0x8350, decimal(sign * (32768 if base == 1 else 2147483648)))
                machine.er(0, 0x8300); machine.er(2, 0x8350)
                machine.call(0x1cd60, limit=3000000); raw_stage_native_calls += 1
                check('raw_scalar_comparison_witness',
                      (machine.reg(0), bytes(machine.ram[0x8300:0x830a])),
                      (native_stage[field], record), f'{row["label"]} base={base} {field}')
            reset(base); put(0x8300, record)
            machine.er(12, 0x8300); machine.reg(6, 2); machine.reg(0, 0)
            machine.call(0x15e82, limit=3000000); raw_stage_native_calls += 1
            expected = machine.reg(0)
            detail = f'{row["label"]} base={base}'
            check('raw_range_immutable_witness',
                  (expected, int(machine.counts[0x1ccf6 >> 1]), int(machine.counts[0x1cd60 >> 1]),
                   bytes(machine.ram[0x8300:0x830a])),
                  (native_stage['native_range_status'], native_stage['range_calls_classification'],
                   native_stage['range_calls_comparison'], record), detail)
            source = Number.from_buffer_copy(record); native_status = C.c_uint(0xab)
            status = lib.fx_base_validate_raw(C.byref(source), base, C.byref(native_status))
            check('raw_range_admission', (status, native_status.value, source.raw()),
                  (0, expected, record), detail)
    raw_arithmetic_native_calls = 0
    for base in bases:
        for first in raw_fixture['records']:
            a = bytes.fromhex(first['record'])
            for second in raw_fixture['records']:
                b = bytes.fromhex(second['record'])
                for operation in range(4):
                    test_operation('raw_scalar_arithmetic', a, b, base, operation,
                                   aliases=True, raw_domain=True)
                    raw_arithmetic_native_calls += 1
    assert raw_arithmetic_native_calls == raw_fixture['full_pairwise_native_calls']
    assert raw_stage_native_calls == raw_fixture['stage_native_calls']
    report = {'cases': sum(checks.values()) + unsupported, 'groups': checks,
              'canonical_cases': canonical_cases,
              'raw_arithmetic_native_calls': raw_arithmetic_native_calls,
              'raw_stage_native_calls': raw_stage_native_calls,
              'immutable_raw_fixture': {'path': str(RAW_FIXTURE.relative_to(ROOT)),
                                        'sha256': RAW_FIXTURE_SHA256},
              'failures': len(failures), 'mismatches': failures,
              'scope': '15A1E/15A94 decimal-to-word conversion;15B00/15A64 signed-word serialization;15E82 range admission;1D040 ordinary preparation;15ED6 post-fetch scalar preparation;15C1C/15C46 unary;15D62/15D9E/15DDA/15E1E bitwise;15F34/15F40/15F4C/15F58 prepared arithmetic;16828 radix literal scanner',
              'input': 'canonical ordinary decimal records, every exponent/sign, fractional/truncation and signed16/32 boundaries; deterministic random decimal and signed integer operands; full pairwise canonical raw headers0/2/4/6/8/F arithmetic and direct native classification/comparison/range stages',
              'output': 'exact ten-byte records, native R0/carry/range status, signed widths, immutable inputs and both output aliases',
              'explicit_unsupported_controls': unsupported,
              'gaps': ['Shared BASE-N expression precedence/dispatch, variable bank copy and controller integration belong to the parser/controller owners',
                       'raw marked/exact/error operands remain unsupported in direct word/unary/logical conversion; prepared arithmetic admits canonical raw scalars, and scalar preparation converts valid stored records',
                       'malformed BCD/compact records and token/output storage overlap are outside documented value APIs',
                       'invalid BIN logical operands that ignore native serializer errors may hang; those raw paths are explicitly unsupported',
                       'native RAM scratch/register writes are not exported by value APIs']}
    path = ROOT / 'analysis/c-verification/numeric_base.json'
    if args.explore or failures:
        path = build / 'exploration.json'; path.write_text(json.dumps(report, indent=2) + '\n')
    else:
        write_report(path, report, source_files + ['csrc/numeric/fx_base.h', 'csrc/numeric/fx_numeric.h',
                    'csrc/parse/fx_tokens.h', 'csrc/data/fx_rom_data.h', 'csrc/numeric/base/manifest.json',
                    'csrc/numeric/base/understood_ranges.json',
                    'tools/trace_natural_result.py', 'tools/c_verification.py',
                    str(RAW_FIXTURE.relative_to(ROOT))], 'tools/test_numeric_base_c.py')
    print(f'{sum(checks.values()) + unsupported} BASE-N comparisons, {len(failures)} mismatches', flush=True)
    for failure in failures[:10]: print(failure)
    if failures: raise SystemExit(1)


if __name__ == '__main__': main()
