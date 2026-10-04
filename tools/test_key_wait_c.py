#!/usr/bin/env python3
"""Compare nonblocking emulator key waits with original1D802 checkpoints.

The native CPU is only an independent oracle. The new implementation owns
semantic cursor state and does not export or reproduce a CPU stack frame.
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
from trace_natural_result import settings


class Key(C.Structure):
    _fields_ = [('columns', C.c_uint8), ('rows', C.c_uint8)]


class Wait(C.Structure):
    _fields_ = [('shown', C.c_uint8*20), ('hidden', C.c_uint8*20),
                ('framebuffer', C.c_uint16), ('pair_destination', C.c_uint16),
                ('remaining_transitions', C.c_uint16), ('last_idle_counter', C.c_uint16),
                *[(name, C.c_uint8) for name in ('phase', 'cursor_enabled', 'period',
                                               'countdown', 'captured_height', 'active', 'ready')]]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pair-cases', type=int, default=65536)
    parser.add_argument('--random-cases', type=int, default=1200)
    args = parser.parse_args()
    build = ROOT/'analysis/build/key-wait'
    build.mkdir(parents=True, exist_ok=True)
    sources = ['csrc/ui/fx_key_wait.c', 'csrc/ui/fx_cursor.c',
               'csrc/render/fx_render.c', 'csrc/platform/fx_platform.c']
    library = build/'port.so'
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror', '-pedantic',
                    '-shared', '-fPIC', *[str(ROOT/path) for path in sources], '-o', str(library)], check=True)
    lib = C.CDLL(str(library))
    pointer = C.POINTER(Wait)
    lib.fx_key_wait_begin.argtypes = [C.POINTER(Platform), pointer, C.c_uint16]
    lib.fx_key_wait_tick.argtypes = [C.POINTER(Platform), pointer]
    lib.fx_key_wait_finish.argtypes = [C.POINTER(Platform), pointer, C.POINTER(Key)]
    lib.fx_take_callback.argtypes = [C.POINTER(Platform)]
    lib.fx_take_callback.restype = C.c_uint8
    rom = (ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    rom_buffer = (C.c_uint8*len(rom)).from_buffer_copy(rom)
    ram = (C.c_uint8*65536)()
    platform = Platform(rom_buffer, len(rom), ram, 0, 0)
    native = Machine(rom, build/'oracle')
    rng = random.Random(0x1d802)
    background = rng.randbytes(65536)
    counts = {}
    state = Wait()

    def record(group): counts[group] = counts.get(group, 0)+1

    def set_byte(address, value):
        ram[address] = native.ram[address] = value

    def prepare(pair=(0,0), font=6, visible=True, x=17, y=3, character=0x7c,
                destination=0x8300, counter=0xffff):
        nonlocal state
        native.reset()
        C.memmove(ram, background, 65536)
        C.memmove(native.ram, background, 65536)
        settings(native)
        for address in (0x80f9,0x80f5,0x8106,0x8121,0x812c,0x812d): ram[address] = native.ram[address]
        for address,value in [(0x8118,x),(0x8119,y&255),(0x811a,character),
                              (0x811b,font),(0x811f,10),(0x80fe,1 if visible else 0),
                              (0x80dd,0),(0x80fb,0),(0x8e01,pair[0]),(0x8e02,pair[1]),
                              (0x8224,counter&255),(0x8225,counter>>8)]: set_byte(address,value)
        platform.callback_pending = platform.status = 0
        state = Wait()
        native.er(0,destination)
        native.lib.harness_set_sp(0x8dee)
        native.lib.harness_set_lr(0x2fffe)
        native.lib.harness_set_pc(0x1d802)
        return destination

    def run(stop):
        status = native.lib.harness_run(1000000,stop,False)
        assert status == 100, (status,hex(native.lib.harness_get_pc()),hex(stop))

    def compare(group, detail):
        actual, expected = bytes(ram), bytes(native.ram)
        if actual[:0x8d00] != expected[:0x8d00] or actual[0x8dee:] != expected[0x8dee:]:
            differences = [(hex(a),actual[a],expected[a]) for a in range(65536)
                           if not 0x8d00<=a<0x8dee and actual[a] != expected[a]]
            raise AssertionError((group,detail,differences[:30]))
        callback = lib.fx_take_callback(C.byref(platform))
        assert callback == native.lib.harness_callback(), (group,detail,'callback',callback)
        record(group)

    def compare_blink():
        frame = native.er(14)-50
        assert (state.phase,state.cursor_enabled,state.framebuffer,state.period,state.countdown,
                state.remaining_transitions) == (native.ram[frame+40],native.ram[frame+41],
                                                 native.word(frame+42),native.ram[frame+44],
                                                 native.ram[frame+45],native.word(frame+46))

    def begin(destination, detail):
        assert lib.fx_key_wait_begin(C.byref(platform),C.byref(state),destination) == 0
        run(0x1d8a4)
        compare('begin_1D8A4',detail)
        assert state.phase == 0 and state.period == state.countdown == 1
        assert state.remaining_transitions == 1195 and state.active == 1 and state.ready == 0
        assert state.last_idle_counter == 0
        frame = native.er(14)-50
        assert bytes(state.shown[:2*state.captured_height]) == bytes(native.ram[frame:frame+2*state.captured_height])
        assert bytes(state.hidden[:2*state.captured_height]) == bytes(native.ram[frame+20:frame+20+2*state.captured_height])
        compare_blink()
        record('initialized_host_fields')

    def idle_tick(detail):
        assert lib.fx_key_wait_tick(C.byref(platform),C.byref(state)) == 0
        run(0x1d8a6); run(0x1d8d2)
        compare('idle_tick_1D8D2',detail)
        compare_blink()
        assert state.last_idle_counter == ram[0x8224] | ram[0x8225] << 8
        record('idle_counter_and_host_state')

    def ready_tick(detail):
        counter = ram[0x8224] | ram[0x8225] << 8
        assert lib.fx_key_wait_tick(C.byref(platform),C.byref(state)) == 1
        run(0x1d8a6); run(0x1d8b6)
        compare('ready_tick_prefix_1D8B6',detail)
        compare_blink()
        assert ram[0x8224] | ram[0x8225] << 8 == counter
        run(0x1d8d4)
        compare('key_ready_1D8D4',detail)
        initial = bytes(ram)
        assert lib.fx_key_wait_tick(C.byref(platform),C.byref(state)) == 1
        assert bytes(ram) == initial
        record('ready_state_does_not_repeat_tick')

    def finish(detail):
        key = Key()
        assert lib.fx_key_wait_finish(C.byref(platform),C.byref(state),C.byref(key)) == 0
        run(0x2fffe)
        compare('finish_1D900_return',detail)
        assert state.active == state.ready == 0
        # The native return registers are scratch; the semantic key is the
        # raw pair copied in bus order, including deliberately aliased ports.
        return key

    for index in range(args.pair_cases):
        pair = (index&255,(index>>8)&255)
        destination = prepare(pair,visible=False)
        begin(destination,pair)
        if pair == (0,0):
            idle_tick(pair)
            set_byte(0x8e01,1)
        ready_tick(pair)
        key = finish(pair)
        expected = (1,0) if pair == (0,0) else pair
        assert (key.columns,key.rows) == expected
        assert (ram[0x8e01],ram[0x8e02]) == expected
        record('all_raw_host_pairs_retained')

    for index in range(args.random_cases):
        font = rng.choice((6,7,10))
        destination = prepare(font=font,visible=bool(index%2),x=rng.randrange(256),
                              y=rng.randrange(-128,128),character=rng.randrange(256),
                              counter=rng.randrange(65536))
        begin(destination,index)
        for tick in range(index%4): idle_tick((index,tick))
        pair = (rng.randrange(256),rng.randrange(256))
        if pair == (0,0): pair = (1,0)
        set_byte(0x8e01,pair[0]); set_byte(0x8e02,pair[1])
        ready_tick(index); key = finish(index)
        assert (key.columns,key.rows) == pair
        record('cursor_coordinates_fonts_characters')

    # Start visible/suppressed cursors at the callback port, and exercise
    # original copying order for output/host-port and LCD aliases.
    for destination in (0x8000,0x811a,0x811b,0x8300,0x8e00,0x8e01,0x8e02,0xf000,0xf001,0xf832,0xffff,0x7fff):
        for visible in (False,True):
            prepare((3,2),visible=visible,x=0,y=-128,destination=destination)
            begin(destination,(destination,visible)); ready_tick((destination,visible))
            finish((destination,visible)); record('bus_destination_aliases_and_callbacks')

    for font,y,character in ((6,-128,0x7c),(7,-128,1),(7,-127,1),(7,-127,0x7c),(10,-128,0xcc)):
        destination=prepare((1,2),font=font,visible=True,x=0,y=y,character=character)
        begin(destination,('wrapped-glyph-callback',font,y,character))
        ready_tick(('wrapped-glyph-callback',font,y,character))
        finish(('wrapped-glyph-callback',font,y,character))
        record('wrapped_font7_control_callback')

    destination = prepare(visible=True)
    begin(destination,'transition-wrap')
    for tick in range(1200): idle_tick(('transition-wrap',tick))
    assert state.remaining_transitions == 65531
    set_byte(0x8e01,4); set_byte(0x8e02,2)
    ready_tick('transition-wrap'); finish('transition-wrap')
    record('transition_counter_wrap_after_1195_ticks')

    for countdown in (0,1,2,255):
        for period in (0,1,255):
            for phase in (0,1,2,255):
                for remaining in (0,1,1195,65535):
                    destination = prepare((1,2),visible=True)
                    detail=(countdown,period,phase,remaining)
                    begin(destination,detail)
                    frame=native.er(14)-50
                    state.countdown=native.ram[frame+45]=countdown
                    state.period=native.ram[frame+44]=period
                    state.phase=native.ram[frame+40]=phase
                    state.remaining_transitions=remaining
                    native.word(frame+46,remaining)
                    ready_tick(detail);finish(detail)
                    record('prepared_blink_counter_boundaries')

    for height in range(11):
        destination=prepare((1,2),font=10,visible=True)
        begin(destination,('reduced-height',height))
        set_byte(0x811b,height)
        ready_tick(('reduced-height',height));finish(('reduced-height',height))
        record('dynamic_height_reduction')

    # The firmware's unused localbyte30/EE does not become the blink period.
    for busy in range(256):
        destination = prepare((1,2),visible=False)
        set_byte(0x80f4,busy)
        begin(destination,busy); ready_tick(busy); finish(busy)
        assert state.period == 1
        record('all_busy_bytes_leave_period_one')

    prepare((1,2),visible=True)
    begin(0x8300,'unsupported-growth')
    set_byte(0x811b,11)
    before=bytes(ram)
    assert lib.fx_key_wait_tick(C.byref(platform),C.byref(state)) == -2
    assert bytes(ram) == before
    record('uncaptured_height_growth_explicitly_unsupported')
    state.captured_height=255
    assert lib.fx_key_wait_tick(C.byref(platform),C.byref(state)) == -2
    state.ready=1
    assert lib.fx_key_wait_finish(C.byref(platform),C.byref(state),None) == -2
    assert bytes(ram) == before
    record('corrupted_host_capacity_explicitly_unsupported')
    for font in range(256):
        if font in (6,7,10): continue
        prepare((1,2),font=font,visible=True)
        before=bytes(ram)
        assert lib.fx_key_wait_begin(C.byref(platform),C.byref(state),0x8300) == -2
        assert bytes(ram) == before
        record('noncanonical_visible_fonts_explicitly_unsupported')
    state=Wait()
    assert lib.fx_key_wait_tick(C.byref(platform),C.byref(state)) == -1
    assert lib.fx_key_wait_finish(C.byref(platform),C.byref(state),None) == -1
    record('inactive_lifecycle')

    report = write_report('analysis/c-verification/key_wait.json', {
        'cases':sum(counts.values()),'domains':counts,'failures':0,
        'pair_cases':args.pair_cases,'random_cases':args.random_cases,'seed':'0x1d802',
        'input':'identical persistent memory, raw host pairs and semantic wait configuration',
        'output':'complete persistent RAM/MMIO and callback events at native begin, ready-tick prefix, idle/key-ready and finish boundaries; owned host state initialization and idle counter',
        'scope':'original emulator1D802 lifecycle; raw pair domain'+(' exhaustive' if args.pair_cases==65536 else ' sampled')+', mandatory preloaded-key tick, retained host pair, cursor drawing/blink, timer and wrapping counters',
        'limitation':'oracle CPU-call-stack8D00..8DED excluded; native locals are never exported to C memory. Noncanonical visible fonts, uncaptured height growth, destination aliases to native CPU stack, outer1DB34 bridge/menu/reset handling and physical-time scheduling remain outside this API'},
        sources+['csrc/ui/fx_key_wait.h','csrc/ui/fx_cursor.h','csrc/ui/fx_keys.h',
                 'csrc/render/fx_render.h','csrc/platform/fx_platform.h',
                 'tools/test_platform_c.py','tools/trace_natural_result.py','tools/c_verification.py'],
        'tools/test_key_wait_c.py')
    print(json.dumps({key:value for key,value in report.items() if key!='tested_inputs_sha256'},indent=2))


if __name__=='__main__': main()
