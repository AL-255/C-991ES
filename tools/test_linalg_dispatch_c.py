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
class Decimal(C.Structure):_fields_=[('sign',C.c_int),('exponent',C.c_int),('mantissa',C.c_uint64),('flags',C.c_uint8)]
TOKENS={0x61:7,0x62:8,0x88:9,0xc3:10,0xc0:13,0xc1:14,0x5a:122,0x5b:123,0x63:11,0xb3:12,0x60:95,0x75:108,0x76:109,0x77:107,
 0x2b:43,0x2d:44,0x4e:45,0x4f:46,0x9e:47,0x5e:101,0x9f:102,0xbe:49,0xbf:50,0x68:32,
 0x98:23,0xa8:25,0xa3:24,0x73:21,0x93:22,0x25:110,0x57:111,0x70:15,0x71:16,0x72:17,
 0x90:18,0x91:19,0x92:20,0xa0:26,0xa1:27,0xa2:28,0xb0:29,0xb1:30,0xb2:31,0x85:112,0x86:113,0x87:114}
BINARY=[0x2b,0x2d,0x4e,0x4f,0x9e,0x5e,0x9f,0xbe,0xbf,0x68]
# Keep the existing deterministic corpus and random stream intact. New
# wrapped61/62 cases have their own explicit boundary and raw-expression groups.
UNARY=[x for x in TOKENS if x not in BINARY and x not in [0x61,0x62]]+[0x68]
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--random-cases',type=int,default=6000);p.add_argument('--no-report',action='store_true');a=p.parse_args()
 build=ROOT/'analysis/build/linalg_dispatch';build.mkdir(parents=True,exist_ok=True)
 sources=['csrc/linalg/fx_linalg_dispatch.c','csrc/numeric/fx_raw_fraction_convert.c','csrc/numeric/fx_raw_decimal_divide.c','csrc/numeric/fx_raw_decimal_parts.c','csrc/numeric/fx_raw_decimal_multiply_add.c','csrc/numeric/fx_raw_decimal_exp.c','csrc/numeric/fx_transcend.c','csrc/numeric/fx_base.c','csrc/linalg/fx_linalg_store.c','csrc/linalg/fx_linalg.c','csrc/linalg/fx_linalg_reduce.c','csrc/complex/fx_complex.c','csrc/complex/fx_complex_round.c','csrc/numeric/fx_numeric.c','csrc/trig/fx_trig_hyperbolic.c']
 headers=[x[:-2]+'.h' for x in sources]+['csrc/numeric/fx_transcend_internal.h','csrc/numeric/fx_transcend_guarded.h','csrc/numeric/fx_base_word.h','csrc/trig/fx_trig.h']
 library=build/'dispatch.so';subprocess.run(['gcc','-std=c99','-O2','-Wall','-Wextra','-Werror','-pedantic','-shared','-fPIC','-I'+str(ROOT/'csrc/numeric'),*(str(ROOT/x) for x in sources),'-o',str(library)],check=True)
 lib=C.CDLL(str(library));lib.fx_decimal_parse.argtypes=[C.POINTER(Number),C.c_char_p];lib.fx_rational_encode.argtypes=[C.POINTER(Number),C.POINTER(Rational)];lib.fx_surd_pack.argtypes=[C.POINTER(Number),C.POINTER(Number)]
 lib.fx_raw_fraction_convert.argtypes=[C.POINTER(Number),C.POINTER(Number)];lib.fx_decimal_decode.argtypes=[C.POINTER(Decimal),C.POINTER(Number)]
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
 def run(group,initial,left,right,token,ctx=None,alias=0,unimplemented=False):
  nonlocal native_calls
  ctx=ctx or Context(6,NumericContext(1,0,0,0))
  b=Bank.from_buffer_copy(bytes(initial));aa=Complex.from_buffer_copy(bytes(left));bb=Complex.from_buffer_copy(bytes(right)) if right else None;out=Result()
  if alias:out.value=aa if alias==1 else bb
  before=bytes(out)
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
  if unimplemented:
   check('wrapped-malformed-host',host,-3,detail)
   check('wrapped-malformed-uncommitted',bytes(out).hex(),before.hex(),detail)
   wanted=b'\xf3'+bytes(9) if token==0x61 else bytes.fromhex('08479405083949380700')
   check('wrapped-malformed-native',bytes(m.ram[0x8900:0x8914]).hex(),(wanted+bytes(left.imaginary)).hex(),detail)
   check('wrapped-malformed-native-status',m.reg(2),3 if token==0x61 else 0,detail)
  else:
   check('host',host,0,detail);check('record',bytes(out.value).hex(),bytes(m.ram[0x8900:0x8914]).hex(),detail)
   check('status',out.firmware_status,m.reg(2),detail);check('polls',out.cancellation_checks,polls,detail)
  check('mask',b.temporary_mask,m.ram[0x8125],detail)
  check('dimensions',bytes(x for s in b.slots for x in [s.rows,s.columns]).hex(),bytes(m.ram[0x80e0:0x80f2]).hex(),detail)
  check('payload',bytes(x for s in b.slots for x in bytes(s.cells)).hex(),bytes(m.ram[0x829e:0x85c8]).hex(),detail)
  if not alias:check('sources',bytes(aa).hex()+(bytes(bb).hex() if bb else ''),bytes(left).hex()+(bytes(right).hex() if right else ''),detail)
 for mode in [6,7]:
  for kind in [0x60,0x90]:
   for identity in range(9):
    for token in UNARY:
     run('unary-slots',bank(mask=0x18 if identity<4 else 0x18|(0x80>>(identity-4))),operand(record(kind,identity,True),dec(71)),None,token,Context(mode,NumericContext(1,0,0,0)),identity%2)
 for mode in [6,7]:
  for identity in range(9):
   for mask in [0,0x18,0x80,0xc0,0xe0,0xf0,0xf8,0xff]:
    for token in [0x88,0xc3,0x5a,0x5b]:
     run('rich-vector-gap',bank(mask=mask),operand(record(0x90,identity,True),dec(71)),None,token,Context(mode,NumericContext(1,0,0,0)),identity%2)
 for byte in range(256):
  for token in [0x88,0x5a,0x5b]:
   run('rich-vector-metadata',bank(mask=byte),operand(bytes([0x90])+bytes([byte])*9,dec(71)),None,token)
 for mode in [6,7]:
  for identity in range(9):
   for mask in [0,0x18,0x80,0xc0,0xe0,0xf0,0xf8,0xff]:
    for token in [0x88,0xc3]:
     run('rich-matrix-gap',bank(mask=mask),operand(record(0x60,identity,True),dec(71)),None,token,Context(mode,NumericContext(1,0,0,0)),identity%2)
 for n in ['64a20000000000000301','641a2000000000000401','64a1a200000000000501','64a2a300000000000501','64533563da9e9f2b07de','64082a55de3d0167061b','64ffffffffffffff0f01','64000000000000000000','64aaabacadaeafba0806','640123456789abcd1401','65fdd922136163e51251','6835c3cf7c9cf9110fb9','65a32e1337ec518a11b6','66545dd3aded35740db6','662f950dfb9b879c0f41']:
  n=bytes.fromhex(n)
  run('rich-matrix-exp-metadata',bank(mask=0),operand(n,dec(71)),None,0x88)
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
  run('random-'+str(index),initial,left,right,token,ctx,(index%3 if right else index%2))
 # Unsupported tokens and safe host boundaries leave bank and output intact.
 for token in [0x00,0x80]:
  b=bank();prior=bytes(b);out=Result();C.memset(C.byref(out),0xa5,C.sizeof(out));before=bytes(out);x=operand(record(0x60));ctx=Context(6,NumericContext(1,0,0,0))
  h=lib.fx_linalg_dispatch_unary(C.byref(out),C.byref(b),C.byref(x),token,C.byref(ctx))
  check('unsupported',[h,bytes(b).hex(),bytes(out).hex()],[-3,prior.hex(),before.hex()],{'token':token})
 # Raw61/62 wrap to inverse-hyperbolic leaves after rich staging. Ordinary
 # reference metadata has a zero denominator, but valid marked fractions
 # loaded through scalarA must execute their real finite numerical path.
 for mode in [6,7]:
  for kind in [0x60,0x90]:
   for identity in range(9):
    for mask in [0,0x18,0x80,0xc0,0xe0,0xf0,0xf8,0xff]:
     for token in [0x61,0x62]:
      run('wrapped-logical-slots',bank(mask=mask),operand(record(kind,identity),dec(71)),None,token,
          Context(mode,NumericContext(1,0,0,0)),identity%2)
 for mask in range(256):
  for kind in [0x60,0x90]:
   for token in [0x61,0x62]:
    run('wrapped-logical-bitmap',bank(mask=mask),operand(record(kind),dec(71)),None,token)
 metadata=[bytes.fromhex(x) for x in [
  '61a20000000000000301','61a30000000000000301','61a90000000000000301',
  '61a1a200000000000501','61a30000000000000306','62a30000000000000301',
  '61a40000000000000301','61a40000000000000306',
  '61000001a40000001501','61999999a50000001501','61000000a40000001501']]
 for mode in [6,7]:
  for identity in range(9):
   for raw in metadata:
    rich=bytes([0x60|identity])+raw[1:]
    for token in [0x61,0x62]:
     run('wrapped-marked-metadata',bank(mask=0x18|(0x80>>(identity-4)) if identity>=4 else 0x18),
         operand(rich,dec(71)),None,token,Context(mode,NumericContext(1,0,0,0)),identity%2)
 # This malformed finite conversion is independently rejected by the frozen
 # ordinary decimal decoder. Native acosh returns F3; atanh returns a finite
 # record. The typed API leaves both results uncommitted while retaining the
 # exact prior allocation/bank copy, rather than inventing a Math error.
 malformed=Number.from_buffer_copy(bytes.fromhex('6441d755588230e80fb0'));converted=Number();decoded=Decimal()
 check('wrapped-malformed-convert-host',lib.fx_raw_fraction_convert(C.byref(converted),C.byref(malformed)),0,{})
 check('wrapped-malformed-converted',bytes(converted).hex(),'08479404a83949380700',{})
 check('wrapped-malformed-decimal-boundary',lib.fx_decimal_decode(C.byref(decoded),C.byref(converted)),-1,{})
 for mode in [6,7]:
  for token in [0x61,0x62]:
   for alias in [0,1]:
    run('wrapped-malformed-boundary',bank(mask=0x18),operand(bytes.fromhex('6141d755588230e80fb0'),dec(71)),
        None,token,Context(mode,NumericContext(1,0,0,0)),alias,True)
 wrapped_examples=[]
 def raw_wrapped(initial,token,tokens,mode,real=None,nested=False):
  nonlocal native_calls
  ctx=Context(mode,NumericContext(1,0,0,0));b=Bank.from_buffer_copy(bytes(initial));out=Result();host_polls=0
  if nested:
   left=operand(bytes([0x60 if initial.slots[0].rows==2 else 0x90])+bytes(9),bytes([0xee])*10)
   right=operand(bytes([left.real.bytes[0]+1])+bytes(9),bytes([0xee])*10)
   h=lib.fx_linalg_dispatch_binary(C.byref(out),C.byref(b),C.byref(left),C.byref(right),0x2b,C.byref(ctx))
   check('wrapped-raw-sum-host',h,0,{'tokens':tokens.hex(),'mode':mode})
   check('wrapped-raw-sum-status',out.firmware_status,0,{'tokens':tokens.hex(),'mode':mode})
   host_polls=out.cancellation_checks
   value=Complex.from_buffer_copy(bytes(out.value))
  else:value=operand(real,bytes([0xee])*10)
  h=lib.fx_linalg_dispatch_unary(C.byref(out),C.byref(b),C.byref(value),token,C.byref(ctx))
  host_polls+=out.cancellation_checks
  actual=(bytes([0xf0|out.firmware_status])+bytes(9) if out.firmware_status else bytes(out.value.real))+bytes([0xee])*10
  m.reset();settings(m)
  for address,v in [(0x80f9,mode),(0x80fa,0),(0x80fc,1),(0x8105,4),(0x8106,1)]:m.ram[address]=v
  for identity,slot in enumerate(initial.slots):m.word(0x80e0+2*identity,slot.rows+256*slot.columns);put(0x829e+90*identity,bytes(slot.cells))
  variables=b''.join(dec(i+2) for i in range(10));put(0x8226,variables)
  if b'A' in tokens:put(0x823a,real);variables=variables[:20]+real+variables[30:]
  put(0x8900,bytes([0xee])*20);put(0x8600,tokens+b'\0');m.word(0x8190,0x8600)
  m.er(0,0x8190);m.er(2,0x8900);m.lib.harness_set_sp(0x8dee);m.lib.harness_set_lr(0x2fffe);m.lib.harness_set_pc(0x171f4)
  polls=0
  for _ in range(200):
   stop=m.lib.dispatch_run(3000000,0x2fffe,0x5564)
   if stop==100:break
   if stop!=104:raise RuntimeError(('wrapped-raw',stop,hex(m.lib.harness_get_pc())))
   polls+=1;m.ram[0x8e00]=0;assert m.lib.harness_run(1,0x2fffe,False)==103
  else:raise RuntimeError('wrapped-raw poll limit')
  native_calls+=1;detail={'tokens':tokens.hex(),'mode':mode,'real':real.hex() if real else None,'nested':nested}
  check('wrapped-raw-host',h,0,detail);check('wrapped-raw-record',actual.hex(),bytes(m.ram[0x8900:0x8914]).hex(),detail)
  check('wrapped-raw-status',out.firmware_status,m.reg(0),detail)
  check('wrapped-raw-cursor',m.word(0x8190)-0x8600,len(tokens)-1 if out.firmware_status else len(tokens)+1,detail)
  check('wrapped-raw-polls',host_polls,polls,detail)
  check('wrapped-raw-mask',b.temporary_mask,m.ram[0x8125],detail)
  check('wrapped-raw-dimensions',bytes(v for s in b.slots for v in (s.rows,s.columns)).hex(),bytes(m.ram[0x80e0:0x80f2]).hex(),detail)
  check('wrapped-raw-payload',bytes(v for s in b.slots for v in bytes(s.cells)).hex(),bytes(m.ram[0x829e:0x85c8]).hex(),detail)
  check('wrapped-raw-variables',bytes(m.ram[0x8226:0x828a]).hex(),variables.hex(),detail)
  check('wrapped-raw-input',bytes(m.ram[0x8600:0x8600+len(tokens)+1]).hex(),(tokens+b'\0').hex(),detail)
  if real and b'A' in tokens:wrapped_examples.append(dict(detail,record20=bytes(m.ram[0x8900:0x8914]).hex(),status=m.reg(0),mask=m.ram[0x8125],polls=polls))
 for mode in [6,7]:
  for kind,base,rows,cols in [(0x60,0xc8,2,2),(0x90,0xcc,1,3)]:
   for token in [0x61,0x62]:
    for identity in range(4):
     initial=bank(rows,cols,ints,0x18 if mode==6 else 0)
     raw_wrapped(initial,token,bytes([token,base+identity,0x29]),mode,bytes([kind|identity])+bytes(9))
    raw_wrapped(bank(rows,cols,ints,0x18 if mode==6 else 0),token,
                bytes([token,0x28,base,0x2b,base+1,0x29,0x29]),mode,nested=True)
  for rich in metadata:
   for token in [0x61,0x62]:raw_wrapped(bank(mask=0x18 if mode==6 else 0),token,bytes([token,0x41,0x29]),mode,rich)
 raw=run_raw_regressions(library,build/'raw_oracle',ROOT)
 counts.update(raw['groups']);fail.extend(raw['failures']);native_calls+=raw['native_calls']
 report={'checks':sum(counts.values()),'native_calls':native_calls,'groups':counts,'failures':fail,
  'scope':'Typed rich MATRIX/VECTOR prepared16336 admission, value-stack real transfer, temporary reference rewrite, dispatch, partial bank commit, native cleanup and status/poll propagation.',
  'oracle_context':'Unchanged ROM/CPU; two scalar work records and native10-byte previous-value stack prepared. Explicit RAM8E00 timer cancellation at5564; compare full20-byte output, all18 dimensions, all810 payload bytes, bitmap, nativeR2 and timer polls.',
  'limits':['No second parser or physical key/timer controller; ordinary scalar-only operands returnUNIMPLEMENTED.',
   'Canonical fixed identities0..8, dimension bytes0..3, and no input pointers into mutable bank storage.',
   'Rich61/62 malformed converted finite digits outside the ordinary hyperbolic helper returnUNIMPLEMENTED after native staging, with uncommitted output. The canonical witness includes a native finite atanh return, separately from numerical errors/non-return.',
   'Raw mapping regressions at original171F4 use independently hand-built expression trees, not a second parser; final caller error-record construction and preserved imaginary bytes are compared explicitly.'],
  'raw_expression_examples':raw['examples'][:20],
  'wrapped_metadata_examples':wrapped_examples}
 if not fail and not a.no_report:report=write_report('analysis/c-verification/linalg_dispatch.json',report,sources+headers+['tools/linalg_raw_cases.py','tools/trace_natural_result.py','tools/c_verification.py'],'tools/test_linalg_dispatch_c.py')
 print(json.dumps({k:v for k,v in report.items() if k!='tested_inputs_sha256'},indent=2));return bool(fail)
if __name__=='__main__':raise SystemExit(main())
