#!/usr/bin/env python3
"""Compare4074 error painting and3FBA four-line dialogs with the original ROM.

Every persistent RAM/LCD/MMIO byte and bus write is observable; only original
CPU-call-stack memory is excluded. No CPU frame exists in C. GPL-3.0-or-later.
"""
import argparse
import ctypes as C
import json
import random
import subprocess

from c_verification import ROOT, write_report
from nxu8.machine import Machine
from test_platform_c import Platform


SOURCES = ['csrc/ui/fx_error_display.c', 'csrc/render/fx_render.c',
           'csrc/platform/fx_platform.c']
BUS_INSTRUMENTATION = r'''
#include "csrc/platform/fx_platform.h"
#include <string.h>
uint64_t test_writes[65536];
uint16_t test_addresses[2048];
uint8_t test_values[2048];
unsigned test_event_count;
void __real_fx_data_write(fx_platform *, uint8_t, uint16_t, uint8_t);
void __wrap_fx_data_write(fx_platform *p, uint8_t s, uint16_t a, uint8_t v)
{
    if (!s && a >= 0x8000) {
        ++test_writes[a];
        if (test_event_count < 2048) {
            test_addresses[test_event_count] = a;
            test_values[test_event_count] = v;
        }
        ++test_event_count;
    }
    __real_fx_data_write(p, s, a, v);
}
void test_reset(void)
{
    memset(test_writes, 0, sizeof(test_writes));
    test_event_count = 0;
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--random-cases', type=int, default=1024)
    args = parser.parse_args()
    build = ROOT/'analysis/build/error-display'
    build.mkdir(parents=True, exist_ok=True)
    instrumentation = build/'bus_instrumentation.c'
    instrumentation.write_text(BUS_INSTRUMENTATION)
    library = build/'error-display.so'
    subprocess.run(['gcc','-std=c99','-O2','-Wall','-Wextra','-Werror','-pedantic',
                    '-shared','-fPIC','-I',str(ROOT), *[str(ROOT/path) for path in SOURCES],
                    str(instrumentation),'-Wl,--wrap=fx_data_write','-o',str(library)], check=True)
    lib = C.CDLL(str(library))
    lib.fx_error_display.argtypes = [C.POINTER(Platform), C.c_uint8]
    lib.fx_error_display.restype = C.c_int
    lib.fx_error_dialog_draw.argtypes = [C.POINTER(Platform), C.POINTER(C.c_uint16)]
    lib.fx_error_dialog_draw.restype = C.c_int
    lib.fx_take_callback.argtypes = [C.POINTER(Platform)]
    lib.fx_take_callback.restype = C.c_uint8
    lib.fx_data_write.argtypes = [C.POINTER(Platform), C.c_uint8, C.c_uint16, C.c_uint8]
    writes = (C.c_uint64*65536).in_dll(lib,'test_writes')
    addresses = (C.c_uint16*2048).in_dll(lib,'test_addresses')
    values = (C.c_uint8*2048).in_dll(lib,'test_values')
    event_count = C.c_uint.in_dll(lib,'test_event_count')
    rom = (ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    rom_buffer = (C.c_uint8*len(rom)).from_buffer_copy(rom)
    ram = (C.c_uint8*65536)()
    platform = Platform(rom_buffer,len(rom),ram,0,0)
    native = Machine(rom,build/'oracle')
    native.lib.memorySetData.argtypes = [C.c_uint8,C.c_uint16,C.c_size_t,C.c_uint64]
    rng = random.Random(0x4074)
    backgrounds = [rng.randbytes(65536),bytes(65536),bytes([255])*65536]
    counts, unsupported_errors = {}, []
    lines = (C.c_uint16*4)()
    persistent = ((0,0x8d00),(0x8dee,65536))

    def record(group): counts[group] = counts.get(group,0)+1

    def prepare(mode=0, context=0, pending=0, background=0):
        native.reset()
        C.memmove(native.ram,backgrounds[background],65536)
        for address,value in ((0x811f,rng.randrange(256)),(0x8120,mode),
                              (0x8121,rng.randrange(256)),(0x80fc,context),
                              (0xf031,rng.randrange(256))): native.ram[address] = value
        # Vary every initial LCD pixel/padding byte and RAM pixel, independently.
        for address,length in ((0xf800,512),(0x87d0,384)):
            block = rng.randbytes(length)
            for offset,value in enumerate(block): native.ram[address+offset] = value
        C.memmove(ram,native.ram,65536)
        platform.callback_pending = platform.status = 0
        if pending:
            lib.fx_data_write(C.byref(platform),0,0xf000,pending)
            native.lib.memorySetData(0,0xf000,1,pending)
            native.ram_writes[0xf000] = 0
        lib.test_reset()

    def compare(group, detail, before, trace_path=None):
        actual,expected = bytes(ram),bytes(native.ram)
        actual_writes,expected_writes = bytes(writes),bytes(native.ram_writes)
        for start,end in persistent:
            if actual[start:end] != expected[start:end]:
                differences=[(hex(a),actual[a],expected[a]) for a in range(start,end)
                             if actual[a] != expected[a]]
                raise AssertionError((group,detail,'memory',differences[:20]))
            if actual_writes[8*start:8*end] != expected_writes[8*start:8*end]:
                differences=[(hex(a),writes[a],native.ram_writes[a]) for a in range(start,end)
                             if writes[a] != native.ram_writes[a]]
                raise AssertionError((group,detail,'bus write counts',differences[:20]))
        assert actual[0x87d0:0x8950] == before[0x87d0:0x8950], (group,detail,'RAM framebuffer')
        assert actual[0x811f] == 7 and actual[0x8121] == 1 and actual[0xf031] == 5
        assert actual[0x8120] == before[0x8120]
        assert writes[0xf031] == 2, 'unconditional54E6 sleep, then display active'
        for row in range(32):
            assert actual[0xf80c+16*row:0xf810+16*row] == bytes(4), 'LCD padding cleared'
        assert lib.fx_take_callback(C.byref(platform)) == native.lib.harness_callback()
        assert platform.status == 0
        if trace_path:
            expected_events=[]
            for line in trace_path.read_text().splitlines():
                fields=line.split(',')
                if fields[0] != 'W': continue
                segment,address=int(fields[3],16),int(fields[4],16)
                size,value=int(fields[5]),int(fields[6],16)
                for offset in range(size):
                    destination=(address+offset)&65535
                    if segment == 0 and destination >= 0x8000 and not 0x8d00<=destination<0x8dee:
                        expected_events.append((destination,(value>>(8*offset))&255))
            assert event_count.value <= 2048
            actual_events=[(addresses[i],values[i]) for i in range(event_count.value)]
            assert actual_events == expected_events, (group,detail,'ordered bus writes')
            record('ordered_native_bus_writes')
        record(group)

    def check(error,group,mode=0,context=0,pending=0,background=0,trace=False):
        prepare(mode,context,pending,background)
        before=bytes(ram)
        status=lib.fx_error_display(C.byref(platform),error)
        if status:
            assert status == -2 and bytes(ram) == before
            assert not any(writes)
            unsupported_errors.append(error)
            record('CPU_stack_source_alias_explicitly_rejected')
            return
        assert status == 0
        native.reg(0,error)
        trace_path=build/'native-writes.csv' if trace else None
        if trace_path: native.trace_open(trace_path,reads=False)
        try: native.call(0x4074)
        finally:
            if trace_path: native.trace_close()
        compare(group,(error,mode,context,pending,background),before,trace_path)
        assert writes[0x811f] == 2

    def check_dialog(pointers,group,mode=0,context=0,text=None,trace=False):
        prepare(mode,context)
        for index,pointer in enumerate(pointers): lines[index]=pointer
        if text is not None:
            for pointer,data in zip(pointers,text):
                for offset,value in enumerate(data):
                    address=(pointer+offset)&65535
                    ram[address]=native.ram[address]=value
        before=bytes(ram);descriptor=bytes(lines)
        assert lib.fx_error_dialog_draw(C.byref(platform),lines) == 0
        # Native3FBA owns four pointers: two arguments and two supplied stack
        # arguments. Only the independent oracle has a CPU-call frame.
        native.er(0,pointers[0]);native.er(2,pointers[1])
        native.word(0x8dee,pointers[2]);native.word(0x8df0,pointers[3])
        trace_path=build/'native-writes.csv' if trace else None
        if trace_path: native.trace_open(trace_path,reads=False)
        try: native.call(0x3fba)
        finally:
            if trace_path: native.trace_close()
        # Supplied oracle call arguments are not persistent application state.
        for address in range(0x8dee,0x8df2):native.ram[address]=before[address]
        compare(group,(pointers,mode,context),before,trace_path)
        assert bytes(lines) == descriptor and writes[0x811f] == 1

    for error in range(256): check(error,'all_error_byte_indices',mode=error,context=error,trace=error in (0,1,6,13,14,127,128,255))
    for error in range(1,14):
        for mode in range(256): check(error,'defined_errors_all_composite_modes',mode,mode,mode,mode%3)
    for index in range(args.random_cases):
        check(rng.randrange(256),'random_framebuffer_and_context',rng.randrange(256),
              rng.randrange(256),rng.randrange(256),index%3)

    # Each byte glyph in every row, including font7 control glyphs with their
    # extra leading row. Sources are persistent RAM, and text is capped at16.
    pointers=[0x8300,0x8340,0x8380,0x83c0]
    for character in range(1,256):
        data=bytes([character])*16 + b'\x00'
        check_dialog(pointers,'all_byte_glyphs_and_four_rows',character,character,[data]*4,trace=character in (1,31,32,124,255))
        for pointer in pointers: assert bytes(ram[pointer:pointer+17]) == data
    for length in (0,1,15,16,17,32):
        data=bytes([ord('A')])*length+b'\x00'
        check_dialog(pointers,'text_length_truncation',0,0,[data]*4,trace=True)
        for pointer in pointers: assert bytes(ram[pointer:pointer+len(data)]) == data
    for pointer in (0xffff,0xfff8,0x7fff,0x8000,0x8df2,0xf800,0xf9f8,0x811f,0x8120,0x8121):
        check_dialog([pointer]*4,'live_bus_source_pointer_edges',trace=True)

    # Source validation is explicit and atomic. Unmapped low ROM, missing
    # font masks, and original CPU-stack aliases have no invented CPU outcome.
    prepare();before=bytes(ram)
    for pointer in (0x8cf1,0x8d00,0x8ded,0x8dee,0x8df1):
        rejected=(C.c_uint16*4)(pointer,0x11a1,0x1292,0x1158)
        assert lib.fx_error_dialog_draw(C.byref(platform),rejected) == -2
        assert bytes(ram) == before and not any(writes)
        record('CPU_stack_source_span_rejected')
    short_rom=Platform(rom_buffer,0x2ac4,ram,0x37,0)
    unmapped=(C.c_uint16*4)(0x7000,0x11a1,0x1292,0x1158)
    assert lib.fx_error_dialog_draw(C.byref(short_rom),unmapped) == -2
    assert bytes(ram) == before and short_rom.callback_pending == 0x37
    record('unmapped_source_span_rejected')
    for invalid in (None,C.byref(Platform(rom_buffer,len(rom),None,0,0)),
                    C.byref(Platform(None,len(rom),ram,0,0)),
                    C.byref(Platform(rom_buffer,0x2ac3,ram,0,0))):
        assert lib.fx_error_display(invalid,1) == -1
        assert lib.fx_error_dialog_draw(invalid,lines) == -1
        assert bytes(ram) == before and not any(writes)
        record('invalid_platform_without_writes')
    assert lib.fx_error_dialog_draw(C.byref(platform),None) == -1
    record('invalid_descriptor_without_writes')
    assert bytes(rom_buffer) == rom

    report=write_report('analysis/c-verification/error_display.json',{
        'cases':sum(counts.values()),'domains':counts,'failures':0,
        'random_cases':args.random_cases,'seed':'0x4074',
        'input':'identical complete memory, all256error byte indices, defined errors1..13, arbitrary compositor/context/settings bytes, four immutable host line pointers, raw ROM/RAM text and existing callbacks',
        'output':'complete persistent RAM/LCD/MMIO, every per-address bus-write count and selected ordered native traces; complete512byteLCDclear including row padding; retainedRAMframebuffer, source text/descriptor and callbacks',
        'scope':'4074error painter and3FBAfour-line small-font dialog at(0,1),(0,9),(0,17),(0,25); fixed16charwidth, unconditional54E6sleep, live data-bus source reads, ending8121=1/F031=5',
        'unsupported_error_bytes':sorted(set(unsupported_errors)),
        'limitation':'native CPU-call-stack8D00..8DED excluded and stack-source aliases explicitly rejected;3FBAoracle supplied arguments8DEE..8DF1 restored before comparison and their source aliases rejected; unmapped source spans/missing font data rejected before drawing; physical LCD timing and error event/key lifecycle remain separate; no full firmware completion claim'},
        [*SOURCES,'csrc/ui/fx_error_display.h','csrc/render/fx_render.h',
         'csrc/platform/fx_platform.h','tools/test_platform_c.py','tools/c_verification.py'],
        'tools/test_error_display_c.py')
    print(json.dumps({key:value for key,value in report.items() if key!='tested_inputs_sha256'},indent=2))


if __name__=='__main__':main()
