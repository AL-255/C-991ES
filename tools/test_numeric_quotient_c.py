#!/usr/bin/env python3
"""Live original-ROM comparison of the prepared 1C138 quotient wrapper."""
import argparse
import ctypes as C
import json
from pathlib import Path
import random
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT / 'tools'))
from c_verification import write_report

SOURCES = ['csrc/numeric/fx_quotient_remainder.c', 'csrc/numeric/fx_numeric.c',
           'csrc/numeric/fx_raw_decimal_parts.c', 'csrc/numeric/fx_raw_decimal_divide.c',
           'csrc/numeric/fx_raw_decimal_multiply_add.c', 'csrc/numeric/fx_raw_fraction_convert.c']
HEADERS = [p[:-2] + '.h' for p in SOURCES]
HELPER = 'tools/nxu8/quotient_host_events.c'
REGRESSIONS = 'csrc/numeric/quotient/regressions.json'

class Number(C.Structure):
    _fields_ = [('bytes',C.c_uint8 * 10)]

class Result(C.Structure):
    _fields_ = [('quotient',Number), ('remainder',Number), ('firmware_status',C.c_uint8)]

class Rational(C.Structure):
    _fields_ = [('numerator',C.c_int64), ('denominator',C.c_uint64), ('flags',C.c_uint8)]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--random-cases',type=int,default=6000,
                        help='Cases per finite-boundary group; default retains the complete independent corpus')
    parser.add_argument('--no-report',action='store_true')
    args = parser.parse_args()
    if args.random_cases < 0: parser.error('--random-cases must be nonnegative')
    build = ROOT / 'analysis/build/numeric/quotient'; build.mkdir(parents=True,exist_ok=True)
    library = build / 'quotient.so'
    subprocess.run(['gcc','-std=c99','-O3','-Wall','-Wextra','-Werror','-pedantic',
                    '-shared','-fPIC',*(str(ROOT / p) for p in SOURCES),'-o',str(library)],check=True)
    lib = C.CDLL(str(library))
    lib.fx_number_quotient_remainder.argtypes = [C.c_void_p] * 3
    lib.fx_decimal_parse.argtypes = [C.POINTER(Number),C.c_char_p]
    lib.fx_rational_encode.argtypes = [C.POINTER(Number),C.POINTER(Rational)]
    lib.fx_surd_pack.argtypes = [C.POINTER(Number),C.POINTER(Number)]
    oracle_library = build / 'oracle.so'
    subprocess.run(['gcc','-std=c99','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',
                    str(ROOT / HELPER),str(ROOT / 'tools/nxu8/vendor/SimU8/core.c'),
                    '-o',str(oracle_library)],check=True)
    oracle = C.CDLL(str(oracle_library))
    oracle.harness_init.argtypes = [C.c_void_p,C.c_size_t]
    oracle.harness_ram.restype = C.POINTER(C.c_uint8 * 65536)
    oracle.harness_set_reg.argtypes = [C.c_uint,C.c_uint8]
    oracle.quotient_wrapper_call.argtypes = [C.c_uint64]
    rom = (ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    rom_buffer = C.create_string_buffer(rom)
    groups, failures, outcomes, native_branches = {}, [], {}, {}
    native_calls = 0
    normalized_truncation_samples = 0

    def number(text):
        if isinstance(text,bytes): return text
        result = Number()
        assert lib.fx_decimal_parse(C.byref(result),str(text).encode()) == 0
        return bytes(result.bytes)
    def rational(n,d,marker=0):
        result = Number(); value = Rational(n,d,marker)
        assert lib.fx_rational_encode(C.byref(result),C.byref(value)) == 0
        return bytes(result.bytes)
    def surd(coefficient,radicand,denominator,coefficient2=0,radicand2=0,denominator2=1):
        components = (Number * 6)(*[Number.from_buffer_copy(number(x)) for x in
                     (coefficient,radicand,denominator,coefficient2,radicand2,denominator2)])
        result = Number()
        status = lib.fx_surd_pack(C.byref(result),components)
        return bytes(result.bytes) if status == 0 else None
    def check(group,actual,expected,detail):
        groups[group] = groups.get(group,0) + 1
        if actual != expected:
            failures.append(dict(group=group,actual=actual,expected=expected,fixture=detail))
            if len(failures) <= 20: print(json.dumps(failures[-1]))
    def native(a,b,math=1,context=0xc1,screen=1,reset=True,poison=None):
        nonlocal native_calls
        if reset: oracle.harness_init(rom_buffer,len(rom))
        ram = oracle.harness_ram().contents
        if poison is not None:
            rng = random.Random(poison)
            for start,end in ((0x8000,0x805c),(0x8100,0x813f),
                              (0x8226,0x829e),(0x8408,0x8476)):
                for address in range(start,end): ram[address] = rng.randrange(256)
        for address,value in ((0x80f9,context),(0x80fc,screen),(0x80f5,0xf0),
                              (0x8105,4),(0x8106,math),(0x8121,1)):
            ram[address] = value
        for address,record in ((0x8500,a),(0x8520,b)):
            for i,value in enumerate(record): ram[address+i] = value
        for i,value in enumerate((0,0x85,0x20,0x85)): oracle.harness_set_reg(i,value)
        persistent = bytes(ram[0x8226:0x829e]) + bytes(ram[0x8408:0x8476])
        metadata = bytes(ram[0x8100:0x813f]); native_calls += 1
        execution_status = oracle.quotient_wrapper_call(3000000)
        accepted = C.c_uint.in_dll(oracle,'quotient_accepts').value
        fallback = C.c_uint.in_dll(oracle,'quotient_fallbacks').value
        early_error = C.c_uint.in_dll(oracle,'quotient_error_admissions').value
        branch = 'accepted' if accepted else 'fallback' if fallback else 'early_error' if early_error else 'unclassified'
        native_branches[branch] = native_branches.get(branch,0) + 1
        status = oracle.harness_get_reg(0)
        outcomes[str(status)] = outcomes.get(str(status),0) + 1
        return dict(execution_status=execution_status,firmware_status=status,
                    quotient=bytes(ram[0x8500:0x850a]),remainder=bytes(ram[0x8520:0x852a]),
                    persistent_before=persistent,persistent_after=bytes(ram[0x8226:0x829e])+bytes(ram[0x8408:0x8476]),
                    metadata_before=metadata,metadata_after=bytes(ram[0x8100:0x813f]),
                    polls=C.c_uint.in_dll(oracle,'quotient_polls').value,
                    truncations=C.c_uint.in_dll(oracle,'quotient_truncations').value,
                    noncanonical_prefixes=C.c_uint.in_dll(oracle,'quotient_noncanonical_prefixes').value,
                    normalized=bytes((C.c_uint8 * 20).in_dll(oracle,'quotient_normalized')).hex(),branch=branch)
    def run(a,b,name,shared_input=False,**context):
        nonlocal normalized_truncation_samples
        a,b = number(a),number(b)
        expected = native(a,b,**context)
        detail = dict(name=name,a=a.hex(),b=b.hex(),context=context,
                      normalized=expected['normalized'],native_branch=expected['branch'])
        check('native_return',expected['execution_status'],100,detail)
        check('persistent',expected['persistent_after'].hex(),expected['persistent_before'].hex(),detail)
        check('metadata',expected['metadata_after'].hex(),expected['metadata_before'].hex(),detail)
        check('no_timer_calls',expected['polls'],0,detail)
        check('normalized_truncation_prefix',expected['noncanonical_prefixes'],0,detail)
        normalized_truncation_samples += expected['truncations']
        if expected['execution_status'] != 100: return
        for offset in (0,24,40,25,41,23,39,28):
            buf = (C.c_uint8 * 80)(*[0xee] * 80)
            for i,value in enumerate(a): buf[24+i] = value
            for i,value in enumerate(b): buf[40+i] = value
            before = bytes(buf)
            right_offset = 24 if shared_input else 40
            status = lib.fx_number_quotient_remainder(C.byref(buf,offset),C.byref(buf,24),C.byref(buf,right_offset))
            result = Result.from_buffer_copy(bytes(buf[offset:offset+C.sizeof(Result)]))
            alias_detail = dict(detail,alias_offset=offset,shared_input=shared_input)
            check('host_status',status,0,alias_detail)
            check('firmware_status',result.firmware_status,expected['firmware_status'],alias_detail)
            check('quotient',bytes(result.quotient.bytes).hex(),expected['quotient'].hex(),alias_detail)
            check('remainder',bytes(result.remainder.bytes).hex(),expected['remainder'].hex(),alias_detail)
            check('output_canary',(bytes(buf[:offset])+bytes(buf[offset+C.sizeof(Result):])).hex(),
                  (before[:offset]+before[offset+C.sizeof(Result):]).hex(),alias_detail)
            if offset == 0:
                check('input_preservation',(bytes(buf[24:34])+bytes(buf[40:50])).hex(),(a+b).hex(),alias_detail)

    # Named canonical input/output eligibility gates, both Math policies.
    boundary_pairs = [('10','3'),('-10','3'),('10','-3'),('-10','-3'),('2.5','1.2'),
                      ('0','3'),('3','0'),('0','0'),('1e10','3'),('9999999999','3'),
                      ('1','1e-10'),('1','1e-9'),('1e-99','2e-99'),('1e-99','1e-99'),('1e9','1e-99')]
    for i,(a,b) in enumerate(boundary_pairs):
        for math in (0,1): run(a,b,'initial_gate_' + str(i),math=math)
    late_pairs = [('.25','.12'),('.025','.012'),('.0025','.0012'),('.00025','.00012'),
                  ('.000025','.000012'),('.0000025','.0000012'),('123456789.5','1'),
                  ('123456789.123456','1'),('1.123456789','1'),('1.12345678','1'),('1.1234567','1'),
                  ('1.001','1'),('1.0001','1'),('1e-3','2e-3'),('1e-4','2e-4'),('9999999999','.001')]
    for i,(a,b) in enumerate(late_pairs): run(a,b,'late_remainder_gate_' + str(i))
    boundaries = ['0','.0001','.001','.01','.1','1','3','10','9999999999',
                  '1e10','1e99','1e-99','-1','-3','-1e10']
    for a in boundaries:
        for b in boundaries: run(a,b,'decimal_boundaries')
    formats = [bytes.fromhex(x) for x in ('21a20000000000000301','61a20000000000000301',
               '80000001000201010100','41000000000000000001','40000000000000000000',
               'f1000000000000000000','f2000000000000000000','f3000000000000000000',
               'f7000000000000000000','70000000000000000000')]
    for a in formats + [number(x) for x in ('0','1','3','-3')]:
        for b in formats + [number(x) for x in ('0','1','3','-3')]: run(a,b,'format_and_sentinel')
    rng = random.Random(0x1c138)
    for i in range(args.random_cases // 3):
        def pick_decimal():
            scale = rng.randrange(-12,13); sign = rng.choice((-1,1)); digits = rng.randrange(1,100000000)
            return f'{sign*digits}e{scale}'
        a,b = pick_decimal(),pick_decimal()
        if i % 4 == 0: a,b = f'{rng.randrange(1,100000000)}e-3',f'{rng.randrange(1,100000)}e-3'
        run(a,b,'random_decimal_' + str(i))
    for a in ('10',formats[0],formats[2]):
        for b in ('3',formats[2]):
            for context in (0xc1,0xc4):
                for math in (0,1):
                    for screen in (0,1,0xc0): run(a,b,'context_controls',context=context,math=math,screen=screen)
    rng = random.Random(0x19146)
    for i in range(args.random_cases):
        ma = rng.randrange(10**14,10**15); mb = rng.randrange(10**14,10**15)
        ea = rng.randrange(-9,10); eb = max(-99,ea-rng.randrange(0,10))
        run(f'{ma}e{ea-14}',f'{mb}e{eb-14}','finite_15digit_' + str(i))
    for i in range(args.random_cases):
        b = rng.randrange(1,10**8); q = rng.randrange(0,10**9)
        delta = rng.choice((-1001,-1000,-999,-2,-1,0,1,2,999,1000,1001)); a = b*q + delta
        if a <= 0: continue
        scale = rng.randrange(-6,1)
        run(f'{a}e{scale}',f'{b}e{scale}','quotient_integer_edge_' + str(i))
    for i in range(args.random_cases):
        b = rng.randrange(2,10**9); q = rng.randrange(0,10**6); r = rng.randrange(1,b)
        run(f'{b*q+r}e-3',f'{b}e-3','thousandth_remainder_' + str(i))
    zeros = [bytes(10)] + [bytes.fromhex(x) for x in ('00000000000000000001',
             '00000000000000000006','40000000000000000000','40000000000000000001',
             '40000000000000000006','70000000000000000000')]
    other = [number(x) for x in ('0','1','-1','1e-99','9999999999')] + [bytes.fromhex('f3000000000000000000')]
    for a in zeros:
        for b in zeros + other:
            run(a,b,'noncanonical_zero'); run(b,a,'noncanonical_zero_reverse')
    rng = random.Random(0x1c1386f)
    for i in range(args.random_cases // 3):
        def pick_rich():
            if rng.randrange(4): return rational(rng.randrange(-10**9,10**9),rng.randrange(1,10000),rng.choice((0,0x40)))
            value = bytearray(number(f'{rng.randrange(-10**14,10**14)}e{rng.randrange(-99,100)}'))
            value[0] |= rng.choice((0,0x40)); return bytes(value)
        run(pick_rich(),pick_rich(),'random_rational_marked_' + str(i),math=i % 2)
    roots = (0,1,2,3,5,7,11,13,17,19,23,29,31,41,43,47,61,71,83,97)
    for i in range(args.random_cases // 6):
        a = surd(rng.randrange(-99,100),rng.choice(roots),rng.randrange(1,100),
                 rng.randrange(-99,100),rng.choice(roots),rng.randrange(1,100))
        if a is None: continue
        b = rng.choice((number('3'),number('-3'),number('.001'),number('1e10'),rational(1,3,0x40),a))
        if i % 2: a,b = b,a
        run(a,b,'random_surd_' + str(i),math=i % 2)
    fixed = [number('1'),bytes.fromhex('41000000000000000001'),bytes.fromhex('61a30000000000000301'),
             bytes.fromhex('80000001000201010100'),bytes.fromhex('70000000000000000000')]
    for code in range(16):
        a = bytes([0xf0 | code]) + bytes(9)
        for b in fixed: run(a,b,'early_error_divisor'); run(b,a,'early_error_reverse')
    for marker in (0x60,0x64,0x68):
        for text in ('1a3','4a2','1a2a3','12a13','123a987','12a13a17','0a1','1a0'):
            for sign in (0,1,5,6):
                digits = [int(c,16) for c in text]; length = len(digits); field = digits + [0]*(15-length)
                a = bytes([marker | field[0]] + [(field[i]<<4) | field[i+1] for i in range(1,15,2)])
                a += bytes([length if length < 10 else length+6,sign])
                for b in (number('1'),number('3'),number('-3'),a,formats[-1]): run(a,b,'unchecked_rich_fraction')
    for a in [number(x) for x in ('0','1','-1','.001','1e-99','9999999999','1e10')]:
        run(a,a,'same_input_pointer',shared_input=True)
    for row in json.loads((ROOT / REGRESSIONS).read_text())['fixtures']:
        run(bytes.fromhex(row['a']),bytes.fromhex(row['b']),row['name'])
    # Full raw prefix-byte sweep proves that no host canonical-decoder gate
    # hides native decimal correction on these returned coordinates.
    for field in (8,9):
        for value in range(256):
            for side in (0,1):
                for a,b in (('1','3'),('1e-99','.001'),('9999999999','3')):
                    records = [bytearray(number(a)),bytearray(number(b))]; records[side][field] = value
                    run(bytes(records[0]),bytes(records[1]),'raw_prefix_byte')
    scratch_cases = [('10','3'),('0','3'),('-10','3'),('.025','.012'),('.0025','.0012'),
                     ('73770.2558278193','.0000297652955465714'),(formats[-1],formats[-1]),
                     (formats[5],formats[3]),(formats[5],formats[2]),
                     (bytes.fromhex('64a2a300000000000501'),bytes.fromhex('61a30000000000000301'))]
    for i in range(500):
        a,b = scratch_cases[i % len(scratch_cases)]
        run(a,b,'poisoned_and_reused_state',math=i % 2,context=(0xc1,0xc4,0x49,6,2)[i % 5],
            screen=(0,1,0xc0)[i % 3],reset=i % 7 == 0,poison=i if i % 2 else None)
    for nulls in ((True,False,False),(False,True,False),(False,False,True),(True,True,True)):
        result = Result.from_buffer_copy(bytes([0xab]*C.sizeof(Result))); before = bytes(result)
        operand = Number.from_buffer_copy(number('1')); pointers = [C.byref(result),C.byref(operand),C.byref(operand)]
        for i,is_null in enumerate(nulls):
            if is_null: pointers[i] = None
        status = lib.fx_number_quotient_remainder(*pointers)
        check('null_status',status,-1,dict(nulls=nulls)); check('null_canary',bytes(result).hex(),before.hex(),dict(nulls=nulls))
    report = dict(checks=sum(groups.values()),native_calls=native_calls,groups=groups,failures=failures,
                  normalized_truncation_samples=normalized_truncation_samples,
                  outcomes=outcomes,native_branches=native_branches,random_cases=args.random_cases,
                  scope='Prepared native1C138 quotient/remainder records/status; original live instructions, finite scratch policy, full retained deterministic independent corpus, aliases, source markers/error/surd/fraction admission, all exponent/sign bytes, poisoned and reused arithmetic/metadata/persistent state.',
                  limits=['Parser token5F precedence/terminalstatus37, expression cursors, bank-reference lookup, history and display are separate frontend/controller work.',
                          'Raw numerical helper bounded non-return failures propagate without changing the API output; this wrapper corpus contains only native returned calls.',
                          'Unsupported malformed surd conversion remains explicit UNIMPLEMENTED; this suite verifies valid prepared surd records including active-zero components.'])
    if not failures and not args.no_report:
        report = write_report('analysis/c-verification/numeric_quotient.json',report,
                              SOURCES+HEADERS+[HELPER,REGRESSIONS], 'tools/test_numeric_quotient_c.py')
    (build / 'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k != 'tested_inputs_sha256'},indent=2))
    return bool(failures)

if __name__ == '__main__': raise SystemExit(main())
