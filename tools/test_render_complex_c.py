#!/usr/bin/env python3
"""Complex/polar result display versus the original test-only firmware oracle."""
import argparse
import ctypes as C
import hashlib
import json
from pathlib import Path
import random
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from nxu8.machine import Machine
from c_verification import write_report
from test_complex_c import Number,Rational,decimal_record

class Render(C.Structure):
    _fields_=[('rom',C.POINTER(C.c_uint8)),('rom_size',C.c_size_t),('memory',C.POINTER(C.c_uint8))]
class Box(C.Structure):
    _fields_=[('width',C.c_uint16),('height',C.c_uint8),('depth',C.c_uint8)]

SOURCES=['csrc/render/fx_result_complex.c','csrc/render/fx_result_complex.h',
 'csrc/render/fx_result_verify.c','csrc/render/fx_result_verify.h',
 'csrc/render/fx_render.c','csrc/render/fx_render.h','csrc/render/fx_render_context.c','csrc/render/fx_render_context.h',
 'csrc/render/fx_render_memory.c','csrc/render/fx_render_memory.h','csrc/render/fx_layout.c',
 'csrc/render/fx_layout_validate.c','csrc/render/fx_layout_validate.h','csrc/render/fx_viewport.c',
 'csrc/render/fx_result_format_state.c','csrc/render/fx_result_format_state.h',
 'csrc/render/fx_result_inequality.c','csrc/render/fx_result_inequality.h',
 'csrc/complex/fx_complex.c','csrc/complex/fx_complex.h','csrc/complex/fx_complex_angle.c','csrc/complex/fx_complex_angle.h',
 'csrc/format/fx_format.c','csrc/format/fx_format.h','csrc/format/fx_format_budget.c','csrc/format/fx_format_budget.h',
 'csrc/trig/fx_trig.c','csrc/trig/fx_trig.h','csrc/trig/fx_trig_math.c','csrc/trig/fx_trig_math.h',
 'csrc/trig/fx_trig_inverse.c','csrc/trig/fx_trig_inverse.h','csrc/trig/fx_math_context.c','csrc/trig/fx_math_context.h',
 'csrc/numeric/fx_numeric.c','csrc/numeric/fx_numeric.h',
           'csrc/numeric/fx_surd_components.c',
           'csrc/numeric/fx_raw_decimal_divide.c',
           'csrc/numeric/fx_raw_decimal_multiply_add.c',
           'csrc/numeric/fx_raw_decimal_parts.c',
           'csrc/numeric/fx_surd_components.h',
           'csrc/numeric/fx_numeric_components.h',
           'csrc/numeric/fx_raw_decimal_divide.h',
           'csrc/numeric/fx_raw_decimal_multiply_add.h',
           'csrc/numeric/fx_raw_decimal_parts.h'
]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--quick',action='store_true')
    parser.add_argument('--no-report',action='store_true')
    parser.add_argument('--random-cases',type=int,default=5000)
    args=parser.parse_args()
    build=ROOT/'analysis/build/render-complex';build.mkdir(parents=True,exist_ok=True)
    library=build/'render-complex.so'
    subprocess.run(['gcc','-std=c99','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',
                    *(str(ROOT/source) for source in SOURCES if source.endswith('.c')),'-o',str(library)],check=True)
    lib=C.CDLL(str(library));byte=C.c_uint8
    lib.fx_display_complex_result.argtypes=[C.POINTER(Render),C.c_uint16,C.POINTER(Box)]
    lib.fx_display_complex_result.restype=C.c_int
    lib.fx_flush_framebuffer.argtypes=[C.POINTER(Render)]
    lib.fx_display_has_natural_input.argtypes=[C.POINTER(Render)]
    lib.fx_display_has_natural_result.argtypes=[C.POINTER(Render)]
    lib.fx_decimal_parse.argtypes=[C.POINTER(Number),C.c_char_p]
    lib.fx_rational_encode.argtypes=[C.POINTER(Number),C.POINTER(Rational)]
    lib.fx_surd_pack.argtypes=[C.POINTER(Number),C.POINTER(Number)]
    ROM=(ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    rom=(byte*len(ROM)).from_buffer_copy(ROM);memory=(byte*65536)()
    render=Render(rom,len(ROM),memory);r=C.byref(render)
    oracle=Machine(ROM,build/'oracle');counts={};faults=[];rng=random.Random(0xb070c)

    def literal(value):
        number=Number();assert lib.fx_decimal_parse(C.byref(number),str(value).encode())==0
        return bytes(number)
    def fraction(numerator,denominator):
        number=Number();assert lib.fx_rational_encode(C.byref(number),C.byref(Rational(numerator,denominator,0)))==0
        return bytes(number)
    def surd(values):
        parts=(Number*6)()
        for n,value in enumerate(values):assert lib.fx_decimal_parse(C.byref(parts[n]),str(value).encode())==0
        output=Number();assert lib.fx_surd_pack(C.byref(output),parts)==0
        return bytes(output)
    def setting(address,value):memory[address]=oracle.ram[address]=value
    def same(start,length,detail):
        actual=bytes(memory[start:start+length]);expected=bytes(oracle.ram[start:start+length])
        if actual!=expected:
            n=next(n for n,(a,b) in enumerate(zip(actual,expected)) if a!=b)
            raise AssertionError((detail,hex(start+n),expected[n],actual[n],expected.hex() if length<128 else '',actual.hex() if length<128 else ''))
    def compare(group,record,selection=0,mode=196,enabled=1,font=10,selected=1,
                polar=0,override=0,unit=4,display=0,digits=0,height=0,editing=0,cached=None,address=0x8300,preference=None):
        oracle.reset();C.memset(memory,0,65536)
        for location,value in [(0x80f9,mode),(0x80fc,1),(0x80fe,editing),(0x8100,selection),
                              (0x8102,display),(0x8103,digits),(0x8104,1),(0x8105,unit),(0x8106,enabled),
                              (0x8108,int(not polar) if preference is None else preference),(0x8101,override),(0x811f,font),(0x8121,selected),
                              (0x8128,height),(0x8130,int(cached is not None)),(0xf031,0x5a)]:setting(location,value)
        oracle.word(0x812c,0x8200);memory[0x812c]=0;memory[0x812d]=0x82
        for n,value in enumerate(record):setting(0x8300+n,value)
        for n in range(384):setting(0x87d0+n,(n*17+3)&255)
        for n in range(512):setting(0xf800+n,(n*7+17)&255)
        for n in range(256):setting(0x9800+n,(n*31+5)&255)
        persistent=0x8546 if mode==136 or not mode&128 else 0x8398
        if cached is not None:
            for n,value in enumerate(cached):setting(persistent+n,value)
        permitted=bool(lib.fx_display_has_natural_input(r) or lib.fx_display_has_natural_result(r))
        natural=permitted and selection&15!=10
        detail=(group,record.hex(),selection,mode,enabled,font,selected,polar,override,unit,display,digits,height,editing,cached.hex() if cached else '')
        oracle.er(0,address)
        # Large prime-factor records can execute more than the default one
        # million instructions. Exhausting that budget is not a native crash.
        try:oracle.call(0xb070,limit=20000000)
        except RuntimeError as error:
            portable_status=lib.fx_display_complex_result(r,address,C.byref(Box()))
            faults.append(dict(detail=detail,outcome=str(error),portable_status=portable_status,
                frame_sha256=hashlib.sha256(bytes(oracle.ram[0x87d0:0x8950])).hexdigest(),
                portable_frame_sha256=hashlib.sha256(bytes(memory[0x87d0:0x8950])).hexdigest()))
            assert bytes(memory[0x8300:0x8314])==record
            return
        status=lib.fx_display_complex_result(r,address,C.byref(Box()))
        assert status==1,(detail,'portable status',status)
        for start,length in [(0x8100,64),(0x8300,20),(0x87d0,384),(0x9800,256),(0xf800,512),(0xf031,1)]:same(start,length,detail)
        assert bytes(memory[0x8300:0x8314])==record
        if permitted:
            expected=bytes(oracle.ram[persistent:persistent+1024]).split(b'\0')[0]
            same(persistent,len(expected)+1,detail)
        if natural or cached is not None:
            for start,length in [(0x8000,6),(0x8007,4),(0x8640,memory[0x8008]*4)]:same(start,length,detail)
        oracle.call(0x3cfc);lib.fx_flush_framebuffer(r);same(0xf800,512,detail)
        counts[group]=counts.get(group,0)+1

    zero=literal(0);one=literal(1);minus_one=literal(-1)
    topology=[literal(a)+literal(b) for a in (0,3,-3) for b in (0,1,-1,2,-2)]
    sqrt2=bytes.fromhex('80000001000201010100');two_surds=bytes.fromhex('80020102000301020101')
    exact=[fraction(1,3)+sqrt2,sqrt2+fraction(1,3),fraction(1,3)*2,sqrt2+bytes.fromhex('80000001000301010100'),
           literal(3)+two_surds,two_surds+literal(2),zero+two_surds]
    exact += [literal(3)+surd([-2,2,1,0,1,1]),zero+surd([-1,2,1,1,3,1]),
              literal(3)+bytes.fromhex('89970199099801990106'),surd([1,2,1,1,3,1])+literal(2),
              zero+surd([1,2,1,-1,2,1])]
    decimals=[literal('1.2345')+literal('-9.8765'),literal('1e-99')+literal('-1e99'),
              literal('1e10')+literal('-1e10'),zero+literal('1e-10'),literal(3)+literal('3.14159265358979')]
    errors=[bytes([header])+bytes(9) for header in range(0xf0,0x100)]
    selections=(0,1,10,11,13,14,15,0x1d,0x65,0x56,0x6d,0x6e) if args.quick else range(256)
    for record in topology+exact[:4]+decimals[:2]:
        for selection in selections:
            compare('selection_byte_topology_and_exact',record,selection)
    configurations=[(mode,enabled,font,selected) for mode in (1,65,129,193,196,136)
                    for enabled in (0,1) for font in (6,7,10) for selected in (0,1)]
    if args.quick:configurations=[(196,1,10,1),(196,0,7,0),(193,1,10,1),(65,1,7,1),(1,0,6,0)]
    for mode,enabled,font,selected in configurations:
        for record in topology+exact+decimals:
            for selection in ((0,1,10,13,0x65) if mode==1 else (0,1,10,13,14,15,0x65)):
                compare('display_modes_fonts_maps',record,selection,mode,enabled,font,selected,height=24,editing=1)
    for error in errors:
        for record in (error+one,literal(3)+error):
            for selection in (0,1,10,13,14,15,0x65):compare('all_error_headers',record,selection)
    polar_pairs=[literal(a)+literal(b) for a,b in [(0,0),(0,1),(0,-1),(3,0),(-3,0),(3,4),(3,-4),(-3,4),(-3,-4),(1,1),(1,-1)]]
    for record in polar_pairs:
        for unit in (4,5,6):
            for enabled in (0,1):
                for override in (0,1,2):
                    for selection in (0,1,10,13,14,15,0x65):
                        compare('polar_units_axes_quadrants_overrides',record,selection,enabled=enabled,polar=1,override=override,unit=unit)
    for record in (errors[0]+one,literal(3)+errors[3],errors[13]+one):
        for unit in (4,5,6):
            for selection in (0,10,13,15):compare('polar_error_components',record,selection,polar=1,unit=unit)
    for preference in range(256) if not args.quick else (0,1,37,255):
        compare('all_polar_preference_bytes',literal(3)+literal(4),13,polar=int(preference==0),preference=preference)
    marked=bytearray(literal('1.2345'));marked[0]|=0x40
    for selection in (0,1,13,0x1d,0x65):compare('marked_dms_axis_bypass',bytes(marked)+zero,selection,polar=1)
    for record in topology+decimals:
        for display,digits in ((0,0),(4,0),(8,0),(8,4),(9,0),(9,4)):
            for selection in (0,1,10,13,0x65):compare('display_precision',record,selection,display=display,digits=digits)
    for selection in (0,10,13,14,15):
        for expression in (b'12\0',bytes.fromhex('aebbb831b9b833b9bc00'),bytes.fromhex('98b832b900'),b'\0',b'\0XY\0'):
            for height in (0,24):
                compare('cached_numeric_bypass',literal(3)+literal(4),selection,height=height,cached=expression)
    for address in (0,0x7fff,0xfff0):
        compare('cached_invalid_address_unread',bytes([0xff])*20,15,cached=b'12\0',address=address)
    for mode,selection,status in ((1,14,0),(1,15,0),(196,0,0x10),(69,0,0)):
        oracle.reset();C.memset(memory,0,65536)
        for place,value in [(0x80f9,mode),(0x80fc,1),(0x80ff,status),(0x811f,10),(0x8100,selection),(0x8106,1)]:setting(place,value)
        before=bytes(memory)
        assert lib.fx_display_complex_result(r,0x8300,C.byref(Box()))==-1
        assert bytes(memory)==before
    counts['explicit_unsupported_context_guards']=4
    # Preserve the old137 admission control as a genuine original-ROM
    # comparison now that the branch is implemented. NULL live label
    # pointers are valid empty spellings; the separate mode137 corpus also
    # tests initialized and rewritten label pointers.
    compare('newly_supported_verify_context',literal(3)+literal(4),0,mode=137)
    for index in range(0 if args.quick else args.random_cases):
        parts=[]
        for component in range(2):
            if rng.randrange(8)==0:parts.append(zero)
            elif rng.randrange(4)==0:parts.append(rng.choice([fraction(1,3),fraction(7,3),sqrt2,two_surds]))
            else:parts.append(decimal_record(rng.randrange(10**14,10**15),rng.randrange(-99,100),rng.choice([-1,1]),0x40 if index%11==component else 0))
        compare('random_valid_components',b''.join(parts),rng.randrange(256),mode=rng.choice([65,129,193,196,136]),
                enabled=rng.randrange(2),selected=rng.randrange(2),polar=int(index%7==0),unit=rng.choice([4,5,6]),
                display=rng.choice([0,4,8,9]),digits=rng.randrange(10))
    report={'status':'pass','full_firmware_complete':False,'tests':counts,'total_cases':sum(counts.values()),
            'implementation':'readable high-level C; extracted ROM is constant font/table data only',
            'comparison_scope':'tokens,8100..813F,source20bytes,active viewport/cache,history9800..98FF,framebuffer,all512LCDbytes before/afterflush,F031',
            'oracle_instruction_limit_per_call':20000000,
            'explicit_gaps':['numeric scratch within8000..80DB and inactive metric slots','CPU scratch flags/registers/temporary stack aliases',
                             'status80FFbit4 and equation-mode polar policies','other nonordinary result modes; mode137 has its own full raw-record/display corpus'],
            'original_native_faults':faults}
    if not args.no_report:
        assert not args.quick,'A reduced suite cannot publish the canonical report'
        report=write_report('analysis/c-verification/render_complex.json',report,SOURCES+['tools/test_complex_c.py'],
                            'tools/test_render_complex_c.py')
    print(json.dumps(report,indent=2))
if __name__=='__main__':main()
