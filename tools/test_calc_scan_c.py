#!/usr/bin/env python3
"""Differential CALC variable discovery against original172F6 and all RAM."""
import ctypes as C
import hashlib
import json
import random
import subprocess
from pathlib import Path

from c_build_inputs import implementation_inputs
from c_verification import ROOT, write_report
from nxu8.machine import Machine
from test_platform_c import Platform

SOURCES = ['csrc/ui/fx_calc_scan.c', 'csrc/platform/fx_platform.c',
           'csrc/parse/fx_tokens.c', 'csrc/data/fx_rom_data.c']
ADAPTER = r'''/* Observe the original CPU; no replacement instructions. */
#include "harness.c"
unsigned calc_scan_floor;
int calc_scan_run(void) {
    calc_scan_floor=0x8dee;
    for (unsigned i=0;i<500000;++i) {
        unsigned sp=harness_get_sp();
        if (sp<calc_scan_floor) calc_scan_floor=sp;
        int status=harness_run(1,0x2fffe,false);
        if (status!=103) return status;
    }
    return 103;
}
'''


def main():
    build = ROOT/'analysis/build/calc-scan'
    build.mkdir(parents=True, exist_ok=True)
    pins = implementation_inputs(ROOT, SOURCES)
    before_pins = {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in pins}
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-shared', '-fPIC', '-Wl,--no-undefined',
                    *[str(ROOT/p) for p in SOURCES], '-o', str(build/'calc.so')], check=True)
    lib = C.CDLL(str(build/'calc.so'))
    lib.fx_calc_scan_variables.argtypes = [C.POINTER(Platform)]
    rom = (ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    native = Machine(rom, build/'machine')
    (build/'observer.c').write_text(ADAPTER)
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-shared', '-fPIC', '-I', str(ROOT/'tools/nxu8'),
                    str(build/'observer.c'), str(ROOT/'tools/nxu8/vendor/SimU8/core.c'),
                    '-o', str(build/'observer.so')], check=True)
    observer = C.CDLL(str(build/'observer.so'))
    for name in ('harness_init', 'harness_set_pc', 'harness_get_pc', 'harness_set_reg',
                 'harness_get_reg', 'harness_set_sp', 'harness_get_sp', 'harness_set_lr',
                 'harness_ram'):
        getattr(observer, name).argtypes = getattr(native.lib, name).argtypes
        getattr(observer, name).restype = getattr(native.lib, name).restype
    native.lib = observer
    native.ram = observer.harness_ram().contents
    rb = (C.c_uint8*len(rom)).from_buffer_copy(rom)
    ram = (C.c_uint8*65536)()
    platform = Platform(rb, len(rom), ram, 0, 0)
    rng = random.Random(0x172f6)
    cases = []
    for mode in (0xc1, 0xc4, 0x88, 2):
        for raw in range(256):
            cases.append((bytes([raw]), mode, 0xa0))
            cases.append((b'X:'+bytes([raw])+b':A+X', mode, 0xa0))
    expressions = [b'', b'X+A=9', b'X=3:X+A', b'A=3:A+X', b'A=3:A=A+X:A',
                   b'A=3:B=A:B+X', b'A+A:A=2:A', b':A=3::A+B',
                   b'Ans+A', b'A=3:A=4:A', b'A=3:A+M:X+Y', b'X=3,X+Y']
    for mode in range(256):
        for expression in expressions:
            cases.append((expression, mode, 0xa0))
    for _ in range(2000):
        raw = bytes(rng.randrange(256) for _ in range(rng.randrange(1,48)))
        cases.append((raw, rng.randrange(256), rng.choice([0,1,0x20,0x80,0xa0])))
    for screen in range(256):
        if screen&64: continue
        for mode in (0xc1,0xc4):
            cases.append((b'A=A+X:A+B:M=2:M+X',mode,screen))
    # The physical FF-list initialization intersects overlong source streams.
    # Keep these native inputs intact and compare live-read effects, rather
    # than substituting an immutable host string for scanner bus reads.
    for length in (96,99,100,101,102,103,111,128,256):
        for raw in (b'X'*length, (b'A+X:'*((length+3)//4))[:length]):
            for mode in (0xc1,0xc4):
                cases.append((raw,mode,0xa0))
    checks = 0
    failures = []
    floors = set()
    for index, (raw, mode, screen) in enumerate(cases):
        native.reset()
        # Poison all RAM, rather than only the output list. Frame bytes are
        # excluded solely by the observer's actual minimum SP on this call.
        poison = bytes(rng.randrange(256) for _ in range(256))
        C.memmove(native.ram, poison*256, 65536)
        native.ram[0x80f9] = mode
        native.ram[0x80fc] = screen
        C.memmove(C.byref(native.ram,0x8398),raw+b'\0',len(raw)+1)
        C.memmove(ram,bytes(native.ram),65536)
        platform.callback_pending=platform.status=0
        actual = lib.fx_calc_scan_variables(C.byref(platform))
        observer.harness_set_sp(0x8dee)
        observer.harness_set_lr(0x2fffe)
        observer.harness_set_pc(0x172f6)
        execution = observer.calc_scan_run()
        floor = C.c_uint.in_dll(observer,'calc_scan_floor').value
        floors.add(floor)
        expected_status=native.reg(0)
        expected, observed=bytes(native.ram), bytes(ram)
        differences=[]
        if expected[:floor]!=observed[:floor] or expected[0x8dee:]!=observed[0x8dee:]:
            differences=[(f'{a:04x}',expected[a],observed[a]) for a in range(65536)
                         if expected[a]!=observed[a] and not floor<=a<0x8dee]
        checks += 3
        if execution!=100 or actual!=expected_status or differences:
            failures.append(dict(index=index,raw=raw.hex(),mode=mode,screen=screen,
                execution=execution,expected_status=expected_status,actual_status=actual,
                differences=differences))
    # SOLVE admission and invalid host guards decline before any write.
    snapshot=bytes(ram)
    for screen in (0x40,0xc0,0xff):
        ram[0x80fc]=screen
        saved=bytes(ram)
        assert lib.fx_calc_scan_variables(C.byref(platform))==-2
        assert bytes(ram)==saved
        checks+=2
    assert lib.fx_calc_scan_variables(None)==-1
    checks+=1
    C.memmove(ram,snapshot,65536)
    changed=[p for p,digest in before_pins.items()
             if hashlib.sha256((ROOT/p).read_bytes()).hexdigest()!=digest]
    assert not changed, changed
    if failures:
        (build/'failures.json').write_text(json.dumps(failures,indent=2)+'\n')
        print(json.dumps({'cases':len(cases),'failures':len(failures),'first':failures[:3]},indent=2))
        raise SystemExit(1)
    report=write_report('analysis/c-verification/calc_scan.json',
        {'cases':len(cases),'original_calls':len(cases),'checks':checks,
         'comparison':'Native status plus all65536 RAM bytes outside each call measured CPU frame.',
         'native_stack_floors':[f'{v:04x}' for v in sorted(floors)],
         'domains':['all input byte values in four calculation contexts',
                    'assignment and repeated-variable statements in all256 contexts',
                    '2000 seeded raw streams with poisoned RAM',
                    'all128 non-SOLVE screen bytes in COMP and CMPLX',
                    'live source/list aliases in overlong96..256-byte streams'],
         'limits':['Host guard on 65536 decoder reads; no native nonreturn is classified as parity.']},
        pins+['tools/c_build_inputs.py','tools/test_platform_c.py','tools/c_verification.py'],
        'tools/test_calc_scan_c.py')
    print(json.dumps({key:report[key] for key in ('status','cases','checks','original_calls')},indent=2))


if __name__=='__main__':
    main()
