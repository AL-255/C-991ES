#!/usr/bin/env python3
"""Differential boot, retained-state and emulator packet checks against ROM."""
import ctypes as C
import json
from pathlib import Path
import random
import subprocess

from c_verification import write_report
from nxu8.machine import Machine

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'analysis/build/boot'


class Platform(C.Structure):
    _fields_ = [('rom', C.POINTER(C.c_uint8)), ('rom_size', C.c_size_t),
                ('ram', C.POINTER(C.c_uint8)), ('callback_pending', C.c_uint8), ('status', C.c_int)]


def main():
    BUILD.mkdir(parents=True, exist_ok=True)
    modules = ['data/fx_rom_data', 'platform/fx_platform', 'platform/fx_boot', 'platform/fx_host_bridge',
               'ui/fx_keys', 'ui/fx_cursor', 'ui/fx_editor', 'ui/fx_natural_editor',
               'parse/fx_tokens', 'numeric/fx_numeric', 'format/fx_format',
               'format/fx_format_base', 'render/fx_render', 'render/fx_render_context',
               'render/fx_render_memory', 'render/fx_layout_validate',
               'render/fx_result_special', 'render/fx_result_format_state']
    sources = [Path('csrc') / (module + '.c') for module in modules]
    library = BUILD / 'fx_boot.so'
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC', '-Wl,--no-undefined',
                    *(str(ROOT / p) for p in sources), '-o', str(library)], check=True)
    lib = C.CDLL(str(library))
    ctxarg = C.POINTER(Platform)
    word_functions = ['fx_host_write_descriptor', 'fx_host_write_status', 'fx_host_write_text_packet']
    for name in word_functions:
        getattr(lib, name).argtypes = [ctxarg, C.c_uint16]
        getattr(lib, name).restype = C.c_int if name.endswith('text_packet') else None
    noarg_functions = ['fx_host_write_framebuffer', 'fx_boot_write_signature',
                       'fx_boot_retained_state_invalid', 'fx_boot_clear_expression',
                       'fx_boot_clear_exported_input', 'fx_boot_clear_result_workspaces',
                       'fx_boot_reset_settings', 'fx_boot_cold_reset', 'fx_boot_default_screen',
                       'fx_boot_probe_welcome_key', 'fx_boot_initialize', 'fx_boot_resume',
                       'fx_boot_prepare_power_off', 'fx_boot_reset']
    for name in noarg_functions:
        getattr(lib, name).argtypes = [ctxarg]
        getattr(lib, name).restype = C.c_int
    lib.fx_boot_initialize_editor.argtypes = [ctxarg, C.c_uint8]
    lib.fx_boot_initialize_editor.restype = C.c_int
    rom = (ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    rom_bytes = (C.c_uint8 * len(rom)).from_buffer_copy(rom)
    ram = (C.c_uint8 * 65536)()
    ctx = Platform(rom_bytes, len(rom), ram, 0, 0)
    native = Machine(rom, ROOT / 'analysis/build')
    rng = random.Random(0xb007991)
    background = bytearray(rng.randbytes(65536))
    # The startup pointer table is data belonging to the calling context.
    for n in range(0x12):
        background[0x8dee+n] = rom[0x1f8dc+n]
    counts = {}

    def restore(initial=None):
        data = background if initial is None else initial
        C.memmove(ram, bytes(data), 65536)
        C.memmove(native.ram, bytes(data), 65536)
        ctx.callback_pending = 0
        native.lib.harness_callback()

    def equal(tag, numeric_workspace=False):
        actual, expected = bytes(ram), bytes(native.ram)
        exclusions = [(0x8d00, 0x8dee)]
        if numeric_workspace:
            exclusions += [(0x8000, 0x80dc)]
        comparable = [(0, 0x8d00), (0x8dee, 65536)]
        if numeric_workspace: comparable[0:1] = [(0, 0x8000), (0x80dc, 0x8d00)]
        if any(actual[lo:hi] != expected[lo:hi] for lo, hi in comparable):
            mismatch = [n for n in range(65536) if actual[n] != expected[n]
                        and not any(lo <= n < hi for lo, hi in exclusions)]
            raise AssertionError((tag, [(hex(n), actual[n], expected[n]) for n in mismatch[:12]]))
        assert ctx.callback_pending == native.lib.harness_callback(), (tag, 'callback value')
        counts[tag.split(':')[0]] = counts.get(tag.split(':')[0], 0) + 1

    def settings_initial():
        initial = bytearray(background)
        initial[0x80f9] = 0xc1
        initial[0x80fa] = 1
        initial[0x80dd] = 0
        initial[0x80fc] = 1
        initial[0x80fe] = 1
        initial[0x80fb] = 0
        initial[0x80f8] = 0
        initial[0x8102:0x810f] = rom[0x1ffd0:0x1ffdd]
        initial[0x8112] = 17
        initial[0x811f] = 10
        initial[0x8120] = 0
        initial[0x8121] = 1
        initial[0x8154:0x81b8] = bytes(100)
        initial[0x80dc] = 3
        initial[0x860e:0x861d] = bytes(range(15, 0, -1))
        for index in range(10):
            initial[0x8226+10*index:0x8230+10*index] = bytes(10)
        initial[0xf040] = 255
        return initial

    for destination in [0x8000, 0x8154, 0x8400, 0x8e00, 0xf000, 0xfff0]:
        restore()
        lib.fx_host_write_descriptor(C.byref(ctx), destination)
        native.er(0, destination)
        native.call(0x792c)
        equal(f'descriptor:{destination:04x}')

    status_fields = [0x80dd, 0x80fb, 0x80fe, 0x80f8, 0x8105, 0x8118, 0x8119, 0x811a, 0x811b]
    initial = settings_initial()
    for field in status_fields:
        for value in range(256):
            restore(initial)
            ram[field] = native.ram[field] = value
            lib.fx_host_write_status(C.byref(ctx), 0x9804)
            native.er(0, 0x9804)
            native.call(0x796e)
            equal(f'status:{field:04x}/{value:02x}')
    for index in range(200):
        initial = settings_initial()
        initial[0xf800:0xfa00] = rng.randbytes(512)
        restore(initial)
        lib.fx_host_write_framebuffer(C.byref(ctx))
        native.call(0x742c)
        equal(f'framebuffer:{index}')
    for length in [0, 1, 2, 15, 99, 255, 256, 1023, 4095, 8191]:
        initial = settings_initial()
        restore(initial)
        lib.fx_host_write_descriptor(C.byref(ctx), 0x8400)
        C.memmove(native.ram, bytes(ram), 65536)
        # Relocate the optional text and header to avoid accidental overlap
        # with the fixed status packet for the long string boundary cases.
        ram[0x8412] = native.ram[0x8412] = 0
        ram[0x8413] = native.ram[0x8413] = 0xa0
        text = bytes(rng.randrange(1, 256) for _ in range(length)) + b'\0'
        C.memmove(C.byref(ram, 0xa000), text, len(text))
        C.memmove(C.byref(native.ram, 0xa000), text, len(text))
        assert lib.fx_host_write_text_packet(C.byref(ctx), 0x8400) == 0
        native.er(0, 0x8400)
        native.call(0xaf5a)
        equal(f'text_packet:{length}')

    restore()
    lib.fx_boot_write_signature(C.byref(ctx))
    native.call(0x52e2)
    equal('signature:write')
    valid = settings_initial()
    for field in list(range(0x860e, 0x861d)) + [0x8112, 0x80dc] + [
            0x8226+10*n+offset for n in range(10) for offset in [0, 9]]:
        for value in range(256):
            restore(valid)
            ram[field] = native.ram[field] = value
            actual = lib.fx_boot_retained_state_invalid(C.byref(ctx))
            native.call(0x52f0)
            assert actual == native.reg(0), (hex(field), value, actual, native.reg(0))
            equal(f'validation:{field:04x}/{value:02x}')
    for address, name in [(0x1d77e, 'fx_boot_clear_expression'),
                          (0x1d78a, 'fx_boot_clear_exported_input')]:
        restore()
        getattr(lib, name)(C.byref(ctx))
        native.call(address)
        equal(f'input_clear:{address:x}')
    for mode in range(256):
        restore()
        ram[0x80f9] = native.ram[0x80f9] = mode
        lib.fx_boot_clear_result_workspaces(C.byref(ctx))
        native.call(0x1d796)
        equal(f'workspace_clear:{mode}')

    # All editor control-byte actions, natural/legacy settings, and ordinary
    # and special screens. Preserve-capable inputs remain bounded by99.
    for action in range(256):
        for mode, screen, math in [(0xc1, 1, 1), (0xc1, 1, 0), (0xc1, 17, 1),
                                   (0xc4, 1, 1), (2, 1, 0), (0x88, 1, 1), (0x89, 1, 1)]:
            initial = settings_initial()
            initial[0x80f9], initial[0x80fc], initial[0x8106] = mode, screen, math
            initial[0x8154:0x8159] = b'12+3\0'
            initial[0x8114] = 2
            # ROM startup metadata names the BASE-N label strings.
            initial[0x8df2:0x8df6] = b'\xb9\x31\xb9\x31'
            restore(initial)
            actual = lib.fx_boot_initialize_editor(C.byref(ctx), action)
            assert actual == 0, ('editor status', action, mode, screen, actual)
            native.reg(0, action)
            native.call(0x1e55e)
            equal(f'editor_init:{action}/{mode}/{screen}/{math}',
                  numeric_workspace=(action & 15) == 2 and
                  not (mode == 0x88 or mode == 0x89 or (mode & 0x80 and math and screen == 1)))

    for index in range(256):
        initial = settings_initial()
        initial[0xf050] = index
        restore(initial)
        assert lib.fx_boot_cold_reset(C.byref(ctx)) == 0
        native.call(0x1d6ec)
        equal(f'cold_reset:{index}')
    for mode in range(256):
        initial = settings_initial()
        initial[0x80f9] = mode
        restore(initial)
        assert lib.fx_boot_reset_settings(C.byref(ctx)) == 0
        native.call(0x1d71c)
        equal(f'settings_reset:{mode}')
    for value in range(256):
        initial = settings_initial()
        initial[0xf040] = value
        restore(initial)
        actual = lib.fx_boot_probe_welcome_key(C.byref(ctx))
        native.call(0x6fe6)
        assert actual == native.reg(0), (value, actual, native.reg(0))
        equal(f'welcome_probe:{value}')
    for index in range(100):
        initial = settings_initial() if index & 1 else bytearray(rng.randbytes(65536))
        restore(initial)
        assert lib.fx_boot_initialize(C.byref(ctx)) == 0
        native.lib.harness_set_sp(0x8dee)
        native.lib.harness_set_pc(0xd6fe)
        assert native.lib.harness_run(1000000, 0xd730, False) == 100
        equal(f'boot_prelude:{index}')
    for flags in range(256):
        initial = settings_initial()
        initial[0x80f8] = flags
        restore(initial)
        assert lib.fx_boot_default_screen(C.byref(ctx)) == 0
        native.call(0x40a2)
        equal(f'default_screen:{flags}')
    for mode in range(256):
        initial = settings_initial()
        initial[0x80f9] = mode
        initial[0x8df2:0x8df6] = b'\xb9\x31\xb9\x31'
        restore(initial)
        assert lib.fx_boot_default_screen(C.byref(ctx)) == 0, ('default mode', mode)
        native.call(0x40a2)
        equal(f'default_screen_mode:{mode}', numeric_workspace=not (mode & 0x80) and mode != 0x89)
    for value in range(256):
        initial = settings_initial()
        initial[0xf040] = value
        restore(initial)
        actual = lib.fx_boot_resume(C.byref(ctx))
        native.lib.harness_set_sp(0x8dee)
        native.lib.harness_set_pc(0xd730)
        stop = 0x740c if value and not (value & 0x18) else 0xd748 if value == 0x7b else 0xd7ae
        assert native.lib.harness_run(1000000, stop, False) == 100
        assert actual == (1 if stop == 0x740c else 2 if stop == 0xd748 else 0)
        equal(f'boot_resume:{value}')
    for mode in [0xc1, 0xc4, 2, 0x88, 0x89, 0x45, 0x4a, 0x4b, 12]:
        initial = settings_initial()
        initial[0x80f9] = mode
        initial[0x8df2:0x8df6] = b'\xb9\x31\xb9\x31'
        restore(initial)
        actual = lib.fx_boot_resume(C.byref(ctx))
        native.lib.harness_set_sp(0x8dee)
        native.lib.harness_set_pc(0xd730)
        stop = 0xd7a6 if mode == 12 else 0xd7ae
        assert native.lib.harness_run(1000000, stop, False) == 100
        assert actual == (-1 if mode == 12 else 0), ('resume mode', mode, actual)
        equal(f'boot_resume_mode:{mode}', numeric_workspace=not (mode & 0x80) and mode != 0x89)

    for suppression in range(256):
        initial = settings_initial()
        initial[0x80dd] = suppression
        restore(initial)
        actual = lib.fx_boot_prepare_power_off(C.byref(ctx))
        if suppression:
            native.call(0x5338)
            assert actual == 0
        else:
            native.lib.harness_set_sp(0x8dee)
            native.lib.harness_set_pc(0x5338)
            assert native.lib.harness_run(1000000, 0x6f82, False) == 100
            assert actual == 3
        equal(f'power_off:{suppression}')
    for index in range(100):
        initial = settings_initial() if index & 1 else bytearray(rng.randbytes(65536))
        initial[0xf040] = 255
        initial[0xf050] = index & 7
        restore(initial)
        assert lib.fx_boot_reset(C.byref(ctx)) == 0
        native.lib.harness_set_sp(0x8dee)
        native.lib.harness_set_pc(0x6f82)
        assert native.lib.harness_run(1000000, 0xd7ae, False) == 100
        equal(f'reset_entry:{index}')

    report = {'cases': sum(counts.values()), 'groups': counts,
              'comparison': 'Whole RAM excluding native CPU stack8d00..8ded; editor action2 branches that format zero also exclude numeric operand workspace8000..80db. Query return bytes and complete host packets compared.',
              'boot_scope': 'Full6F82 reset-entry data initialization throughD7AE, separateD6FE/D730 checkpoints and5338 power-off writes through6F82; diagnostic and welcome key branches stop at their native event boundary.',
              'limitations': ['Physical time, interrupt delivery, diagnostic screens, welcome key-wait and main calculator event loop remain incomplete.',
                              'Mode12 boot resume explicitly reports an untranslated mode controller.',
                              'Oversized BASE-N labels and unterminated strings are bounded in C; native CPU stack corruption or infinite loops are excluded.']}
    inputs = [str(p) for p in sources]
    inputs += [str(Path('csrc') / (module + '.h')) for module in modules
               if (ROOT / 'csrc' / (module + '.h')).exists()]
    report = write_report(ROOT / 'analysis/c-verification/boot.json', report, inputs + ['tools/c_verification.py'], 'tools/test_boot_c.py')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
