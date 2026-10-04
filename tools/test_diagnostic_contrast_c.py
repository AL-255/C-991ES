#!/usr/bin/env python3
"""Prepared and complete-event native checks for nonblocking contrast CCF4.

Production C owns semantic values and has no CPU frame or instruction API.
Native register injection is confined to the independent test oracle.
GPL-3.0-only.
"""
import ctypes as C
import json
from pathlib import Path
import random
import subprocess

from c_verification import write_report
from nxu8.machine import Machine

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'analysis/build/diagnostic-contrast'


class Platform(C.Structure):
    _fields_ = [('rom', C.POINTER(C.c_uint8)), ('rom_size', C.c_size_t),
                ('ram', C.POINTER(C.c_uint8)), ('callback_pending', C.c_uint8),
                ('status', C.c_int)]


class Contrast(C.Structure):
    _fields_ = [(name, C.c_uint8) for name in
                ('value', 'minimum', 'maximum', 'expanded', 'active')]


def main():
    BUILD.mkdir(parents=True, exist_ok=True)
    modules = ['platform/fx_diagnostic_contrast', 'platform/fx_platform',
               'render/fx_render', 'render/fx_render_memory']
    sources = [Path('csrc') / (module + '.c') for module in modules]
    library = BUILD / 'contrast.so'
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-pedantic', '-shared', '-fPIC', '-Wl,--no-undefined',
                    *(str(ROOT / p) for p in sources), '-o', str(library)], check=True)
    lib = C.CDLL(str(library))
    pointer = C.POINTER(Platform)
    lib.fx_diagnostic_contrast_begin.argtypes = [pointer, C.POINTER(Contrast), C.c_uint8]
    lib.fx_diagnostic_contrast_step.argtypes = [pointer, C.POINTER(Contrast), C.c_uint8]
    lib.fx_diagnostic_contrast_draw_value.argtypes = [pointer, C.c_uint8]
    for name in ['begin', 'step', 'draw_value']:
        getattr(lib, 'fx_diagnostic_contrast_' + name).restype = C.c_int
    rom = (ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    rom_data = (C.c_uint8 * len(rom)).from_buffer_copy(rom)
    ram = (C.c_uint8 * 65536)()
    platform = Platform(rom_data, len(rom), ram, 0, 0)
    native = Machine(rom, BUILD / 'oracle')
    rng = random.Random(0xccf4)
    background = bytearray(rng.randbytes(65536))
    background[0x8dee:0x8e00] = rom[0x1f8dc:0x1f8ee]
    counts, bounded_counts = {}, {}
    state = Contrast()

    def prepared(value=17):
        initial = bytearray(background)
        for a, v in [(0x80f9, 0xc1), (0x80f5, 0xf0), (0x80fa, 1),
                     (0x80fb, 0), (0x80fc, 1), (0x80fd, 0), (0x80fe, 3),
                     (0x80ff, 0), (0x80dd, 1), (0x80dc, 3), (0x80f8, 0),
                     (0x80f4, 0), (0x8105, 4), (0x8106, 1), (0x810c, 0),
                     (0x8112, value), (0x811b, 10), (0x811f, 10),
                     (0x8118, 0), (0x8119, 1), (0x811a, 0x7c),
                     (0x8120, 0), (0x8121, 1), (0x8137, 0),
                     (0xf040, 0xff), (0xf032, value), (0x8e00, 0),
                     (0x8e01, 0), (0x8e02, 0)]:
            initial[a] = v
        initial[0x8140:0x8154] = bytes(20)
        initial[0x8154:0x81b8] = bytes(100)
        initial[0x812c:0x812e] = (0x8154).to_bytes(2, 'little')
        return initial

    def restore(initial):
        nonlocal state
        native.reset()
        C.memmove(native.ram, bytes(initial), 65536)
        C.memmove(ram, bytes(initial), 65536)
        platform.status = platform.callback_pending = 0
        native.lib.harness_callback()
        state = Contrast()

    def run(stop):
        status = native.lib.harness_run(1000000, stop, False)
        assert status == 100, (status, hex(stop), hex(native.lib.harness_get_pc()))

    def equal(tag):
        actual, expected = bytes(ram), bytes(native.ram)
        spans = [(0, 0x8d00), (0x8dee, 65536)]
        if any(actual[lo:hi] != expected[lo:hi] for lo, hi in spans):
            differences = [(hex(a), actual[a], expected[a])
                           for lo, hi in spans for a in range(lo, hi)
                           if actual[a] != expected[a]]
            raise AssertionError((tag, differences[:20]))
        assert platform.callback_pending == native.lib.harness_callback(), (tag, 'callback')
        group = tag.split(':')[0]
        counts[group] = counts.get(group, 0) + 1

    def begin(initial, expanded, compare=True):
        restore(initial)
        assert lib.fx_diagnostic_contrast_begin(C.byref(platform), C.byref(state), expanded) == 0
        native.reg(0, expanded)
        native.lib.harness_set_sp(0x8dee)
        native.lib.harness_set_lr(0x2fffe)
        native.lib.harness_set_pc(0xccf4)
        run(0xcd1e)
        assert state.value == native.reg(4)
        assert state.minimum == native.reg(5)
        assert state.maximum == native.reg(6)
        assert state.expanded == expanded and state.active == 1
        if compare: equal(f'begin:{expanded}/{initial[0x8112]}')

    def accept(token, tag):
        result = lib.fx_diagnostic_contrast_step(C.byref(platform), C.byref(state), token)
        native.reg(0, token)
        native.lib.harness_set_pc(0xcd24)
        run(0x2fffe if token == 0xe6 else 0xcd1e)
        assert result == (1 if token == 0xe6 else 0), tag
        assert state.active == (token != 0xe6), tag
        assert state.value == native.reg(4) or token == 0xe6, tag
        equal(tag)

    # Preserve all byte inputs, including the native character-conversion
    # quirks outside the diagnostic's ordinary contrast range0..31.
    for value in range(256):
        for selected in [0, 1, 77]:
            for composite in [0, 1, 2, 3]:
                initial = prepared(value)
                initial[0x8121] = selected; initial[0x8120] = composite
                restore(initial)
                assert lib.fx_diagnostic_contrast_draw_value(C.byref(platform), value) == 0
                native.reg(0, value); native.call(0x739e)
                equal(f'value_glyph:{value:02x}/{selected}/{composite}')
    for expanded in [0, 1]:
        for value in range(256):
            begin(prepared(value), expanded)
    # The argument is a nonzero predicate, not a Boolean-only admission rule.
    for expanded in range(256):
        begin(prepared(17), expanded)

    for expanded in [0, 1]:
        for value in [0, 4, 17, 29, 31, 255]:
            for token in range(256):
                begin(prepared(value), expanded, False)
                accept(token, f'token:{expanded}/{value}/{token:02x}')
    for expanded, value, token in [(0, 5, 0xe3), (0, 4, 0xe3),
                                    (0, 28, 0xe2), (0, 29, 0xe2),
                                    (1, 0, 0xe3), (1, 31, 0xe2)]:
        for busy in range(256):
            initial = prepared(value); initial[0x80f4] = busy
            begin(initial, expanded, False)
            accept(token, f'busy:{expanded}/{value}/{token:02x}/{busy:02x}')
    for expanded in [0, 1]:
        begin(prepared(17), expanded, False)
        for index, token in enumerate([0xe3]*25 + [0xe2]*40 + [0x31, 0xe5, 0xe6]):
            # While waiting the retained local wins over an external8112 edit.
            ram[0x8112] = native.ram[0x8112] = rng.randrange(256)
            ram[0xf032] = native.ram[0xf032] = rng.randrange(256)
            accept(token, f'sequence:{expanded}/{index}/{token:02x}')

    # These events execute the real1DB34 controller. At its return CD24,
    # copy RAM to C, leaving native-only numeric/header scratch in the initial
    # snapshot. The contrast component then compares all non-stack RAM with
    # no numeric/annunciator scratch exclusion.
    normal = {rom[0x7fe+c*8+r]: (1 << c, 1 << r)
              for c in range(8) for r in range(8)}
    for expanded in [0, 1]:
        for value in [0, 4, 17, 29, 31]:
            for token in [0xe3, 0xe2, 0xe6, 0x31]:
                begin(prepared(value), expanded, False)
                run(0x1d8d2)
                native.ram[0x8e01], native.ram[0x8e02] = normal[token]
                run(0xcd24)
                assert native.reg(0) == token
                native.ram[0x8e01] = native.ram[0x8e02] = 0
                C.memmove(ram, bytes(native.ram), 65536)
                platform.callback_pending = native.lib.harness_callback()
                accept(token, f'full_native_event:{expanded}/{value}/{token:02x}')

    def bounded(name, call):
        before = bytes(ram)
        assert call() == -1, name
        assert bytes(ram) == before and not platform.callback_pending, name
        bounded_counts[name] = bounded_counts.get(name, 0) + 1

    restore(prepared())
    bounded('inactive_state', lambda: lib.fx_diagnostic_contrast_step(C.byref(platform), C.byref(state), 0xe2))
    bounded('null_begin_state', lambda: lib.fx_diagnostic_contrast_begin(C.byref(platform), None, 1))
    bounded('null_step_state', lambda: lib.fx_diagnostic_contrast_step(C.byref(platform), None, 0xe3))
    bounded('null_begin_platform', lambda: lib.fx_diagnostic_contrast_begin(None, C.byref(state), 1))
    bounded('null_step_platform', lambda: lib.fx_diagnostic_contrast_step(None, C.byref(state), 0xe2))
    bounded('null_glyph_platform', lambda: lib.fx_diagnostic_contrast_draw_value(None, 17))

    inputs = [str(path) for path in sources]
    inputs += [str(Path('csrc') / (module + '.h')) for module in modules]
    report = {'cases': sum(counts.values()) + sum(bounded_counts.values()),
              'native_cases': sum(counts.values()),
              'bounded_domain_checks': sum(bounded_counts.values()),
              'groups': counts, 'bounded_groups': bounded_counts,
              'comparison': 'Whole RAM, including MMIO, and host callback excluding native CPU stack8d00..8ded only. Begin ends atCD1E; prepared token steps enterCD24 and end atCD1E/CD44. Complete native key-controller events copy the oracle RAM atCD24 and use the same comparison without numeric/header scratch exclusions.',
              'scope': 'CCF4 contrast menu and retained semantic state, delivered-token handler,400C/402E menu effects and739E LCD value glyphs. The parent host owns key scheduling and composition with1DB34.',
              'limitations': ['Production code does not allocate calculator RAM text/CPU-frame locals. Prepared tokens are semantic events, not register snapshots.',
                              'The contrast component does not run the ordinary key controller itself; the host composes a WAIT result with that controller.',
                              'Native glyph quirks for byte values outside0..31 are preserved; existing contrast values are not clamped.',
                              'Physical timer and interrupt scheduling remain with the host.']}
    report = write_report('analysis/c-verification/diagnostic_contrast.json', report,
                          inputs + ['tools/c_verification.py'], 'tools/test_diagnostic_contrast_c.py')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
