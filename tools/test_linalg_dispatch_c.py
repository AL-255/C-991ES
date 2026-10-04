#!/usr/bin/env python3
"""Typed matrix/vector16336 dispatcher against unchanged native instructions.

Prepared operands are passed through the actual evaluator work/operand stack,
not called directly at numerical leaves. Production C does not execute ROM.
GPL-3.0-or-later.
"""
import argparse,ctypes as C,json,random,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from nxu8.machine import Machine
from trace_natural_result import settings
from c_verification import write_report
from linalg_raw_cases import run_raw_regressions
class Number(C.Structure):_fields_=[('bytes',C.c_uint8*10)]
class Complex(C.Structure):_fields_=[('real',Number),('imaginary',Number)]
class Slot(C.Structure):_fields_=[('rows',C.c_uint8),('columns',C.c_uint8),('cells',Number*9)]
class Bank(C.Structure):_fields_=[('slots',Slot*9),('temporary_mask',C.c_uint8)]
class NumericContext(C.Structure):_fields_=[('exact_math',C.c_uint8),('display_mode',C.c_uint8),('digits',C.c_uint8),('cancel_at',C.c_uint32)]
class Context(C.Structure):_fields_=[('calculation_context',C.c_uint8),('numeric',NumericContext)]
class Result(C.Structure):_fields_=[('value',Complex),('firmware_status',C.c_uint8),('cancellation_checks',C.c_uint32)]
class Rational(C.Structure):_fields_=[('numerator',C.c_int64),('denominator',C.c_uint64),('flags',C.c_uint8)]
TOKENS={0xc0:13,0xc1:14,0x5a:122,0x5b:123,0x63:11,0xb3:12,0x60:95,0x75:108,0x76:109,0x77:107,
 0x2b:43,0x2d:44,0x4e:45,0x4f:46,0x9e:47,0x5e:101,0x9f:102,0xbe:49,0xbf:50,0x68:32,
 0x98:23,0xa8:25,0xa3:24,0x73:21,0x93:22,0x25:110,0x57:111,0x70:15,0x71:16,0x72:17,
 0x90:18,0x91:19,0x92:20,0xa0:26,0xa1:27,0xa2:28,0xb0:29,0xb1:30,0xb2:31,0x85:112,0x86:113,0x87:114}
BINARY=[0x2b,0x2d,0x4e,0x4f,0x9e,0x5e,0x9f,0xbe,0xbf,0x68]
UNARY=[x for x in TOKENS if x not in BINARY]+[0x68]
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--random-cases',type=int,default=6000);p.add_argument('--no-report',action='store_true');a=p.parse_args()
 build=ROOT/'analysis/build/linalg_dispatch';build.mkdir(parents=True,exist_ok=True)
 sources=['csrc/linalg/fx_linalg_dispatch.c','csrc/linalg/fx_linalg_store.c','csrc/linalg/fx_linalg.c','csrc/linalg/fx_linalg_reduce.c','csrc/complex/fx_complex.c','csrc/complex/fx_complex_round.c','csrc/numeric/fx_numeric.c']
 headers=[x[:-2]+'.h' for x in sources]
 library=build/'dispatch.so';subprocess.run(['gcc','-std=c99','-O2','-Wall','-Wextra','-Werror','-pedantic','-shared','-fPIC',*(str(ROOT/x) for x in sources),'-o',str(library)],check=True)
 lib=C.CDLL(str(library));lib.fx_decimal_parse.argtypes=[C.POINTER(Number),C.c_char_p];lib.fx_rational_encode.argtypes=[C.POINTER(Number),C.POINTER(Rational)];lib.fx_surd_pack.argtypes=[C.POINTER(Number),C.POINTER(Number)]
 lib.fx_linalg_dispatch_unary.argtypes=[C.POINTER(Result),C.POINTER(Bank),C.POINTER(Complex),C.c_uint8,C.POINTER(Context)]
 lib.fx_linalg_dispatch_binary.argtypes=[C.POINTER(Result),C.POINTER(Bank),C.POINTER(Complex),C.POINTER(Complex),C.c_uint8,C.POINTER(Context)]
 oracle=build/'oracle';oracle.mkdir(exist_ok=True);helper=oracle/'dispatch-oracle.c'
 helper.write_text('#define harness_run original_harness_run\n#include "'+str(ROOT/'tools/nxu8/harness.c')+'"\n#undef harness_run\nint harness_run(uint64_t n,uint32_t stop,bool cb){return original_harness_run(n,stop,cb); }\nint dispatch_run(uint64_t n,uint32_t stop,uint32_t poll){for(uint64_t i=0;i<n;++i){uint32_t pc=harness_get_pc();if(pc==stop)return 100;if(pc==poll)return 104;int s=original_harness_run(1,stop,false);if(s!=103)return s;}return 103;}\n')
 subprocess.run(['gcc','-std=c99','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',str(helper),str(ROOT/'tools/nxu8/vendor/SimU8/core.c'),'-o',str(oracle/'nxu8-harness.so')],check=True)
 m=Machine((ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes(),oracle);m.lib.dispatch_run.argtypes=[C.c_uint64,C.c_uint32,C.c_uint32]
 rng=random.Random(0x16336);counts={};fail=[];native_calls=0
 def dec(x):
  n=Number();assert not lib.fx_decimal_parse(C.byref(n),str(x).encode());return bytes(n)
 def ratio(x,y):
  n=Number();assert not lib.fx_rational_encode(C.byref(n),C.byref(Rational(x,y,0)));return bytes(n)
 def surd(v):
  n=Number();parts=(Number*6)(*(Number.from_buffer_copy(dec(x)) for x in v));assert not lib.fx_surd_pack(C.byref(n),parts);return bytes(n)
 ints=[dec(x) for x in [-9,-3,-1,0,1,2,3,7,99]]
 exact=[ratio(1,3),ratio(-2,7),ratio(5,2),surd([1,2,1,0,1,1]),surd([-1,3,2,1,5,3])]
 marked=[bytes([n[0]|0x40])+n[1:] for n in ints+exact[:3]]
 errors=[bytes([0xf0+i])+bytes(9) for i in range(16)]
 decimal=[]
 for _ in range(60):
  d=f'{rng.randrange(10**14,10**15):015d}';e=rng.randrange(-99,100)
  decimal.append(bytes([int(d[0]),*(int(d[i:i+2],16) for i in range(1,15,2)),int(f'{e%100:02d}',16),(e>=0)+(5 if rng.randrange(2) else 0)]))
 pools=[ints,ints+exact,ints+marked+errors,decimal]
 def bank(rows=2,cols=2,pool=ints,mask=0x18):
  b=Bank();b.temporary_mask=mask
  for slot in b.slots:
   slot.rows=rows;slot.columns=cols
   for i in range(9):slot.cells[i]=Number.from_buffer_copy(rng.choice(pool))
  return b
 def record(kind,identity=0,metadata=False):
  return bytes([kind|identity])+bytes(rng.randrange(256) if metadata else 0 for _ in range(9))
 def operand(real,imag=None):return Complex.from_buffer_copy(real+(imag or dec(0)))
 def put(addr,data):
  for i,x in enumerate(data):m.ram[addr+i]=x
 def check(group,actual,expected,detail):
  counts[group]=counts.get(group,0)+1
  if actual!=expected and len(fail)<30:
   fail.append({'group':group,'actual':actual,'expected':expected,'fixture':detail});print(json.dumps(fail[-1]))
 def run(group,initial,left,right,token,ctx=None,alias=0):
  nonlocal native_calls
  ctx=ctx or Context(6,NumericContext(1,0,0,0))
  b=Bank.from_buffer_copy(bytes(initial));aa=Complex.from_buffer_copy(bytes(left));bb=Complex.from_buffer_copy(bytes(right)) if right else None;out=Result()
  if alias:out.value=aa if alias==1 else bb
  ap=C.byref(out.value) if alias==1 else C.byref(aa);bp=C.byref(out.value) if alias==2 else C.byref(bb) if bb else None
  host=lib.fx_linalg_dispatch_binary(C.byref(out),C.byref(b),ap,bp,token,C.byref(ctx)) if right else lib.fx_linalg_dispatch_unary(C.byref(out),C.byref(b),ap,token,C.byref(ctx))
  m.reset();settings(m);m.ram[0x80f9]=ctx.calculation_context;m.ram[0x8106]=ctx.numeric.exact_math;m.ram[0x8102]=ctx.numeric.display_mode;m.ram[0x8103]=ctx.numeric.digits;m.ram[0x8125]=initial.temporary_mask
  for i,s in enumerate(initial.slots):m.word(0x80e0+2*i,s.rows+256*s.columns);put(0x829e+90*i,bytes(s.cells))
  # The non-CMPLX parser stores the previous real record on its10-byte value
  # stack. Current right work supplies the preserved imaginary ten bytes.
  put(0x8900,bytes(right or left));put(0x8914,bytes(20));put(0x8078,bytes(left.real));m.er(12,0x8900);m.reg(1,35 if right and token==0x68 else TOKENS[token]);m.reg(6,0);m.reg(10,0);m.reg(11,1 if right else 0)
  polls=0
  # Raw68 decodes unary-log internal32. Parsing its explicit base and
  # second argument changes the prepared logbase selector to35.
  m.lib.harness_set_sp(0x8dee);m.lib.harness_set_lr(0x2fffe);m.lib.harness_set_pc(0x16336)
  for _ in range(200):
   status=m.lib.dispatch_run(3000000,0x2fffe,0x5564)
   if status==100:break
   if status!=104:raise RuntimeError((group,hex(token),status,hex(m.lib.harness_get_pc())))
   polls+=1;m.ram[0x8e00]=2 if polls==ctx.numeric.cancel_at else 0
   assert m.lib.harness_run(1,0x2fffe,False)==103
  else:raise RuntimeError('poll limit')
  native_calls+=1;detail={'label':group,'token':hex(token),'left':bytes(left).hex(),'right':bytes(right).hex() if right else None,'initial_bank':bytes(initial).hex(),'context':bytes(ctx).hex(),'alias':alias}
  check('host',host,0,detail);check('record',bytes(out.value).hex(),bytes(m.ram[0x8900:0x8914]).hex(),detail)
  check('status',out.firmware_status,m.reg(2),detail);check('polls',out.cancellation_checks,polls,detail);check('mask',b.temporary_mask,m.ram[0x8125],detail)
  check('dimensions',bytes(x for s in b.slots for x in [s.rows,s.columns]).hex(),bytes(m.ram[0x80e0:0x80f2]).hex(),detail)
  check('payload',bytes(x for s in b.slots for x in bytes(s.cells)).hex(),bytes(m.ram[0x829e:0x85c8]).hex(),detail)
  if not alias:check('sources',bytes(aa).hex()+(bytes(bb).hex() if bb else ''),bytes(left).hex()+(bytes(right).hex() if right else ''),detail)
 for mode in [6,7]:
  for kind in [0x60,0x90]:
   for identity in range(9):
    for token in UNARY:
     if kind==0x90 and token in [0x5a,0x5b]:continue
     run('unary-slots',bank(mask=0x18 if identity<4 else 0x18|(0x80>>(identity-4))),operand(record(kind,identity,True),dec(71)),None,token,Context(mode,NumericContext(1,0,0,0)),identity%2)
 for mask in range(256):
  for token in [0xc0,0xc1,0x63,0x75,0x76]:
   run('bitmap',bank(mask=mask),operand(record(0x60,0)),None,token)
 for identity in range(4,9):
  for mask in [0,0x80,0xc0,0xe0,0xf0,0xf8,0xff]:
   for cancel in [0,1,2,5,10,20]:
    for token in [0x75,0x76]:
     run('power-storage-alias',bank(3,3,ints,mask),operand(record(0x60,identity,True)),None,token,
         Context(6,NumericContext(1,0,0,cancel)),1)
 for error in range(9,16):
  bad=operand(bytes([0xf0+error])+bytes(9),dec(72));ref=operand(record(0x60),dec(71))
  for token in [0x9e,0x5e,0x9f,0xbe,0xbf,0x68]:
   for left,right in [(ref,bad),(bad,ref)]:run('early-high-error',bank(),left,right,token)
 for error in range(16):
  for kind in [0x60,0x90]:
   for token in [0x2b,0x2d,0x4e,0x4f]:
    for mask in [0,0x18,0xff]:
     bad=operand(bytes([0xf0+error])+bytes(9),dec(72));ref=operand(record(kind),dec(71))
     for left,right in [(ref,bad),(bad,ref)]:run('error-rich-bitmap',bank(mask=mask),left,right,token)
 for rows in range(4):
  for cols in range(4):
   for kind in [0x60,0x90]:
    for token in [0xc0,0xc1,0x63,0xb3,0x60,0x75,0x76,0x77,0x2b,0x2d,0x4e,0x4f,0x9e]:
     run('dimensions',bank(rows,cols),operand(record(kind)),operand(record(kind,1)) if token in BINARY else None,token)
 for index in range(a.random_cases):
  pool=pools[index%4];rows=rng.randrange(4);cols=rng.randrange(4);kind=rng.choice([0x60,0x90]);identity=rng.randrange(9);ctx=Context(6+index%2,NumericContext(index%7!=0,rng.choice([0,4,8,9]),rng.randrange(10),rng.choice([0,0,0,1,2,5,10,20])))
  initial=bank(rows,cols,pool,rng.randrange(256));left=operand(record(kind,identity,index%3==0),rng.choice(ints+marked+errors));token=rng.choice(BINARY+UNARY);right=None
  if token in BINARY:
   rk=rng.choice([0x60,0x90,0]);ri=rng.randrange(9)
   right=operand(record(rk,ri,index%3==1) if rk else rng.choice(pool),rng.choice(ints+marked+errors))
   if index%3==0:left,right=right,left
   if not (left.real.bytes[0]&0xf0 in [0x60,0x90] or right.real.bytes[0]&0xf0 in [0x60,0x90]):continue
  if right is None and kind==0x90 and token in [0x5a,0x5b]:continue
  run('random-'+str(index),initial,left,right,token,ctx,(index%3 if right else index%2))
 # Unsupported tokens and safe host boundaries leave bank and output intact.
 for token in [0x00,0x80,0x88,0xc3]:
  b=bank();prior=bytes(b);out=Result();C.memset(C.byref(out),0xa5,C.sizeof(out));before=bytes(out);x=operand(record(0x60));ctx=Context(6,NumericContext(1,0,0,0))
  h=lib.fx_linalg_dispatch_unary(C.byref(out),C.byref(b),C.byref(x),token,C.byref(ctx))
  check('unsupported',[h,bytes(b).hex(),bytes(out).hex()],[-3,prior.hex(),before.hex()],{'token':token})
 raw=run_raw_regressions(library,build/'raw_oracle',ROOT)
 counts.update(raw['groups']);fail.extend(raw['failures']);native_calls+=raw['native_calls']
 report={'checks':sum(counts.values()),'native_calls':native_calls,'groups':counts,'failures':fail,
  'scope':'Typed rich MATRIX/VECTOR prepared16336 admission, value-stack real transfer, temporary reference rewrite, dispatch, partial bank commit, native cleanup and status/poll propagation.',
  'oracle_context':'Unchanged ROM/CPU; two scalar work records and native10-byte previous-value stack prepared. Explicit RAM8E00 timer cancellation at5564; compare full20-byte output, all18 dimensions, all810 payload bytes, bitmap, nativeR2 and timer polls.',
  'limits':['No second parser or physical key/timer controller; ordinary scalar-only operands returnUNIMPLEMENTED.',
   'Canonical fixed identities0..8, dimension bytes0..3, and no input pointers into mutable bank storage.',
   'Vector-tag REF/RREF select unrelated scalar/base routines after native index adjustment and remainUNIMPLEMENTED; conjugate/argument rich dispatch is outside this module.',
   'Raw mapping regressions at original171F4 use independently hand-built expression trees, not a second parser; final caller error-record construction and preserved imaginary bytes are compared explicitly.'],
  'raw_expression_examples':raw['examples'][:20]}
 if not fail and not a.no_report:report=write_report('analysis/c-verification/linalg_dispatch.json',report,sources+headers+['tools/linalg_raw_cases.py'],'tools/test_linalg_dispatch_c.py')
 print(json.dumps({k:v for k,v in report.items() if k!='tested_inputs_sha256'},indent=2));return bool(fail)
if __name__=='__main__':raise SystemExit(main())
