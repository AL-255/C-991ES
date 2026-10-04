#!/usr/bin/env python3
"""Original main-loop caller boundaries and full key-wait lifecycles.

Untranslated UI/menu bodies are explicit pending semantic requests. Native
prepared return boundaries verify caller policy without claiming those bodies.
GPL-3.0-only.
"""
import argparse
import ctypes as C
import json
import random
import re
import subprocess
from c_verification import ROOT, write_report
from nxu8.machine import Machine
from test_platform_c import Platform
from test_key_controller_c import Controller
from test_boot_events_c import MODULES as BOOT_MODULES


class Main(C.Structure):
    _fields_ = [('keys',Controller), *[(n,C.c_uint8) for n in
                 ('wait_required','last_menu_result','phase','pending_request','argument','active')]]


SOURCES = ['csrc/'+module+'.c' for module in [*BOOT_MODULES,'platform/fx_persistent','platform/fx_main_loop']]
ENTRY = {1:0xd9ee,2:0xc978,3:0xca7c,4:0xcd66,5:0xf02c,6:0xe22a,
         7:0xecaa,8:0xeca6,9:0xe862,10:0xe1be,11:0xdca4,12:0xef18,13:0xef68}
RETURN = {1:0xd87e,2:0xd98e,3:0xd99e,4:0xd9d6,5:0xd8fe,6:0xd90a,
          7:0xd918,8:0xd926,9:0xd934,10:0xd942,11:0xd950,12:0xd96c,13:0xd97a}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--random-cases',type=int,default=4096)
    args=ap.parse_args();build=ROOT/'analysis/build/main-loop';build.mkdir(parents=True,exist_ok=True)
    library=build/'main.so'
    subprocess.run(['gcc','-std=c99','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',
                    '-Wl,--no-undefined',*[str(ROOT/f) for f in SOURCES],'-o',str(library)],check=True)
    lib=C.CDLL(str(library));pp=C.POINTER(Platform);ss=C.POINTER(Main)
    lib.fx_main_loop_begin.argtypes=[ss]
    lib.fx_main_loop_tick.argtypes=[pp,ss]
    lib.fx_main_loop_accept_token.argtypes=[pp,ss,C.c_uint8]
    lib.fx_main_loop_accept_handler.argtypes=[pp,ss,C.c_uint8]
    lib.fx_main_routes_input.argtypes=[pp];lib.fx_main_routes_input.restype=C.c_uint8
    lib.fx_boot_reset.argtypes=[pp];lib.fx_boot_reset.restype=C.c_int
    lib.fx_take_callback.argtypes=[pp];lib.fx_take_callback.restype=C.c_uint8
    rom=(ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes();rd=(C.c_uint8*len(rom)).from_buffer_copy(rom)
    ram=(C.c_uint8*65536)();p=Platform(rd,len(rom),ram,0,0);m=Machine(rom,build/'oracle')
    rng=random.Random(0xd7b4d9e8);background=bytearray(rng.randbytes(65536));background[0x8dee:0x8e00]=rom[0x1f8dc:0x1f8ee]
    counts={};bounds={}
    def count(group):counts[group]=counts.get(group,0)+1
    def prepare(mode=0xc1,screen=1,flags=1,token=0xe6,menu=0,command=1,item=0,math=1):
        m.reset();C.memmove(m.ram,bytes(background),65536)
        for a,v in [(0x80f9,mode),(0x80fc,screen),(0x80fe,flags),(0x80f5,token),(0x80fb,menu),
                    (0x80f7,command),(0x80fd,item),(0x80f8,0),(0x80f4,0),(0x80dd,0),
                    (0x8102,0),(0x8105,4),(0x8106,math),(0x8112,17),(0x8114,0),
                    (0x8117,1),(0x8118,0),(0x8119,1),(0x811a,0x7c),(0x811b,10),(0x811f,10),
                    (0x8120,0),(0x8121,1),(0x8127,0),(0x8128,0),(0x8129,0),(0x8137,0),
                    (0x8e00,0),(0x8e01,0),(0x8e02,0),(0xf040,255)]:m.ram[a]=v
        for a in (0x8154,0x81b8):
            for n in range(100):m.ram[a+n]=0
        m.ram[0x8154]=0x31;m.ram[0x81b8]=0x32
        for a in (0x8226,0x8408):
            for n in range(10):m.ram[a+n]=0
        C.memmove(ram,m.ram,65536);p.callback_pending=p.status=0
        state=Main();lib.fx_main_loop_begin(C.byref(state));m.reg(4,0);m.reg(5,0)
        m.lib.harness_set_sp(0x8dee);m.lib.harness_set_lr(0x2fffe)
        return state
    def run(entry,stop):
        m.lib.harness_set_pc(entry)
        if entry==stop:assert m.lib.harness_run(1,0x2fffe,False)==103
        assert m.lib.harness_run(3000000,stop,False)==100,(hex(entry),hex(stop),hex(m.lib.harness_get_pc()))
    def equal(group,detail,state=None):
        actual,expected=bytes(ram),bytes(m.ram)
        assert actual[:0x8d00]==expected[:0x8d00] and actual[0x8dee:]==expected[0x8dee:],(
            group,detail,[(hex(a),actual[a],expected[a]) for a in range(65536)
                         if not 0x8d00<=a<0x8dee and actual[a]!=expected[a]][:25])
        assert lib.fx_take_callback(C.byref(p))==m.lib.harness_callback()
        if state is not None:
            assert state.wait_required==m.reg(5),(group,detail,'wait',state.wait_required,m.reg(5))
            assert state.last_menu_result==m.reg(4),(group,detail,'menu',state.last_menu_result,m.reg(4))
        count(group)
    def dispatch(group,fields,token=None,last=0):
        state=prepare(**fields);state.last_menu_result=last;m.reg(4,last)
        if token is None:
            status=lib.fx_main_loop_tick(C.byref(p),C.byref(state));entry=0xd7b4
        else:
            state.wait_required=1;m.reg(5,1);m.reg(0,token)
            status=lib.fx_main_loop_accept_token(C.byref(p),C.byref(state),token);entry=0xd7c2
        assert status in (1,4),(group,fields,token,status)
        stop=ENTRY[state.pending_request] if status==4 else 0xd7b4
        run(entry,stop);equal(group,(fields,token,last),state)
        if status==4:
            before=bytes(ram);assert lib.fx_main_loop_tick(C.byref(p),C.byref(state))==4
            assert bytes(ram)==before
            bounds['pending_request_retained_without_writes']=bounds.get('pending_request_retained_without_writes',0)+1
        return state

    for screen,flags,command in [(1,0,0),(2,1,0),(2,2,0),(2,2,1),(2,0x10,1),
                                  (18,2,1),(0xc0,3,1),(24,0xf3,255)]:
        for token in range(256):
            prepare(screen=screen,flags=flags,command=command,token=token)
            actual=lib.fx_main_routes_input(C.byref(p));m.call(0x1dde4)
            assert actual==m.reg(0),(screen,flags,command,token)
            equal('routing_predicate_all_tokens',(screen,flags,command,token))
    for screen in range(256):
        for mode in [12,0x88,0xc1,0xc4]:
            dispatch('all_screen_routes',dict(mode=mode,screen=screen,flags=2,token=0,command=1))
    for menu in range(256):
        for last in [0,1,127,128,255]:
            dispatch('all_menu_bytes',dict(menu=menu),last=last)
    for token in range(256):
        dispatch('all_returned_tokens',dict(screen=1),token)
    for token in [0xfc,0xfd]:
        for mode in range(256):
            for screen,flags,item in [(1,1,0),(1,0x40,0),(0xc0,4,1),(0xc0,4,2)]:
                dispatch('screen_selection_mode_and_blockers',dict(mode=mode,screen=screen,flags=flags,item=item),token)
    for mode in [12,0x88,0xc1,0xc4]:
        for screen in [2,6,9,18,19,21,23,24,0xa0,0xc0]:
            dispatch('AC_screen_policies',dict(mode=mode,screen=screen,flags=2,command=1),0xe6)
    for length in range(100):
        state=prepare(screen=0xc0,flags=4);state.wait_required=1;m.reg(5,1);m.reg(0,0xfc)
        for n in range(100):ram[0x81b8+n]=m.ram[0x81b8+n]=0x31 if n<length else 0
        assert lib.fx_main_loop_accept_token(C.byref(p),C.byref(state),0xfc)==4
        assert state.pending_request==11
        run(0xd7c2,0xdca4);equal('all_bounded_selector_copy_lengths',length,state)

    for index in range(args.random_cases):
        dispatch('random_dispatch_policies',dict(mode=rng.choice((12,0x88,0xc1,0xc4)),
             screen=rng.randrange(256),flags=rng.randrange(256),token=rng.randrange(256),
             menu=rng.choice((0,0,0,1,2,3,255)),command=rng.randrange(256),item=rng.randrange(256)),
             last=rng.randrange(256))

    for kind in range(1,14):
        for returned in range(256):
            state=prepare(screen=18 if kind==5 else 1,menu=kind-1 if kind in (2,3,4) else 0)
            state.wait_required=1;state.phase=3;state.pending_request=kind
            state.last_menu_result=0x43;m.reg(4,0x43);m.reg(5,1);m.reg(0,returned)
            status=lib.fx_main_loop_accept_handler(C.byref(p),C.byref(state),returned)
            assert status==(4 if kind==5 and returned==0 else 1)
            run(RETURN[kind],ENTRY[6] if status==4 else 0xd7b4)
            equal('all_prepared_handler_return_bytes',(kind,returned),state)
    for mode in [0,12,0xc1,0xc4,255]:
        for flags in [0,1,4,5,0xf3,255]:
            for screen in [1,16,18,24,0x80,0x90,255]:
                state=prepare(mode=mode,screen=screen,flags=flags,menu=2)
                state.wait_required=1;state.phase=3;state.pending_request=3;m.reg(5,1);m.reg(0,1)
                assert lib.fx_main_loop_accept_handler(C.byref(p),C.byref(state),1)==1
                run(0xd99e,0xd7b4);equal('setup_completion_exceptions',(mode,flags,screen),state)

    # Native full outer wait is exercised through the main caller, including
    # ordinary header classification. The host retains its raw pair bytes.
    for token in [0x31,0x2b,0x32,0xe4,0xe6,0xfe]:
        state=prepare();state.wait_required=1;m.reg(5,1)
        assert lib.fx_main_loop_tick(C.byref(p),C.byref(state))==0
        run(0xd7b4,0x1d8a4);equal('full_main_key_wait_begin',token,state)
        pair=None
        for row in range(1,9):
            for column in range(1,9):
                if rom[0x7fe+(column-1)*8+row-1]==token:pair=(1<<(column-1),1<<(row-1))
        assert pair is not None,token
        for a,v in [(0x8e01,pair[0]),(0x8e02,pair[1])]:ram[a]=m.ram[a]=v
        status=lib.fx_main_loop_tick(C.byref(p),C.byref(state))
        stop=ENTRY[state.pending_request] if status==4 else 0xd7b4
        assert status in (1,4),(token,status)
        run(0x1d8a4,stop);equal('full_main_key_to_handler',token,state)

    state=prepare();state.wait_required=1;m.reg(5,1)
    assert lib.fx_main_loop_tick(C.byref(p),C.byref(state))==0
    run(0xd7b4,0x1d8a4)
    normal={rom[0x7fe+c*8+r]:(1<<c,1<<r) for c in range(8) for r in range(8)}
    for raw,stop,status_expected in [(0xe9,0x1d8a4,0),(0xe4,0xca7c,4)]:
        pair=normal[raw]
        for a,v in [(0x8e01,pair[0]),(0x8e02,pair[1])]:ram[a]=m.ram[a]=v
        assert lib.fx_main_loop_tick(C.byref(p),C.byref(state))==status_expected
        run(0x1d8a4,stop);equal('full_SHIFT_SETUP_wait_lifecycle',raw,state if status_expected else None)
        assert state.wait_required==1

    state=prepare();state.wait_required=1;m.reg(5,1)
    assert lib.fx_main_loop_tick(C.byref(p),C.byref(state))==0
    run(0xd7b4,0x1d8a4)
    for index in range(64):
        assert lib.fx_main_loop_tick(C.byref(p),C.byref(state))==0
        # The first poll enters throughD8A4; subsequent polls branch from
        # D8D2. Preserve the native continuation rather than restarting the
        # one-time wait-entry branch on every host tick.
        assert m.lib.harness_run(3000000,0x1d8a6,False)==100
        assert m.lib.harness_run(3000000,0x1d8d2,False)==100
        equal('full_main_idle_host_polls',index)
        assert state.wait_required==1 and state.last_menu_result==0 and not state.pending_request
    for columns in [0x20,0x40,0x80,0x10]:
        state=prepare();state.wait_required=1;m.reg(5,1)
        for a in [0x8230,0x8412]:
            for n,b in enumerate(bytes.fromhex('01000000000000000001')):ram[a+n]=m.ram[a+n]=b
        ram[0x9838]=m.ram[0x9838]=0
        assert lib.fx_main_loop_tick(C.byref(p),C.byref(state))==0
        run(0xd7b4,0x1d8a4)
        ram[0x8e01]=m.ram[0x8e01]=columns;ram[0x8e02]=m.ram[0x8e02]=0x80
        expected_status=2 if columns==0x10 else 3
        assert lib.fx_main_loop_tick(C.byref(p),C.byref(state))==expected_status
        run(0x1d8a4,0x1824e if columns==0x10 else 0x1d8a4)
        equal('full_main_host_export_or_reset',columns)
        assert state.wait_required==1 and state.last_menu_result==0 and not state.pending_request

    # Genuine reset6F82, through ordinary boot and first main UI request.
    # The initial E6 handler remains an actual pending dependency, not a
    # synthetic ready flag. Both cold and retained ordinary modes are used.
    for retained_mode in [None,0xc1,0xc4]:
        for port in [0,3,7]:
            state=prepare(mode=retained_mode or 0xc1)
            m.ram[0xf050]=port
            if retained_mode is not None:
                for n in range(15):m.ram[0x860e+n]=15-n
                for n in range(100):m.ram[0x8226+n]=0
                m.ram[0x80dc]=port
                m.ram[0x8112]=17
            C.memmove(ram,m.ram,65536)
            assert lib.fx_boot_reset(C.byref(p))==0
            lib.fx_main_loop_begin(C.byref(state))
            assert lib.fx_main_loop_tick(C.byref(p),C.byref(state))==4
            assert state.pending_request==1
            run(0x6f82,0xd9ee)
            equal('true_reset_entry_to_initial_UI_request',(retained_mode,port),state)

    saved=bytes(ram)
    assert lib.fx_main_loop_tick(None,C.byref(Main()))==-1
    assert lib.fx_main_loop_tick(C.byref(p),None)==-1
    inactive=Main();assert lib.fx_main_loop_tick(C.byref(p),C.byref(inactive))==-1
    assert lib.fx_main_loop_accept_handler(C.byref(p),C.byref(inactive),1)==-1
    assert bytes(ram)==saved;bounds['invalid_arguments']=4
    lib.fx_main_loop_begin(C.byref(inactive))
    assert lib.fx_main_loop_accept_token(C.byref(p),C.byref(inactive),0x31)==-1
    assert bytes(ram)==saved;bounds['token_without_actual_wait']=1
    headers,pending=set(),[ROOT/f for f in SOURCES]
    while pending:
        source=pending.pop()
        for include in re.findall(r'^\s*#include\s+"([^"]+)"',source.read_text(),re.M):
            dependency=(source.parent/include).resolve();name=str(dependency.relative_to(ROOT))
            if name not in headers:headers.add(name);pending.append(dependency)
    report={'cases':sum(counts.values())+sum(bounds.values()),
            'native_cases':sum(counts.values()),'groups':counts,'bounds_cases':sum(bounds.values()),
            'bounds_groups':bounds,'comparison':'Complete RAM/MMIO, callback and named wait/menu state; only CPU-stack8D00..8DED excluded.',
            'limits':['UI/menu/special-screen requests are pending real dependencies; prepared return fixtures verify caller policy, not subordinate implementations.',
                      'Full reset6F82 to first wait still requires the UI worker actualD9EE bootE6 dispatch; no synthetic readiness or header flags are used.',
                      'High-bit screen exit accepts a terminated exported expression shorter than100 bytes; malformed overflow is explicit unsupported status.',
                      'Physical interrupt/timer scheduling belongs to host input; genericF000 callbacks are not evidence of native5550 timer service.']}
    report=write_report('analysis/c-verification/main_loop.json',report,SOURCES+sorted(headers)+
         ['tools/c_verification.py','tools/test_platform_c.py','tools/test_boot_events_c.py',
          'tools/test_key_controller_c.py','tools/test_key_wait_c.py','tools/test_boot_c.py',
          'tools/test_diagnostic_contrast_c.py'],'tools/test_main_loop_c.py')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
