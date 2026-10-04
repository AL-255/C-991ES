#!/usr/bin/env python3
"""Compare prepared matrix/vector kernels with unchanged original firmware.

The numerical C library never links ROM/CPU code. The test-only oracle supplies
RAM8E00 timer cancellation responses at5564, without changing instructions.
GPL-3.0-or-later.
"""
import argparse
import ctypes as C
import json
from pathlib import Path
import random
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from nxu8.machine import Machine
from trace_natural_result import settings
from c_verification import write_report
class Number(C.Structure): _fields_=[('bytes',C.c_uint8*10)]
class Value(C.Structure): _fields_=[('reference',Number),('rows',C.c_uint8),('columns',C.c_uint8),('cells',Number*9)]
class Context(C.Structure): _fields_=[('exact_math',C.c_uint8),('display_mode',C.c_uint8),('digits',C.c_uint8),('cancel_at',C.c_uint32)]
class Result(C.Structure): _fields_=[('value',Value),('firmware_status',C.c_uint8),('cancellation_checks',C.c_uint32)]
class Rational(C.Structure): _fields_=[('numerator',C.c_int64),('denominator',C.c_uint64),('flags',C.c_uint8)]
BINARY=[0x13f88,0x14042,0x14162,0x14570,0x145fe]
SCALAR=[0x1404a,0x140b6,0x140be]
UNARY=[0x14242,0x142c0,0x143ec,0x146d6,0x1414a,0x140c6,0x14152,0x1415a,0x1589c,0x15bf8,0x15bfc]
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--random-cases',type=int,default=12000);p.add_argument('--no-report',action='store_true');a=p.parse_args()
 build=ROOT/'analysis/build/linalg';build.mkdir(parents=True,exist_ok=True)
 sources=['csrc/linalg/fx_linalg.c','csrc/complex/fx_complex.c','csrc/complex/fx_complex_round.c','csrc/numeric/fx_numeric.c']
 headers=['csrc/linalg/fx_linalg.h','csrc/complex/fx_complex.h','csrc/complex/fx_complex_round.h','csrc/numeric/fx_numeric.h']
 library=build/'linalg.so'
 subprocess.run(['gcc','-std=c99','-O2','-Wall','-Wextra','-Werror','-pedantic','-shared','-fPIC',*(str(ROOT/x) for x in sources),'-o',str(library)],check=True)
 lib=C.CDLL(str(library));lib.fx_decimal_parse.argtypes=[C.POINTER(Number),C.c_char_p];lib.fx_rational_encode.argtypes=[C.POINTER(Number),C.POINTER(Rational)];lib.fx_surd_pack.argtypes=[C.POINTER(Number),C.POINTER(Number)]
 lib.fx_linalg_binary.argtypes=[C.POINTER(Result),C.POINTER(Value),C.POINTER(Value),C.c_int,C.POINTER(Context)]
 lib.fx_linalg_scalar.argtypes=[C.POINTER(Result),C.POINTER(Value),C.POINTER(Number),C.c_int,C.POINTER(Context)]
 lib.fx_linalg_unary.argtypes=[C.POINTER(Result),C.POINTER(Value),C.c_int,C.POINTER(Context)]
 oracle=build/'oracle';oracle.mkdir(exist_ok=True)
 helper=oracle/'linalg-oracle.c'
 helper.write_text('#define harness_run original_harness_run\n#include "'+str(ROOT/'tools/nxu8/harness.c')+'"\n#undef harness_run\nint harness_run(uint64_t limit,uint32_t stop,bool callback){return original_harness_run(limit,stop,callback); }\nint linalg_run(uint64_t limit,uint32_t stop,uint32_t poll){for(uint64_t i=0;i<limit;++i){uint32_t pc=harness_get_pc();if(pc==stop)return100;if(pc==poll)return104;int status=original_harness_run(1,stop,false);if(status!=103)return status;}return103;}\n'.replace('return100','return 100').replace('return104','return 104').replace('return103','return 103'))
 subprocess.run(['gcc','-std=c99','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',str(helper),str(ROOT/'tools/nxu8/vendor/SimU8/core.c'),'-o',str(oracle/'nxu8-harness.so')],check=True)
 m=Machine((ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes(),oracle);m.lib.linalg_run.argtypes=[C.c_uint64,C.c_uint32,C.c_uint32]
 rng=random.Random(0x14024);counts={};failures=[];native_calls=0
 def literal(v):
  n=Number();assert lib.fx_decimal_parse(C.byref(n),str(v).encode())==0;return bytes(n)
 def rational(x,y,flags=0):
  n=Number();assert lib.fx_rational_encode(C.byref(n),C.byref(Rational(x,y,flags)))==0;return bytes(n)
 def surd(vals):
  parts=(Number*6)(*(Number.from_buffer_copy(literal(x)) for x in vals));n=Number();assert lib.fx_surd_pack(C.byref(n),parts)==0;return bytes(n)
 def value(kind,identity,rows,cols,cells):
  v=Value();v.reference=Number.from_buffer_copy(bytes([kind*16+identity])+bytes(9));v.rows=rows;v.columns=cols
  for i,n in enumerate(cells):v.cells[i]=Number.from_buffer_copy(n)
  return v
 def put(address,data):
  for i,b in enumerate(data):m.ram[address+i]=b
 def check(group,actual,expected,detail):
  counts[group]=counts.get(group,0)+1
  if actual!=expected and len(failures)<100:failures.append({'group':group,'detail':detail,'actual':actual,'expected':expected})
 def run(family,op,left,right=None,scalar=None,context=None,label='',scalar_index=None,output_alias=False):
  nonlocal native_calls
  context=context or Context(1,0,0,0)
  out=Result();out.value=right if output_alias==2 else left
  c_left=C.byref(out.value) if output_alias==1 else C.byref(left)
  c_right=C.byref(out.value) if output_alias==2 else C.byref(right) if right is not None else None
  if family=='binary':host=lib.fx_linalg_binary(C.byref(out),c_left,c_right,op,C.byref(context));entry=BINARY[op]
  elif family=='scalar':
   n=Number.from_buffer_copy(scalar)
   factor=C.byref(out.value.cells[scalar_index]) if output_alias and scalar_index is not None else C.byref(left.cells[scalar_index]) if scalar_index is not None else C.byref(n)
   host=lib.fx_linalg_scalar(C.byref(out),c_left,factor,op,C.byref(context));entry=SCALAR[op]
  else:host=lib.fx_linalg_unary(C.byref(out),c_left,op,C.byref(context));entry=UNARY[op]
  m.reset();settings(m);m.ram[0x8106]=context.exact_math;m.ram[0x8102]=context.display_mode;m.ram[0x8103]=context.digits
  identity=left.reference.bytes[0]&15;base=0x829e+90*identity
  m.word(0x80e0+identity*2,left.rows+256*left.columns);put(base,bytes(left.cells));put(0x8900,bytes(left.reference))
  if right is not None:
   ri=right.reference.bytes[0]&15;rb=0x829e+90*ri
   m.word(0x80e0+ri*2,right.rows+256*right.columns);put(rb,bytes(right.cells));put(0x8920,bytes(right.reference))
  if scalar is not None:put(0x8940,scalar)
  if family=='unary' and op>=8:
   m.er(12,0x8900)
   if op>=9:
    original=Value.from_buffer_copy(bytes(left));original.reference.bytes[0]=(left.reference.bytes[0]&0xf0)|3
    m.word(0x80e6,original.rows+256*original.columns);put(0x83ac,bytes(original.cells));put(0x8914,bytes(original.reference))
  m.er(0,0x8900);m.er(2,base+10*scalar_index if scalar_index is not None else 0x8940 if family=='scalar' else 0x8920)
  m.lib.harness_set_sp(0x8dee);m.lib.harness_set_lr(0x2fffe);m.lib.harness_set_pc(entry)
  polls=0
  for _ in range(100):
   status=m.lib.linalg_run(3000000,0x2fffe,0x5564)
   if status==100:break
   assert status==104,(hex(entry),status,hex(m.lib.harness_get_pc()))
   polls+=1;m.ram[0x8e00]=2 if context.cancel_at==polls else 0
   assert m.lib.harness_run(1,0x2fffe,False)==103
  else:raise RuntimeError('oracle poll limit')
  native_calls+=1;detail={'label':label,'entry':hex(entry),'left':bytes(left).hex(),'right':bytes(right).hex() if right else None,'scalar':scalar.hex() if scalar else None,'cancel_at':context.cancel_at,'scalar_index':scalar_index,'output_alias':output_alias}
  group=family+'-'+str(op)
  check(group,host,0,detail)
  check(group,bytes(out.value.reference).hex(),bytes(m.ram[0x8900:0x890a]).hex(),detail)
  check(group,bytes(out.value.cells).hex(),bytes(m.ram[base:base+90]).hex(),detail)
  check(group,out.value.rows+256*out.value.columns,m.word(0x80e0+identity*2),detail)
  check(group,out.firmware_status,m.reg(0),detail)
  check(group,out.cancellation_checks,polls,detail)
 integers=[literal(x) for x in [-9,-3,-1,0,1,2,3,7,99]]
 exact=[rational(1,3),rational(-2,7),rational(5,2),surd([1,2,1,0,1,1]),surd([-1,3,2,1,5,3])]
 marked=[bytes([n[0]|0x40])+n[1:] for n in integers+exact[:3]]
 errors=[bytes([x])+bytes(9) for x in [0xf0,0xf1,0xf2,0xf3,0xf8,0xff]]
 decimal=[]
 for _ in range(60):
  digits=f'{rng.randrange(10**14,10**15):015d}';e=rng.randrange(-99,100)
  decimal.append(bytes([int(digits[0]),*(int(digits[i:i+2],16) for i in range(1,15,2)),int(f'{e%100:02d}',16),(e>=0)+(5 if rng.randrange(2) else 0)]))
 pools=[integers,integers+exact,integers+marked+errors,decimal]
 def cells(pool):return [rng.choice(pool) for _ in range(9)]
 for rows in range(4):
  for cols in range(4):
   for k in [6,9]:
    v=value(k,0,rows,cols,cells(integers));w=value(k,1,rows,cols,cells(integers))
    for op in range(5):run('binary',op,v,w,label='dimensions')
    for op in range(3):run('scalar',op,v,scalar=literal(2),label='dimensions')
    for op in range(11):run('unary',op,v,label='dimensions')
 for index in range(a.random_cases):
  pool=pools[index%4];k=9 if index%5==0 else 6;rows=1 if k==9 else rng.randrange(1,4);cols=rng.randrange(1,4)
  v=value(k,index%2,rows,cols,cells(pool));w=value(k,2,rows,cols,cells(pool));ctx=Context(1 if index%7 else 0,rng.choice([0,4,8,9]),rng.randrange(10),rng.choice([0,0,0,1,2,5,10,20]))
  family=rng.choice(['binary','scalar','unary']);op=rng.randrange(5 if family=='binary' else 3 if family=='scalar' else 11)
  if family=='binary' and op==2:w.rows=v.columns;w.columns=rng.randrange(4)
  run(family,op,v,w if family=='binary' else None,rng.choice(pool) if family=='scalar' else None,ctx,'random-'+str(index),output_alias=index%3 if family=='binary' else index%2)
 # Unsupported rich tags, preserved reference metadata, and equal storage
 # identities exercise reference admission independently of scalar encoding.
 for k in range(16):
  v=value(k,0,2,2,cells(integers));w=value(k,1,2,2,cells(integers))
  for i in range(1,10):v.reference.bytes[i]=i*7
  for op in range(5):run('binary',op,v,w,label='reference-kind')
  for op in range(11):run('unary',op,v,label='reference-kind')
  for op in range(3):run('scalar',op,v,scalar=literal(2),label='reference-kind')
 for k in [6,9]:
  for op in range(5):
   v=value(k,0,3,3,cells(integers))
   run('binary',op,v,Value.from_buffer_copy(bytes(v)),label='same-storage',output_alias=2)
 for exact_math in [0,1]:
  for coords in [[3,4,99],[0,3,99],[1,2,3],[-1,-2,3]]:
   v=value(9,0,1,3,[literal(x) for x in coords]+[literal(97)]*6)
   run('unary',3,v,context=Context(exact_math,0,0,0),label='magnitude-permission')
 # Cancellation boundaries after preparation, determinants, cofactor groups and
 # scalar updates distinguish temp-buffer commits from in-place partial writes.
 for dimension in [1,2,3]:
  v=value(6,0,dimension,dimension,[literal(x) for x in [2,1,3,0,3,4,1,2,5]])
  for cancel in range(25):
   for op in [1,2]:run('unary',op,v,context=Context(1,0,0,cancel),label='cancel-'+str(cancel))
 for position in range(9):
  v=value(6,0,3,3,[literal(x) for x in range(1,10)])
  for op in range(3):run('scalar',op,v,scalar=bytes(v.cells[position]),scalar_index=position,label='scalar-alias',output_alias=True)
 report={'checks':sum(counts.values()),'native_calls':native_calls,'groups':counts,'failures':failures,'oracle_context':'Unchanged ROM and CPU; explicit RAM8E00 cancellation response at5564. Settings C1, exact selector fixtures, fixed payload stride3; full payload/dimensions/reference/status/poll count compared.','limits':['Prepared numerical entries only; evaluator reference rewriting and input/UI excluded.','Physical timer/key scheduling excluded; cancellation responses supplied explicitly.','REF/RREF elimination not implemented in this initial kernel suite.']}
 if failures:print(json.dumps(report,indent=2));return 1
 if not a.no_report:report=write_report('analysis/c-verification/linalg.json',report,sources+headers,'tools/test_linalg_c.py')
 print(json.dumps({k:v for k,v in report.items() if k not in ['tested_inputs_sha256']},indent=2));return 0
if __name__=='__main__':raise SystemExit(main())
