#!/usr/bin/env python3
"""Compare prepared Ran#/RanInt# and persistent seeds with the original ROM."""
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
from nxu8.machine import Machine

SOURCES = ['csrc/numeric/fx_random.c','csrc/numeric/fx_numeric.c',
           'csrc/numeric/fx_raw_decimal_parts.c','csrc/numeric/fx_raw_decimal_divide.c',
           'csrc/numeric/fx_raw_decimal_multiply_add.c','csrc/numeric/fx_raw_fraction_convert.c']
HEADERS = [p[:-2]+'.h' for p in SOURCES]

class Number(C.Structure):
    _fields_ = [('bytes',C.c_uint8 * 10)]
class Result(C.Structure):
    _fields_ = [('value',Number),('seed',Number),('firmware_status',C.c_uint8)]
class Rational(C.Structure):
    _fields_ = [('numerator',C.c_int64),('denominator',C.c_uint64),('flags',C.c_uint8)]

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--random-cases',type=int,default=6000)
    ap.add_argument('--no-report',action='store_true')
    args = ap.parse_args()
    if args.random_cases < 0: ap.error('--random-cases must be nonnegative')
    build = ROOT / 'analysis/build/numeric-random'; build.mkdir(parents=True,exist_ok=True)
    so = build / 'random.so'
    subprocess.run(['gcc','-std=c99','-O3','-Wall','-Wextra','-Werror','-Wpedantic',
                    '-shared','-fPIC',*(str(ROOT/p) for p in SOURCES),'-o',str(so)],check=True)
    lib = C.CDLL(str(so))
    lib.fx_random_next.argtypes = [C.c_void_p,C.c_void_p]
    lib.fx_random_integer.argtypes = [C.c_void_p] * 4
    lib.fx_random_xorshift32.argtypes = [C.c_uint32]
    lib.fx_random_xorshift32.restype = C.c_uint32
    lib.fx_decimal_parse.argtypes = [C.POINTER(Number),C.c_char_p]
    lib.fx_rational_encode.argtypes = [C.POINTER(Number),C.POINTER(Rational)]
    lib.fx_surd_pack.argtypes = [C.c_void_p,C.c_void_p]
    m = Machine((ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes(),build/'oracle')
    rng = random.Random(0x13db8)
    groups,failures,limits,outcomes = {},[],[],{}
    native_calls = 0

    def number(text):
        if isinstance(text,bytes): return text
        n = Number(); assert lib.fx_decimal_parse(C.byref(n),str(text).encode()) == 0
        return bytes(n.bytes)
    def rational(n,d,marker=0):
        value = Number(); ratio = Rational(n,d,marker)
        assert lib.fx_rational_encode(C.byref(value),C.byref(ratio)) == 0
        return bytes(value.bytes)
    def surd(c,r,d,c2=0,r2=0,d2=1):
        fields = (Number * 6)(*[Number.from_buffer_copy(number(x)) for x in (c,r,d,c2,r2,d2)])
        value = Number(); assert lib.fx_surd_pack(C.byref(value),fields) == 0
        return bytes(value.bytes)
    def check(group,actual,expected,detail):
        groups[group] = groups.get(group,0)+1
        if actual != expected:
            failures.append(dict(group=group,actual=actual,expected=expected,fixture=detail))
            if len(failures) <= 20: print(json.dumps(failures[-1]),flush=True)
    def native(seed,a=None,b=None,math=1,poison=None,reuse=False):
        nonlocal native_calls
        if not reuse: m.reset()
        if poison is not None:
            p = random.Random(poison)
            for start,end in ((0x8000,0x8064),(0x8100,0x821c),(0x8226,0x829e),(0x8408,0x8476)):
                m.ram[start:end] = p.randbytes(end-start)
        for addr,value in ((0x80f9,0xc1),(0x80fc,1),(0x80f5,0xf0),(0x8105,4),
                           (0x8106,math),(0x8121,1)):
            m.ram[addr] = value
        m.ram[0x821c:0x8226] = seed
        m.ram[0x8500:0x850a] = a if a is not None else bytes([0xee]*10)
        if b is not None: m.ram[0x8520:0x852a] = b
        m.er(0,0x8500); m.er(2,0x8520)
        persistent_before = bytes(m.ram[0x8100:0x821c])+bytes(m.ram[0x8226:0x829e])+bytes(m.ram[0x8408:0x8476])
        native_calls += 1
        try:
            m.call(0x13ebe if a is not None else 0x13db8,limit=3000000)
            execution = 100
        except RuntimeError:
            execution = int(m.lib.harness_get_pc())
        status = m.reg(0)
        outcomes[str(status)] = outcomes.get(str(status),0)+1
        return dict(execution=execution,firmware_status=status,value=bytes(m.ram[0x8500:0x850a]),
                    seed=bytes(m.ram[0x821c:0x8226]),upper=bytes(m.ram[0x8520:0x852a]),
                    persistent_before=persistent_before,
                    persistent_after=bytes(m.ram[0x8100:0x821c])+bytes(m.ram[0x8226:0x829e])+bytes(m.ram[0x8408:0x8476]))
    def run(seed,a=None,b=None,name='',math=1,poison=None,reuse=False,expect_limit=False):
        seed = number(seed); a = number(a) if a is not None else None; b = number(b) if b is not None else None
        expected = native(seed,a,b,math,poison,reuse)
        detail = dict(name=name,seed=seed.hex(),a=a.hex() if a else None,b=b.hex() if b else None,
                      math=math,poison=poison,native_execution=expected['execution'])
        result = Result(); C.memset(C.byref(result),0xee,C.sizeof(result))
        input_seed=Number.from_buffer_copy(seed)
        inputs = [input_seed]+([Number.from_buffer_copy(a),Number.from_buffer_copy(b)] if a is not None else [])
        status = (lib.fx_random_integer(C.byref(result),*(C.byref(x) for x in inputs)) if a is not None
                  else lib.fx_random_next(C.byref(result),C.byref(input_seed)))
        if expected['execution'] != 100 or expect_limit:
            limits.append(dict(detail,native_value=expected['value'].hex(),native_seed=expected['seed'].hex(),
                               host_status=status))
            check('explicit_architectural_limit',status,-3,detail)
            check('limit_output_untouched',bytes(result).hex(),bytes([0xee]*C.sizeof(result)).hex(),detail)
            return expected['seed']
        check('native_return',expected['execution'],100,detail)
        check('host_status',status,0,detail)
        check('firmware_status',result.firmware_status,expected['firmware_status'],detail)
        check('value',bytes(result.value.bytes).hex(),expected['value'].hex(),detail)
        check('seed',bytes(result.seed.bytes).hex(),expected['seed'].hex(),detail)
        check('persistent',expected['persistent_after'].hex(),expected['persistent_before'].hex(),detail)
        if b is not None: check('native_upper_unchanged',expected['upper'].hex(),b.hex(),detail)
        check('input_preservation',b''.join(bytes(x.bytes) for x in inputs).hex(),(seed+(a or b'')+(b or b'')).hex(),detail)
        # Exercise exact and partial output aliases, retaining canaries outside result.
        for offset in (0,24,25,44,43,64,67):
            buffer = (C.c_uint8 * 110)(*[0xbd]*110)
            buffer[24:34] = seed
            if a is not None: buffer[44:54] = a; buffer[64:74] = b
            before = bytes(buffer)
            alias_status = (lib.fx_random_integer(C.byref(buffer,offset),C.byref(buffer,24),C.byref(buffer,44),C.byref(buffer,64))
                            if a is not None else lib.fx_random_next(C.byref(buffer,offset),C.byref(buffer,24)))
            value = Result.from_buffer_copy(bytes(buffer[offset:offset+C.sizeof(Result)]))
            alias_detail = dict(detail,alias=offset)
            check('alias_host_status',alias_status,0,alias_detail)
            check('alias_result',bytes(value).hex(),bytes(result).hex(),alias_detail)
            check('alias_canaries',(bytes(buffer[:offset])+bytes(buffer[offset+C.sizeof(Result):])).hex(),
                  (before[:offset]+before[offset+C.sizeof(Result):]).hex(),alias_detail)
        return expected['seed']

    for state in [0,1,0x80000000,0xffffffff,0x12345678]+[rng.randrange(1<<32) for _ in range(args.random_cases)]:
        m.reset(); m.er(0,state&0xffff); m.er(2,state>>16); m.call(0x13d74)
        native_calls += 1
        check('xorshift',lib.fx_random_xorshift32(state),m.er(0)|(m.er(2)<<16),dict(state=state))

    boundaries = ['0','.1','.2','.5','.99','.999999999999999','1e-99','1','2','3','10','100','1e99',
                  '-.1','-1','-1e99']
    for math in (0,1):
        for value in boundaries: run(value,name='seed_decimal_boundary',math=math)
        for exponent in range(256):
            for sign in (0,1,5,6,0xff):
                run(number('.123456789012345')[:8]+bytes([exponent,sign]),name='idle_binary_seed_word',math=math)
    for header in range(256):
        record = bytes([header])+number('.123456789012345')[1:]
        run(record,name='every_raw_seed_header',expect_limit=0x80<=header<=0x8f)
    # A native decimal magnitude-ordering cycle is retained, rather than retried
    # with a different seed or silently counted as ordinary successful parity.
    run(bytes.fromhex('416f44ee0c679822aaad'),name='native_decimal_add_cycle')
    for i in range(args.random_cases):
        record = number(str(rng.randrange(10**14,10**15))+'e'+str(rng.randrange(-113,86)))
        if i&1: record=bytes([record[0]|0x40])+record[1:]
        run(record,name='fresh_random_normal_seed',math=i&1)
        record = bytes([rng.choice([0,0x40])+rng.randrange(16)])+rng.randbytes(9)
        run(record,name='fresh_raw_decimal_seed',math=i&1)
    seed = number(0)
    for i in range(max(100,args.random_cases)):
        # Idle wait advances the little-endian last word, not a BCD exponent.
        word = (int.from_bytes(seed[8:10],'little')+rng.randrange(65536))&65535
        seed = seed[:8]+word.to_bytes(2,'little')
        seed = run(seed,name='reused_seed_and_idle_ticks',reuse=True,math=i&1)

    endpoints = ['-10000000000','-9999999999','-100','-10','-1','0','1','10','100',
                 '9999999999','10000000000','.1','1.00000000000001','1e-99','1e99']
    for i,a in enumerate(endpoints):
        for j,b in enumerate(endpoints):
            run(0,a,b,name='bound_and_span_gates',math=(i+j)&1)
    exact = [rational(1,2),rational(4,2),rational(1,3),rational(-1,2),rational(1,2,0x40),
             surd(1,2,1),surd(1,4,1),surd(0,0,1,1,1,1)]
    for a in exact:
        for b in (number(3),number(10),a):
            run(0,a,b,name='exact_bounds')
            run(0,b,a,name='exact_bounds_reverse')
    for header in range(256):
        record = bytes([header])+number(3)[1:]
        run(0,record,10,name='all_bound_headers')
        run(0,-10,record,name='all_upper_headers')
    for sign in range(256):
        for exponent in (0,9,0x10,0xff):
            raw = number(3)[:8]+bytes([exponent,sign])
            run(0,raw,10,name='all_bound_sign_coordinates')
            run(0,-10,raw,name='all_upper_sign_coordinates')
    for i in range(args.random_cases):
        a=rng.randrange(-10**10-10,10**10+10);b=rng.randrange(-10**10-10,10**10+10)
        if i%3==0: a,b=sorted([a,b])
        seed=number(str(rng.randrange(10**14,10**15))+'e-15')
        run(seed,str(a),str(b),name='fresh_integer_bounds',poison=i if i%37==0 else None)
        # Native CAA8 counts zero positions without validating every mantissa
        # nibble. These whole integer records can retain malformed high digits
        # in the final floor result; preserve their finite operations too.
        raw = bytes([rng.randrange(1,10)])+rng.randbytes(4)+bytes(3)+bytes([9,rng.choice([1,6])])
        run(0,raw,number(9999999999),name='raw_integer_mantissa')
        run(0,number(-9999999999),raw,name='raw_upper_integer_mantissa')

    record = Number.from_buffer_copy(number(0)); result = Result()
    C.memset(C.byref(result),0xe5,C.sizeof(result))
    check('null_seed',lib.fx_random_next(C.byref(result),None),-1,{})
    check('null_out',lib.fx_random_next(None,C.byref(record)),-1,{})
    check('null_integer_input',lib.fx_random_integer(C.byref(result),C.byref(record),None,C.byref(record)),-1,{})
    check('null_output_unchanged',bytes(result).hex(),bytes([0xe5]*C.sizeof(result)).hex(),{})

    report = dict(checks=sum(groups.values()),cases=groups,original_calls=native_calls,
                  native_outcomes=outcomes,mismatches=len(failures),failures=failures,
                  limits=limits,scope='Prepared 13DB8 / 13EBE and exact xorshift13D74; explicit raw-surd-seed and native nonreturn boundaries retained.')
    (build/'diagnostics.json').write_text(json.dumps(report,indent=2)+'\n')
    if failures:
        print(json.dumps({'status':'fail','checks':report['checks'],'mismatches':len(failures),'limits':len(limits)}))
        return 1
    if not args.no_report:
        write_report('analysis/c-verification/numeric_random.json',report,SOURCES+HEADERS,__file__.replace(str(ROOT)+'/', ''))
    print(json.dumps({'status':'pass','checks':report['checks'],'original_calls':native_calls,'limits':len(limits)}))
    return 0

if __name__ == '__main__': raise SystemExit(main())
