#!/usr/bin/env python3
"""Differential token classification tests: high-level C versus original ROM."""
import ctypes as C
import hashlib
import json
from pathlib import Path
import subprocess

from nxu8.machine import Machine
from c_verification import write_report

ROOT=Path(__file__).resolve().parents[1]
BUILD=ROOT/'analysis/build/tokens'
OUT=ROOT/'analysis/c-verification'


def main():
    BUILD.mkdir(parents=True,exist_ok=True);OUT.mkdir(parents=True,exist_ok=True)
    library=BUILD/'fx_tokens.so'
    subprocess.run(['gcc','-std=c99','-O2','-Wall','-Wextra','-Werror','-fPIC','-shared',
                    str(ROOT/'csrc/parse/fx_tokens.c'),str(ROOT/'csrc/data/fx_rom_data.c'),
                    '-o',str(library)],check=True)
    lib=C.CDLL(str(library))
    class Token(C.Structure): _fields_=[('value',C.c_uint8),('kind',C.c_uint8)]
    lib.fx_decode_evaluator_token.argtypes=[C.c_uint8,C.c_uint8]
    lib.fx_decode_evaluator_token.restype=Token
    for name in ['fx_classify_display_token','fx_classify_construct_token']:
        getattr(lib,name).argtypes=[C.c_uint8];getattr(lib,name).restype=C.c_uint8
    rom=(ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    m=Machine(rom,ROOT/'analysis/build')
    cases=0
    for context in range(256):
        m.ram[0x80f9]=context
        for token in range(256):
            m.ram[0x8200]=token;m.er(14,0x8200)
            m.call(0x159d0)
            actual=lib.fx_decode_evaluator_token(token,context)
            assert (actual.value,actual.kind)==(m.reg(0),m.reg(2)),(token,context)
            assert m.er(14)==0x8201
            cases+=1
    for address,name in [(0x31e2,'fx_classify_display_token'),(0x327a,'fx_classify_construct_token')]:
        function=getattr(lib,name)
        for token in range(256):
            m.reg(0,token);m.call(address)
            assert function(token)==m.reg(0),(hex(address),token)
            cases+=1
    expected=rom+bytes(0x10000)
    embedded=(C.c_uint8*0x30000).in_dll(lib,'fx_rom_data')
    assert bytes(embedded)==expected
    report={'status':'pass','cases':cases,'rom_sha256':hashlib.sha256(rom).hexdigest(),
            'domains':{'evaluator':'all 256 input bytes times all 256 context bytes',
                       'display':'all 256 input bytes','construct':'all 256 input bytes'},
            'comparison':'Semantic function outputs and native evaluator cursor advancement; CPU flags and incidental clobbered registers are outside the C API.',
            'embedded_data_matches_original':True}
    report=write_report(OUT/'tokens.json',report,
        ['csrc/parse/fx_tokens.c','csrc/parse/fx_tokens.h','csrc/data/fx_rom_data.c',
         'csrc/data/fx_rom_data.h','tools/c_verification.py'],'tools/test_tokens_c.py')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
