#!/usr/bin/env python3
"""Compare structured natural-editor edits with original A3E0/A82E behavior."""
import ctypes as C
import json
import random
import subprocess

from c_verification import ROOT, write_report
from nxu8.machine import Machine
from test_platform_c import Platform


def main():
    build = ROOT / 'analysis/build/editor-construct'
    build.mkdir(parents=True, exist_ok=True)
    sources = ['csrc/ui/fx_construct_editor.c', 'csrc/ui/fx_editor.c', 'csrc/ui/fx_keys.c', 'csrc/ui/fx_natural_editor.c',
               'csrc/platform/fx_platform.c', 'csrc/parse/fx_tokens.c',
               'csrc/render/fx_render.c', 'csrc/render/fx_layout_validate.c',
               'csrc/data/fx_rom_data.c']
    library = build / 'port.so'
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-shared', '-fPIC', *[str(ROOT / s) for s in sources], '-o', str(library)], check=True)
    lib = C.CDLL(str(library))
    lib.fx_editor_insert_construct.argtypes = [C.POINTER(Platform), C.c_uint8]
    lib.fx_editor_text_action.argtypes = [C.POINTER(Platform), C.c_uint8]
    rom = (ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    rb = (C.c_uint8 * len(rom)).from_buffer_copy(rom)
    ram = (C.c_uint8 * 65536)()
    platform = Platform(rb, len(rom), ram, 0, 0)
    native = Machine(rom, build / 'oracle')
    rng = random.Random(0xa3e0)
    background = rng.randbytes(65536)
    counts = {}

    def set_byte(address, value):
        ram[address] = native.ram[address] = value

    def restore(expression, cursor, overwrite=0, context=0xc1, math_input=1):
        C.memmove(ram, background, 65536)
        C.memmove(native.ram, background, 65536)
        for address, value in [(0x80f9, context), (0x80fa, 1), (0x80fc, 1), (0x80fd, 0),
                               (0x8106, math_input), (0x8114, cursor), (0x80f8, overwrite),
                               (0x812c, 0x54), (0x812d, 0x81)]:
            set_byte(address, value)
        for i, byte in enumerate(expression + b'\0'): set_byte(0x8154+i, byte)

    def edit(token, domain, detail, action=False):
        if action:
            status = lib.fx_editor_text_action(C.byref(platform), token)
            assert status == 0, (detail, status)
            native.reg(0, token); native.call(0xa846)
        else:
            status = lib.fx_editor_insert_construct(C.byref(platform), token)
            assert status in (0, 1), (detail, status)
            native.reg(0, token); native.reg(1, 1); native.call(0xa82e)
        actual, expected = bytes(ram), bytes(native.ram)
        if actual[:0x8d00] != expected[:0x8d00] or actual[0x8dee:] != expected[0x8dee:]:
            mismatch = [(hex(i), actual[i], expected[i]) for i in range(65536)
                        if not 0x8d00 <= i < 0x8dee and actual[i] != expected[i]]
            raise AssertionError((domain, detail, mismatch[:40]))
        counts[domain] = counts.get(domain, 0) + 1

    expressions = (b'', b'123', b'12+34', b'!^12', b'^12', b'\x98\xb82\xb9',
                   b'\xae\xbb\xb81\xb9\xb82\xb9\xbc')
    for token in range(256):
        for expression in expressions:
            for cursor in range(len(expression)+1):
                for overwrite in (0, 128):
                    restore(expression, cursor, overwrite)
                    edit(token, 'all_token_positions_and_wrapping', (token, expression.hex(), cursor, overwrite))
    constructs = [0x5e, 0x68, 0x75, 0x76, 0x77, 0x7c, 0x7d, 0x97, 0x98, 0x9f,
                  0xa0, 0xa1, 0xa2, 0xa3, 0xa8, 0xae, 0xb0, 0xb1, 0xb2]
    for length in (0, 1, 2, 85, 90, 95, 96, 97, 98, 99):
        for prefix in (b'1', b'!', b'^'):
            expression = prefix * length
            for cursor in sorted({0, length // 2, length}):
                for token in constructs:
                    for overwrite in (0, 128):
                        restore(expression, cursor, overwrite)
                        edit(token, 'capacity_boundaries', (length, prefix.hex(), cursor, token, overwrite))
    for context, math_input in [(0x88, 1), (0xc1, 0), (0x41, 1), (1, 0)]:
        for token in range(256):
            for expression, cursor in [(b'', 0), (b'123', 1), (b'!^12', 0)]:
                restore(expression, cursor, 128, context, math_input)
                edit(token, 'backup_and_linear_contexts', (context, math_input, token, expression.hex(), cursor))
    # Well-formed display-token fixtures include signed/scientific operands,
    # parentheses, nested powers, fractions and function arguments.
    atoms = [b'123', b'\x6012', b'1.25', b'1t\x602', b'(1+2)', b'\x82',
             b'\x98\xb82\xb9', b'2^\xb83\xb9', b'\xa0\xb830\xb9',
             b'\xae\xbb\xb81\xb9\xb82\xb9\xbc']
    for case in range(6000):
        expression = rng.choice(atoms) + rng.choice([b'+', b'-', b'\x4e', b'\x4f']) + rng.choice(atoms)
        cursor = rng.randrange(len(expression)+1)
        overwrite = rng.choice([0, 128])
        token = rng.choice(constructs)
        restore(expression, cursor, overwrite)
        edit(token, 'nested_expression_edits', (case, token, expression.hex(), cursor, overwrite))
    action_fixtures = [b'', b'1', b'123', b'!^\xb82\xb9', b'2^\xb8!\xb9',
                       b'\x68\xb82\xba8\xb9', b'\x69\xb81\xba2\xba3\xb9',
                       b'\x6a\xb81\xba2\xba3\xb9', b'\x6b\xb81\xba2\xb9',
                       b'\xae\xbb\xb81\xb9\xb82\xb9\xbc',
                       b'\x7c\xbd\xbb\xb81\xb9\xb82\xb9\xb83\xb9\xbc',
                       b'\xae\xbb\xb8!\xb9\xb8!\xb9\xbc',
                       b'\xa0\xb8\xae\xbb\xb81\xb9\xb82\xb9\xbc\xb9']
    actions = [0xe0, 0xe1, 0xe2, 0xe3, 0xfe]
    for expression in action_fixtures:
        for cursor in range(len(expression)+1):
            for overwrite in (0, 128):
                for token in actions:
                    restore(expression, cursor, overwrite)
                    edit(token, 'natural_delete_and_field_navigation', (expression.hex(), cursor, overwrite, token), action=True)
    for case in range(6000):
        expression = rng.choice(action_fixtures[3:]) + b'+' + rng.choice(atoms)
        cursor = rng.randrange(len(expression)+1)
        token = rng.choice(actions)
        restore(expression, cursor, rng.choice([0, 128]), rng.choice([0xc1, 0x88]))
        edit(token, 'nested_natural_actions', (case, expression.hex(), cursor, token), action=True)
    report = write_report('analysis/c-verification/editor_construct.json', {
        'cases': sum(counts.values()), 'domains': counts,
        'comparison': 'Full RAM after native structured A82E insertion and natural A846 actions, excluding CPU call-stack scratch8d00..8ded.',
        'scope': 'Natural construct templates, atom wrapping, placeholders, cursor fields, backups,99-byte capacity and nonnatural fallback; natural deletion, shell removal/argument preservation and field/left/right navigation. No complete key event loop.'},
        sources + ['csrc/ui/fx_editor.h', 'csrc/ui/fx_keys.h', 'csrc/platform/fx_platform.h',
                   'csrc/parse/fx_tokens.h', 'csrc/render/fx_render.h',
                   'csrc/render/fx_layout_validate.h', 'csrc/data/fx_rom_data.h',
                   'tools/test_platform_c.py', 'tools/c_verification.py'], 'tools/test_editor_construct_c.py')
    print(json.dumps({k: v for k, v in report.items() if k != 'tested_inputs_sha256'}, indent=2))


if __name__ == '__main__': main()
