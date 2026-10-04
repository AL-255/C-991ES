#!/usr/bin/env python3
"""Original differential proof of actual TABLE88 C subordinate composition.

Handwritten C executes continued/ordinary parsing, named row generation, F12A
controller requests, physical polling and painting. Original outcomes are only
comparisons. Whole main/D9EE admission remains a separate runtime boundary.
"""
import argparse
import ast
import collections
import ctypes as C
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from c_build_inputs import implementation_inputs
from c_verification import write_report
from nxu8.machine import Machine
from test_input_controller_c import MODULES,Context,Number
from test_table_controller_c import Controller
from test_platform_c import Platform
from test_table_c import Poll
from test_eval_environment_c import Storage,Effects
from test_eval_variables_c import Result

class Execution(C.Structure):
    _fields_=[('returned_source',C.c_uint16),('evaluator_calls',C.c_uint),('body_status',C.c_int)]
class Source(C.Structure):
    _fields_=[('input_address',C.c_uint16),('output_address',C.c_uint16),('before_sample',C.c_void_p),('userdata',C.c_void_p)]

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def tool_dependency_closure(paths):
    """Pin local Python modules used by imported layouts and input recipes."""
    pending=list(paths);found=set()
    while pending:
        relative=pending.pop()
        if relative in found:continue
        found.add(relative)
        path=ROOT/relative
        if path.suffix!='.py':continue
        for node in ast.walk(ast.parse(path.read_text())):
            modules=[n.name for n in node.names]if isinstance(node,ast.Import)else [node.module]if isinstance(node,ast.ImportFrom)and node.module else []
            for module in modules:
                local=Path('tools')/Path(*module.split('.')).with_suffix('.py')
                if (ROOT/local).is_file():pending.append(str(local))
    return sorted(found)

def restored(segments):
    ram=bytearray(65536)
    previous_end=0
    for address,hexbytes in segments:
        raw=bytes.fromhex(hexbytes)
        if not isinstance(address,int) or address<previous_end or address+len(raw)>65536 or not raw:
            raise ValueError('Malformed or overlapping input RAM segment')
        ram[address:address+len(raw)]=raw
        previous_end=address+len(raw)
    return bytes(ram)

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--optimization',choices=('O2','O3'),default='O2')
    ap.add_argument('--source-root',type=Path,default=ROOT)
    ap.add_argument('--fixture',type=Path,default=ROOT/'analysis/native-fixtures/table-composition/inputs.json')
    ap.add_argument('--build-dir',type=Path,default=ROOT/'analysis/build/table-composition')
    ap.add_argument('--no-report',action='store_true',help='Write diagnostics only; mandatory for a private source root')
    args=ap.parse_args()
    if args.source_root.resolve()!=ROOT.resolve() and not args.no_report:
        ap.error('A private source root requires --no-report')
    if not args.no_report and args.fixture.resolve()!= (ROOT/'analysis/native-fixtures/table-composition/inputs.json').resolve():
        ap.error('Canonical publication requires the default complete input-only fixture')
    build=args.build_dir;build.mkdir(parents=True,exist_ok=True)
    recipe=json.loads(args.fixture.read_text())
    expected_counts={'continued':828,'controller':370,'parameter':264,'presentation':1856,'range':798,'architecture':120}
    if recipe.get('schema')!=1 or recipe.get('expected_cases')!=4236 or len(recipe.get('rows',[]))!=4236:
        raise ValueError('The complete4236-row input recipe is required')
    if collections.Counter(r['scope']for r in recipe['rows'])!=expected_counts:
        raise ValueError('Malformed or incomplete fixture scope counts')
    if [r['case_id']for r in recipe['rows']]!=list(range(4236)):
        raise ValueError('Fixture IDs must be unique and ordered')
    for row in recipe['rows']:
        if set(row)!= {'scope','setup','ram_segments','case_id'}:
            raise ValueError('Input recipe has unexpected output/unknown fields')
        restored(row['ram_segments'])
    names=list(dict.fromkeys(['csrc/'+n+'.c'for n in MODULES]+[
        'csrc/table/fx_table.c','csrc/table/fx_table_controller.c','csrc/table/fx_table_runtime.c',
        'csrc/table/fx_table_device.c','csrc/table/fx_table_expression_display.c',
        'csrc/table/fx_table_presentation.c','csrc/table/fx_table_range.c',
        'csrc/stats/fx_stats_editor.c','csrc/render/fx_result_linalg.c']))
    source_inputs=implementation_inputs(args.source_root,names)
    common=['tools/test_table_composition_c.py','tools/nxu8/table_composition_events.c',
        'tools/nxu8/table_composition_abi.c','tools/nxu8/machine.py','tools/nxu8/harness.c',
        'tools/nxu8/vendor/SimU8/core.c','tools/test_input_controller_c.py',
        'tools/test_table_controller_c.py','tools/test_platform_c.py','tools/test_table_c.py',
        'tools/test_eval_environment_c.py','tools/test_eval_variables_c.py',
        'tools/c_build_inputs.py','tools/c_verification.py','firmware/fx-991es-plus-c-ver4.bin']
    common=tool_dependency_closure(common)
    common += [str(p.relative_to(ROOT))for p in (ROOT/'tools/nxu8/vendor/SimU8').glob('*.h')]
    pins={str(args.source_root/p):sha(args.source_root/p)for p in source_inputs}
    pins.update({str(ROOT/p):sha(ROOT/p)for p in common})
    pins[str(args.fixture)]=sha(args.fixture)
    output=build/('table-composition-'+args.optimization+'.so')
    subprocess.run(['gcc','-std=c99','-'+args.optimization,'-Wall','-Wextra','-Werror',
        '-shared','-fPIC','-Wl,--no-undefined','-I'+str(args.source_root/'csrc'),
        *[str(args.source_root/n)for n in names],str(ROOT/'tools/nxu8/table_composition_abi.c'),
        '-o',str(output)],check=True)
    lib=C.CDLL(str(output));pp=C.POINTER(Platform);ss=C.POINTER(Controller)
    lib.table_composition_abi.argtypes=[C.c_uint];lib.table_composition_abi.restype=C.c_size_t
    abi=[C.sizeof(Platform),C.sizeof(Controller),C.sizeof(Context),C.sizeof(Execution),C.sizeof(Source),C.sizeof(Result),
         Execution.returned_source.offset,Execution.evaluator_calls.offset,Execution.body_status.offset,
         Source.input_address.offset,Source.output_address.offset,Source.before_sample.offset,Source.userdata.offset,
         Controller.context.offset,Controller.error.offset,Controller.saved_result.offset,
         Controller.current_source.offset,Controller.request.offset,Controller.phase.offset,
         Context.display_address.offset,Context.result_address.offset,Context.return_value.offset,
         Context.calculation_mode.offset,Context.special_view.offset]
    if abi!=[lib.table_composition_abi(i)for i in range(len(abi))]:
        raise ValueError('The compiled production ABI does not match verifier layouts')
    lib.fx_table_controller_begin.argtypes=[pp,ss,C.POINTER(Context)]
    lib.fx_table_execute_request.argtypes=[pp,ss,Poll,C.c_void_p,C.POINTER(Execution)]
    lib.fx_table_poll_device.argtypes=[pp,C.c_uint8]
    lib.fx_table_controller_navigate.argtypes=[pp,ss,C.c_uint8]
    lib.fx_table_present_request.argtypes=[pp,ss]
    lib.fx_table_controller_accept_handler.argtypes=[pp,ss,C.c_uint8]
    lib.fx_table_draw_linear_expression.argtypes=[pp]
    lib.fx_table_prepare_range_prompt.argtypes=[pp,C.c_uint8,C.POINTER(C.c_uint8)]
    lib.fx_table_refresh_expression.argtypes=[pp]
    lib.fx_evaluate_table_expression.argtypes=[C.POINTER(C.c_uint8),C.c_size_t,C.POINTER(Storage),C.POINTER(Effects),C.POINTER(Result)]
    lib.fx_evaluate_table_parameter_source.argtypes=[C.c_size_t,C.POINTER(Storage),C.POINTER(Source),C.POINTER(C.c_uint16),C.POINTER(Number),C.POINTER(Result)]
    rom=(ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes();rb=(C.c_uint8*len(rom)).from_buffer_copy(rom)
    native=Machine(rom,build/'base');oracle=build/'observer.so'
    subprocess.run(['gcc','-std=c99','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',
        '-I'+str(ROOT/'tools/nxu8'),str(ROOT/'tools/nxu8/table_composition_events.c'),
        str(ROOT/'tools/nxu8/vendor/SimU8/core.c'),'-o',str(oracle)],check=True)
    nl=C.CDLL(str(oracle))
    for name in ('harness_init','harness_ram','harness_set_reg','harness_get_reg','harness_set_sp','harness_get_sp','harness_set_lr','harness_set_pc','harness_get_pc'):
        getattr(nl,name).argtypes=getattr(native.lib,name).argtypes
        getattr(nl,name).restype=getattr(native.lib,name).restype
    native.lib=nl;native.ram=nl.harness_ram().contents
    nl.observer_reset.argtypes=[C.c_uint];nl.observer_run.argtypes=[C.c_uint64,C.c_uint32]
    count=C.c_uint.in_dll(nl,'event_count');minimum=C.c_uint.in_dll(nl,'minimum_sp')
    pcs=(C.c_uint32*128).in_dll(nl,'event_pc');registers=((C.c_uint8*16)*128).in_dll(nl,'event_regs')
    memories=((C.c_uint8*65536)*128).in_dll(nl,'event_ram')
    pins[str(output)]=sha(output);pins[str(oracle)]=sha(oracle)
    failures=[];observations=[];gaps=[];checks=0;scope_checks=collections.Counter()
    def check(row,key,wanted,actual):
        nonlocal checks
        checks+=1;scope_checks[row['scope']]+=1
        if wanted!=actual:
            failure=dict(case_id=row['case_id'],scope=row['scope'],key=key,expected=wanted,actual=actual)
            failures.append(failure)
            if len(failures)<=8:print(json.dumps(failure),flush=True)
    archive=build/('native-states-'+args.optimization+'.jsonl.gz')
    with gzip.open(archive,'wt')as stream:
        for row in recipe['rows']:
            scope=row['scope'];spec=row['setup'];initial=restored(row['ram_segments'])
            native.reset();C.memmove(native.ram,initial,65536)
            native.er(0,0x9d00);native.er(8,0x9d00)
            stop=0x2fffe;entry=0x1f12a
            if scope=='continued':
                entry=0x171ea;native.er(12,0x9000);native.er(14,0x8200);native.er(10,0);native.er(8,0x0103);native.reg(6,1)
            elif scope=='parameter':
                entry=0x171f4;native.er(0,0x9900);native.er(2,spec['output_address'])
            elif scope in('presentation','architecture'):
                entry=0x8282 if spec.get('group')=='expression' else 0xe22a
            elif scope=='range':
                entry=0xde7e if spec['group']=='prompt' else 0x1ee7c
                if spec['group']=='prompt':native.reg(0,spec['item']);native.reg(1,0);native.reg(2,1);stop=0xdf34
            nl.harness_set_sp(0x8dee);nl.harness_set_lr(0x2fffe);nl.observer_reset(spec.get('cancel',0));nl.harness_set_pc(entry)
            outcome=nl.observer_run(5000000,stop);after=bytes(native.ram);floor=minimum.value
            events=[dict(pc=pcs[j],regs=bytes(registers[j]),ram=bytes(memories[j]))for j in range(count.value)]
            indices=[a for a in range(0x80dc,65536)if not floor<=a<0x8dee
                and not(scope=='continued'and 0x9000<=a<0x903c)
                and not(scope=='controller'and 0x9d00<=a<0x9d0c)
                and not(scope=='parameter'and a in(0x9900,0x9901))]
            ram=(C.c_uint8*65536).from_buffer_copy(initial);platform=Platform(rb,len(rom),ram,0,0);storage=Storage(ram,65536,rb,len(rom));state=Controller()
            event_cursor=0;polls=0;evaluations=0;bodies=[]
            def same(key,wanted):
                check(row,key,[],[(f'{a:04x}',wanted[a],ram[a])for a in indices if wanted[a]!=ram[a]])
            def boundary(pc):
                nonlocal event_cursor
                for j in range(event_cursor,len(events)):
                    if events[j]['pc']==pc:event_cursor=j+1;return events[j]
                raise AssertionError((row['case_id'],'missing original boundary',hex(pc)))
            @Poll
            def poll(_user,address):
                nonlocal polls
                before=boundary(0x5550);same('C_device_input',before['ram']);polls+=1
                status=lib.fx_table_poll_device(C.byref(platform),2 if spec.get('cancel')==polls else 0)
                after_poll=boundary(0x5578);same('C_device_output',after_poll['ram']);check(row,'C_device_status',after_poll['regs'][0],status)
                return status
            if scope=='continued':
                result=Result();effects=Effects();length=len(bytes.fromhex(spec['tokens']))+1
                live=C.cast(C.byref(ram,0x8200),C.POINTER(C.c_uint8))
                status=lib.fx_evaluate_table_expression(live,length,C.byref(storage),C.byref(effects),C.byref(result))
                check(row,'continued_status',native.reg(0),status);check(row,'continued_named_source',native.er(14),0x8200+result.consumed)
                if native.reg(0)==255:check(row,'continued_primary',after[0x9000:0x900a].hex(),bytes(result.value[0]).hex())
                same('continued_all_persistent_RAM',after)
            elif scope=='parameter':
                source=Source(spec['input_address'],spec['output_address'],None,None);cursor=C.c_uint16(source.input_address);result=Result();prior=Number();prior.bytes[:]=initial[0x828a:0x8294]
                status=lib.fx_evaluate_table_parameter_source(len(bytes.fromhex(spec['tokens']))+1,C.byref(storage),C.byref(source),C.byref(cursor),C.byref(prior),C.byref(result))
                check(row,'parameter_status',native.reg(0),status);check(row,'parameter_named_source',native.word(0x9900),cursor.value);same('parameter_all_persistent_RAM',after)
            elif scope=='controller':
                context=Context(0x8154,0x8140,1,0x88,0,0,0,int(spec.get('screen')==6 and spec.get('item')in(1,2,3)))
                status=lib.fx_table_controller_begin(C.byref(platform),C.byref(state),C.byref(context))
                for _iteration in range(3):
                    if status!=5:break
                    request=state.request
                    if request not in(1,2):raise AssertionError(('unexpected TABLE request',request))
                    begin=boundary(0x4f26 if request==2 else 0x171f4);same('C_body_input',begin['ram'])
                    word=int.from_bytes(begin['regs'][:2],'little');check(row,'C_body_named_source',int.from_bytes(begin['ram'][word:word+2],'little'),state.current_source)
                    execution=Execution();status=lib.fx_table_execute_request(C.byref(platform),C.byref(state),poll,None,C.byref(execution))
                    evaluations+=execution.evaluator_calls;bodies.append(dict(request=request,status=execution.body_status,source=execution.returned_source,evaluations=execution.evaluator_calls))
                check(row,'C_controller_terminal',0 if outcome==105 else 1,status);same('C_controller_all_persistent_RAM',after)
                check(row,'C_evaluator_calls',sum(e['pc']in(0x171ea,0x171f4)for e in events),evaluations);check(row,'C_device_calls',sum(e['pc']==0x5550 for e in events),polls)
                if outcome==100:
                    terminal=events[-1];check(row,'C_handler_action',terminal['regs'][0],state.handler_action)
                    expected=list(after[0x9d00:0x9d05])+list(after[0x9d06:0x9d0b]);actual=[state.context.display_address&255,state.context.display_address>>8,state.context.result_address&255,state.context.result_address>>8,state.context.return_value,state.context.calculation_mode,state.context.saved_math_result,state.context.natural_input,state.context.natural_result,state.context.special_view]
                    check(row,'C_named_context',expected,actual)
            elif scope=='presentation':
                if spec['group']=='expression':status=lib.fx_table_draw_linear_expression(C.byref(platform));check(row,'expression_status',0,status)
                else:
                    status=lib.fx_table_controller_navigate(C.byref(platform),C.byref(state),spec['token'])
                    for _iteration in range(3):
                        if status!=5:break
                        if state.request==5:
                            same('grid_paint_input',boundary(0xe3d4)['ram']);value=lib.fx_table_present_request(C.byref(platform),C.byref(state));check(row,'grid_paint_status',0,value);same('grid_paint_output',boundary(0xe402)['ram'])
                        elif state.request==6:
                            before=next(e for e in events if e['pc']in(0xe438,0xe440));same('selected_paint_input',before['ram']);value=lib.fx_table_present_request(C.byref(platform),C.byref(state));check(row,'selected_paint_status',0,value)
                        else:raise AssertionError(('unexpected presentation request',state.request))
                        status=lib.fx_table_controller_accept_handler(C.byref(platform),C.byref(state),0)
                    check(row,'grid_controller_terminal',1,status)
                same('presentation_all_persistent_RAM',after)
            elif scope=='range':
                if spec['group']=='prompt':
                    refresh=C.c_uint8();status=lib.fx_table_prepare_range_prompt(C.byref(platform),spec['item'],C.byref(refresh));check(row,'prompt_refresh_argument',native.reg(0),refresh.value)
                else:status=lib.fx_table_refresh_expression(C.byref(platform))
                check(row,'range_C_status',0,status);same('range_all_persistent_RAM',after)
            else:
                status=lib.fx_table_controller_navigate(C.byref(platform),C.byref(state),spec['token'])
                check(row,'architectural_native_nonreturn',103,outcome);check(row,'architectural_C_boundary',-2,status)
                same('architectural_C_prefix_before_CPU_overrun',boundary(0xe2b4)['ram'])
                gaps.append(dict(case_id=row['case_id'],kind='grid_top_byte_iterator_overruns_CPU_local_array',native_outcome=outcome,native_pc=f'{nl.harness_get_pc():06x}',C_status=status))
            if scope!='architecture':check(row,'original_return_or_error_wait',True,outcome in(100,105))
            observation=dict(case_id=row['case_id'],scope=scope,native_outcome=outcome,entry=f'{entry:06x}',stop=f'{stop:06x}',minimum_sp=f'{floor:04x}',C_status=status,bodies=bodies)
            observations.append(observation)
            stream.write(json.dumps(dict(initial_ram=initial.hex(),final_ram=after.hex(),events=[dict(pc=f'{e["pc"]:06x}',registers=e['regs'].hex(),ram=e['ram'].hex())for e in events],outcome=observation),separators=(',',':'))+'\n')
            if len(observations)%500==0:print(json.dumps(dict(completed=len(observations),total=4236,failures=len(failures))),flush=True)
    changes=[path for path,digest in pins.items()if sha(path)!=digest]
    report=dict(status='pass'if not failures and not changes else 'fail',optimization=args.optimization,
        cases=len(observations),original_calls=len(observations),checks=checks,failures=failures,
        source_changes=changes,explicit_architectural_gaps=gaps,matching_supported_original_calls=4116 if not failures else None,
        scope_cases=expected_counts,scope_checks=dict(scope_checks),input_sha256=pins,
        ABI_layout=abi,artifact_sha256={str(output):sha(output),str(oracle):sha(oracle),str(archive):sha(archive)},
        original_subordinate_outputs_supplied_to_C=False,external_device_input='Readiness0/2 only; C computes timer/status/MMIO.',
        full_TABLE_mode_complete=False,whole_D9EE_and_main_dispatch_complete=False,
        comparison='Actual TABLE88 original status, named cursors/context, persistent64KiB workspace/LCD/MMIO and actual C request boundaries. Arithmetic arena8000..80DB and observed activeCPUframes are excluded. Continued caller-private9000..903B, native parameter cursor9900..9901 and supplied F12A context9D00..9D0B are compared through named C records/cursor/context. All120 native grid iterator nonreturns remain explicit with matching C prefix.')
    diagnostic=build/('result-'+args.optimization+'.json');diagnostic.write_text(json.dumps(dict(report=report,observations=observations),indent=2)+'\n')
    if failures or changes:raise AssertionError((len(failures),changes))
    if not args.no_report:
        dependencies=source_inputs+common+['analysis/native-fixtures/table-composition/inputs.json']
        report=write_report('analysis/c-verification/table_composition.json',report,sorted(set(dependencies)),'tools/test_table_composition_c.py')
    print(json.dumps(dict(cases=len(observations),checks=checks,failures=len(failures),architectural_gaps=len(gaps),canonical_published=not args.no_report)))

if __name__=='__main__':main()
