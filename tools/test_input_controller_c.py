#!/usr/bin/env python3
"""Native F12A input/evaluate/commit and nonblocking error transactions."""
import argparse
import ctypes as C
import json
import hashlib
import random
import subprocess
import sys

from c_build_inputs import implementation_inputs
from c_verification import ROOT, write_report
from pathlib import Path
from nxu8.machine import Machine
from test_platform_c import Platform
from test_error_event_c import ErrorEvent
from trace_natural_result import settings

ORACLE_CONTEXT=0x9d00 # Separate from host framebuffer packet9000..9181.

MODULES=[
    'ui/fx_linalg_controller','ui/fx_ui_controller','ui/fx_construct_editor',
    'ui/fx_equation_controller','ui/fx_equation_result','numeric/fx_solver',
    'linalg/fx_linalg_reduce','render/fx_result_linalg','ui/fx_mode_setup','ui/fx_menu_navigator',
    'ui/fx_input_controller','ui/fx_input_display','ui/fx_input_prepare','ui/fx_input_recover',
    'ui/fx_input_codec','ui/fx_error_event','ui/fx_error_boundary','ui/fx_error_display','ui/fx_key_controller',
    'ui/fx_key_wait','ui/fx_annunciator','ui/fx_cursor','ui/fx_keys','ui/fx_key_dispatch',
    'ui/fx_editor','ui/fx_natural_editor',
    'platform/fx_platform','platform/fx_host_bridge','platform/fx_boot','platform/fx_boot_events',
    'platform/fx_persistent','platform/fx_diagnostic_contrast','platform/fx_result_classify',
    'parse/fx_tokens','parse/fx_eval','parse/fx_eval_rich','parse/fx_eval_rich_unary','parse/fx_eval_rich_reduce','parse/fx_eval_surd_workspace','numeric/fx_raw_decimal_exp', 'stats/fx_stats', 'stats/fx_stats_value','parse/fx_eval_storage','parse/fx_eval_finish','numeric/fx_numeric','numeric/fx_random','numeric/fx_transcend','numeric/fx_power',
    'numeric/fx_root','numeric/fx_combinatorics','numeric/fx_logbase','numeric/fx_calculus',
    'numeric/fx_integral', 'numeric/fx_integral_storage','numeric/fx_c4_integral_storage','numeric/fx_derivative', 'numeric/fx_derivative_storage', 'numeric/fx_surd_components','numeric/fx_base','numeric/fx_base_literal',
    'numeric/fx_sexagesimal','numeric/fx_quotient_remainder',
    'numeric/fx_raw_decimal_parts','numeric/fx_raw_decimal_divide',
    'numeric/fx_raw_decimal_multiply_add','numeric/fx_raw_fraction_convert','numeric/fx_raw_rational',
    'complex/fx_complex','complex/fx_complex_angle','complex/fx_complex_round','complex/fx_complex_dispatch',
    'linalg/fx_linalg','linalg/fx_linalg_store',
    'trig/fx_trig','trig/fx_trig_math','trig/fx_trig_inverse','trig/fx_trig_hyperbolic','trig/fx_math_context',
    'format/fx_format','format/fx_format_base','format/fx_format_budget',
    'render/fx_render','render/fx_render_context','render/fx_render_memory','render/fx_layout','render/fx_layout_validate','render/fx_viewport',
    'render/fx_result','render/fx_result_special','render/fx_result_linear','render/fx_result_complex','render/fx_result_pair',
    'render/fx_result_inequality','render/fx_result_format_state','data/fx_rom_data']


class Number(C.Structure):
    _fields_=[('bytes',C.c_uint8*10)]
class Variables(C.Structure):
    _fields_=[('values',(Number*2)*10)]
class Control(C.Structure):
    _fields_=[('cancelled',C.c_void_p),('userdata',C.c_void_p)]
class Context(C.Structure):
    _fields_=[('display_address',C.c_uint16),('result_address',C.c_uint16),
              *[(n,C.c_uint8) for n in ('return_value','calculation_mode','saved_math_result',
                                       'natural_input','natural_result','special_view')]]
class Controller(C.Structure):
    _fields_=[('context',Context),('error',ErrorEvent),('variables',Variables),
              ('original_variables',Variables),('saved_result',Number*2),('cancellation',Control),
              ('prepared_source',C.c_uint16),('current_source',C.c_uint16),
              *[(n,C.c_uint8) for n in ('evaluator_status','handler_action','continuation',
                                       'preparation_ok','phase','active','unsupported_token')],
              ('input',C.c_uint8*1024)]


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--random-cases',type=int,default=4000)
    ap.add_argument('--no-report',action='store_true')
    ap.add_argument('--optimization',choices=['O2','O3'],default='O2')
    ap.add_argument('--source-root',type=Path,default=ROOT)
    ap.add_argument('--fixture',type=Path,default=ROOT/'analysis/native-fixtures/input-controller-physical/inputs.json')
    ap.add_argument('--build-dir',type=Path,default=ROOT/'analysis/build/input-controller')
    args=ap.parse_args()
    if not args.no_report and args.random_cases<4000:
        ap.error('Canonical publication retains all4000 existing random controls')
    if args.source_root.resolve()!=ROOT.resolve() and not args.no_report:
        ap.error('Private source-root requires --no-report')
    canonical_fixture=ROOT/'analysis/native-fixtures/input-controller-physical/inputs.json'
    if args.fixture.resolve()!=canonical_fixture.resolve() and not args.no_report:
        ap.error('Custom fixture requires --no-report')
    fixture_hash=hashlib.sha256(args.fixture.read_bytes()).hexdigest()
    assert fixture_hash=='b3247f288651a4af8e66317a9cf3de2226be935332f53aaa2e3405cec4277361'
    fixture=json.loads(args.fixture.read_text())
    assert set(fixture)=={'schema','provenance','expected_cases','rows'}
    assert fixture['schema']==1 and fixture['expected_cases']==len(fixture['rows'])==69
    assert len({row['id'] for row in fixture['rows']})==69
    assert sum(row['kind']=='success' for row in fixture['rows'])==54
    assert sum(row['kind']=='error' for row in fixture['rows'])==12
    assert {row.get('guard') for row in fixture['rows'] if row['kind']=='host_guard'}=={'output-ROM','output-overrun','input-overrun'}
    build=args.build_dir;build.mkdir(parents=True,exist_ok=True)
    modules=list(MODULES)
    for module in ('ui/fx_linalg_controller','ui/fx_ui_controller','ui/fx_construct_editor','render/fx_result_linalg'):
        if (args.source_root/('csrc/'+module+'.c')).is_file() and module not in modules:
            modules.append(module)
    sources=['csrc/'+module+'.c' for module in modules]
    closure=implementation_inputs(args.source_root,sources)
    pins={f:hashlib.sha256((args.source_root/f).read_bytes()).hexdigest() for f in closure}
    python_helpers={Path(module.__file__).resolve() for module in list(sys.modules.values())
        if getattr(module,'__file__',None) and Path(module.__file__).suffix=='.py'
        and Path(module.__file__).resolve().is_relative_to(ROOT/'tools')}
    python_helpers.add(Path(__file__).resolve())
    helper_pins={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in python_helpers}
    probe_rows=[]
    for ctype,python_type in [('fx_platform',Platform),('fx_number',Number),
            ('fx_eval_variables',Variables),('fx_calculus_control',Control),
            ('fx_input_context',Context),('fx_error_event',ErrorEvent),
            ('fx_input_controller',Controller)]:
        probe_rows.append((f'sizeof({ctype})',C.sizeof(python_type)))
        for field,*_ in python_type._fields_:
            probe_rows.append((f'offsetof({ctype},{field})',getattr(python_type,field).offset))
    probe='#include "ui/fx_input_controller.h"\n#include <stddef.h>\nsize_t input_test_abi(unsigned n){const size_t v[]={'
    probe+=','.join(code for code,_ in probe_rows)+'};return n<sizeof(v)/sizeof(v[0])?v[n]:0;}\n'
    output=build/'controller.so'
    subprocess.run(['gcc','-std=c99','-'+args.optimization,'-Wall','-Wextra','-Werror','-shared','-fPIC',
                    '-Wl,--no-undefined','-I',str(args.source_root/'csrc'),*[str(args.source_root/f) for f in sources],'-x','c','-','-o',str(output)],input=probe,text=True,check=True)
    compiled_hash=hashlib.sha256(output.read_bytes()).hexdigest()
    lib=C.CDLL(str(output))
    lib.input_test_abi.argtypes=[C.c_uint];lib.input_test_abi.restype=C.c_size_t
    abi_actual=[lib.input_test_abi(n) for n in range(len(probe_rows))]
    assert abi_actual==[value for _,value in probe_rows],('compiled_input_ABI',abi_actual,probe_rows)
    pp=C.POINTER(Platform)
    lib.fx_input_context_capture.argtypes=[pp,C.c_uint16,C.c_uint16]
    lib.fx_input_context_capture.restype=Context
    lib.fx_input_controller_begin.argtypes=[pp,C.POINTER(Controller),C.POINTER(Context),C.POINTER(Control)]
    lib.fx_input_controller_tick.argtypes=[pp,C.POINTER(Controller)]
    lib.fx_input_controller_finish.argtypes=[C.POINTER(Controller),C.POINTER(C.c_uint8)]
    lib.fx_input_controller_present.argtypes=[pp,C.POINTER(Controller)]
    lib.fx_input_draw_linear_expression.argtypes=[pp]
    rom=(ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    rb=(C.c_uint8*len(rom)).from_buffer_copy(rom);ram=(C.c_uint8*65536)()
    p=Platform(rb,len(rom),ram,0,0);native=Machine(rom,build/'oracle')
    adapter='tools/nxu8/input_physical_events.c'
    oracle=build/'events.so'
    subprocess.run(['gcc','-std=c99','-'+args.optimization,'-Wall','-Wextra','-Werror','-shared','-fPIC',
                    str(ROOT/adapter),str(ROOT/'tools/nxu8/vendor/SimU8/core.c'),
                    '-o',str(oracle)],check=True)
    observer_hash=hashlib.sha256(oracle.read_bytes()).hexdigest()
    observer_inputs=[adapter,'tools/nxu8/input_controller_events.c','tools/nxu8/harness.c','tools/nxu8/vendor/SimU8/core.c']
    observer_inputs += [str(f.relative_to(ROOT)) for f in (ROOT/'tools/nxu8/vendor/SimU8').glob('*.h')]
    observer_pins={f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in observer_inputs}
    events=C.CDLL(str(oracle))
    for name in ('harness_init','harness_set_pc','harness_get_pc','harness_set_reg',
                 'harness_get_reg','harness_set_sp','harness_get_sp','harness_set_lr',
                 'harness_ram','harness_run','harness_trace_open'):
        getattr(events,name).argtypes=getattr(native.lib,name).argtypes
        getattr(events,name).restype=getattr(native.lib,name).restype
    events.input_controller_run.argtypes=[C.c_uint64,C.c_uint32,C.c_uint]
    native.lib=events;native.ram=events.harness_ram().contents;native.reset()
    native_polls=C.c_uint.in_dll(events,'input_controller_polls')
    native_x=((C.c_uint8*10)*8192).in_dll(events,'input_controller_poll_x')
    native_workspaces=((C.c_uint8*0xc6)*8192).in_dll(events,'input_physical_poll_workspace')
    native_floor=C.c_uint.in_dll(events,'input_physical_floor')
    native_entries=C.c_uint.in_dll(events,'input_physical_entry_count')
    native_source=C.c_uint16.in_dll(events,'input_physical_source')
    native_output=C.c_uint16.in_dll(events,'input_physical_output')
    native_returned=C.c_uint16.in_dll(events,'input_physical_returned_source')
    abort_poll=0
    rng=random.Random(0xf12a);counts={};gaps=[];stack_witnesses=[]
    background=bytearray(rng.randbytes(65536))
    background[0x8dee:0x8e00]=rom[0x1f8dc:0x1f8ee]
    def count(group):counts[group]=counts.get(group,0)+1
    def put(a,v):ram[a]=native.ram[a]=v
    def word(a,v):put(a,v&255);put(a+1,v>>8)
    def string(a,v):
        for i,b in enumerate(v+b'\0\0'):put(a+i,b)
    def run(stop):
        result=native.lib.input_controller_run(50000000,stop,abort_poll)
        assert result==100,(result,hex(native.lib.harness_get_pc()),hex(stop))
    def prepare(expression=b'1+2',mode=0xc1,natural=1,angle=4,token=0xf0,
                saved=0,continuation=0,selection=0,context_mode=None,cancel=0,
                variable_record=None,imaginary_record=None,old_imaginary=None,
                screen=1,item=0,replay=None,replay_index=0,evaluator_flags=0,
                polar=0):
        nonlocal abort_poll
        abort_poll=cancel;events.input_controller_observations_reset()
        native.reset();C.memmove(native.ram,bytes(background),65536);settings(native)
        C.memmove(ram,native.ram,65536)
        for a,v in ((0x80f9,mode),(0x80fa,1),(0x80fc,screen),(0x80fd,item),
                    (0x80fe,1|continuation),(0x80ff,0),(0x80f5,token),(0x80f7,1),
                    (0x80f8,0),(0x80fb,0),(0x80f4,0),(0x8100,selection),
                    (0x8101,0),(0x8102,0),(0x8103,0),(0x8104,1),(0x8105,angle),
                    (0x8106,natural),(0x8107,0),(0x8108,0 if polar else 1),(0x810c,0),
                    (0x8120,0),(0x8121,1),(0x8124,evaluator_flags),(0x8125,0xa5),
                    (0x8113,replay_index),
                    (0x8129,0),(0x8130,0),(0x8138,0),(0x80dd,0),(0x8114,0),
                    (0x8116,0),(0x8117,1),(0x8118,0),(0x8119,1),(0x811a,0x7c),
                    (0x811b,10),(0x811c,1),(0x811d,1),(0x811e,1),(0x811f,10),
                    (0x8127,0),(0x8128,0),(0x8e01,0),(0x8e02,0)):
            put(a,v)
        word(0x812c,0x8154);word(0x812e,0x8398)
        string(0x8154,expression);string(0x81b8,b'prior input')
        for a in (0x829e,0x8406,0x84e2,0x8546,0x8398):
            for n in range(250):put(a+n,0)
        for a in (0x8226,0x8408):
            for n in range(100):put(a+n,0)
        if variable_record is not None:
            for slot in range(10):
                for n,b in enumerate(variable_record):put(0x8226+10*slot+n,b)
        if imaginary_record is not None:
            for slot in range(10):
                for n,b in enumerate(imaginary_record):put(0x8408+10*slot+n,b)
        if replay is not None:
            base=0x8406 if mode==0x45 else 0x84e2 if mode==12 else 0x829e
            for n,b in enumerate(replay):put(base+n,b)
        for n,b in enumerate(bytes.fromhex('09000000000000000001')+bytes(10)):put(0x8140+n,b)
        if old_imaginary is not None:
            for n,b in enumerate(old_imaginary):put(0x814a+n,b)
        context=lib.fx_input_context_capture(C.byref(p),0x8154,0x8140)
        context.saved_math_result=saved
        if context_mode is not None:context.calculation_mode=context_mode
        context.return_value=1
        word(ORACLE_CONTEXT,context.display_address);word(ORACLE_CONTEXT+2,context.result_address)
        for offset,v in ((4,context.return_value),(5,0),(6,context.calculation_mode),
                         (7,context.saved_math_result),(8,context.natural_input),
                         (9,context.natural_result),(10,context.special_view),(11,0)):
            put(ORACLE_CONTEXT+offset,v)
        p.callback_pending=p.status=0
        state=Controller()
        state.polls=[]
        state.poll_workspaces=[]
        Cancel=C.CFUNCTYPE(C.c_int,C.c_void_p)
        def cancelled(_):
            state.polls.append(bytes(ram[0x8276:0x8280]))
            state.poll_workspaces.append(bytes(ram[0x850a:0x85d0]))
            return int(cancel and len(state.polls)==cancel)
        state.callback=Cancel(cancelled)
        control=Control(C.cast(state.callback,C.c_void_p),None)
        actual=lib.fx_input_controller_begin(C.byref(p),C.byref(state),C.byref(context),C.byref(control))
        native.er(0,ORACLE_CONTEXT);native.lib.harness_set_sp(0x8dee)
        native.lib.harness_set_lr(0x2fffe);native.lib.harness_set_pc(0x1f12a)
        return state,actual

    def compare(group,detail,state,numeric=False,presentation=False):
        actual=bytearray(ram);expected=bytes(native.ram)
        actual[ORACLE_CONTEXT+4]=state.context.return_value
        stack_floor=min(native_floor.value,getattr(state,'native_presentation_stack_floor',0x8dee))
        excludes=[(stack_floor,0x8dee)]
        if numeric:excludes += [(0x8000,0x80dc)]
        integral=0x6a in bytes(state.input).split(b'\0',1)[0]
        if numeric and not integral:excludes += [(0x8640,0x87d0)]
        if numeric and state.input[0]==0x6b:excludes += [(0x850a,0x8640)]
        if presentation and not integral:excludes += [(0x8640,0x8708)]
        differences=[(hex(a),actual[a],expected[a]) for a in range(65536)
                     if actual[a]!=expected[a] and not any(lo<=a<hi for lo,hi in excludes)]
        assert not differences,(group,detail,differences[:40])
        assert p.callback_pending==native.lib.harness_callback(),(group,detail,'callback')
        p.callback_pending=0;count(group)
        assert state.polls==[bytes(native_x[n]) for n in range(native_polls.value)],(group,detail,'poll_X')
        if integral and hasattr(state,'poll_workspaces'):
            expected_work=[bytes(native_workspaces[n]) for n in range(native_polls.value)]
            assert state.poll_workspaces==expected_work,(group,detail,'poll_workspace',[(n,[(hex(0x850a+i),a,b) for i,(a,b) in enumerate(zip(actual,expected)) if a!=b][:12]) for n,(actual,expected) in enumerate(zip(state.poll_workspaces,expected_work)) if actual!=expected][:3])

    def success(expression,detail,**kw):
        state,actual=prepare(expression,**kw)
        assert actual==4,(detail,'begin',actual)
        run(0x1f2ac);compare('preparation',detail,state)
        actual=lib.fx_input_controller_tick(C.byref(p),C.byref(state))
        assert actual==1,(detail,'evaluate',actual,state.unsupported_token,state.evaluator_status)
        run(0x2fffe)
        assert state.handler_action==native.reg(0),(detail,'action',state.handler_action,native.reg(0))
        compare('success_transaction',detail,state,True)
        assert native_entries.value==1,(detail,'entry_count',native_entries.value)
        assert native_source.value==state.prepared_source,(detail,'source',hex(native_source.value),hex(state.prepared_source))
        assert native_output.value==state.context.result_address,(detail,'output',native_output.value,state.context.result_address)
        assert native_returned.value==state.current_source,(detail,'returned_source',hex(native_returned.value),hex(state.current_source))
        count('all_input_address_contract')
        return state

    def present(state,detail):
        actual=lib.fx_input_controller_present(C.byref(p),C.byref(state))
        assert actual==1,(detail,'present',actual)
        trace_polar=state.evaluator_status==34 and state.context.calculation_mode==0xc4 and state.context.natural_result
        if trace_polar:native.trace_open(build/'pol-presentation.trace.csv',reads=False)
        native.call(0x1ee7c)
        if native.ram[0x80fe]!=1:
            native.er(0,state.context.result_address);native.call(0xb070)
        if trace_polar:
            native.trace_close()
            instructions={};lowest=0x8b00;stack_writes=[]
            for line in (build/'pol-presentation.trace.csv').read_text().splitlines():
                fields=line.split(',')
                if fields[0]=='I':
                    instructions[fields[1]]=fields
                    lowest=min(lowest,int(fields[3],16))
                elif fields[0]=='W' and int(fields[3],16)==0:
                    address,size=int(fields[4],16),int(fields[5])
                    if 0x8a00<=address<0x8b00:
                        instruction=instructions[fields[1]];pc=int(instruction[2],16)
                        # Each newly exposed byte is a real PUSH XR0 below
                        # the previous fixed CPU-stack boundary, not a result
                        # or persistent workspace write hidden by a mask.
                        assert rom[pc:pc+2]==b'\x6e\xf0',(detail,fields,instruction)
                        stack_writes.append({'pc':hex(pc),'sp_before':instruction[3],
                                             'address':hex(address),'size':size})
            assert lowest>=0x8a00,(detail,'unexpected_stack_depth',hex(lowest))
            state.native_presentation_stack_floor=lowest
            stack_witnesses.append({'expression':bytes(state.input).split(b'\0',1)[0].hex(),
                                    'minimum_sp':hex(lowest),'writes_below_8b00':stack_writes})
        if not native.ram[0x80fe]&32:
            native.call(0x1e9a0)
            if native.reg(0)>0:native.ram[0x8129]=1
        compare('result_presentation',detail,state,True,True)

    def error(expression,detail,token_pair=(4,16),events_before=(),**kw):
        state,actual=prepare(expression,**kw)
        assert actual==4,(detail,'begin',actual)
        run(0x1f2ac);compare('error_preparation',detail,state)
        actual=lib.fx_input_controller_tick(C.byref(p),C.byref(state))
        assert actual==0,(detail,'error_begin',actual,state.evaluator_status)
        run(0x1d8a4);compare('error_wait_begin',detail,state,True)
        assert native_entries.value==1,(detail,'entry_count',native_entries.value)
        assert native_source.value==state.prepared_source,(detail,'source',hex(native_source.value),hex(state.prepared_source))
        assert native_output.value==state.context.result_address,(detail,'output',native_output.value,state.context.result_address)
        assert native_returned.value==state.current_source,(detail,'returned_source',hex(native_returned.value),hex(state.current_source))
        count('all_error_address_contract')
        for pair in events_before:
            put(0x8e01,pair[0]);put(0x8e02,pair[1])
            actual=lib.fx_input_controller_tick(C.byref(p),C.byref(state))
            run(0x1d8a6)
            if pair==(0,0):
                run(0x1d8d2);expected=0
            else:
                run(0x1db5e)
                if pair[1]==128 and pair[0] in (128,64,32):
                    run(0x1db56);run(0x1d8a4);expected=3
                else:
                    run(0x1d8a4);expected=0
            assert actual==expected,(detail,'wait_event',pair,actual,expected)
            compare('error_wait_event_'+str(expected),(detail,pair),state,True)
        # Every wait performs an iteration even for preloaded input.
        put(0x8e01,token_pair[0]);put(0x8e02,token_pair[1])
        actual=lib.fx_input_controller_tick(C.byref(p),C.byref(state))
        assert actual==1,(detail,'error_recover',actual)
        run(0x2fffe)
        assert state.handler_action==native.reg(0),(detail,'error_action',state.handler_action,native.reg(0))
        compare('error_accepted_and_recovered',detail,state,True)
        assert bytes(ram[0x8e01:0x8e03])==bytes(token_pair),(detail,'raw_pair_retained')
        if state.handler_action==1:present(state,('recovered_input',detail))
        action=C.c_uint8(255)
        assert lib.fx_input_controller_finish(C.byref(state),C.byref(action))==1
        assert action.value==state.handler_action
        count('nonblocking_error_completion')

    for natural in (0,1):
        for mode in (0xc1,0xc4):
            for expression in (b'1+2',b'3-5',b'1N3',b'2^3',b'98',b'0',b'2(3+4)'):
                success(expression,(expression.hex(),natural,mode),natural=natural,mode=mode)
    for mode in (0xc1,0xc4):
        for expression in (b'1+2',b'1O3',b'\x98\xb82\xb9',
                           bytes.fromhex('aebbb898b8393938b92d98b8393937b9b9b83939b9bc')):
            state=success(expression,('presentation',mode,expression.hex()),mode=mode)
            present(state,(mode,expression.hex()))
    for expression in (b'1+2\x80',b'(1+2\x80)(3+4\x80)',b'\x98\x602)'):
        for natural in (0,1):
            for polar in (0,1):
                state=success(expression,('complex_presentation',expression.hex(),natural,polar),
                              mode=0xc4,natural=natural,polar=polar)
                present(state,(expression.hex(),natural,polar))
    for expression in (b'123456789012345678901234567890',b'\xa030)',b'A+1O3',
                       b'\x98(123)+\x68(456)',b'12:34',b''):
        for cursor in range(len(expression)+1):
            for origin in (0,6,30):
                state,begun=prepare(expression,natural=0)
                run(0x1f2ac if begun==4 else 0x2fffe)
                put(0x8114,cursor);put(0x8116,origin)
                actual=lib.fx_input_draw_linear_expression(C.byref(p))
                assert actual==0,('linear_row',expression.hex(),cursor,origin,actual)
                native.call(0x8282)
                compare('linear_expression_row',(expression.hex(),cursor,origin),state)
    for mode in (0xc1,0xc4):
        for expression in (b'1+2',b'1O3',b'\x982)',b'1.23456789+2.3456789'):
            state=success(expression,('linear_presentation',mode,expression.hex()),mode=mode,natural=0)
            present(state,(mode,expression.hex()))
    for natural in (0,1):
        for mode in (0xc1,0xc4):
            for expression in (b'1+',b'1O0',b'(1+)'):
                for pair in ((4,16),(128,8),(64,4)):
                    error(expression,(expression.hex(),natural,mode,pair),natural=natural,mode=mode,token_pair=pair)
    stores=[0x4b,0x47,0x48,0x49,0x4a,0x83,0x84,0x4c,0x4d,0x99,0xa9]
    for mode in (0xc1,0xc4):
        for natural in (0,1):
            for suffix in stores:
                success(b'3'+bytes([suffix]),('store',mode,natural,suffix),mode=mode,natural=natural,
                        variable_record=bytes.fromhex('07000000000000000001'),
                        imaginary_record=bytes.fromhex('01000000000000000001'))
    for natural in (0,1):
        for saved in (0,1):
            for pair in ((4,16),(128,8),(64,4)):
                error(b'1+',('saved_error',natural,saved,pair),natural=natural,saved=saved,
                      token_pair=pair,old_imaginary=bytes.fromhex('08000000000000000001'))
    for expression in (b'\x69X,1,4)',b'\x5dX,1,4)'):
        success(expression,('series',expression.hex()),natural=0,
                variable_record=bytes.fromhex('07000000000000000001'))
        for cancel in (1,2,4):
            error(expression,('series_cancel',expression.hex(),cancel),natural=0,cancel=cancel,
                  variable_record=bytes.fromhex('07000000000000000001'))
    for expression in (b'\x6aX,0,1)',b'\x6bX,1)'):
        success(expression,('continuous',expression.hex()),natural=0,
                variable_record=bytes.fromhex('07000000000000000001'))
        error(expression,('continuous_cancel',expression.hex()),natural=0,cancel=1,
              variable_record=bytes.fromhex('07000000000000000001'))
    error(b'1+',('export_and_retry',),events_before=((0,0),(1,1),(1,8),(2,64),
          (0,0),(128,128),(64,128),(32,128)))
    for mode in (0xc1,0xc4):
        for natural in (0,1):
            first=success(b'1+2:3+4',('colon_first',mode,natural),mode=mode,natural=natural)
            assert first.continuation and ram[0x80fe]&64
            context=lib.fx_input_context_capture(C.byref(p),0x8154,0x8140)
            context.return_value=1
            for offset,v in ((4,1),(6,context.calculation_mode),(7,context.saved_math_result),
                             (8,context.natural_input),(9,context.natural_result),(10,context.special_view)):
                put(ORACLE_CONTEXT+offset,v)
            state=Controller();state.polls=[]
            assert lib.fx_input_controller_begin(C.byref(p),C.byref(state),C.byref(context),None)==4
            native.er(0,ORACLE_CONTEXT);native.lib.harness_set_sp(0x8dee)
            native.lib.harness_set_lr(0x2fffe);native.lib.harness_set_pc(0x1f12a)
            run(0x1f2ac);compare('colon_continuation_preparation',(mode,natural),state,True)
            assert lib.fx_input_controller_tick(C.byref(p),C.byref(state))==1
            run(0x2fffe);compare('colon_continuation_commit',(mode,natural),state,True)
    entry=bytes([0,0xad,0])+bytes.fromhex('07000000000000000001')+b'3+4:\0'
    for mode in (0x45,12,0x4b):
        for selection in (0,0x0d,0xad):
            for item in (0,3):
                for replay_index in (0,1,255):
                    state,actual=prepare(mode=mode,selection=selection,item=item,
                                         replay=entry,replay_index=replay_index)
                    assert actual==1,('history_gate',mode,selection,item,replay_index,actual)
                    run(0x2fffe)
                    assert state.handler_action==native.reg(0)
                    compare('history_and_context_gates',(mode,selection,item,replay_index),state)
    for flags in range(256):
        success(b'\x982)',('evaluator_flags',flags),natural=0,evaluator_flags=flags)
    for mode in (0xc1,0xc4):
        state,actual=prepare(b'',mode=mode)
        assert actual==1 and state.handler_action==0
        run(0x2fffe);compare('empty_input_gate',mode,state)
    state,actual=prepare(b'1+')
    assert actual==4;run(0x1f2ac)
    assert lib.fx_input_controller_tick(C.byref(p),C.byref(state))==0
    run(0x1d8a4)
    put(0x8e01,16);put(0x8e02,128)
    assert lib.fx_input_controller_tick(C.byref(p),C.byref(state))==2
    run(0x1824e);compare('error_host_reset_request',0,state,True)
    assert lib.fx_input_controller_finish(C.byref(state),None)==2
    count('reset_completion')
    for mode in (0xc1,0xc4):
        for natural in (0,1):
            for expression in (b'\x6c3,4)',b'\x6d2,30)',b'2_30',b'10_3',
                               b'\x6010_3',b'2.5_1.2',b'2\xaf30',
                               b'\x6c3,4)+1',b'(\x6c3,4))',b'\x6c3,4)\x47',
                               b'\x6d.999999999999999,0)'):
                state=success(expression,('paired_transaction',mode,natural,expression.hex()),
                              mode=mode,natural=natural,
                              variable_record=bytes.fromhex('07000000000000000001'),
                              imaginary_record=bytes.fromhex('01000000000000000001'))
                present(state,('paired_or_scalar_presentation',mode,natural,expression.hex()))
            for expression in (b'\x6c3,4,5)',b'\x6d2,30,4)',b'\x6c0,0)',
                               b'\x6d\x602,30)',b'\x6c3,4\x47)',b'10_0'):
                error(expression,('paired_error',mode,natural,expression.hex()),
                      mode=mode,natural=natural,
                      variable_record=bytes.fromhex('07000000000000000001'),
                      imaginary_record=bytes.fromhex('01000000000000000001'))
    for i in range(args.random_cases):
        a,b=rng.randrange(1,100000),rng.randrange(1,100000)
        op=rng.choice([b'+',b'-',b'N',b'O'])
        expression=str(a).encode()+op+str(b).encode()
        state=success(expression,i,natural=rng.randrange(2),mode=rng.choice([0xc1,0xc4]))
        if i%10==0:present(state,('random_presentation',i))
        expression=bytes(rng.choices(b'1234567890+-NO().ABC'+bytes([0x98,0xa0,0xa1,0xa2,0x82]),k=rng.randrange(1,60)))
        state,begun=prepare(expression,natural=0,mode=rng.choice([0xc1,0xc4]))
        run(0x1f2ac if begun==4 else 0x2fffe)
        put(0x8114,rng.randrange(len(expression)+1));put(0x8116,rng.choice([0,6,12,30]))
        assert lib.fx_input_draw_linear_expression(C.byref(p))==0
        native.call(0x8282);compare('random_linear_rows',i,state)
    inactive=Controller();action=C.c_uint8(255)
    for actual in (lib.fx_input_controller_begin(None,C.byref(inactive),None,None),
                   lib.fx_input_controller_tick(C.byref(p),C.byref(inactive)),
                   lib.fx_input_controller_finish(C.byref(inactive),C.byref(action)),
                   lib.fx_input_controller_present(C.byref(p),C.byref(inactive))):
        assert actual==-1
        count('explicit_invalid_lifecycle')
    for row in fixture['rows']:
        setup=dict(row['setup'])
        if 'variable_record' in setup:setup['variable_record']=bytes.fromhex(setup['variable_record'])
        expression=bytes.fromhex(row['tokens'])
        if row['kind']=='success':
            state=success(expression,('physical_integral',row['id']),**setup)
            count('physical_integral_address_contract')
        elif row['kind']=='error':
            error(expression,('physical_integral_abort',row['id']),**setup)
        else:
            # Early physical-source rejection leaves outputs untouched. The
            # caller initializes its result before consuming unsupported_token.
            state,actual=prepare(expression,**setup)
            assert actual==4,(row['id'],'prepare',actual)
            if row['guard']=='output-ROM':state.context.result_address=0x7fff
            elif row['guard']=='output-overrun':state.context.result_address=0xffff
            else:
                state.current_source=0xffff
                ram[0xffff]=ord('1')
            state.unsupported_token=0xa5
            assert lib.fx_input_controller_tick(C.byref(p),C.byref(state))==-2,(row['id'],'early_rejection')
            assert state.unsupported_token==0,(row['id'],'initialized_unsupported',state.unsupported_token)
            assert not state.polls,(row['id'],'unexpected_poll')
            count('explicit_host_address_boundary')
    changes=[f for f,digest in pins.items() if hashlib.sha256((args.source_root/f).read_bytes()).hexdigest()!=digest]
    changes += [f for f,digest in observer_pins.items() if hashlib.sha256((ROOT/f).read_bytes()).hexdigest()!=digest]
    changes += [f for f,digest in helper_pins.items() if hashlib.sha256(Path(f).read_bytes()).hexdigest()!=digest]
    if hashlib.sha256(args.fixture.read_bytes()).hexdigest()!=fixture_hash:changes.append(str(args.fixture))
    if hashlib.sha256(output.read_bytes()).hexdigest()!=compiled_hash:changes.append(str(output))
    if hashlib.sha256(oracle.read_bytes()).hexdigest()!=observer_hash:changes.append(str(oracle))
    assert not changes,('tested_input_changed',changes)
    report={'cases':sum(counts.values()),'domains':counts,'unsupported_native_fixtures':gaps,
        'native_presentation_stack_witnesses':stack_witnesses,
        'optimization':args.optimization,'fixture_sha256':fixture_hash,'appended_input_recipes':len(fixture['rows']),
        'compiled_ABI':abi_actual,'compiled_artifact_sha256':compiled_hash,'observer_artifact_sha256':observer_hash,
        'source_changes':changes,'random_controls':args.random_cases,'retained_legacy_control_generation_seed':'0xf12a',
        'comparison':'Original F12A preparation and completed ordinary COMP/CMPLX transactions; native status, named context return and remaining64KiB RAM/LCD/MMIO/callbacks. Only each transaction’s passively measured original CPU stack interval and numerical8000..80DB scratch are excluded. Integral transactions compare the entire850A..87CF physical workspace, all poll-time850A..85CF records and cancellation X/count. Other historical arithmetic transactions retain their documented8640..87CF operand workspace exclusion, and derivative transactions retain850A..863F exclusion. Only non-integral presentation retains inactive layout8640..8707 exclusion; integral recovery presentation compares the entire physical workspace. Native actual input/output/local-cursor contracts are asserted for every ordinary success/error transaction. The eight mode6/7 recovery presentations use the rich controller’s verified mode admissions and are compared as completed native presentations, without a workspace mask.',
        'scope':'Ordinary COMP/CMPLX preparation, evaluation, variable/Ans/replay commit, colon continuation, cancellation, nonblocking error wait/recovery/reset/host exports, ordinary natural/linear expression and result presentation; mode45/12/4B initial history/result gates. Paired Pol/Rec and quotient/remainder transactions and presentation, AF polar expressions, coordinate writes before later syntax failures, quotient fallback sentinel clearing and native labels/metadata are compared.'}
    if not args.no_report:
        deps=implementation_inputs(ROOT,sources)+['tools/test_platform_c.py','tools/test_error_event_c.py',
             'tools/test_key_controller_c.py','tools/test_key_wait_c.py','tools/test_boot_c.py',
             'tools/trace_natural_result.py','tools/verify_firmware.py','tools/nxu8/decoder.py',
             'tools/c_build_inputs.py','tools/c_verification.py',*observer_inputs,
             'analysis/native-fixtures/input-controller-physical/inputs.json']
        deps += [str(Path(f).relative_to(ROOT)) for f in helper_pins if Path(f).is_relative_to(ROOT)]
        report=write_report('analysis/c-verification/input_controller.json',report,deps,'tools/test_input_controller_c.py')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
