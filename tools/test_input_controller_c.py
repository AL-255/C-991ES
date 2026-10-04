#!/usr/bin/env python3
"""Native F12A input/evaluate/commit and nonblocking error transactions."""
import argparse
import ctypes as C
import json
import hashlib
import random
import subprocess

from c_build_inputs import implementation_inputs
from c_verification import ROOT, write_report
from nxu8.machine import Machine
from test_platform_c import Platform
from test_error_event_c import ErrorEvent
from trace_natural_result import settings

ORACLE_CONTEXT=0x9d00 # Separate from host framebuffer packet9000..9181.

MODULES=[
    'ui/fx_input_controller','ui/fx_input_display','ui/fx_input_prepare','ui/fx_input_recover',
    'ui/fx_input_codec','ui/fx_error_event','ui/fx_error_boundary','ui/fx_error_display','ui/fx_key_controller',
    'ui/fx_key_wait','ui/fx_annunciator','ui/fx_cursor','ui/fx_keys','ui/fx_key_dispatch',
    'ui/fx_editor','ui/fx_natural_editor',
    'platform/fx_platform','platform/fx_host_bridge','platform/fx_boot','platform/fx_boot_events',
    'platform/fx_persistent','platform/fx_diagnostic_contrast','platform/fx_result_classify',
    'parse/fx_tokens','parse/fx_eval','parse/fx_eval_storage','parse/fx_eval_finish','numeric/fx_numeric','numeric/fx_random','numeric/fx_transcend','numeric/fx_power',
    'numeric/fx_root','numeric/fx_combinatorics','numeric/fx_logbase','numeric/fx_calculus',
    'numeric/fx_integral','numeric/fx_derivative','numeric/fx_base','numeric/fx_base_literal',
    'numeric/fx_sexagesimal','numeric/fx_quotient_remainder',
    'numeric/fx_raw_decimal_parts','numeric/fx_raw_decimal_divide',
    'numeric/fx_raw_decimal_multiply_add','numeric/fx_raw_fraction_convert',
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
    args=ap.parse_args()
    build=ROOT/'analysis/build/input-controller';build.mkdir(parents=True,exist_ok=True)
    sources=['csrc/'+module+'.c' for module in MODULES]
    output=build/'controller.so'
    subprocess.run(['gcc','-std=c99','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',
                    '-Wl,--no-undefined','-I',str(ROOT/'csrc'),*[str(ROOT/f) for f in sources],'-o',str(output)],check=True)
    lib=C.CDLL(str(output))
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
    adapter='tools/nxu8/input_controller_events.c'
    oracle=build/'events.so'
    subprocess.run(['gcc','-std=c99','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',
                    str(ROOT/adapter),str(ROOT/'tools/nxu8/vendor/SimU8/core.c'),
                    '-o',str(oracle)],check=True)
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
        Cancel=C.CFUNCTYPE(C.c_int,C.c_void_p)
        def cancelled(_):
            state.polls.append(bytes(ram[0x8276:0x8280]))
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
        stack_floor=getattr(state,'native_presentation_stack_floor',0x8b00) if presentation else 0x8b00
        excludes=[(stack_floor,0x8dee)]
        if numeric:excludes += [(0x8000,0x80dc),(0x8640,0x87d0)]
        if numeric and state.input[0] in (0x6a,0x6b):excludes += [(0x850a,0x8640)]
        if presentation:excludes += [(0x8640,0x8708)]
        differences=[(hex(a),actual[a],expected[a]) for a in range(65536)
                     if actual[a]!=expected[a] and not any(lo<=a<hi for lo,hi in excludes)]
        assert not differences,(group,detail,differences[:40])
        assert p.callback_pending==native.lib.harness_callback(),(group,detail,'callback')
        p.callback_pending=0;count(group)
        assert state.polls==[bytes(native_x[n]) for n in range(native_polls.value)],(group,detail,'poll_X')

    def success(expression,detail,**kw):
        state,actual=prepare(expression,**kw)
        assert actual==4,(detail,'begin',actual)
        run(0x1f2ac);compare('preparation',detail,state)
        actual=lib.fx_input_controller_tick(C.byref(p),C.byref(state))
        assert actual==1,(detail,'evaluate',actual,state.unsupported_token,state.evaluator_status)
        run(0x2fffe)
        assert state.handler_action==native.reg(0),(detail,'action',state.handler_action,native.reg(0))
        compare('success_transaction',detail,state,True)
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
    report={'cases':sum(counts.values()),'domains':counts,'unsupported_native_fixtures':gaps,
        'native_presentation_stack_witnesses':stack_witnesses,
        'comparison':'Original F12A preparation and completed ordinary COMP/CMPLX transactions; native status, named context return and remaining64KiB RAM/LCD/MMIO/callbacks. CPU stack8B00..8DED is excluded; natural CMPLX Pol presentation additionally excludes traced PUSH XR0 bytes down to its measured minimum SP, with write-PC witnesses retained. After numeric evaluation, excluded called workspaces are8000..80DB and40 ten-byte surd/common-denominator operand slots8640..87CF; integral/derivative transactions additionally exclude850A..863F. Presentation excludes inherited inactive layout slots8640..8707. Cancellation callback X records and counts are compared independently.',
        'scope':'Ordinary COMP/CMPLX preparation, evaluation, variable/Ans/replay commit, colon continuation, cancellation, nonblocking error wait/recovery/reset/host exports, ordinary natural/linear expression and result presentation; mode45/12/4B initial history/result gates. Paired Pol/Rec and quotient/remainder transactions and presentation, AF polar expressions, coordinate writes before later syntax failures, quotient fallback sentinel clearing and native labels/metadata are compared.'}
    if not args.no_report:
        deps=implementation_inputs(ROOT,sources)+['tools/test_platform_c.py','tools/test_error_event_c.py',
             'tools/test_key_controller_c.py','tools/test_key_wait_c.py','tools/test_boot_c.py',
             'tools/trace_natural_result.py','tools/verify_firmware.py','tools/nxu8/decoder.py',
             'tools/c_build_inputs.py','tools/c_verification.py',adapter]
        report=write_report('analysis/c-verification/input_controller.json',report,deps,'tools/test_input_controller_c.py')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
