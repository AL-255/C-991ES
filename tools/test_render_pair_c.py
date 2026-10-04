#!/usr/bin/env python3
"""Paired Pol/Rec/Qrem/SOLVE result display versus the original test-only firmware oracle."""
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
from c_build_inputs import implementation_inputs
from test_complex_c import Number,Rational,decimal_record

class Render(C.Structure):
    _fields_=[('rom',C.POINTER(C.c_uint8)),('rom_size',C.c_size_t),('memory',C.POINTER(C.c_uint8))]
class Box(C.Structure):
    _fields_=[('width',C.c_uint16),('height',C.c_uint8),('depth',C.c_uint8)]

SOURCES=['csrc/render/fx_result_pair.c','csrc/render/fx_result_pair.h',
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
    sources=implementation_inputs(ROOT,SOURCES)
    build=ROOT/'analysis/build/render-pair';build.mkdir(parents=True,exist_ok=True)
    library=build/'render-pair.so'
    subprocess.run(['gcc','-std=c99','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',
                    *(str(ROOT/source) for source in SOURCES if source.endswith('.c')),'-o',str(library)],check=True)
    lib=C.CDLL(str(library));byte=C.c_uint8
    lib.fx_display_pair_result.argtypes=[C.POINTER(Render),C.c_uint16,C.POINTER(Box)]
    lib.fx_display_pair_result.restype=C.c_int
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
    comparisons=0;native_calls=0

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
        nonlocal comparisons
        comparisons+=1
        actual=bytes(memory[start:start+length]);expected=bytes(oracle.ram[start:start+length])
        if actual!=expected:
            n=next(n for n,(a,b) in enumerate(zip(actual,expected)) if a!=b)
            raise AssertionError((detail,hex(start+n),expected[n],actual[n],expected.hex() if length<128 else '',actual.hex() if length<128 else ''))
    def compare(group,record,selection=0,mode=196,enabled=1,font=10,selected=1,
                polar=0,override=0,unit=4,display=0,digits=0,height=0,editing=0,cached=None,address=0x8300,preference=None,status_byte=17,decimal_dot=1,variable=0,screen=1,width=0):
        nonlocal native_calls
        oracle.reset();C.memset(memory,0,65536)
        for location,value in [(0x80f9,mode),(0x80fc,screen),(0x80ff,status_byte),(0x83fc,variable),(0x80fe,editing),(0x8100,selection),
                              (0x8102,display),(0x8103,digits),(0x8104,decimal_dot),(0x8105,unit),(0x8106,enabled),
                              (0x8108,int(not polar) if preference is None else preference),(0x8101,override),(0x811f,font),(0x8121,selected),
                              (0x8128,height),(0x8115,width),(0x8130,int(cached is not None)),(0xf031,0x5a)]:setting(location,value)
        oracle.word(0x812c,0x8200);memory[0x812c]=0;memory[0x812d]=0x82
        for n,value in enumerate(record):setting(0x8300+n,value)
        for n in range(384):setting(0x87d0+n,(n*17+3)&255)
        for n in range(512):setting(0xf800+n,(n*7+17)&255)
        for n in range(256):setting(0x9800+n,(n*31+5)&255)
        persistent=0x8546 if mode==136 or not mode&128 else 0x8398
        # C1F0 leaves dormant padding bytes after the earlier result NUL.
        # Poison the destination so the comparison cannot hide missed writes.
        for n in range(64):setting(persistent+n,(n*23+0xa5)&255)
        if cached is not None:
            for n,value in enumerate(cached):setting(persistent+n,value)
        permitted=bool(lib.fx_display_has_natural_input(r) or lib.fx_display_has_natural_result(r))
        effective_selection=10 if status_byte==19 or not permitted else selection&15
        natural=permitted and effective_selection!=10
        cache_used=cached is not None and status_byte!=19 and permitted
        detail=(group,record.hex(),selection,mode,enabled,font,selected,polar,override,unit,display,digits,height,editing,cached.hex() if cached else '',status_byte,decimal_dot,variable,screen,width)
        oracle.er(0,address)
        # Large prime-factor records can execute more than the default one
        # million instructions. Exhausting that budget is not a native crash.
        try:oracle.call(0xb070,limit=20000000)
        except RuntimeError as error:
            native_calls+=1
            # Record actual architectural nonreturn boundaries. These are
            # neither passing pixel comparisons nor ordinary input errors.
            portable_status=lib.fx_display_pair_result(r,address,C.byref(Box()))
            assert group=='byte_width_and_height_space' and portable_status==-1,(detail,error,portable_status)
            assert 'status=101' in str(error) and oracle.counts[0x3922>>1],(detail,error)
            assert ((width+96)&255)>90 and ((20+(height or 10))&255)>=63,detail
            assert bytes(memory[0x8300:0x8314])==record
            faults.append(dict(detail=detail,outcome=str(error),portable_status=portable_status,
                native_pc=oracle.lib.harness_get_pc(),native_sp=oracle.lib.harness_get_sp(),
                native_ram_sha256=hashlib.sha256(bytes(oracle.ram)).hexdigest(),
                native_ram_writes=sum(oracle.ram_writes),
                portable_frame_sha256=hashlib.sha256(bytes(memory[0x87d0:0x8950])).hexdigest()))
            return
        native_calls+=1
        status=lib.fx_display_pair_result(r,address,C.byref(Box()))
        assert status==1,(detail,'portable status',status)
        for start,length in [(0x80f0,80),(0x8300,20),(0x87d0,384),(0x9800,256),(0xf800,512),(0xf031,1)]:same(start,length,detail)
        assert bytes(memory[0x8300:0x8314])==record
        if permitted:
            expected=bytes(oracle.ram[persistent:persistent+1024]).split(b'\0')[0]
            same(persistent,max(len(expected)+1,64),detail)
        if natural or cache_used:
            for start,length in [(0x8000,6),(0x8007,4),(0x8640,memory[0x8008]*4)]:same(start,length,detail)
        oracle.call(0x3cfc);native_calls+=1
        lib.fx_flush_framebuffer(r);same(0xf800,512,detail)
        counts[group]=counts.get(group,0)+1

    zero=literal(0);one=literal(1);minus_one=literal(-1)
    sqrt2=bytes.fromhex('80000001000201010100')
    two_surds=bytes.fromhex('80020102000301020101')
    records=[literal(a)+literal(b) for a,b in [(0,0),(0,1),(3,0),(3,4),(-3,-4)]]
    records += [fraction(1,3)+sqrt2,sqrt2+fraction(1,3),two_surds+literal(2),
                literal('1.2345')+literal('-9.8765'),literal('1e-99')+literal('-1e99')]
    statuses=[value for value in range(256) if value&16]
    selections=[0,1,10,13,14,15,0x1d,0x65] if args.quick else range(256)
    for status_byte in statuses:
        for record in records[:5]:
            for mode,enabled in [(193,1),(193,0)]:
                compare('all_status_bytes_labels',record,mode=mode,enabled=enabled,status_byte=status_byte)
    for status_byte in (17,18,19,20,16,255):
        for selection in selections:
            for record in records:
                compare('all_selection_bytes_formats',record,selection,mode=193,status_byte=status_byte)
    configurations=[(mode,enabled,font,selected) for mode in (1,65,129,193,196,136)
                    for enabled in (0,1) for font in (6,7,10) for selected in (0,1)]
    if args.quick:configurations=[(193,1,10,1),(193,0,7,0),(65,1,6,1),(1,0,6,0)]
    for mode,enabled,font,selected in configurations:
        for status_byte in (17,18,19,20,16,255):
            for record in records:
                for selection in (0,1,10,13,0x65):
                    compare('display_modes_fonts_maps',record,selection,mode,enabled,font,selected,
                            height=24,editing=1,status_byte=status_byte)
    errors=[bytes([header])+bytes(9) for header in range(0xf0,0x100)]
    for status_byte in (17,18,19,20,255):
        for error in errors:
            for record in (error+one,literal(3)+error,error+error):
                for selection in (0,1,10,13,14,15,0x65):
                    compare('all_error_headers',record,selection,mode=193,status_byte=status_byte)
    for variable in range(256):
        compare('all_solve_variable_bytes',literal('1.25')+literal('-1e-8'),
                0x1d,mode=193,status_byte=19,variable=variable,screen=192)
    marked=bytearray(literal('1.2345'));marked[0]|=0x40
    for status_byte in (17,18,19,20,255):
        for record in (bytes(marked)+zero,one+bytes(marked),literal('1e7')+one,one+literal('1e7')):
            for selection in (0,1,13,0x1d,0x1e,0x65):
                compare('dms_first_previous_and_fallback',record,selection,mode=193,status_byte=status_byte)
    for numerator,denominator in [(1,3),(-1,3),(7,3)]:
        tagged=bytearray(fraction(numerator,denominator));tagged[0]|=0x40
        for status_byte in (17,18,19,20,255):
            for record in (bytes(tagged)+one,one+bytes(tagged)):
                for selection in selections:
                    compare('marked_rational_raw_dms_guard',record,selection,mode=193,status_byte=status_byte)
    for status_byte in (17,20):
        for selection in (1,0x1d):
            for real in ('1e7','9999999.99999999'):
                for decimal_dot in (0,1):
                    for display in (8,9):
                        for digits in range(256):
                            compare('all_dms_precision_bytes_ignored',literal(real)+one,selection,
                                    mode=193,status_byte=status_byte,decimal_dot=decimal_dot,
                                    display=display,digits=digits)
    for status_byte in (17,18,19,20,255):
        for record in records:
            for display,digits in [(0,0),(4,0),(8,0),(8,9),(9,0),(9,9),(255,255)]:
                for decimal_dot in (0,1,255):
                    compare('budget_precision_and_separator',record,0,mode=193,status_byte=status_byte,
                            display=display,digits=digits,decimal_dot=decimal_dot)
    for status_byte in (17,18,19,20,255):
        for selection in (0,10,13,14,15):
            for expression in (b'12\0',bytes.fromhex('aebbb831b9b833b9bc00'),b'\0',b'\0XY\0'):
                for height in (0,24):
                    compare('cache_status19_invalidation',literal(3)+literal(4),selection,
                            mode=193,height=height,cached=expression,status_byte=status_byte)
    for status_byte in (17,18,20,255):
        for address in (0,0x7fff,0xfff0):
            compare('cached_invalid_address_unread',bytes([0xff])*20,15,mode=193,
                    cached=b'12\0',address=address,status_byte=status_byte)
    for unit in (4,5,6):
        for status_byte in (17,18,19,20,255):
            polar_records=records[:5]+[literal(a)+literal(b) for a,b in [(3,-4),(-3,4),(0,-1),(-3,0)]]
            for record in polar_records:
                for override in (0,1,2):
                    compare('cmplx_polar_conversion_before_pair',record,0,mode=196,
                            polar=1,override=override,unit=unit,status_byte=status_byte)
    for state in range(256):
        for status_byte in (17,20,255):
            compare('byte_width_and_height_space',literal(3)+literal(4),10,mode=193,
                    height=state,width=state,status_byte=status_byte)
    for height in (0,1,41,42,43,44,159,160,234,235,236,237,255):
        for width in (0,1,158,159,160,161,249,250,251,252,255):
            for status_byte in (17,20,255):
                compare('byte_width_and_height_space',literal(3)+literal(4),10,mode=193,
                        height=height,width=width,status_byte=status_byte)
    for index in range(0 if args.quick else args.random_cases):
        parts=[]
        for component in range(2):
            if rng.randrange(8)==0:parts.append(zero)
            elif rng.randrange(4)==0:parts.append(rng.choice([fraction(1,3),fraction(7,3),sqrt2,two_surds]))
            else:parts.append(decimal_record(rng.randrange(10**14,10**15),rng.randrange(-99,100),rng.choice([-1,1]),0x40 if index%11==component else 0))
        compare('random_valid_components',b''.join(parts),rng.randrange(256),mode=rng.choice([65,129,193,136]),
                enabled=rng.randrange(2),selected=rng.randrange(2),unit=rng.choice([4,5,6]),
                display=rng.choice([0,4,8,9]),digits=rng.randrange(10),status_byte=rng.choice(statuses),
                decimal_dot=rng.randrange(2),variable=rng.randrange(256))
    guards=0
    for mode,font,selection,status_byte,rom_size in [
            (193,10,0,value,len(ROM)) for value in range(256) if not value&16
            ]+[(69,10,0,17,len(ROM)),(137,10,0,17,len(ROM)),
                (193,0,0,17,len(ROM)),(193,8,0,17,len(ROM)),
                (1,10,14,17,len(ROM)),(1,10,15,17,len(ROM)),
                (193,10,0,17,0x1add)]:
        C.memset(memory,0,65536)
        for location,value in [(0x80f9,mode),(0x80fc,1),(0x80ff,status_byte),
                (0x811f,font),(0x8100,selection),(0x8106,1)]:memory[location]=value
        before=bytes(memory);render.rom_size=rom_size
        assert lib.fx_display_pair_result(r,0x8300,C.byref(Box()))==-1
        assert bytes(memory)==before
        guards+=1;comparisons+=1
    render.rom_size=len(ROM)
    for address in (0,0x7fff,0xfff0):
        for status_byte in (17,19):
            C.memset(memory,0,65536)
            for location,value in [(0x80f9,193),(0x80fc,1),(0x80ff,status_byte),
                    (0x811f,10),(0x8100,0x1d),(0x8106,1),
                    (0x8130,int(status_byte==19))]:memory[location]=value
            assert lib.fx_display_pair_result(r,address,C.byref(Box()))==-1
            assert memory[0x8127]==0 and memory[0x8130]==0
            assert memory[0x8100]==(10 if status_byte==19 else 0x1d)
            guards+=1;comparisons+=1
    complete_cases=sum(counts.values())
    counts['explicit_prepared_api_guard_assertions']=guards
    report={'status':'pass','full_firmware_complete':False,'tests':counts,'total_cases':sum(counts.values()),
            'complete_b070_cases':complete_cases,
            'total_comparisons':comparisons,'native_calls':native_calls,
            'implementation':'readable high-level C; extracted ROM is constant font/table data only',
            'comparison_scope':'tokens including dormant64-byte persistent scratch,80F0..813F,source20bytes,active viewport/cache,history9800..98FF,framebuffer,all512LCDbytes before/afterflush,F031',
            'oracle_instruction_limit_per_call':20000000,
            'explicit_gaps':['numeric scratch within8000..80DB and inactive metric slots','CPU scratch flags/registers/temporary stack aliases',
                             'requested result space with wrapped height total>=63 reaches native return-frame memory; explicit-1 after prior formatting writes',
                             'equation-mode polar policies','mode137 and other nonordinary result modes'],
            'original_native_faults':faults}
    if not args.no_report:
        assert not args.quick,'A reduced suite cannot publish the canonical report'
        report=write_report('analysis/c-verification/render_pair.json',report,sources+['tools/test_complex_c.py','tools/c_build_inputs.py','tools/c_verification.py'],
                            'tools/test_render_pair_c.py')
    print(json.dumps(report,indent=2))
if __name__=='__main__':main()
