#!/usr/bin/env python3
"""Full persistent RAM parity for input preparation before evaluation."""
import argparse
import ctypes as C
import json
import random
import subprocess

from c_verification import ROOT, write_report
from nxu8.machine import Machine
from test_platform_c import Platform
from trace_natural_result import settings

MODULES = ['ui/fx_input_prepare', 'ui/fx_input_codec', 'ui/fx_editor', 'ui/fx_keys',
           'ui/fx_natural_editor', 'platform/fx_platform', 'parse/fx_tokens',
           'render/fx_render', 'render/fx_layout_validate', 'data/fx_rom_data']
SOURCES = ['csrc/'+module+'.c' for module in MODULES]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--random-cases', type=int, default=4000)
    parser.add_argument('--no-report', action='store_true')
    args = parser.parse_args()
    build = ROOT/'analysis/build/input-prepare'
    build.mkdir(parents=True, exist_ok=True)
    library = build/'prepare.so'
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-shared', '-fPIC', '-Wl,--no-undefined',
                    *[str(ROOT/f) for f in SOURCES], '-o', str(library)], check=True)
    lib = C.CDLL(str(library))
    pp = C.POINTER(Platform)
    for name in ('fx_input_workspace', 'fx_input_needs_export'):
        getattr(lib,name).argtypes = [pp]
    lib.fx_input_workspace.restype = C.c_uint16
    for name in ('fx_input_append_variable_suffix', 'fx_input_normalize_equation'):
        getattr(lib,name).argtypes = [pp,C.c_uint16]
    for name in ('fx_input_prepare_direct', 'fx_input_prepare_exported', 'fx_input_prepare_saved_solve'):
        getattr(lib,name).argtypes = [pp,C.POINTER(C.c_uint16)]
    rom = (ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    rb = (C.c_uint8*len(rom)).from_buffer_copy(rom)
    ram = (C.c_uint8*65536)()
    p = Platform(rb,len(rom),ram,0,0)
    native = Machine(rom,build/'oracle')
    rng = random.Random(0xe852)
    background = rng.randbytes(65536)
    counts = {}

    def record(domain): counts[domain] = counts.get(domain,0)+1
    def put(a,v): ram[a] = native.ram[a] = v
    def word(a,v): put(a,v&255);put((a+1)&65535,v>>8)
    def string(a,v):
        for i,b in enumerate(v+b'\0\0'): put((a+i)&65535,b)

    def prepare(expression=b'123', mode=0xc1, screen=1, item=0, natural=0, continuation=0,
                root=0x8154, tracked=0x8398, backup=b'41+1', saved=b'51+2'):
        native.reset();C.memmove(native.ram,background,65536);settings(native)
        C.memmove(ram,native.ram,65536)
        for a,v in ((0x80f9,mode),(0x80fc,screen),(0x80fd,item),(0x8106,natural),
                    (0x80fe,continuation),(0x8114,0),(0x80fa,1),(0x8137,0),(0x80f8,0)):
            put(a,v)
        word(0x812c,root);word(0x812e,tracked)
        string(0x8154,expression);string(0x81b8,backup);string(0x85aa,saved)
        p.callback_pending = p.status = 0

    def compare(domain,detail):
        actual,expected = bytes(ram),bytes(native.ram)
        if actual[:0x8d00] != expected[:0x8d00] or actual[0x8dee:] != expected[0x8dee:]:
            mismatch = [(hex(a),actual[a],expected[a]) for a in range(65536)
                        if not 0x8d00<=a<0x8dee and actual[a]!=expected[a]]
            raise AssertionError((domain,detail,mismatch[:40]))
        assert p.callback_pending == native.lib.harness_callback(), (domain,detail,'callback')
        p.callback_pending = 0
        record(domain)

    def source_case(mode,screen,item):
        prepare(mode=mode,screen=screen,item=item)
        a = lib.fx_input_workspace(C.byref(p));native.call(0x11072)
        assert a == native.er(0),(mode,a,native.er(0))
        compare('workspace_all_modes',(mode,screen,item))
        a = lib.fx_input_needs_export(C.byref(p));native.call(0x1e7ea)
        assert a == native.reg(0),(mode,screen,item,a,native.reg(0))
        compare('source_route_policies',(mode,screen,item))

    for mode in range(256):
        for screen,item in ((1,0),(6,1),(6,4),(0x81,2),(0x81,3),(9,0),(9,4)):
            source_case(mode,screen,item)

    for mode in (0xc1,0xc4,0x89,0x88,1):
        for screen in (1,6,0x81):
            for token in range(256):
                prepare(expression=bytes([token]),mode=mode,screen=screen)
                assert lib.fx_input_append_variable_suffix(C.byref(p),0x8154) == 0
                native.er(0,0x8154);native.call(0x1e7b8)
                compare('single_variable_suffix_all_tokens',(mode,screen,token))
    for length in (1,255,256,257,258,511,512,513,514):
        for token in (ord('X'),ord('1'),0xc8):
            prepare(mode=0xc1,screen=1)
            string(0x8500,bytes([token])+b'1'*(length-1))
            assert lib.fx_input_append_variable_suffix(C.byref(p),0x8500)==0
            native.er(0,0x8500);native.call(0x1e7b8)
            compare('suffix_low_byte_length_comparison',(length,token))

    def tree(depth):
        if not depth or rng.randrange(4)==0: return str(rng.randrange(1000)).encode()
        a,b = tree(depth-1),tree(depth-1)
        choice = rng.randrange(6)
        if choice==0: return b'\x98\xb8'+a+b'\xb9'
        if choice==1: return b'\xae\xbb\xb8'+a+b'\xb9\xb8'+b+b'\xb9\xbc'
        if choice==2: return a+b'^\xb8'+b+b'\xb9'
        if choice==3: return b'\xa0\xb8'+a+b'\xb9'
        return b'('+a+rng.choice([b'+',b'-',b'\x4e',b'\x4f'])+b+b')'

    for token in range(1,256):
        for mode,natural in ((0x89,0),(0x89,1),(0xc1,0)):
            expression = b'1'+bytes([token])+b'2'
            prepare(expression=expression,mode=mode,natural=natural)
            a = lib.fx_input_normalize_equation(C.byref(p),0x8154)
            assert a == 0
            native.er(0,0x8154);native.call(0x7fca)
            compare('equation_comparison_and_insertion',(token,mode,natural))

    entries = [('fx_input_prepare_direct',0x1e802),('fx_input_prepare_exported',0x1e852),
               ('fx_input_prepare_saved_solve',0x1e8f0)]
    def execute(entry,address,domain,detail,**kw):
        prepare(**kw)
        out = C.c_uint16(0xffff)
        result = getattr(lib,entry)(C.byref(p),C.byref(out))
        native.er(0,0x8d00);native.call(address)
        assert result == native.reg(0),(domain,detail,result,native.reg(0))
        assert out.value == native.word(0x8d00),(domain,detail,out.value,native.word(0x8d00))
        compare(domain,detail)

    fixtures = [b'',b'X',b'1',b'1+2',b'1:2',b'1=2',b'\x98\xb82\xb9',
                b'\xae\xbb\xb81\xb9\xb83\xb9\xbc',b'\x98\xb8(2\xb9',
                b'\x98\xb81,2\xb9',b'\x6a\xb8X\xba1\xba5\xb9']
    for entry,address in entries:
        for mode in (0xc1,0xc4,0x89,0x88,0x45,0x4b,0x0c,1):
            for screen,item in ((1,0),(6,1),(6,4),(0x81,2),(0x81,3)):
                for natural in (0,1):
                    for continuation in (0,0x40,0xc0):
                        for expression in fixtures:
                            execute(entry,address,'prepared_routing_matrix',
                                    (entry,mode,screen,item,natural,continuation,expression.hex()),
                                    expression=expression,mode=mode,screen=screen,item=item,
                                    natural=natural,continuation=continuation,
                                    saved=expression,backup=expression)
        for low in range(256):
            execute(entry,address,'continuation_byte_wrap',(entry,low),
                    mode=0xc1,natural=0,continuation=64,root=0x81f0,tracked=0x8300+low)
        for case in range(args.random_cases):
            expression = tree(rng.randrange(1,4))
            mode = rng.choice([0xc1,0xc4,0x89,0x88])
            execute(entry,address,'nested_natural_preparation',(entry,case,expression.hex()),
                    expression=expression,mode=mode,natural=1,
                    continuation=rng.choice([0,64]),
                    tracked=(0x8546 if mode==0x88 else 0x8398)+rng.randrange(100),
                    saved=expression,backup=expression)

    for entry,_ in entries:
        assert getattr(lib,entry)(C.byref(p),None) == -1
        record('null_host_source_guard')
    for i in range(65536): ram[i] = 1
    assert lib.fx_input_append_variable_suffix(C.byref(p),0x8200) == 0 # screen1 not selected
    ram[0x80fc] = 1
    unterminated_rom = (C.c_uint8*len(rom))(*([1]*len(rom)))
    p.rom = unterminated_rom
    assert lib.fx_input_append_variable_suffix(C.byref(p),0x8200) == -1
    p.rom = rb
    record('bounded_unterminated_source')
    report = {'cases':sum(counts.values()),'domains':counts,
              'comparison':'Original11072/E7EA/E7B8/7FCA/E802/E852/E8F0 return values, host source and full64KiB RAM/LCD/MMIO, excluding only CPU stack8D00..8DED.',
              'scope':'All256 mode/source and token predicates; direct/exported/saved-solve policies; equation comparison normalization; natural-field validation/export; continuation low-byte arithmetic and backups. No evaluator or outer event handler.'}
    if not args.no_report:
        dependencies = SOURCES[:]
        dependencies += [f for f in [s[:-2]+'.h' for s in SOURCES] if (ROOT/f).exists()]
        dependencies += ['tools/test_platform_c.py','tools/trace_natural_result.py','tools/c_verification.py']
        report = write_report('analysis/c-verification/input_prepare.json',report,dependencies,'tools/test_input_prepare_c.py')
    print(json.dumps({k:v for k,v in report.items() if k!='tested_inputs_sha256'},indent=2))


if __name__=='__main__': main()
