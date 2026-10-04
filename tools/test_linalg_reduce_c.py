#!/usr/bin/env python3
"""Differential original-ROM checks for readable finite-order matrix REF/RREF.

The CPU/ROM are test-only; production C executes numerical algorithms only.
GPL-3.0-or-later.
"""
import argparse
import ctypes as C
import json
import random
import sys
import subprocess
import itertools
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from test_linalg_c import Number,Value,Context,Result,Rational
from nxu8.machine import Machine
from trace_natural_result import settings
from c_verification import write_report

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--random-cases',type=int,default=12000)
    parser.add_argument('--no-report',action='store_true')
    args=parser.parse_args()
    build=ROOT/'analysis/build/linalg-reduce';build.mkdir(parents=True,exist_ok=True)
    sources=['csrc/linalg/fx_linalg_reduce.c','csrc/linalg/fx_linalg.c','csrc/complex/fx_complex.c','csrc/complex/fx_complex_round.c','csrc/numeric/fx_numeric.c']
    subprocess.run(['gcc','-std=c99','-O2','-Wall','-Wextra','-Werror','-pedantic','-shared','-fPIC','-I'+str(ROOT/'csrc/linalg'),'-I'+str(ROOT/'csrc/complex'),*(str(ROOT/x) for x in sources),'-o',str(build/'reduce.so')],check=True)
    lib=C.CDLL(str(build/'reduce.so'));lib.fx_linalg_echelon.argtypes=[C.POINTER(Result),C.POINTER(Value),C.c_int,C.POINTER(Context)];lib.fx_decimal_parse.argtypes=[C.POINTER(Number),C.c_char_p];lib.fx_rational_encode.argtypes=[C.POINTER(Number),C.POINTER(Rational)];lib.fx_surd_pack.argtypes=[C.POINTER(Number),C.POINTER(Number)]
    oracle=build/'oracle';oracle.mkdir(exist_ok=True);helper=oracle/'helper.c'
    helper.write_text('#define harness_run original_harness_run\n#include "'+str(ROOT/'tools/nxu8/harness.c')+'"\n#undef harness_run\nint harness_run(uint64_t limit,uint32_t stop,bool callback){return original_harness_run(limit,stop,callback); }\nint linalg_run(uint64_t limit,uint32_t stop,uint32_t poll){for(uint64_t i=0;i<limit;++i){uint32_t pc=harness_get_pc();if(pc==stop)return 100;if(pc==poll)return 104;int status=original_harness_run(1,stop,false);if(status!=103)return status;}return 103;}\n')
    subprocess.run(['gcc','-std=c99','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',str(helper),str(ROOT/'tools/nxu8/vendor/SimU8/core.c'),'-o',str(oracle/'nxu8-harness.so')],check=True)
    m=Machine((ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes(),oracle);m.lib.linalg_run.argtypes=[C.c_uint64,C.c_uint32,C.c_uint32]
    rng=random.Random(0x14776);failures=[];checks=0;calls=0

    def literal(x):
     n=Number();assert lib.fx_decimal_parse(C.byref(n),str(x).encode())==0;return bytes(n)
    def rational(x,y,flags=0):
     n=Number();assert lib.fx_rational_encode(C.byref(n),C.byref(Rational(x,y,flags)))==0;return bytes(n)
    def surd(x):
     p=(Number*6)(*(Number.from_buffer_copy(literal(a)) for a in x));n=Number();assert lib.fx_surd_pack(C.byref(n),p)==0;return bytes(n)
    def value(rows,cols,data):
     v=Value();v.reference.bytes[0]=0x60;v.rows=rows;v.columns=cols
     for i,n in enumerate(data):v.cells[i]=Number.from_buffer_copy(n)
     return v
    def put(a,data):
     for i,b in enumerate(data):m.ram[a+i]=b
    def check(actual,expected,detail):
     nonlocal checks
     checks+=1
     if actual!=expected and len(failures)<100:failures.append({'actual':actual,'expected':expected,'detail':detail})
    def run(v,reduced,context=Context(1,0,0,0),label='',alias=False):
     nonlocal calls
     out=Result();out.value=v;inp=C.byref(out.value) if alias else C.byref(v)
     host=lib.fx_linalg_echelon(C.byref(out),inp,reduced,C.byref(context));m.reset();settings(m);m.ram[0x8106]=context.exact_math
     m.word(0x80e0,v.rows+256*v.columns);put(0x829e,bytes(v.cells));put(0x8900,bytes(v.reference));m.er(0,0x8900)
     m.lib.harness_set_sp(0x8dee);m.lib.harness_set_lr(0x2fffe);m.lib.harness_set_pc(0x14786 if reduced else 0x14776)
     polls=0
     for _ in range(400):
      status=m.lib.linalg_run(3000000,0x2fffe,0x5564)
      if status==100:break
      assert status==104,(hex(m.lib.harness_get_pc()),status)
      polls+=1;m.ram[0x8e00]=2 if context.cancel_at==polls else 0;assert m.lib.harness_run(1,0x2fffe,False)==103
     else:raise RuntimeError('poll limit')
     calls+=1;detail={'label':label,'input':bytes(v).hex(),'reduced':reduced,'cancel_at':context.cancel_at,'alias':alias}
     for actual,expected in [(host,0),(bytes(out.value.reference).hex(),bytes(m.ram[0x8900:0x890a]).hex()),(bytes(out.value.cells).hex(),bytes(m.ram[0x829e:0x82f8]).hex()),(out.value.rows+256*out.value.columns,m.word(0x80e0)),(out.firmware_status,m.reg(0)),(out.cancellation_checks,polls)]:check(actual,expected,detail)

    ints=[literal(x) for x in [-9,-3,-1,0,1,2,3,7,99]]
    exact=[rational(1,3),rational(-2,7),rational(5,2),surd([1,2,1,0,1,1]),surd([-1,3,2,1,5,3])]
    errors=[bytes([x])+bytes(9) for x in [0xf0,0xf1,0xf2,0xf3,0xf8,0xff]]
    marked=[bytes([x[0]|0x40])+x[1:] for x in ints+exact[:3]]
    dec=[literal(x) for x in ['1e-99','-9.99e99','1e-12','1e-11','1e-10','1.00000000000001','0.999999999999999','-1.23456789012345','1e99']]
    for rows in range(4):
     for cols in range(4):
      for reduced in [0,1]:run(value(rows,cols,[rng.choice(ints) for _ in range(9)]),reduced,label='dimension')
    for x in itertools.product([-1,0,1],repeat=4):
     v=value(2,2,[literal(t) for t in [x[0],x[1],97,x[2],x[3],98,95,96,99]])
     for reduced in [0,1]:run(v,reduced,label='exhaustive2')
    fixtures=[[1,2,97,3,4,98,95,96,99],[1,0,2,0,0,1,0,0,3],[0,1,2,0,1,4,0,0,0],[0,0,1,0,2,3,4,5,6],[1,2,3,2,4,6,3,6,9],[0,0,0,0,0,0,0,0,0],[1,0,0,0,1,0,0,0,1]]
    for f in fixtures:
     v=value(3,3,[literal(x) for x in f])
     for cancel in range(82):
      for reduced in [0,1]:run(v,reduced,Context(1,0,0,cancel),label='cancellation')
    # Native1CA3E tests original94EC integer eligibility before packing a
    # fraction. An exponent15 pivot must keep ordinary division's guards;
    # eligible exponent14 decimal fallbacks still receive integer cleanup.
    for text in ['99999999999999','1.23456789012345e14','1e15',
                 '1.23456789012345e15','-1.23456789012345e15']:
     for rows,cols,data in [(1,2,[text,1,97,98,99,96,95,94,93]),
                            (2,2,[text,1,97,0,1,98,95,96,99]),
                            (2,3,[text,1,2,0,1,3,95,96,99])]:
      for reduced in [0,1]:
       for alias in [False,True]:
        run(value(rows,cols,[literal(x) for x in data]),reduced,
            label='fraction-eligibility-'+text,alias=alias)
    for i in range(args.random_cases):
     pool=[ints,ints+exact,ints+errors+marked,dec][i%4];v=value(rng.randrange(1,4),rng.randrange(1,4),[rng.choice(pool) for _ in range(9)])
     run(v,i%2,Context(i%2,0,0,rng.choice([0,0,0,1,2,5,10,20,40,60])),label='random-'+str(i),alias=bool(i%2))
    report={'checks':checks,'native_calls':calls,'failures':failures,'scope':'Prepared matrix REF14776/RREF14786 with exact finite product/subtraction/normalization order, recursive shifts and cancellation partial-state parity.','output':'Complete90-byte backing, dimension word, ten-byte reference/result, native R0 and reached timer check count.','oracle_context':'Unchanged original ROM and CPU; prepared RAM8E00 timer response supplied atPC5564. Canonical rich matrix references and ten-byte scalar cells; scalar exact permission explicit.','limits':['Physical timer/key interrupt scheduling and persistent matrix UI are outside this numerical entry API.','Caller slot/reference rewriting and malformed BCD are excluded.']}
    if not failures and not args.no_report:
        headers=['csrc/linalg/fx_linalg_reduce.h','csrc/linalg/fx_linalg.h','csrc/complex/fx_complex.h','csrc/complex/fx_complex_round.h','csrc/numeric/fx_numeric.h']
        report=write_report('analysis/c-verification/linalg_reduce.json',report,sources+headers+['tools/test_linalg_c.py','tools/trace_natural_result.py','tools/c_verification.py'],'tools/test_linalg_reduce_c.py')
    print(json.dumps({k:v for k,v in report.items() if k!='tested_inputs_sha256'},indent=2))
    return int(bool(failures))

if __name__=='__main__':raise SystemExit(main())
