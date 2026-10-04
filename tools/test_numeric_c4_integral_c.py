import argparse,ctypes as C,gzip,hashlib,json,subprocess,sys
from pathlib import Path
from c_verification import ROOT,write_report
sys.path.insert(0,str(ROOT/'tools'))
ap=argparse.ArgumentParser(description='Original C4 integral paired-storage stages and kernel boundaries.')
ap.add_argument('--optimization',choices=['O2','O3'],default='O2')
ap.add_argument('--no-report',action='store_true')
ap.add_argument('--source-root',type=Path,default=ROOT)
ap.add_argument('--fixture',type=Path,default=ROOT/'analysis/native-fixtures/c4-integral/core/inputs.json')
ap.add_argument('--build-dir',type=Path,default=ROOT/'analysis/build/numeric-c4-integral')
args=ap.parse_args()
if args.source_root.resolve()!=ROOT.resolve() and not args.no_report:ap.error('Private source-root requires --no-report')
CANONICAL_FIXTURE=ROOT/'analysis/native-fixtures/c4-integral/core/inputs.json'
if args.fixture.resolve()!=CANONICAL_FIXTURE.resolve() and not args.no_report:ap.error('Custom fixture requires --no-report')
FIXTURE_SHA256='8533ab843469a2e73fd4287c6cf660446c7507caf08b8a044da7cd1fa124a331'
assert hashlib.sha256(args.fixture.read_bytes()).hexdigest()==FIXTURE_SHA256
fixture=json.loads(args.fixture.read_text())
assert set(fixture)=={'schema','provenance','expected_cases','rows'}
assert fixture['schema']==1 and len(fixture['rows'])==fixture['expected_cases']==77
assert all(set(row)<={'formula','lower','upper','abort','imag'} and {'formula','lower','upper','abort'}<=set(row) for row in fixture['rows'])
assert all(row['formula']in ('identity','constant','i','error','sumzero')
 and isinstance(row['lower'],str)and isinstance(row['upper'],str)
 and isinstance(row['abort'],int)and row['abort']>=0
 and set(row.get('imag',{}))<={'A','B','C','X'}for row in fixture['rows'])
HERE=args.build_dir;HERE.mkdir(parents=True,exist_ok=True)
BASE=args.source_root/'csrc/numeric'
from c_build_inputs import implementation_inputs
from nxu8.machine import Machine
from test_numeric_calculus_c import Number,Pointer,Cancel,Control
from test_platform_c import Platform
from test_eval_environment_c import Storage
class Pair(C.Structure):_fields_=[('real',Number),('imaginary',Number)]
P=C.POINTER(Pair)
Function=C.CFUNCTYPE(C.c_int,P,P,C.c_void_p)
Publish=C.CFUNCTYPE(None,P,C.c_void_p)
Context=C.CFUNCTYPE(None,C.c_uint16,C.POINTER(C.c_uint16),C.c_void_p)
class IntegralStorage(C.Structure):_fields_=[('ram',C.POINTER(C.c_uint8)),('ram_size',C.c_size_t)]
class Event(C.Structure):_fields_=[('pc',C.c_uint32),('caller',C.c_uint32),('cursor',C.c_uint16),('sink',C.c_uint16),('workspace',C.c_uint8*0xc6),('x',C.c_uint8*20)]
observer='''#include "%s"
int c4_boundary_run(uint64_t limit) {
 for(uint64_t i=0;i<limit;++i) {
  uint32_t pc=harness_get_pc();if(pc==0x4a5c||pc==0x4696||pc==0x2fffe)return100;
  int status=integral_observer_run(1,0x2fffe);if(status!=103)return status;
 }return103;
}
'''%(ROOT/'tools/nxu8/integral_storage_events.c')
observer=observer.replace('return100','return 100').replace('return103','return 103');(HERE/'oracle.c').write_text(observer)
sources=[BASE/'fx_c4_integral_storage.c',*[args.source_root/'csrc'/n for n in ['numeric/fx_numeric.c','numeric/fx_raw_fraction_convert.c','numeric/fx_raw_decimal_parts.c','numeric/fx_raw_decimal_divide.c','numeric/fx_raw_decimal_multiply_add.c','numeric/fx_surd_components.c','complex/fx_complex.c','platform/fx_platform.c']]]
files=sources+[BASE/'fx_c4_integral_storage.h',HERE/'oracle.c',Path(__file__),ROOT/'firmware/fx-991es-plus-c-ver4.bin',ROOT/'tools/nxu8/integral_storage_events.c',ROOT/'tools/nxu8/harness.c',ROOT/'tools/nxu8/vendor/SimU8/core.c'];files+=list((ROOT/'tools/nxu8/vendor/SimU8').glob('*.h'))
files+=[args.source_root/name for name in implementation_inputs(args.source_root,[str(p.relative_to(args.source_root))for p in sources])]
files+=[Path(module.__file__).resolve()for module in list(sys.modules.values())if getattr(module,'__file__',None)and Path(module.__file__).suffix=='.py'and Path(module.__file__).resolve().is_relative_to(ROOT/'tools')]
files+=[args.fixture];files=sorted(set(files));pins={str(p):hashlib.sha256(p.read_bytes()).hexdigest()for p in files}
subprocess.run(['gcc','-std=c99','-'+args.optimization,'-Wall','-Wextra','-Werror','-pedantic','-shared','-fPIC','-Wl,--no-undefined','-I',str(args.source_root/'csrc'),*[str(s)for s in sources],'-x','c','-','-o',str(HERE/'candidate.so')],input='''#include <stddef.h>
#include "complex/fx_complex.h"
#include "numeric/fx_integral_storage.h"
size_t c4_test_abi(unsigned i){const size_t values[]={sizeof(fx_number),sizeof(fx_complex),offsetof(fx_complex,real),offsetof(fx_complex,imaginary),sizeof(fx_integral_storage),offsetof(fx_integral_storage,ram),offsetof(fx_integral_storage,ram_size)};return i<7?values[i]:0;}
''',text=True,check=True)
subprocess.run(['gcc','-std=c99','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',str(HERE/'oracle.c'),str(ROOT/'tools/nxu8/vendor/SimU8/core.c'),'-o',str(HERE/'oracle.so')],check=True)
artifact_paths=[HERE/'candidate.so',HERE/'oracle.so']
artifact_hashes={str(path):hashlib.sha256(path.read_bytes()).hexdigest()for path in artifact_paths}
rom=(ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes();native=Machine(rom,HERE/'oracle-build');nl=C.CDLL(str(HERE/'oracle.so'));old=native.lib
for name in ('harness_init','harness_set_reg','harness_get_reg','harness_set_sp','harness_get_sp','harness_set_lr','harness_set_pc','harness_get_pc','harness_ram'):
 getattr(nl,name).argtypes=getattr(old,name).argtypes;getattr(nl,name).restype=getattr(old,name).restype
nl.integral_stage_run.argtypes=[C.c_uint64,C.c_uint32];nl.integral_observer_run.argtypes=[C.c_uint64,C.c_uint32];nl.c4_boundary_run.argtypes=[C.c_uint64];native.lib=nl;native.ram=nl.harness_ram().contents
lib=C.CDLL(str(HERE/'candidate.so'))
lib.c4_test_abi.argtypes=[C.c_uint];lib.c4_test_abi.restype=C.c_size_t
abi=[lib.c4_test_abi(i)for i in range(7)];assert abi==[C.sizeof(Number),C.sizeof(Pair),Pair.real.offset,Pair.imaginary.offset,C.sizeof(IntegralStorage),IntegralStorage.ram.offset,IntegralStorage.ram_size.offset]
lib.fx_decimal_parse.argtypes=[Pointer,C.c_char_p];lib.fx_complex_cleanup.argtypes=[P,P];lib.fx_complex_binary.argtypes=[P,P,P,C.c_int];lib.fx_timer_start.argtypes=[C.POINTER(Platform),C.c_uint16]
for name in ('lower','upper'):getattr(lib,'fx_c4_integral_'+name).argtypes=[C.POINTER(IntegralStorage),P]
lib.fx_c4_integral_tolerance.argtypes=[C.POINTER(IntegralStorage),P,C.c_uint16,C.POINTER(C.c_uint)]
lib.fx_c4_integral_run.argtypes=[P,C.POINTER(IntegralStorage),Function,C.c_void_p,Publish,C.c_uint16,Context,C.POINTER(Control),C.POINTER(C.c_uint),C.POINTER(C.c_uint16)]
ram=(C.c_uint8*65536)();rb=(C.c_uint8*len(rom)).from_buffer_copy(rom);storage=IntegralStorage(ram,65536);platform=Platform(rb,len(rom),ram,0,0)
def num(text):
 v=Number();assert lib.fx_decimal_parse(C.byref(v),str(text).encode())==0;return bytes(v)
def put(a,b):C.memmove(C.byref(native.ram,a),b,len(b))
def count(name):return C.c_uint.in_dll(nl,'integral_'+name)
forms={'identity':b'X','constant':b'A','i':b'\x80','error':b'1\x4f0','sumzero':b'X+0'}
cases=fixture['rows']
stage_rows=[];rows=[]
with gzip.open(HERE/'observations.jsonl.gz','wt')as stream:
 for index,case in enumerate(cases):
  native.reset();nl.integral_observer_reset();count('abort').value=case['abort'];count('mutation_call').value=count('mutation_address').value=0
  for a,v in [(0x80f9,0xc4),(0x80fc,1),(0x80f5,0xf0),(0x8105,4),(0x8106,1),(0x8121,1)]:native.ram[a]=v
  for a,raw in [(0x823a,num(2)),(0x8244,num(case['lower'])),(0x824e,num(case['upper'])),(0x8276,num(37)),(0x8900,b'\xee'*20)]:put(a,raw)
  for name,a in [('A',0x841c),('B',0x8426),('C',0x8430),('X',0x8458)]:put(a,num(case.get('imag',{}).get(name,0)))
  tokens=b'\x6a'+forms[case['formula']]+b',B,C)\0';put(0x8a00,tokens);native.word(0x8190,0x8a00);native.er(0,0x8190);native.er(2,0x8900);nl.harness_set_sp(0x8dee);nl.harness_set_lr(0x2fffe);nl.harness_set_pc(0x171f4)
  initial=bytes(native.ram)
  for name,start,end in [('lower',0x471e,0x472c),('upper',0x4738,0x4746),('tolerance',0x476c,0x4786)]:
   reached=nl.integral_stage_run(10000000,start)
   if reached!=100 or nl.harness_get_pc()!=start:break
   before=bytes(native.ram);source=native.er(12);cursor=native.er(14);value=Pair.from_buffer_copy(before[source:source+20]);C.memmove(ram,before,65536)
   execution=nl.integral_stage_run(10000000,end);after=bytes(native.ram);floor=count('floor').value;status=C.c_uint(255)
   host=lib.fx_c4_integral_tolerance(C.byref(storage),None,cursor,C.byref(status))if name=='tolerance'else getattr(lib,'fx_c4_integral_'+name)(C.byref(storage),C.byref(value))
   differences=[[hex(a),after[a],ram[a]]for a in range(0x80dc,65536)if not floor<=a<0x8dee and after[a]!=ram[a]]
   stage=dict(index=index,stage=name,host=host,execution=execution,pc=hex(nl.harness_get_pc()),differences=differences)
   stage_rows.append(stage);stream.write(json.dumps(dict(kind='stage',**stage,before=before.hex(),after=after.hex()))+'\n')
  if nl.harness_get_pc()!=0x4786:
   rows.append(dict(index=index,input=case,preparation_return=True,pc=hex(nl.harness_get_pc()),status=native.reg(0)));continue
  before=bytes(native.ram);local=native.er(12);cursor_start=native.er(14);nl.integral_observer_reset();execution=nl.c4_boundary_run(10000000);after=bytes(native.ram);pc=nl.harness_get_pc();floor=count('floor').value
  native_events=(Event*8192).in_dll(nl,'integral_events');events=[dict(kind='poll'if e.pc==0x5564 else'callback'if e.pc==0x171ea else'error',workspace=bytes(e.workspace).hex(),x=bytes(e.x).hex())for e in native_events[:count('event_count').value]if e.pc in [0x5564,0x171ea]]
  C.memmove(ram,before,65536);out=Pair.from_buffer_copy(before[local:local+20]);cursor=C.c_uint16(cursor_start);status=C.c_uint(255);host_events=[];calls=[];polls=[];sink=[0x8900]
  @Context
  def context(s,cp,_):sink[0]=s
  @Publish
  def publish(x,_):C.memmove(C.byref(ram,0x8276),C.byref(x.contents.real),10);C.memmove(C.byref(ram,0x8458),C.byref(x.contents.imaginary),10)
  @Function
  def function(y,x,_):
   calls.append(bytes(x.contents).hex());host_events.append(dict(kind='callback',workspace=bytes(ram[0x850a:0x85d0]).hex(),x=(bytes(ram[0x8276:0x8280])+bytes(ram[0x8458:0x8462])).hex()))
   formula=case['formula']
   if formula in ['identity','sumzero']:
    if formula=='identity':C.memmove(y,x,20)
    else:
     zero=Pair();assert lib.fx_complex_binary(y,x,C.byref(zero),0)==0
   elif formula=='constant':C.memmove(C.byref(y.contents.real),C.byref(ram,0x823a),10);C.memmove(C.byref(y.contents.imaginary),C.byref(ram,0x841c),10)
   elif formula=='i':C.memmove(y,bytes(10)+num(1),20)
   else:C.memmove(y,bytes.fromhex('f3000000000000000000')+bytes(10),20)
   assert lib.fx_complex_cleanup(y,y)==0
   cursor.value=0x8a02+len(forms[formula])
   if formula=='error':
    if sink[0]>=0x8000:C.memmove(C.byref(ram,sink[0]),C.byref(y.contents.real),10)
    return 2
   return 1
  @Cancel
  def cancel(_):
   polls.append(1);ram[0x8e00]=2;lib.fx_timer_start(C.byref(platform),0x129a);ram[0x8e00]=0;host_events.append(dict(kind='poll',workspace=bytes(ram[0x850a:0x85d0]).hex(),x=(bytes(ram[0x8276:0x8280])+bytes(ram[0x8458:0x8462])).hex()))
   if case['abort']==len(polls):ram[0x80f2]=4;ram[0x80f3]=16;return 1
   return 0
  control=Control(cancel,None)
  host=lib.fx_c4_integral_run(C.byref(out),C.byref(storage),function,None,publish,0x8900,context,C.byref(control),C.byref(status),C.byref(cursor))
  differences=[[hex(a),after[a],ram[a]]for a in range(0x80dc,65536)if not floor<=a<0x8dee and after[a]!=ram[a]]
  record_match=bytes(out)==after[local:local+20];event_match=events==host_events;return_match=(host==0 and pc==0x4a5c and status.value==native.reg(0)and cursor.value==native.er(14))or(host==-3 and pc==0x4696)
  row=dict(index=index,input=case,execution=execution,pc=hex(pc),native=dict(out=after[local:local+20].hex(),status=native.reg(0),cursor=hex(native.er(14)),callbacks=count('callbacks').value,polls=count('polls').value),actual=dict(out=bytes(out).hex(),host=host,status=status.value,cursor=hex(cursor.value),callbacks=len(calls),polls=len(polls)),record_match=record_match,event_match=event_match,return_match=return_match,callback_count_match=len(calls)==count('callbacks').value,poll_count_match=len(polls)==count('polls').value,differences=differences)
  rows.append(row);stream.write(json.dumps(dict(kind='core',**row,before=before.hex(),after=after.hex(),native_events=events,actual_events=host_events))+'\n')
  print(index,case['formula'],case['lower'],case['upper'],case['abort'],hex(pc),host,'record',record_match,'events',event_match,'diff',len(differences),flush=True)
changes=[p for p,h in {**pins,**artifact_hashes}.items()if hashlib.sha256(Path(p).read_bytes()).hexdigest()!=h]
report=dict(optimization=args.optimization,compiled_abi=abi,sources=pins,source_changes=changes,stage_rows=stage_rows,rows=rows,stage_failures=[r for r in stage_rows if r['differences']or r['host']or r['execution']!=100],failures=[r for r in rows if not r.get('preparation_return')and(not r['record_match']or not r['event_match']or not r['return_match']or not r['callback_count_match']or not r['poll_count_match']or r['differences'])],limits=[r for r in rows if r.get('pc')=='0x4696'])
(HERE/'report.json').write_text(json.dumps(report,indent=2)+'\n');print('FAILURES',len(report['failures']),'STAGES',len(report['stage_failures']),'LIMITS',len(report['limits']))

assert len(rows)==77 and len(stage_rows)==231
assert len(report['limits'])==8 and all(row['pc']in ('0x4a5c','0x4696')for row in rows)
report.update(status='pass'if not report['failures']and not report['stage_failures']and not changes else 'fail',cases=77,checks=len(stage_rows)*3+len(rows)*6+len(abi)+8,original_calls=77,prepared_stage_comparisons=231,native_returned_controls=69,native_architectural_boundaries=8,fixture_sha256=FIXTURE_SHA256,compiled_artifact_hashes=artifact_hashes,comparison='Prepared original171F4 argument stages and0480E driver to4A5C or exact04696 CPU-local overflow boundary. Raw20-byte records, independent status/cursor, each callback/poll pair/workspace event and all80DC..FFFF RAM outside observed native activeCPUframe;8000..80DB excluded. Eight04696 prefixes retained explicitly, no invented continuation.')
(HERE/'report.json').write_text(json.dumps(report,indent=2)+'\n')
if report['failures']or report['stage_failures']or changes:raise AssertionError('Unfiltered C4 integral proof failed')
if not args.no_report:
 dependencies=[str(path.relative_to(ROOT))for path in files if path.is_relative_to(ROOT)and path!=HERE/'oracle.c']
 write_report('analysis/c-verification/numeric_c4_integral.json',report,sorted(set(dependencies)),'tools/test_numeric_c4_integral_c.py')
print(json.dumps({key:report[key]for key in ['status','cases','checks','original_calls','prepared_stage_comparisons','native_returned_controls','native_architectural_boundaries','fixture_sha256','source_changes']}))
