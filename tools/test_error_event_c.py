#!/usr/bin/env python3
"""Native error host text, resumable key admission and cursor restore parity."""
import argparse
import ctypes as C
import json
import random
import subprocess

from c_verification import ROOT, write_report
from nxu8.machine import Machine
from test_platform_c import Platform
from test_key_controller_c import Controller
from trace_natural_result import settings


class ErrorContext(C.Structure):
    _fields_ = [('display_address',C.c_uint16),('calculation_mode',C.c_uint8)]


class ErrorEvent(C.Structure):
    _fields_ = [('key',Controller), *[(n,C.c_uint8) for n in ('error','token','event','active')]]


MODULES = ['ui/fx_error_event','ui/fx_error_display','ui/fx_key_controller',
           'ui/fx_key_wait','ui/fx_annunciator','ui/fx_cursor','ui/fx_keys',
           'ui/fx_key_dispatch','ui/fx_editor','ui/fx_natural_editor',
           'platform/fx_result_classify', 'platform/fx_platform','platform/fx_host_bridge','platform/fx_boot',
           'numeric/fx_numeric','numeric/fx_surd_components','numeric/fx_raw_decimal_parts','numeric/fx_raw_decimal_divide','numeric/fx_raw_decimal_multiply_add','complex/fx_complex','parse/fx_tokens',
           'format/fx_format','format/fx_format_base','render/fx_render',
           'render/fx_render_context','render/fx_render_memory',
           'render/fx_layout_validate','render/fx_result_special', 'render/fx_result_verify',
           'render/fx_result_format_state','data/fx_rom_data']
SOURCES = ['csrc/'+module+'.c' for module in MODULES]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--random-cases',type=int,default=4000)
    ap.add_argument('--no-report',action='store_true')
    args = ap.parse_args()
    build = ROOT/'analysis/build/error-event'
    build.mkdir(parents=True,exist_ok=True)
    library = build/'error.so'
    subprocess.run(['gcc','-std=c99','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',
                    '-Wl,--no-undefined',*[str(ROOT/f) for f in SOURCES],'-o',str(library)],check=True)
    lib = C.CDLL(str(library))
    pp = C.POINTER(Platform)
    lib.fx_error_write_host_text.argtypes = [pp,C.c_uint16]
    lib.fx_error_accepts_token.argtypes = [pp,C.c_uint8]
    lib.fx_error_cursor_restore.argtypes = [pp,C.POINTER(ErrorContext)]
    lib.fx_error_result_cursor.argtypes = [pp]
    lib.fx_error_event_begin.argtypes = [pp,C.POINTER(ErrorEvent),C.c_uint8]
    lib.fx_error_event_tick.argtypes = [pp,C.POINTER(ErrorEvent)]
    lib.fx_error_event_finish.argtypes = [C.POINTER(ErrorEvent),C.POINTER(C.c_uint8)]
    rom = (ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    rb = (C.c_uint8*len(rom)).from_buffer_copy(rom)
    ram = (C.c_uint8*65536)()
    p = Platform(rb,len(rom),ram,0,0)
    native = Machine(rom,build/'oracle')
    rng = random.Random(0xe47e)
    background = bytearray(rng.randbytes(65536))
    background[0x8dee:0x8e00] = rom[0x1f8dc:0x1f8ee]
    counts = {}

    def record(group): counts[group] = counts.get(group,0)+1
    def put(a,v): ram[a] = native.ram[a] = v
    def word(a,v): put(a,v&255);put(a+1,v>>8)
    def string(a,v):
        for i,b in enumerate(v+b'\0\0'):put(a+i,b)

    def prepare(mode=0xc1,screen=1,item=0,flags=0x80,token=0xe2,command=1,natural=1,
                expression=b'1+2',backup=b'4+5',cursor=1,busy=0,selection=0,cache=0):
        native.reset();C.memmove(native.ram,bytes(background),65536);settings(native)
        C.memmove(ram,native.ram,65536)
        for a,v in ((0x80f9,mode),(0x80fc,screen),(0x80fd,item),(0x80fe,flags),
                    (0x80f5,token),(0x80f7,command),(0x8106,natural),(0x8114,cursor),
                    (0x8102,0),(0x8103,0),(0x8104,1),(0x8107,0),(0x810c,0),
                    (0x80f4,busy),(0x8100,selection),(0x8130,cache),(0x80fb,0),
                    (0x80f8,0),(0x80fa,1),(0x8137,0),(0x811b,7),(0x811f,7),
                    (0x8118,17),(0x8119,3),(0x811a,0x7c),(0x80dd,0),
                    (0x8120,0),(0x8121,1),(0x8e01,0),(0x8e02,0)):
            put(a,v)
        word(0x812c,0x8154)
        string(0x8154,expression);string(0x81b8,backup)
        string(0x9838,b'old host text')
        for a in (0x8226,0x8408):
            for i in range(10):put(a+i,0)
        p.callback_pending = p.status = 0

    def compare(group,detail,extended_stack=False,numeric=False):
        excludes = [(0x8c00 if extended_stack else 0x8d00,0x8dee)]
        if numeric: excludes += [(0x8000,0x80dc)]
        actual,expected = bytes(ram),bytes(native.ram)
        spans = [(0,0x8c00 if extended_stack else 0x8d00),(0x8dee,65536)]
        if numeric: spans[0:1] = [(0,0x8000),(0x80dc,spans[0][1])]
        if any(actual[lo:hi]!=expected[lo:hi] for lo,hi in spans):
            mismatch = [(hex(a),actual[a],expected[a]) for a in range(65536)
                        if actual[a]!=expected[a] and not any(lo<=a<hi for lo,hi in excludes)]
            raise AssertionError((group,detail,mismatch[:30]))
        assert p.callback_pending == native.lib.harness_callback(),(group,detail,'callback')
        p.callback_pending = 0
        record(group)

    for error in list(range(256))+[0x100,0x101,0x7fff,0x8000,0xffff]:
        prepare()
        assert lib.fx_error_write_host_text(C.byref(p),error)==0
        native.er(0,error);native.call(0x1dfd6)
        compare('host_error_mapping',error,extended_stack=True)
    for command in (0,1,255):
        for token in range(256):
            prepare(command=command)
            a = lib.fx_error_accepts_token(C.byref(p),token)
            native.reg(0,token);native.call(0x41a8)
            assert a == native.reg(0),(command,token,a,native.reg(0))
            compare('all_token_admission',(command,token))

    def restore_case(detail,context_mode=None,**kw):
        prepare(**kw)
        context_mode = kw.get('mode',0xc1) if context_mode is None else context_mode
        context = ErrorContext(0x8154,context_mode)
        actual = lib.fx_error_cursor_restore(C.byref(p),C.byref(context))
        # The independent oracle alone builds the native12-byte call context.
        native.word(0x8d00,0x8154);native.ram[0x8d06] = context_mode
        native.er(0,0x8d00);native.call(0x1ec72)
        assert actual == native.reg(0),(detail,actual,native.reg(0))
        compare('cursor_restore',detail,numeric=True)

    for flags in range(256):
        for screen,item in ((1,0),(6,0),(6,1),(6,4),(0x81,2),(0x81,3),(0x10,0),(9,0)):
            for token in (0xe2,0xe3,0xe6):
                restore_case((flags,screen,item,token),flags=flags,screen=screen,item=item,
                             token=token,expression=b'' if flags%2 else b'1+2')
    for mode in range(256):
        for flags in (0,1,3,5,0x80):
            for token in (0xe2,0xe3):
                restore_case((mode,flags,token),mode=mode,flags=flags,token=token,
                             expression=b'',context_mode=mode)
    for case in range(args.random_cases):
        restore_case(case,mode=rng.choice([0xc1,0xc4,2,0x88,0x89,0x45,0x4b,12]),
                     flags=rng.randrange(256),screen=rng.choice([1,6,0x81,0x10]),item=rng.randrange(5),
                     token=rng.choice([0xe2,0xe3,0xe6,0xf0]),command=rng.randrange(2),
                     cursor=rng.randrange(256),busy=rng.randrange(256),natural=rng.randrange(2),
                     expression=rng.choice([b'',b'123',b'\x98\xb82\xb9']))

    for flags in range(256):
        for natural in (0,1):
            for selection in (0,14,15):
                for token in (0xe2,0xe3):
                    prepare(flags=flags,natural=natural,selection=selection,cache=1,
                            token=token,cursor=flags,busy=flags)
                    actual = lib.fx_error_result_cursor(C.byref(p));native.call(0x1ed16)
                    assert actual == native.reg(0),(flags,natural,selection,token,actual,native.reg(0))
                    compare('cached_result_cursor',(flags,natural,selection,token))

    def run(stop):
        result = native.lib.harness_run(2000000,stop,False)
        assert result==100,(result,hex(native.lib.harness_get_pc()),hex(stop))

    def begin(error,command=1,pair=(0,0)):
        prepare(command=command,flags=0x80)
        put(0x8e01,pair[0]);put(0x8e02,pair[1])
        state = ErrorEvent()
        assert lib.fx_error_event_begin(C.byref(p),C.byref(state),error)==0
        native.lib.harness_set_sp(0x8dee);native.lib.harness_set_lr(0x2fffe)
        native.reg(0,error);native.lib.harness_set_pc(0x1e47e)
        run(0x1d8a4)
        compare('event_begin',(error,command),extended_stack=True,numeric=True)
        return state

    def tick(state,pair,detail):
        put(0x8e01,pair[0]);put(0x8e02,pair[1])
        actual = lib.fx_error_event_tick(C.byref(p),C.byref(state))
        run(0x1d8a6)
        if pair==(0,0):
            run(0x1d8d2);expected=0
        else:
            run(0x1db5e)
            if pair[1]==0x80 and pair[0] in (0x80,0x40,0x20):
                run(0x1db56);run(0x1d8a4);expected=3
            elif pair==(0x10,0x80):
                run(0x1824e);expected=2
            else:
                run(0x1dc3e);token=native.reg(0)
                if 0xe8<=token<=0xec:
                    run(0x1db4c);run(0x1d8a4);expected=0
                else:
                    run(0x1e498)
                    if token==0xe6 or (native.ram[0x80f7] and token in (0xe2,0xe3)):
                        run(0x2fffe);expected=1
                        assert state.token==native.reg(0)
                    else:
                        run(0x1d8a4);expected=0
        assert actual==expected,(detail,pair,actual,expected)
        compare('event_tick_'+str(expected),detail,extended_stack=True,numeric=True)
        assert (ram[0x8e01],ram[0x8e02])==pair
        record('event_retained_raw_pair')
        if expected in (1,2):
            before=bytes(ram)
            assert lib.fx_error_event_tick(C.byref(p),C.byref(state))==expected
            out=C.c_uint8()
            assert lib.fx_error_event_finish(C.byref(state),C.byref(out))==expected
            assert not state.active and out.value==state.token and bytes(ram)==before
            record('retained_terminal_event')
        return expected

    for error in range(1,14):
        for command in (0,1):
            state=begin(error,command)
            # 1,+ and a modifier are ignored before the acceptedAC event.
            for pair in ((0,0),(1,1),(1,8),(2,0x40),(0,0),(4,0x10)):
                if tick(state,pair,(error,command)) in (1,2):break
    for column in (0x80,0x40,0x20,0x10):
        state=begin(2)
        tick(state,(column,0x80),('host',column))
    for error in range(14,256):
        state=begin(error,pair=(4,0x10))
        tick(state,(4,0x10),('preloaded_error_byte',error))
    # All one-hot nativekeymap combinations prove admission and retry behavior.
    for command in (0,1):
        for col in (1,2,4,8,16,32,64,128):
            for row in (1,2,4,8,16,32,64,128):
                state=begin(2,command)
                tick(state,(col,row),('onehot',command,col,row))
    for fn in ('fx_error_event_begin','fx_error_event_tick','fx_error_cursor_restore'):
        if fn=='fx_error_event_begin': result=getattr(lib,fn)(C.byref(p),None,2)
        else:result=getattr(lib,fn)(C.byref(p),None)
        assert result==-1
        record('null_context_guard')
    report={'cases':sum(counts.values()),'domains':counts,
            'comparison':'OriginalDFD6/41A8/EC72/ED16 and injectedE47E wait/header/bridge/admission checkpoints; full persistentRAM,LCD,MMIO and callbacks. CPU stack8D00..8DED (8C00..8DED forDFD6/E47E) and only native numeric workspace8000..80DB where called are excluded.',
            'scope':'Error host strings, alltoken admission, cursor/error restore branches, cached-resultcursor, begin/idle/ignored-key/modifier/export/reset/accepted-key lifecycle and rawpair retention. Resetexecution/evaluator/fullhandler are separate.'}
    if not args.no_report:
        deps=SOURCES+[f for f in [s[:-2]+'.h' for s in SOURCES] if (ROOT/f).exists()]
        deps += ['tools/test_platform_c.py','tools/test_boot_c.py','tools/test_key_wait_c.py',
                 'tools/test_key_controller_c.py','tools/trace_natural_result.py','tools/c_verification.py',
                 'csrc/format/fx_format_base.h','csrc/render/fx_layout_validate.h']
        report=write_report('analysis/c-verification/error_event.json',report,deps,'tools/test_error_event_c.py')
    print(json.dumps({k:v for k,v in report.items() if k!='tested_inputs_sha256'},indent=2))


if __name__=='__main__':main()
