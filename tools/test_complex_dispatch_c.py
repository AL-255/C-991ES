#!/usr/bin/env python3
"""Native CMPLX operator/unary dispatch records, status and cleanup parity."""
import argparse,ctypes as C,json,random,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from nxu8.machine import Machine
from trace_natural_result import settings
from c_verification import write_report
from datetime import datetime,timezone
class Number(C.Structure): _fields_=[('bytes',C.c_uint8*10)]
class Complex(C.Structure): _fields_=[('real',Number),('imaginary',Number)]
class Context(C.Structure): _fields_=[(x,C.c_uint8) for x in ['calculation_context','exact_math','angle_unit','display_mode','digits']]
class Rational(C.Structure): _fields_=[('numerator',C.c_int64),('denominator',C.c_uint64),('flags',C.c_uint8)]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--random-cases',type=int,default=1200)
parser.add_argument('--decimal-cases',type=int,default=1500)
parser.add_argument('--no-report',action='store_true')
args=parser.parse_args()
build=ROOT/'analysis/build/complex-dispatch'
build.mkdir(parents=True,exist_ok=True)
SOURCES=['complex/fx_complex_dispatch.c','complex/fx_complex.c','complex/fx_complex_angle.c','complex/fx_complex_round.c','numeric/fx_numeric.c','numeric/fx_transcend.c','numeric/fx_power.c','numeric/fx_root.c','numeric/fx_combinatorics.c','numeric/fx_logbase.c','trig/fx_trig.c','trig/fx_trig_math.c','trig/fx_trig_inverse.c','trig/fx_trig_hyperbolic.c']
subprocess.run(['gcc','-std=c99','-O2','-Wall','-Wextra','-Werror','-pedantic','-shared','-fPIC',*[str(ROOT/'csrc'/p) for p in SOURCES],'-o',str(build/'complex-dispatch.so')],check=True)
lib=C.CDLL(str(build/'complex-dispatch.so'));ptr=C.POINTER(Complex);ctxptr=C.POINTER(Context);byteptr=C.POINTER(C.c_uint8)
lib.fx_complex_dispatch_binary.argtypes=[ptr,ptr,ptr,C.c_uint8,ctxptr,byteptr]
lib.fx_complex_dispatch_unary.argtypes=[ptr,ptr,C.c_uint8,ctxptr,byteptr]
lib.fx_complex_dispatch_cleanup.argtypes=[ptr,ptr,C.c_uint8,ctxptr,byteptr]
lib.fx_decimal_parse.argtypes=[C.POINTER(Number),C.c_char_p]
lib.fx_rational_encode.argtypes=[C.POINTER(Number),C.POINTER(Rational)]
lib.fx_surd_pack.argtypes=[C.POINTER(Number),C.POINTER(Number)]
def dec(x):
 n=Number();assert lib.fx_decimal_parse(C.byref(n),str(x).encode())==0;return bytes(n)
def rat(n,d,flags=0):
 o=Number();assert lib.fx_rational_encode(C.byref(o),C.byref(Rational(n,d,flags)))==0;return bytes(o)
def surd(v):
 o=Number();parts=(Number*6)(*[Number.from_buffer_copy(dec(x)) for x in v]);assert lib.fx_surd_pack(C.byref(o),parts)==0;return bytes(o)
m=Machine((ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes(),build/'oracle')
tokens={0x9f:102,0xbe:49,0xbf:50,0x2b:43,0x2d:44,0x4e:45,0x4f:46,0x5e:101,0x60:95,0x63:11,0x68:32,0x70:15,0x71:16,0x72:17,0x73:21,0x75:108,0x76:109,0x77:107,0x85:112,0x86:113,0x87:114,0x88:9,0x90:18,0x91:19,0x92:20,0x93:22,0x57:111,0x98:23,0xa0:26,0xa1:27,0xa2:28,0xa3:24,0xa8:25,0xb0:29,0xb1:30,0xb2:31,0xb3:12,0xc3:10,0x25:110}
BINARY=[0x2b,0x2d,0x4e,0x4f,0x5e,0x9f,0xbe,0xbf,0x68]
counts={};failures=[]
def oracle(a,b,token,ctx):
 m.reset();settings(m);m.ram[0x80f9]=ctx.calculation_context;m.ram[0x8105]=ctx.angle_unit;m.ram[0x8106]=ctx.exact_math;m.ram[0x8102]=ctx.display_mode;m.ram[0x8103]=ctx.digits;m.ram[0x810c]=0
 for i,x in enumerate(a+(b or bytes(20))):m.ram[0x8300+i]=x
 m.er(12,0x8300);m.er(0,0x8300);m.er(2,0x8314);m.reg(6,0xc4);m.reg(10,0)
 if b is None:
  if token not in [0x60]:
   flags=255 if token in [0x63,0x88,0xc3,0xb3] else 1 if token in [0x75,0x76,0x77] else 7
   m.reg(0,flags);m.call(0x16a14)
   if m.reg(2):return a,m.reg(2)
  entries={0x60:0x15d4e,0x63:0x1cade,0x88:0x186f4,0xc3:0x18708,0x98:0x1cbfc,0x75:0x1869e,0x76:0x18672,0x77:0x15f8a,0xb3:0x15d36,0xa0:0x16268,0xa1:0x16272,0xa2:0x16308,0xa3:0x1c242,
   0x70:0x1c532,0x71:0x1c520,0x72:0x1c50e,0x73:0x1c22e,
   0x90:0x1c4fc,0x91:0x1c4ea,0x92:0x1c4d8,0x93:0x1c21a,
   0x68:0x1c256,0xa8:0x1c878,0xb0:0x1c568,0xb1:0x1c556,0xb2:0x1c544,
   0x85:0x16194,0x86:0x16198,0x87:0x1619c,0x25:0x16182,0x57:0x1c1a2}
  m.er(0,0x8300);m.er(2,0);m.er(4,0)
  m.call(entries[token],limit=3000000)
 else:
  if token in [0x9f,0xbe,0xbf,0x68]:
   for pointer in [0x8314,0x8300]:
    m.er(12,pointer);m.reg(0,7);m.call(0x16a14)
    if m.reg(2):return a,m.reg(2)
   m.er(12,0x8300);m.er(0,0x8300);m.er(2,0x8314)
  entries={0x9f:0x1122c,0xbe:0x1c0aa,0xbf:0x1c096,0x68:0x1c082,0x2b:0x15f9e,0x2d:0x15fb2,0x4e:0x15fc6,0x4f:0x1602a,0x5e:0x15f00}
  m.call(entries[token],limit=3000000)
 # Enter the native cleanup continuation with a manually prepared saved LR.
 m.reg(1,ctx.calculation_context);m.word(0x8dee,0xfffe);m.word(0x8df0,2)
 m.call(0x16562,limit=3000000)
 return bytes(m.ram[0x8300:0x8314]),m.reg(2)
def check(group,a,b,token,ctx=Context(0xc4,1,4,0,0),alias=False):
 expected,fw=oracle(a,b,token,ctx)
 aa=Complex.from_buffer_copy(a);bb=Complex.from_buffer_copy(b) if b else None;out=Complex();status=C.c_uint8(0xab)
 host=lib.fx_complex_dispatch_binary(C.byref(out),C.byref(aa),C.byref(bb),token,C.byref(ctx),C.byref(status)) if b else lib.fx_complex_dispatch_unary(C.byref(out),C.byref(aa),token,C.byref(ctx),C.byref(status))
 actual=[host,bytes(out).hex(),status.value,bytes(aa).hex()];want=[0,expected.hex(),fw,a.hex()]
 counts[group]=counts.get(group,0)+1
 if actual!=want:
  failures.append(dict(group=group,token=hex(token),left=a.hex(),right=b.hex() if b else None,context=bytes(ctx).hex(),actual=actual,expected=want))
  if len(failures)<8:print(json.dumps(failures[-1]))
 if alias:
  for target in ['left','right'] if b else ['left']:
   aa=Complex.from_buffer_copy(a);bb=Complex.from_buffer_copy(b) if b else None;out=aa if target=='left' else bb;status=C.c_uint8(0xab)
   host=lib.fx_complex_dispatch_binary(C.byref(out),C.byref(aa),C.byref(bb),token,C.byref(ctx),C.byref(status)) if b else lib.fx_complex_dispatch_unary(C.byref(out),C.byref(aa),token,C.byref(ctx),C.byref(status))
   actual=[host,bytes(out).hex(),status.value];want=[0,expected.hex(),fw]
   counts['alias_'+target]=counts.get('alias_'+target,0)+1
   if actual!=want:failures.append(dict(group='alias_'+target,token=hex(token),left=a.hex(),right=b.hex() if b else None,actual=actual,expected=want))
zero=dec(0);one=dec(1);markzero=b'\x40'+bytes(9)
surd_zero=surd([1,2,1,-1,2,1])
recs=[bytes([dec('1.23456789012345')[0]|0x40])+dec('1.23456789012345')[1:]]+[dec(x) for x in ['0','1','-1','2','-2','3','4','.5','1.23456789012345','1e-99','1e99']]+[markzero,rat(1,3),rat(-1,3),rat(1,3,0x40),surd([1,2,1,0,1,1]),surd_zero]+[bytes([0xf0|x])+bytes(9) for x in range(16)]
for a in recs:
 for imag in [zero,markzero,one,recs[-1],surd_zero]:
  for token in [t for t in tokens if t not in BINARY or t == 0x68]:check('unary-boundary',a+imag,None,token,alias=imag==zero)
for a in recs:
 for b in recs:
  for imag in [zero,one,markzero]:
   for token in BINARY:check('binary-boundary',a+imag,b+zero,token)
for a in recs:
 for imag in recs:
  check('multiply-i',a+imag,zero+one,0x4e)
# Cleanup continuation is checked independently of any operation's result.
for context in [0xc4,0xc1,0x02]:
 for a in recs:
  for b in recs:
   for leaf in [0,3,0x30]:
    raw=a+b;ctx=Context(context,1,4,0,0)
    m.reset();settings(m);m.ram[0x80f9]=context
    for i,x in enumerate(raw):m.ram[0x8300+i]=x
    m.er(12,0x8300);m.reg(0,leaf);m.reg(1,context)
    m.word(0x8dee,0xfffe);m.word(0x8df0,2);m.call(0x16562)
    expected=bytes(m.ram[0x8300:0x8314]);fw=m.reg(2)
    aa=Complex.from_buffer_copy(raw);out=Complex();status=C.c_uint8(0xab)
    host=lib.fx_complex_dispatch_cleanup(C.byref(out),C.byref(aa),leaf,C.byref(ctx),C.byref(status))
    counts['context-cleanup']=counts.get('context-cleanup',0)+1
    actual=[host,bytes(out).hex(),status.value,bytes(aa).hex()];want=[0,expected.hex(),fw,raw.hex()]
    if actual!=want:failures.append(dict(group='context-cleanup',left=raw.hex(),context=context,leaf=leaf,actual=actual,expected=want))
# A successful leaf may leave a value whose integer cleanup carries exponent99
# into Math ERROR. Compare the complete continuation, including early errors,
# scalar-context imaginary preservation, marked-real routing and alias output.
overflow=bytes.fromhex('09999999999999999901')
negative_overflow=overflow[:-1]+b'\x06'
marked_overflow=bytes([overflow[0]|0x40])+overflow[1:]
near_overflow=[overflow,negative_overflow,marked_overflow,
               bytes.fromhex('09999999999999919901'),
               bytes.fromhex('09999999999999909901'),
               bytes.fromhex('09999999999999919801')]
cleanup_examples=[]
cleanup_pairs=[]
for value in near_overflow:
 for companion in [zero,one,b'\xf0'+bytes(9),b'\xf3'+bytes(9)]:
  cleanup_pairs.extend([value+companion,companion+value])
for context in [0xc4,0xc1,0x02]:
 for raw in cleanup_pairs:
  for leaf in [0,3,0x30]:
   ctx=Context(context,1,4,8,0)
   m.reset();settings(m);m.ram[0x80f9]=context;m.ram[0x8102]=8;m.ram[0x8103]=0
   for i,x in enumerate(raw):m.ram[0x8300+i]=x
   m.er(12,0x8300);m.reg(0,leaf);m.reg(1,context)
   m.word(0x8dee,0xfffe);m.word(0x8df0,2);m.call(0x16562)
   expected=bytes(m.ram[0x8300:0x8314]);fw=m.reg(2)
   for alias in [False,True]:
    source=Complex.from_buffer_copy(raw);out=source if alias else Complex();status=C.c_uint8(0xab)
    host=lib.fx_complex_dispatch_cleanup(C.byref(out),C.byref(source),leaf,C.byref(ctx),C.byref(status))
    counts['cleanup-overflow-continuation']=counts.get('cleanup-overflow-continuation',0)+1
    actual=[host,bytes(out).hex(),status.value];want=[0,expected.hex(),fw]
    if not alias:actual.append(bytes(source).hex());want.append(raw.hex())
    if actual!=want:failures.append(dict(group='cleanup-overflow-continuation',left=raw.hex(),context=context,leaf=leaf,alias=alias,actual=actual,expected=want))
   if leaf==0 and raw in [overflow+one,one+overflow,marked_overflow+one]:
    cleanup_examples.append(dict(context=context,input20=raw.hex(),result20=expected.hex(),status=fw))
for value in [overflow,negative_overflow,marked_overflow]:
 for imaginary in [zero,one,overflow,b'\xf0'+bytes(9),b'\xf3'+bytes(9)]:
  for digits in [0,9]:
   check('display-round-cleanup-overflow',value+imaginary,None,0xb3,Context(0xc4,1,4,8,digits),alias=True)
rng=random.Random(0x16562)
for index in range(args.random_cases):
 a=rng.choice(recs)+rng.choice(recs);b=rng.choice(recs)+rng.choice(recs)
 token=rng.choice(BINARY)
 ctx=Context(0xc4,rng.randrange(2),4+rng.randrange(3),rng.choice([0,4,8,9]),rng.randrange(10))
 check('binary-random',a,b,token,ctx,alias=index<50)
 token=rng.choice([t for t in tokens if t not in BINARY or t == 0x68])
 check('unary-random',a,None,token,ctx,alias=index<50)
for mode in [0,4,8,9]:
 for digits in range(10):
  for unit in [4,5,6]:
   check('display-round-context',dec('1.23456789012345')+dec('-0.56789999999995'),None,0xb3,Context(0xc4,1,unit,mode,digits),alias=digits==0)
# Arbitrary full fifteen-digit decimals cover mantissa/exponent truncation.
for index in range(args.decimal_cases):
 def raw_decimal():
  n=Number();parts=str(rng.randrange(10**14,10**15));exponent=rng.randrange(-99,100)
  raw=bytes([int(parts[0])|(0x40 if rng.randrange(9)==0 else 0),*[int(parts[j:j+2],16) for j in range(1,15,2)],int(f'{exponent%100:02d}',16),(exponent>=0)+(5 if rng.randrange(2) else 0)])
  return raw
 a=raw_decimal()+raw_decimal();b=raw_decimal()+raw_decimal()
 check('binary-decimal-coordinates',a,b,rng.choice(BINARY),alias=index<25)
for base in ['-32','32','-2','.123456789012345','1.23456789012345','1e-99','1e99']:
 for exponent in [dec(x) for x in ['-1','2','3','4','-4','.5','-.5','1.23456789012345']] + [rat(1,3),rat(2,3),rat(1,5)]:
  for imaginary in [zero,markzero]:
   check('real-power-fallback',dec(base)+imaginary,exponent+zero,0x5e,alias=True)
# Imaginary-unit input token80 is checked at the parser boundary, oracle-only.
lib.fx_complex_dispatch_constant.argtypes=[ptr,C.c_uint8,ctxptr,byteptr]
m.reset();settings(m);m.ram[0x80f9]=0xc4;m.ram[0x8200]=0x80;m.ram[0x8201]=0;m.word(0x8190,0x8200);m.er(0,0x8190);m.er(2,0x8300);m.call(0x171f4)
out=Complex();fw=C.c_uint8();ctx=Context(0xc4,1,4,0,0);host=lib.fx_complex_dispatch_constant(C.byref(out),0x80,C.byref(ctx),C.byref(fw))
counts['imaginary-unit']=1
if [host,bytes(out),fw.value]!=[0,bytes(m.ram[0x8300:0x8314]),m.reg(0)]:failures.append(dict(group='imaginary-unit'))
# The ordinary pending-operator continuation proves the selected token table
# leaves before rich tagged-record rewriting is needed. Unary16336 saves LR;
# binary16340 takes arity2 and an explicit saved return address.
for token in [t for t in tokens if t not in [0x9f,0xbe,0xbf,0x68]]:
 for imaginary in [zero,one]:
  raw=dec(3)+imaginary;right=dec(1)+dec(2)
  unary=token not in BINARY
  m.reset();settings(m);m.ram[0x80f9]=0xc4;m.ram[0x8105]=4
  for i,x in enumerate(raw+right):m.ram[0x8300+i]=x
  m.er(12,0x8300);m.er(2,0x8314);m.reg(1,tokens[token]);m.reg(6,0);m.reg(10,0)
  if unary:m.call(0x16336,limit=3000000)
  else:
   m.reg(5,2);m.word(0x8dee,0xfffe);m.word(0x8df0,2);m.call(0x16340,limit=3000000)
  expected=bytes(m.ram[0x8300:0x8314]);expected_status=m.reg(2)
  source=Complex.from_buffer_copy(raw);other=Complex.from_buffer_copy(right);out=Complex();fw=C.c_uint8(0xab)
  ctx=Context(0xc4,1,4,0,0)
  host=lib.fx_complex_dispatch_unary(C.byref(out),C.byref(source),token,C.byref(ctx),C.byref(fw)) if unary else lib.fx_complex_dispatch_binary(C.byref(out),C.byref(source),C.byref(other),token,C.byref(ctx),C.byref(fw))
  counts['ordinary-pending-dispatch']=counts.get('ordinary-pending-dispatch',0)+1
  actual=[host,bytes(out).hex(),fw.value];want=[0,expected.hex(),expected_status]
  if actual!=want:failures.append(dict(group='ordinary-pending-dispatch',token=hex(token),left=raw.hex(),actual=actual,expected=want))
# Raw-token regression: only57 is the factorial input token. Token97 is
# rejected by the original parser before any numeric factorial leaf executes.
def evaluator(tokens):
 m.reset();settings(m);m.ram[0x80f9]=0xc4;m.ram[0x8105]=4
 for i,x in enumerate(tokens):m.ram[0x8200+i]=x
 m.word(0x8190,0x8200);m.er(0,0x8190);m.er(2,0x8300);m.call(0x171f4,limit=3000000)
 return m.reg(0),bytes(m.ram[0x8300:0x8314]),m.word(0x8190)-0x8200
for expression,operand,token in [(b'3\x57\0',dec(3)+zero,0x57),
                                (b'\x633+4\x80)\0',dec(3)+dec(4),0x63),
                                (b'\x883+4\x80)\0',dec(3)+dec(4),0x88),
                                (b'\xc33+4\x80)\0',dec(3)+dec(4),0xc3)]:
 expected_status,expected,_=evaluator(expression)
 source=Complex.from_buffer_copy(operand);out=Complex();fw=C.c_uint8(0xab)
 host=lib.fx_complex_dispatch_unary(C.byref(out),C.byref(source),token,C.byref(ctx),C.byref(fw))
 counts['raw-token-normalization']=counts.get('raw-token-normalization',0)+1
 actual=[host,bytes(out).hex(),fw.value];want=[0,expected.hex(),expected_status]
 if actual!=want:failures.append(dict(group='raw-token-normalization',expression=expression.hex(),actual=actual,expected=want))
expected_status,_,cursor=evaluator(b'3\x97\0')
source=Complex.from_buffer_copy(dec(3)+zero);out=Complex.from_buffer_copy(dec(7)+dec(8));fw=C.c_uint8(0xab)
host=lib.fx_complex_dispatch_unary(C.byref(out),C.byref(source),0x97,C.byref(ctx),C.byref(fw))
counts['raw-nonfactorial-rejection']=1
if [expected_status,cursor,host,bytes(out),fw.value]!=[2,1,-3,dec(7)+dec(8),0xab]:
 failures.append(dict(group='raw-nonfactorial-rejection',native_status=expected_status,cursor=cursor,host=host,output=bytes(out).hex(),firmware_status=fw.value))
# A9x real header is rejected by flags1 before postfix powers read its payload.
for header in [0x90,0x91,0x9f]:
 for token in [0x75,0x76,0x77]:
  check('dms-power-admission',bytes([header])+bytes(9)+zero,None,token,alias=True)
# Upstream C4 admission rejects complex operands on either side of each
# real-only binary function; retain the original parser's error cursor too.
for expression,token,left,right,cursor in [
 (b'2\x80\xbe1\0',0xbe,zero+dec(2),one+zero,4),
 (b'2\xbe\x80\0',0xbe,dec(2)+zero,zero+one,3),
 (b'2\x80\x9f4)\0',0x9f,zero+dec(2),dec(4)+zero,4),
 (b'2\x9f\x80)\0',0x9f,dec(2)+zero,zero+one,3),
 (b'\x682,\x80)\0',0x68,dec(2)+zero,zero+one,4),
 (b'\x68\x80,2)\0',0x68,zero+one,dec(2)+zero,4),
 (b'2\x80\xbf1\0',0xbf,zero+dec(2),one+zero,4),
 (b'2\xbf\x80\0',0xbf,dec(2)+zero,zero+one,3)]:
 native_status,_,native_cursor=evaluator(expression)
 source=Complex.from_buffer_copy(left);other=Complex.from_buffer_copy(right);out=Complex();fw=C.c_uint8(0xab)
 host=lib.fx_complex_dispatch_binary(C.byref(out),C.byref(source),C.byref(other),token,C.byref(ctx),C.byref(fw))
 counts['raw-real-only-rejection']=counts.get('raw-real-only-rejection',0)+1
 actual=[native_status,native_cursor,host,bytes(out).hex(),fw.value]
 want=[3,cursor,0,left.hex(),3]
 if actual!=want:failures.append(dict(group='raw-real-only-rejection',expression=expression.hex(),actual=actual,expected=want))
for expression,token,left,right in [
 (b'5\xbe2\0',0xbe,dec(5)+zero,dec(2)+zero),
 (b'5\xbf2\0',0xbf,dec(5)+zero,dec(2)+zero),
 (b'2\x9f4)\0',0x9f,dec(2)+zero,dec(4)+zero),
 (b'\x682,8)\0',0x68,dec(2)+zero,dec(8)+zero)]:
 native_status,native_output,_=evaluator(expression)
 source=Complex.from_buffer_copy(left);other=Complex.from_buffer_copy(right);out=Complex();fw=C.c_uint8(0xab)
 host=lib.fx_complex_dispatch_binary(C.byref(out),C.byref(source),C.byref(other),token,C.byref(ctx),C.byref(fw))
 counts['raw-real-only-success']=counts.get('raw-real-only-success',0)+1
 actual=[host,bytes(out).hex(),fw.value];want=[0,native_output.hex(),native_status]
 if actual!=want:failures.append(dict(group='raw-real-only-success',expression=expression.hex(),actual=actual,expected=want))
 check('real-only-binary-alias',left,right,token,alias=True)
total=sum(counts.values())
report={'scope':'Prepared CMPLX value dispatch: native16A14 unary admission, scalar/complex leaves,16562 context cleanup, binaryzero classification, i rotation and original numeric return status; parser163F0 tagged-record rewriting is excluded',
        'oracle':'Extracted firmware through the independent test-only nX-U8 machine',
        'cases':counts,'total_cases':total,'failures':failures,
        'cleanup_overflow_examples':cleanup_examples,
        'timestamp_utc':datetime.now(timezone.utc).isoformat(),
        'complete':False,'full_firmware_complete':False}
if failures:
    (build/'failures.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'total_cases':total,'failures':len(failures),'artifact':str(build/'failures.json')}))
    raise SystemExit(1)
if not args.no_report:
    headers=['complex/fx_complex_dispatch.h','complex/fx_complex.h','complex/fx_complex_angle.h',
             'complex/fx_complex_round.h','numeric/fx_numeric.h','numeric/fx_transcend.h',
             'numeric/fx_transcend_internal.h','numeric/fx_transcend_guarded.h',
             'numeric/fx_root.h','numeric/fx_combinatorics.h','numeric/fx_logbase.h',
             'trig/fx_trig.h','trig/fx_trig_math.h','trig/fx_trig_inverse.h','trig/fx_trig_hyperbolic.h']
    write_report('analysis/c-verification/complex_dispatch.json',report,
                 ['csrc/'+p for p in SOURCES+headers]+['tools/trace_natural_result.py','tools/c_verification.py'],'tools/test_complex_dispatch_c.py')
print(json.dumps({'status':'pass','total_cases':total,'cases':counts,'full_firmware_complete':False}))
