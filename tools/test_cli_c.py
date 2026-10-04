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


def paired_cli_cases(m, executable, pbm, rng):
    """Retain171F4's raw result and derive presentation policy through F12A.

    The CLI exports a fresh result-only bitmap. F12A first establishes the
    native status labels and local70-sentinel cleanup; a separate zero-RAM
    B070/37BC call then renders those flags without editor pixels. All expected
    records, labels, tokens and pixels come from unchanged original ROM calls.
    """
    controls = [b'\x6c3,4)', b'\x6c\x603,4)', b'\x6c3,\x604)',
                b'\x6c\x603,\x604)', b'\x6c0,0)', b'\x6c0,1)', b'\x6c1,0)',
                b'\x6c1\xae3,1\xae2)', b'\x6c\x982),1)',
                b'\x6d2,30)', b'\x6d\x602,30)', b'\x6d2,\x6030)',
                b'\x6d0,30)', b'\x6d1\xae2,30)', b'\x6d2,90)', b'\x6d2,180)',
                b'(\x6c3,4))', b'(\x6d2,30))', b'\x6c3,4)+1',
                b'\x60\x6d2,30)', b'\x6c3,4)\x47', b'\x6d2,30)\x47',
                b'\x6c3,4)\x75', b'\x6c\x6d2,30),4)', b'\x6c1,1)\x5f1',
                b'10\x5f3', b'0\x5f3', b'10\x5f5', b'10\x5f0',
                b'\x6010\x5f3', b'10\x5f\x603', b'1\xae2\x5f1\xae3',
                b'10\x5f\x983)', b'10\x5f\x6c1,1)', b'(10\x5f3)',
                b'10\x5f3+1', b'10\x5f3\x47', b'10\x5f3\x75']

    def signed(value):
        return (b'\x60' if value < 0 else b'') + str(abs(value)).encode()

    random_controls = []
    for _ in range(24):
        x, y = rng.randrange(-99, 100), rng.randrange(-99, 100)
        radius, angle = rng.randrange(0, 100), rng.randrange(-360, 361)
        numerator, denominator = rng.randrange(-999, 1000), rng.randrange(1, 100)
        random_controls.extend([b'\x6c' + signed(x) + b',' + signed(y) + b')',
                                b'\x6d' + signed(radius) + b',' + signed(angle) + b')',
                                signed(numerator) + b'\x5f' + signed(denominator)])
    cases = [(tokens, mode, None, None) for mode in (193, 196)
             for tokens in controls + random_controls]
    for base, name in ((1, 'bin'), (7, 'oct'), (9, 'dec'), (15, 'hex')):
        cases.extend((tokens, 2, name, None) for tokens in
                     (b'\x5110\x5f\x513', b'\x60\x5110\x5f\x513',
                      b'\x510\x5f\x513', b'\x5110\x5f\x515'))

    def put(address, data):
        for offset, byte in enumerate(data):
            m.ram[address + offset] = byte

    structured = [b'\x6c3,4)', b'\x6d2,30)',
                  b'\x6c\xae\xbb\xb81\xb9\xb82\xb9\xbc,4)', b'10\x5f3',
                  b'\xae\xbb\xb81\xb9\xb82\xb9\xbc\x5f\xae\xbb\xb81\xb9\xb83\xb9\xbc']
    for mode in (193, 196):
        for display in structured:
            m.reset(); settings(m); m.ram[0x80f9] = mode
            put(0x8154, display + b'\0\0'); m.word(0x812c, 0x8154)
            m.er(0, 0x8154); m.call(0x9ee4)
            assert m.reg(0) == 1, (display.hex(), mode, 'native input boundary')
            m.er(0, 0x8154); m.er(2, 0x8200); m.word(0x8dee, 0); m.ram[0x8df0] = 1
            m.call(0x9ff2)
            tokens = bytes(m.ram[0x8200:0x8400]).split(b'\0', 1)[0]
            cases.append((tokens, mode, None, display))

    def evaluate_context(tokens, mode, radix, screen):
        m.reset()
        for address, value in ((0x80f9, mode), (0x80fa, radix if mode == 2 else 1),
                               (0x80fc, screen), (0x80fe, 1), (0x80f5, 240),
                               (0x80f7, 1), (0x8104, 1), (0x8105, 4),
                               (0x8106, 1), (0x8108, 1), (0x8121, 1),
                               (0x8117, 1), (0x8119, 1), (0x811a, 124),
                               (0x811b, 10), (0x811c, 1), (0x811d, 1),
                               (0x811e, 1), (0x811f, 10)):
            m.ram[address] = value
        put(0x8600, tokens + b'\0\0'); put(0x8154, tokens + b'\0\0')
        m.word(0x812c, 0x8154)
        # Six original startup pointers, including the special-function table.
        put(0x8dee, m.rom[0x1f8dc:0x1f8ee])
        put(0x8140, bytes.fromhex('09000000000000000001') + bytes(10))

    def full_commit(tokens, mode, radix):
        evaluate_context(tokens, mode, radix, 17 if mode == 2 else 1)
        m.word(0x9300, 0x8154); m.word(0x9302, 0x8140)
        for offset, value in ((4, 1), (6, mode), (8, 1 if mode & 128 else 0),
                              (9, 1 if mode & 64 else 0), (10, 0)):
            m.ram[0x9300 + offset] = value
        m.er(0, 0x9300)
        # Answer the native timer poll through the existing passive adapter;
        # every original instruction still executes.
        stop = m.lib.calculus_expression_call(0x1f12a, 20000000, 0)
        assert stop == 100 and m.reg(0) == (0 if mode == 2 else 2), (
            tokens.hex(), mode, stop, m.reg(0))
        return m.ram[0x80ff], m.ram[0x8101], bytes(m.ram[0x8140:0x8154])

    counts = {'cases': len(cases), 'successful_PBM_cases': 0, 'error_cases': 0,
              'no_PBM_cases': 0, 'F12A_commit_calls': 0, 'native_calls': len(structured) * 4,
              'COMP_paired_cases': 0, 'CMPLX_coordinate_cases': 0,
              'BASE_Qrem_cases': 0, 'sentinel_scalar_cases': 0,
              'CMPLX_PBM_cases': 0, 'natural_input_conversion_cases': len(structured) * 2,
              'random_expression_cases': len(random_controls) * 2}
    for tokens, mode, base_name, display in cases:
        radix = {'bin': 1, 'oct': 7, 'dec': 9, 'hex': 15}.get(base_name, 9)
        evaluate_context(tokens, mode, radix, 1)
        m.word(0x8190, 0x8600); m.er(0, 0x8190); m.er(2, 0x8300)
        m.call(0x171f4, limit=20000000); counts['native_calls'] += 1
        status = m.reg(0)
        raw_record = bytes(m.ram[0x8300:0x8314])
        consumed = m.word(0x8190) - 0x8600
        flags = ['--complex'] if mode == 196 else ['--base', base_name] if mode == 2 else []
        if status not in (0, 34, 35, 37):
            proc = subprocess.run([str(executable), '--eval', tokens.hex(), *flags],
                                  capture_output=True, text=True)
            actual = json.loads(proc.stdout)
            assert proc.returncode == 1 and (
                actual['eval_status'], actual['record'], actual['consumed']) == (
                status, raw_record.hex(), consumed), (tokens.hex(), mode, actual)
            counts['error_cases'] += 1
            continue

        flag_byte, complex_override, committed = full_commit(tokens, mode, radix)
        counts['native_calls'] += 1; counts['F12A_commit_calls'] += 1
        local_record = bytearray(raw_record)
        if status == 37 and raw_record[10] == 0x70:
            local_record[10:] = bytes(10)
            counts['sentinel_scalar_cases'] += 1
        if mode == 2:
            assert flag_byte == 0 and committed == raw_record[:10] + bytes(10)
            counts['BASE_Qrem_cases'] += 1
        else:
            assert committed == bytes(local_record), (tokens.hex(), mode, 'native commit changed value')
            if status in (34, 35):
                if mode == 196:
                    assert (flag_byte, complex_override) == (0, 2 if status == 34 else 1)
                    counts['CMPLX_coordinate_cases'] += 1
                else:
                    assert (flag_byte, complex_override) == (18 if status == 34 else 17, 0)
            if status == 37:
                assert flag_byte == (0 if raw_record[10] == 0x70 else 20)
            if mode == 193 and flag_byte & 16:
                counts['COMP_paired_cases'] += 1

        # Match the CLI's fresh result-only framebuffer, not F12A's editor row.
        m.reset()
        for address, value in ((0x80f9, mode), (0x80f5, 240), (0x8106, 1),
                               (0x8100, 13), (0x8121, 1),
                               (0x80ff, flag_byte), (0x8101, complex_override)):
            m.ram[address] = value
        if mode == 196 or status != 0:
            for address, value in ((0x80fc, 1), (0x8104, 1), (0x8105, 4),
                                   (0x8108, 1), (0x811f, 10)):
                m.ram[address] = value
        if mode == 2:
            m.ram[0x80fa] = radix; m.ram[0x811f] = 10
        put(0x8200, tokens + b'\0'); put(0x8300, local_record); m.word(0x812c, 0x8200)
        m.call(0xc034); m.er(0, 0x8300)
        m.call(0x37bc if mode == 2 else 0xb070, limit=20000000)
        m.call(0x3cfc); counts['native_calls'] += 3
        expected_pbm = b'P4\n96 32\n' + b''.join(
            bytes(m.ram[0xf800+16*y:0xf80c+16*y]) for y in range(32))
        persistent_tokens = bytes(m.ram[0x8398:0x8798]).split(b'\0', 1)[0].hex()
        expected_kind = m.ram[0x8100] >> 4
        if mode == 196 or (mode == 193 and flag_byte & 16):
            expected_tokens = persistent_tokens
        else:
            # Preserve the existing ordinary COMP isolated formatter alphabet,
            # including37/70 scalar fallback, and BASE's radix formatter.
            m.reset(); settings(m); put(0x8300, raw_record)
            if mode == 2:
                m.ram[0x80f9] = 2; m.ram[0x80fa] = radix
                m.er(0, 0x8300); m.er(2, 0x8500); m.call(0x158b8)
                expected_kind = 0; counts['native_calls'] += 1
            else:
                m.call(0xc034); m.er(0, 0x8300); m.er(2, 0x8500)
                m.word(0x8dee, 0); m.call(0xc060)
                expected_kind = m.reg(0); counts['native_calls'] += 2
            expected_tokens = bytes(m.ram[0x8500:0x8700]).split(b'\0', 1)[0].hex()
        for with_pbm in (True, False):
            command = [str(executable), '--eval' if display is None else '--display',
                       tokens.hex() if display is None else display.hex(), *flags]
            if with_pbm:
                command += ['--pbm', str(pbm)]
            proc = subprocess.run(command, capture_output=True, text=True)
            actual = json.loads(proc.stdout)
            if display is not None:
                assert (actual['conversion_status'], actual['input_tokens']) == (0, tokens.hex()), (
                    display.hex(), mode, actual)
            assert proc.returncode == 0 and (
                actual['eval_status'], actual['format_status'], actual['bitmap_status'],
                actual['record'], actual['consumed'], actual['tokens'], actual['kind']) == (
                status, 0, 0, raw_record.hex(), consumed, expected_tokens, expected_kind), (
                tokens.hex(), mode, with_pbm, actual, expected_tokens, expected_kind)
            if with_pbm:
                assert pbm.read_bytes() == expected_pbm, (tokens.hex(), mode, 'paired CLI pixels')
                counts['successful_PBM_cases'] += 1
                if mode == 196:
                    counts['CMPLX_PBM_cases'] += 1
            else:
                counts['no_PBM_cases'] += 1
    return counts


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
    base_inputs = [b'0', b'1', b'1+1', b'(\x513+\x514)\x4e\x512',
                   b'(\x519-\x511)\x4f\x513', b'\x61\x515)', b'\x62\x515)',
                   b'\x515\x6f\x512', b'\x515\x6e\x513', b'\x515\x7e\x512',
                   b'\x515\x7f\x512', b'\x50'+b'\xbd'*8, b'\x53'+b'1'+b'0'*15,
                   b'\x5237777777777', b'\x5112', b'\x511\xae\x512',
                   b'\x511\xae\x511\xae\x512', b'\x98\x512)', b'A', b'\x513\x47']
    base_cases = 0
    for base, name in ((1, 'bin'), (7, 'oct'), (9, 'dec'), (15, 'hex')):
        for tokens in base_inputs:
            def prepare_base():
                prepare(False)
                m.ram[0x80f9] = 2; m.ram[0x80fa] = base
                for i, byte in enumerate(tokens+b'\0'): m.ram[0x8200+i] = byte
                m.word(0x8190, 0x8200); m.er(0, 0x8190); m.er(2, 0x8300)
                m.call(0x171f4)
            prepare_base()
            assert m.reg(0) == 0, (name, tokens.hex(), m.reg(0))
            expected_record = bytes(m.ram[0x8300:0x8314]).hex()
            expected_consumed = m.word(0x8190)-0x8200
            m.er(0, 0x8300); m.er(2, 0x8500); m.call(0x158b8)
            expected_tokens = bytes(m.ram[0x8500:0x8600]).split(b'\0', 1)[0].hex()
            prepare_base()
            for address, value in ((0x80f5, 0xf0), (0x8100, 13), (0x811f, 10), (0x8121, 1)):
                m.ram[address] = value
            m.er(0, 0x8300); m.call(0x37bc); m.call(0x3cfc)
            frame = b''.join(bytes(m.ram[0xf800+16*y:0xf80c+16*y]) for y in range(32))
            actual = json.loads(subprocess.run([str(executable), '--eval', tokens.hex(), '--base', name,
                '--pbm', str(pbm)], check=True, capture_output=True, text=True).stdout)
            assert (actual['eval_status'], actual['format_status'], actual['bitmap_status'], actual['kind']) == (0, 0, 0, 0)
            assert (actual['record'], actual['consumed'], actual['tokens']) == (
                expected_record, expected_consumed, expected_tokens), (name, tokens.hex(), actual)
            assert pbm.read_bytes() == b'P4\n96 32\n' + frame, (name, tokens.hex(), 'BASE-N result pixels')
            base_cases += 1
    invalid_arguments = [[], ['--eval', 'z'], ['--eval', '0'], ['--format', 'ff'], ['--token', '100'],
                 ['--token', 'xyz'], ['--eval', '31', '--unknown'], ['--format', '0'*20, '--unknown'],
                 ['--eval', '31', '--base'], ['--eval', '31', '--base', '3'],
                 ['--eval', '31', '--base', 'hex', '--complex'],
                 ['--eval', '31', '--complex', '--base', 'hex'], ['--display', '31', '--base', 'dec']]
    for args in invalid_arguments:
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
    paired = paired_cli_cases(m, executable, pbm, rng)
    sources = build_inputs(ROOT)
    data = {
        'cases': len(cases) + base_cases + len(invalid_arguments) + 1 + len(evaluator_errors) + len(boundary_errors) + len(mapped_errors) + paired['cases'] + paired['no_PBM_cases'],
        'successful_expression_PBM_cases': len(cases) + base_cases + paired['successful_PBM_cases'],
        'base_expression_PBM_cases': base_cases + paired['BASE_Qrem_cases'],
        'complex_expression_PBM_cases': len(complex_inputs) + len(complex_displays) + paired['CMPLX_PBM_cases'],
        'natural_input_conversion_cases': len(display_inputs) + len(complex_displays) + paired['natural_input_conversion_cases'], 'natural_boundary_error_cases': len(boundary_errors),
        'natural_evaluator_error_cursor_cases': len(mapped_errors),
        'invalid_argument_cases': len(invalid_arguments) + 1, 'evaluator_error_cases': len(evaluator_errors),
        'paired_coordinate_Qrem': paired,
        'comparison': 'Standalone executable JSON status,20-byte record,consumed pointer,formatter tokens and all96x32 PBM pixels versus original171F4/F12A/C034/C060/B070/158B8/37BC/3CFC. Paired tokens are checked both with and without PBM export.',
        'scope': 'Prepared ordinary Math COMP and CMPLX contexts including structured input, successful34Pol/35Rec/37Qrem status labels and70-sentinel scalar fallback; BASE-N raw grammar plus radix token formatting and fixed-row display precedence. F12A supplies native presentation policy; fresh result-only displays exclude editor pixels. No reset/key UI.'}
    report = data if options.no_report else write_report('analysis/c-verification/cli.json', data,
        sources + ['tools/c_build_inputs.py', 'tools/c_verification.py', 'tools/trace_natural_result.py',
                   'tools/nxu8/calculus_expression_events.c'], 'tools/test_cli_c.py')
    print(json.dumps({k: v for k, v in report.items() if k != 'tested_inputs_sha256'}, indent=2))


if __name__ == '__main__': main()
