#!/usr/bin/env python3
"""Compare readable prepared finite SUM/product stages with fresh original firmware."""
import argparse,ast,ctypes as C,hashlib,json,os,shutil,subprocess,sys
from decimal import Decimal
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from c_build_inputs import implementation_inputs
from c_verification import write_report
from finite_series_storage_support.original import observe
DEFAULT_FIXTURE=ROOT/'analysis/native-fixtures/finite-series/inputs.json'
FIXTURE_SHA='563340f89c52cf1fcc672bea324cc4b214a79a3bb03becbc3f3d6d8346f737af'
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def validate_fixture(path,canonical):
 data=json.loads(path.read_text())
 if not isinstance(data,dict) or set(data)!={'schema','expected_cases','rows'} or data['schema']!=1:
  raise ValueError('fixture must be schema1 input-only recipes')
 rows=data['rows']
 if not isinstance(rows,list) or not rows or data['expected_cases']!=len(rows):
  raise ValueError('fixture expected_cases must equal nonempty recipe count')
 labels=set()
 fields={'label','kind','mode','body','lower','upper','constant','x','abort_poll'}
 for row in rows:
  if not isinstance(row,dict) or set(row)!=fields:raise ValueError('unexpected/missing input-only recipe fields')
  if not isinstance(row['label'],str) or row['label']in labels:raise ValueError('recipe labels must be distinct strings')
  labels.add(row['label'])
  if row['kind']not in ('sum','product') or row['mode']not in (0xc1,0xc4) or row['body']not in ('X','A','1/0'):raise ValueError('recipe outside supported input seam')
  if type(row['abort_poll'])is not int or not 0<=row['abort_poll']<=7:raise ValueError('bounded abort poll must be0..7')
  for name in ('lower','upper','constant','x'):
   if not isinstance(row[name],list) or len(row[name])!=2:raise ValueError('pair input must contain two records')
   for value in row[name]:
    if not isinstance(value,str):raise ValueError('record recipes must be strings')
    if value.startswith('raw:'):
     if len(value)!=24 or len(bytes.fromhex(value[4:]))!=10:raise ValueError('raw record must contain ten bytes')
    else:
     d=Decimal(value)
     if not d.is_finite():raise ValueError('nonfinite record recipe')
     t=d.copy_abs().normalize().as_tuple();digits=''.join(map(str,t.digits));e=len(digits)+t.exponent-1
     if len(digits)>15 or abs(e)>99:raise ValueError('record exceeds input recipe extent')
 if canonical and (len(rows)!=16 or sha(path)!=FIXTURE_SHA):raise ValueError('canonical frozen16 fixture was changed')
 return rows
ap=argparse.ArgumentParser(description=__doc__)
ap.add_argument('--fixture',type=Path,default=DEFAULT_FIXTURE)
ap.add_argument('--source-root',type=Path,default=ROOT)
ap.add_argument('--build-dir',type=Path,default=ROOT/'analysis/build/finite-series-storage')
ap.add_argument('--no-report',action='store_true')
args=ap.parse_args();fixture=args.fixture.resolve();source_root=args.source_root.resolve();BUILD=args.build_dir.resolve()
canonical=fixture==DEFAULT_FIXTURE.resolve() and source_root==ROOT
if not canonical and not args.no_report:ap.error('custom fixtures or private implementation roots require --no-report')
recipes=validate_fixture(fixture,canonical);BUILD.mkdir(parents=True,exist_ok=True)
sources=next(ast.literal_eval(n.value)for n in ast.parse((ROOT/'tools/test_eval_variables_c.py').read_text()).body if isinstance(n,ast.Assign)and any(isinstance(t,ast.Name)and t.id=='SOURCES'for t in n.targets))
sources=[source_root/'csrc'/p for p in sources]+[source_root/'csrc/numeric/fx_finite_series_storage.c']
abi=ROOT/'tools/finite_series_storage_support/abi.c'
generated_abi=BUILD/'compiled-abi.c'
generated_abi.write_text(abi.read_text().replace('../../csrc/numeric/fx_finite_series_storage.h',str(source_root/'csrc/numeric/fx_finite_series_storage.h')))
rompath=ROOT/'firmware/fx-991es-plus-c-ver4.bin';rombytes=rompath.read_bytes()
cclosure=[source_root/p for p in implementation_inputs(source_root,sources)]
python_inputs=[Path(__file__),ROOT/'tools/finite_series_storage_support/original.py',ROOT/'tools/nxu8/machine.py',ROOT/'tools/c_build_inputs.py',ROOT/'tools/c_verification.py',ROOT/'tools/test_eval_variables_c.py']
oracle_inputs=[ROOT/'tools/finite_series_storage_support/native.c',ROOT/'tools/finite_series_storage_support/native_v2.c',ROOT/'tools/nxu8/harness.c',ROOT/'tools/nxu8/isa.txt',ROOT/'tools/nxu8/vendor/SimU8/core.c',*list((ROOT/'tools/nxu8/vendor/SimU8').glob('*.h')),ROOT/'analysis/disassembly/complete.asm']
compiler=Path(shutil.which('gcc')).resolve();python=Path(sys.executable).resolve()
pinpaths=[*cclosure,*python_inputs,*oracle_inputs,abi,generated_abi,fixture,rompath,compiler,python]
pins={str(p):sha(p)for p in pinpaths}
class Number(C.Structure):_fields_=[('bytes',C.c_uint8*10)]
class Pair(C.Structure):_fields_=[('real',Number),('imaginary',Number)]
class Storage(C.Structure):_fields_=[('ram',C.POINTER(C.c_uint8)),('ram_size',C.c_size_t),('rom',C.POINTER(C.c_uint8)),('rom_size',C.c_size_t)]
class State(C.Structure):_fields_=[('records',Number*4),('value',Pair),('source',C.c_uint16),('body_source',C.c_uint16),('kind',C.c_uint8),('phase',C.c_uint8),('native_status',C.c_uint8),('spilled',C.c_uint8)]
class Evaluation(C.Structure):_fields_=[('value',Pair),('source',C.c_uint16),('condition',C.c_uint8),('error_sink_written',C.c_uint8),('error_sink',Number)]
Function=C.CFUNCTYPE(C.c_int,C.POINTER(Evaluation),C.POINTER(Pair),C.c_void_p)
Cancel=C.CFUNCTYPE(C.c_int,C.c_void_p)
class Control(C.Structure):_fields_=[('cancelled',Cancel),('userdata',C.c_void_p)]
def num(s):
 if s.startswith('raw:'):return bytes.fromhex(s[4:])
 d=Decimal(s)
 if not d:return bytes(10)
 t=d.copy_abs().normalize().as_tuple();digits=''.join(map(str,t.digits));e=len(digits)+t.exponent-1;ds=digits.ljust(15,'0');flag=(6 if d<0 else 1)if e>=0 else(5 if d<0 else 0)
 return bytes([int(ds[0]),*[int(ds[i:i+2],16)for i in range(1,15,2)],int(f'{abs(e):02d}',16),flag])
def pair(v):return Pair.from_buffer_copy(b''.join(map(num,v)))
def snapshot(st,ram,polls,samples,host):
 return dict(records=bytes(st.records).hex(),value=bytes(st.value).hex(),x=(bytes(ram[0x8276:0x8280])+bytes(ram[0x8458:0x8462])).hex(),source=st.source,body_source=st.body_source,phase=st.phase,spilled=st.spilled,native_status=st.native_status,polls=polls[0],callbacks=len(samples),host=host)
def build_run(opt):
 libpath=BUILD/('candidate-'+opt+'.so')
 subprocess.run(['gcc','-std=c11','-'+opt,'-Wall','-Wextra','-Werror','-shared','-fPIC',*[str(p)for p in sources],str(generated_abi),'-o',str(libpath)],check=True,env={**os.environ,'TMPDIR':str(BUILD)})
 artifact_pin={str(libpath):sha(libpath)}
 lib=C.CDLL(str(libpath));lib.finite_series_abi.argtypes=[C.c_uint];lib.finite_series_abi.restype=C.c_size_t
 expected=[C.sizeof(Number),C.sizeof(Pair),C.sizeof(Storage),*[getattr(Storage,n).offset for n in ('ram','ram_size','rom','rom_size')],C.sizeof(State),*[getattr(State,n).offset for n in ('records','value','source','body_source','kind','phase','native_status','spilled')],C.sizeof(Evaluation),*[getattr(Evaluation,n).offset for n in ('value','source','condition','error_sink_written','error_sink')],C.sizeof(Control)]
 assert expected==[lib.finite_series_abi(i)for i in range(23)]
 lib.fx_finite_series_begin.argtypes=[C.POINTER(State),C.c_int]
 lib.fx_finite_series_lower.argtypes=[C.POINTER(State),C.POINTER(Storage),C.POINTER(Pair)]
 lib.fx_finite_series_upper.argtypes=[C.POINTER(State),C.POINTER(Storage),C.POINTER(Pair),C.c_uint16]
 lib.fx_finite_series_step.argtypes=[C.POINTER(State),C.POINTER(Storage),Function,C.c_void_p,C.POINTER(Control)]
 lib.fx_finite_series_store_result.argtypes=[C.POINTER(State),C.POINTER(Storage),C.c_uint16]
 host=host_controls(lib)
 global host_checks
 host_checks+=host
 results=[]
 for index,case in enumerate(recipes):
  ram=(C.c_uint8*65536)();rom=(C.c_uint8*len(rombytes)).from_buffer_copy(rombytes);storage=Storage(ram,65536,rom,len(rombytes));st=State();samples=[];polls=[0]
  for a,v in [(0x80f9,case['mode']),(0x80fc,1),(0x80f5,0xf0),(0x8105,4),(0x8106,1),(0x8121,1)]:ram[a]=v
  for name,addresses in [('constant',(0x823a,0x841c)),('lower',(0x8244,0x8426)),('upper',(0x824e,0x8430)),('x',(0x8276,0x8458))]:
   for v,a in zip(case[name],addresses):C.memmove(C.byref(ram,a),num(v),10)
  lower=pair(case['lower']);upper=pair(case['upper']);constant=pair(case['constant'])
  @Function
  def callback(ev,x,_):
   samples.append(dict(argument=bytes(x.contents).hex(),x=(bytes(ram[0x8276:0x8280])+bytes(ram[0x8458:0x8462])).hex()))
   if case['body']=='X':ev.contents.value=x.contents
   elif case['body']=='A':
    ev.contents.value=constant
    if bytes(constant.real)[0]>=0xf0:
     ev.contents.value.real=Number.from_buffer_copy(bytes.fromhex('f3000000000000000000'))
   else:
    ev.contents.value=Pair.from_buffer_copy(bytes.fromhex('f3000000000000000000')+bytes(10))
    ev.contents.condition=3;ev.contents.error_sink_written=1;ev.contents.error_sink=ev.contents.value.real
   if case['mode']!=0xc4:ev.contents.value.imaginary=Number()
   ev.contents.source=0x8a02+len(case['body']);ev.contents.condition=ev.contents.condition or 0xfe
   samples[-1].update(value=bytes(ev.contents.value).hex(),condition=ev.contents.condition,source=ev.contents.source)
   return 0
  @Cancel
  def cancelled(_):
   polls[0]+=1
   return int(bool(case['abort_poll']and polls[0]==case['abort_poll']))
  ctl=Control(cancelled,None);host=lib.fx_finite_series_begin(C.byref(st),case['kind']=='product');assert host==0
  host=lib.fx_finite_series_lower(C.byref(st),C.byref(storage),C.byref(lower));assert host==0
  stages=[dict(snapshot(st,ram,polls,samples,host),stage='lower_stored')]
  host=lib.fx_finite_series_upper(C.byref(st),C.byref(storage),C.byref(upper),0x8a07);assert host==0
  stages.append(dict(snapshot(st,ram,polls,samples,host),stage='published'))
  steps=0
  while st.phase in (2,3):
   host=lib.fx_finite_series_step(C.byref(st),C.byref(storage),callback,None,C.byref(ctl));steps+=1
   assert host==0 and steps<=8
   if st.phase==4 and st.native_status==0:
    working=0x8da0;C.memmove(C.byref(ram,working),bytes(st.value),20)
    host=lib.fx_finite_series_store_result(C.byref(st),C.byref(storage),working);assert host==0
   stages.append(dict(snapshot(st,ram,polls,samples,host),stage='step'))
  results.append(dict(index=index,input=case,stages=stages,samples=samples,final=snapshot(st,ram,polls,samples,host)))
 (BUILD/(opt+'-actual.json')).write_text(json.dumps(results,indent=2)+'\n')
 return results,artifact_pin,23
def host_controls(lib):
 count=0;ram=(C.c_uint8*65536)();rom=(C.c_uint8*len(rombytes)).from_buffer_copy(rombytes)
 ram[0x80f9]=0xc4;storage=Storage(ram,65536,rom,len(rombytes));st=State();bound=pair(['1','0'])
 @Function
 def callback(ev,x,_):ev.contents.value=x.contents;return 0
 def rejected(name,call):
  nonlocal count
  before=(bytes(st),bytes(ram),bytes(storage))
  status=call()
  assert status==-1 and before==(bytes(st),bytes(ram),bytes(storage)),name
  count+=1
 rejected('begin-null',lambda:lib.fx_finite_series_begin(None,0))
 rejected('begin-enum',lambda:lib.fx_finite_series_begin(C.byref(st),7))
 rejected('lower-null-state',lambda:lib.fx_finite_series_lower(None,C.byref(storage),C.byref(bound)))
 rejected('lower-null-storage',lambda:lib.fx_finite_series_lower(C.byref(st),None,C.byref(bound)))
 rejected('lower-null-bound',lambda:lib.fx_finite_series_lower(C.byref(st),C.byref(storage),None))
 st.phase=2
 rejected('lower-wrong-phase',lambda:lib.fx_finite_series_lower(C.byref(st),C.byref(storage),C.byref(bound)))
 st.phase=1
 rejected('upper-null-bound',lambda:lib.fx_finite_series_upper(C.byref(st),C.byref(storage),None,0x8a07))
 st.phase=0
 rejected('upper-wrong-phase',lambda:lib.fx_finite_series_upper(C.byref(st),C.byref(storage),C.byref(bound),0x8a07))
 rejected('step-wrong-phase',lambda:lib.fx_finite_series_step(C.byref(st),C.byref(storage),callback,None,None))
 st.phase=2
 rejected('step-null-function',lambda:lib.fx_finite_series_step(C.byref(st),C.byref(storage),Function(),None,None))
 rejected('step-ram-control',lambda:lib.fx_finite_series_step(C.byref(st),C.byref(storage),callback,None,C.cast(C.byref(ram,0x9000),C.POINTER(Control))))
 st.phase=4
 rejected('store-rom-address',lambda:lib.fx_finite_series_store_result(C.byref(st),C.byref(storage),0x7fff))
 rejected('store-end-address',lambda:lib.fx_finite_series_store_result(C.byref(st),C.byref(storage),65520))
 st.native_status=3
 rejected('store-failed-condition',lambda:lib.fx_finite_series_store_result(C.byref(st),C.byref(storage),0x9000))
 return count

# C numerical results are computed from authored recipes BEFORE any native report is loaded.
actuals={};artifacts={str(generated_abi):sha(generated_abi)};abi_checks=0;host_checks=0
for opt in ('O2','O3'):
 actuals[opt],art,n=build_run(opt);artifacts.update(art);abi_checks+=n
native_report=observe(ROOT,BUILD/'original',fixture)
assert not native_report['changes']
artifacts.update(native_report['artifacts'])
native=native_report['rows']
checks=0;failures=[]
def check(opt,index,field,actual,expected):
 global checks
 checks+=1
 if actual!=expected:failures.append(dict(opt=opt,index=index,field=field,actual=actual,expected=expected))
for opt,rows in actuals.items():
 for actual,n in zip(rows,native):
  index=actual['index'];case=actual['input'];last=actual['final'];lower=next(s for s in n['stages']if s['stage']=='lower_stored')
  end=next((s for s in n['stages']if s['stage']=='numeric_finish'),None)
  check(opt,index,'lower-real',actual['stages'][0]['records'][20:40],lower['workspace40'][20:40])
  if case['mode']==0xc4:check(opt,index,'lower-imag',actual['stages'][0]['records'][40:60],lower['workspace40'][40:60])
  if end is None:
   check(opt,index,'Argument8',last['native_status'],8);check(opt,index,'no-spill',last['spilled'],0);check(opt,index,'no-body',last['callbacks'],n['callback_count']);check(opt,index,'no-polls',last['polls'],n['polls'])
   continue
  published=next(s for s in n['stages']if s['stage']=='published')
  check(opt,index,'ready-X',actual['stages'][1]['x'],published['x'])
  if case['mode']==0xc4:check(opt,index,'ready-records40',actual['stages'][1]['records'],published['workspace40'])
  else:check(opt,index,'ready-records30',actual['stages'][1]['records'][:60],published['workspace40'][:60])
  check(opt,index,'native-condition',last['native_status'],end['registers'][0])
  check(opt,index,'numeric-working20',last['value'],end['working20'])
  check(opt,index,'live-X',last['x'],end['x'])
  check(opt,index,'callback-count',last['callbacks'],n['callback_count']);check(opt,index,'poll-count',last['polls'],n['polls'])
  check(opt,index,'end-records',last['records'][:80 if case['mode']==0xc4 else 60],end['workspace40'][:80 if case['mode']==0xc4 else 60])
  ns=[s for s in n['samples']if s['r6']==1]
  for i,(a,b)in enumerate(zip(actual['samples'],ns)):
   for field in ('x','value'):check(opt,index,'callback-'+str(i)+'-'+field,a[field],b[field])
   check(opt,index,'callback-'+str(i)+'-condition',a['condition'],b['status'])
  # Each step endpoint is either the next poll-entry (same published PC) or numeric finish.
  ev=[e for e in n['events']if e['pc']in ([0x4430,0x447e]if case['kind']=='sum'else[0x433c,0x4390])]
  for i,(a,b)in enumerate(zip(actual['stages'][2:],ev[1:])):
   for field,other in [('x','x'),('value','value')]:check(opt,index,'step-'+str(i)+'-'+field,a[field],b[other])
   check(opt,index,'step-'+str(i)+'-records',a['records'][:80 if case['mode']==0xc4 else 60],b['records'][:80 if case['mode']==0xc4 else 60])
changes={p:sha(p)for p,h in {**pins,**artifacts}.items()if sha(p)!=h}
report=dict(status='PASS'if not failures and not changes else'FAIL',
 cases=len(recipes),distinct_input_recipes=len(recipes),candidate_executions=2*len(recipes),
 native_calls=native_report['native_calls'],native_instructions=native_report['native_instructions'],
 abi_checks=abi_checks,host_checks=host_checks,stage_field_checks=checks,
 failures=failures,pins=pins,artifacts=artifacts,changes=changes,
 original_outcomes=[dict(index=r['index'],label=r['input']['label'],outcome=r['outcome'],pc=r['final_pc'],numeric_status=r['numeric_status'],output=r['output'],cursor=r['cursor'])for r in native],
 scope='Actual strict O2/O3 prepared finite-series module stages computed from authored input recipes before fresh unchanged original calls. Provider covers X/A/error bodies, including decoded variable F canonicalization and explicit eager evaluator error-sink event. Named defined workspace records, numeric working pair, physical X, raw condition, callback and poll stages only. COMP secondary is a semantic zero callback argument while the observed physical X companion is retained. No full persistentRAM/LCD, raw keypad scan, complete C4 caller epilogue return or complete firmware parity claim.',
 expected_native_boundaries='Valid C4 prepared171F4 frame upper companion spills beyond the original30-byte allocation; numeric finish is compared and actual last return instruction is recorded, then unexpected PC0 stopped. Invalid bounds returnArgument8 before spill. COMP reaches its real16BD4 numerical continuation and complete171F4 return.',
 full_firmware_complete=False)
(BUILD/'proof.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({k:report[k]for k in ('status','distinct_input_recipes','candidate_executions','native_calls','native_instructions','abi_checks','host_checks','stage_field_checks','failures','changes')}),flush=True)
assert not failures and not changes
if not args.no_report:
 # The shared writer accepts its supported source extensions; independently
 # guarded ISA/listing/compiled-ABI/compiler pins remain explicit below.
 eligible=[Path(p).resolve().relative_to(ROOT)for p in pins if Path(p).resolve().is_relative_to(ROOT) and Path(p).suffix in ('.c','.h','.py','.json','.bin') and not Path(p).resolve().is_relative_to(BUILD)]
 staging=BUILD/'canonical-stage.json'
 published=write_report(staging,report,eligible,Path(__file__).resolve().relative_to(ROOT))
 if any(sha(p)!=h for p,h in {**pins,**artifacts}.items()):raise RuntimeError('source/artifact drift before canonical publication')
 published['tested_inputs_sha256'].update({str(Path(p).relative_to(ROOT)):h for p,h in pins.items()if Path(p).is_relative_to(ROOT) and not Path(p).is_relative_to(BUILD)})
 published['executed_artifacts_sha256']=artifacts
 published['compiler_sha256']={str(compiler):sha(compiler)}
 target=ROOT/'analysis/c-verification/finite_series_storage.json';target.parent.mkdir(parents=True,exist_ok=True)
 target.write_text(json.dumps(published,indent=2)+'\n')
 print('Published '+str(target),flush=True)
