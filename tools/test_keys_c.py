#!/usr/bin/env python3
"""Differential key-matrix scanning, debounce and ROM key-map tests."""
import ctypes as C
import json
import random
import subprocess

from c_verification import ROOT, write_report
from nxu8.machine import Machine
from test_platform_c import Platform


class State(C.Structure):
    _fields_ = [('columns', C.c_uint8), ('rows', C.c_uint8)]


SAMPLE = C.CFUNCTYPE(C.c_uint8, C.c_void_p, C.c_uint8)


class Input(C.Structure):
    _fields_ = [('sample', SAMPLE), ('context', C.c_void_p)]


def main():
    build = ROOT / 'analysis/build/keys'; build.mkdir(parents=True, exist_ok=True)
    sources = ['csrc/ui/fx_keys.c', 'csrc/platform/fx_platform.c']
    output = build / 'keys.so'
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror', '-fPIC', '-shared',
                    *[str(ROOT / s) for s in sources], '-o', str(output)], check=True)
    lib = C.CDLL(str(output))
    for name in ('fx_key_scan', 'fx_key_debounce', 'fx_key_is_held'):
        getattr(lib, name).argtypes = [C.POINTER(Platform), C.POINTER(Input), C.POINTER(State)]
        getattr(lib, name).restype = C.c_uint8
    lib.fx_key_map.argtypes = [C.POINTER(Platform), State, C.c_uint16]; lib.fx_key_map.restype = C.c_uint8
    lib.fx_key_map_current.argtypes = [C.POINTER(Platform), State]; lib.fx_key_map_current.restype = C.c_uint8
    lib.fx_key_is_modifier.argtypes = [C.c_uint8]; lib.fx_key_is_modifier.restype = C.c_uint8
    lib.fx_key_update_modifiers.argtypes = [C.POINTER(Platform), C.c_uint8]
    for name in ('fx_key_is_data_token', 'fx_key_is_menu_token', 'fx_key_is_direction_token'):
        getattr(lib, name).argtypes = [C.POINTER(Platform), C.c_uint8]
        getattr(lib, name).restype = C.c_uint8
    lib.fx_key_can_math_input.argtypes = [C.POINTER(Platform)]; lib.fx_key_can_math_input.restype = C.c_uint8
    lib.fx_key_normalize_action.argtypes = [C.POINTER(Platform)]; lib.fx_key_normalize_action.restype = None
    rom = (ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    rb = (C.c_uint8 * len(rom)).from_buffer_copy(rom)
    ram = (C.c_uint8 * 65536)(); p = Platform(rb, len(rom), ram, 0, 0)
    m = Machine(rom, build / 'oracle')
    background = random.Random(0x1d9a6).randbytes(65536)
    counts = {}

    def restore():
        C.memmove(ram, background, len(ram)); C.memmove(m.ram, background, len(ram))

    def memory_equal(detail):
        # Copy via the buffer protocol. ctypes array slicing creates Python
        # integer lists and makes exhaustive full-RAM comparisons needlessly
        # expensive without adding coverage.
        actual, expected = bytes(ram), bytes(m.ram)
        assert actual[:0x8d00] == expected[:0x8d00], detail
        assert actual[0x8dee:] == expected[0x8dee:], detail

    for table in (0x07fe, 0x083e, 0x087e, 0x08be, 0x08fe, 0x093e, 0x097e):
        for columns in range(256):
            for rows in range(256):
                state = State(columns, rows); m.ram[0x8290] = columns; m.ram[0x8291] = rows
                m.er(0, 0x8290); m.er(2, table); m.call(0x1dae6)
                assert lib.fx_key_map(C.byref(p), state, table) == m.reg(0), (table, columns, rows)
    counts['key_map_all_column_row_bytes_seven_tables'] = 7 * 65536
    # Execute the original modifier dispatch as a bounded block, stopping
    # before its later editor/controller actions. FP points at the input pair.
    for context in range(256):
        for modifiers in range(256):
            ram[0x80f8] = m.ram[0x80f8] = modifiers
            ram[0x80f9] = m.ram[0x80f9] = context
            m.ram[0x82ea] = 0xa8; m.ram[0x82eb] = 0x50; m.er(14, 0x8300)
            m.lib.harness_set_pc(0x1dbc2); m.lib.harness_set_sp(0x8dee)
            assert m.lib.harness_run(1000, 0x1dc3e, False) == 100
            assert lib.fx_key_map_current(C.byref(p), State(0xa8, 0x50)) == m.reg(0), (context, modifiers)
    counts['modifier_context_dispatch_all_bytes'] = 65536
    for token in range(256):
        m.reg(0, token); m.call(0x1dd4e)
        assert lib.fx_key_is_modifier(token) == m.reg(0)
        for flags in range(256):
            restore(); ram[0x80f8] = m.ram[0x80f8] = flags
            if token == 0xec:
                assert lib.fx_key_update_modifiers(C.byref(p), token) == -1 and ram[0x80f8] == flags
                continue
            assert lib.fx_key_update_modifiers(C.byref(p), token) == 0
            m.reg(0, token); m.call(0x1dcf4); memory_equal(('modifier update', token, flags))
    counts['modifier_predicate'] = 256
    counts['modifier_state_transitions'] = 255 * 256
    counts['explicit_cursor_modifier_gap'] = 256
    for name, address in [('fx_key_is_data_token', 0x4106), ('fx_key_is_menu_token', 0x4120),
                          ('fx_key_is_direction_token', 0x41d0)]:
        for setting in range(256):
            ram[0x80f7] = m.ram[0x80f7] = setting
            for token in range(256):
                m.reg(0, token); m.call(address)
                assert getattr(lib, name)(C.byref(p), token) == m.reg(0), (name, setting, token)
        counts[name] = 65536
    for context in range(256):
        for math in (0, 1, 255):
            for suppress in (0, 1, 255):
                for state in (0, 1, 255):
                    for mode in (0, 1, 2, 3, 255):
                        for a, b in [(0x80f9, context), (0x8106, math), (0x810c, suppress), (0x80fe, state), (0x80fa, mode)]:
                            ram[a] = m.ram[a] = b
                        m.call(0x1dcb6)
                        assert lib.fx_key_can_math_input(C.byref(p)) == m.reg(0), (context, math, suppress, state, mode)
    counts['math_input_permission'] = 256 * 3 * 3 * 3 * 5
    for state in (0, 1, 255):
        for action_type in (0, 1, 255):
            for token in range(256):
                restore()
                for a, b in [(0x80fe, state), (0x80f7, action_type), (0x80f5, token)]: ram[a] = m.ram[a] = b
                lib.fx_key_normalize_action(C.byref(p)); m.call(0x1ddac)
                memory_equal(('action normalization', state, action_type, token))
    counts['action_normalization'] = 3 * 3 * 256
    for value in range(256):
        restore(); ram[0xf040] = m.ram[0xf040] = value
        state = State(0x5a, 0x24); m.ram[0x8290] = state.columns; m.ram[0x8291] = state.rows
        actual = lib.fx_key_scan(C.byref(p), None, C.byref(state))
        ram[0x8290] = state.columns; ram[0x8291] = state.rows
        m.er(0, 0x8290); m.call(0x1d9a6)
        assert actual == m.reg(0), value; memory_equal(('scan', value))
    counts['passive_scan_all_input_bytes'] = 256
    for name, address in [('fx_key_debounce', 0x1d9e4), ('fx_key_is_held', 0x1d958)]:
        for value in range(256):
            for columns in range(256):
                restore(); ram[0xf040] = m.ram[0xf040] = value
                state = State(columns, 0x20); m.ram[0x8290] = columns; m.ram[0x8291] = 0x20
                actual = getattr(lib, name)(C.byref(p), None, C.byref(state))
                ram[0x8290] = state.columns; ram[0x8291] = state.rows
                m.er(0, 0x8290); m.call(address)
                assert actual == m.reg(0), (name, value, columns)
                memory_equal((name, value, columns))
        counts[name + '_all_input_and_column_bytes'] = 65536
    # Callback-driven row inputs exercise the portable host interface. These
    # checks are distinct from the passive native-peripheral comparisons above.
    for selected in range(7):
        calls = []
        @SAMPLE
        def sample(unused, rows):
            calls.append(rows)
            return 0xfe if rows == 1 << selected else 0xff
        restore(); state = State(0, 0); inp = Input(sample, None)
        assert lib.fx_key_scan(C.byref(p), C.byref(inp), C.byref(state)) == 1
        assert (state.columns, state.rows) == (1, 1 << selected)
        assert calls == [1 << n for n in range(selected+1)] and ram[0xf046] == 0
    counts['host_row_sampling_contract'] = 7
    report = write_report('analysis/c-verification/keys.json', {
        'cases': sum(counts.values()), 'domains': counts,
        'comparison': 'Native return values, key-state pair and RAM/peripheral writes excluding CPU call-stack scratch 8d00..8ded.',
        'scope': 'Matrix primitives and modifier table dispatch; no editor, blocking key-event loop, physical debounce timing or interrupt scheduler.'},
        sources + ['csrc/ui/fx_keys.h', 'csrc/platform/fx_platform.h', 'tools/test_platform_c.py',
                   'tools/c_verification.py'], 'tools/test_keys_c.py')
    print(json.dumps({k: v for k, v in report.items() if k != 'tested_inputs_sha256'}, indent=2))


if __name__ == '__main__': main()
