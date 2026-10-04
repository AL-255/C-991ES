#!/usr/bin/env python3
"""Compare the high-level expression parser and result pipeline with the ROM.

This exercises supported COMP expression tokens at the evaluator boundary,
not keyboard, reset, modes, or currently unimplemented expression functions.
"""
import argparse
import ctypes as C
import hashlib
import json
from pathlib import Path
import random
import subprocess

from nxu8.machine import Machine
from trace_natural_result import settings
from c_verification import write_report
from c_build_inputs import implementation_inputs

ROOT = Path(__file__).resolve().parents[1]


class Number(C.Structure):
    _fields_ = [('bytes', C.c_uint8 * 10)]


class EvalOptions(C.Structure):
    _fields_ = [(n, C.c_uint8) for n in ('calculation_context', 'math_output', 'angle_unit')]


class EvalResult(C.Structure):
    _fields_ = [('value', Number * 2), ('consumed', C.c_size_t), ('unsupported_token', C.c_uint8)]


class FormatOptions(C.Structure):
    _fields_ = [(n, C.c_uint8) for n in ('selection', 'math_output', 'mixed_fraction',
                'display_mode', 'digits', 'decimal_dot', 'format_context', 'recurring_style')]


class FormatResult(C.Structure):
    _fields_ = [('length', C.c_size_t), ('kind', C.c_uint8), ('recognized', C.c_uint8)]


class Render(C.Structure):
    _fields_ = [('rom', C.POINTER(C.c_uint8)), ('rom_size', C.c_size_t), ('memory', C.POINTER(C.c_uint8))]


class Box(C.Structure):
    _fields_ = [('width', C.c_uint16), ('height', C.c_uint8), ('depth', C.c_uint8)]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--random-cases', type=int, default=1000)
    ap.add_argument('--records-only', action='store_true', help='Triage evaluator parity without formatter/layout; separate report')
    args = ap.parse_args()
    build = ROOT / 'analysis/build/eval'
    build.mkdir(parents=True, exist_ok=True)
    output = build / 'eval.so'
    sources = ['parse/fx_eval.c', 'parse/fx_tokens.c', 'data/fx_rom_data.c',
               'numeric/fx_numeric.c', 'numeric/fx_transcend.c', 'numeric/fx_power.c', 'numeric/fx_root.c', 'numeric/fx_calculus.c', 'numeric/fx_integral.c', 'numeric/fx_derivative.c', 'numeric/fx_combinatorics.c', 'numeric/fx_logbase.c',
               'complex/fx_complex.c', 'complex/fx_complex_angle.c', 'complex/fx_complex_round.c', 'complex/fx_complex_dispatch.c',
        'linalg/fx_linalg.c', 'linalg/fx_linalg_store.c',
               'trig/fx_trig.c', 'trig/fx_trig_math.c', 'trig/fx_trig_inverse.c', 'trig/fx_trig_hyperbolic.c',
               'format/fx_format.c', 'render/fx_render.c', 'render/fx_render_context.c', 'render/fx_layout.c', 'render/fx_layout_validate.c']
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
                    *[str(ROOT / 'csrc' / f) for f in sources], '-o', str(output)], check=True)
    lib = C.CDLL(str(output))
    lib.fx_evaluate.argtypes = [C.POINTER(C.c_uint8), C.c_size_t,
                               C.POINTER(EvalOptions), C.POINTER(EvalResult)]
    lib.fx_evaluate.restype = C.c_int
    lib.fx_format_default_options.restype = FormatOptions
    lib.fx_format_number.argtypes = [C.POINTER(Number), C.POINTER(FormatOptions),
                                    C.POINTER(C.c_uint8), C.c_size_t, C.POINTER(FormatResult)]
    lib.fx_begin_layout_pass.argtypes = [C.POINTER(Render), C.c_uint8]
    lib.fx_layout_sequence.argtypes = [C.POINTER(Render), C.c_uint16, C.POINTER(Box), C.c_uint16, C.c_uint8]
    lib.fx_layout_sequence.restype = C.c_uint16
    lib.fx_flush_framebuffer.argtypes = [C.POINTER(Render)]
    c_rom = (C.c_uint8 * 0x30000).in_dll(lib, 'fx_rom_data')
    rom = (ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    m = Machine(rom, build / 'oracle')
    rng = random.Random(0x171f4)
    domains = {}
    failures = []

    def native(tokens, math_output, angle_unit):
        m.reset(); settings(m)
        m.ram[0x8106] = math_output
        m.ram[0x8105] = angle_unit
        for i, b in enumerate(tokens): m.ram[0x8200 + i] = b
        m.word(0x8190, 0x8200)
        m.er(0, 0x8190); m.er(2, 0x8300); m.call(0x171f4, limit=3000000)
        return m.reg(0), bytes(m.ram[0x8300:0x8314]), m.word(0x8190) - 0x8200

    def check(tokens, domain, format_result=True, math_output=1, angle_unit=4):
        if args.records_only: format_result = False
        if not tokens.endswith(b'\0'): tokens += b'\0'
        original, records, consumed = native(tokens, math_output, angle_unit)
        buf = (C.c_uint8 * len(tokens)).from_buffer_copy(tokens)
        result = EvalResult()
        status = lib.fx_evaluate(buf, len(buf), C.byref(EvalOptions(0xc1, math_output, angle_unit)), C.byref(result))
        actual = (status, bytes(result.value), result.consumed)
        expected = (original, records, consumed)
        if actual != expected:
            failures.append({'input': tokens.hex(), 'domain': domain, 'actual':
                             [status, bytes(result.value).hex(), result.consumed], 'expected':
                             [original, records.hex(), consumed]})
            if len(failures) > 30:
                (ROOT / 'analysis/c-verification/eval-mismatches.json').write_text(json.dumps(failures, indent=2) + '\n')
                raise AssertionError(json.dumps(failures, indent=2))
        domains[domain] = domains.get(domain, 0) + 1
        if actual != expected: return
        if status == 0 and original == 0 and format_result:
            # Selection is part of the native pipeline, not fixed by the test.
            m.call(0xc034)
            selected = m.ram[0x8100]
            m.er(0, 0x8300); m.er(2, 0x8500); m.word(0x8dee, 0); m.call(0xc060)
            expected_tokens = bytes(m.ram[0x8500:0x8700]).split(b'\0', 1)[0]
            options = lib.fx_format_default_options(); options.selection = selected
            options.math_output = math_output
            formatted = (C.c_uint8 * 512)(); detail = FormatResult()
            fstatus = lib.fx_format_number(C.byref(result.value[0]), C.byref(options),
                                          formatted, len(formatted), C.byref(detail))
            assert fstatus == 0, (tokens.hex(), fstatus)
            actual_tokens = bytes(formatted[:detail.length])
            assert (actual_tokens, detail.kind) == (expected_tokens, m.reg(0)), (
                    tokens.hex(), actual_tokens.hex(), expected_tokens.hex(), detail.kind, m.reg(0))
            domains['evaluate_select_format_pipeline'] = domains.get('evaluate_select_format_pipeline', 0) + 1
            # Feed the C formatter output to the C layout. Start both renderers
            # from the same post-evaluation state, disabling editor cursor work.
            m.ram[0x8114] = 255
            memory = (C.c_uint8 * 65536).from_buffer_copy(bytes(m.ram))
            for i, b in enumerate(actual_tokens + b'\0'): memory[0x8500 + i] = b
            render = Render(c_rom, len(c_rom), memory)
            for draw in (0, 1):
                m.reg(0, draw); m.call(0xc634); lib.fx_begin_layout_pass(C.byref(render), draw)
                m.er(0, 0x8500); m.er(2, 0x8600); m.word(0x8dee, 2); m.word(0x8df0, 17)
                m.call(0x9cd6)
                box = Box(); stop = lib.fx_layout_sequence(C.byref(render), 0x8500, C.byref(box), 2, 17)
                assert (stop, bytes(box)) == (m.er(0), bytes(m.ram[0x8600:0x8604])), (
                        tokens.hex(), draw, 'layout metrics')
                for start, length in [(0x8640, 200), (0x87d0, 384), (0x8007, 2), (0x811f, 1)]:
                    assert bytes(memory[start:start+length]) == bytes(m.ram[start:start+length]), (
                            tokens.hex(), draw, 'layout memory', hex(start))
                domains['pipeline_layout_passes'] = domains.get('pipeline_layout_passes', 0) + 1
            m.call(0x3cfc); lib.fx_flush_framebuffer(C.byref(render))
            assert bytes(memory[0xf800:0xfa00]) == bytes(m.ram[0xf800:0xfa00]), (tokens.hex(), 'LCD transfer')
            domains['pipeline_LCD_transfers'] = domains.get('pipeline_LCD_transfers', 0) + 1

    fixtures = [b'0', b'1', b'1+2', b'1\x4f3', b'3\x4e(4+5)', b'2(3+4)',
                b'6\x4f2(1+2)', b'.5', b'(1+2', b'\x601+2', b'-1+2', b'+1',
                b'1+\x602', b'\x81', b'2\x82', b'1\x743', b'1\x74\x602',
                b'1\x7499', b'1\x74\x6099', b'1.2345678901234567890',
                b'99\x4e99\x4e99\x4f99', b'1+2\x4e3', b'1\x4e2+3',
                b'((1+2)(3+4))', b'2\x81\x82', b'((1+2', b'1-2-3', b'1\x4f2\x4f3']
    for t in fixtures: check(t, 'canonical_grammar')
    for t in [b'1\xae3', b'1\xae2\xae3', b'1\xae2(3+4)', b'2(1\xae3)',
              b'2+1\xae3', b'1\xae2+1', b'1.5\xae10', b'1\xae2.5', b'1\xae\x603',
              b'\x601\xae3', b'2\x4f1\xae3', b'\x989+7)', b'\x989)+7', b'\x989+7',
              b'\x98(9)+7', b'(\x98998)-\x98997))\x4f99']:
        for math_output in (0, 1): check(t, 'rational_and_root_grammar', math_output=math_output)
    for t in [b'', b'.', b'1..2', b'1+', b'1)', b'1\x4f0', b'1\x74200',
              b'1\x74\x60100', b'1\x74', b'1\x74\x60', b'()', b'1++', b'(1+)',
              b'1\xae0', b'\x98\x601)']:
        check(t, 'syntax_and_math_errors', False)
    for exponent in (13, 14, 15, 18):
        for numerator, denominator in [(b'1', b'3'), (b'3', b'1'), (b'\x601', b'3')]:
            t = numerator + b'\x74' + str(exponent).encode() + b'\xae' + denominator + b'\x74' + str(exponent).encode()
            for math_output in (0, 1): check(t, 'fraction_operand_eligibility', math_output=math_output)
    for function in (0xa0, 0xa1, 0xa2):
        for angle in (b'0', b'15', b'30', b'45', b'60', b'90', b'180', b'270', b'360',
                      b'\x6030', b'\x82\x4f6', b'1\xae3', b'\x982)', b'1\x74\x6099', b'1\x7499'):
            for angle_unit in (4, 5, 6):
                for math_output in (0, 1):
                    check(bytes([function]) + angle + b')', 'forward_trigonometry',
                          math_output=math_output, angle_unit=angle_unit)
    for t in (b'\xa030', b'\xa0(30)', b'2\xa030)', b'\xa030)+1', b'\xa0\xa130))',
              b'\xa0\x9830))', b'\xa2\x6090)', b'\xa0)', b'\xa2+)', b'\xa045)\x4e\xa145)'):
        check(t, 'trigonometric_grammar')
    for function in (0xb0, 0xb1, 0xb2):
        for argument in (b'0', b'.5', b'1', b'\x601', b'2', b'\x602', b'1\xae3',
                         b'\x98.5)', b'\x60717\xae3946', b'1\x74\x6099', b'1\x7499'):
            for angle_unit in (4, 5, 6):
                for math_output in (0, 1):
                    check(bytes([function]) + argument + b')', 'inverse_trigonometry',
                          math_output=math_output, angle_unit=angle_unit)
    for t in (b'\xb0.5', b'2\xb0.5)', b'\xb0\xa030))', b'\xa0\xb0.5))',
              b'\xb1\x982)\x4f2)', b'\xb0)', b'\xb2+)', b'\xb2(1+2)', b'\xb2\xb2.1))'):
        check(t, 'inverse_trigonometric_grammar')
    for function in (0x68, 0xa3):
        for argument in (b'0', b'1', b'\x601', b'2', b'10', b'1\xae3', b'\x82',
                         b'\x81', b'\x982)', b'\x98.5)', b'1\x74\x6099', b'1\x7499'):
            for math_output in (0, 1):
                check(bytes([function]) + argument + b')', 'logarithms', math_output=math_output)
    for t in (b'\x6810', b'2\x6810)', b'\xa3\x682))', b'\x68\xa310))',
              b'\x68)', b'\xa3+)', b'\xa3\x81)'):
        check(t, 'logarithmic_grammar')
    for base in (b'0', b'1', b'2', b'10', b'\x602', b'1\xae3', b'\x982)',
                 b'1\x7499', b'1\x74\x6099'):
        for argument in (b'0', b'1', b'8', b'\x608', b'1\xae8', b'\x982)'):
            for math_output in (0, 1):
                check(b'\x68' + base + b',' + argument + b')', 'logarithm_with_base', math_output=math_output)
    for t in (b'\x682,8', b'\x68(1+1),4+4)', b'\x682,8)+1', b'\x68,8)', b'\x682,)',
              b'\x682,,8)', b'\x682,8,4)', b'\x682,8)+', b'\x682,1\x4f0)', b'\xa3,8)', b',', b'1+,'):
        check(t, 'logarithm_with_base_grammar')
    for function in (0x73, 0x93, 0x70, 0x71, 0x72, 0x90, 0x91, 0x92):
        for argument in (b'0', b'1', b'\x601', b'.013', b'.0129999999999999', b'\x60.013',
                         b'.5', b'2', b'\x602', b'1\xae3', b'\x982)',
                         b'1\x74\x6099', b'1\x7499'):
            for math_output in (0, 1):
                check(bytes([function]) + argument + b')', 'exponential_and_hyperbolic', math_output=math_output)
    for t in (b'\x731', b'2\x731)', b'\x70\x901))', b'\xa3\x731))',
              b'\x73\xa31))', b'\x71)', b'\x92+)'):
        check(t, 'exponential_hyperbolic_grammar')
    for angle in (b'0', b'30', b'\x6030', b'\x82', b'1\xae3', b'\x982)', b'1\x74\x6099', b'1\x7499'):
        for unit_token in (0x85, 0x86, 0x87):
            for angle_unit in (4, 5, 6):
                check(angle + bytes([unit_token]), 'angle_unit_postfix', angle_unit=angle_unit)
    for base in (b'0', b'2', b'\x602', b'1\xae3', b'\x982)', b'\x98997)-\x98998)', b'1\x7499', b'1\x74\x6099'):
        for exponent in (b'\x601', b'0', b'2', b'3'):
            check(b'(' + base + b')\x5e(' + exponent + b')', 'verified_fast_powers')
        for postfix in (0x75, 0x76, 0x77):
            check(b'(' + base + b')' + bytes([postfix]), 'power_postfix')
    for t in (b'\x602\x76', b'\x602\x5e2', b'3\xae2\x76', b'3\xae2\x5e2',
              b'2\x5e\x601\x5e2', b'2\x76\x76', b'2\x76\xa030)', b'\xa030)\x76'):
        check(t, 'power_precedence')
    for t in (b'2^3)', b'2^2+1)', b'2^2+1', b'2^(2)+1)', b'2^2)+1', b'2^3)^2)',
              b'3\xae2^2+1)', b'0^\x601)', b'2^)', b'2^2)+'):
        check(t, 'power_implicit_parenthesis')
    for argument in (b'0', b'1', b'8', b'27', b'\x608', b'1\xae8', b'\x982)',
                     b'1\x7499', b'1\x74\x6099'):
        for math_output in (0, 1):
            check(b'\xa8' + argument + b')', 'cube_root', math_output=math_output)
    for degree in (b'0', b'1', b'2', b'3', b'\x601', b'\x603', b'.5', b'2\xae3'):
        for radicand in (b'0', b'1', b'8', b'\x608', b'1\xae8', b'\x982)'):
            for math_output in (0, 1):
                check(b'(' + degree + b')\x9f' + radicand + b')', 'nth_root', math_output=math_output)
    for t in (b'3\x9f8+19)', b'3\x9f8)+19', b'3\x9f(8)+19)', b'\x603\x9f8)',
              b'3\x9f8', b'3\x9f)', b'2\x9f4)\x9f16)', b'2\xa88)', b'\xa8)', b'\xa88)+1'):
        check(t, 'root_grammar')
    for argument in (b'0', b'1', b'3', b'69', b'70', b'\x603', b'1.5', b'1\xae3',
                     b'\x982)', b'1\x7499', b'1\x74\x6099'):
        for postfix in (0x57, 0x25):
            for math_output in (0, 1):
                check(b'(' + argument + b')' + bytes([postfix]), 'factorial_percent', math_output=math_output)
    for n in (b'0', b'5', b'70', b'200', b'\x605', b'1.5', b'1\xae3', b'1\x7410'):
        for r in (b'0', b'2', b'100', b'\x601', b'1.5', b'1\xae3'):
            for operator in (0xbe, 0xbf):
                check(b'(' + n + b')' + bytes([operator]) + r, 'permutations_combinations')
    for t in (b'\x603\x57', b'5\x57^2)', b'5^2)\x57', b'200+10\x25', b'1\xae3\x25',
              b'5\xbe2+1', b'5\xbe2(2)', b'2\x4e5\xbe2', b'\x605\xbe2',
              b'5\xbe2^2)', b'10\xbe3\xae2', b'10\xae2\xbe3', b'5\xbe2\xbf2',
              b'5\xbf2\xbe2', b'5\xbf2(2)', b'5\xbe'):
        check(t, 'combinatorics_precedence')
    power_bases = (b'0', b'1', b'2', b'9', b'.01', b'9999', b'1\x7490',
                   b'1\x74\x6090', b'\x602', b'\x608', b'1\xae3',
                   b'\x601\xae2', b'\x982)', b'\x98998)-\x98997)')
    power_exponents = (b'0', b'1', b'2', b'3', b'4', b'5', b'\x601', b'\x602',
                       b'\x603', b'\x604', b'.5', b'.333333333333333',
                       b'.666666666666667', b'2\xae3', b'\x602\xae3', b'\x982)')
    for base in power_bases:
        for exponent in power_exponents:
            for math_output in (0, 1):
                check(b'(' + base + b')^' + exponent + b')', 'general_real_power', math_output=math_output)
    regression_file = ROOT / 'analysis/c-verification/fixtures/exact-division-regressions.json'
    for row in json.loads(regression_file.read_text())['original_failure_cases']:
        check(bytes.fromhex(row['input']), 'historical_exact_division_regressions')

    def atom():
        n = str(rng.randrange(0, 10000)).encode()
        choice = rng.randrange(7)
        if choice == 0: return n + b'.' + str(rng.randrange(0, 100000)).encode()
        if choice == 1: return n + b'\x74' + (b'\x60' if rng.randrange(2) else b'') + str(rng.randrange(0, 99)).encode()
        if choice == 2: return rng.choice([b'\x81', b'\x82'])
        return n

    def expression(depth):
        if not depth or rng.randrange(3) == 0: return atom()
        left, right = expression(depth-1), expression(depth-1)
        op = rng.choice([b'+', b'-', b'\x4e', b'\x4f'])
        result = b'(' + left + op + right + b')'
        return rng.choice([b'', b'', b'', b'\x60', b'+']) + result

    for _ in range(args.random_cases): check(expression(rng.randrange(1, 4)), 'random_nested_expressions')
    def exact_expression(depth):
        if not depth or rng.randrange(3) == 0:
            if rng.randrange(2): return b'\x98' + str(rng.randrange(1, 1000)).encode() + b')'
            return str(rng.randrange(0, 100)).encode() + b'\xae' + str(rng.randrange(1, 100)).encode()
        left, right = exact_expression(depth-1), exact_expression(depth-1)
        op = rng.choice([b'+', b'-', b'\x4e', b'\x4f'])
        return b'(' + left + op + right + b')'
    for _ in range(args.random_cases): check(exact_expression(rng.randrange(1, 4)), 'random_exact_expressions')
    def mixed_expression(depth):
        if not depth or rng.randrange(3) == 0:
            if rng.randrange(2): return exact_expression(0)
            return (str(rng.randrange(10000)).encode() + b'.' +
                    str(rng.randrange(100000)).encode() + b'\x74\x60' + str(rng.randrange(9)).encode())
        return b'(' + mixed_expression(depth-1) + rng.choice([b'+', b'-', b'\x4e', b'\x4f']) + mixed_expression(depth-1) + b')'
    for _ in range(args.random_cases): check(mixed_expression(rng.randrange(1, 4)), 'random_decimal_exact_interactions')
    for case in range(args.random_cases):
        angle = mixed_expression(rng.randrange(2))
        function = bytes([rng.choice([0xa0, 0xa1, 0xa2])])
        check(function + angle + b')', 'random_trigonometric_expressions',
              math_output=case % 2, angle_unit=4 + case % 3)
    for case in range(args.random_cases):
        argument = mixed_expression(rng.randrange(2))
        function = bytes([rng.choice([0xb0, 0xb1, 0xb2])])
        check(function + argument + b')', 'random_inverse_trigonometric_expressions',
              math_output=case % 2, angle_unit=4 + case % 3)
    for case in range(args.random_cases):
        check(bytes([rng.choice([0x68, 0xa3])]) + mixed_expression(rng.randrange(2)) + b')',
              'random_logarithmic_expressions', math_output=case % 2)
    for case in range(args.random_cases):
        check(bytes([rng.choice([0x73, 0x93, 0x70, 0x71, 0x72, 0x90, 0x91, 0x92])]) +
              mixed_expression(rng.randrange(2)) + b')', 'random_exponential_hyperbolic_expressions', math_output=case % 2)
    # This subset advertises gaps rather than accidentally accepting them.
    for case in range(args.random_cases):
        check(b'(' + mixed_expression(rng.randrange(2)) + b')^' +
              rng.choice(power_exponents) + b')', 'random_general_real_power_expressions', math_output=case % 2)
    for case in range(args.random_cases):
        check(b'\xa8' + mixed_expression(rng.randrange(2)) + b')', 'random_cube_roots', math_output=case % 2)
        check(b'(' + rng.choice([b'2', b'3', b'\x603', b'.5', b'2\xae3']) + b')\x9f' +
              mixed_expression(rng.randrange(2)) + b')', 'random_nth_roots', math_output=case % 2)
        check(b'(' + mixed_expression(rng.randrange(2)) + b')\x25', 'random_percent', math_output=case % 2)
        n, r = rng.randrange(0, 201), rng.randrange(0, 101)
        check(str(n).encode() + bytes([rng.choice([0xbe, 0xbf])]) + str(r).encode(), 'random_combinatorics')
        check(b'\x68' + mixed_expression(rng.randrange(2)) + b',' +
              mixed_expression(rng.randrange(2)) + b')', 'random_logarithm_with_base', math_output=case % 2)
    for tokens in [b'1\x97']:
        tokens += b'\0'; buf = (C.c_uint8 * len(tokens)).from_buffer_copy(tokens); result = EvalResult()
        assert lib.fx_evaluate(buf, len(buf), C.byref(EvalOptions(0xc1, 1, 4)), C.byref(result)) == -1
        domains['explicit_unsupported_contract'] = domains.get('explicit_unsupported_contract', 0) + 1
    if failures:
        failure_path = ROOT / 'analysis/c-verification/eval-mismatches.json'
        failure_path.parent.mkdir(parents=True, exist_ok=True)
        failure_path.write_text(json.dumps(failures, indent=2) + '\n')
        raise AssertionError(json.dumps(failures, indent=2))
    (ROOT / 'analysis/c-verification/eval-mismatches.json').write_text('[]\n')
    report = {'status': 'pass', 'cases': sum(domains.values()), 'domains': domains,
              'rom_sha256': hashlib.sha256(rom).hexdigest(),
              'comparison': 'Native status, both 10-byte numeric records, consumed input pointer, result tokens/kind, measure/draw metrics/cache/framebuffer and LCD transfer.',
              'scope': 'Supported COMP grammar: decimals, e/pi, parentheses, unary signs, arithmetic, implicit multiplication, compact/mixed fractions, square root, general real powers with native implicit exponent parentheses, forward and inverse sin/cos/tan, single/two-argument logarithms and ln, exp/exp10 and forward/inverse hyperbolic functions with Math on/off, cube/nth roots, factorial/percent/nPr/nCr, angle-unit postfix and degrees/radians/gradians. No key UI or unsupported functions.'}
    out = ROOT / 'analysis/c-verification'; out.mkdir(parents=True, exist_ok=True)
    if args.records_only:
        report['comparison'] = 'Native evaluator status, both 10-byte numeric records and consumed input pointer only.'
    report = write_report(out / ('eval-records.json' if args.records_only else 'eval.json'), report,
            implementation_inputs(ROOT, [str(Path('csrc') / f) for f in sources]) +
            ['tools/c_build_inputs.py', 'tools/c_verification.py', 'tools/trace_natural_result.py',
             str(regression_file.relative_to(ROOT))], 'tools/test_eval_c.py')
    print(json.dumps(report, indent=2))


if __name__ == '__main__': main()
