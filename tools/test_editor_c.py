#!/usr/bin/env python3
"""Original-ROM differential checks for editor policy and cursor behavior."""
import ctypes as C
import json
import random
import subprocess

from c_verification import ROOT, write_report
from nxu8.machine import Machine
from test_platform_c import Platform


def main():
    build = ROOT / 'analysis/build/editor'
    build.mkdir(parents=True, exist_ok=True)
    sources = ['csrc/ui/fx_editor.c', 'csrc/ui/fx_keys.c', 'csrc/ui/fx_natural_editor.c',
               'csrc/render/fx_render.c', 'csrc/render/fx_layout_validate.c',
               'csrc/platform/fx_platform.c', 'csrc/parse/fx_tokens.c',
               'csrc/data/fx_rom_data.c']
    output = build / 'editor.so'
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-fPIC', '-shared', *[str(ROOT / s) for s in sources],
                    '-o', str(output)], check=True)
    lib = C.CDLL(str(output))
    policies = [('fx_editor_is_special_view', 0x3876),
                ('fx_editor_has_formula_view', 0xc328),
                ('fx_editor_has_natural_input', 0xc340),
                ('fx_editor_has_natural_result', 0xc35e)]
    for name, _ in policies:
        getattr(lib, name).argtypes = [C.POINTER(Platform)]
        getattr(lib, name).restype = C.c_uint8
    for name in ('fx_editor_cursor_category', 'fx_editor_navigation_category'):
        getattr(lib, name).argtypes = [C.POINTER(Platform), C.c_uint16]
        getattr(lib, name).restype = C.c_uint8
    lib.fx_editor_refresh_cursor.argtypes = [C.POINTER(Platform)]
    lib.fx_editor_place_cursor.argtypes = [C.POINTER(Platform), C.c_uint8, C.c_uint8]
    lib.fx_editor_update_modifiers.argtypes = [C.POINTER(Platform), C.c_uint8]
    lib.fx_editor_insert_byte.argtypes = [C.POINTER(Platform), C.c_uint8]
    lib.fx_editor_text_action.argtypes = [C.POINTER(Platform), C.c_uint8]
    for name in ('fx_editor_step', 'fx_editor_resolve_position'):
        getattr(lib, name).argtypes = [C.POINTER(Platform), C.c_uint8]
        getattr(lib, name).restype = C.c_uint16
    rom = (ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    rb = (C.c_uint8 * len(rom)).from_buffer_copy(rom)
    ram = (C.c_uint8 * 65536)()
    p = Platform(rb, len(rom), ram, 0, 0)
    m = Machine(rom, build / 'oracle')
    rng = random.Random(0x11014)
    background = rng.randbytes(65536)
    counts = {}

    def restore():
        C.memmove(ram, background, len(ram))
        C.memmove(m.ram, background, len(ram))

    def set_byte(address, value):
        ram[address] = m.ram[address] = value

    def set_expression(expression):
        assert len(expression) <= 256
        for i, value in enumerate(expression): set_byte(0x8154 + i, value)
        set_byte(0x8154 + len(expression), 0)

    def equal_memory(detail):
        actual, expected = bytes(ram), bytes(m.ram)
        if actual[:0x8d00] != expected[:0x8d00] or actual[0x8dee:] != expected[0x8dee:]:
            mismatches = [(hex(i), actual[i], expected[i]) for i in range(65536)
                          if not 0x8d00 <= i < 0x8dee and actual[i] != expected[i]]
            raise AssertionError((detail, mismatches[:30]))

    # All screen/item bytes, including the ROM setup table branch.
    for mode, extra in [(1, 0), (4, 1), (255, 255)]:
        set_byte(0x80fa, mode); set_byte(0x8137, extra)
        for screen in range(256):
            set_byte(0x80fc, screen)
            for item in range(256):
                set_byte(0x80fd, item); m.call(0x3876)
                assert lib.fx_editor_is_special_view(C.byref(p)) == m.reg(0), (mode, screen, item)
    counts['special_view_all_screen_item_bytes'] = 3 * 65536
    for mode in range(256):
        for extra in (0, 1, 255):
            set_byte(0x80fa, mode); set_byte(0x8137, extra); set_byte(0x80fc, 9)
            for item in range(256):
                set_byte(0x80fd, item); m.call(0x3876)
                assert lib.fx_editor_is_special_view(C.byref(p)) == m.reg(0), (mode, extra, item)
    counts['setup_table_all_mode_item_bytes'] = 256 * 3 * 256
    for _ in range(12000):
        for address in (0x80f9, 0x80fa, 0x80fc, 0x80fd, 0x8100, 0x8106, 0x8137):
            set_byte(address, rng.randrange(256))
        for name, address in policies[1:]:
            m.call(address)
            assert getattr(lib, name)(C.byref(p)) == m.reg(0), name
    counts['formula_natural_context_policies'] = 12000 * 3
    for token in range(256):
        set_byte(0x8300, token)
        for following in range(256):
            set_byte(0x8301, following)
            for name, address in [('fx_editor_cursor_category', 0x89d2),
                                  ('fx_editor_navigation_category', 0x8a08)]:
                m.er(0, 0x8300); m.call(address)
                assert getattr(lib, name)(C.byref(p), 0x8300) == m.reg(0), (name, token, following)
    counts['cursor_categories_all_token_pairs'] = 2 * 65536
    for case in range(6000):
        restore()
        for address in (0x80f8, 0x80f9, 0x80fa, 0x80fc, 0x80fd, 0x8106, 0x8114, 0x8137):
            set_byte(address, rng.randrange(256))
        if case % 3 == 0:
            set_byte(0x80f9, 0xc1); set_byte(0x80fc, 1); set_byte(0x8106, 1)
        length = rng.randrange(256)
        set_expression(bytes(rng.randrange(1, 256) for _ in range(length)))
        assert lib.fx_editor_refresh_cursor(C.byref(p)) == 0
        m.call(0x11014); equal_memory(('refresh', case, length))
    counts['cursor_refresh_random_whole_ram'] = 6000
    for flags in range(256):
        for editing_mode in (0, 1, 255):
            for expression in (b'123', b'\xb8abc', b'\xbaabc', b'\xbbabc', b'\xbcabc'):
                restore(); set_expression(expression)
                for address, value in [(0x80f8, flags), (0x80fb, editing_mode),
                                       (0x80f9, 0xc1), (0x80fc, 1), (0x8106, 1), (0x8114, 0)]:
                    set_byte(address, value)
                assert lib.fx_editor_update_modifiers(C.byref(p), 0xec) == 0
                m.reg(0, 0xec); m.call(0x1dcf4); equal_memory(('EC', flags, editing_mode, expression))
    counts['EC_modifier_refresh_all_flags'] = 256 * 3 * 5
    for x in range(256):
        for y, font in [(0, 7), (1, 10), (31, 255), (127, 0), (128, 9), (255, 6)]:
            restore(); set_expression(b'123')
            set_byte(0x80fc, 1); set_byte(0x811f, font)
            assert lib.fx_editor_place_cursor(C.byref(p), x, y) == 0
            m.reg(0, x); m.reg(1, y); m.call(0x8182); equal_memory(('place', x, y, font))
    counts['cursor_place_coordinates_and_fonts'] = 256 * 6
    for case in range(3000):
        restore()
        expression = bytes([ord('a')] + [rng.choice([ord('a'), ord('b'), 0x21, *range(0xb8, 0xbe)]) for _ in range(254)] + [0])
        set_expression(expression)
        set_byte(0x80fc, 1); set_byte(0x80f9, 0xc1); set_byte(0x8106, case % 2)
        position = rng.randrange(256)
        for forward in (0, 1, 255):
            for name, address in [('fx_editor_step', 0xa79a), ('fx_editor_resolve_position', 0xa800)]:
                set_byte(0x8114, position)
                actual = getattr(lib, name)(C.byref(p), forward)
                m.reg(0, forward); m.call(address)
                assert actual == m.er(0), (name, case, forward, position, actual, m.er(0))
                equal_memory(('navigation', name, case, forward))
    counts['control_byte_navigation'] = 3000 * 3 * 2
    for token in range(256):
        for natural in (0, 1):
            for overwrite in (0, 128, 255):
                for expression, cursor in [(b'', 0), (b'123', 0), (b'123', 1), (b'123', 3),
                                           (b'!^12', 0), (b'^12', 0), (b'!' * 99, 50), (b'1' * 99, 50)]:
                    restore(); set_expression(expression)
                    for address, value in [(0x80fc, 1), (0x80f9, 0xc1), (0x8106, natural),
                                           (0x80f8, overwrite), (0x8114, cursor)]: set_byte(address, value)
                    assert lib.fx_editor_insert_byte(C.byref(p), token) in (0, 1)
                    m.reg(0, token); m.reg(1, 0); m.call(0xa82e)
                    equal_memory(('byte insertion', token, natural, overwrite, expression, cursor))
    counts['ordinary_byte_insertion_all_tokens'] = 256 * 2 * 3 * 8
    # Repeated edits compare whole input/cursor state after every key.
    for sequence in range(120):
        restore(); set_expression(b'')
        for address, value in [(0x80fc, 1), (0x80f9, 0xc1), (0x8106, sequence % 2),
                               (0x80f8, 0), (0x8114, 0)]: set_byte(address, value)
        for step in range(140):
            length = bytes(ram[0x8154:0x81b8]).find(b'\0')
            assert length >= 0
            cursor = rng.randrange(length + 1)
            set_byte(0x8114, cursor)
            token = rng.choice(b'0123456789+-()\x4e\x4f')
            assert lib.fx_editor_insert_byte(C.byref(p), token) in (0, 1)
            m.reg(0, token); m.reg(1, 0); m.call(0xa82e)
            equal_memory(('insertion sequence', sequence, step))
    counts['ordinary_edit_sequences'] = 120 * 140
    for case in range(6000):
        restore(); length = rng.randrange(100)
        expression = bytes(rng.randrange(1, 256) for _ in range(length))
        set_expression(expression)
        set_byte(0x8106, 0); set_byte(0x8114, rng.randrange(length + 1))
        for token in (0xe0, 0xe1, 0xe2, 0xe3, 0xfe, case % 256):
            assert lib.fx_editor_text_action(C.byref(p), token) == 0
            m.reg(0, token); m.call(0xa846)
            equal_memory(('ordinary text action', case, token))
    counts['ordinary_delete_and_cursor_actions'] = 6000 * 6
    # Bounded C behavior for a native infinite cursor-search cycle.
    restore(); set_expression(b'\xb8' * 256)
    set_byte(0x80fc, 1); set_byte(0x80f9, 0xc1); set_byte(0x8106, 1); set_byte(0x8114, 7)
    assert lib.fx_editor_step(C.byref(p), 1) == 0 and ram[0x8114] == 7
    counts['bounded_native_navigation_cycle'] = 1
    report = write_report('analysis/c-verification/editor.json', {
        'cases': sum(counts.values()), 'domains': counts,
        'comparison': 'Native returned policy/category values, cursor pointer and full RAM excluding CPU call-stack scratch8d00..8ded.',
        'scope': 'Prepared editor context policies, cursor glyph/position, EC modifier refresh, construct-control navigation, ordinary-byte insertion/overwrite with placeholder and caret rules, and legacy-text deletion/navigation. No structured wrapping, natural deletion/controller or blink event loop.',
        'bounded_behavior': 'A control-only navigation cycle returns0 rather than looping indefinitely.'},
        sources + ['csrc/ui/fx_editor.h', 'csrc/ui/fx_keys.h', 'csrc/platform/fx_platform.h',
                   'csrc/parse/fx_tokens.h', 'csrc/data/fx_rom_data.h',
                   'csrc/render/fx_render.h', 'csrc/render/fx_layout_validate.h',
                   'tools/test_platform_c.py', 'tools/c_verification.py'], 'tools/test_editor_c.py')
    print(json.dumps({k: v for k, v in report.items() if k != 'tested_inputs_sha256'}, indent=2))


if __name__ == '__main__': main()
