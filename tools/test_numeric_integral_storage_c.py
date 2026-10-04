#!/usr/bin/env python3
"""Fresh original-ROM verification of the physical real integral driver.
GPL-3.0-or-later. No held expected outputs are used."""
import ctypes as C,gzip,hashlib,json,subprocess,sys
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
import argparse
from c_verification import write_report
from c_build_inputs import implementation_inputs
ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--optimization',choices=['O2','O3'],default='O2');ap.add_argument('--no-report',action='store_true');args=ap.parse_args()
HERE=ROOT/'analysis/build/numeric/integral-storage';HERE.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(ROOT/'tools'))
from nxu8.machine import Machine
from test_numeric_calculus_c import Number,Rational,Pointer,Function,Cancel,Control
Publish=C.CFUNCTYPE(None,Pointer,C.c_void_p)
class IntegralStorage(C.Structure):
 _fields_=[('ram',C.POINTER(C.c_uint8)),('ram_size',C.c_size_t)]
CallbackContext=C.CFUNCTYPE(None,C.c_uint16,C.POINTER(C.c_uint16),C.c_void_p)
from test_platform_c import Platform
from test_eval_environment_c import Storage
class Write(C.Structure):
 _fields_=[('pc',C.c_uint32),('anchor',C.c_uint32),('address',C.c_uint16),('size',C.c_uint8),('value',C.c_uint64)]
class Event(C.Structure):
 _fields_=[('pc',C.c_uint32),('caller',C.c_uint32),('cursor',C.c_uint16),('sink',C.c_uint16),('workspace',C.c_uint8*0xc6),('x',C.c_uint8*20)]
SOURCES=['csrc/numeric/fx_surd_components.c','csrc/numeric/fx_integral_storage.c','csrc/numeric/fx_numeric.c','csrc/numeric/fx_raw_fraction_convert.c','csrc/numeric/fx_raw_decimal_parts.c','csrc/numeric/fx_raw_decimal_divide.c','csrc/numeric/fx_raw_decimal_multiply_add.c','csrc/platform/fx_platform.c','csrc/parse/fx_eval_finish.c']
INPUT_PATH='analysis/native-fixtures/integral-storage/inputs.json'
OBSERVER='tools/nxu8/integral_storage_events.c'
files=[ROOT/INPUT_PATH,ROOT/OBSERVER,ROOT/'tools/c_build_inputs.py',ROOT/'tools/c_verification.py',ROOT/'tools/nxu8/machine.py',ROOT/'tools/test_numeric_calculus_c.py',ROOT/'tools/test_platform_c.py',ROOT/'tools/test_eval_environment_c.py',ROOT/'firmware/fx-991es-plus-c-ver4.bin',ROOT/'analysis/disassembly/complete.asm',ROOT/'tools/nxu8/harness.c',ROOT/'tools/nxu8/vendor/SimU8/core.c',ROOT/'csrc/numeric/fx_integral.c',ROOT/'csrc/numeric/fx_integral.h',ROOT/'csrc/numeric/fx_calculus.h',ROOT/'csrc/numeric/fx_numeric.c',ROOT/'csrc/numeric/fx_numeric.h',ROOT/'csrc/platform/fx_platform.c',ROOT/'csrc/platform/fx_platform.h',ROOT/'csrc/parse/fx_eval_finish.c',ROOT/'csrc/parse/fx_eval_finish.h',ROOT/'csrc/parse/fx_eval_storage.h',ROOT/'csrc/numeric/fx_integral_storage.c',ROOT/'csrc/numeric/fx_integral_storage.h',Path(__file__)]
files+=list((ROOT/'tools/nxu8/vendor/SimU8').glob('*.h'))
files+=[ROOT/name for name in implementation_inputs(ROOT,SOURCES)]
files=sorted(set(files))
pins={str(p):hashlib.sha256(p.read_bytes()).hexdigest()for p in files}
subprocess.run(['gcc','-std=c99','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',str(ROOT/OBSERVER),str(ROOT/'tools/nxu8/vendor/SimU8/core.c'),'-o',str(HERE/'oracle.so')],check=True)
subprocess.run(['gcc','-std=c99','-'+args.optimization,'-Wall','-Wextra','-Werror','-shared','-fPIC','-Wl,--no-undefined','-I',str(ROOT/'csrc'),*[str(ROOT/p)for p in SOURCES],'-o',str(HERE/'prototype.so')],check=True)
rom=(ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes();native=Machine(rom,HERE/'native');nl=C.CDLL(str(HERE/'oracle.so'));old=native.lib
for name in ('harness_init','harness_set_reg','harness_get_reg','harness_set_sp','harness_get_sp','harness_set_lr','harness_set_pc','harness_get_pc','harness_ram'):
 getattr(nl,name).argtypes=getattr(old,name).argtypes;getattr(nl,name).restype=getattr(old,name).restype
nl.integral_observer_run.argtypes=[C.c_uint64,C.c_uint32]
nl.integral_stage_run.argtypes=[C.c_uint64,C.c_uint32]
native.lib=nl;native.ram=nl.harness_ram().contents
lib=C.CDLL(str(HERE/'prototype.so'))
lib.fx_integral_storage_lower.argtypes=[C.POINTER(IntegralStorage),Pointer]
lib.fx_integral_storage_upper.argtypes=[C.POINTER(IntegralStorage),Pointer]
lib.fx_integral_storage_tolerance.argtypes=[C.POINTER(IntegralStorage),Pointer,C.c_uint16,C.POINTER(C.c_uint)]
lib.fx_number_integral_storage.argtypes=[Pointer,C.POINTER(IntegralStorage),Function,C.c_void_p,Publish,C.c_uint16,CallbackContext,C.POINTER(Control),C.POINTER(C.c_uint),C.POINTER(C.c_uint16)]
for n in ['fx_decimal_parse','fx_decimal_integer_cleanup','fx_number_kind']:getattr(lib,n).argtypes=[Pointer]+([C.c_char_p]if n=='fx_decimal_parse'else[])
lib.fx_rational_encode.argtypes=[Pointer,C.POINTER(Rational)]
lib.fx_number_binary.argtypes=[Pointer,Pointer,Pointer,C.c_int];lib.fx_number_integer_power.argtypes=[Pointer,Pointer,C.c_int];lib.fx_number_sqrt.argtypes=[Pointer,Pointer,C.c_int]
ram=(C.c_uint8*65536)();rb=(C.c_uint8*len(rom)).from_buffer_copy(rom);platform=Platform(rb,len(rom),ram,0,0)
lib.fx_timer_start.argtypes=[C.POINTER(Platform),C.c_uint16]
lib.fx_eval_finish_cleanup.argtypes=[C.POINTER(Storage),Pointer,C.POINTER(C.c_uint8)]
storage=Storage(ram,65536,rb,len(rom));integral_storage=IntegralStorage(ram,65536)
native_writes=(Write*100000).in_dll(nl,'integral_writes');native_events=(Event*8192).in_dll(nl,'integral_events')
def counter(name):return C.c_uint.in_dll(nl,'integral_'+name)
def literal(text):
 n=Number();assert lib.fx_decimal_parse(C.byref(n),str(text).encode())==0;return bytes(n.bytes)
def setraw(address,raw):C.memmove(C.byref(native.ram,address),raw,len(raw))
formulas={'identity':b'X','square':b'X\x75','cube':b'X\x76','constant':b'A','radical':b'\x98X)','reciprocal':b'1\x4fX','error':b'1\x4f0','reciprocal_A':b'1\x4fA'}
recipes=json.loads((ROOT/INPUT_PATH).read_text());cases=recipes['core']
rows=[];checks=0
with gzip.open(HERE/'observations.jsonl.gz','wt')as stream:
 for i,case in enumerate(cases):
  native.reset();nl.integral_observer_reset();counter('abort').value=case['abort'];mutation=case.get('mutation');counter('mutation_call').value=mutation['call']if mutation else 0;counter('mutation_address').value=mutation['address']if mutation else 0
  if mutation:C.memmove((C.c_uint8*10).in_dll(nl,'integral_mutation_value'),literal(mutation['value']),10)
  for a,v in [(0x80f9,case.get('mode',0xc1)),(0x80fc,case.get('screen',1)),(0x80f5,0xf0),(0x8105,4),(0x8106,1),(0x8121,1)]:native.ram[a]=v
  if case.get('rich'):
   for identity in range(16):
    native.ram[0x80e0+identity*2]=native.ram[0x80e1+identity*2]=1
    for cell in range(9):setraw(0x829e+90*identity+10*cell,literal(str(identity+cell+1)))
  else:setraw(0x850a,bytes((j*17+3)&255 for j in range(0xc6)))
  # High-ID dimensions alias environment bytes; install the requested mode last.
  for a,v in [(0x80f9,case.get('mode',0xc1)),(0x80fc,case.get('screen',1)),(0x80f5,0xf0),(0x8105,4),(0x8106,1),(0x8121,1)]:native.ram[a]=v
  tokens=b'\x6a'+formulas[case['formula']]+b',B,C)\0';setraw(0x8a00,tokens);native.word(0x8190,0x8a00)
  for a,raw in [(0x823a,(bytes.fromhex(case['coefficient'])if isinstance(case.get('coefficient'),str)else case['coefficient'])if 'coefficient'in case else literal('2')),(0x8244,bytes.fromhex(case['lower_raw'])if 'lower_raw'in case else literal(case['lower'])),(0x824e,bytes.fromhex(case['upper_raw'])if 'upper_raw'in case else literal(case['upper'])),(0x8276,literal('37')),(0x8900,bytes([0xee])*20)]:setraw(a,raw)
  initial=bytes(native.ram)
  native.er(0,0x8190);native.er(2,0x8900);nl.harness_set_sp(0x8dee);nl.harness_set_lr(0x2fffe);nl.harness_set_pc(0x171f4)
  prep=nl.integral_observer_run(5000000,0x4786);before=bytes(native.ram);local=native.er(12);cursor_before=native.er(14)
  if prep!=100 or native.lib.harness_get_pc()!=0x4786:
   row=dict(index=i,input=case,tokens=tokens.hex(),prepared=False,preparation_return=prep,pc=f'{nl.harness_get_pc():06x}',status=native.reg(0),cursor=native.word(0x8190),result20=before[0x8900:0x8914].hex(),before=initial.hex(),after=before.hex())
   stream.write(json.dumps(row)+'\n');rows.append({k:v for k,v in row.items()if k not in ['before','after']});continue
  assert counter('write_count').value<=100000 and counter('event_count').value<=8192
  preparation_writes=[dict(pc=f'{w.pc:06x}',anchor=f'{w.anchor:06x}',address=f'{w.address:04x}',size=w.size,value=f'{w.value:016x}')for w in native_writes[:min(counter('write_count').value,100000)]]
  nl.integral_observer_reset();execution=nl.integral_observer_run(200000000,0x4a5c);after=bytes(native.ram);floor=counter('floor').value
  expected_out=after[local:local+10];expected_status=native.reg(0);expected_cursor=native.er(14)
  C.memmove(ram,before,65536);out=Number.from_buffer_copy(before[local:local+10]);host_callbacks=[];host_polls=[];host_events=[];cursor=C.c_uint16(cursor_before);callback_sink=[0x8900]
  @CallbackContext
  def callback_context(sink,cp,unused):callback_sink[0]=sink
  @Publish
  def publish(x,unused):C.memmove(C.byref(ram,0x8276),x,10)
  @Function
  def function(y,x,unused):
   host_callbacks.append(bytes(x.contents.bytes).hex())
   if mutation and len(host_callbacks)==mutation['call']:C.memmove(C.byref(ram,mutation['address']),literal(mutation['value']),10)
   host_events.append(dict(kind='callback',workspace=bytes(ram[0x850a:0x85d0]).hex(),x=bytes(ram[0x8276:0x8280]).hex()+bytes(ram[0x8458:0x8462]).hex()))
   formula=case['formula']
   if formula=='identity':C.memmove(y,x,10);status=0
   elif formula=='constant':
    C.memmove(y,C.byref(ram,0x823a),10);status=0
    if ram[0x80fc]==1 and y.contents.bytes[0]>>4 in [6,9,15]:
     leaf=C.c_uint8();status=lib.fx_eval_finish_cleanup(C.byref(storage),y,C.byref(leaf))
   elif formula in ['square','cube']:status=lib.fx_number_integer_power(y,x,2 if formula=='square'else 3)
   elif formula=='radical':status=lib.fx_number_sqrt(y,x,0)
   else:
    one=Number.from_buffer_copy(literal('1'));zero=Number.from_buffer_copy(bytes(10));divisor=C.byref(zero)if formula=='error'else C.cast(C.byref(ram,0x823a),Pointer)if formula=='reciprocal_A'else x
    status=lib.fx_number_binary(y,C.byref(one),divisor,3)
   if status:return status
   lib.fx_decimal_integer_cleanup(y)
   cursor.value=0x8a02+len(formulas[formula])
   if lib.fx_number_kind(y)==15 and formula not in ['constant','identity']:
    C.memmove(y,bytes.fromhex('f3000000000000000000'),10)
    if callback_sink[0]>=0x8000:C.memmove(C.byref(ram,callback_sink[0]&0xfffe),y,10)
    return 2
   return 1
  @Cancel
  def cancel(unused):
   host_polls.append(1);ram[0x8e00]=2;lib.fx_timer_start(C.byref(platform),0x129a);ram[0x8e00]=0;host_events.append(dict(kind='poll',workspace=bytes(ram[0x850a:0x85d0]).hex(),x=bytes(ram[0x8276:0x8280]).hex()+bytes(ram[0x8458:0x8462]).hex()))
   if case['abort']==len(host_polls):ram[0x80f2]=4;ram[0x80f3]=16;return 1
   return 0
  control=Control(cancel,None);status=C.c_uint(255)
  host_return=lib.fx_number_integral_storage(C.byref(out),C.byref(integral_storage),function,None,publish,0x8900,callback_context,C.byref(control),C.byref(status),C.byref(cursor))
  actual=bytes(ram);events=[]
  assert counter('write_count').value<=100000 and counter('event_count').value<=8192
  for e in native_events[:min(counter('event_count').value,8192)]:events.append(dict(kind='poll'if e.pc==0x5564 else 'callback'if e.pc==0x171ea else'error_sink',pc=f'{e.pc:06x}',caller=f'{e.caller:06x}',cursor=f'{e.cursor:04x}',sink=f'{e.sink:04x}',workspace=bytes(e.workspace).hex(),x=bytes(e.x).hex()))
  paired=[e for e in events if e['kind']!='error_sink'];event_match=len(paired)==len(host_events)and all(e['workspace']==h['workspace']and e['x']==h['x']and e['kind']==h['kind']for e,h in zip(paired,host_events))
  differences=[[f'{a:04x}',after[a],actual[a]]for a in range(0x80dc,65536)if not floor<=a<0x8dee and after[a]!=actual[a]]
  workspace_differences=[d for d in differences if 0x850a<=int(d[0],16)<0x85d0]
  semantic_match=execution==100 and nl.harness_get_pc()==0x4a5c and host_return==0 and bytes(out.bytes)==expected_out and status.value==expected_status and cursor.value==expected_cursor
  checks+=7
  row=dict(index=i,input={k:(v.hex()if isinstance(v,bytes)else v)for k,v in case.items()},tokens=tokens.hex(),preparation=prep,execution=execution,pc=f'{nl.harness_get_pc():06x}',local_output=f'{local:04x}',floor=f'{floor:04x}',native=dict(out=expected_out.hex(),status=expected_status,cursor=f'{expected_cursor:04x}',callbacks=counter('callbacks').value,polls=counter('polls').value),actual=dict(out=bytes(out.bytes).hex(),status=status.value,cursor=f'{cursor.value:04x}',host_return=host_return,callbacks=len(host_callbacks),polls=len(host_polls)),prepared=True,semantic_match=semantic_match,event_match=event_match,workspace_differences=workspace_differences,differences=differences,preparation_writes=preparation_writes,writes=[dict(pc=f'{w.pc:06x}',anchor=f'{w.anchor:06x}',address=f'{w.address:04x}',size=w.size,value=f'{w.value:016x}')for w in native_writes[:min(counter('write_count').value,100000)]],events=events,host_events=host_events,before=before.hex(),after=after.hex())
  stream.write(json.dumps(row)+'\n');rows.append({k:v for k,v in row.items()if k not in ['before','after','writes','preparation_writes','host_events','events']})
  print(i,case['formula'],expected_status,len(differences),len(workspace_differences),semantic_match,event_match,flush=True)
# Staged preparation uses fresh original parsing before each conversion. The
# argument error controls are retained at the actual04A5C boundary.
prefix_rows=[];stage_rows=[];guard_failures=[]
def initialize_prefix(case):
 native.reset();nl.integral_observer_reset();counter('abort').value=1
 counter('mutation_call').value=counter('mutation_address').value=0
 for identity in range(16):
  native.ram[0x80e0+2*identity]=native.ram[0x80e1+2*identity]=1
  for cell in range(9):setraw(0x829e+90*identity+10*cell,literal(identity+cell+1))
 setraw(0x8408,bytes(100))
 for a,v in [(0x80f9,case['mode']),(0x80fc,1),(0x80f5,0xf0),(0x8105,4),(0x8106,1),(0x8121,1)]:native.ram[a]=v
 pattern=case['pattern'];lower=b'B';upper=b'C';tol=None
 b=literal('0');c=literal('1');d=literal('0.0001')
 if pattern=='explicit-positive':tol=b'D'
 if pattern=='negative-tolerance':tol=b'D';d=literal('-1')
 if pattern=='zero-tolerance':tol=b'D';d=literal('0')
 if pattern=='lower-error':lower=b'1\x4f0'
 if pattern=='upper-error':upper=b'1\x4f0'
 if pattern=='tolerance-error':tol=b'1\x4f0'
 if pattern=='missing-upper':upper=b''
 if pattern=='equal-bounds':c=b
 if pattern=='lower-F':b=bytes.fromhex('f3000000000000000000')
 if pattern=='upper-F':c=bytes.fromhex('f3000000000000000000')
 if pattern=='tolerance-F':tol=b'D';d=bytes.fromhex('f3000000000000000000')
 if 'raw'in case:b=bytes.fromhex(case['raw'])
 tokens=b'\x6aX,'+lower+b','+upper+(b','+tol if tol is not None else b'')+b')\0'
 for a,raw in [(0x8244,b),(0x824e,c),(0x8258,d),(0x8276,literal('37')),(0x8a00,tokens),(0x8900,bytes([0xee])*20)]:setraw(a,raw)
 native.word(0x8190,0x8a00);native.er(0,0x8190);native.er(2,0x8900)
 nl.harness_set_sp(0x8dee);nl.harness_set_lr(0x2fffe);nl.harness_set_pc(0x171f4)
 assert native.ram[0x80f9]==case['mode']
 return tokens,tol
with gzip.open(HERE/'preparation-observations.jsonl.gz','wt')as stream:
 for index,case in enumerate(recipes['preparation']):
  tokens,tol=initialize_prefix(case);initial=bytes(native.ram);stages=[]
  for name,start,end in [('lower',0x471e,0x472c),('upper',0x4738,0x4746),('tolerance',0x4758 if tol is not None else 0x476c,0x4786)]:
   entry=nl.integral_stage_run(10000000,start)
   if entry!=100 or nl.harness_get_pc()!=start:
    stages.append(dict(stage=name,reached=False,execution=entry,pc=f'{nl.harness_get_pc():06x}',status=native.reg(0)));break
   pre=bytes(native.ram);source=native.er(12);final_cursor=native.er(14)
   value=Number.from_buffer_copy(pre[source:source+10]);C.memmove(ram,pre,65536)
   native_stage=nl.integral_stage_run(10000000,end);post=bytes(native.ram);floor=counter('floor').value
   status=C.c_uint(255)
   if name=='tolerance':host=lib.fx_integral_storage_tolerance(C.byref(integral_storage),C.byref(value)if tol is not None else None,final_cursor,C.byref(status))
   else:host=getattr(lib,'fx_integral_storage_'+name)(C.byref(integral_storage),C.byref(value))
   expected_pc=0x4a5c if name=='tolerance'and case['pattern']=='negative-tolerance'else end
   differences=[[f'{a:04x}',post[a],ram[a]]for a in range(0x80dc,65536)if not floor<=a<0x8dee and post[a]!=ram[a]]
   guarded=case['mode']==0xc4
   native_stop_ok=native_stage==100 and nl.harness_get_pc()==expected_pc
   passed=native_stop_ok and ((host==-3 and bytes(ram)==pre)if guarded else(host==0 and not differences and (name!='tolerance'or status.value==(8 if expected_pc==0x4a5c else 0))))
   stage=dict(index=index,stage=name,input=case,guarded=guarded,entry=entry,execution=native_stage,pc=f'{nl.harness_get_pc():06x}',host_return=host,native_status=native.reg(0),host_status=status.value if name=='tolerance'else None,source=f'{source:04x}',cursor=f'{final_cursor:04x}',floor=f'{floor:04x}',passed=passed,differences=differences)
   stages.append(stage);stage_rows.append(stage);checks+=4
   stream.write(json.dumps(dict(kind='stage',**stage,before=pre.hex(),after=post.hex()))+'\n')
   if nl.harness_get_pc()==0x4a5c:break
  # C4 guard is tested for every API without publishing or invoking callbacks.
  if case['mode']==0xc4:
   C.memmove(ram,initial,65536);out=Number.from_buffer_copy(bytes([0xee])*10);status=C.c_uint(255);cursor=C.c_uint16(0x1234);called=[]
   @Function
   def forbidden(y,x,unused):called.append(1);return 0
   @Publish
   def forbidden_publish(x,unused):called.append(2)
   @CallbackContext
   def forbidden_context(sink,cp,unused):called.append(3)
   host=lib.fx_number_integral_storage(C.byref(out),C.byref(integral_storage),forbidden,None,forbidden_publish,0x8900,forbidden_context,None,C.byref(status),C.byref(cursor))
   if host!=-3 or called or bytes(ram)!=initial or bytes(out.bytes)!=bytes([0xee])*10 or status.value!=255 or cursor.value!=0x1234:guard_failures.append(index)
   checks+=1
  execution=nl.integral_observer_run(10000000,0x2fffe);after=bytes(native.ram)
  assert counter('write_count').value<=100000 and counter('event_count').value<=8192
  row=dict(index=index,input=case,tokens=tokens.hex(),execution=execution,pc=f'{nl.harness_get_pc():06x}',status=native.reg(0),cursor=native.word(0x8190)-0x8a00,result20=after[0x8900:0x8914].hex(),callbacks=counter('callbacks').value,polls=counter('polls').value,stages=stages)
  stream.write(json.dumps(dict(kind='complete',**row,before=initial.hex(),after=after.hex()))+'\n');prefix_rows.append(row);checks+=1
# Original prepared stage entry receives a raw SURD working record. This
# isolates15C82 from upstream variable loading, including poisoned pools.
direct_stage_rows=[]
with gzip.open(HERE/'direct-stage-observations.jsonl.gz','wt')as stream:
 for index,case in enumerate(recipes['direct_stages']):
  native.reset();nl.integral_observer_reset();counter('abort').value=0
  counter('mutation_call').value=counter('mutation_address').value=0
  for a in range(0x8500,0x8680):native.ram[a]=(a*73+31)&255 if case['poison']else 0
  native.ram[0x80f9]=case['mode'];native.ram[0x80fc]=1
  raw=bytes.fromhex(case['raw']);source=case['source'];setraw(source,raw)
  name=case['stage'];start,end={'lower':(0x471e,0x472c),'upper':(0x4738,0x4746),'tolerance':(0x4758,0x4786)}[name]
  native.er(12,source);native.er(14,case['final_cursor']);native.er(8,0x8900)
  nl.harness_set_sp(0x8d00);nl.harness_set_lr(0x2fffe);nl.harness_set_pc(start)
  before=bytes(native.ram);C.memmove(ram,before,65536);value=Number.from_buffer_copy(raw);status=C.c_uint(255)
  execution=nl.integral_stage_run(1000000,end);after=bytes(native.ram);floor=counter('floor').value
  if name=='tolerance':host=lib.fx_integral_storage_tolerance(C.byref(integral_storage),C.byref(value),case['final_cursor'],C.byref(status))
  else:host=getattr(lib,'fx_integral_storage_'+name)(C.byref(integral_storage),C.byref(value))
  differences=[[f'{a:04x}',after[a],ram[a]]for a in range(0x80dc,65536)if not floor<=a<0x8dee and after[a]!=ram[a]]
  passed=execution==100 and nl.harness_get_pc()==end and host==0 and not differences and (name!='tolerance'or status.value==0)
  assert counter('write_count').value<=100000
  row=dict(index=index,input=case,execution=execution,pc=f'{nl.harness_get_pc():06x}',host_return=host,host_status=status.value if name=='tolerance'else None,floor=f'{floor:04x}',passed=passed,differences=differences,writes=[dict(pc=f'{w.pc:06x}',anchor=f'{w.anchor:06x}',address=f'{w.address:04x}',size=w.size,value=f'{w.value:016x}')for w in native_writes[:counter('write_count').value]])
  stream.write(json.dumps(dict(**row,before=before.hex(),after=after.hex()))+'\n');direct_stage_rows.append({k:v for k,v in row.items()if k!='writes'});checks+=4

# The native header guard admits malformed decimal payloads which this
# scalar decoder does not model. Prove the explicit host gap is deterministic
# and invokes no callback, rather than reading uninitialized decode fields.
malformed_guards=[]
for address,value in [(1,0xfa),(8,0xfa),(9,2)]:
 C.memset(ram,0,65536);ram[0x80f9]=0xc1
 lower=bytearray(literal('1'));lower[address]=value
 C.memmove(C.byref(ram,0x850a),bytes(lower),10);C.memmove(C.byref(ram,0x8514),literal('2'),10)
 before=bytes(ram);out=Number.from_buffer_copy(bytes([0xee])*10);status=C.c_uint(255);cursor=C.c_uint16(0x1234);called=[]
 @Function
 def forbidden(y,x,unused):called.append(1);return 0
 host=lib.fx_number_integral_storage(C.byref(out),C.byref(integral_storage),forbidden,None,Publish(),0x8900,CallbackContext(),None,C.byref(status),C.byref(cursor))
 passed=host==-3 and not called and bytes(ram)==before and bytes(out.bytes)==bytes([0xee])*10 and status.value==255 and cursor.value==0x1234
 malformed_guards.append(dict(record=bytes(lower).hex(),host_return=host,passed=passed));checks+=1
changes=[name for name,h in pins.items()if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=h]
report=dict(cases=len(rows)+len(prefix_rows)+len(direct_stage_rows),core_entry_cases=len(rows),native_calls=len(rows)+len(prefix_rows)+len(direct_stage_rows),checks=checks,source_changes=changes,pins_before_build=pins,core_calls=sum(bool(r.get('prepared'))for r in rows),native_preparation_controls=[r for r in rows if not r.get('prepared')],semantic_failures=[r['index']for r in rows if r.get('prepared')and not r.get('semantic_match')],workspace_failures=[r['index']for r in rows if r.get('workspace_differences')],event_failures=[r['index']for r in rows if r.get('prepared')and not r.get('event_match')],full_ram_failures=[r['index']for r in rows if r.get('differences')],rows=rows)
report.update(preparation_cases=len(prefix_rows),preparation_stages=len(stage_rows),preparation_rows=prefix_rows,preparation_failures=[r for r in stage_rows if not r['passed']],direct_stage_cases=len(direct_stage_rows),direct_stage_rows=direct_stage_rows,direct_stage_failures=[r for r in direct_stage_rows if not r['passed']],guard_failures=guard_failures,malformed_decimal_guards=malformed_guards,native_nonreturns=[r for r in rows if r.get('prepared')and(r['execution']!=100 or r['pc']!='004a5c')]+[r for r in prefix_rows if r['execution']!=100 or r['pc']!='02fffe'])
report['preparation_control_failures']=[r for r in rows if not r.get('prepared')and not(r['preparation_return']==100 and r['pc']=='02fffe'and r['status']==2 and r['cursor']==0x8a02 and r['result20']=='f2000000000000000000'+'ee'*10 and r['input']['formula']=='constant'and r['input'].get('screen')==0 and r['input'].get('coefficient','')[:2]in ['f1','f3'])]
report.update(status='pass'if not(report['direct_stage_failures']or any(not r['passed']for r in malformed_guards)or report['preparation_control_failures']or report['preparation_failures']or report['guard_failures']or report['native_nonreturns']or report['source_changes']or report['semantic_failures']or report['workspace_failures']or report['event_failures']or report['full_ram_failures'])else'fail',optimization=args.optimization,source_inputs=INPUT_PATH,scope='Prepared real integral core and argument stages in C1/6/7. Compare all RAM from 80DC outside measured CPU frames, including every supplied rich-slot payload and callback/poll snapshot. Numeric 8000..80DB and CPU frames are outside this high-level API. C4 returns UNIMPLEMENTED without writes; its original preparation witnesses are retained. Original grammar rejection controls are checked separately. Callback adapters own variable publication, timer/device effects, evaluator error sinks and final parser normalization. Native write order is retained as evidence, while parity is checked at stage/callback/poll/final boundaries.')
if not args.no_report:report=write_report('analysis/c-verification/numeric_integral_storage.json',report,[str(p.relative_to(ROOT))for p in files if p.suffix in ['.c','.h','.py','.json','.bin']or p.name=='CMakeLists.txt'],'tools/test_numeric_integral_storage_c.py')
(HERE/'report.json').write_text(json.dumps(report,indent=2)+'\n')
print({k:v for k,v in report.items()if k not in ['rows','preparation_rows','direct_stage_rows','pins_before_build','tested_inputs_sha256']})
assert report['status']=='pass', 'Original integral storage parity failed'
