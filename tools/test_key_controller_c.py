#!/usr/bin/env python3
"""Compare host-owned nonblocking1DB34 key routing with native injected events.

Production C never exports a CPU frame or executes firmware instructions.
Native wait/table/bridge checkpoints are an independent differential oracle.
GPL-3.0-or-later.
"""
import argparse
import ctypes as C
import json
from pathlib import Path
import random
import subprocess

from c_verification import ROOT, write_report
from nxu8.machine import Machine
from test_platform_c import Platform
from test_key_wait_c import Key, Wait
from test_boot_c import HostDescriptor
from trace_natural_result import settings


class Controller(C.Structure):
    _fields_ = [('wait', Wait), ('host', HostDescriptor), ('raw_key', Key),
                *[(name, C.c_uint8) for name in ('token', 'event', 'active', 'export_mask')]]


MODULES = ['ui/fx_key_controller', 'ui/fx_key_wait', 'ui/fx_annunciator',
           'ui/fx_cursor', 'ui/fx_keys', 'ui/fx_key_dispatch', 'ui/fx_editor',
           'ui/fx_natural_editor', 'platform/fx_result_classify', 'platform/fx_platform', 'platform/fx_host_bridge',
           'numeric/fx_numeric', 'complex/fx_complex', 'parse/fx_tokens',
           'render/fx_render', 'render/fx_layout_validate', 'data/fx_rom_data']
SOURCES = ['csrc/'+module+'.c' for module in MODULES]
EXCLUDED = [(0x8d00, 0x8dee)]
PERSISTENT = [(0, 0x8d00), (0x8dee, 65536)]
INSTRUMENTATION = r'''
#include "csrc/platform/fx_platform.h"
#include <string.h>
uint64_t fx_key_controller_test_writes[65536];
void __real_fx_data_write(fx_platform *, uint8_t, uint16_t, uint8_t);
void __wrap_fx_data_write(fx_platform *p, uint8_t s, uint16_t a, uint8_t v)
{
    if (!s && a >= 0x8000) ++fx_key_controller_test_writes[a];
    __real_fx_data_write(p, s, a, v);
}
void fx_key_controller_test_clear_writes(void)
{
    memset(fx_key_controller_test_writes, 0, sizeof(fx_key_controller_test_writes));
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pair-cases', type=int, default=65536)
    parser.add_argument('--random-cases', type=int, default=1200)
    parser.add_argument('--no-report', action='store_true')
    args = parser.parse_args()
    build = ROOT/'analysis/build/key-controller'
    build.mkdir(parents=True, exist_ok=True)
    instrument = build/'bus_instrumentation.c'
    instrument.write_text(INSTRUMENTATION)
    library = build/'controller.so'
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-shared', '-fPIC', '-Wl,--no-undefined', '-I', str(ROOT),
                    *[str(ROOT/path) for path in SOURCES], str(instrument),
                    '-Wl,--wrap=fx_data_write', '-o', str(library)], check=True)
    lib = C.CDLL(str(library))
    ptr = C.POINTER(Controller)
    lib.fx_key_controller_begin.argtypes = [C.POINTER(Platform), ptr]
    lib.fx_key_controller_tick.argtypes = [C.POINTER(Platform), ptr]
    lib.fx_key_controller_finish.argtypes = [ptr, C.POINTER(C.c_uint8)]
    lib.fx_take_callback.argtypes = [C.POINTER(Platform)]
    lib.fx_take_callback.restype = C.c_uint8
    lib.fx_key_wait_begin_host.argtypes = [C.POINTER(Platform), C.POINTER(Wait)]
    lib.fx_key_wait_tick.argtypes = [C.POINTER(Platform), C.POINTER(Wait)]
    lib.fx_key_wait_finish_host.argtypes = [C.POINTER(Platform), C.POINTER(Wait), C.POINTER(Key)]
    c_writes = (C.c_uint64*65536).in_dll(lib, 'fx_key_controller_test_writes')
    rom = (ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    rb = (C.c_uint8*len(rom)).from_buffer_copy(rom)
    ram = (C.c_uint8*65536)()
    p = Platform(rb, len(rom), ram, 0, 0)
    native = Machine(rom, build/'oracle')
    rng = random.Random(0x1db34)
    background = rng.randbytes(65536)
    state = Controller()
    counts = {}
    frame = 0

    def record(group): counts[group] = counts.get(group, 0)+1

    def set_byte(address, value): ram[address] = native.ram[address] = value

    def prepare(pair=(0,0), mode=0xc1, flags=0, font=6, visible=True, header=0,
                x=17, y=3, character=0x7c, math_input=1, suppression=0,
                counter=0xffff, text=b''):
        nonlocal state
        native.reset()
        C.memmove(native.ram, background, 65536)
        settings(native)
        C.memmove(ram, native.ram, 65536)
        for address,value in [(0x80f9,mode),(0x80f8,flags),(0x811b,font),
                              (0x8118,x),(0x8119,y&255),(0x811a,character),
                              (0x80fe,1 if visible else 0),(0x80fb,header),
                              (0x80dd,0),(0x80fc,1),(0x80fd,0),(0x80fa,1),
                              (0x8106,math_input),(0x810c,suppression),(0x8114,1),
                              (0x8137,0),(0x8224,counter&255),(0x8225,counter>>8),
                              (0x8e01,pair[0]),(0x8e02,pair[1])]: set_byte(address,value)
        for base, data in [(0x8154,b'123\0'),(0x8226,bytes(10)),
                           (0x8408,bytes(10)),(0x8230,bytes.fromhex('01000000000000000001')),
                           (0x8412,bytes.fromhex('01000000000000000006')),
                           (0x9838,text+b'\0')]:
            for i,value in enumerate(data): set_byte(base+i,value)
        p.callback_pending = p.status = 0
        lib.fx_key_controller_test_clear_writes()
        state = Controller()
        native.lib.harness_set_sp(0x8dee)
        native.lib.harness_set_lr(0x2fffe)
        native.lib.harness_set_pc(0x1db34)

    def run(stop):
        status = native.lib.harness_run(1000000,stop,False)
        assert status == 100, (status,hex(native.lib.harness_get_pc()),hex(stop))

    def compare(group, detail):
        actual, expected = bytes(ram), bytes(native.ram)
        if any(actual[lo:hi] != expected[lo:hi] for lo,hi in PERSISTENT):
            differences = [(hex(a),actual[a],expected[a]) for a in range(65536)
                           if not any(lo<=a<hi for lo,hi in EXCLUDED) and actual[a]!=expected[a]]
            raise AssertionError((group,detail,differences[:30]))
        assert lib.fx_take_callback(C.byref(p)) == native.lib.harness_callback(), (group,detail,'callback')
        record(group)
        for address in (0x8e00,0x8e01,0x8e02):
            assert c_writes[address] == native.ram_writes[address], (group,detail,'host-write-count',hex(address),c_writes[address],native.ram_writes[address])
        record('host_flag_and_pair_write_counts')

    def compare_wait(group):
        assert (state.wait.phase,state.wait.cursor_enabled,state.wait.framebuffer,
                state.wait.period,state.wait.countdown,state.wait.remaining_transitions) == (
                native.ram[frame+40],native.ram[frame+41],native.word(frame+42),
                native.ram[frame+44],native.ram[frame+45],native.word(frame+46))
        size = 2*state.wait.captured_height
        assert bytes(state.wait.shown[:size]) == bytes(native.ram[frame:frame+size])
        assert bytes(state.wait.hidden[:size]) == bytes(native.ram[frame+20:frame+20+size])
        record(group)

    def begin(detail):
        nonlocal frame
        assert lib.fx_key_controller_begin(C.byref(p),C.byref(state)) == 0
        run(0x1d8a4)
        frame = native.er(14)-50
        compare('begin_1D8A4',detail)
        compare_wait('begin_host_blink_fields')
        assert state.active and not state.event and not state.export_mask
        assert [getattr(state.host,name) for name,_ in HostDescriptor._fields_] == [
            0x8e00,0x8e01,0x8e02,0x8e10,0x9000,0x9800,0x9804,0x9808,0x9834,0x9838]
        record('host_owned_descriptor')

    def tick(detail):
        nonlocal frame
        pair = (ram[0x8e01],ram[0x8e02])
        actual_status = lib.fx_key_controller_tick(C.byref(p),C.byref(state))
        run(0x1d8a6)
        if pair == (0,0):
            run(0x1d8d2)
            expected_status = 0
        else:
            run(0x1db5e)
            assert (state.raw_key.columns,state.raw_key.rows) == pair
            if pair[1] == 0x80 and pair[0] in (0x80,0x40,0x20):
                run(0x1db56);run(0x1d8a4)
                frame = native.er(14)-50
                expected_status = 3
                assert state.export_mask == (1 if pair[0] == 0x20 else 7)
            elif pair == (0x10,0x80):
                run(0x1824e)
                expected_status = 2
                assert state.export_mask == 1
            else:
                run(0x1dc3e)
                mapped = native.reg(0)
                if 0xe8 <= mapped <= 0xec:
                    run(0x1db4c);run(0x1d8a4)
                    frame = native.er(14)-50
                    expected_status = 0
                else:
                    run(0x2fffe)
                    expected_status = 1
                    assert state.token == native.reg(0), (detail,state.token,native.reg(0))
            assert (ram[0x8e01],ram[0x8e02]) == pair
            record('retained_raw_pair')
        assert actual_status == expected_status, (detail,actual_status,expected_status)
        compare('event_'+str(expected_status),detail)
        if state.wait.active:
            compare_wait('event_host_blink_fields')
        else:
            # The native wait locals expire before bridge calls reuse that
            # stack space. Host blink state is retained without modeling the
            # unrelated call-frame clobbering which follows completion.
            assert not state.wait.ready
            record('finished_wait_host_state')
        if expected_status in (1,2):
            initial = bytes(ram)
            assert lib.fx_key_controller_tick(C.byref(p),C.byref(state)) == expected_status
            assert bytes(ram) == initial
            result = C.c_uint8(0xa5)
            assert lib.fx_key_controller_finish(C.byref(state),C.byref(result)) == expected_status
            assert result.value == state.token and not state.active
            assert bytes(ram) == initial
            assert lib.fx_key_controller_tick(C.byref(p),C.byref(state)) == -1
            assert lib.fx_key_controller_finish(C.byref(state),None) == -1
            record('retained_event_and_finish')
        return expected_status

    # All raw byte pairs are tested in a prepared ordinary COMP context.
    for value in range(min(args.pair_cases,65536)):
        prepare(pair=(value&255,value>>8))
        begin(('raw-pair',value));tick(('raw-pair',value))

    # Table selection and modifier consumption are validated in the actual
    # outer wait lifecycle, rather than calling lookup/dispatch independently.
    for mode in (2,0xc1,0xc4):
        for flags in range(16):
            for column in range(8):
                for row in range(7):
                    detail = ('table',mode,flags,column,row)
                    prepare((1<<column,1<<row),mode=mode,flags=flags)
                    begin(detail);tick(detail)

    for i in range(args.random_cases):
        pair = (rng.randrange(256),rng.randrange(256))
        font = rng.choice((6,7,10))
        detail = ('random',i,pair,font)
        prepare(pair,mode=rng.randrange(256),flags=rng.randrange(256),font=font,
                visible=bool(i&1),header=rng.randrange(256),x=rng.randrange(256),
                y=rng.randrange(-128,128),character=rng.randrange(256),
                math_input=i&1,suppression=rng.choice((0,1,255)),counter=rng.randrange(65536),
                text=b'event-'+str(i).encode() if i%3==0 else b'')
        begin(detail);tick(detail)

    # No-key time and subsequent event delivery; export and modifier retries
    # intentionally leave the raw bytes intact until the host clears them.
    retry_pairs = [((0x80,0x80),0),((0x40,0x80),0),((0x20,0x80),0),
                   ((8,1),0),((0x80,1),0),((0x80,2),0),((8,1),8),((4,8),8)]
    for pair,flags in retry_pairs:
        prepare(flags=flags);begin(('retry',pair,flags))
        for idle in range(3): assert tick(('idle',pair,idle)) == 0
        set_byte(0x8e01,pair[0]);set_byte(0x8e02,pair[1])
        event = tick(('retry',pair))
        if event in (0,3):
            set_byte(0x8e01,0);set_byte(0x8e02,0)
            for idle in range(3): assert tick(('after-retry-idle',pair,idle)) == 0
            set_byte(0x8e01,1);set_byte(0x8e02,1)
            tick(('after-retry-token',pair))

    for pair in ((0x80,0x80),(0x40,0x80),(0x20,0x80)):
        prepare(pair);begin(('repeated-export',pair))
        assert tick(('repeated-export',pair,0)) == 3
        assert tick(('repeated-export',pair,1)) == 3

    records = [bytes.fromhex(record) for record in (
        '00000000000000000000','01000000000000000001',
        '01000000000000000006','21a30000000000000301',
        '80020102000301020101','f3000000000000000000')]
    for mode in (0xc1,0xc4):
        for real in records:
            for imaginary in records:
                for pair in ((0x80,0x80),(0x40,0x80),(0x20,0x80)):
                    detail = ('numeric-export',mode,real.hex(),imaginary.hex(),pair)
                    prepare(pair,mode=mode,text=b'export-before-clear')
                    for address,data in ((0x8230,real),(0x8412,imaginary)):
                        for i,value in enumerate(data): set_byte(address+i,value)
                    begin(detail);assert tick(detail) == 3

    prepare((0x10,0x80),text=b'reset-clears-text')
    begin('prepared-reset-request');assert tick('prepared-reset-request') == 2

    # The host-output finish variant makes no data-bus destination stores.
    # Even an otherwise dangerous prepared destination is ignored.
    prepare((0x11,0x22))
    local_wait = Wait();key = Key()
    assert lib.fx_key_wait_begin_host(C.byref(p),C.byref(local_wait)) == 0
    assert lib.fx_key_wait_tick(C.byref(p),C.byref(local_wait)) == 1
    local_wait.pair_destination = 0x811a
    before = bytes(ram[0x811a:0x811c])
    assert lib.fx_key_wait_finish_host(C.byref(p),C.byref(local_wait),C.byref(key)) == 0
    assert bytes(ram[0x811a:0x811c]) == before
    assert (key.columns,key.rows) == (0x11,0x22)
    assert (ram[0x8e01],ram[0x8e02]) == (0x11,0x22)
    record('host_finish_ignores_ram_destination')

    # Invalid/inactive public state and unsupported cursor domains are bounded.
    assert lib.fx_key_controller_begin(None,C.byref(state)) == -1
    assert lib.fx_key_controller_begin(C.byref(p),None) == -1
    assert lib.fx_key_controller_tick(C.byref(p),None) == -1
    assert lib.fx_key_controller_finish(None,None) == -1
    record('invalid_public_arguments')
    for font in (0,1,5,8,9,11,255):
        prepare(font=font);assert lib.fx_key_controller_begin(C.byref(p),C.byref(state)) == -2
        record('unsupported_visible_cursor_font')

    report = {'cases':sum(counts.values()),'domains':counts,'failures':0,
              'pair_cases':min(args.pair_cases,65536),'random_cases':args.random_cases,
              'seed':0x1db34,'scope':'nonblocking native1DB34 through token return, host export retry, modifier retry, or prepared1824E reset request; header3D62 and host-owned1D802 state',
              'input':'prepared original emulator RAM; all raw key pairs, modifier/context table one-hot keys and timed event injection',
              'output':'full persistent RAM/LCD/MMIO, callback, token/event, descriptor and blink fields, exact8E00/01/02 CPU-store counts; no synthetic native locals',
              'limitation':'native CPU stack8D00..8DED excluded; complete classifier RAM/MMIO is compared. Physical wall-clock scheduling, reset execution, menus and outer input/evaluator controllers remain separate. Malformed strings/records, cursor height growth and CPU-local aliases are bounded explicit gaps.'}
    if not args.no_report:
        headers = [path[:-2]+'.h' for path in SOURCES if (ROOT/(path[:-2]+'.h')).exists()]
        write_report('analysis/c-verification/key_controller.json',report,
                     SOURCES+headers+['tools/test_key_wait_c.py','tools/test_boot_c.py',
                     'tools/test_platform_c.py','tools/trace_natural_result.py','tools/c_verification.py'],
                     'tools/test_key_controller_c.py')
    print(json.dumps({'cases':report['cases'],'failures':0,'domains':counts},indent=2))


if __name__ == '__main__': main()
