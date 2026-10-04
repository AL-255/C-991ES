#!/usr/bin/env python3
"""Fresh original-ROM rich INPUT/result lifecycle; strict bounded persistent state."""
import argparse,ctypes as C,gzip,hashlib,json,sys,subprocess,re,time
from pathlib import Path
TOOL_ROOT=Path(__file__).resolve().parents[1]
ap=argparse.ArgumentParser(description=__doc__)
ap.add_argument('--repository-root',type=Path)
ap.add_argument('--optimization',choices=['O2','O3'],default='O2')
ap.add_argument('--no-report',action='store_true')
ap.add_argument('--csrc-root',type=Path)
ap.add_argument('--build-dir',type=Path)
ap.add_argument('--only-label')
args=ap.parse_args()
if any(x is not None for x in (args.repository_root,args.csrc_root,args.only_label,args.build_dir)) and not args.no_report:
 ap.error('Preview source/build locations and filtered workloads require --no-report')
ROOT=(args.repository_root or TOOL_ROOT).resolve()
sys.path.insert(0,str(ROOT/'tools'))
from nxu8.machine import Machine
from test_platform_c import Platform
from c_verification import write_report
class Context(C.Structure):
 _fields_=[('display_address',C.c_uint16),('result_address',C.c_uint16),*[(n,C.c_uint8) for n in ('return_value','calculation_mode','saved_math_result','natural_input','natural_result','special_view')]]
class Control(C.Structure):
 _fields_=[('cancelled',C.c_void_p),('userdata',C.c_void_p)]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 source_root=(args.csrc_root or ROOT/'csrc').resolve()
 build=(args.build_dir or ROOT/'analysis/build/rich-ui').resolve()/args.optimization
 build.mkdir(parents=True,exist_ok=True)
 text=(source_root/'CMakeLists.txt').read_text().split('target_include_directories')[0]
 rels=re.findall(r'^\s+([a-zA-Z0-9_/]+\.c)\)?$',text,re.M)
 if len(rels)!=len(set(rels)):raise ValueError('Duplicate CMake library sources')
 bridge=TOOL_ROOT/'tools/rich_ui_support/candidate_bridge.c'
 observer=TOOL_ROOT/'tools/nxu8/rich_ui_host_events.c'
 fixture_path=TOOL_ROOT/'analysis/native-fixtures/rich-ui/inputs.json.gz'
 sources=[source_root/p for p in rels]+[bridge]
 if source_root/'ui/fx_linalg_controller.c' not in sources:
  raise ValueError('Production CMake must include actual bank controller')
 inputs=list(sources)+sorted(source_root.rglob('*.c'))+sorted(source_root.rglob('*.h'))+[Path(__file__),observer,source_root/'CMakeLists.txt',ROOT/'firmware/fx-991es-plus-c-ver4.bin',ROOT/'tools/nxu8/harness.c',ROOT/'tools/nxu8/vendor/SimU8/core.c',ROOT/'tools/nxu8/machine.py',ROOT/'tools/test_platform_c.py',ROOT/'tools/c_verification.py',ROOT/'tools/c_build_inputs.py',fixture_path]+sorted((ROOT/'tools/nxu8/vendor/SimU8').rglob('*.h'))
 executed={str(Path(v.__file__).resolve()) for v in sys.modules.values() if getattr(v,'__file__',None) and (str(Path(v.__file__).resolve()).startswith(str(ROOT/'tools')) or str(Path(v.__file__).resolve()).startswith(str(TOOL_ROOT)))}
 inputs+=sorted(Path(x) for x in executed)
 pins={str(p):sha(p) for p in inputs}
 library=build/'candidate.so';subprocess.run(['gcc','-std=c99','-'+args.optimization,'-Wall','-Wextra','-Werror','-shared','-fPIC','-Wl,--no-undefined','-I',str(source_root),*[str(p) for p in sources],'-o',str(library)],check=True)
 rom=(ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes();m=Machine(rom,build/'base-oracle')
 oracle=build/'oracle.so';subprocess.run(['gcc','-std=c99','-'+args.optimization,'-Wall','-Wextra','-Werror','-shared','-fPIC','-I',str(ROOT/'tools/nxu8'),str(observer),str(ROOT/'tools/nxu8/vendor/SimU8/core.c'),'-o',str(oracle)],check=True)
 native=C.CDLL(str(oracle));
 for name in ('harness_init','harness_set_pc','harness_get_pc','harness_set_reg','harness_get_reg','harness_set_sp','harness_get_sp','harness_set_lr','harness_ram','harness_run','harness_trace_open'):
  getattr(native,name).argtypes=getattr(m.lib,name).argtypes;getattr(native,name).restype=getattr(m.lib,name).restype
 native.lifecycle_run.argtypes=[C.c_uint64,C.c_uint32,C.c_uint];native.lifecycle_reset.argtypes=[]
 native.harness_callback.argtypes=[];native.harness_callback.restype=C.c_uint32
 m.lib=native;m.ram=native.harness_ram().contents;m.reset()
 lib=C.CDLL(str(library));lib.candidate_size.argtypes=[C.c_uint];lib.candidate_size.restype=C.c_size_t;lib.candidate_field.argtypes=[C.c_void_p,C.c_uint,C.c_uint];lib.candidate_abi.argtypes=[C.c_uint];lib.candidate_abi.restype=C.c_size_t
 abi=[C.sizeof(Platform),*[getattr(Platform,n).offset for n in ('rom','rom_size','ram','callback_pending','status')],C.sizeof(Context),*[getattr(Context,n).offset for n in ('display_address','result_address','return_value','calculation_mode','saved_math_result','natural_input','natural_result','special_view')],C.sizeof(Control),*[getattr(Control,n).offset for n in ('cancelled','userdata')]]
 assert abi==[lib.candidate_abi(i) for i in range(len(abi))]
 pp=C.POINTER(Platform);lib.fx_take_callback.argtypes=[pp];lib.fx_take_callback.restype=C.c_uint8
 lib.fx_input_controller_begin.argtypes=[pp,C.c_void_p,C.POINTER(Context),C.POINTER(Control)];lib.fx_input_controller_tick.argtypes=[pp,C.c_void_p]
 lib.fx_ui_controller_begin.argtypes=[pp,C.c_void_p,C.c_uint8,C.POINTER(Control)];lib.fx_ui_controller_tick.argtypes=[pp,C.c_void_p]
 lib.fx_linalg_controller_begin.argtypes=[pp,C.c_void_p,C.POINTER(Control)];lib.fx_linalg_controller_tick.argtypes=[pp,C.c_void_p]
 lib.fx_linalg_ui_store_cell.argtypes=[pp,C.c_uint16,C.c_uint8,C.c_uint8,C.c_uint8,C.POINTER(C.c_uint8)]
 rb=(C.c_uint8*len(rom)).from_buffer_copy(rom);ram=(C.c_uint8*65536)();p=Platform(rb,len(rom),ram,0,0)
 frames=(C.c_uint8*65536).in_dll(native,'lifecycle_frames');polls=C.c_uint.in_dll(native,'lifecycle_polls');poll_ram=((C.c_uint8*65536)*256).in_dll(native,'lifecycle_poll_ram')
 records=[];failures=[];checks=len(abi);calls=0;cumulative_frames=set()
 binary_paths=(library,oracle,build/'base-oracle/nxu8-harness.so')
 binaries={str(x):sha(x) for x in binary_paths}
 with gzip.open(fixture_path,'rt') as f:fixture=json.load(f)
 if fixture.get('schema')!=1:raise ValueError('Unexpected input fixture schema')
 if (len(fixture['prepared']),len(fixture['extra']),fixture['default_original_entries'])!=(28,1160,1232):
  raise ValueError('Unexpected default input corpus')
 permitted={'index','mode','label','initial_ram_hex','cancel_at','dimensions','error_wait','expression_hex','initial_screen','initial_slot','kind','row','column','source','slot','number_domain','host_gap','gap_pc'}
 for family in ('prepared','extra'):
  values=fixture[family]
  if len({x['index'] for x in values})!=len(values):raise ValueError('Duplicate recipe index')
  for x in values:
   if set(x)-permitted:raise ValueError('Unrecognized input field')
   if len(bytes.fromhex(x['initial_ram_hex']))!=65536 or x['mode'] not in (6,7):raise ValueError('Invalid initial RAM/mode')
   if x.get('host_gap') and (x.get('host_gap')!='marked-compact-format' or x.get('gap_pc')!=0xed64 or x.get('kind')!='bank'):
    raise ValueError('Unrecognized diagnostic boundary')
 if sum(bool(x.get('host_gap')) for x in fixture['extra'])!=fixture['historical_raw_format_diagnostics'] or fixture['historical_raw_format_diagnostics']!=16:
  raise ValueError('Raw-format diagnostics were changed')
 fixtures=[]
 for family in ('prepared','whole','extra'):
  values=fixture['extra' if family=='extra' else 'prepared']
  fixtures.extend(dict(x,execution_family=family) for x in values)
 if args.only_label is not None:fixtures=[x for x in fixtures if args.only_label in x['label']]
 if not fixtures:raise ValueError('No selected input recipes')
 def compare(label,context=None,numeric=False):
  nonlocal checks
  cumulative_frames.update(a for a in range(65536) if frames[a])
  actual=bytearray(ram);expected=bytes(m.ram)
  if context is not None:actual[0x9d04]=context
  differences=[(hex(a),actual[a],expected[a]) for a in range(65536) if actual[a]!=expected[a] and a not in cumulative_frames and not(numeric and 0x8000<=a<0x80dc)]
  host_callback=lib.fx_take_callback(C.byref(p));native_callback=native.harness_callback()
  if host_callback!=native_callback:differences.append(('callback_pending',host_callback,native_callback))
  checks+=2
  return {'host_callback':host_callback,'native_callback':native_callback,'label':label,'differences':differences,'frame_floor':C.c_uint.in_dll(native,'lifecycle_floor').value,'frame_written':sum(frames),'excluded_frame_addresses':sorted(cumulative_frames),'host_ram_sha':hashlib.sha256(actual).hexdigest(),'native_ram_sha':hashlib.sha256(expected).hexdigest()}
 def call(entry,stop=0x2fffe):
  nonlocal calls
  native.lifecycle_reset();m.er(0,0x9d00);native.harness_set_sp(0x8dee);native.harness_set_lr(0x2fffe);native.harness_set_pc(entry)
  result=native.lifecycle_run(50000000,stop,case.get('cancel_at',0));calls+=1
  return result
 Cancel=C.CFUNCTYPE(C.c_int,C.c_void_p)
 for case in fixtures:
  is_extra=case['execution_family']=='extra';is_whole=case['execution_family']=='whole'
  cumulative_frames.clear();m.reset();initial=bytes.fromhex(case['initial_ram_hex']);C.memmove(m.ram,initial,65536);C.memmove(ram,initial,65536);p.status=p.callback_pending=0
  context=Context(0x8154,0x8140,initial[0x9d04],case['mode'],initial[0x9d07],initial[0x9d08],initial[0x9d09],initial[0x9d0a]);s=C.create_string_buffer(lib.candidate_size(0));host_polls=[]
  def cancelled(_):host_polls.append(bytes(ram));return int(case.get('cancel_at',0) and len(host_polls)==case['cancel_at'])
  callback=Cancel(cancelled);control=Control(C.cast(callback,C.c_void_p),None)
  if is_extra:
   if case['kind']=='cell':
    fw=C.c_uint8(255);status=lib.fx_linalg_ui_store_cell(C.byref(p),case['source'],case['slot'],case['row'],case['column'],C.byref(fw))
    native.lifecycle_reset();m.er(0,case['source']);m.reg(2,case['slot']);m.reg(3,case['row']);native.harness_set_sp(0x8dee);native.harness_set_lr(0x2fffe);native.harness_set_pc(0x1d362);nr=native.lifecycle_run(50000000,0x2fffe,0);calls+=1
    record={'index':case['index'],'mode':case['mode'],'label':case['label'],'host_status':status,'host_native_status':fw.value,'native_status':nr,'native_return':m.reg(0),'checks':[compare('live-cell-store',None,False)],'host_final_ram_hex':bytes(ram).hex(),'native_final_ram_hex':bytes(m.ram).hex()}
    if status!=0 or nr!=100 or fw.value!=m.reg(0):record['contract_failure']=True
   else:
    view=C.create_string_buffer(lib.candidate_size(2));begin=lib.fx_linalg_controller_begin(C.byref(p),view,C.byref(control));status=begin
    for _ in range(8):
     if status!=4:break
     status=lib.fx_linalg_controller_tick(C.byref(p),view)
    gap=bool(case.get('host_gap') and status==-2)
    nr=call(0xecaa,case['gap_pc'] if gap else 0x2fffe);returned=lib.candidate_field(view,2,0)
    record={'index':case['index'],'mode':case['mode'],'label':case['label'],'host_begin':begin,'host_status':status,'host_context_return':returned,'native_status':nr,'native_return':m.reg(0),'native_pc':hex(native.harness_get_pc()),'checks':[compare('bank-event',None,True)],'host_final_ram_hex':bytes(ram).hex(),'native_final_ram_hex':bytes(m.ram).hex()}
    if gap:
     record['host_gap']=case['host_gap'];record['gap_pc']=hex(case['gap_pc'])
     if status!=-2 or nr!=100 or native.harness_get_pc()!=0xed64:record['contract_failure']=True
     continuation=native.lifecycle_run(50000000,0x2fffe,0)
     record['original_completion']={'status':continuation,'pc':hex(native.harness_get_pc()),'return':m.reg(0),'ram_hex':bytes(m.ram).hex(),'callback':native.harness_callback()}
     if continuation!=100:record['contract_failure']=True
    elif status!=1 or nr!=100 or returned!=m.reg(0):record['contract_failure']=True
    elif case.get('host_gap'):record['historical_gap_resolved']=True
   checks+=2;differences=sum(len(x['differences']) for x in record['checks'])
   if differences or record.get('contract_failure'):failures.append({'index':case['index'],'label':case['label'],'differences':differences,'contract_failure':record.get('contract_failure',False)})
  elif is_whole:
   s=C.create_string_buffer(lib.candidate_size(1));begin=lib.fx_ui_controller_begin(C.byref(p),s,0,C.byref(control));status=begin
   for _ in range(8):
    if status!=4:break
    status=lib.fx_ui_controller_tick(C.byref(p),s)
   stop=0x1d8a4 if (case['label'] in ('missing-shape','syntax') or case.get('error_wait',False)) else 0x2fffe
   nr=call(0xd9ee,stop);returned=lib.candidate_field(s,1,0)
   record={'index':case['index'],'mode':case['mode'],'label':case['label'],'begin_status':begin,'host_status':status,'native_status':nr,'native_pc':hex(native.harness_get_pc()),'host_context_return':returned,'host_action':lib.candidate_field(s,1,1),'native_return':m.reg(0),'host_poll_count':len(host_polls),'native_poll_count':polls.value,'checks':[compare('whole-D9EE',None,True)],'host_final_ram_hex':bytes(ram).hex(),'native_final_ram_hex':bytes(m.ram).hex()}
   for i,host in enumerate(host_polls):
    if i>=polls.value:break
    expected=bytes(poll_ram[i]);diff=[(hex(a),host[a],expected[a]) for a in range(65536) if host[a]!=expected[a] and a not in cumulative_frames and not(0x8000<=a<0x80dc)]
    record['checks'].append({'label':f'poll{i+1}','differences':diff,'host_ram_hex':host.hex(),'native_ram_hex':expected.hex()});checks+=1
   checks+=3
   waiting=case['label'] in ('missing-shape','syntax') or case.get('error_wait',False)
   if nr!=100 or len(host_polls)!=polls.value or (status!=0 if waiting else (status!=1 or returned!=m.reg(0))):record['contract_failure']=True
   differences=sum(len(x['differences']) for x in record['checks'])
   if differences or record.get('contract_failure'):failures.append({'index':case['index'],'label':case['label'],'differences':differences,'contract_failure':record.get('contract_failure',False)})
  else:
   begin=lib.fx_input_controller_begin(C.byref(p),s,C.byref(context),C.byref(control));nr=call(0x1f12a,0x1f2ac)
   prepared_pc=native.harness_get_pc()
   record={'index':case['index'],'mode':case['mode'],'label':case['label'],'begin_status':begin,'native_prepared_status':nr,'native_prepared_pc':hex(prepared_pc),'checks':[compare('prepared')]}
   if nr!=100 or prepared_pc!=0x1f2ac:record['contract_failure']=True
   status=lib.fx_input_controller_tick(C.byref(p),s)
   # Continue actual CPU from the unchanged F2AC checkpoint.
   stop=0x1d8a4 if (case['label'] in ('missing-shape','syntax') or case.get('error_wait',False)) else 0x2fffe
   nr=native.lifecycle_run(50000000,stop,case.get('cancel_at',0))
   returned=lib.candidate_field(s,0,0);record.update(host_status=status,native_status=nr,native_pc=hex(native.harness_get_pc()),host_context_return=returned,host_action=lib.candidate_field(s,0,1),native_action=m.reg(0),host_poll_count=len(host_polls),native_poll_count=polls.value)
   record['checks'].append(compare('commit',returned,True));record['host_final_ram_hex']=bytes(ram).hex();record['native_final_ram_hex']=bytes(m.ram).hex()
   checks+=3
   if begin!=4 or nr!=100 or len(host_polls)!=polls.value:record['contract_failure']=True
   waiting=case['label'] in ('missing-shape','syntax') or case.get('error_wait',False)
   if status!=0 if waiting else (status!=1 or record['host_action']!=m.reg(0)):record['contract_failure']=True
   for i,host in enumerate(host_polls):
    if i>=polls.value:break
    expected=bytes(poll_ram[i]);diff=[(hex(a),host[a],expected[a]) for a in range(65536) if host[a]!=expected[a] and a not in cumulative_frames and not(0x8000<=a<0x80dc)]
    record['checks'].append({'label':f'poll{i+1}','differences':diff,'host_ram_hex':host.hex(),'native_ram_hex':expected.hex()});checks+=1
   if nr==100 and m.ram[0x80fc] in (19,20):
    ram[0x80f5]=m.ram[0x80f5]=0;ram[0x80f7]=m.ram[0x80f7]=1
    view=C.create_string_buffer(lib.candidate_size(2));vb=lib.fx_linalg_controller_begin(C.byref(p),view,C.byref(control));vs=lib.fx_linalg_controller_tick(C.byref(p),view) if vb==4 else vb
    nr=call(0xecaa);record['view']={'host_begin':vb,'host_status':vs,'native_status':nr,'host_return':lib.candidate_field(view,2,0),'native_return':m.reg(0),'comparison':compare('bank-view',returned,True)}
    checks+=2
    if vs!=1 or nr!=100 or lib.candidate_field(view,2,0)!=m.reg(0):record['contract_failure']=True
    record['view']['host_ram_hex']=bytes(ram).hex();record['view']['native_ram_hex']=bytes(m.ram).hex()
   differences=sum(len(x['differences']) for x in record['checks'])+len(record.get('view',{}).get('comparison',{}).get('differences',[]))
   if differences or record.get('contract_failure'):failures.append({'index':case['index'],'label':case['label'],'differences':differences,'contract_failure':record.get('contract_failure',False)})
  record['input']=case;records.append(record)
  if differences or record.get('contract_failure') or args.only_label is not None or case['index']%100==0:print(case['index'],case['mode'],case['label'],status,differences,record.get('view',{}).get('host_status'),flush=True)
 after_modules={str(Path(v.__file__).resolve()) for v in sys.modules.values() if getattr(v,'__file__',None) and (str(Path(v.__file__).resolve()).startswith(str(ROOT/'tools')) or str(Path(v.__file__).resolve()).startswith(str(TOOL_ROOT)))}
 module_set_stable=executed==after_modules
 after={str(x):sha(x) for x in inputs};binary_after={str(x):sha(x) for x in binary_paths}
 stamp=time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+'-'+str(time.time_ns());kind='rich-ui';archive=build/f'observations-{kind}-{stamp}.json.gz'
 with gzip.open(archive,'wt') as f:json.dump(records,f)
 report={'optimization':args.optimization,'subset':args.only_label,'calls':calls,'checks':checks,'abi':abi,'failures':failures,'before':pins,'after':after,'binary_before':binaries,'binary_after':binary_after,'observations':str(archive),'host_gap_controls':sum('host_gap' in r for r in records),'handled_entry_calls':calls-sum('host_gap' in r for r in records),'executed_python_modules':sorted(executed),'executed_python_modules_after':sorted(after_modules),'executed_module_set_stable':module_set_stable,'source_changes':[x for x in pins if pins[x]!=after[x]],'scope':'Fresh F12A/ECAA/D9EE and live-cell calls from the complete input-only corpus (a named subset is preview only); input-only recipes; bank/dims/pools/display/MMIO and callback publication strict. Numeric8000..80DB and individually witnessed original CPU-frame writes are excluded. Raw C0 compact selected-format host gaps compare exact original ED64 prefix, and retain subsequent unfiltered original outcomes; they do not count as full handled calls.'}
 reportfile=build/f'report-{kind}-{stamp}.json';reportfile.write_text(json.dumps(report,indent=2)+'\n')
 print('REPORT',reportfile,'FAILURES',len(failures),flush=True)
 assert module_set_stable,'executed Python module set changed'
 assert pins==after and binaries==binary_after,'source drift'
 assert not failures,failures
 if args.only_label is None and (calls!=fixture['default_original_entries'] or len(records)!=1216):
  raise AssertionError(f'Default workload changed: {calls}')
 if not args.no_report:
  canonical={k:v for k,v in report.items() if k not in ('before','after')}
  canonical.update(cases=len(records),original_calls=calls,observations=str(archive.relative_to(ROOT)),native_gaps_preserved=sum('host_gap' in r for r in records),resolved_historical_gaps=sum(r.get('historical_gap_resolved',False) for r in records),limitations=['Numeric8000..80DB and individually witnessed original frame writes excluded.','RawC0 formatter diagnostics retain exactED64 prefix and original finite completion.','Bounded slots0..3, shapes/selection1..3; no complete UI or oversized/foreign formatting claim.'])
  deps=[str(Path(x).relative_to(ROOT)) for x in pins if Path(x)!=fixture_path]
  canonical=write_report('analysis/c-verification/rich_ui.json',canonical,deps,'tools/test_rich_ui_c.py')
  canonical['tested_inputs_sha256'][str(fixture_path.relative_to(ROOT))]=pins[str(fixture_path)]
  (ROOT/'analysis/c-verification/rich_ui.json').write_text(json.dumps(canonical,indent=2)+'\n')
 return 0
if __name__=='__main__':raise SystemExit(main())
