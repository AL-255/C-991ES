#!/usr/bin/env python3
"""True original D9EE entry, named host state and resumable UI transactions."""
import argparse
import ctypes as C
import json
import hashlib
import random
import subprocess
from c_verification import ROOT, write_report
from c_build_inputs import implementation_inputs
from nxu8.machine import Machine
from test_platform_c import Platform
from test_input_controller_c import MODULES, Context, Controller as Input, Control
from trace_natural_result import settings

class Controller(C.Structure):
    _fields_=[('context',Context),('input',Input),('cancellation',Control),
              ('request',C.c_int),*[(n,C.c_uint8) for n in
              ('phase','active','refresh_only','structured_input','command_token',
               'command_index','handler_action','saved_result_state')]]

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--random-cases',type=int,default=4000)
    ap.add_argument('--no-report',action='store_true')
    args=ap.parse_args()
    build=ROOT/'analysis/build/ui-controller';build.mkdir(parents=True,exist_ok=True)
    sources=list(dict.fromkeys(['csrc/ui/fx_ui_controller.c','csrc/ui/fx_construct_editor.c',
             *['csrc/'+m+'.c' for m in MODULES]]))
    library=build/'ui.so'
    subprocess.run(['gcc','-std=c99','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',
                    '-Wl,--no-undefined','-I',str(ROOT/'csrc'),*[str(ROOT/f) for f in sources],'-o',str(library)],check=True)
    lib=C.CDLL(str(library));pp=C.POINTER(Platform)
    lib.fx_ui_controller_begin.argtypes=[pp,C.POINTER(Controller),C.c_uint8,C.POINTER(Control)]
    lib.fx_ui_controller_tick.argtypes=[pp,C.POINTER(Controller)]
    lib.fx_ui_controller_finish.argtypes=[C.POINTER(Controller),C.POINTER(C.c_uint8)]
    lib.fx_decimal_parse.argtypes=[C.c_void_p,C.c_char_p]
    rom=(ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    rb=(C.c_uint8*len(rom)).from_buffer_copy(rom);ram=(C.c_uint8*65536)()
    p=Platform(rb,len(rom),ram,0,0);native=Machine(rom,build/'oracle')
    adapter='tools/nxu8/ui_controller_events.c';oracle=build/'events.so'
    subprocess.run(['gcc','-std=c99','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',
        str(ROOT/adapter),str(ROOT/'tools/nxu8/vendor/SimU8/core.c'),'-o',str(oracle)],check=True)
    events=C.CDLL(str(oracle))
    for name in ('harness_init','harness_set_pc','harness_get_pc','harness_set_reg',
                 'harness_get_reg','harness_set_sp','harness_get_sp','harness_set_lr',
                 'harness_ram','harness_run','harness_trace_open'):
        getattr(events,name).argtypes=getattr(native.lib,name).argtypes
        getattr(events,name).restype=getattr(native.lib,name).restype
    events.ui_controller_run.argtypes=[C.c_uint64,C.c_uint32,C.c_uint]
    native.lib=events;native.ram=events.harness_ram().contents;native.reset()
    native_polls=C.c_uint.in_dll(events,'input_controller_polls')
    native_x=((C.c_uint8*10)*8192).in_dll(events,'input_controller_poll_x')
    stack_floor=C.c_uint16.in_dll(events,'ui_controller_min_sp')
    abort_poll=0
    rng=random.Random(0xd9ee);counts={};gaps=[];background=rng.randbytes(65536)
    lowest_stack=0x8dee
    def count(group):counts[group]=counts.get(group,0)+1
    def put(a,v):ram[a]=native.ram[a]=v
    def word(a,v):put(a,v&255);put(a+1,v>>8)
    def string(a,b):
        for n,v in enumerate(b+b'\0\0'):put(a+n,v)
    def run(stop):
        result=native.lib.ui_controller_run(50000000,stop,abort_poll)
        assert result==100,(result,hex(native.lib.harness_get_pc()),hex(stop))
    def compare(group,detail,numeric=False,continuous=False):
        nonlocal lowest_stack
        lowest_stack=min(lowest_stack,stack_floor.value)
        exclusions=[(stack_floor.value,0x8dee)]
        if numeric:exclusions += [(0x8000,0x80dc),(0x8640,0x87d0)]
        if continuous:exclusions += [(0x850a,0x8640)]
        diff=[(hex(n),ram[n],native.ram[n]) for n in range(65536)
              if ram[n]!=native.ram[n] and not any(lo<=n<hi for lo,hi in exclusions)]
        assert not diff,(group,detail,diff[:30])
        assert p.callback_pending==native.lib.harness_callback(),(group,detail,'callback')
        p.callback_pending=0;count(group)
    def prepare(expression=b'1+2',token=0xf0,natural=1,mode=0xc1,flags=1,
                cursor=0,decoded=1,refresh=0,cache=0,selection=0,modifiers=0,
                cancel=0,real=None,imaginary=None,polar=1,metadata=0):
        nonlocal abort_poll
        abort_poll=cancel;events.ui_controller_observations_reset()
        native.reset();C.memmove(native.ram,background,65536);settings(native)
        C.memmove(ram,native.ram,65536)
        for a,v in ((0x80f9,mode),(0x80fa,1),(0x80fb,0),(0x80fc,1),(0x80fd,0),
                    (0x80fe,flags),(0x80ff,0),(0x80f5,token),(0x80f7,decoded),(0x80f8,modifiers),
                    (0x8100,selection),(0x8101,metadata),(0x8102,0),(0x8103,0),(0x8104,1),(0x8105,4),
                    (0x8106,natural),(0x8107,0),(0x8108,polar),(0x810c,0),(0x8113,0),
                    (0x8114,cursor),(0x8116,0),(0x8117,1),(0x8118,0),(0x8119,1),
                    (0x811a,0x7c),(0x811b,10),(0x811c,1),(0x811d,1),(0x811e,1),(0x811f,10),
                    (0x8120,0),(0x8121,1),(0x8124,0),(0x8125,0),(0x8126,0),(0x8127,0),
                    (0x8128,0),(0x8129,0),(0x8130,cache),(0x8138,0),(0x80dd,0),
                    (0x8e00,0),(0x8e01,0),(0x8e02,0)):
            put(a,v)
        word(0x812c,0x8154);word(0x812e,0x8398)
        for a,length in ((0x8226,100),(0x8408,100),(0x829e,250),(0x8398,100),
                         (0x81b8,100),(0x8140,20)):
            for n in range(length):put(a+n,0)
        string(0x8154,expression)
        if real is not None:
            for n,b in enumerate(real):put(0x8140+n,b)
        if imaginary is not None:
            for n,b in enumerate(imaginary):put(0x814a+n,b)
        state=Controller()
        state.polls=[];Cancel=C.CFUNCTYPE(C.c_int,C.c_void_p)
        def cancelled(_):
            state.polls.append(bytes(ram[0x8276:0x8280]))
            return int(cancel and len(state.polls)==cancel)
        state.callback=Cancel(cancelled)
        control=Control(C.cast(state.callback,C.c_void_p),None)
        assert lib.fx_ui_controller_begin(C.byref(p),C.byref(state),refresh,C.byref(control))==4
        native.reg(0,refresh);native.lib.harness_set_sp(0x8dee)
        native.lib.harness_set_lr(0x2fffe);native.lib.harness_set_pc(0xd9ee)
        run(0xda58);compare('entry_preparation',(expression.hex(),token,natural,mode,flags),False)
        base=native.er(14)-12
        fields=[native.word(base),native.word(base+2),native.ram[base+4],native.ram[base+6],
                native.ram[base+7],native.ram[base+8],native.ram[base+9],native.ram[base+10]]
        expected=[state.context.display_address,state.context.result_address,state.context.return_value,
                  state.context.calculation_mode,state.context.saved_math_result,state.context.natural_input,
                  state.context.natural_result,state.context.special_view]
        assert fields==expected,('context',fields,expected)
        return state
    def complete(state,detail,numeric=True,continuous=False,key=None,auto_error=False,
                 events_before=()):
        for _ in range(4):
            actual=lib.fx_ui_controller_tick(C.byref(p),C.byref(state))
            if actual!=4:break
        if auto_error and actual==0:key=(4,16)
        if key is not None:
            assert actual==0,('wait',detail,actual,state.request,state.command_token)
            run(0x1d8a4);compare('full_entry_error_wait',detail,True,continuous)
            for pair in events_before:
                put(0x8e01,pair[0]);put(0x8e02,pair[1])
                actual=lib.fx_ui_controller_tick(C.byref(p),C.byref(state))
                run(0x1d8a6)
                if pair==(0,0):
                    run(0x1d8d2);expected=0
                else:
                    run(0x1db5e)
                    if pair[1]==128 and pair[0] in (128,64,32):
                        run(0x1db56);run(0x1d8a4);expected=3
                    else:run(0x1d8a4);expected=0
                assert actual==expected,(detail,'wait_event',pair,actual,expected)
                compare('full_entry_wait_event_'+str(expected),(detail,pair),True,continuous)
            put(0x8e01,key[0]);put(0x8e02,key[1])
            actual=lib.fx_ui_controller_tick(C.byref(p),C.byref(state))
        assert actual==1,('completion',detail,actual,state.request,state.command_token)
        run(0x2fffe)
        assert state.context.return_value==native.reg(0),('return',detail,state.context.return_value,native.reg(0))
        compare('full_entry_completion',detail,numeric,continuous)
        assert state.polls==[bytes(native_x[n]) for n in range(native_polls.value)],(detail,'X_callback')
        out=C.c_uint8(255)
        assert lib.fx_ui_controller_finish(C.byref(state),C.byref(out))==1
        assert out.value==native.reg(0)
        count('host_completion')
    for natural in (0,1):
        for mode in (0xc1,0xc4):
            for token in (0xe6,0xf0,0xed,0xe2,0xe3,0xfe,0xe0,0xe1):
                for flags in (1,3):
                    if token in (0xe0,0xe1) and flags==3:continue
                    state=prepare(token=token,natural=natural,mode=mode,flags=flags,cursor=1)
                    complete(state,('command',token,natural,mode,flags))
            for token in (ord('1'),ord('+'),0x98,0x8b,0xcf,0xd0):
                for flags in (1,3):
                    state=prepare(token=token,natural=natural,mode=mode,flags=flags,cursor=1)
                    complete(state,('typing',token,natural,mode,flags))
            state=prepare(natural=natural,mode=mode,refresh=1)
            complete(state,('refresh',natural,mode))
    for n in range(args.random_cases):
        expression=str(rng.randrange(1,100000)).encode()+rng.choice([b'+',b'-',b'N',b'O'])+str(rng.randrange(1,100000)).encode()
        state=prepare(expression,natural=rng.randrange(2),mode=rng.choice([0xc1,0xc4]))
        complete(state,('random_evaluate',n))
    for natural in (0,1):
        for mode in (0xc1,0xc4):
            for expression in (b'1+',b'1O0'):
                for pair in ((4,16),(128,8),(64,4)):
                    state=prepare(expression,natural=natural,mode=mode)
                    complete(state,('error',natural,mode,expression.hex(),pair),key=pair)
            if mode==0xc4:
                for polar in (0,1):
                    state=prepare(b'1+2\x80',natural=natural,mode=mode,polar=polar)
                    complete(state,('complex_full_entry',natural,polar))
        for expression in (b'\x69X,1,4)',b'\x5dX,1,4)',b'\x6aX,0,1)',b'\x6bX,1)'):
            for cancel in (0,1):
                state=prepare(expression,natural=0,cancel=cancel)
                complete(state,('host_callback',expression.hex(),cancel),
                         continuous=expression[0] in (0x6a,0x6b),key=(4,16) if cancel else None)
    for natural in (0,1):
        for mode in (0xc1,0xc4):
            for token in (0xe4,0xe5,0xf1,0xf2,0xf3,0xf4,0xf5,0xf6,0xf7,0xf8,0xf9,0xfa,0xfb):
                for selection in (0x00,0x11,0xa5,0xbb,0xcc,0xdd):
                    state=prepare(token=token,natural=natural,mode=mode,flags=3,selection=selection,
                                  real=bytes.fromhex('03000000000000000001'))
                    complete(state,('format',natural,mode,token,selection))
            for token in range(14,32):
                state=prepare(token=token,natural=natural,mode=mode,cursor=1)
                complete(state,('decoded_command',natural,mode,token))
    for text in ('0','1','2','12','1024','997','1009','9999999999','10000000000',
                 '-2','1.5','2.5','2.00000000000001','1e-99','1e99'):
        record=(C.c_uint8*10)()
        assert lib.fx_decimal_parse(record,text.encode())==0
        for natural in (0,1):
            state=prepare(token=0xf1,natural=natural,flags=3,real=bytes(record))
            complete(state,('prime_domain',text,natural),auto_error=True)
    for natural in (0,1):
        state=prepare(b'',token=0xe6,natural=natural,flags=0)
        complete(state,('initial_AC',natural))
        for token in (*b'1+2',0xf0,0xe0,0xe1):
            events.input_controller_observations_reset()
            put(0x80f5,token);put(0x80f7,1)
            state=Controller();state.polls=[]
            assert lib.fx_ui_controller_begin(C.byref(p),C.byref(state),0,None)==4
            native.reg(0,0);native.lib.harness_set_sp(0x8dee)
            native.lib.harness_set_lr(0x2fffe);native.lib.harness_set_pc(0xd9ee)
            run(0xda58);compare('sequential_entry_preparation',(natural,token),True)
            complete(state,('sequential_key',natural,token))
    for mode in (0xc1,0xc4):
        for polar in (0,1):
            for metadata in (0,1,2):
                for token in (0xf6,0xf7):
                    state=prepare(token=token,mode=mode,natural=0,flags=3,polar=polar,metadata=metadata,
                                  real=bytes.fromhex('01000000000000000006'))
                    complete(state,('382E_regression',mode,polar,metadata,token))
    huge=(C.c_uint8*10)();assert lib.fx_decimal_parse(huge,b'9e99')==0
    for metadata in (0,1,2):
        for polar in (0,1):
            state=prepare(token=0xe5,mode=0xc4,natural=0,flags=1,polar=polar,metadata=metadata,
                          real=bytes(huge),imaginary=bytes(huge))
            complete(state,('editing_E5_admission',polar,metadata),auto_error=True)
    state=prepare(b'1+')
    complete(state,('full_ui_wait_exports',),key=(4,16),
             events_before=((0,0),(1,1),(128,128),(64,128),(32,128)))
    state=prepare(b'1+')
    assert lib.fx_ui_controller_tick(C.byref(p),C.byref(state))==4
    assert lib.fx_ui_controller_tick(C.byref(p),C.byref(state))==0
    run(0x1d8a4);put(0x8e01,16);put(0x8e02,128)
    assert lib.fx_ui_controller_tick(C.byref(p),C.byref(state))==2
    run(0x1824e);compare('full_ui_host_reset_request',0,True)
    out=C.c_uint8(255)
    assert lib.fx_ui_controller_finish(C.byref(state),C.byref(out))==2
    count('host_reset_completion')
    for number in (bytes.fromhex('21a30000000000000301'),
                   bytes.fromhex('80020102000301020101')):
        state=prepare(token=0x30,refresh=1,flags=3,selection=15,real=number)
        actual=lib.fx_ui_controller_tick(C.byref(p),C.byref(state))
        assert actual==5 and state.request==2,('tagged_prime_request',actual,state.request)
        run(0x2fffe)
        gaps.append({'record':number.hex(),'native_return':native.reg(0),'c_status':actual,
                     'request':state.request,'native_format':native.ram[0x8100],
                     'native_ram_sha256':hashlib.sha256(bytes(native.ram)).hexdigest(),
                     'native_lcd_sha256':hashlib.sha256(bytes(native.ram[0xf800:0xfa00])).hexdigest()})
    for mode in (2,0x88,0x89):
        state=prepare(mode=mode)
        assert lib.fx_ui_controller_tick(C.byref(p),C.byref(state))==5 and state.request==1
        count('explicit_special_context_request')
    inactive=Controller()
    for actual in (lib.fx_ui_controller_begin(None,C.byref(inactive),0,None),
                   lib.fx_ui_controller_tick(C.byref(p),C.byref(inactive)),
                   lib.fx_ui_controller_finish(C.byref(inactive),None)):
        assert actual==-1
        count('explicit_invalid_lifecycle')
    report={'cases':sum(counts.values()),'domains':counts,'unsupported_native_fixtures':gaps,
            'lowest_native_stack_pointer':hex(lowest_stack),
            'scope':'TrueD9EE ordinary COMP/CMPLX entry normalization/context preparation, every valid command-table index, typed-key/reset/evaluation/editor-refresh, Ans/replay navigation, prime-factor workspace, nonblocking error/export/reset, finite/continuous cancellation and metadata admission regression transactions. Specialized context and tagged-prime workspace requests remain explicit.',
            'comparison':'Original full-entry return and named context plus remaining64KiB RAM/records/tokens/LCD/MMIO/callbacks. The actual nativeCPU stack extent is measured per fresh fixture and excluded through8DED (retained across sequential keys). Called numeric/layout workspaces8000..80DB/8640..87CF are excluded after action; integral/derivative additionally exclude850A..863F. Fresh entry preparation includes all nonstack RAM. Cancellation counts and sampled persistentX records are compared independently.'}
    if not args.no_report:
        deps=implementation_inputs(ROOT,sources)+['tools/test_input_controller_c.py','tools/test_platform_c.py',
            'tools/test_error_event_c.py','tools/test_key_controller_c.py','tools/test_key_wait_c.py',
            'tools/test_boot_c.py','tools/trace_natural_result.py','tools/verify_firmware.py',
            'tools/nxu8/decoder.py',
            'tools/c_build_inputs.py','tools/c_verification.py',adapter,
            'tools/nxu8/input_controller_events.c']
        report=write_report('analysis/c-verification/ui_controller.json',report,deps,'tools/test_ui_controller_c.py')
    print(json.dumps(report,indent=2))
if __name__=='__main__':main()
