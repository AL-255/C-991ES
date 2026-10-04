#!/usr/bin/env python3
"""Differential tests: readable C display implementation versus actual ROM.

The C library consumes ROM font/table data but never executes ROM.  Only this
test's independently implemented nX-U8 oracle executes the original image.
"""
import ctypes as C
import hashlib
import json
import random
import subprocess
from pathlib import Path

from nxu8.machine import Machine
from c_verification import write_report

ROOT = Path(__file__).resolve().parents[1]
ROM = (ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
BUILD = ROOT / 'analysis/build/render'
REPORT = ROOT / 'csrc/render/differential-results.json'


class Render(C.Structure):
    _fields_ = [('rom', C.POINTER(C.c_uint8)), ('rom_size', C.c_size_t),
                ('memory', C.POINTER(C.c_uint8))]


class Box(C.Structure):
    _fields_ = [('width', C.c_uint16), ('height', C.c_uint8), ('depth', C.c_uint8)]


def main():
    BUILD.mkdir(parents=True, exist_ok=True)
    library_path = BUILD / 'libfx_render.so'
    subprocess.run(['gcc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-O2',
                    '-shared', '-fPIC', str(ROOT / 'csrc/render/fx_render.c'),
                    str(ROOT / 'csrc/render/fx_render_memory.c'),
                    str(ROOT / 'csrc/render/fx_render_context.c'),
                    str(ROOT / 'csrc/render/fx_layout.c'),
                    str(ROOT / 'csrc/render/fx_layout_validate.c'),
                    str(ROOT / 'csrc/render/fx_viewport.c'),
                    str(ROOT / 'csrc/render/fx_result.c'),
                    str(ROOT / 'csrc/render/fx_result_linear.c'),
                    str(ROOT / 'csrc/render/fx_result_special.c'),
                    str(ROOT / 'csrc/render/fx_result_format_state.c'),
                    str(ROOT / 'csrc/render/fx_result_inequality.c'),
                    str(ROOT / 'csrc/format/fx_format.c'),
                    str(ROOT / 'csrc/format/fx_format_base.c'),
                    str(ROOT / 'csrc/format/fx_format_budget.c'),
                    str(ROOT / 'csrc/numeric/fx_numeric.c'),
                    str(ROOT / 'csrc/numeric/fx_surd_components.c'),
                    str(ROOT / 'csrc/numeric/fx_raw_decimal_parts.c'),
                    str(ROOT / 'csrc/numeric/fx_raw_decimal_divide.c'),
                    str(ROOT / 'csrc/numeric/fx_raw_decimal_multiply_add.c'),
                    '-o', str(library_path)], check=True)
    lib = C.CDLL(str(library_path))
    ptr = C.POINTER(Render)
    byte = C.c_uint8
    word = C.c_uint16
    sbyte = C.c_int8
    lib.fx_pixel_address.argtypes = [byte, byte, sbyte, C.POINTER(byte)]
    lib.fx_pixel_address.restype = word
    lib.fx_decode_glyph.argtypes = [ptr, byte, C.POINTER(byte)]
    lib.fx_decode_glyph.restype = C.c_uint
    lib.fx_decode_glyph_to_memory.argtypes = [ptr, byte, word]
    lib.fx_composite_byte.argtypes = [byte, byte, byte, byte]
    lib.fx_composite_byte.restype = byte
    lib.fx_composite_at.argtypes = [ptr, word, byte, byte]
    lib.fx_draw_glyph.argtypes = [ptr, byte, sbyte, byte]
    lib.fx_draw_text.argtypes = [ptr, byte, sbyte, C.POINTER(word)]
    lib.fx_draw_text.restype = byte
    lib.fx_set_pixel.argtypes = [ptr, sbyte, sbyte]
    lib.fx_draw_line.argtypes = [ptr, sbyte, sbyte, sbyte, sbyte]
    lib.fx_draw_vertical.argtypes = [ptr, byte, byte, byte, byte]
    lib.fx_clear_framebuffer.argtypes = [ptr]
    lib.fx_flush_framebuffer.argtypes = [ptr]
    lib.fx_fill_display.argtypes = [ptr, byte, byte]
    for name in ('fx_clear_from_row', 'fx_scroll_previous_rows', 'fx_make_result_space'):
        getattr(lib, name).argtypes = [ptr, byte]
    for name in ('fx_display_setup_item', 'fx_display_is_special_view',
                 'fx_display_has_formula_view', 'fx_display_has_natural_input',
                 'fx_display_has_natural_result'):
        getattr(lib, name).argtypes = [ptr]
        getattr(lib, name).restype = C.c_int
    lib.fx_merge_vertical.argtypes = [C.POINTER(Box), C.POINTER(Box)]
    lib.fx_begin_layout_pass.argtypes = [ptr, byte]
    lib.fx_select_small_font.argtypes = [ptr]
    lib.fx_select_small_font.restype = byte
    lib.fx_construct_class.argtypes = [ptr, byte]
    lib.fx_construct_class.restype = byte
    lib.fx_construct_index.argtypes = [byte]
    lib.fx_construct_index.restype = byte
    for name in ['fx_font_height', 'fx_font_depth', 'fx_font_ascent']:
        getattr(lib, name).argtypes = [ptr]
        getattr(lib, name).restype = byte
    lib.fx_layout_sequence.argtypes = [ptr, word, C.POINTER(Box), word, byte]
    lib.fx_layout_sequence.restype = word
    lib.fx_render_viewport.argtypes = [ptr, C.POINTER(Box)]
    lib.fx_render_viewport.restype = C.c_int
    lib.fx_display_real_math_result.argtypes = [ptr, word, C.POINTER(Box)]
    lib.fx_display_real_math_result.restype = C.c_int
    lib.fx_display_real_linear_result.argtypes = [ptr, word, C.POINTER(Box)]
    lib.fx_display_real_linear_result.restype = C.c_int
    lib.fx_display_special_real_result.argtypes = [ptr, word, C.POINTER(Box)]
    lib.fx_display_special_real_result.restype = C.c_int
    lib.fx_display_special_real_number.argtypes = [ptr, C.POINTER(byte), C.POINTER(Box)]
    lib.fx_display_special_real_number.restype = C.c_int
    lib.fx_append_inequality_relation.argtypes = [ptr, word, byte, byte]
    lib.fx_append_inequality_relation.restype = word
    lib.fx_combine_result_kinds.argtypes = [byte, byte]
    lib.fx_combine_result_kinds.restype = byte
    lib.fx_display_equation_caption.argtypes = [ptr, word, C.POINTER(Box)]
    lib.fx_display_equation_caption.restype = C.c_int
    lib.fx_display_inequality_result.argtypes = [ptr, C.POINTER(Box)]
    lib.fx_display_inequality_result.restype = C.c_int
    for name in ('fx_construct_length', 'fx_parenthesis_length', 'fx_field_length'):
        getattr(lib, name).argtypes = [ptr, word]
        getattr(lib, name).restype = byte
    lib.fx_parameter_length.argtypes = [ptr, word, byte]
    lib.fx_parameter_length.restype = byte
    lib.fx_atom_length.argtypes = [ptr, word, byte, byte]
    lib.fx_atom_length.restype = byte
    for name in ('fx_owning_construct', 'fx_parenthesis_start'):
        getattr(lib, name).argtypes = [ptr, word, C.POINTER(byte)]
        getattr(lib, name).restype = word
    lib.fx_previous_atom_start.argtypes = [ptr, word]
    lib.fx_previous_atom_start.restype = word
    rom = (byte * len(ROM)).from_buffer_copy(ROM)
    memory = (byte * 65536)()
    render = Render(rom, len(ROM), memory)
    r = C.byref(render)
    oracle = Machine(ROM, BUILD)
    counts = {}

    def reset():
        oracle.reset()
        C.memset(memory, 0, len(memory))

    def setting(address, value):
        oracle.ram[address] = memory[address] = value

    def same_region(start, length, reason):
        original = bytes(oracle.ram[start:start + length])
        replacement = bytes(memory[start:start + length])
        if original != replacement:
            mismatch = next(n for n, (a, b) in enumerate(zip(original, replacement)) if a != b)
            raise AssertionError((reason, hex(start + mismatch),
                                  original[mismatch], replacement[mismatch]))

    reset()
    bit = byte()
    for selected in (0, 1):
        setting(0x8121, selected)
        for y in range(-128, 128):
            for x in range(256):
                oracle.reg(0, x); oracle.reg(1, y & 255); oracle.er(2, 0x8500)
                oracle.call(0x3d28)
                address = lib.fx_pixel_address(selected, x, y, C.byref(bit))
                assert address == oracle.word(0x8500), (selected, x, y)
                assert bit.value == oracle.reg(0)
    counts['address_mapping_exhaustive'] = 131072

    reset()
    rows = (byte * 9)()
    for font in (6, 7, 10):
        setting(0x811f, font)
        for character in range(256):
            oracle.reg(0, character); oracle.er(2, 0x8500); oracle.call(0x3bbc)
            height = lib.fx_decode_glyph(r, character, rows)
            assert bytes(rows[:height]) == bytes(oracle.ram[0x8500:0x8500 + height]), (font, character)
    counts['font_decoding_all_character_bytes'] = 768
    for font in (6, 7, 10):
        setting(0x811f, font)
        for destination in (0x811f, 0x8500, 0x85fb, 0x85ff, 0xfffd):
            for character in (0, 1, 12, 31, 32, 65, 124, 207, 208, 255):
                setting(0x811f, font)
                for n in range(65536):
                    if n < 16 or 0x8500 <= n < 0x8700 or n >= 0xfff0:
                        memory[n] = oracle.ram[n] = 0x5a
                oracle.reg(0, character); oracle.er(2, destination); oracle.call(0x3bbc)
                lib.fx_decode_glyph_to_memory(r, character, destination)
                for start, length in [(0, 16), (0x811f, 9), (0x8500, 0x200), (0xfff0, 16)]:
                    same_region(start, length, ('font destination wrap', font, destination, character))
    counts['font_destination_wrap_and_font_alias'] = 150

    reset()
    for mode in range(5):
        setting(0x8120, mode)
        for mask in (0, 1, 0x55, 0xaa, 0xff):
            for destination in range(256):
                for source in range(256):
                    oracle.ram[0x8800] = destination; oracle.ram[0x8500] = source
                    oracle.er(0, 0x8800); oracle.er(2, 0x8500); oracle.word(0x8dee, mask)
                    oracle.call(0x3c8e)
                    assert lib.fx_composite_byte(destination, source, mask, mode) == oracle.ram[0x8800]
    counts['byte_compositor_exhaustive'] = 1638400
    for address in (0, 0x7fff, 0x8000, 0x87db, 0x87dc, 0x8950, 0xf800, 0xffff):
        for mode in (0, 1, 2, 3, 4, 5, 255):
            setting(0x8120, mode)
            oracle.ram[address] = memory[address] = 0x5a
            oracle.ram[0x8500] = 0xc3
            oracle.er(0, address); oracle.er(2, 0x8500); oracle.word(0x8dee, 0x5f)
            oracle.call(0x3c8e)
            lib.fx_composite_at(r, address, 0xc3, 0x5f)
            same_region(address, 1, ('compositor address guard', address, mode))
    counts['compositor_address_and_default_modes'] = 56

    reset()
    for y in range(32):
        for x in range(96):
            oracle.reg(0, x); oracle.reg(1, y); oracle.call(0x3b88)
            lib.fx_set_pixel(r, x, y)
    same_region(0x87d0, 384, 'all pixels')
    for x, y in [(-1, 0), (96, 0), (0, -1), (0, 32), (127, 127), (-128, -128)]:
        oracle.reg(0, x & 255); oracle.reg(1, y & 255); oracle.call(0x3b88)
        lib.fx_set_pixel(r, x, y)
    same_region(0x87d0, 384, 'pixel bounds')
    counts['single_pixel'] = 3078

    rng = random.Random(0x3a8a)
    glyph_cases = [(selected, font, character, mode, x, y)
                   for selected in (0, 1)
                   for font, character in ((10, 65), (7, 65), (6, 208), (7, 1))
                   for mode in range(5)
                   for x in (0, 1, 7, 8, 90, 94, 95, 96, 255)
                   for y in (-128, -10, -1, 0, 1, 24, 30, 31, 32, 127)]
    glyph_cases += [(rng.randrange(2), rng.choice((6, 7, 10)), rng.randrange(256),
                    rng.randrange(256), rng.randrange(256), rng.randrange(-128, 128))
                   for _ in range(2000)]
    # In the original, control glyph y=-128 decrements the byte to +127.
    # Its first RAM write can overwrite this oracle call's stack frame,
    # preventing a normal return. This is outside the successful-call
    # differential domain and is recorded explicitly below.
    glyph_cases = [case for case in glyph_cases
                   if not (case[0] == 1 and case[1] == 7 and case[2] < 32 and case[5] == -128)]
    initial_ram = bytes(rng.randrange(256) for _ in range(0x300))
    initial_lcd = bytes(rng.randrange(256) for _ in range(0x240))
    for selected, font, character, mode, x, y in glyph_cases:
        setting(0x8121, selected); setting(0x811f, font); setting(0x8120, mode)
        for base, data in ((0x87c0, initial_ram), (0xf7f0, initial_lcd)):
            C.memmove(C.addressof(memory) + base, data, len(data))
            for n, value in enumerate(data): oracle.ram[base + n] = value
        oracle.reg(0, x); oracle.reg(1, y & 255); oracle.reg(2, character)
        oracle.call(0x3a8a)
        lib.fx_draw_glyph(r, x, y, character)
        for base, data in ((0x87c0, initial_ram), (0xf7f0, initial_lcd)):
            same_region(base, len(data), ('glyph', selected, font, character, mode, x, y))
    counts['glyph_compositing_edges_and_random'] = len(glyph_cases)

    reset()
    for font in (6, 7, 10):
        setting(0x811f, font); setting(0x8121, 1); setting(0x8120, 1)
        text = bytes(range(208, 240)) + b'\0' if font == 6 else b'12345678901234567890\0'
        for n, b in enumerate(text): oracle.ram[0x8200 + n] = memory[0x8200 + n] = b
        for x in (0, 1, 86, 90, 92, 95, 96, 255):
            oracle.ram[0x87d0:0x8950] = bytes(384)
            C.memset(C.addressof(memory) + 0x87d0, 0, 384)
            oracle.reg(0, x); oracle.reg(1, 10); oracle.er(2, 0x8200)
            oracle.call(0x3a4a)
            address = word(0x8200)
            count = lib.fx_draw_text(r, x, 10, C.byref(address))
            assert count == oracle.reg(0) and address.value == oracle.er(2)
            same_region(0x87d0, 384, ('text', font, x))
    counts['text_bounds'] = 24

    reset()
    lines = [(x0, y0, x1, y1) for x0, y0 in ((0, 0), (95, 31), (-20, -10), (127, -128))
             for x1 in (-128, -1, 0, 31, 95, 96, 127)
             for y1 in (-128, -1, 0, 31, 32, 127)]
    lines += [tuple(rng.randrange(-128, 128) for _ in range(4)) for _ in range(1000)]
    for line in lines:
        oracle.ram[0x87d0:0x8950] = bytes(384)
        C.memset(C.addressof(memory) + 0x87d0, 0, 384)
        for index, value in enumerate(line): oracle.reg(index, value & 255)
        oracle.call(0x39a8)
        lib.fx_draw_line(r, *line)
        same_region(0x87d0, 384, ('line', line))
    counts['bresenham_line_edges_and_random'] = len(lines)

    reset()
    for decoration in range(256):
        setting(0x87d0, 0)
        oracle.reg(0, 20); oracle.reg(1, 3); oracle.reg(2, 20); oracle.reg(3, decoration)
        oracle.call(0x3960)
        lib.fx_draw_vertical(r, 20, 3, 20, decoration)
        same_region(0x87d0, 384, ('vertical decoration', decoration))
    counts['vertical_decoration_all_bytes'] = 256

    reset()
    for n in range(384): oracle.ram[0x87d0 + n] = memory[0x87d0 + n] = (n * 19 + 17) & 255
    for n in range(512): oracle.ram[0xf800 + n] = memory[0xf800 + n] = 0x5a
    oracle.call(0x3cfc); lib.fx_flush_framebuffer(r)
    same_region(0xf800, 512, 'flush and untouched LCD row padding')
    oracle.call(0x3908); lib.fx_clear_framebuffer(r)
    same_region(0x87d0, 384, 'clear')
    counts['framebuffer_transfer_rows'] = 32
    counts['framebuffer_clear_bytes'] = 384

    # Seed all RAM, because malformed row arithmetic can wrap through its full
    # address space. The native stack is outside this semantic-memory boundary.
    memory_seed = bytes((n * 31 + (n >> 8) * 7 + 0x65) & 255 for n in range(65536))

    def reset_display_memory():
        reset()
        C.memmove(memory, memory_seed, len(memory_seed))
        C.memmove(oracle.ram, memory_seed, len(memory_seed))

    def same_display_memory(reason):
        for start, length in ((0x8000, 0xd80), (0x8e00, 0x7200)):
            same_region(start, length, reason)

    fill_cases = [(pattern, selection) for pattern in range(256) for selection in range(4)]
    fill_cases += [(90, selection) for selection in range(256)]
    for pattern, selection in fill_cases:
        reset_display_memory()
        oracle.er(0, pattern | (selection << 8)); oracle.call(0x38ce)
        lib.fx_fill_display(r, pattern, selection)
        same_display_memory(('display fill', pattern, selection))
    counts['display_fill_pattern_and_selection_bits'] = len(fill_cases)
    memory_faults = []
    successful_rows = {0x38b0: 0, 0x3922: 0}
    for address, function in ((0x38b0, lib.fx_clear_from_row), (0x3922, lib.fx_scroll_previous_rows)):
        for row in range(256):
            reset_display_memory(); oracle.reg(0, row)
            native_returns = row <= 32 or row >= 131 if address == 0x38b0 else row <= 31
            try:
                oracle.call(address)
            except RuntimeError as fault:
                assert not native_returns, (hex(address), row, str(fault))
                memory_faults.append({'routine': hex(address), 'row': row,
                    'native_fault': str(fault),
                    'framebuffer_sha256': hashlib.sha256(bytes(oracle.ram[0x87d0:0x8950])).hexdigest()})
            else:
                assert native_returns, (hex(address), row)
                function(r, row)
                same_display_memory(('display memory rows', hex(address), row))
                successful_rows[address] += 1
    counts['framebuffer_clear_rows_including_16bit_wrap'] = successful_rows[0x38b0]
    counts['framebuffer_scroll_rows'] = successful_rows[0x3922]
    counts['documented_original_row_stack_faults'] = len(memory_faults)
    space_cases = [(height, previous) for height in range(63) for previous in range(63)
                   if height + (previous or 10) <= 62]
    space_cases += [(255, 1), (255, 2), (250, 10), (220, 63), (200, 100)]
    for height, previous in space_cases:
        reset_display_memory(); setting(0x8128, previous)
        oracle.reg(0, height); oracle.call(0x10e5c)
        lib.fx_make_result_space(r, height)
        same_display_memory(('result vertical space', height, previous))
    counts['result_vertical_space_and_height_wrap'] = len(space_cases)

    reset()
    for token in range(256):
        oracle.reg(0, token); oracle.call(0x31e2)
        assert lib.fx_construct_class(r, token) == oracle.reg(0)
        oracle.reg(0, token); oracle.call(0x327a)
        assert lib.fx_construct_index(token) == oracle.reg(0)
    counts['construct_token_classifiers'] = 512
    reset()
    setting(0x80fc, 9)
    context_checks = 0
    for page in (0, 1):
        setting(0x8137, page)
        for mode in range(256):
            setting(0x80fa, mode)
            for item in range(256):
                setting(0x80fd, item)
                for function, address in ((lib.fx_display_setup_item, 0x5264),
                                          (lib.fx_display_is_special_view, 0x3876)):
                    oracle.call(address)
                    assert function(r) == oracle.reg(0), (hex(address), page, mode, item)
                    context_checks += 1
    setting(0x80fa, 1); setting(0x8137, 0)
    for context in range(256):
        setting(0x80fc, context)
        for item in range(256):
            setting(0x80fd, item)
            for function, address in ((lib.fx_display_is_special_view, 0x3876),
                                      (lib.fx_display_has_formula_view, 0xc328)):
                oracle.call(address)
                assert function(r) == oracle.reg(0), (hex(address), context, item)
                context_checks += 1
    setting(0x80fc, 1); setting(0x80fd, 0)
    for enabled in (0, 1):
        setting(0x8106, enabled)
        for mode in range(256):
            setting(0x80f9, mode)
            for selection in range(256):
                setting(0x8100, selection)
                for function, address in ((lib.fx_display_has_natural_input, 0xc340),
                                          (lib.fx_display_has_natural_result, 0xc35e)):
                    oracle.call(address)
                    assert function(r) == oracle.reg(0), (hex(address), enabled, mode, selection)
                    context_checks += 1
    counts['display_context_predicates_and_setup_selector'] = context_checks
    reset()
    for mode in (0, 1, 255):
        for n in (0x8007, 0x8008, 0x8009, 0x800a, 0x811f, 0x8120): setting(n, 0xa5)
        oracle.reg(0, mode); oracle.call(0xc634); lib.fx_begin_layout_pass(r, mode)
        for n in (0x8007, 0x8008, 0x8009, 0x800a, 0x811f, 0x8120): same_region(n, 1, 'pass initialization')
    for font in range(256):
        setting(0x811f, font)
        for function, address in [('fx_font_height', 0xc514), ('fx_font_depth', 0xc524), ('fx_font_ascent', 0xc534)]:
            oracle.call(address)
            assert getattr(lib, function)(r) == oracle.reg(0)
        oracle.call(0xc664)
        assert lib.fx_select_small_font(r) == oracle.reg(0)
        same_region(0x811f, 1, 'small font selection')
    counts['layout_pass_and_font_state'] = 1027
    for _ in range(10000):
        left = Box(rng.randrange(65536), rng.randrange(256), rng.randrange(256))
        right = Box(rng.randrange(65536), rng.randrange(256), rng.randrange(256))
        oracle.word(0x8500, left.width); oracle.ram[0x8502] = left.height; oracle.ram[0x8503] = left.depth
        oracle.er(0, 0x8500); oracle.word(0x8dee, right.width)
        oracle.ram[0x8df0] = right.height; oracle.ram[0x8df1] = right.depth
        oracle.call(0xc544)
        lib.fx_merge_vertical(C.byref(left), C.byref(right))
        assert bytes(left) == bytes(oracle.ram[0x8500:0x8504])
    counts['box_vertical_merge_random_including_malformed'] = 10000
    layouts = {
        'literal': b'1+2',
        'power': b'2\x5e\xb83\xb9',
        'square-root': b'\x98\xb82\xb9',
        'absolute-value': b'\x63\xb82\xb9',
        'fraction': b'\xae\xbb\xb812\xb9\xb8345\xb9\xbc',
        'nested-fraction': b'\xae\xbb\xb8\x98\xb82\xb9\xb9\xb83\xb9\xbc',
        'nth-root': b'\x9f\xbb\xb83\xb9\xb88\xb9\xbc',
        'mixed-fraction': b'\x7c\xbd\xbb\xb82\xb9\xb81\xb9\xb83\xb9\xbc',
        'e-power': b'2\x73\xb83\xb9',
        'ten-power': b'2\x93\xb83\xb9',
        'log-base': b'\x68\xb82\xba8\xb9',
        'derivative': b'\x6b\xb8X\xba1\xb9',
        'integral': b'\x6a\xb8X\xba1\xba5\xb9',
        'sum': b'\x69\xb8X\xba1\xba5\xb9',
        'product': b'\x5d\xb8X\xba1\xba5\xb9',
        'repetend': b'0.\xa4\xb83\xb9',
        'parentheses': b'(1+(2+3))',
        'tall-parentheses': b'(\xae\xbb\xb81\xb9\xb83\xb9\xbc)',
        'unmatched-parentheses': b'(1+2',
        'unmatched-close': b'1+2)',
        'function-parenthesis': b'\x60' + b'30)',
    }

    def tree(depth):
        if not depth or rng.randrange(4) == 0:
            return str(rng.randrange(1, 10000)).encode()
        choice = rng.randrange(12)
        if choice == 0: return b'\x98\xb8' + tree(depth - 1) + b'\xb9'
        if choice == 1: return b'\x63\xb8' + tree(depth - 1) + b'\xb9'
        if choice == 2: return tree(depth - 1) + b'\x5e\xb8' + tree(depth - 1) + b'\xb9'
        if choice == 3: return b'\xae\xbb\xb8' + tree(depth - 1) + b'\xb9\xb8' + tree(depth - 1) + b'\xb9\xbc'
        if choice == 4: return b'\x9f\xbb\xb8' + tree(depth - 1) + b'\xb9\xb8' + tree(depth - 1) + b'\xb9\xbc'
        if choice == 5: return tree(depth - 1) + b'+' + tree(depth - 1)
        if choice == 6: return b'\x68\xb8' + tree(depth - 1) + b'\xba' + tree(depth - 1) + b'\xb9'
        if choice == 7: return b'\x6b\xb8' + tree(depth - 1) + b'\xba' + tree(depth - 1) + b'\xb9'
        if choice in (8, 9, 10):
            token = bytes([(0x69, 0x5d, 0x6a)[choice - 8]])
            return token + b'\xb8' + tree(depth - 1) + b'\xba' + tree(depth - 1) + b'\xba' + tree(depth - 1) + b'\xb9'
        return b'0.\xa4\xb8' + str(rng.randrange(1, 10000)).encode() + b'\xb9'

    for n, whole in enumerate([b'', b'!', b'X', b'+', b'++', b'--1', b'-X', b'1+2', b'1.2',
            b'1..2', b'1t-2', b'1t2t3', b'(1+2)', b'(X)', b'(1+2', b'1+2)',
            b'\x98\xb82\xb9', b'(\x98\xb82\xb9)', b'\x602)', b'(\x602))']):
        layouts[f'mixed-whole-{n}'] = b'\x7c\xbd\xbb\xb8' + whole + b'\xb9\xb81\xb9\xb83\xb9\xbc'
    for n in range(300): layouts[f'random-{n}'] = tree(rng.randrange(1, 5))
    for name, expression in layouts.items():
        reset()
        setting(0x8121, 1); setting(0x8114, 255)
        oracle.word(0x812c, 0x8200); memory[0x812c] = 0; memory[0x812d] = 0x82
        for n, value in enumerate(expression + b'\0'): setting(0x8200 + n, value)
        for mode in (0, 1):
            oracle.reg(0, mode); oracle.call(0xc634); lib.fx_begin_layout_pass(r, mode)
            oracle.er(0, 0x8200); oracle.er(2, 0x8500)
            oracle.word(0x8dee, 2); oracle.word(0x8df0, 17)
            oracle.call(0x9cd6)
            box = Box()
            stop = lib.fx_layout_sequence(r, 0x8200, C.byref(box), 2, 17)
            assert stop == oracle.er(0), ('layout return', name, mode, expression.hex(), hex(stop), hex(oracle.er(0)))
            assert bytes(box) == bytes(oracle.ram[0x8500:0x8504]), ('layout metrics', name, mode, expression.hex(), list(bytes(box)), list(oracle.ram[0x8500:0x8504]))
            same_region(0x8640, 200, ('layout metric cache', name, mode))
            same_region(0x87d0, 384, ('layout framebuffer', name, mode, expression.hex()))
            for state in (0x8007, 0x8008, 0x811f): same_region(state, 1, ('layout state', name, mode))
    counts['recursive_layout_measure_and_draw'] = len(layouts) * 2
    cursor_cases = 0
    for name, expression in layouts.items():
        cursors = range(len(expression) + 1) if not name.startswith('random-') else sorted(set([0, len(expression)] + [rng.randrange(len(expression) + 1) for _ in range(6)]))
        for cursor in cursors:
            for overwrite in (0, 0x88):
                reset()
                setting(0x8121, 1); setting(0x80f9, 193); setting(0x8106, 1)
                setting(0x80fe, 1); setting(0x80f8, overwrite); setting(0x8114, cursor)
                oracle.word(0x812c, 0x8154); memory[0x812c] = 0x54; memory[0x812d] = 0x81
                for n, value in enumerate(expression + b'\0'): setting(0x8154 + n, value)
                for mode in (0, 1):
                    oracle.reg(0, mode); oracle.call(0xc634); lib.fx_begin_layout_pass(r, mode)
                    oracle.er(0, 0x8154); oracle.er(2, 0x8500)
                    oracle.word(0x8dee, 2); oracle.word(0x8df0, 62 if not mode else 17)
                    oracle.call(0x9cd6)
                    box = Box()
                    stop = lib.fx_layout_sequence(r, 0x8154, C.byref(box), 2, 62 if not mode else 17)
                    reason = ('cursor geometry', name, cursor, overwrite, mode)
                    assert stop == oracle.er(0), reason
                    assert bytes(box) == bytes(oracle.ram[0x8500:0x8504]), reason
                    for start, length in [(0x8002, 3), (0x800a, 1), (0x8118, 4), (0x80f8, 1)]:
                        same_region(start, length, reason)
                    same_region(0x87d0, 384, reason)
                    cursor_cases += 1
    counts['editor_cursor_geometry_and_metadata'] = cursor_cases
    setup_cursor_cases = 0
    for name, expression in list(layouts.items())[:20]:
        for setup_item in (0, 3):
            for cursor in sorted({0, len(expression) // 2, len(expression)}):
                for overwrite in (0, 0x88):
                    reset()
                    for address, value in ((0x8121, 1), (0x80f9, 193), (0x8106, 1),
                            (0x80fc, 9), (0x80fa, 1), (0x80fd, setup_item),
                            (0x80fe, 1), (0x80f8, overwrite), (0x8114, cursor)):
                        setting(address, value)
                    oracle.word(0x812c, 0x8154); memory[0x812c] = 0x54; memory[0x812d] = 0x81
                    for n, value in enumerate(expression + b'\0'): setting(0x8154 + n, value)
                    for mode in (0, 1):
                        oracle.reg(0, mode); oracle.call(0xc634); lib.fx_begin_layout_pass(r, mode)
                        oracle.er(0, 0x8154); oracle.er(2, 0x8500)
                        oracle.word(0x8dee, 2); oracle.word(0x8df0, 62 if not mode else 17)
                        oracle.call(0x9cd6)
                        box = Box()
                        stop = lib.fx_layout_sequence(r, 0x8154, C.byref(box), 2, 62 if not mode else 17)
                        reason = ('setup cursor geometry', name, setup_item, cursor, overwrite, mode)
                        assert stop == oracle.er(0), reason
                        assert bytes(box) == bytes(oracle.ram[0x8500:0x8504]), reason
                        for start, length in ((0x8002, 3), (0x800a, 1), (0x8118, 4), (0x80f8, 1)):
                            same_region(start, length, reason)
                        same_region(0x87d0, 384, reason)
                        setup_cursor_cases += 1
    counts['setup_view_cursor_layout'] = setup_cursor_cases
    span_layouts = dict(layouts)
    span_layouts.update({f'byte-{n}':bytes([n]) for n in range(256)})
    span_layouts.update({'malformed-wrap-signs': b'+' * 256 + b'1',
                         'malformed-wrap-number': b'1' * 273,
                         'malformed-wrap-exponent': b'1t-' + b'2' * 260})
    for n in range(300):
        span_layouts[f'malformed-{n}']=bytes(rng.choice(b'1234567890.t+-!()+X\x98\xb8\xb9\xba\xbb\xbc') for _ in range(rng.randrange(1,50)))
    cases=0
    for name,expression in span_layouts.items():
        for flags in (0,0x40):
            reset();setting(0x80fe,flags)
            oracle.word(0x812c,0x8200);memory[0x812c]=0;memory[0x812d]=0x82
            for n,b in enumerate(expression+b'\0'):setting(0x8200+n,b)
            for original,replacement in [(0x8b9e,'fx_construct_length'),(0x8bf8,'fx_parenthesis_length'),(0x8ae0,'fx_field_length')]:
                oracle.er(0,0x8200);oracle.call(original)
                value=getattr(lib,replacement)(r,0x8200)
                assert value==oracle.reg(0),(name,expression.hex(),hex(original),flags,value,oracle.reg(0))
                cases+=1
            for parameter in (0,1,2,3,255):
                oracle.er(0,0x8200);oracle.reg(2,parameter);oracle.call(0x8b14)
                value=lib.fx_parameter_length(r,0x8200,parameter)
                assert value==oracle.reg(0),(name,expression.hex(),'parameter',parameter,value,oracle.reg(0))
                cases+=1
            for stop in (0,1):
              for allow in (0,1):
                oracle.er(0,0x8200);oracle.reg(2,stop);oracle.reg(3,allow);oracle.call(0xa1fe)
                value=lib.fx_atom_length(r,0x8200,stop,allow)
                assert value==oracle.reg(0),(name,expression.hex(),'atom',stop,allow,value,oracle.reg(0))
                cases+=1
    reverse_cases=0
    for name,expression in span_layouts.items():
        if name.startswith('byte-') or name.startswith('malformed-'):continue
        reset()
        oracle.word(0x812c,0x8200);memory[0x812c]=0;memory[0x812d]=0x82
        for n,b in enumerate(expression+b'\0'):setting(0x8200+n,b)
        for offset in range(1,len(expression)+1):
            position=0x8200+offset
            for original,replacement in [(0xa14e,'fx_owning_construct'),(0x8a6c,'fx_parenthesis_start')]:
                oracle.er(0,position);oracle.er(2,0x8500);oracle.call(original)
                out=byte()
                value=getattr(lib,replacement)(r,position,C.byref(out))
                assert value==oracle.er(0) and out.value==oracle.ram[0x8500],(name,expression.hex(),offset,hex(original),hex(value),hex(oracle.er(0)),out.value,oracle.ram[0x8500])
                reverse_cases+=1
            oracle.er(0,position);oracle.call(0xa2da)
            value=lib.fx_previous_atom_start(r,position)
            assert value==oracle.er(0),(name,expression.hex(),offset,'previous',hex(value),hex(oracle.er(0)))
            reverse_cases+=1
    counts['display_token_reverse_spans'] = reverse_cases
    counts['display_token_forward_spans'] = cases
    viewport_cases = 0
    for name in ('square-root', 'fraction', 'nth-root', 'sum', 'integral', 'derivative', 'log-base', 'tall-parentheses'):
        expression = layouts[name]
        for x, baseline, scroll_x, scroll_y, margin in [(0, 7, 0, 0, 0), (80, 17, 0, 0, 0),
              (90, 31, 8, 0, 3), (2, 17, 8, 5, 3), (100, 40, 96, 25, 0), (20, 17, 0, 5, 30)]:
            reset()
            setting(0x8121, 1); setting(0x8114, 255)
            oracle.word(0x812c, 0x8200); memory[0x812c] = 0; memory[0x812d] = 0x82
            for n, value in enumerate(expression + b'\0'): setting(0x8200 + n, value)
            setting(0x8000, scroll_x & 255); setting(0x8001, scroll_x >> 8)
            setting(0x8005, scroll_y); setting(0x8116, margin)
            for mode in (0, 1):
                oracle.reg(0, mode); oracle.call(0xc634); lib.fx_begin_layout_pass(r, mode)
                oracle.er(0, 0x8200); oracle.er(2, 0x8500)
                oracle.word(0x8dee, x); oracle.word(0x8df0, baseline)
                oracle.call(0x9cd6)
                box = Box()
                stop = lib.fx_layout_sequence(r, 0x8200, C.byref(box), x, baseline)
                assert stop == oracle.er(0)
                assert bytes(box) == bytes(oracle.ram[0x8500:0x8504])
                same_region(0x87d0, 384, ('layout clipping and scroll', name, mode, x, baseline, scroll_x, scroll_y, margin))
                viewport_cases += 1
    counts['layout_world_coordinates_clipping_and_scroll'] = viewport_cases

    for style in range(4):
        config = bytearray(ROM); config[0x1ffe2] = style
        oracle.rom = bytes(config); rom[0x1ffe2] = style
        for digits in (b'3', b'12', b'1234567890'):
            reset()
            setting(0x8121, 1); setting(0x8114, 255)
            oracle.word(0x812c, 0x8200); memory[0x812c] = 0; memory[0x812d] = 0x82
            expression = b'0.\xa4\xb8' + digits + b'\xb9\0'
            for n, value in enumerate(expression): setting(0x8200 + n, value)
            for mode in (0, 1):
                oracle.reg(0, mode); oracle.call(0xc634); lib.fx_begin_layout_pass(r, mode)
                oracle.er(0, 0x8200); oracle.er(2, 0x8500)
                oracle.word(0x8dee, 2); oracle.word(0x8df0, 17)
                oracle.call(0x9cd6)
                box = Box()
                stop = lib.fx_layout_sequence(r, 0x8200, C.byref(box), 2, 17)
                assert stop == oracle.er(0)
                assert bytes(box) == bytes(oracle.ram[0x8500:0x8504])
                same_region(0x87d0, 384, ('repetend style', style, digits, mode))
    oracle.rom = ROM; rom[0x1ffe2] = ROM[0x1ffe2]
    counts['all_four_repetend_styles_measure_and_draw'] = 24

    native_faults = []
    for x in (3, 7):
        reset()
        setting(0x811f, 7); setting(0x8121, 1); setting(0x8120, 0)
        setting(0x8dc5, 0xa5)
        # Native PUSH ER14 replaces this byte with 0xde before the glyph's
        # spilled byte writes it. Seed that same intermediate byte in C;
        # the semantic API itself does not create a CPU stack frame.
        memory[0x8dc5] = 0xde
        oracle.reg(0, x); oracle.reg(1, 128); oracle.reg(2, 1)
        try:
            oracle.call(0x3a8a)
        except RuntimeError as fault:
            native_faults.append({'x': x, 'native_fault': str(fault),
                                  'frame_pointer_byte_after': oracle.ram[0x8dc5]})
        else:
            raise AssertionError('Expected original native stack-corruption fault')
        lib.fx_draw_glyph(r, x, -128, 1)
        assert memory[0x8dc5] == oracle.ram[0x8dc5]
    counts['documented_original_stack_corruption_faults'] = 2
    viewport_controller_cases = 0
    for expression in [layouts[name] for name in ('literal', 'fraction', 'nested-fraction', 'nth-root',
                                                  'sum', 'integral', 'derivative', 'log-base')] + [b'1234567890' * 24]:
        for selected, editing, margin, previous_height, cursor, overwrite in [
                (1, 0, 0, 0, 0, 0), (1, 0, 0, 24, 0, 0),
                (0, 1, 0, 0, 255, 0), (1, 0, 30, 0, 0, 0),
                (0, 1, 0, 0, 0, 0), (0, 1, 0, 0, 3, 0x88),
                (0, 1, 0, 0, len(expression), 0),
                (1, 1, 0, 0, len(expression), 0x88),
                (1, 0, 0, 0, (len(expression) * 6 - 80) // 8 if len(expression) > 96 else 0, 0)]:
            reset()
            setting(0x8121, 1); setting(0x80f9, 136 if margin else 193)
            setting(0x80fc, 1 if margin else 0)
            setting(0x80fe, editing); setting(0x8126, selected); setting(0x80f4, 0xff)
            setting(0x8114, cursor); setting(0x8106, 1); setting(0x80f8, overwrite)
            setting(0x8128, previous_height)
            setting(0x8004, 62)
            oracle.word(0x812c, 0x8154); memory[0x812c] = 0x54; memory[0x812d] = 0x81
            for n, value in enumerate(expression + b'\0'): setting(0x8154 + n, value)
            for n in range(384): setting(0x87d0 + n, (n * 17 + 3) & 255)
            oracle.call(0x8c56)
            box = Box()
            assert lib.fx_render_viewport(r, C.byref(box))
            assert bytes(box) == bytes(oracle.ram[0x8de4:0x8de8]), ('viewport metrics', expression.hex())
            same_region(0x87d0, 384, ('viewport controller', expression.hex(), selected, editing, margin, previous_height))
            same_region(0x8640, 200, 'viewport metric cache')
            for state in (0x8000, 0x8001, 0x8002, 0x8003, 0x8004, 0x8005, 0x8007, 0x8008, 0x8009,
                          0x800a, 0x80f4, 0x80f8, 0x8118, 0x8119, 0x811a, 0x811b, 0x8114, 0x8115, 0x8116, 0x811f, 0x8128, 0x8130):
                same_region(state, 1, ('viewport state', hex(state), selected, editing))
            viewport_controller_cases += 1
    counts['viewport_controller_8c56'] = viewport_controller_cases
    fallback_cases = 0
    failures = [b'\xb8', b'\x98\xb8' * 15 + b'2' + b'\xb9' * 15,
                b'\xae\xbb\xb8\xb8\xb9\xb8\xb8\xb9\xbc']
    for expression in failures:
        for mode, editing in [(193, 0), (65, 1), (136, 0), (0, 1)]:
            reset()
            setting(0x8121, 1); setting(0x80f9, mode); setting(0x80fe, editing)
            setting(0x8126, 1); setting(0x8006, 1); setting(0x8114, 255)
            oracle.word(0x812c, 0x8154); memory[0x812c] = 0x54; memory[0x812d] = 0x81
            for n, value in enumerate(expression + b'\0'): setting(0x8154 + n, value)
            for address in (0x8398, 0x8546):
                for n, value in enumerate(b'42\0'): setting(address + n, value)
            oracle.call(0x8c56)
            box = Box()
            assert lib.fx_render_viewport(r, C.byref(box))
            assert bytes(box) == bytes(oracle.ram[0x8de4:0x8de8])
            for start, length in [(0x8154, 3), (0x8000, 11), (0x8114, 18), (0x87d0, 384)]:
                same_region(start, length, ('viewport fallback', expression.hex(), mode, editing))
            fallback_cases += 1
    counts['viewport_fallback_copy_and_remeasure'] = fallback_cases

    fixtures = json.loads((ROOT / 'analysis/verification/numeric-samples.json').read_text())
    fixtures += [{'name': 'original-two-surds', 'numeric_record': '89970199099801990106'},
                 {'name': 'zero', 'numeric_record': '00000000000000000000'},
                 {'name': 'decimal-1.2345', 'numeric_record': '01234500000000000001'}]
    for n in range(80):
        mantissa = rng.randrange(10**14, 10**15)
        exponent = rng.choice((-95, -12, -10, -9, -5, -3, -2, -1, 0, 3, 9, 10, 12, 94))
        digits = str(mantissa)
        magnitude = abs(exponent)
        record = bytes([int(digits[0]), *[int(digits[i:i+2], 16) for i in range(1, 15, 2)],
                        magnitude // 10 * 16 + magnitude % 10,
                        int(exponent >= 0) + rng.choice((0, 5))])
        fixtures.append({'name': f'random-decimal-{n}', 'numeric_record': record.hex()})
    result_cases = 0
    for sample in fixtures:
        for selection in (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 13, 14, 0x1d, 0x65, 0x56):
            for mode, context, previous_height, editing in [(193, 0, 0, 0), (65, 0, 0, 0),
                                                           (136, 1, 0, 0), (193, 0, 24, 0),
                                                           (193, 0, 0, 1), (193, 9, 0, 0),
                                                           (193, 9, 0, 1)]:
                reset()
                setting(0x80f9, mode); setting(0x80fc, context); setting(0x80fe, editing)
                setting(0x8128, previous_height); setting(0x8106, int(not(context == 9 and selection == 14))); setting(0x8121, 1)
                if context == 9:
                    setting(0x80fa, 1); setting(0x80fd, 3)
                setting(0x8104, 1); setting(0x8100, selection); setting(0x8105, 5)
                setting(0x80f8, 0x8f); setting(0x811a, 204); setting(0x811b, 7)
                setting(0x8118, 5); setting(0x8119, 8)
                setting(0x8107, int(sample['name'] == 'mixed-numeric-fraction'))
                oracle.word(0x812c, 0x8200); memory[0x812c] = 0; memory[0x812d] = 0x82
                for n, value in enumerate(bytes.fromhex(sample['numeric_record'])): setting(0x8300 + n, value)
                for n in range(384): setting(0x87d0 + n, (n * 17 + 3) & 255)
                for n in range(512): setting(0xf800 + n, (n * 7 + 17) & 255)
                setting(0xf031, 0x5a)
                oracle.er(0, 0x8300); oracle.call(0xb070)
                box = Box()
                assert lib.fx_display_real_math_result(r, 0x8300, C.byref(box)) == 1
                address = 0x8546 if mode in (65, 136) else 0x8398
                original = bytes(oracle.ram[address:address + 256]).split(b'\0')[0]
                reason = ('real Math result controller', sample['name'], selection, mode, context, previous_height, editing)
                # Numeric operand workspaces8006 and inactive8640 slots are an
                # explicit pending RAM-parity gap, documented in the ledger.
                for start, length in [(0x8100, 1), (0x8126, 2), (0x812c, 2), (0x8130, 1),
                                      (0x8000, 6), (0x8007, 4), (0x8114, 18),
                                      (address, len(original) + 1), (0x87d0, 384),
                                      (0x8640, memory[0x8008] * 4), (0x9800, 256),
                                      (0xf800, 512), (0xf031, 1)]:
                    same_region(start, length, reason)
                oracle.call(0x3cfc); lib.fx_flush_framebuffer(r)
                same_region(0xf800, 512, reason)
                result_cases += 1
    counts['ordinary_real_result_controller_b070_and_lcd'] = result_cases
    # AFE2 starts with a do-while: empty prime/cached text still writes its
    # first NUL and may copy dormant bytes before the following terminator.
    empty_history_cases=0
    for cached in (0,1):
      for selection in (14,15,0x8f):
        for tail in (b'\0',b'\0XY\0'):
          reset()
          for address,value in [(0x80f9,193),(0x80fc,1),(0x8106,1),(0x8104,1),
                                (0x8100,selection),(0x8130,cached),(0x811f,10),(0x8121,1)]: setting(address,value)
          record=bytes.fromhex('03625402861350898400') if selection&15==15 else bytes.fromhex('00000000000000000000')
          for n,value in enumerate(record): setting(0x8300+n,value)
          for n,value in enumerate(tail): setting(0x8398+n,value)
          for n in range(256): setting(0x9800+n,(n*31+5)&255)
          oracle.word(0x812c,0x8200);memory[0x812c]=0;memory[0x812d]=0x82
          oracle.er(0,0x8300);oracle.call(0xb070)
          assert lib.fx_display_real_math_result(r,0x8300,C.byref(Box()))==1
          reason=('empty history do-while',cached,selection,tail.hex())
          for start,length in [(0x8100,64),(0x9800,256),(0x87d0,384),(0xf800,512)]:same_region(start,length,reason)
          empty_history_cases+=1
    counts['empty_natural_history_do_while_regressions'] = empty_history_cases
    linear_cases = 0
    for sample in fixtures:
        for selection in (0,1,2,3,4,5,6,7,8,9,10,11,12,13,0x1d,0x65,0x56):
          for mode, enabled, previous, editing, font in [(193,0,0,0,10),(65,0,0,0,7),(136,0,0,1,10),(1,1,24,0,10),(193,1,24,0,10),(129,0,0,0,6),(65,0,0,0,6),(193,0,0,1,7),(193,1,24,1,7)]:
            if enabled and mode != 1 and selection & 15 != 10: continue
            reset()
            setting(0x80f9, mode); setting(0x8106, enabled); setting(0x8121, 0 if font == 6 else 1)
            setting(0x80fc, 1 if mode == 136 else 0); setting(0x80fe, editing)
            if mode == 193 and font == 7:
                setting(0x80fc, 9); setting(0x80fa, 1); setting(0x80fd, 3)
            setting(0x8100, selection); setting(0x8104, 1); setting(0x8105, 5)
            setting(0x80f8, 0x8f); setting(0x811f, font)
            setting(0x811a, 204); setting(0x811b, 7); setting(0x8118, 5); setting(0x8119, 8)
            setting(0x8128, previous); setting(0x8115, 50)
            setting(0x8107, int(sample['name'] == 'mixed-numeric-fraction'))
            oracle.word(0x812c,0x8200); memory[0x812c]=0;memory[0x812d]=0x82
            for n,b in enumerate(bytes.fromhex(sample['numeric_record'])): setting(0x8300+n,b)
            for n in range(384):setting(0x87d0+n,(n*17+3)&255)
            for n in range(512):setting(0xf800+n,(n*7+17)&255)
            setting(0xf031,0x5a)
            setting(0x8130,int(not(enabled and mode != 1)))
            oracle.er(0,0x8300);oracle.call(0xb070)
            box=Box()
            assert lib.fx_display_real_linear_result(r,0x8300,C.byref(box)) == 1
            reason=('legacy real result',sample['name'],selection,mode,enabled,font,editing)
            for start,length in [(0x8100,1),(0x8114,1),(0x8115,18),(0x8130,1),(0x9800,256),(0x87d0,384),(0x812c,2),(0xf031,1)]:same_region(start,length,reason)
            if enabled and mode != 1:
                address=0x8546 if mode in (65,136) else 0x8398
                same_region(address,256,reason)
            same_region(0xf800,512,reason)
            oracle.call(0x3cfc);lib.fx_flush_framebuffer(r)
            same_region(0xf800,512,reason)
            linear_cases+=1
    counts['ordinary_real_legacy_result_controller_b070_and_lcd'] = linear_cases
    linear_cache_cases=0
    for previous_selection in range(16):
      for mode in (65,129,193,136):
        for font in (6,7,10):
          for selected in (0,1):
            for editing in (0,1):
              for expression in (b'12\0',bytes.fromhex('98b832b92b98b833b900'),b'12345678901234567890\0'):
                reset()
                for address,value in [(0x80f9,mode),(0x80fc,1),(0x8100,previous_selection*16+10),
                                      (0x8106,1),(0x811f,font),(0x8121,selected),(0x8130,1),
                                      (0x8128,24),(0x80fe,editing)]: setting(address,value)
                oracle.word(0x812c,0x8200); memory[0x812c]=0; memory[0x812d]=0x82
                persistent=0x8546 if mode in (65,136) else 0x8398
                for n,value in enumerate(expression): setting(persistent+n,value)
                for n in range(384): setting(0x87d0+n,(n*17+3)&255)
                for n in range(512): setting(0xf800+n,(n*7+17)&255)
                oracle.er(0,0x8300); oracle.call(0xb070)
                assert lib.fx_display_real_linear_result(r,0x8300,C.byref(Box()))==1
                reason=('legacy cached natural expression',previous_selection,mode,font,selected,editing,expression.hex())
                for start,length in [(0x8100,64),(persistent,len(expression)),(0x8000,6),(0x8007,4),
                                     (0x8640,memory[0x8008]*4),(0x9800,256),(0x87d0,384),(0xf800,512)]: same_region(start,length,reason)
                oracle.call(0x3cfc); lib.fx_flush_framebuffer(r); same_region(0xf800,512,reason)
                linear_cache_cases+=1
    counts['ordinary_real_legacy_cached_natural_viewport_reuse'] = linear_cache_cases
    # The special view bypasses layout and history. All selection bytes test
    # previous DMS/ENG state, and seeded LCD bytes expose formatter side effects
    # that would be hidden by the later framebuffer flush.
    special_fixtures = fixtures[:11] + [
        {'name': 'huge-DMS', 'numeric_record': '41234500000000000701'},
        {'name': 'marked-decimal', 'numeric_record': '41234500000000000001'}]
    special_cases = 0
    unsupported_special = []
    for sample in special_fixtures:
      for selection in range(256):
        for font in (6, 7, 10):
          for selected in (0, 1):
            reset()
            for address, value in [(0x80f9,193),(0x80fc,16),(0x80fe,0),(0x8106,1),
                                   (0x8104,1),(0x8100,selection),(0x811f,font),
                                   (0x8121,selected),(0x8130,1),(0xf031,0x5a)]: setting(address,value)
            for n,b in enumerate(bytes.fromhex(sample['numeric_record'])): setting(0x8300+n,b)
            for n in range(384): setting(0x87d0+n,(n*17+3)&255)
            for n in range(512): setting(0xf800+n,(n*7+17)&255)
            oracle.er(0,0x8300)
            native_outcome='returned'
            try: oracle.call(0x37bc)
            except RuntimeError as fault: native_outcome=str(fault)
            if selected:
                status=lib.fx_display_special_real_result(r,0x8300,C.byref(Box()))
            else:
                supplied=(byte*10).from_buffer_copy(bytes.fromhex(sample['numeric_record']))
                status=lib.fx_display_special_real_number(r,supplied,C.byref(Box()))
                assert bytes(supplied)==bytes.fromhex(sample['numeric_record'])
            if status!=1 or native_outcome!='returned':
                assert selection&15==15 and int(sample['numeric_record'][:2],16)&0xb0 in (0x20,0x80)
                unsupported_special.append(dict(sample=sample['name'],record=sample['numeric_record'],
                    selection=selection,font=font,selected_map=selected,
                    reason='tagged prime formatter/API boundary',portable_status=status,
                    original_outcome=native_outcome,
                    original_framebuffer_sha256=hashlib.sha256(bytes(oracle.ram[0x87d0:0x8950])).hexdigest(),
                    original_lcd_sha256=hashlib.sha256(bytes(oracle.ram[0xf800:0xfa00])).hexdigest()))
                continue
            reason=('special real result',sample['name'],selection,font,selected)
            for start,length in [(0x8100,64),(0x8300,10),(0x87d0,384),(0xf800,512),
                                 (0x9800,256),(0xf030,4)]: same_region(start,length,reason)
            special_cases += 1
    counts['special_real_result_37bc_full_selection_state_and_lcd'] = special_cases
    counts['documented_original_tagged_prime_api_boundaries'] = len(unsupported_special)
    special_error_cases=0
    for code in range(16):
      for selection in range(256):
        for mode in (1,2,75,137,193):
          for font in (6,7,10):
            reset()
            for address,value in [(0x80f9,mode),(0x80fa,15),(0x80fc,1),(0x80ff,(0,0x10,0x20)[code%3]),
                                  (0x8100,selection),(0x811f,font),(0x8121,code&1),
                                  (0x8127,code&1),(0x8130,1),(0xf031,0x5a)]: setting(address,value)
            record=bytes([0xf0+code])+bytes.fromhex('123456789012345600')
            for n,value in enumerate(record): setting(0x8300+n,value)
            for n in range(384): setting(0x87d0+n,(n*17+3)&255)
            for n in range(512): setting(0xf800+n,(n*7+17)&255)
            oracle.er(0,0x8300); oracle.call(0x37bc)
            assert lib.fx_display_special_real_result(r,0x8300,C.byref(Box()))==1
            reason=('special error',code,selection,mode,font)
            for start,length in [(0x8100,64),(0x8300,10),(0x87d0,384),(0xf800,512),(0xf030,4)]: same_region(start,length,reason)
            special_error_cases+=1
    counts['special_error_tokens_all_headers_selections_modes_fonts'] = special_error_cases
    special_clear_cases = 0
    for mode in (1,2,65,129,137,193):
      for font in (6,7,10):
        for setup in range(256) if mode == 2 else (0,):
          for selected in (0,1):
            reset()
            for address,value in [(0x80f9,mode),(0x80fa,setup),(0x8100,0xab),
                                  (0x811f,font),(0x8121,selected),(0x8130,1)]: setting(address,value)
            for n in range(384): setting(0x87d0+n,(n*17+3)&255)
            for n in range(512): setting(0xf800+n,(n*7+17)&255)
            oracle.er(0,0); oracle.call(0x37bc)
            assert lib.fx_display_special_real_result(r,0,C.byref(Box())) == 1
            reason=('special clear and BASE-N title',mode,font,setup,selected)
            for start,length in [(0x8100,64),(0x87d0,384),(0xf800,512)]: same_region(start,length,reason)
            special_clear_cases += 1
    counts['special_clear_all_base_title_settings'] = special_clear_cases
    from test_numeric_c import raw_decimal
    def integer_record(value):
        if not value: return bytes(10)
        exponent = len(str(abs(value))) - 1
        return raw_decimal(abs(value) * 10**(14-exponent), exponent, -1 if value < 0 else 1)
    base_fixtures = [dict(name='base-'+str(value),numeric_record=integer_record(value).hex())
                     for value in (-2147483648,-32768,-1,0,1,32767,32768,2147483647)]
    base_fixtures += special_fixtures
    base_cases = 0
    for sample in base_fixtures:
      for base in (1,7,9,15):
        for selection in (0,1,10,13,14,15,0x1d,0x65,0xab,0xff):
          for font in (6,7,10):
            reset()
            for address,value in [(0x80f9,2),(0x80fa,base),(0x80fc,16),(0x8100,selection),
                                  (0x811f,font),(0x8121,int(font != 6)),(0x8130,1),
                                  (0xf031,0x5a),(0x80ff,0x10)]: setting(address,value)
            for n,b in enumerate(bytes.fromhex(sample['numeric_record'])): setting(0x8300+n,b)
            for n in range(384): setting(0x87d0+n,(n*17+3)&255)
            for n in range(512): setting(0xf800+n,(n*7+17)&255)
            oracle.er(0,0x8300); oracle.call(0x37bc)
            assert lib.fx_display_special_real_result(r,0x8300,C.byref(Box())) == 1
            reason=('BASE-N special result',sample['name'],base,selection,font)
            for start,length in [(0x8100,64),(0x8300,10),(0x87d0,384),(0xf800,512),
                                 (0x9800,256),(0xf030,4)]: same_region(start,length,reason)
            base_cases += 1
    counts['base_n_special_result_37bc_full_persistent_state_and_lcd'] = base_cases

    # B60E's complete byte-valued dispatch space. The decimal setting selects
    # comma/semicolon between disconnected solution intervals.
    reset()
    for decimal_dot in (0,1):
      setting(0x8104,decimal_dot)
      for part in range(256):
        for solution in range(256):
          for n,value in enumerate(b'P\0'+bytes(30)): setting(0x8300+n,value)
          oracle.er(0,0x8300); oracle.reg(2,part); oracle.reg(3,solution); oracle.call(0xb60e)
          assert lib.fx_append_inequality_relation(r,0x8300,part,solution)==oracle.er(0)
          same_region(0x8300,32,('inequality relation',decimal_dot,part,solution))
    counts['inequality_relations_b60e_all_byte_arguments'] = 131072
    reset()
    for first in range(256):
      for second in range(256):
        oracle.reg(0,first); oracle.reg(1,second); oracle.call(0x10e34)
        assert lib.fx_combine_result_kinds(first,second)==oracle.reg(0)
    counts['combined_result_kinds_10e34_exhaustive'] = 65536

    def startup_caption_table():
        # Copy the actual startup initialized-data block,1F8BE→8DEE.
        for n,value in enumerate(ROM[0x1f8be:0x1f8d0]): setting(0x8dee+n,value)

    caption_cases=0
    for solution in range(256):
      for selected in (0,1):
        reset(); startup_caption_table()
        for address,value in [(0x8135,solution),(0x8100,0x65),(0x8130,1),(0x8121,selected)]: setting(address,value)
        for n in range(384): setting(0x87d0+n,(n*17+3)&255)
        for n in range(512): setting(0xf800+n,(n*7+17)&255)
        oracle.er(0,0x8300); oracle.call(0xb4b0)
        assert lib.fx_display_equation_caption(r,0x8300,C.byref(Box()))==1
        reason=('equation caption',solution,selected)
        for start,length in [(0x8300,40),(0x8100,64),(0x87d0,384),(0xf800,512)]: same_region(start,length,reason)
        caption_cases+=1
    counts['equation_captions_b4b0_all_selectors_both_maps'] = caption_cases

    inequality_records=[bytes.fromhex(sample['numeric_record']) for sample in fixtures[:11]]
    inequality_records += [raw_decimal(123456789012345,0,1),raw_decimal(123456789012345,-99,-1),
                           raw_decimal(123456789012345,99,1),bytes.fromhex('f0123456789012345600'),
                           bytes.fromhex('fd123456789012345600')]
    inequality_cases=0
    for solution in range(1,21):
      for selection in (0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,0x1d,0x65,0x56,0x6d,0x6e,0x1e):
        for enabled in (0,1):
          for sample_index in range(len(inequality_records)):
            reset(); startup_caption_table()
            for address,value in [(0x80f9,75),(0x80fc,1),(0x8406,solution),(0x8100,selection),
                                  (0x8106,enabled),(0x8104,1),(0x8121,1),(0xf031,0x5a)]: setting(address,value)
            oracle.word(0x812c,0x8200); memory[0x812c]=0; memory[0x812d]=0x82
            for root in range(3):
                record=inequality_records[(sample_index+root)%len(inequality_records)]
                for n,value in enumerate(record): setting(0x8410+10*root+n,value)
            for n in range(384): setting(0x87d0+n,(n*17+3)&255)
            for n in range(512): setting(0xf800+n,(n*7+17)&255)
            natural=bool(lib.fx_display_has_natural_result(r))
            oracle.call(0xb754)
            assert lib.fx_display_inequality_result(r,C.byref(Box()))==1
            reason=('inequality controller',solution,selection,enabled,sample_index)
            for start,length in [(0x8100,64),(0x8410,30),(0x87d0,384),(0xf800,512),(0xf031,1),
                                 (0x9800,256)]: same_region(start,length,reason)
            if natural and solution>2:
                length=len(bytes(oracle.ram[0x8546:0x8640]).split(b'\0')[0])+1
                same_region(0x8546,length,reason)
                if selection&15!=10:
                    for start,length in [(0x8000,6),(0x8007,4),(0x8640,memory[0x8008]*4)]: same_region(start,length,reason)
            oracle.call(0x3cfc); lib.fx_flush_framebuffer(r); same_region(0xf800,512,reason)
            inequality_cases+=1
    counts['inequality_controller_b754_all_twenty_classes_and_formatter_histories'] = inequality_cases
    cache_cases=0
    for selection in (0,10,11,13,14,15,0x65):
      for expression in (b'12\0',bytes.fromhex('98b832b92b98b833b900'),b'12345678901234567890\0'):
        reset(); startup_caption_table()
        for address,value in [(0x80f9,75),(0x80fc,1),(0x8406,17),(0x8100,selection),
                              (0x8106,1),(0x8121,1),(0x8130,1),(0x8128,24)]: setting(address,value)
        oracle.word(0x812c,0x8200); memory[0x812c]=0; memory[0x812d]=0x82
        for n,value in enumerate(expression): setting(0x8546+n,value)
        for n in range(384): setting(0x87d0+n,(n*17+3)&255)
        for n in range(512): setting(0xf800+n,(n*7+17)&255)
        oracle.call(0xb754); assert lib.fx_display_inequality_result(r,C.byref(Box()))==1
        reason=('inequality cached viewport',selection,expression.hex())
        for start,length in [(0x8100,64),(0x8546,len(expression)),(0x8000,6),(0x8007,4),
                             (0x8640,memory[0x8008]*4),(0x87d0,384),(0xf800,512)]: same_region(start,length,reason)
        cache_cases+=1
    counts['inequality_cached_natural_viewport_reuse'] = cache_cases
    result = {'status': 'passed', 'rom_sha256': hashlib.sha256(ROM).hexdigest(),
              'implementation': 'readable high-level C; ROM used only as constant data',
              'oracle': 'original ROM executed by separately implemented SimU8 CPU',
              'comparison_scope': 'semantic return values, unpacked glyph bytes, settings, and framebuffer/LCD bytes; CPU scratch registers and call-stack bytes excluded',
              'controller_comparison_scope': 'tokens, full selection/cache state and viewport settings, active metric cache slots, history record0x9800..0x98ff, framebuffer, all512 LCD bytes and formatter-triggered MMIO sleep port; unused numeric workspaces remain documented gaps (0x8006/inactive0x8640slots in the viewport branch;unused numeric bytes within0x8000..0x80DB in legacy/special branches)',
              'tests': counts, 'total_cases': sum(counts.values()),
              'original_invalid_input_faults': native_faults,
              'original_invalid_row_faults': memory_faults,
              'unsupported_special_controller_inputs': unsupported_special,
              'full_firmware_complete': False}
    sources = ['csrc/render/fx_render.c', 'csrc/render/fx_render.h', 'csrc/render/fx_render_memory.c', 'csrc/render/fx_render_memory.h', 'csrc/render/fx_render_context.c', 'csrc/render/fx_render_context.h', 'csrc/render/fx_layout.c', 'csrc/render/fx_layout_validate.c', 'csrc/render/fx_layout_validate.h',
               'csrc/render/fx_viewport.c',
               'csrc/render/fx_result.c', 'csrc/render/fx_result_linear.c', 'csrc/render/fx_result_linear.h',
               'csrc/render/fx_result_special.c', 'csrc/render/fx_result_special.h',
               'csrc/render/fx_result_format_state.c', 'csrc/render/fx_result_format_state.h',
               'csrc/render/fx_result_inequality.c', 'csrc/render/fx_result_inequality.h',
               'csrc/format/fx_format.c', 'csrc/format/fx_format.h',
               'csrc/format/fx_format_base.c', 'csrc/format/fx_format_base.h',
               'csrc/format/fx_format_budget.c', 'csrc/format/fx_format_budget.h',
               'csrc/numeric/fx_numeric.c', 'csrc/numeric/fx_numeric.h',
               'csrc/numeric/fx_surd_components.c','csrc/numeric/fx_surd_components.h','csrc/numeric/fx_raw_decimal_parts.c','csrc/numeric/fx_raw_decimal_parts.h','csrc/numeric/fx_raw_decimal_divide.c','csrc/numeric/fx_raw_decimal_divide.h','csrc/numeric/fx_raw_decimal_multiply_add.c','csrc/numeric/fx_raw_decimal_multiply_add.h',
               'analysis/verification/numeric-samples.json', 'tools/test_numeric_c.py', 'tools/c_verification.py']
    result = write_report(REPORT, result, sources, 'tools/test_render_c.py')
    write_report('analysis/c-verification/render.json', result, sources, 'tools/test_render_c.py')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
