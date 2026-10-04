#!/usr/bin/env python3
"""Compare token remapping and modifier consumption after native key lookup."""
import ctypes as C
import json
import random
import subprocess

from c_verification import ROOT, write_report
from nxu8.machine import Machine
from test_platform_c import Platform


def main():
    build = ROOT / 'analysis/build/key-dispatch'
    build.mkdir(parents=True, exist_ok=True)
    sources = ['csrc/ui/fx_key_dispatch.c', 'csrc/ui/fx_editor.c', 'csrc/ui/fx_keys.c',
               'csrc/ui/fx_natural_editor.c', 'csrc/platform/fx_platform.c',
               'csrc/parse/fx_tokens.c', 'csrc/render/fx_render.c',
               'csrc/render/fx_layout_validate.c', 'csrc/data/fx_rom_data.c']
    library = build / 'port.so'
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
                    *[str(ROOT / f) for f in sources], '-o', str(library)], check=True)
    lib = C.CDLL(str(library))
    lib.fx_key_process_token.argtypes = [C.POINTER(Platform), C.c_uint8, C.c_uint16, C.POINTER(C.c_uint8)]
    rom = (ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    rb = (C.c_uint8 * len(rom)).from_buffer_copy(rom)
    ram = (C.c_uint8 * 65536)()
    p = Platform(rb, len(rom), ram, 0, 0)
    native = Machine(rom, build / 'oracle')
    background = random.Random(0x1dc3e).randbytes(65536)
    counts = {}

    def set_byte(address, value):
        ram[address] = native.ram[address] = value

    def check(token, context, flags, domain, math_input=1, suppression=0, mode=1, state=1):
        C.memmove(ram, background, 65536)
        C.memmove(native.ram, background, 65536)
        for address, value in ((0x80f9, context), (0x80f8, flags), (0x80fa, mode),
                               (0x80fc, 1), (0x80fd, 0), (0x80fe, state), (0x80fb, 0),
                               (0x8106, math_input), (0x810c, suppression), (0x8114, 1),
                               (0x812c, 0x54), (0x812d, 0x81), (0x8137, 0)):
            set_byte(address, value)
        for i, value in enumerate(b'123\0'): set_byte(0x8154+i, value)
        # Native caller frame's action-pointer slot (-14h[FP]).
        set_byte(0x82ec, 0); set_byte(0x82ed, 0x84)
        output = C.c_uint8(0xff)
        status = lib.fx_key_process_token(C.byref(p), token, 0x8400, C.byref(output))
        native.reg(0, token); native.er(14, 0x8300)
        native.lib.harness_set_pc(0x1dc3e)
        native.lib.harness_set_sp(0x8dee)
        stop = 0x1db4c if 0xe8 <= token <= 0xec else 0x1dc94
        assert native.lib.harness_run(10000, stop, False) == 100, (token, context, flags)
        assert status == (0 if stop == 0x1db4c else 1), (token, context, flags, status)
        assert output.value == (0 if not status else native.reg(4)), (token, context, flags, output.value, native.reg(4))
        actual, expected = bytes(ram), bytes(native.ram)
        if actual[:0x8d00] != expected[:0x8d00] or actual[0x8dee:] != expected[0x8dee:]:
            mismatch = [(hex(i), actual[i], expected[i]) for i in range(65536)
                        if not 0x8d00 <= i < 0x8dee and actual[i] != expected[i]]
            raise AssertionError((domain, token, context, flags, mismatch[:30]))
        counts[domain] = counts.get(domain, 0)+1

    for context in range(256):
        for token in range(256):
            for flags in (0, 8, 15, 255):
                check(token, context, flags, 'all_tokens_and_contexts')
    for flags in range(256):
        for token in range(256):
            check(token, 0xc4, flags, 'all_modifier_bytes_in_remapping_context')
    for context in range(256):
        for math_input in (0, 1):
            for suppression in (0, 1, 255):
                for mode in (0, 2, 3, 255):
                    for state in (0, 1, 2):
                        check(0xf0, context, 0xff, 'math_input_gate', math_input, suppression, mode, state)

    assert lib.fx_key_process_token(C.byref(p), 0xe7, 0x8400, None) == -1
    report = write_report('analysis/c-verification/key_dispatch.json', {
        'cases': sum(counts.values())+1, 'domains': counts,
        'comparison': 'Bounded native1DC3E block to1DC94 token return or1DB4C modifier retry; output token and full RAM excluding CPU call-stack8D00..8DED',
        'scope': 'All token/context bytes, modifier state transitions includingEC cursor refresh, C4 remapping, E7 action/timer writes, F0 input gate and C8 context gate. Earlier blocking wait, scan and menu/controller branches are pending.'},
        sources + ['csrc/ui/fx_key_dispatch.h', 'csrc/ui/fx_editor.h', 'csrc/ui/fx_keys.h',
                   'csrc/platform/fx_platform.h', 'csrc/parse/fx_tokens.h', 'csrc/render/fx_render.h',
                   'csrc/render/fx_layout_validate.h', 'tools/test_platform_c.py', 'tools/c_verification.py'],
        'tools/test_key_dispatch_c.py')
    print(json.dumps({key: value for key, value in report.items() if key != 'tested_inputs_sha256'}, indent=2))


if __name__ == '__main__': main()
