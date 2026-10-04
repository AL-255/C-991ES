#!/usr/bin/env python3
"""Native E67C/E71E error/context recovery without production CPU frames."""
import argparse
import ctypes as C
import hashlib
import json
import random
import subprocess

from c_verification import ROOT, write_report
from nxu8.machine import Machine
from test_platform_c import Platform
from trace_natural_result import settings


class Context(C.Structure):
    _fields_ = [('display_address',C.c_uint16),('result_address',C.c_uint16),
                ('calculation_mode',C.c_uint8),('saved_math_result',C.c_uint8),
                ('return_value',C.c_uint8)]


MODULES = ['ui/fx_input_recover','platform/fx_platform','platform/fx_boot',
           'platform/fx_host_bridge','platform/fx_persistent','ui/fx_keys',
           'ui/fx_cursor','ui/fx_editor','ui/fx_natural_editor','parse/fx_tokens',
           'numeric/fx_numeric','numeric/fx_surd_components','numeric/fx_raw_decimal_parts','numeric/fx_raw_decimal_divide','numeric/fx_raw_decimal_multiply_add','complex/fx_complex','format/fx_format','format/fx_format_base',
           'render/fx_render','render/fx_render_context','render/fx_render_memory',
           'render/fx_layout_validate','render/fx_result_special', 'render/fx_result_verify','render/fx_result_format_state',
           'data/fx_rom_data']
SOURCES = ['csrc/'+module+'.c' for module in MODULES]


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--random-cases',type=int,default=4000)
    ap.add_argument('--no-report',action='store_true')
    args=ap.parse_args()
    build=ROOT/'analysis/build/input-recover';build.mkdir(parents=True,exist_ok=True)
    library=build/'recover.so'
    subprocess.run(['gcc','-std=c99','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',
                    '-Wl,--no-undefined',*[str(ROOT/f) for f in SOURCES],'-o',str(library)],check=True)
    lib=C.CDLL(str(library))
    for name in ('fx_input_recover_after_error','fx_input_reset_context'):
        getattr(lib,name).argtypes=[C.POINTER(Platform),C.POINTER(Context)]
    rom=(ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    rb=(C.c_uint8*len(rom)).from_buffer_copy(rom);ram=(C.c_uint8*65536)()
    p=Platform(rb,len(rom),ram,0,0);native=Machine(rom,build/'oracle')
    rng=random.Random(0xe67c);background=bytearray(rng.randbytes(65536))
    background[0x8dee:0x8e00]=rom[0x1f8dc:0x1f8ee]
    counts={};gaps=[]
    records=[bytes(10),bytes.fromhex('03000000000000000001'),
             bytes.fromhex('03000000000000000006'),bytes.fromhex('21a30000000000000301'),
             bytes.fromhex('80000001000201010100'),bytes.fromhex('80011322012201010601'),
             bytes.fromhex('f3000000000000000000')]

    def record(group):counts[group]=counts.get(group,0)+1
    def put(a,v):ram[a]=native.ram[a]=v
    def word(a,v):put(a,v&255);put(a+1,v>>8)
    def string(a,v):
        for i,b in enumerate(v+b'\0\0'):put(a+i,b)

    def prepare(mode=0xc1,context_mode=None,saved=0,screen=1,item=0,natural=1,
                solve_unit=0,solve_flags=0,mode12_flag=0,real=None,display=0x8154):
        native.reset();C.memmove(native.ram,bytes(background),65536);settings(native)
        C.memmove(ram,native.ram,65536)
        for a,v in ((0x80f9,mode),(0x80fa,1),(0x80fc,screen),(0x80fd,item),(0x80fe,0x80),
                    (0x8106,natural),(0x810e,solve_unit),(0x8138,solve_flags),(0x8137,mode12_flag),
                    (0x80f8,0),(0x80dd,0),(0x8102,0),(0x8103,0),(0x8104,1),(0x8107,0),
                    (0x810c,0),(0x8120,0),(0x8121,1),(0x8114,3),(0x811f,10),(0x811b,10)):
            put(a,v)
        string(0x8154,b'old expression');string(0x81b8,b'backup input')
        string(0x85aa,b'saved solve input')
        if display!=0x8154:string(display,b'alternate input')
        for i,b in enumerate((records[1] if real is None else real)+records[0]):put(0x8140+i,b)
        mode=context_mode if context_mode is not None else mode
        context=Context(display,0x8140,mode,saved,0xa5)
        # This external fixture belongs only to the independent oracle. The
        # production API receives the named host object above, never this RAM.
        word(0x9000,display);word(0x9002,0x8140);put(0x9004,0xa5)
        put(0x9006,mode);put(0x9007,saved)
        p.callback_pending=p.status=0
        return context

    def compare(group,detail,context):
        actual=bytearray(ram);expected=bytes(native.ram)
        assert context.return_value==expected[0x9004],(group,detail,'host_return',context.return_value,expected[0x9004])
        # Project the named host output into the one oracle-only context field.
        actual[0x9004]=context.return_value
        # Saved rational/surd formatting nests past8D00; the original CPU
        # call-frame region for this composed routine extends into8Cxx.
        spans=[(0,0x8000),(0x80dc,0x8640),(0x867c,0x8c00),(0x8dee,65536)]
        if any(actual[lo:hi]!=expected[lo:hi] for lo,hi in spans):
            mismatch=[(hex(a),actual[a],expected[a]) for lo,hi in spans for a in range(lo,hi)
                      if actual[a]!=expected[a]]
            raise AssertionError((group,detail,mismatch[:30]))
        assert p.callback_pending==native.lib.harness_callback(),(group,detail,'callback')
        p.callback_pending=0;record(group)

    def case(entry,address,group,detail,**kw):
        context=prepare(**kw)
        actual=getattr(lib,entry)(C.byref(p),C.byref(context))
        native.er(0,0x9000);native.call(address)
        if actual<0:
            assert (entry=='fx_input_recover_after_error' and kw.get('mode')==0x89
                    and kw.get('saved') and (kw.get('real',records[1])[0]&0xf0)!=0xf0), \
                ('unexpected unsupported fixture',entry,detail,actual)
            gaps.append({'entry':hex(address),'fixture':str(detail),
                         'native_return':native.reg(0),'c_return':actual,
                         'native_ram_sha256':hashlib.sha256(bytes(native.ram)).hexdigest(),
                         'native_lcd_sha256':hashlib.sha256(bytes(native.ram[0xf800:0xfa00])).hexdigest(),
                         'native_framebuffer_sha256':hashlib.sha256(bytes(native.ram[0x87d0:0x8950])).hexdigest()})
            return
        assert actual==native.reg(0),(group,detail,actual,native.reg(0))
        compare(group,detail,context)

    for mode in range(256):
        for natural in (0,1):
            for screen,item in ((1,0),(6,1),(6,4),(0x10,0),(0x81,2)):
                case('fx_input_recover_after_error',0x1e67c,'all_mode_editor_reset',
                     (mode,natural,screen,item),mode=mode,natural=natural,screen=screen,item=item)
                case('fx_input_reset_context',0x1e71e,'all_mode_context_reset',
                     (mode,natural,screen,item),mode=mode,natural=natural,screen=screen,item=item)
    for mode in (0xc1,0xc4,2,0x88,0x89,0x45,12):
        for saved in (0,1,255):
            for real in records:
                for screen,item in ((1,0),(6,4),(0x10,0)):
                    case('fx_input_recover_after_error',0x1e67c,'saved_result_and_mode_policy',
                         (mode,saved,real.hex(),screen,item),mode=mode,saved=saved,real=real,
                         screen=screen,item=item)
    for item in (0,1,4,255):
        for unit in (0,1,2,255):
            for flags in range(256):
                case('fx_input_recover_after_error',0x1e67c,'solve_backup_and_clear',
                     (item,unit,flags),mode=0x88,item=item,solve_unit=unit,solve_flags=flags,
                     display=0x8200 if flags%2 else 0x8154)
    for mode in (0xc1,12,0x88):
        for context_mode in (0xc1,12,0x88,0x4b):
            for flag in range(256):
                case('fx_input_reset_context',0x1e71e,'mode12_initial_screen',
                     (mode,context_mode,flag),mode=mode,context_mode=context_mode,mode12_flag=flag)
    for i in range(args.random_cases):
        case('fx_input_recover_after_error',0x1e67c,'random_context_and_record',i,
             mode=rng.choice([0xc1,0xc4,2,0x88,0x89,0x45,12]),saved=rng.randrange(2),
             screen=rng.choice([1,6,0x10,0x81]),item=rng.randrange(5),natural=rng.randrange(2),
             solve_unit=rng.randrange(3),solve_flags=rng.randrange(256),mode12_flag=rng.randrange(2),
             real=rng.choice(records))
    for entry in ('fx_input_recover_after_error','fx_input_reset_context'):
        assert getattr(lib,entry)(C.byref(p),None)==-1
        record('null_host_context_guard')
    report={'cases':sum(counts.values()),'domains':counts,'unsupported_native_fixtures':gaps,
            'comparison':'OriginalE67C/E71E return andnamedcontext output, allremaining64KiB RAM/LCD/MMIO andcallbacks; hostreturnvalue projected into oneoracle-only contextbyte9004. NativeCPUstack8C00..8DED andcallednumericworkspaces8000..80DB/8640..867B excluded.',
            'scope':'Editor/errorrecovery, savedrealresult restoration, allmode bytes, mode12 reset, solvebackup/clear selection andparentcontextreturn. Inheritedsharedinitializer/renderer unsupportedcases are explicitledger entries; nofullhandler/evaluator.'}
    if not args.no_report:
        deps=SOURCES+[f for f in [s[:-2]+'.h' for s in SOURCES] if (ROOT/f).exists()]
        deps+=['tools/test_platform_c.py','tools/trace_natural_result.py','tools/c_verification.py']
        report=write_report('analysis/c-verification/input_recover.json',report,deps,'tools/test_input_recover_c.py')
    print(json.dumps({k:v for k,v in report.items() if k not in ('tested_inputs_sha256','unsupported_native_fixtures')},indent=2))
    print('unsupported_native_fixtures',len(gaps))


if __name__=='__main__':main()
