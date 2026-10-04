#!/usr/bin/env python3
"""Compare readable complex formulas with the extracted firmware oracle.

The original CPU and ROM are test-only dependencies. GPL-3.0-or-later.
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


class Complex(C.Structure):
    _fields_ = [('real', Number), ('imaginary', Number)]


class Rational(C.Structure):
    _fields_ = [('numerator', C.c_int64), ('denominator', C.c_uint64), ('flags', C.c_uint8)]


def decimal_record(mantissa, exponent, sign=1, flags=0):
    if not mantissa: return bytes(10)
    digits = f'{mantissa:015d}'
    return bytes([int(digits[0]) | flags,
                  *(int(digits[i:i + 2], 16) for i in range(1, 15, 2)),
                  int(f'{exponent % 100:02d}', 16), (exponent >= 0) + (5 if sign < 0 else 0)])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--random-cases', type=int, default=8000)
    parser.add_argument('--no-report', action='store_true')
    args = parser.parse_args()
    build = ROOT / 'analysis/build/complex'
    build.mkdir(parents=True, exist_ok=True)
    library = build / 'complex.so'
    sources = ['csrc/complex/fx_complex.c', 'csrc/numeric/fx_numeric.c']
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror', '-pedantic',
                    '-shared', '-fPIC', *(str(ROOT / p) for p in sources), '-o', str(library)], check=True)
    lib = C.CDLL(str(library))
    pointer = C.POINTER(Complex)
    lib.fx_complex_binary.argtypes = [pointer, pointer, pointer, C.c_int]
    lib.fx_complex_error_status.argtypes = [pointer]
    lib.fx_complex_firmware_status.argtypes = [C.POINTER(C.c_uint8),C.c_int,pointer,pointer]
    lib.fx_scalar_numeric_classify.argtypes = [C.POINTER(C.c_uint8),C.POINTER(Number)]
    lib.fx_complex_integer_power.argtypes = [pointer, pointer, C.c_int]
    lib.fx_complex_power.argtypes = [pointer, pointer, pointer]
    lib.fx_complex_magnitude.argtypes = [pointer, pointer, C.c_int]
    lib.fx_complex_sqrt.argtypes = [pointer, pointer, C.c_int]
    for name in ['conjugate', 'negate', 'cleanup']:
        getattr(lib, 'fx_complex_' + name).argtypes = [pointer, pointer]
    lib.fx_decimal_parse.argtypes = [C.POINTER(Number), C.c_char_p]
    lib.fx_rational_encode.argtypes = [C.POINTER(Number), C.POINTER(Rational)]
    lib.fx_surd_pack.argtypes = [C.POINTER(Number), C.POINTER(Number)]
    rom = (ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    machine = Machine(rom, build / 'oracle')
    rng = random.Random(0x18480)
    cases, counts, failures = [], {}, []

    def literal(text):
        value = Number()
        assert lib.fx_decimal_parse(C.byref(value), str(text).encode()) == 0
        return bytes(value.bytes)

    def put(address, data):
        for position, byte in enumerate(data): machine.ram[address + position] = byte

    def check(group, actual, expected, detail):
        counts[group] = counts.get(group, 0) + 1
        if actual != expected:
            failures.append({'group': group, 'detail': detail, 'actual': actual, 'expected': expected})

    integers = [-99, -4, -1, 0, 1, 3, 4, 99]
    for index in range(300):
        values = [rng.choice(integers) for _ in range(4)]
        left = b''.join(literal(value) for value in values[:2])
        right = b''.join(literal(value) for value in values[2:])
        for operation in range(4): cases.append((f'integer-{values}', left, right, operation))
    for values in [[3,4,1,2], [1,2,3,4], [0,3,0,4], [0,3,4,0], [3,0,0,4], [0,0,0,0]]:
        left = b''.join(literal(value) for value in values[:2])
        right = b''.join(literal(value) for value in values[2:])
        for operation in range(4): cases.append((f'axis-{values}', left, right, operation))
    for index in range(args.random_cases):
        records = []
        for component in range(4):
            if rng.randrange(8) == 0: record = bytes(10)
            else:
                exponent = rng.randrange(-5, 6) if index % 3 else rng.randrange(-99, 100)
                record = decimal_record(rng.randrange(10**14, 10**15), exponent,
                                         rng.choice([-1, 1]), 0x40 if index % 7 == component else 0)
            records.append(record)
        cases.append((f'decimal-{index}', b''.join(records[:2]), b''.join(records[2:]), rng.randrange(4)))
    exact = []
    for index in range(400):
        if index % 2:
            values = [rng.randrange(-99,100),rng.randrange(1,1000),rng.randrange(1,100),
                      rng.randrange(-99,100),rng.randrange(1,1000),rng.randrange(1,100)]
            parts = (Number * 6)(); number = Number()
            for position, value in enumerate(values):
                assert lib.fx_decimal_parse(C.byref(parts[position]), str(value).encode()) == 0
            assert lib.fx_surd_pack(C.byref(number), parts) == 0
        else:
            number = Number(); fraction = Rational(rng.randrange(-99999,100000), rng.randrange(1,10000),0)
            assert lib.fx_rational_encode(C.byref(number), C.byref(fraction)) == 0
        exact.append(bytes(number.bytes))
    for index in range(800):
        records = [rng.choice(exact) for _ in range(4)]
        cases.append((f'exact-{index}', b''.join(records[:2]), b''.join(records[2:]), rng.randrange(4)))
    # Bit40-marked fractions have operation-specific admission. In
    # particular abs/sqrt reject header6x before normalizing the marker.
    marked_values = [literal(0),literal(1),literal(-1),literal('1.5'),
                     bytes([0x40]) + bytes(9)]
    for numerator,denominator in [(1,3),(-1,3),(7,3)]:
        for marker in [0,0x40]:
            number = Number(); fraction = Rational(numerator,denominator,marker)
            assert lib.fx_rational_encode(C.byref(number),C.byref(fraction)) == 0
            marked_values.append(bytes(number))
    for values in [[1,2,1,0,1,1],[-1,2,1,0,1,1],
                   [1,2,1,-1,2,1],[1,2,1,-1,3,1],[1,3,1,-1,2,1]]:
        parts=(Number*6)();number=Number()
        for position,value in enumerate(values):
            assert lib.fx_decimal_parse(C.byref(parts[position]),str(value).encode())==0
        assert lib.fx_surd_pack(C.byref(number),parts)==0
        marked_values.append(bytes(number))
    for first in marked_values:
        for second in marked_values:
            left = first + second;right = literal(3) + literal(4)
            # Repeating each operation ensures every pair reaches the unary
            # branch selected every third iteration as well as all formulas.
            for operation in range(4):
                cases.append(('marked-rational-grid',left,right,operation))
    for code in range(16):
        error = bytes([0xf0 | code]) + bytes(9)
        for position in range(4):
            records = [literal(3),literal(4),literal(1),literal(2)]; records[position] = error
            for operation in range(4):
                cases.append((f'error-{code}-{position}', b''.join(records[:2]), b''.join(records[2:]), operation))

    entries = [0x18404,0x1845c,0x183c4,0x18480]
    unary = [('conjugate',0x186f4),('negate',0x15d4e),('cleanup',0x18724),
             ('reciprocal',0x18632),('square',0x1869e),('cube',0x18672),
             ('magnitude_exact',0x1cade),('magnitude_decimal',0x1cade),
             ('sqrt_exact',0x1cbfc),('sqrt_decimal',0x1cbfc)]
    classification_records = set()
    for _,left,right,_ in cases:
        classification_records.update([left[:10],left[10:],right[:10],right[10:]])
    for record in sorted(classification_records):
        source=Number.from_buffer_copy(record);classification=C.c_uint8(0xab)
        status=lib.fx_scalar_numeric_classify(C.byref(classification),C.byref(source))
        machine.reset();settings(machine);put(0x8300,record);machine.er(0,0x8300)
        machine.call(0x1ccf6,limit=3000000)
        check('scalar_sign_classification',[status,classification.value,bytes(source).hex()],
              [0,machine.reg(0),bytes(machine.ram[0x8300:0x830a]).hex()],record.hex())
    for index, (name, left, right, operation) in enumerate(cases):
        source = Complex.from_buffer_copy(left); operand = Complex.from_buffer_copy(right); output = Complex()
        status = lib.fx_complex_binary(C.byref(output), C.byref(source), C.byref(operand), operation)
        machine.reset(); settings(machine); machine.ram[0x80f9] = 0xc4; machine.ram[0x810c] = 0
        put(0x8300,left);put(0x8340,right)
        machine.er(0,0x8300);machine.er(2,0x8340);machine.call(entries[operation],limit=3000000)
        expected = bytes(machine.ram[0x8300:0x8314])
        check(f'binary_{operation}', [status,bytes(output).hex(),bytes(source).hex(),bytes(operand).hex(),
                                     lib.fx_complex_error_status(C.byref(output))],
              [0,expected.hex(),left.hex(),bytes(machine.ram[0x8340:0x8354]).hex(),machine.reg(0)],
              [name,left.hex(),right.hex()])
        if index < 100:
            alias = Complex.from_buffer_copy(left)
            alias_status = lib.fx_complex_binary(C.byref(alias),C.byref(alias),C.byref(operand),operation)
            check('output_alias_left',[alias_status,bytes(alias).hex()],[status,bytes(output).hex()],[name,operation])
            alias = Complex.from_buffer_copy(right)
            alias_status = lib.fx_complex_binary(C.byref(alias),C.byref(source),C.byref(alias),operation)
            check('output_alias_right',[alias_status,bytes(alias).hex()],[status,bytes(output).hex()],[name,operation])
        if index % 3 == 0:
            for function, entry in unary:
                output = Complex()
                if function in ('reciprocal','square','cube'):
                    exponent = {'reciprocal':-1,'square':2,'cube':3}[function]
                    status = lib.fx_complex_integer_power(C.byref(output),C.byref(source),exponent)
                elif function.startswith('magnitude'):
                    status = lib.fx_complex_magnitude(C.byref(output),C.byref(source),function.endswith('exact'))
                elif function.startswith('sqrt'):
                    status = lib.fx_complex_sqrt(C.byref(output),C.byref(source),function.endswith('exact'))
                else: status = getattr(lib,'fx_complex_' + function)(C.byref(output),C.byref(source))
                machine.reset();settings(machine);machine.ram[0x80f9] = 0xc4;machine.ram[0x810c] = 0
                if function in ('magnitude_decimal','sqrt_decimal'): machine.ram[0x8106] = 0
                put(0x8300,left);machine.er(0,0x8300);machine.er(12,0x8300)
                machine.call(entry,limit=3000000)
                expected = bytes(machine.ram[0x8300:0x8314])
                return_kind = {'conjugate':1,'negate':2,'cleanup':3}.get(function,0)
                if function.startswith('magnitude'):return_kind=4
                elif function.startswith('sqrt'):return_kind=5
                numerical_status=C.c_uint8(0xab)
                numerical_host_status=lib.fx_complex_firmware_status(C.byref(numerical_status),return_kind,
                                                                     C.byref(source),C.byref(output))
                check('unary_' + function,[status,bytes(output).hex(),bytes(source).hex(),
                                           numerical_host_status,numerical_status.value],
                      [0,expected.hex(),left.hex(),0,machine.reg(0)],[name,left.hex()])
        if index % 37 == 0:
            # The original also permits both operand pointers to coincide.
            shared = Complex.from_buffer_copy(left); output = Complex()
            status = lib.fx_complex_binary(C.byref(output),C.byref(shared),C.byref(shared),operation)
            machine.reset();settings(machine);machine.ram[0x80f9] = 0xc4;machine.ram[0x810c] = 0
            put(0x8300,left);machine.er(0,0x8300);machine.er(2,0x8300)
            machine.call(entries[operation],limit=3000000)
            expected = bytes(machine.ram[0x8300:0x8314])
            check('coincident_input_operands',[status,bytes(output).hex(),bytes(shared).hex()],
                  [0,expected.hex(),left.hex()],[name,operation])
            status = lib.fx_complex_binary(C.byref(shared),C.byref(shared),C.byref(shared),operation)
            check('coincident_input_output_alias',[status,bytes(shared).hex()],
                  [0,expected.hex()],[name,operation])

    for real in [-3,-1,0,1,2,3,4,'.5','1.00000000000001']:
        for imaginary in [0,1,-1]:
            exponent = Complex.from_buffer_copy(literal(real) + literal(imaginary))
            source = Complex.from_buffer_copy(literal(3) + literal(4));output = Complex()
            status = lib.fx_complex_power(C.byref(output),C.byref(source),C.byref(exponent))
            machine.reset();settings(machine);put(0x8300,bytes(source));put(0x8340,bytes(exponent))
            machine.er(0,0x8300);machine.er(2,0x8340);machine.call(0x186a8)
            check('restricted_power',[status,bytes(output).hex(),lib.fx_complex_error_status(C.byref(output))],
                  [0,bytes(machine.ram[0x8300:0x8314]).hex(),machine.reg(0)],[real,imaginary])

    # Integer cleanup can carry a fifteen-digit mantissa beyond exponent99.
    # Native18724 checks each scalar return immediately, collapsing a newly
    # produced error to realF3/zeroimag. Its early real-F return and imaginary
    # F0 success quirk remain distinct from this newly produced overflow.
    cleanup_boundary=[]
    for mantissa in [999999999990000,999999999999990,999999999999991,999999999999999]:
        for exponent in [98,99]:
            for sign in [-1,1]:
                for marker in [0,0x40]:
                    value=decimal_record(mantissa,exponent,sign,marker)
                    for companion in [literal(0),literal(3),bytes([0xf0])+bytes(9)]:
                        cleanup_boundary.extend([value+companion,companion+value])
    overflow=decimal_record(999999999999999,99)
    for code in range(16):
        error=bytes([0xf0|code])+bytes(9)
        cleanup_boundary.extend([error+overflow,overflow+error,literal(3)+error])
    for raw in cleanup_boundary:
        machine.reset();settings(machine);put(0x8300,raw);machine.er(0,0x8300)
        machine.call(0x18724,limit=3000000)
        expected=bytes(machine.ram[0x8300:0x8314]);native_status=machine.reg(0)
        source=Complex.from_buffer_copy(raw);output=Complex();numerical_status=C.c_uint8(0xab)
        host=lib.fx_complex_cleanup(C.byref(output),C.byref(source))
        status_host=lib.fx_complex_firmware_status(C.byref(numerical_status),3,C.byref(source),C.byref(output))
        check('cleanup_overflow_admission',[host,bytes(output).hex(),bytes(source).hex(),status_host,numerical_status.value],
              [0,expected.hex(),raw.hex(),0,native_status],raw.hex())
        alias=Complex.from_buffer_copy(raw)
        alias_host=lib.fx_complex_cleanup(C.byref(alias),C.byref(alias))
        check('cleanup_overflow_alias',[alias_host,bytes(alias).hex()],[0,expected.hex()],raw.hex())

    report = {'cases':sum(counts.values()),'groups':counts,'failures':len(failures),'mismatches':failures,
              'seed':'0x18480','random_cases':args.random_cases,
              'scope':'Complete20-byte complex arithmetic, restricted powers, conjugate, negate, cleanup, magnitude and restricted square root in prepared Math CMPLX context',
              'input':'canonical decimal, rational, compact surd and error real/imaginary pairs, explicit operation',
              'output':'all20 result bytes, native binary/selector/unary R0 numerical status, unary record error policy, source immutability and output aliases',
              'limitation':'prepared ER4=0 conjugation context; full CMPLX evaluator/key UI, malformedBCD, scalar scratchRAM and other register side effects excluded'}
    path = ROOT / 'analysis/c-verification/complex.json'
    if not args.no_report:
        if failures: report['status'] = 'fail';path.write_text(json.dumps(report,indent=2) + '\n')
        else: write_report(path,report,[*sources,'csrc/complex/fx_complex.h','csrc/numeric/fx_numeric.h',
                                      'tools/trace_natural_result.py','tools/c_verification.py'],
                          'tools/test_complex_c.py')
    print(f'{sum(counts.values())} complex checks, {len(failures)} mismatches')
    for failure in failures[:20]: print(failure)
    if failures: raise SystemExit(1)


if __name__ == '__main__': main()
