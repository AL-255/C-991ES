#!/usr/bin/env python3
"""Compare prepared variable expression/store transactions with original171F4."""
import argparse
import ctypes as C
import json
import random
import subprocess

from c_verification import ROOT, write_report
from c_build_inputs import implementation_inputs
from nxu8.machine import Machine
from trace_natural_result import settings
from test_eval_complex_c import Number, Options, Result


class Variables(C.Structure):
    _fields_ = [('values', (Number * 2) * 10)]


SOURCES = [
    'parse/fx_eval.c', 'parse/fx_eval_rich.c','parse/fx_eval_rich_unary.c','parse/fx_eval_rich_reduce.c','parse/fx_eval_surd_workspace.c','platform/fx_platform.c','platform/fx_result_classify.c','numeric/fx_raw_decimal_exp.c', 'stats/fx_stats.c', 'stats/fx_stats_value.c', 'parse/fx_eval_storage.c', 'parse/fx_eval_finish.c', 'parse/fx_tokens.c', 'data/fx_rom_data.c',
    'numeric/fx_numeric.c', 'numeric/fx_random.c', 'numeric/fx_transcend.c', 'numeric/fx_power.c',
    'numeric/fx_base.c', 'numeric/fx_base_literal.c',
    'numeric/fx_sexagesimal.c', 'numeric/fx_quotient_remainder.c',
        'numeric/fx_raw_decimal_parts.c', 'numeric/fx_raw_decimal_divide.c',
        'numeric/fx_raw_decimal_multiply_add.c', 'numeric/fx_raw_fraction_convert.c',
    'numeric/fx_root.c', 'numeric/fx_logbase.c', 'numeric/fx_combinatorics.c',
    'numeric/fx_calculus.c', 'numeric/fx_integral.c', 'numeric/fx_integral_storage.c', 'numeric/fx_c4_integral_storage.c', 'numeric/fx_derivative.c', 'numeric/fx_derivative_storage.c', 'numeric/fx_surd_components.c', 'numeric/fx_raw_rational.c', 'complex/fx_complex.c', 'complex/fx_complex_angle.c',
    'complex/fx_complex_round.c', 'complex/fx_complex_dispatch.c',
        'linalg/fx_linalg.c', 'linalg/fx_linalg_store.c',
    'trig/fx_trig.c', 'trig/fx_trig_math.c', 'trig/fx_trig_inverse.c',
    'trig/fx_trig_hyperbolic.c',
]
LOADS = [0x54, 0x8b, 0x41, 0x42, 0x43, 0x44, 0x45, 0x46, 0x58, 0x59]
STORES = [0x4b, None, 0x47, 0x48, 0x49, 0x4a, 0x83, 0x84, 0x4c, 0x4d]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--random-cases', type=int, default=1000)
    ap.add_argument('--no-report', action='store_true')
    args = ap.parse_args()
    build = ROOT / 'analysis/build/eval-variables'
    build.mkdir(parents=True, exist_ok=True)
    shared = build / 'eval-variables.so'
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-shared', '-fPIC', *[str(ROOT / 'csrc' / f) for f in SOURCES],
                    '-o', str(shared)], check=True)
    lib = C.CDLL(str(shared))
    lib.fx_evaluate_with_variables.argtypes = [C.POINTER(C.c_uint8), C.c_size_t,
                                               C.POINTER(Options), C.POINTER(Variables),
                                               C.POINTER(Result)]
    lib.fx_evaluate_with_variables.restype = C.c_int
    lib.fx_decimal_parse.argtypes = [C.POINTER(Number), C.c_char_p]
    lib.fx_number_sqrt.argtypes = [C.POINTER(Number), C.POINTER(Number), C.c_int]
    oracle = Machine((ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes(), build / 'oracle')
    rng = random.Random(0x51ca522a)
    failures, counts = [], {}

    def decimal(text):
        n = Number()
        assert lib.fx_decimal_parse(C.byref(n), str(text).encode()) == 0
        return bytes(n)

    def sqrt(integer):
        source = Number.from_buffer_copy(decimal(integer))
        output = Number()
        assert lib.fx_number_sqrt(C.byref(output), C.byref(source), 1) == 0
        return bytes(output)

    records = [decimal(x) for x in (0, 1, -1, 3, '-1.25', '1e-99', '1e99')]
    records += [bytes.fromhex('21a30000000000000301'), sqrt(2), sqrt(998),
                bytes.fromhex('89970199099801990106'), bytes.fromhex('41000000000000000001')]

    def bank(real, imaginary):
        values = Variables()
        for slot in range(10):
            values.values[slot][0] = Number.from_buffer_copy(real)
            values.values[slot][1] = Number.from_buffer_copy(imaginary)
        return values

    def check(tokens, values, group, math_output=1, context=0xc1, unit=4):
        before = bytes(values)
        oracle.reset(); settings(oracle)
        oracle.ram[0x80f9] = context; oracle.ram[0x80fc] = 1
        oracle.ram[0x8106] = math_output; oracle.ram[0x8105] = unit
        for slot in range(10):
            for part, base in ((0, 0x8226), (1, 0x8408)):
                for i, byte in enumerate(bytes(values.values[slot][part])):
                    oracle.ram[base+10*slot+i] = byte
        raw = tokens+b'\0'
        for i, byte in enumerate(raw): oracle.ram[0x8200+i] = byte
        oracle.word(0x8190, 0x8200); oracle.er(0, 0x8190); oracle.er(2, 0x8300)
        oracle.call(0x171f4, limit=3000000)
        expected_variables = Variables()
        for slot in range(10):
            for part, base in ((0, 0x8226), (1, 0x8408)):
                expected_variables.values[slot][part] = Number.from_buffer_copy(
                    bytes(oracle.ram[base+10*slot:base+10*slot+10]))
        expected = [oracle.reg(0), bytes(oracle.ram[0x8300:0x8314]).hex(),
                    oracle.word(0x8190)-0x8200, bytes(expected_variables).hex()]
        buffer = (C.c_uint8 * len(raw)).from_buffer_copy(raw)
        result = Result()
        status = lib.fx_evaluate_with_variables(buffer, len(raw),
                                               C.byref(Options(context, math_output, unit)),
                                               C.byref(values), C.byref(result))
        actual = [status, bytes(result.value).hex(), result.consumed, bytes(values).hex()]
        assert bytes(buffer) == raw
        counts[group] = counts.get(group, 0)+1
        if actual != expected:
            failure = {'input': tokens.hex(), 'group': group, 'context': context,
                       'math_output': math_output, 'angle_unit': unit,
                       'initial_variables': before.hex(), 'expected': expected,
                       'actual': actual, 'unsupported_token': result.unsupported_token}
            failures.append(failure)
            if len(failures) <= 10: print(json.dumps(failure))

    for context in (0xc1, 0xc4):
        for math_output in (0, 1):
            for record in records:
                for imaginary in (records[0], records[3], records[8]):
                    for slot, token in enumerate(LOADS):
                        check(bytes([token]), bank(record, imaginary), 'load_all_slots', math_output, context)
                    for token in [t for t in STORES if t is not None] + [0x99, 0xa9]:
                        for expression in (b'3', b'A', b'A+1', b'2A', b'(A+B)\x4f3'):
                            check(expression+bytes([token]), bank(record, imaginary),
                                  'store_and_memory_transactions', math_output, context)
    for context in (0xc1, 0xc4):
        for tokens in (b'A2', b'A.5', b'(A)2', b'\x982)3', b'A(2)', b'AB', b'2A^2)',
                       b'A+', b'A\x47+1', b'(A\x47)', b'A\x47\x47', b'A\x99)',
                       b'1\x7499\x99', b'1\x7499\xa9', b'A\x99\x47',
                       b'(3\x47', b'\x982\x47', b'(1+2\x47', b'\x98\x601\x47',
                       b'3\x47)', b'\x982\x47)', b'3^2\x47', b'1+2\x47', b'\xa030\x47'):
            check(tokens, bank(decimal('1e99'), records[0]), 'admission_and_error_cursors', context=context)
    for math_output in (0, 1):
        for unit in (4, 5, 6):
            for record in records:
                for token in (0x63, 0x88, 0xc3):
                    for argument in (b'A', b'(A+B)', b'2A', b'A+1'):
                        check(bytes([token])+argument+b')', bank(record, decimal(7)),
                              'comp_scalar_prefixes', math_output, 0xc1, unit)
    for index in range(args.random_cases):
        context = (0xc1, 0xc4)[index % 2]
        values = Variables()
        for slot in range(10):
            values.values[slot][0] = Number.from_buffer_copy(rng.choice(records[:11]))
            values.values[slot][1] = Number.from_buffer_copy(rng.choice(records[:11]))
        left, right = rng.sample(LOADS, 2)
        expression = b'('+bytes([left])+rng.choice([b'+', b'-', b'\x4e', b'\x4f'])+bytes([right])+b')'
        check(expression, values, 'random_variable_arithmetic', index % 3 != 0, context, 4+index % 3)
        suffix = rng.choice([t for t in STORES if t is not None]+[0x99, 0xa9])
        check(expression+bytes([suffix]), values, 'random_store_transactions', index % 3 != 0, context)
    data = {'cases': sum(counts.values()), 'domains': counts, 'failures': failures,
            'comparison': 'Original171F4 status, full20-byte result, consumed input cursor, all ten real/imaginary variable pairs and immutable input.',
            'scope': 'Prepared ordinary COMP/CMPLX scalar variable banks; all loads/stores and M+/M-. Bus aliases, matrix references and malformed foreign error variables are outside this typed API.'}
    if failures:
        (build / 'failures.json').write_text(json.dumps(data, indent=2)+'\n')
        raise AssertionError(f'{len(failures)} variable-expression mismatches')
    if not args.no_report:
        data = write_report('analysis/c-verification/eval_variables.json', data,
                            implementation_inputs(ROOT, ['csrc/'+p for p in SOURCES])+
                            ['tools/test_eval_complex_c.py', 'tools/trace_natural_result.py', 'tools/c_verification.py',
                             'tools/c_build_inputs.py', 'tools/trace_natural_result.py', 'tools/verify_firmware.py', 'tools/nxu8/decoder.py'],
                            'tools/test_eval_variables_c.py')
    print(json.dumps({'status': 'pass', 'cases': data['cases'], 'domains': counts}, indent=2))


if __name__ == '__main__': main()
