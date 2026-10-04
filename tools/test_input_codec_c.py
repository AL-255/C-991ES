#!/usr/bin/env python3
"""Native parity for natural DISPLAY→INPUT conversion and error-cursor mapping."""
import ctypes as C
import json
import random
import subprocess

from c_verification import ROOT, write_report
from nxu8.machine import Machine
from test_platform_c import Platform


def main():
    build = ROOT / 'analysis/build/input-codec'
    build.mkdir(parents=True, exist_ok=True)
    sources = ['csrc/ui/fx_input_codec.c', 'csrc/ui/fx_editor.c', 'csrc/ui/fx_keys.c',
               'csrc/ui/fx_natural_editor.c', 'csrc/platform/fx_platform.c',
               'csrc/parse/fx_tokens.c', 'csrc/render/fx_render.c',
               'csrc/render/fx_layout_validate.c', 'csrc/data/fx_rom_data.c']
    library = build / 'port.so'
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
                    *[str(ROOT / f) for f in sources], '-o', str(library)], check=True)
    lib = C.CDLL(str(library))
    lib.fx_editor_export_input.argtypes = [C.POINTER(Platform), C.c_uint16, C.c_uint16, C.c_uint8, C.c_uint8]
    lib.fx_editor_input_boundaries.argtypes = [C.POINTER(Platform), C.c_uint16]
    rom = (ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    rb = (C.c_uint8 * len(rom)).from_buffer_copy(rom)
    ram = (C.c_uint8 * 65536)()
    platform = Platform(rb, len(rom), ram, 0, 0)
    native = Machine(rom, build / 'oracle')
    rng = random.Random(0x9ff2)
    background = rng.randbytes(65536)
    counts = {}

    def set_byte(address, value):
        ram[address] = native.ram[address] = value

    def prepare(expression, tracked=0, source=0x8200, destination=0x8400, root_match=True):
        C.memmove(ram, background, 65536); C.memmove(native.ram, background, 65536)
        for address, value in [(0x80fe, tracked), (0x80f9, 0xc1), (0x80fc, 1), (0x8106, 1),
                               (0x812c, source & 255), (0x812d, source >> 8),
                               (0x812e, destination & 255), (0x812f, destination >> 8)]:
            set_byte(address, value)
        if not root_match: set_byte(0x812e, (destination+1) & 255)
        for i, byte in enumerate(expression + b'\0\0'): set_byte((source+i) & 65535, byte)

    def compare(domain, detail):
        actual, expected = bytes(ram), bytes(native.ram)
        if actual[:0x8d00] != expected[:0x8d00] or actual[0x8dee:] != expected[0x8dee:]:
            mismatch = [(hex(i), actual[i], expected[i]) for i in range(65536)
                        if not 0x8d00 <= i < 0x8dee and actual[i] != expected[i]]
            raise AssertionError((domain, detail, mismatch[:40]))
        counts[domain] = counts.get(domain, 0) + 1

    def convert(expression, cursor=0, full=1, tracked=0, domain='templates', source=0x8200, destination=0x8400, root_match=True):
        prepare(expression, tracked, source, destination, root_match)
        status = lib.fx_editor_export_input(C.byref(platform), source, destination, cursor, full)
        assert status == 0, (expression.hex(), status)
        native.er(0, source); native.er(2, destination)
        native.ram[0x8dee] = cursor; native.ram[0x8df0] = full
        # Caller stack arguments are outside semantic RAM and remain unchanged.
        ram[0x8dee] = cursor; ram[0x8df0] = full
        native.call(0x9ff2)
        compare(domain, (expression.hex(), cursor, full, tracked, source, destination))

    fixtures = [b'', b'123', b'2^\xb83\xb9', b'\x98\xb82\xb9', b'\x63\xb82\xb9',
                b'\xae\xbb\xb812\xb9\xb8345\xb9\xbc',
                b'\xae\xbb\xb8\x98\xb82\xb9\xb9\xb83\xb9\xbc',
                b'\x9f\xbb\xb83\xb9\xb88\xb9\xbc',
                b'\x7c\xbd\xbb\xb82\xb9\xb81\xb9\xb83\xb9\xbc',
                b'\x73\xb83\xb9', b'\x93\xb83\xb9', b'\x68\xb82\xba8\xb9',
                b'\x6b\xb8X\xba1\xb9', b'\x6a\xb8X\xba1\xba5\xb9',
                b'\x69\xb8X\xba1\xba5\xb9', b'\x5d\xb8X\xba1\xba5\xb9',
                b'0.\xa4\xb83\xb9', b'(1+(2+3))', b'(1+2', b'1+2)',
                b'\xa0\xb830\xb9', b'\xb0\xb8.5\xb9', b'\xa3\xb82\xb9']
    for expression in fixtures:
        for tracked in (0, 64, 255):
            for full in (1, 255):
                for root_match in (False, True):
                    convert(expression, full=full, tracked=tracked, root_match=root_match)
            for cursor in range(256):
                convert(expression, cursor=cursor, full=0, tracked=tracked, domain='all_error_cursor_bytes')

    def tree(depth):
        if not depth or rng.randrange(4) == 0: return str(rng.randrange(10000)).encode()
        a, b = tree(depth-1), tree(depth-1)
        choice = rng.randrange(6)
        if choice == 0: return b'\x98\xb8' + a + b'\xb9'
        if choice == 1: return b'\xae\xbb\xb8' + a + b'\xb9\xb8' + b + b'\xb9\xbc'
        if choice == 2: return a + b'^\xb8' + b + b'\xb9'
        if choice == 3: return bytes([rng.choice([0xa0, 0xb0, 0xa3])]) + b'\xb8' + a + b'\xb9'
        return b'(' + a + rng.choice([b'+', b'-', b'\x4e', b'\x4f']) + b + b')'

    for case in range(6000):
        expression = tree(rng.randrange(1, 4))
        convert(expression, cursor=rng.randrange(256), full=case % 2, tracked=rng.choice([0, 64]), domain='nested_conversion')
    # Return and memory effects of9EE4, including field-boundary errors.
    invalid = [b'\x98\xb8(2\xb9', b'\x98\xb82)\xb9', b'\x98\xb81,2\xb9',
               b'\xae\xbb\xb81)\xb9\xb82\xb9\xbc', b'\x68\xb82,8\xb9',
               b'\x98\xb8\x681,2)\xb9', b'\x98\xb81:2\xb9']
    for expression in fixtures + invalid + [tree(3) for _ in range(4000)]:
        prepare(expression)
        actual = lib.fx_editor_input_boundaries(C.byref(platform), 0x8200)
        native.er(0, 0x8200); native.call(0x9ee4)
        assert actual == native.reg(0), (expression.hex(), actual, native.reg(0))
        compare('field_boundary_validation', expression.hex())

    report = write_report('analysis/c-verification/input_codec.json', {
        'cases': sum(counts.values()), 'domains': counts,
        'comparison': 'Original9FF2/9EE4 full RAM and validation return values, excluding CPU call-stack scratch8d00..8ded.',
        'scope': 'Prepared natural-token conversion for all construct families, ordinary/nested expressions, all cursor-index bytes, root metadata and parenthesis/comma field boundaries. No complete key/controller integration.'},
        sources + ['csrc/ui/fx_input_codec.h', 'csrc/ui/fx_editor.h', 'csrc/ui/fx_keys.h',
                   'csrc/platform/fx_platform.h', 'csrc/parse/fx_tokens.h', 'csrc/render/fx_render.h',
                   'csrc/render/fx_layout_validate.h', 'csrc/data/fx_rom_data.h',
                   'tools/test_platform_c.py', 'tools/c_verification.py'], 'tools/test_input_codec_c.py')
    print(json.dumps({k: v for k, v in report.items() if k != 'tested_inputs_sha256'}, indent=2))


if __name__ == '__main__': main()
