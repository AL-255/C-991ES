#!/usr/bin/env python3
"""Compare cursor bitmaps and prepared blink ticks with native firmware."""
import ctypes as C
import json
import random
import subprocess

from c_verification import ROOT, write_report
from nxu8.machine import Machine
from test_platform_c import Platform


def main():
    build = ROOT / 'analysis/build/cursor'
    build.mkdir(parents=True, exist_ok=True)
    sources = ['csrc/ui/fx_cursor.c', 'csrc/platform/fx_platform.c']
    library = build / 'port.so'
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
                    *[str(ROOT / p) for p in sources], '-o', str(library)], check=True)
    lib = C.CDLL(str(library))
    for name in ('fx_cursor_capture', 'fx_cursor_restore'):
        getattr(lib, name).argtypes = [C.POINTER(Platform), C.c_uint16, C.c_uint16]
        getattr(lib, name).restype = None
    lib.fx_cursor_tick.argtypes = [C.POINTER(Platform), C.c_uint16]
    lib.fx_cursor_tick.restype = None
    lib.fx_cursor_is_visible.argtypes = [C.POINTER(Platform)]
    lib.fx_cursor_is_visible.restype = C.c_uint8
    rom = (ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    rb = (C.c_uint8 * len(rom)).from_buffer_copy(rom)
    ram = (C.c_uint8 * 65536)()
    p = Platform(rb, len(rom), ram, 0, 0)
    native = Machine(rom, build / 'oracle')
    rng = random.Random(0x1d902)
    background = rng.randbytes(65536)
    counts = {}

    def set_byte(address, value):
        ram[address & 65535] = native.ram[address & 65535] = value

    def prepare():
        C.memmove(ram, background, 65536)
        C.memmove(native.ram, background, 65536)

    def compare(domain, detail):
        actual, expected = bytes(ram), bytes(native.ram)
        if actual[:0x8d00] != expected[:0x8d00] or actual[0x8dee:] != expected[0x8dee:]:
            mismatch = [(hex(i), actual[i], expected[i]) for i in range(65536)
                        if not 0x8d00 <= i < 0x8dee and actual[i] != expected[i]]
            raise AssertionError((domain, detail, mismatch[:30]))
        counts[domain] = counts.get(domain, 0) + 1

    for height in range(256):
        for restore in (False, True):
            prepare(); set_byte(0x811b, height)
            destination, source = (0x9400, 0x9000) if restore else (0x9000, 0x9400)
            name = 'fx_cursor_restore' if restore else 'fx_cursor_capture'
            getattr(lib, name)(C.byref(p), destination, source)
            native.er(0, destination); native.er(2, source)
            native.call(0x1da88 if restore else 0x1da46)
            compare('all_height_bytes', (height, restore))

    for case in range(2000):
        prepare()
        source = rng.choice((0x8100, 0x811a, 0x9000, 0x9400, 0xfff0, 0x7ff0))
        # Tall framebuffer reads from8100 would include native call-stack
        # scratch8D00..8DED and export it into semantic output. Keep those
        # prepared cursor cases within the original font heights; all256
        # height bytes are checked above with nonaliasing9400 rows.
        set_byte(0x811b, rng.choice((0, 6, 7, 10) if source < 0x9000 else (0, 6, 7, 10, 127, 255)))
        destination = (source + rng.choice((-2, -1, 0, 1, 2, 16, 32))) & 65535
        if case % 2:
            lib.fx_cursor_restore(C.byref(p), destination, source)
            native.er(0, destination); native.er(2, source); native.call(0x1da88)
        else:
            lib.fx_cursor_capture(C.byref(p), destination, source)
            native.er(0, destination); native.er(2, source); native.call(0x1da46)
        compare('overlap_wrap_and_dynamic_height', (case, source, destination))

    for countdown in range(256):
        for phase in (0, 1, 2, 127, 128, 255):
            for visible in (0, 1, 255):
                prepare(); set_byte(0x811b, (6, 7, 10)[countdown % 3])
                for offset, value in ((40, phase), (41, visible), (42, 0), (43, 0x95),
                                      (44, countdown ^ 0xa5), (45, countdown),
                                      (46, countdown), (47, countdown ^ 255)):
                    set_byte(0x9200+offset, value)
                lib.fx_cursor_tick(C.byref(p), 0x9200)
                native.er(0, 0x9200); native.call(0x1d902)
                compare('blink_countdown_phase_and_visibility', (countdown, phase, visible))

    for case in range(1000):
        prepare(); set_byte(0x811b, rng.choice((0, 6, 7, 10, 127, 255)))
        state = rng.choice((0x8100, 0x8110, 0x9000, 0xffd0, 0x7fe0))
        if state >= 0x8000 and state < 0xffd0:
            set_byte(state+42, 0); set_byte(state+43, 0x95)
        lib.fx_cursor_tick(C.byref(p), state)
        native.er(0, state); native.call(0x1d902)
        compare('blink_seeded_states_and_wrapping', (case, state))

    for field in (0x80dd, 0x80fb, 0x80fe):
        for value in range(256):
            prepare(); set_byte(0x80dd, 0); set_byte(0x80fb, 0); set_byte(0x80fe, 1)
            set_byte(field, value)
            result = lib.fx_cursor_is_visible(C.byref(p))
            native.call(0x1dac2)
            assert result == native.reg(0), (field, value)
            compare('eligibility_all_field_bytes', (field, value))

    report = write_report('analysis/c-verification/cursor.json', {
        'cases': sum(counts.values()), 'domains': counts,
        'comparison': 'Returned cursor gate and full RAM after native1DA46,1DA88,1D902,1DAC2; CPU call-stack scratch8D00..8DED excluded',
        'scope': 'Prepared cursor bitmap capture/restore, dynamic height, wrapping/overlap, one blink tick and visibility. Blocking key wait and physical timer scheduling remain outside this API.'},
        sources + ['csrc/ui/fx_cursor.h', 'csrc/ui/fx_keys.h', 'csrc/platform/fx_platform.h',
                   'tools/test_platform_c.py', 'tools/c_verification.py'], 'tools/test_cursor_c.py')
    print(json.dumps({key: value for key, value in report.items() if key != 'tested_inputs_sha256'}, indent=2))


if __name__ == '__main__': main()
