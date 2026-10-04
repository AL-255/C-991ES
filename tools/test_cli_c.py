#!/usr/bin/env python3
"""Compare the standalone CPU-free C executable's records, tokens and PBM with ROM output."""
import argparse
import ctypes as C
import json
import random
import subprocess

from c_verification import ROOT, write_report
from c_build_inputs import build_inputs
from nxu8.machine import Machine
from trace_natural_result import settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-report', action='store_true')
    options = parser.parse_args()
    build = ROOT / 'analysis/build/c-port'
    subprocess.run(['cmake', '-S', str(ROOT / 'csrc'), '-B', str(build), '-DCMAKE_BUILD_TYPE=Release'], check=True)
    subprocess.run(['cmake', '--build', str(build), '-j4'], check=True)
    executable = build / 'fx991c'
    oracle_dir = ROOT / 'analysis/build/cli/oracle-calculus'
    oracle_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
                    str(ROOT / 'tools/nxu8/calculus_expression_events.c'),
                    str(ROOT / 'tools/nxu8/vendor/SimU8/core.c'),
                    '-o', str(oracle_dir / 'nxu8-harness.so')], check=True)
    m = Machine((ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes(), oracle_dir)
    m.lib.calculus_expression_call.argtypes = [C.c_uint32, C.c_uint64, C.c_uint]
    rng = random.Random(0xb070)
    inputs = [bytes.fromhex('2898393938292d9839393729294f3939'), b'6\x4f2(1+2)',
              b'1\xae3', b'1\x4f3', b'1\xae2\xae3', b'\x81', b'\x82', b'\x98998)',
              b'0', b'1\x7499', b'1\x74\x6099', b'\xa030)', b'\xa045)', b'\xa215)',
              b'\xa030)+\xa160)', b'\xa045)\x4e\xa145)', b'\xa0\x982))',
              b'2^3', b'2^\x601', b'2^4)', b'2^3+1)', b'(\x608)^2\xae3)',
              b'(1\xae3)^5)', b'\x982)\x75', b'2\x76', b'3\xae2^2', b'30\x86',
              b'\xb0.5)', b'\xb1.5)', b'\xb21)', b'\xa0\xb0.5))', b'\xb0\x98.5))',
              b'\x6810)', b'\xa3\x81)', b'\xa3\x98.5))']
    inputs += [b'\x731)', b'\x93\x602)', b'\x70.5)', b'\x71.5)', b'\x72.5)',
               b'\x90.5)', b'\x912)', b'\x92.5)', b'\xa3\x731))']
    inputs += [b'\xa88)', b'\xa8\x608)', b'3\x9f8)', b'3\x9f8+19)', b'2\x9f2)',
               b'5\x57', b'10\x25', b'5\xbe2', b'5\xbf2', b'\x682,8)', b'\x68(1+1),4+4)']
    inputs += [b'A', b'3\x47', b'\x88\x602)', b'\x63\x602)', b'\xc3\x602)',
               b'\x69X,1,3)', b'\x5dX,1,3)', b'\x69\x98X),1,3)',
               b'\x69X\x75,1,3)', b'\x5d\x88X),1,4)']
    inputs += [b'\x6aX,0,1)', b'\x6aX,1,0)', b'\x6aX\x75,0,1)',
               b'\x6a\x98X),0,1)', b'\x6a\xa0X),0,90)', b'\x6aX,0,1,.01)',
               b'\x6bX,1)', b'\x6bX\x75,3)', b'\x6bX\x76,2)',
               b'\x6b\x98X),1)', b'\x6b\xa0X),30)', b'\x6bX,1,.01)']
    for _ in range(100):
        a, b, c = (str(rng.randrange(1, 100)).encode() for _ in range(3))
        inputs.append(b'(' + a + b'\xae' + b + b'-\x98' + c + b'))')
    pbm = ROOT / 'analysis/c-verification/cli-last.pbm'
    display_inputs = [b'1+2', b'\x98\xb82\xb9', b'2^\xb83\xb9', b'2^\xb84+1\xb9',
                      b'\xae\xbb\xb81\xb9\xb83\xb9\xbc',
                      b'\x7c\xbd\xbb\xb82\xb9\xb81\xb9\xb83\xb9\xbc',
                      b'\xa030)', b'\xb0.5)', b'\xa32)',
                      b'\x73\xb81\xb9', b'\x93\xb82\xb9', b'\x70.5)',
                      b'\x90.5)', b'\x98\xb8\xae\xbb\xb81\xb9\xb82\xb9\xbc\xb9',
                      b'\xae\xbb\xb8(\x98\xb8998\xb9-\x98\xb8997\xb9)\xb9\xb899\xb9\xbc']
    display_inputs += [b'\x9f\xbb\xb83\xb9\xb88\xb9\xbc', b'\x68\xb82\xba8\xb9',
                       b'\xa88)', b'5\x57', b'5\xbf2', b'10\x25']
    display_inputs += [b'\x6a\xb8X\xba0\xba1\xb9', b'\x6b\xb8X\x75\xba3\xb9']
    complex_inputs = [b'\x80', b'2\x80', b'1+2\x80', b'\x601-\x80',
                      b'\x98\x601)', b'\x98\x602)', b'(1+2\x80)(3+4\x80)',
                      b'(1+\x80)\x4f(2+\x80)', b'(1+\x80)\xae(2+\x80)',
                      b'1\xae2\x80', b'\x88(3+4\x80))', b'\xc3(3+4\x80))',
                      b'\x63(3+4\x80))', b'(1+\x80)^3)', b'\x80^\x601)',
                      b'\x80\x75', b'\x80\x76', b'\x80\x77', b'\x80-\x80',
                      b'\x982)+\x983)\x80', b'\x82+\x81\x80', b'\x68(1+1),8)', b'5\xbf2']
    for _ in range(100):
        values = [str(rng.randrange(1, 30)).encode() for _ in range(4)]
        a, b, c, d = values
        complex_inputs.append(b'(' + a + b'+' + b + b'\x80)' + rng.choice([b'+', b'-', b'\x4e', b'\x4f']) +
                              b'(' + c + b'+' + d + b'\x80)')
    cases = [(tokens, None, False) for tokens in inputs]
    cases += [(tokens, None, True) for tokens in complex_inputs]
    complex_displays = [b'1+2\x80', b'\x98\xb8\x601\xb9',
                        b'\xae\xbb\xb8(1+\x80)\xb9\xb8(2+\x80)\xb9\xbc',
                        b'(1+\x80)^\xb83\xb9']
    for display, complex_mode in [(d, False) for d in display_inputs] + [(d, True) for d in complex_displays]:
        m.reset(); settings(m)
        if complex_mode: m.ram[0x80f9] = 0xc4
        m.word(0x812c, 0x8154)
        for i, byte in enumerate(display + b'\0\0'): m.ram[0x8154+i] = byte
        m.er(0, 0x8154); m.call(0x9ee4); assert m.reg(0) == 1, display.hex()
        m.er(0, 0x8154); m.er(2, 0x8200); m.ram[0x8dee] = 0; m.ram[0x8df0] = 1
        m.call(0x9ff2)
        raw = bytes(m.ram[0x8200:0x8400]).split(b'\0', 1)[0]
        cases.append((raw, display, complex_mode))
    def prepare(complex_mode):
        m.reset(); settings(m)
        if complex_mode:
            for address, value in ((0x80f9, 196), (0x80fc, 1), (0x8104, 1), (0x8105, 4), (0x8108, 1)):
                m.ram[address] = value

    def evaluate(tokens):
        if not any(token in (0x5d, 0x69, 0x6a, 0x6b) for token in tokens):
            m.call(0x171f4)
            return
        # The compiled adapter answers5550/5564 without skipping an opcode.
        status = m.lib.calculus_expression_call(0x171f4, 200000000, 0)
        assert status == 100, (tokens.hex(), status, hex(m.lib.harness_get_pc()))

    for tokens, display, complex_mode in cases:
        prepare(complex_mode)
        for i, b in enumerate(tokens + b'\0'): m.ram[0x8200+i] = b
        m.word(0x8190, 0x8200); m.er(0, 0x8190); m.er(2, 0x8300); evaluate(tokens)
        assert m.reg(0) == 0, tokens.hex()
        expected_record = bytes(m.ram[0x8300:0x8314]).hex()
        expected_consumed = m.word(0x8190) - 0x8200
        m.call(0xc034)
        # Compare the standalone formatter alphabet separately from B070's
        # alternate raw-character alphabet used for scientific suffixes.
        m.er(0, 0x8300); m.er(2, 0x8500); m.word(0x8dee, 0); m.call(0xc060)
        expected_tokens = bytes(m.ram[0x8500:0x8700]).split(b'\0', 1)[0].hex()
        # Recreate native evaluation context, since isolated formatting writes
        # numeric scratch that is not part of the ordinary controller entry.
        prepare(complex_mode)
        for i, b in enumerate(tokens + b'\0'): m.ram[0x8200+i] = b
        m.word(0x8190, 0x8200); m.er(0, 0x8190); m.er(2, 0x8300); evaluate(tokens)
        m.call(0xc034); m.er(0, 0x8300); m.call(0xb070); m.call(0x3cfc)
        frame = b''.join(bytes(m.ram[0xf800+16*y:0xf80c+16*y]) for y in range(32))
        if complex_mode:
            expected_kind = m.ram[0x8100] >> 4
            expected_tokens = bytes(m.ram[0x8398:0x8798]).split(b'\0', 1)[0].hex()
        argument, provided = ('--eval', tokens) if display is None else ('--display', display)
        flags = ['--complex'] if complex_mode else []
        actual = json.loads(subprocess.run([str(executable), argument, provided.hex(), *flags, '--pbm', str(pbm)],
                                          check=True, capture_output=True, text=True).stdout)
        if display is not None:
            assert actual['conversion_status'] == 0 and actual['input_tokens'] == tokens.hex(), (display.hex(), actual)
        assert actual['eval_status'] == actual['format_status'] == actual['bitmap_status'] == 0
        assert (actual['record'], actual['consumed'], actual['tokens']) == (
                expected_record, expected_consumed, expected_tokens), (tokens.hex(), actual)
        if complex_mode: assert actual['kind'] == expected_kind
        assert pbm.read_bytes() == b'P4\n96 32\n' + frame, (tokens.hex(), 'standalone C PBM differs')
    for args in [[], ['--eval', 'z'], ['--eval', '0'], ['--format', 'ff'], ['--token', '100'],
                 ['--token', 'xyz'], ['--eval', '31', '--unknown'], ['--format', '0'*20, '--unknown']]:
        assert subprocess.run([str(executable), *args], capture_output=True).returncode == 2, args
    evaluator_errors = [(b'1+', 2, False), (b'1\x4f0', 3, False), (b'1\x97', -1, False),
                        (b'\x80+', 2, True), (b'\x80\x57', 3, True),
                        (b'\xa0\x80)', 3, True), (b'(1+\x80)\x4f0', 3, True)]
    for tokens, status, complex_mode in evaluator_errors:
        flags = ['--complex'] if complex_mode else []
        proc = subprocess.run([str(executable), '--eval', tokens.hex(), *flags], capture_output=True, text=True)
        result = json.loads(proc.stdout)
        assert proc.returncode == 1 and result['eval_status'] == status
        if complex_mode:
            prepare(True)
            for index, byte in enumerate(tokens+b'\0'): m.ram[0x8200+index] = byte
            m.word(0x8190, 0x8200); m.er(0, 0x8190); m.er(2, 0x8300); m.call(0x171f4)
            assert (result['eval_status'], result['record'], result['consumed']) == (
                m.reg(0), bytes(m.ram[0x8300:0x8314]).hex(), m.word(0x8190)-0x8200)
    boundary_errors = [b'\x98\xb8(2\xb9', b'\x98\xb82)\xb9', b'\x98\xb81,2\xb9']
    for display in boundary_errors:
        m.reset(); settings(m); m.word(0x812c, 0x8154)
        for i, byte in enumerate(display+b'\0'): m.ram[0x8154+i] = byte
        m.er(0, 0x8154); m.call(0x9ee4); assert m.reg(0) == 0
        actual = subprocess.run([str(executable), '--display', display.hex()], capture_output=True, text=True)
        assert actual.returncode == 1 and json.loads(actual.stdout) == {
            'conversion_status': 2, 'display_cursor': m.ram[0x8114]}
    assert subprocess.run([str(executable), '--display', '31'*100], capture_output=True).returncode == 2
    mapped_errors = [(b'\x98\xb8\x601\xb9', False), (b'0^\xb8\x601\xb9', False),
                     (b'\xae\xbb\xb81\xb9\xb80\xb9\xbc', False), (b'\xa0+)', False),
                     (b'\x98\xb81+\x80\xb9', True), (b'\x80\x57', True)]
    for display, complex_mode in mapped_errors:
        prepare(complex_mode); m.word(0x812c, 0x8154)
        for i, byte in enumerate(display+b'\0\0'): m.ram[0x8154+i] = byte
        m.er(0, 0x8154); m.er(2, 0x8200); m.ram[0x8dee] = 0; m.ram[0x8df0] = 1; m.call(0x9ff2)
        m.word(0x8190, 0x8200); m.er(0, 0x8190); m.er(2, 0x8400); m.call(0x171f4)
        expected_status = m.reg(0); consumed = m.word(0x8190)-0x8200
        assert expected_status in (2, 3)
        m.er(0, 0x8154); m.er(2, 0x8600); m.ram[0x8dee] = consumed; m.ram[0x8df0] = 0; m.call(0x9ff2)
        flags = ['--complex'] if complex_mode else []
        actual = subprocess.run([str(executable), '--display', display.hex(), *flags], capture_output=True, text=True)
        result = json.loads(actual.stdout)
        assert actual.returncode == 1 and (result['eval_status'], result['consumed'], result['display_cursor']) == (
            expected_status, consumed, m.ram[0x8114]), (display.hex(), result, m.ram[0x8114])
    sources = build_inputs(ROOT)
    data = {
        'cases': len(cases) + 9 + len(evaluator_errors) + len(boundary_errors) + len(mapped_errors), 'successful_expression_PBM_cases': len(cases),
        'complex_expression_PBM_cases': len(complex_inputs) + len(complex_displays),
        'natural_input_conversion_cases': len(display_inputs) + len(complex_displays), 'natural_boundary_error_cases': len(boundary_errors),
        'natural_evaluator_error_cursor_cases': len(mapped_errors),
        'invalid_argument_cases': 9, 'evaluator_error_cases': len(evaluator_errors),
        'comparison': 'Standalone executable JSON status,20-byte record,consumed pointer,formatter tokens and all96x32 PBM pixels versus original171F4/C034/C060/B070/3CFC.',
        'scope': 'Prepared ordinary Math COMP and rectangular CMPLX contexts, including structured input; no reset/key UI or other modes'}
    report = data if options.no_report else write_report('analysis/c-verification/cli.json', data,
        sources + ['tools/c_build_inputs.py', 'tools/c_verification.py', 'tools/trace_natural_result.py',
                   'tools/nxu8/calculus_expression_events.c'], 'tools/test_cli_c.py')
    print(json.dumps({k: v for k, v in report.items() if k != 'tested_inputs_sha256'}, indent=2))


if __name__ == '__main__': main()
