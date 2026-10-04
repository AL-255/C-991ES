#!/usr/bin/env python3
"""Prepared TABLE controller differential proof with explicit subordinate bodies.

Original evaluator, row-generation, range/UI and painting observations are
supplied only while their named request is retained. Structural state and the
error-key wait/recovery execute in C. No CPU instructions execute in C. Outputs are diagnostic evidence in
analysis/build/table-controller. Its canonical report covers the prepared
structural controller; native supplied bodies are explicit test dependencies
and are not counted as C implementations.
"""
import argparse,collections,ctypes as C,gzip,hashlib,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
HERE=ROOT/'analysis/build/table-controller'
FIXTURES=ROOT/'analysis/native-fixtures/table-controller-lifecycle'
sys.path.insert(0,str(ROOT/'tools'))
from c_build_inputs import implementation_inputs
from c_verification import write_report
from test_input_controller_c import MODULES,Context,Number
from test_error_event_c import ErrorEvent
from test_platform_c import Platform
class Controller(C.Structure):
 _fields_=[('context',Context),('error',ErrorEvent),('saved_result',Number*2),
  ('prepared_source',C.c_uint16),('current_source',C.c_uint16),('selected_address',C.c_uint16),('request',C.c_int),
  *[(n,C.c_uint8) for n in ('phase','active','handler_action','execution_status','second_pass','preparation_ok','argument','columns','initial_rows','two_functions')]]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def er(registers,index):b=bytes.fromhex(registers);return b[index]|b[index+1]<<8
def word(ram,address):return ram[address]|ram[address+1]<<8
def main():
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--optimization',choices=('O2','O3'),default='O2');ap.add_argument('--corpus',choices=('controller-final','controller-interventions'),default='controller-final');ap.add_argument('--no-report',action='store_true');args=ap.parse_args()
 if not args.no_report and (args.optimization!='O2' or args.corpus!='controller-final'):
  ap.error('Canonical publication requires the complete default O2 prepared-controller corpus; use --no-report for other runs')
 HERE.mkdir(parents=True,exist_ok=True)
 archive=FIXTURES/args.corpus/'native-states.jsonl.gz';original_report=FIXTURES/args.corpus/'observations.json'
 names=list(dict.fromkeys(['csrc/'+m+'.c' for m in MODULES]+['csrc/stats/fx_stats_editor.c']))
 deps=[ROOT/n for n in implementation_inputs(ROOT,names)]+[ROOT/'csrc/table/fx_table_controller.c',ROOT/'csrc/table/fx_table_controller.h',Path(__file__),archive,original_report,
  *[ROOT/'tools'/n for n in ('c_build_inputs.py','test_input_controller_c.py','test_error_event_c.py','test_key_controller_c.py','test_platform_c.py')],
  FIXTURES/args.corpus/'collect.py',FIXTURES/args.corpus/'oracle.c',ROOT/'firmware/fx-991es-plus-c-ver4.bin',ROOT/'analysis/disassembly/complete.asm']
 pins={str(p):sha(p) for p in deps}
 original_metadata=json.loads(original_report.read_text())
 assert original_metadata['archive_sha256']==pins[str(archive)],'Original archive/metadata mismatch'
 for basename in ('collect.py','oracle.c'):
  recorded=[h for path,h in original_metadata['source_sha256'].items() if Path(path).name==basename]
  assert recorded==[pins[str(FIXTURES/args.corpus/basename)]],('Original source transport mismatch',basename)
 libpath=HERE/('controller-'+args.optimization+'.so')
 subprocess.run(['gcc','-std=c99','-'+args.optimization,'-Wall','-Wextra','-Werror','-shared','-fPIC','-Wl,--no-undefined',
  '-I'+str(ROOT/'csrc/table'),'-I'+str(ROOT/'csrc'),*[str(ROOT/n) for n in names],str(ROOT/'csrc/table/fx_table_controller.c'),'-o',str(libpath)],check=True)
 pins[str(libpath)]=sha(libpath)
 lib=C.CDLL(str(libpath));pp=C.POINTER(Platform);ss=C.POINTER(Controller)
 lib.fx_table_controller_begin.argtypes=[pp,ss,C.POINTER(Context)];lib.fx_table_controller_accept_execution.argtypes=[pp,ss,C.c_int,C.c_uint16]
 lib.fx_table_controller_range_key.argtypes=[pp,ss,C.c_uint8];lib.fx_table_controller_navigate.argtypes=[pp,ss,C.c_uint8]
 lib.fx_table_controller_accept_handler.argtypes=[pp,ss,C.c_uint8];lib.fx_table_controller_tick.argtypes=[pp,ss]
 lib.fx_table_controller_finish.argtypes=[ss,C.POINTER(C.c_uint8)]
 rom=(ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes();rb=(C.c_uint8*len(rom)).from_buffer_copy(rom)
 failures=[];counts=collections.Counter();checks=0;cases=0;gaps=[];host_checks=0
 def check(index,key,wanted,actual):
  nonlocal checks
  checks+=1;counts[key]+=1
  if wanted!=actual:
   failures.append(dict(case_id=index,key=key,expected=wanted,actual=actual))
   if len(failures)<=8:print(json.dumps(failures[-1]),flush=True)
 # Host API guards and mismatched body completions must preserve the bus.
 guard_ram=(C.c_uint8*65536)(*[0xa5]*65536)
 guard_platform=Platform(rb,len(rom),guard_ram,0,0);guard_state=Controller()
 before_guard=bytes(guard_ram)
 guard_calls=(
  lambda:lib.fx_table_controller_begin(None,C.byref(guard_state),None),
  lambda:lib.fx_table_controller_begin(C.byref(guard_platform),None,None),
  lambda:lib.fx_table_controller_tick(C.byref(guard_platform),C.byref(guard_state)),
  lambda:lib.fx_table_controller_accept_handler(C.byref(guard_platform),C.byref(guard_state),0),
  lambda:lib.fx_table_controller_accept_execution(C.byref(guard_platform),C.byref(guard_state),0,0x8546),
  lambda:lib.fx_table_controller_finish(C.byref(guard_state),None),
 )
 for call in guard_calls:
  check('host-api','invalid_call_status',-1,call())
  check('host-api','invalid_call_preserves_RAM',before_guard.hex(),bytes(guard_ram).hex())
  host_checks+=2
 guard_state.active=1;guard_state.phase=1;guard_state.request=2
 for impossible_status in (32,255,256):
  prior=bytes(guard_state)
  check('host-api','invalid_generation_status',-1,lib.fx_table_controller_accept_execution(C.byref(guard_platform),C.byref(guard_state),impossible_status,0x8546))
  check('host-api','invalid_generation_preserves_RAM',before_guard.hex(),bytes(guard_ram).hex())
  check('host-api','invalid_generation_preserves_state',prior.hex(),bytes(guard_state).hex())
  host_checks+=3
 with gzip.open(archive,'rt') as stream:
  for text in stream:
   case=json.loads(text);row=case['outcome'];index=row['case_id'];cases+=1
   initial=bytes.fromhex(case['initial_ram']);ram=(C.c_uint8*65536).from_buffer_copy(initial);p=Platform(rb,len(rom),ram,0,0);state=Controller()
   floor=int(row['minimum_sp'],16)
   named_context=row['group'] in ('function_entry','parameter','generate','error_resume')
   segments=[(0,0x8000),(0x80dc,floor)]+([(0x8dee,0x9d00),(0x9d0c,65536)] if named_context else [(0x8dee,65536)])
   def differences(wanted):
    actual=bytes(ram);different=[]
    for lo,hi in segments:
     if wanted[lo:hi]!=actual[lo:hi]:different.extend((f'{a:04x}',wanted[a],actual[a]) for a in range(lo,hi) if wanted[a]!=actual[a])
    return different
   def same(key,wanted):
    diff=differences(wanted);check(index,key,[],diff)
   def effects(before,after):
    for lo,hi in segments:
     if before[lo:hi]!=after[lo:hi]:
      for a in range(lo,hi):
       if before[a]!=after[a]:ram[a]=after[a]
   events=case['events'];event_index=0
   def next_event(addresses):
    nonlocal event_index
    for j in range(event_index,len(events)):
     if events[j]['pc'] in addresses:
      event_index=j+1;e=events[j];return e,bytes.fromhex(e['ram'])
    raise AssertionError((index,'missing boundary',addresses,[e['pc'] for e in events[event_index:]]))
   if row['group']=='grid':actual=lib.fx_table_controller_navigate(C.byref(p),C.byref(state),row['token'])
   elif row['group']=='range_key':actual=lib.fx_table_controller_range_key(C.byref(p),C.byref(state),row['token'])
   else:
    context=Context(word(initial,0x9d00),word(initial,0x9d02),initial[0x9d04],initial[0x9d06],initial[0x9d07],initial[0x9d08],initial[0x9d09],initial[0x9d0a])
    actual=lib.fx_table_controller_begin(C.byref(p),C.byref(state),C.byref(context))
   if row['outcome'] not in (100,105):
    check(index,'known_original_nonreturn_domain',True,row['outcome']==103 and row['group']=='grid' and row.get('top',0)>=253)
    check(index,'preserved_original_nonreturn_gap',-2,actual)
    if row['group']=='grid':
     boundary=next(e for e in events if e['pc']=='00e2b4')
     same('nonreturn_prefix_before_native_CPU_frame_overrun',bytes.fromhex(boundary['ram']))
    gaps.append(dict(case_id=index,actual=actual,group=row['group'],native_status=row['outcome'],native_pc=row['pc'],reason='Byte row iterator overflows before a 16-bit top+3 limit; native CPU-local pointer writes are outside host state.'))
    continue
   for iteration in range(5):
    if actual!=5:break
    before_tick=bytes(ram);check(index,'retained_request_status',5,lib.fx_table_controller_tick(C.byref(p),C.byref(state)));check(index,'retained_request_no_RAM',before_tick.hex(),bytes(ram).hex())
    if state.request in (1,2):
     begin,before=next_event({'0171f4'} if state.request==1 else {'004f26'})
     same('execution_request_input',before)
     source_word=er(begin['registers'],0);check(index,'named_source',word(before,source_word),state.current_source)
     end,after=next_event({'01f36c'} if state.request==1 else {'01f2fe','01f32c','01f5ae'})
     effects(before,after)
     actual=lib.fx_table_controller_accept_execution(C.byref(p),C.byref(state),bytes.fromhex(end['registers'])[0],word(after,source_word))
    elif state.request==3:
     begin,before=next_event({'00de7e'});same('prompt_request_input',before)
     effects(before,bytes.fromhex(case['final_ram']));actual=lib.fx_table_controller_accept_handler(C.byref(p),C.byref(state),0)
    elif state.request==4:
     begin,before=next_event({'00d9ee'});same('UI_request_input',before)
     end,after=next_event({'00e1d6','00e3d2'});effects(before,after)
     actual=lib.fx_table_controller_accept_handler(C.byref(p),C.byref(state),bytes.fromhex(end['registers'])[0])
    elif state.request==5:
     begin,before=next_event({'00e3d4'});same('grid_request_input',before)
     end,after=next_event({'00e402'});effects(before,after)
     actual=lib.fx_table_controller_accept_handler(C.byref(p),C.byref(state),0)
    elif state.request==6:
     begin,before=next_event({'00e438','00e440'});same('selected_result_request_input',before)
     check(index,'selected_result_address',er(begin['registers'],0),state.selected_address)
     effects(before,bytes.fromhex(case['final_ram']));actual=lib.fx_table_controller_accept_handler(C.byref(p),C.byref(state),0)
    else:raise AssertionError((index,'unknown request',state.request))
   if actual==0:
    wait,before=next_event({'01d8a4'});same('error_wait_initial',before)
    if 'resume' in row:
     ram[0x8e01],ram[0x8e02]=row['resume'];actual=lib.fx_table_controller_tick(C.byref(p),C.byref(state))
     expected=2 if row['pc']=='01824e' else 3 if row['resume'][1]==128 and row['resume'][0] in (128,64,32) else 1 if row['pc']=='02fffe' else 0
     check(index,'error_resume_status',expected,actual)
   if actual in (0,3):
    check(index,'error_state_remains_active',1,state.active)
    check(index,'error_wait_has_no_subordinate_request',0,state.request)
   if actual<0:gaps.append(dict(case_id=index,actual=actual,group=row['group']))
   else:
    same('final_persistent_RAM',bytes.fromhex(case['final_ram']))
    if named_context:
     final=bytes.fromhex(case['final_ram'])
     wanted=(word(final,0x9d00),word(final,0x9d02),*[final[a] for a in (0x9d04,0x9d06,0x9d07,0x9d08,0x9d09,0x9d0a)])
     check(index,'all_named_context_fields',wanted,tuple(getattr(state.context,n) for n,_ in Context._fields_))
    if actual==1:
     if row['group'] in ('function_entry','parameter','generate','error_resume'):
      check(index,'F12A_action',row['return_value'],state.handler_action)
      check(index,'context_return',bytes.fromhex(case['final_ram'])[0x9d04],state.context.return_value)
     elif row['group']=='range_key':check(index,'range_key_return',row['return_value'],state.handler_action)
     retained=bytes(ram);check(index,'retained_completion_status',1,lib.fx_table_controller_tick(C.byref(p),C.byref(state)));check(index,'retained_completion_no_RAM',retained.hex(),bytes(ram).hex())
     action=C.c_uint8();check(index,'finish_status',1,lib.fx_table_controller_finish(C.byref(state),C.byref(action)))
     check(index,'finish_consumes_active_state',0,state.active)
     check(index,'finish_returns_action',state.handler_action,action.value)
     check(index,'consumed_state_tick_invalid',-1,lib.fx_table_controller_tick(C.byref(p),C.byref(state)))
    if actual==2:
     retained=bytes(ram);check(index,'retained_reset_status',2,lib.fx_table_controller_tick(C.byref(p),C.byref(state)))
     check(index,'retained_reset_no_RAM',retained.hex(),bytes(ram).hex())
     check(index,'reset_finish_status',2,lib.fx_table_controller_finish(C.byref(state),None))
    if row.get('callback') is not None:check(index,'callback_pending',row['callback'],p.callback_pending)
 assert cases==original_metadata['cases'],'Original archive case count mismatch'
 assert pins=={p:sha(p) for p in pins}
 result=dict(scope=__doc__,optimization=args.optimization,cases=cases,checks=checks,host_api_checks=host_checks,failures=failures,host_gaps=gaps,domains=dict(counts),source_sha256=pins,
  comparison='All RAM except8000..80DB arithmetic arena and each actual measured CPU-frame interval. F12A caller context9D00..9D0B is compared through all eight named host fields; unused padding remains outside that named ABI. Grid/range calls also compare the physical9D00..9D0B bytes. All physical rich slots and component workspace remain compared.',
  original_subordinate_observations_supplied_only_during_requests=True,production_parser_or_full_grid_renderer_claim=False)
 (HERE/(args.corpus+'-'+args.optimization+'.json')).write_text(json.dumps(result,indent=2)+'\n')
 print(json.dumps(dict(cases=cases,checks=checks,failures=len(failures),gaps=len(gaps),first_failures=failures[:4]),indent=2))
 if failures:raise SystemExit(1)
 if not args.no_report:
  outside_baseline=[Path(p) for p in pins if Path(p).is_relative_to(ROOT/'analysis') and Path(p).suffix!='.json']
  relative_inputs=[str(Path(p).relative_to(ROOT)) for p in pins if Path(p).suffix!='.so' and Path(p) not in outside_baseline]
  canonical=write_report('analysis/c-verification/table_controller.json',result,relative_inputs,'tools/test_table_controller_c.py')
  # The common baseline only captures JSON under analysis. This suite also
  # pinned its collector, observer, archive and listing before execution and
  # checked those exact bytes again above, before publishing these hashes.
  for extra in outside_baseline:
   if extra.suffix!='.so':canonical['tested_inputs_sha256'][str(extra.relative_to(ROOT))]=pins[str(extra)]
  (ROOT/'analysis/c-verification/table_controller.json').write_text(json.dumps(canonical,indent=2)+'\n')
if __name__=='__main__':main()
