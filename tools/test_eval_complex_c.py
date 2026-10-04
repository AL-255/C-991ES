#!/usr/bin/env python3
"""Compare complete CMPLX token expressions with original171F4.

This checks records, numerical status and consumed pointer in prepared modes;
it does not yet assert keyboard, persistent controller or LCD behavior.
"""
import argparse
import ctypes as C
import json
from pathlib import Path
import random
import subprocess

from c_verification import ROOT, write_report
from c_build_inputs import implementation_inputs
from nxu8.machine import Machine
from trace_natural_result import settings


class Number(C.Structure):
    _fields_ = [('bytes', C.c_uint8 * 10)]


class Options(C.Structure):
    _fields_ = [(name, C.c_uint8) for name in
                ('calculation_context', 'math_output', 'angle_unit')]


class Result(C.Structure):
    _fields_ = [('value', Number * 2), ('consumed', C.c_size_t),
                ('unsupported_token', C.c_uint8)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--random-cases', type=int, default=1000)
    parser.add_argument('--parser-source', type=Path,
                        help='Preview a parser source; requires --no-report')
    parser.add_argument('--no-report', action='store_true')
    args = parser.parse_args()
    if args.parser_source and not args.no_report:
        parser.error('Candidate parsers cannot publish a canonical report')
    build = ROOT / 'analysis/build/eval-complex'
    build.mkdir(parents=True, exist_ok=True)
    source_names = [
        'parse/fx_tokens.c', 'data/fx_rom_data.c',
        'numeric/fx_numeric.c', 'numeric/fx_transcend.c', 'numeric/fx_power.c',
        'numeric/fx_root.c', 'numeric/fx_logbase.c', 'numeric/fx_calculus.c', 'numeric/fx_integral.c', 'numeric/fx_derivative.c', 'numeric/fx_combinatorics.c',
        'complex/fx_complex.c', 'complex/fx_complex_angle.c',
        'complex/fx_complex_round.c', 'complex/fx_complex_dispatch.c',
        'linalg/fx_linalg.c', 'linalg/fx_linalg_store.c',
        'trig/fx_trig.c', 'trig/fx_trig_math.c', 'trig/fx_trig_inverse.c',
        'trig/fx_trig_hyperbolic.c',
    ]
    parser_source = args.parser_source or ROOT / 'csrc/parse/fx_eval.c'
    output = build / 'eval-complex.so'
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-shared', '-fPIC', '-I', str(ROOT / 'csrc'),
                    str(parser_source), *[str(ROOT / 'csrc' / name) for name in source_names],
                    '-o', str(output)], check=True)
    lib = C.CDLL(str(output))
    lib.fx_evaluate.argtypes = [C.POINTER(C.c_uint8), C.c_size_t,
                               C.POINTER(Options), C.POINTER(Result)]
    lib.fx_evaluate.restype = C.c_int
    machine = Machine((ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes(), build / 'oracle')
    failures = []
    counts = {}
    rng = random.Random(0xc4171f4)

    def check(tokens, domain, math_output=1, angle_unit=4, context=0xc4):
        raw = tokens + b'\0'
        machine.reset()
        settings(machine)
        machine.ram[0x80f9] = context
        machine.ram[0x8106] = math_output
        machine.ram[0x8105] = angle_unit
        for index, byte in enumerate(raw):
            machine.ram[0x8200 + index] = byte
        machine.word(0x8190, 0x8200)
        machine.er(0, 0x8190)
        machine.er(2, 0x8300)
        machine.call(0x171f4, limit=3000000)
        expected = [machine.reg(0), bytes(machine.ram[0x8300:0x8314]).hex(),
                    machine.word(0x8190) - 0x8200]
        buffer = (C.c_uint8 * len(raw)).from_buffer_copy(raw)
        result = Result()
        status = lib.fx_evaluate(buffer, len(buffer),
                                C.byref(Options(context, math_output, angle_unit)), C.byref(result))
        actual = [status, bytes(result.value).hex(), result.consumed]
        counts[domain] = counts.get(domain, 0) + 1
        if actual != expected:
            failure = {'input': tokens.hex(), 'domain': domain, 'context': context,
                       'math_output': math_output, 'angle_unit': angle_unit,
                       'actual': actual, 'expected': expected,
                       'unsupported_token': result.unsupported_token}
            failures.append(failure)
            if len(failures) <= 15:
                print(json.dumps(failure))

    fixtures = [b'\x80', b'2\x80', b'\x80\x80', b'1+2\x80', b'\x601+2\x80',
                b'\x60(1+2\x80)', b'(1+2\x80)(3+4\x80)', b'1\x4f\x80',
                b'(1+\x80)\x4f(2+\x80)', b'1\xae2\x80', b'(1+\x80)\xae2',
                b'1\xae(2+\x80)', b'(1+\x80)\xae(2+\x80)', b'1\xae2\xae3\x80',
                b'\x98\x601)', b'\x98\x602)', b'\x982)', b'\x982)\x75',
                b'\x80\x75', b'\x80\x76', b'\x80\x77', b'(1+\x80)^2)',
                b'(1+\x80)^3)', b'(1+\x80)^4)', b'(1+\x80)^\x601)',
                b'\x88(3+4\x80))', b'\xc3(3+4\x80))', b'\x63(3+4\x80))',
                b'\x88\x80)', b'\xc3\x80)', b'\x63\x80)', b'3\x57', b'5\xbe2',
                b'5\xbf2', b'3\x9f8)', b'\x682,8)', b'\x81+\x82\x80']
    for tokens in fixtures:
        for math_output in (0, 1):
            for angle_unit in (4, 5, 6):
                check(tokens, 'canonical_complex_grammar', math_output, angle_unit)

    for function in (0x63, 0x88, 0xc3, 0x98, 0xa8, 0x68, 0xa3, 0x73, 0x93,
                     0x70, 0x71, 0x72, 0x90, 0x91, 0x92, 0xa0, 0xa1, 0xa2,
                     0xb0, 0xb1, 0xb2):
        for argument in (b'0', b'1', b'\x601', b'1\xae3', b'\x982)', b'\x80',
                         b'1+2\x80', b'\x80-\x80', b'\x80\x75'):
            for math_output in (0, 1):
                check(bytes([function]) + argument + b')', 'function_admission', math_output)

    for tokens in (b'\xa0\x80)', b'\xa3(1+\x80))', b'\x98(1+\x80))',
                   b'(1+\x80)\x4f0', b'2\x80\xbe1', b'2\xbe\x80', b'2\x80\x9f4)',
                   b'2\x9f\x80)', b'\x682,\x80)', b'\x68\x80,2)', b'\x80\x57',
                   b'\x80\x25', b'\x80\x85', b'\x88)', b'\xc3+)', b'\x63,)',
                   b'1+\x80)', b'\x80+', b'\x80^)', b'\x80\x4f', b'\x80\xbe'):
        check(tokens, 'domain_and_error_cursor')

    # The imaginary-unit token produces zero in scalar COMP; do not introduce
    # a second grammar to support the CMPLX interpretation of that token.
    for tokens in (b'\x80', b'2\x80', b'1+2\x80', b'\xa0\x80)', b'\xa3(1+\x80))'):
        check(tokens, 'comp_imaginary_literal', context=0xc1)

    def real_atom():
        return rng.choice([str(rng.randrange(0, 101)).encode(), b'.125', b'.333333333333333',
                           b'1.23456789012345', b'1\xae3', b'\x82', b'\x982)'])

    def atom():
        choice = rng.randrange(5)
        if choice == 0:
            return b'\x80'
        if choice == 1:
            return b'\x98\x60' + str(rng.randrange(1, 101)).encode() + b')'
        if choice == 2:
            return b'(' + real_atom() + b'+' + real_atom() + b'\x80)'
        return real_atom()

    def expression(depth):
        if not depth or rng.randrange(3) == 0:
            return atom()
        return b'(' + expression(depth - 1) + rng.choice([b'+', b'-', b'\x4e', b'\x4f']) + expression(depth - 1) + b')'

    for index in range(args.random_cases):
        math_output, angle_unit = index % 2, 4 + index % 3
        argument = expression(rng.randrange(1, 4))
        check(argument, 'random_complex_expressions', math_output, angle_unit)
        check(bytes([rng.choice([0x63, 0x88, 0xc3, 0x98, 0xa0, 0xa3])]) + argument + b')',
              'random_complex_functions', math_output, angle_unit)
        check(b'(' + argument + b')^' + rng.choice([b'\x601', b'2', b'3', b'4', b'1\xae3']) + b')',
              'random_complex_powers', math_output, angle_unit)
        check(b'(' + expression(1) + b')\xae(' + expression(1) + b')',
              'random_complex_fractions', math_output, angle_unit)
    report = {'cases': sum(counts.values()), 'domains': counts, 'failures': failures,
              'comparison': 'Complete original171F4 status, both ten-byte records and consumed input pointer.',
              'scope': 'Prepared COMP/CMPLX input expressions; shared grammar, complex constants/arithmetic/fractions/powers/functions and admission/error cursors. Persistent UI, variables and LCD comparison are separate requirements.'}
    if failures:
        target = build / 'failures.json'
        target.write_text(json.dumps(report, indent=2) + '\n')
        raise AssertionError(f'{len(failures)} CMPLX expression mismatches; see {target}')
    if not args.no_report:
        report = write_report('analysis/c-verification/eval_complex.json', report,
                              implementation_inputs(ROOT, ['csrc/parse/fx_eval.c'] + ['csrc/' + name for name in source_names]) +
                              ['tools/c_verification.py', 'tools/trace_natural_result.py', 'tools/c_build_inputs.py'],
                              'tools/test_eval_complex_c.py')
    print(json.dumps({'status': 'pass', 'cases': report['cases'], 'domains': counts}, indent=2))


if __name__ == '__main__':
    main()
