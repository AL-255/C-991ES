#!/usr/bin/env python3
"""Differential high-level startup/peripheral tests against the original ROM."""
import ctypes as C
import hashlib
import json
from pathlib import Path
import random
import subprocess

from nxu8.machine import Machine
from c_verification import write_report

ROOT=Path(__file__).resolve().parents[1]
BUILD=ROOT/'analysis/build/platform'
OUT=ROOT/'analysis/c-verification'


class Platform(C.Structure):
    _fields_=[('rom',C.POINTER(C.c_uint8)),('rom_size',C.c_size_t),
              ('ram',C.POINTER(C.c_uint8)),('callback_pending',C.c_uint8),('status',C.c_int)]


def main():
    BUILD.mkdir(parents=True,exist_ok=True);OUT.mkdir(parents=True,exist_ok=True)
    library=BUILD/'fx_platform.so'
    subprocess.run(['gcc','-std=c99','-O2','-Wall','-Wextra','-Werror','-fPIC','-shared',
                    str(ROOT/'csrc/platform/fx_platform.c'),'-o',str(library)],check=True)
    lib=C.CDLL(str(library));ctxarg=C.POINTER(Platform)
    lib.fx_copy_startup_data.argtypes=[ctxarg];lib.fx_copy_startup_data.restype=C.c_int
    lib.fx_timer_start.argtypes=[ctxarg,C.c_uint16]
    names=['fx_timer_restart','fx_timer_flags','fx_acquire_busy','fx_mark_busy','fx_clear_busy',
           'fx_is_busy','fx_secondary_busy','fx_configure_key_port','fx_configure_interrupt_port',
           'fx_configure_display_port','fx_display_port_restart','fx_display_port_active',
           'fx_configure_ports','fx_display_port_sleep','fx_disable_display','fx_key_drive_enable',
           'fx_key_drive_disable','fx_key_select_all','fx_key_deselect_all','fx_any_key']
    for name in names:
        getattr(lib,name).argtypes=[ctxarg];getattr(lib,name).restype=C.c_uint8
    lib.fx_data_read.argtypes=[ctxarg,C.c_uint8,C.c_uint16];lib.fx_data_read.restype=C.c_uint8
    lib.fx_data_write.argtypes=[ctxarg,C.c_uint8,C.c_uint16,C.c_uint8]
    lib.fx_take_callback.argtypes=[ctxarg];lib.fx_take_callback.restype=C.c_uint8
    lib.fx_set_lcd_flag.argtypes=[ctxarg,C.c_uint8];lib.fx_set_lcd_flag.restype=None
    rom=(ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    rom_bytes=(C.c_uint8*len(rom)).from_buffer_copy(rom)
    ram=(C.c_uint8*65536)();ctx=Platform(rom_bytes,len(rom),ram,0,0)
    m=Machine(rom,ROOT/'analysis/build');rng=random.Random(0x991e5)
    background=rng.randbytes(65536)
    def restore():
        C.memmove(ram,background,65536);C.memmove(m.ram,background,65536)
    restore();assert lib.fx_copy_startup_data(C.byref(ctx))==0
    m.lib.harness_set_pc(0x6f86)
    assert m.lib.harness_run(10000,0x6fd8,False)==100
    assert bytes(ram)==bytes(m.ram)
    cases=1
    restore()
    for period in range(65536):
        lib.fx_timer_start(C.byref(ctx),period);m.er(0,period);m.call(0x538a)
        assert bytes(ram[0xf000:0xf100])==bytes(m.ram[0xf000:0xf100]),period
        cases+=1
    # Verify no writes outside the declared register area on this leaf routine.
    assert bytes(ram[:0xf000])==background[:0xf000]
    assert bytes(ram[0xf100:])==background[0xf100:]
    assert bytes(m.ram[:0xf000])==background[:0xf000]
    assert bytes(m.ram[0xf100:])==background[0xf100:]
    leaf=[(0x53d0,'fx_timer_restart',0xf014,False),
          (0x53f0,'fx_timer_flags',0xf014,True),
          (0x53f8,'fx_acquire_busy',0x80f4,True),
          (0x540a,'fx_mark_busy',0x80f4,False),(0x540e,'fx_clear_busy',0x80f4,False),
          (0x5416,'fx_is_busy',0x80f4,True),(0x541e,'fx_secondary_busy',0x80f4,True),
          (0x5472,'fx_configure_key_port',0xf048,False),
          (0x5482,'fx_configure_interrupt_port',0xf010,False),
          (0x54aa,'fx_configure_display_port',0xf031,False),
          (0x54c6,'fx_display_port_restart',0xf031,False),
          (0x54d8,'fx_display_port_active',0xf031,False),
          (0x54e0,'fx_display_port_sleep',0x80fc,False),
          (0x5514,'fx_disable_display',0xf033,False),
          (0x551c,'fx_key_drive_enable',0xf042,False),
          (0x5524,'fx_key_drive_disable',0xf042,False),
          (0x552c,'fx_key_select_all',0xf046,False),
          (0x5534,'fx_key_deselect_all',0xf046,False),
          (0x553c,'fx_any_key',0xf040,True)]
    for address,name,input_address,compare_result in leaf:
        for value in range(256):
            restore();ram[input_address]=value;m.ram[input_address]=value
            actual=getattr(lib,name)(C.byref(ctx));m.call(address)
            if compare_result: assert actual==m.reg(0),(name,value,actual,m.reg(0))
            assert bytes(ram)==bytes(m.ram),(name,value)
            cases+=1
    for value in range(256):
        restore();lib.fx_set_lcd_flag(C.byref(ctx),value);m.reg(0,value);m.call(0x550a)
        assert bytes(ram)==bytes(m.ram),('lcd flag',value)
        cases+=1
    restore();lib.fx_configure_ports(C.byref(ctx));m.call(0x542a)
    # C has no emulated call stack; native PUSH/POP scratch is not API state.
    assert bytes(ram[:0x8dc0])==bytes(m.ram[:0x8dc0])
    assert bytes(ram[0x8dee:])==bytes(m.ram[0x8dee:])
    cases+=1
    # Data bus behavior is compared to the passive headless oracle, not hardware.
    m.lib.memoryGetData.argtypes=[C.c_uint8,C.c_uint16,C.c_size_t]
    m.lib.memoryGetData.restype=C.c_uint64
    m.lib.memorySetData.argtypes=[C.c_uint8,C.c_uint16,C.c_size_t,C.c_uint64]
    for segment in range(16):
        for address in [0,1,0x7fff,0x8000,0xf000,0xf800,0xffff]:
            assert lib.fx_data_read(C.byref(ctx),segment,address)==m.lib.memoryGetData(segment,address,1)
            cases+=1
    restore();ctx.callback_pending=0;m.lib.harness_callback()
    for value in range(256):
        lib.fx_data_write(C.byref(ctx),0,0xf000,value)
        m.lib.memorySetData(0,0xf000,1,value)
        assert lib.fx_take_callback(C.byref(ctx))==m.lib.harness_callback(),value
        assert ram[0xf000]==m.ram[0xf000]
        cases+=1
    report={'status':'pass','cases':cases,'rom_sha256':hashlib.sha256(rom).hexdigest(),
            'startup_copy':'full RAM equality through native PC 0x6fd8; not full boot',
            'timer_periods':65536,'leaf_control_input_bytes':256,
            'comparison':'Whole RAM for startup and leaf controls; timer register area plus preservation outside it; returned values for queries. Port startup excludes native call-stack scratch 8dc0..8ded.',
            'limitations':['Passive peripheral register semantics; physical timing and keyboard interrupts remain unimplemented.','Bus checks compare the headless oracle mapping, not the Windows emulator host.']}
    report=write_report(OUT/'platform.json',report,
        ['csrc/platform/fx_platform.c','csrc/platform/fx_platform.h',
         'tools/c_verification.py'],'tools/test_platform_c.py')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
