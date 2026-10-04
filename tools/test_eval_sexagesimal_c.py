#!/usr/bin/env python3
"""Verify DMS, scientific constants and unit-conversion expression orchestration."""
import argparse
import ctypes as C
import json
import random
import subprocess
from collections import Counter

from c_build_inputs import implementation_inputs
from c_verification import ROOT, write_report
from nxu8.machine import Machine
from trace_natural_result import settings
from test_eval_variables_c import Number, Options, Result, Variables, SOURCES

FIXTURES = 'analysis/regressions/sexagesimal-expression-grammar.json'


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--random-cases', type=int, default=1000)
    ap.add_argument('--no-report', action='store_true')
    args = ap.parse_args()
    build = ROOT / 'analysis/build/eval-sexagesimal'
    build.mkdir(parents=True, exist_ok=True)
    shared = build / 'eval-sexagesimal.so'
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
        *[str(ROOT / 'csrc' / p) for p in SOURCES], '-o', str(shared)], check=True)
    lib = C.CDLL(str(shared))
    lib.fx_evaluate_with_variables.argtypes = [C.POINTER(C.c_uint8), C.c_size_t,
        C.POINTER(Options), C.POINTER(Variables), C.POINTER(Result)]
    lib.fx_evaluate_with_variables.restype = C.c_int
    oracle = Machine((ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes(), build / 'oracle')
    failures = []
    groups = Counter()
    rng = random.Random(0x5c161ac)

    def check(tokens, group, context=0xc1, exact=1, unit=4, saved=None):
        raw = tokens if tokens.endswith(b'\0') else tokens+b'\0'
        oracle.reset(); settings(oracle)
        oracle.ram[0x80f9] = context; oracle.ram[0x80fc] = 1
        oracle.ram[0x80fa] = 9; oracle.ram[0x8106] = exact; oracle.ram[0x8105] = unit
        for index, byte in enumerate(raw): oracle.ram[0x8200+index] = byte
        oracle.word(0x8190, 0x8200); oracle.er(0, 0x8190); oracle.er(2, 0x8900)
        oracle.call(0x171f4, limit=3000000)
        native_bank = Variables()
        for slot in range(10):
            for part, address in ((0, 0x8226), (1, 0x8408)):
                native_bank.values[slot][part] = Number.from_buffer_copy(
                    bytes(oracle.ram[address+10*slot:address+10*slot+10]))
        expected = [oracle.reg(0), bytes(oracle.ram[0x8900:0x8914]).hex(),
                    oracle.word(0x8190)-0x8200, bytes(native_bank).hex()]
        if saved:
            assert expected[:3] == [saved['native_status'], saved['record20'], saved['consumed']], saved
        buffer = (C.c_uint8*len(raw)).from_buffer_copy(raw)
        bank = Variables(); result = Result()
        status = lib.fx_evaluate_with_variables(buffer, len(raw), C.byref(Options(context, exact, unit)),
                                                C.byref(bank), C.byref(result))
        actual = [status, bytes(result.value).hex(), result.consumed, bytes(bank).hex()]
        assert bytes(buffer) == raw and bytes(oracle.ram[0x8200:0x8200+len(raw)]) == raw
        groups[group] += 1
        if actual != expected:
            failure = {'tokens': raw.hex(), 'group': group, 'context': context, 'exact': exact,
                       'angle_unit': unit, 'expected': expected, 'actual': actual}
            failures.append(failure)
            if len(failures) < 15: print(json.dumps(failure))

    for case in json.loads((ROOT/FIXTURES).read_text())['fixtures']:
        check(bytes.fromhex(case['tokens']), 'saved:'+case['name'], saved=case)
    constants = []
    conversions = []
    rom = (ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    for token in range(256):
        bit = token*12; offset = 0x245a+bit//8
        packed = (rom[offset] | rom[offset+1]<<8) >> (bit%8)
        kind, value = (packed>>8)&15, packed&255
        if kind == 6 and value < 40: constants.append(token)
        if kind == 3 and 55 <= value <= 94: conversions.append(token)
    assert len(constants) == len(conversions) == 40
    dms = [b'1\x5c', b'1\x5c2\x5c', b'1\x5c2\x5c3\x5c', b'1\x5c2', b'1\x5c2\x5c3',
           b'1\x5c2\x5c3\x5c4\x5c', b'1\x5c\x602\x5c', b'1\x5c\x5c', b'1\x5c2\x5c\x5c',
           b'\x601\x5c2\x5c3\x5c', b'1\x5c.5\x5c', b'1\x5c1\x74\x603\x5c',
           b'1\x5c2\xae3\x5c', b'1\x5c2+3\x5c', b'1\x5c(2+3)\x5c', b'1\x5c\x982)\x5c',
           b'1\x5cA', b'1\x5c2\x5c+1', b'1+2\x5c3\x5c', b'(1+2)\x5c',
           b'1\xae2\x5c', b'(1\xae2)\x5c', b'1\xae2\x5c3\x5c', b'1\xae2\x5c0\x5c',
           b'1\xae2\x5c3\x5c4\x5c', b'1\xae2\x5c+3', b'1\xae2\x5c\x75',
           b'1\x5c\xae2', b'1\x5c\xae2\x5c', b'1\xae2\xae3\x5c',
           b'\x601\xae2\x5c', b'\x601\x5c\xae2', b'1\x5c2\x5c\xae3',
           b'1\xae(2\x5c)', b'1\xae2\x5c\x47',
           b'1\xae.5\x5c', b'1\x5c\xae2\xae3', b'1\xae2\x5c\xae3',
           b'(1+2\x80)\xae2\x5c', b'1\xae(2+\x80)\x5c',
           b'(1+2\x80)\xae2\x5c3\x5c', b'\x98(2))\x5c', b'1\x5c3\x47',
           b'\x80\x5c', b'(1+\x80)\x5c', b'(1+\x80)\xa5001', b'\xa030)\x5c']
    for context in (0xc1, 0xc4, 2):
        for exact in (0, 1):
            for tokens in dms:
                check(tokens, 'DMS-grammar', context, exact)
            for token in constants:
                for tokens in (bytes([token]), b'2'+bytes([token]), bytes([token])+b'\x47'):
                    check(tokens, 'constant-admission-and-store', context, exact)
            for token in conversions:
                for tokens in (b'100'+bytes([token]), b'\x60100'+bytes([token]),
                               b'(1+\x80)'+bytes([token]), b'(1\xae2)'+bytes([token])):
                    check(tokens, 'direct-unit-conversions', context, exact)
            for token in (0xd7, 0xfb, 0xfc):
                for left, right in ((b'2\x4e100', b''), (b'2\x4f100', b''),
                    (b'100', b'\x4e2'), (b'1+100', b''), (b'1\xae2', b''),
                    (b'\x60\x60100', b''), (b'\x60100\x75', b''),
                    (b'2\x5e3)', b''), (b'100', b'\x75'),
                    (b'2\x82100', b''), (b'100', b'\x822'), (b'100\x5c', b'')):
                    check(left+bytes([token])+right, 'conversion-precedence', context, exact)
            for code in (b'', b'0', b'00', b'001', b'000', b'040', b'999', b'.01', b'0,1'):
                for prefix in (b'100', b'(1+\x80)'):
                    check(prefix+b'\xa5'+code, 'disabled-dynamic-conversions', context, exact)
    for index in range(args.random_cases):
        context = (0xc1, 0xc4, 2)[index%3]
        count = 1+index%3
        tokens = b''.join((str(rng.randrange(1000))+'.'+str(rng.randrange(1000))).encode()+b'\x5c'
                          for _ in range(count))
        if index%2: tokens = b'\x60'+tokens
        check(tokens, 'random-DMS-components', context, index%2)
        check(b'('+tokens+b')'+bytes([rng.choice(conversions)]), 'random-DMS-conversion', context, index%2)
    data = {'cases':sum(groups.values()), 'groups':dict(groups), 'failures':failures,
        'comparison':'Complete original171F4 status,20-byte result,cursor,all200 variable bytes and immutable input; saved95fixtures independently replayed before C comparison.',
        'scope':'Prepared COMP/CMPLX and DEC BASE-N literal/postfix grammar, all40scientific constants,all40direct conversions and disabled three-digit selectors. Numeric CPU scratch and bus aliases excluded.'}
    if failures:
        (build/'failures.json').write_text(json.dumps(data,indent=2)+'\n')
        raise AssertionError(f'{len(failures)} sexagesimal-expression mismatches')
    if not args.no_report:
        write_report('analysis/c-verification/eval_sexagesimal.json',data,
            implementation_inputs(ROOT,['csrc/'+p for p in SOURCES])+[FIXTURES,
                'tools/test_eval_variables_c.py','tools/test_eval_complex_c.py','tools/trace_natural_result.py',
                'tools/c_build_inputs.py', 'tools/trace_natural_result.py', 'tools/verify_firmware.py', 'tools/nxu8/decoder.py','tools/c_verification.py'], 'tools/test_eval_sexagesimal_c.py')
    print(json.dumps({'status':'pass','cases':data['cases'],'groups':dict(groups)},indent=2))


if __name__ == '__main__': main()
