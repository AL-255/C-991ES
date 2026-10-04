#!/usr/bin/env python3
"""Address-based numeric classification: complete original-ROM RAM parity.

The production adapter uses decimal mathematics and explicit documented
workspace formats; only this independent oracle executes CPU instructions.
GPL-3.0-only.
"""
import argparse
import ctypes as C
import json
import random
import re
import subprocess
from c_verification import ROOT, write_report
from nxu8.machine import Machine
from test_platform_c import Platform


class Classification(C.Structure):
    _fields_ = [('continuation', C.c_uint16), ('classification', C.c_uint8)]


SOURCES = ['csrc/platform/fx_result_classify.c', 'csrc/platform/fx_platform.c',
           'csrc/numeric/fx_numeric.c']


def bcd(value):
    return value//10*16+value%10


def surd(a, r, b, c, s, d, sign):
    return bytes([0x80+r//100, bcd(r%100), bcd(a), bcd(b),
                  s//100, bcd(s%100), bcd(c), bcd(d),
                  6 if sign == 1 else 1, sign])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--random-cases', type=int, default=8192)
    args = parser.parse_args()
    build = ROOT/'analysis/build/result-classify'
    build.mkdir(parents=True, exist_ok=True)
    library = build/'classify.so'
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-pedantic', '-shared', '-fPIC', '-Wl,--no-undefined',
                    *[str(ROOT/path) for path in SOURCES], '-o', str(library)], check=True)
    lib = C.CDLL(str(library))
    lib.fx_result_classify_address.argtypes = [C.POINTER(Platform), C.c_uint16,
                                             C.c_uint16, C.POINTER(Classification)]
    lib.fx_result_classify_address.restype = C.c_int
    lib.fx_data_write.argtypes = [C.POINTER(Platform), C.c_uint8, C.c_uint16, C.c_uint8]
    lib.fx_take_callback.argtypes = [C.POINTER(Platform)]
    lib.fx_take_callback.restype = C.c_uint8
    rom = (ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    rom_data = (C.c_uint8*len(rom)).from_buffer_copy(rom)
    ram = (C.c_uint8*65536)()
    platform = Platform(rom_data, len(rom), ram, 0, 0)
    native = Machine(rom, build/'oracle')
    native.lib.memorySetData.argtypes = [C.c_uint8, C.c_uint16, C.c_size_t, C.c_uint64]
    rng = random.Random(0xccf617576)
    backgrounds = [rng.randbytes(65536), bytes(65536), bytes([255])*65536]
    counts, bounds = {}, {}
    touched = set()

    def check(group, value=None, source=0x8226, companion=0x1199, background=0, pending=0):
        native.reset()
        C.memmove(native.ram, backgrounds[background], 65536)
        if value is not None:
            for offset, byte in enumerate(value):
                native.ram[(source+offset)&65535] = byte
        C.memmove(ram, native.ram, 65536)
        platform.callback_pending = platform.status = 0
        if pending:
            lib.fx_data_write(C.byref(platform), 0, 0xf000, pending)
            native.lib.memorySetData(0, 0xf000, 1, pending)
        before = bytes(ram)
        result = Classification()
        status = lib.fx_result_classify_address(C.byref(platform), source, companion, C.byref(result))
        assert status == 0, (group, value.hex() if value else source, status)
        native.er(0, source); native.er(2, companion)
        native.call(0x1ccf6)
        actual, expected = bytes(ram), bytes(native.ram)
        assert actual[:0x8d00] == expected[:0x8d00] and actual[0x8dee:] == expected[0x8dee:], (
            group, source, value.hex() if value else source,
            [(hex(a), actual[a], expected[a]) for a in range(65536)
             if not 0x8d00 <= a < 0x8dee and actual[a] != expected[a]][:20])
        assert result.classification == native.reg(0), (group, 'classification')
        assert result.continuation == native.er(2), (group, 'continuation')
        assert lib.fx_take_callback(C.byref(platform)) == native.lib.harness_callback()
        assert platform.status == 0
        # Sources outside the documented numeric workspaces remain immutable.
        if 0x8060 <= source < 0x8637 or 0x867c <= source < 0x8cf7:
            assert actual[source:source+10] == before[source:source+10]
        if group.startswith('opposite'):
            touched.update(a for a in range(0x8000, 0x8060) if native.ram_writes[a])
            touched.update(a for a in range(0x8640, 0x867c) if native.ram_writes[a])
        counts[group] = counts.get(group, 0)+1

    # Every raw header and both admission/sign thresholds; opposite conversion
    # has its separate canonical-component domain below.
    for header in range(256):
        for first, second in [(0,0), (1,0), (3,0), (4,0), (255,0),
                              (0,1), (0,3), (0,4), (0,5), (0,255),
                              (1,1), (6,6), (255,255), (254,8)]:
            value = bytearray(rng.randbytes(10)); value[0] = header
            value[8], value[9] = first, second
            check('all_header_and_sign_thresholds', bytes(value), companion=rng.randrange(65536))
    for index in range(args.random_cases):
        value = rng.randbytes(10)
        if value[0]&0xf0 == 0x80 and value[9] and (value[8]+value[9])&255 == 7:
            continue
        check('raw_direct_records', value, companion=rng.randrange(65536), background=index%3)
    # Argument-save overlap and operand-load overlap occur before classification.
    for source in [0x7ff7, 0x7ffd, 0x8000, 0x8002, 0x8008, 0x804f,
                   0x8053, 0x8058, 0x805c, 0x805e, 0x8060,
                   0x863f, 0x8640, 0x867b, 0xf800]:
        for header in [0, 1, 0x21, 0x41, 0xf3]:
            value = bytes([header])+bytes(7)+bytes([1,1])
            check('direct_bus_source_aliases', value, source, rng.randrange(65536))
    for source in [0, 1, 0x7fff, 0xfff7, 0xfffa, 0xffff]:
        check('ROM_and_wrapping_bus_sources', source=source)
    fixtures = [(0,2,2,1,3,2), (1,0,2,1,3,2), (1,2,0,1,3,2),
                (1,2,2,0,3,2), (1,2,2,1,0,2), (1,2,2,1,3,0),
                (0,0,0,0,0,0), (1,0,1,1,0,1), (1,2,1,1,2,1),
                (2,2,1,1,2,1), (99,999,99,99,998,99),
                (1,998,99,1,997,99)]
    for index, fields in enumerate(fixtures):
        for sign in (1,6):
            check('opposite_boundary_components', surd(*fields, sign), background=index%3)
    for index in range(args.random_cases):
        fields = [rng.randrange(100), rng.randrange(1000), rng.randrange(100),
                  rng.randrange(100), rng.randrange(1000), rng.randrange(100)]
        check('opposite_random_components', surd(*fields, rng.choice((1,6))),
              source=rng.choice((0x8226,0x8408,0x814a,0x867c,0x9000)),
              companion=rng.randrange(65536), background=index%3, pending=index%256)
    # These inputs have no corresponding semantic C operation. Reject stack
    # sources before writes; unsupported surds retain only the known prefix.
    for source in [0x8cf7,0x8d00,0x8dec,0x8ded]:
        before = bytes(ram)
        assert lib.fx_result_classify_address(C.byref(platform), source, 0, C.byref(Classification())) == -1
        assert bytes(ram) == before
        bounds['CPU_stack_source'] = bounds.get('CPU_stack_source',0)+1
    for value, source in [(surd(1,2,2,1,3,2,1),0x8000),
                          (bytes.fromhex('8a020102000301020601'),0x8226),
                          (bytes.fromhex('800201020003010208ff'),0x8226)]:
        C.memmove(ram, backgrounds[0],65536)
        for offset,byte in enumerate(value): ram[source+offset]=byte
        before=bytes(ram)
        assert lib.fx_result_classify_address(C.byref(platform),source,0x1199,C.byref(Classification())) == -3
        assert bytes(ram)[0x800a:0x805c] == before[0x800a:0x805c]
        assert bytes(ram)[0x8060:] == before[0x8060:]
        bounds['unsupported_conversion_prefix'] = bounds.get('unsupported_conversion_prefix',0)+1
    assert lib.fx_result_classify_address(None,0,0,C.byref(Classification())) == -1
    assert lib.fx_result_classify_address(C.byref(platform),0,0,None) == -1
    bounds['null_arguments'] = 2
    headers, pending = set(), [ROOT/source for source in SOURCES]
    while pending:
        source = pending.pop()
        for include in re.findall(r'^#include\s+"([^"]+)"',source.read_text(),re.M):
            dependency=(source.parent/include).resolve()
            name=str(dependency.relative_to(ROOT))
            if name not in headers:
                headers.add(name); pending.append(dependency)
    report={'cases':sum(counts.values())+sum(bounds.values()),
            'native_cases':sum(counts.values()),'groups':counts,'bounds_cases':sum(bounds.values()),
            'bounds_groups':bounds,'comparison':'Complete RAM/MMIO, classification, continuation and callbacks; only native CPU-stack8D00..8DED excluded.',
            'native_workspace_addresses_observed':[f'{a:04x}' for a in sorted(touched)],
            'limits':['Canonical opposite-sign surds use BCD coefficients0..99, radicands0..999 and denominators0..99, sign pair1/6; numeric-workspace aliases and address wrap are excluded for conversion.',
                      'Raw direct-branch byte records and bus aliases are admitted; sources intersecting native CPU-stack bytes are rejected before mutation.',
                      'Mathematical workspace reconstruction compares final persistent bytes, not the arithmetic routine instruction trace or repeated intermediate store counts.']}
    report=write_report('analysis/c-verification/result_classify.json',report,
                        SOURCES+sorted(headers)+['tools/c_verification.py','tools/test_platform_c.py'],
                        'tools/test_result_classify_c.py')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
