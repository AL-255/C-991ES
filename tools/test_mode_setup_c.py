#!/usr/bin/env python3
"""Original MODE/SETUP persistent policies and nonblocking menu controllers."""
import argparse
import ctypes as C
import json
import random
import re
import subprocess
from c_verification import ROOT, write_report
from nxu8.machine import Machine
from test_platform_c import Platform
from test_menu_navigator_c import SOURCES as MENU_SOURCES, Menu
from test_key_controller_c import Controller
from test_diagnostic_contrast_c import Contrast


class ModeSetup(C.Structure):
    _fields_ = [('menu', Menu), ('keys', Controller), ('contrast', Contrast),
                *[(n, C.c_uint8) for n in ('kind', 'phase', 'mode', 'submode',
                 'result', 'option', 'request', 'active')]]


SOURCES = [*MENU_SOURCES, 'csrc/platform/fx_persistent.c', 'csrc/ui/fx_mode_setup.c']


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--random-cases', type=int, default=4096)
    args = ap.parse_args()
    build = ROOT/'analysis/build/mode-setup'; build.mkdir(parents=True, exist_ok=True)
    library = build/'mode.so'
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-shared', '-fPIC', '-Wl,--no-undefined',
                    *[str(ROOT/f) for f in SOURCES], '-o', str(library)], check=True)
    lib = C.CDLL(str(library)); pp = C.POINTER(Platform)
    lib.fx_mode_set.argtypes = [pp, C.c_uint8, C.c_uint8]
    for name in ('fx_mode_reset_statistics', 'fx_mode_reset_bank', 'fx_mode_reset_table'):
        getattr(lib, name).argtypes = [pp]
    lib.fx_mode_initialize_equation.argtypes = [pp, C.c_uint8]
    lib.fx_setup_set_layout.argtypes = [pp, C.c_uint8]
    lib.fx_setup_reset_table_expression.argtypes = [pp]
    ss = C.POINTER(ModeSetup)
    for name in ('fx_mode_menu_begin', 'fx_setup_menu_begin', 'fx_mode_setup_tick', 'fx_mode_setup_resume_timer'):
        getattr(lib, name).argtypes = [pp, ss]
    lib.fx_mode_setup_accept_menu.argtypes = [pp, ss, C.c_uint8, C.c_uint8]
    lib.fx_mode_setup_accept_token.argtypes = [pp, ss, C.c_uint8]
    lib.fx_mode_setup_accept_handler.argtypes = [pp, ss, C.c_uint8]
    lib.fx_mode_setup_finish.argtypes = [ss, C.POINTER(C.c_uint8)]
    lib.fx_take_callback.argtypes = [pp]; lib.fx_take_callback.restype = C.c_uint8
    rom = (ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    rd = (C.c_uint8*len(rom)).from_buffer_copy(rom); ram = (C.c_uint8*65536)()
    p = Platform(rd, len(rom), ram, 0, 0); m = Machine(rom, build/'oracle')
    rng = random.Random(0xc77c); background = bytearray(rng.randbytes(65536))
    background[0x8dee:0x8e00] = rom[0x1f8be:0x1f8d0]
    counts, bounds, numeric_residuals = {}, {}, {}
    def prepare(old=0xc1, sub=0, screen=1, flag=1, math=1):
        m.reset(); C.memmove(m.ram, bytes(background), 65536)
        for a, v in [(0x80f9, old), (0x80fa, sub), (0x80fc, screen), (0x80fe, flag),
                     (0x80fb, 1), (0x80f8, 0), (0x80f4, 0), (0x80dd, 0),
                     (0x8102, 0), (0x8103, 0), (0x8105, 4), (0x8106, math),
                     (0x8112, 17), (0x8114, 0), (0x8117, 1),
                     (0x8118, 0), (0x8119, 1), (0x811a, 0x7c), (0x811b, 10), (0x811f, 10),
                     (0x8120, 0), (0x8121, 1), (0x8127, 0), (0x8128, 0), (0x8129, 0),
                     (0x8137, 0), (0x8e00, 0), (0x8e01, 0), (0x8e02, 0), (0xf040, 255)]:
            m.ram[a] = v
        for a in (0x8154, 0x81b8): m.ram[a:a+100] = bytes(100)
        for a in (0x8226, 0x8408): m.ram[a:a+10] = bytes(10)
        m.ram[0x81b8:0x81bc] = b'1+2\0'
        C.memmove(ram, m.ram, 65536); p.callback_pending = p.status = 0
    def equal(group, detail, numeric_gap=False):
        actual, expected = bytes(ram), bytes(m.ram)
        def admitted(a): return not 0x8b00 <= a < 0x8dee and not (numeric_gap and 0x8000 <= a < 0x80dc)
        prefix_matches = actual[:0x8000] == expected[:0x8000] and actual[0x80dc:0x8b00] == expected[0x80dc:0x8b00] if numeric_gap else actual[:0x8b00] == expected[:0x8b00]
        assert prefix_matches and actual[0x8dee:] == expected[0x8dee:], (
            group, detail, [(hex(a), actual[a], expected[a]) for a in range(65536)
                            if admitted(a) and actual[a] != expected[a]][:24])
        assert lib.fx_take_callback(C.byref(p)) == m.lib.harness_callback()
        if numeric_gap and actual[0x8000:0x80dc] != expected[0x8000:0x80dc]:
            group += '_numeric_workspace_gap'
            for a in range(0x8000, 0x80dc):
                if actual[a] != expected[a]:
                    key = hex(a)
                    numeric_residuals[key] = numeric_residuals.get(key, 0)+1
        counts[group] = counts.get(group, 0)+1
    def set_mode(group, old, old_sub, mode, sub):
        prepare(old, old_sub)
        assert lib.fx_mode_set(C.byref(p), mode, sub) == 0
        m.reg(0, mode); m.reg(1, sub); m.call(0xc77c)
        equal(group, (old, old_sub, mode, sub))
    def run(stop, entry=None):
        if entry is not None: m.lib.harness_set_pc(entry)
        if m.lib.harness_get_pc() == stop:
            assert m.lib.harness_run(1, 0x2fffe, False) == 103
        result = m.lib.harness_run(3000000, stop, False)
        assert result == 100, (result, hex(m.lib.harness_get_pc()), hex(stop))
    def compare_controller(state, status, detail, gap=False):
        stop = 0x2fffe if status == 1 else 0xd0cc if status == 5 else 0x1d8a4
        assert status in (0, 1, 5), (detail, status)
        run(stop); equal('prepared_controller_caller_policy', detail, gap)
        if status == 1:
            assert state.result == m.reg(0), (detail, state.result, m.reg(0))
        if status == 5:
            assert m.reg(0) == (44 if state.request == 1 else 45) and m.reg(1) == 1
        return status
    def caller_choice(kind, choice, result=3, old=0xc1):
        prepare(old, sub=9 if old == 2 else 0)
        m.lib.harness_set_sp(0x8dee); m.lib.harness_set_lr(0x2fffe)
        run(0xca42 if kind == 1 else 0xcaa0, 0xc978 if kind == 1 else 0xca7c)
        m.ram[(m.er(14)-1) & 0xffff] = choice
        C.memmove(ram, m.ram, 65536); p.callback_pending = p.status = 0
        state = ModeSetup(); state.kind = kind; state.phase = state.active = 1
        status = lib.fx_mode_setup_accept_menu(C.byref(p), C.byref(state), choice, result)
        m.reg(0, result); m.lib.harness_set_pc(0xca46 if kind == 1 else 0xcaa4)
        return state, compare_controller(state, status, (kind, old, choice, result),
            kind == 1 and choice == 2 or kind == 2 and choice in (1, 2, 22, 23))
    for mode in range(256):
        for sub in (0, 1, 3, 4, 255):
            set_mode('all_mode_bytes', 0xc1, 0, mode, sub)
    for old in range(256):
        for mode in (3, 6, 7, 12, 0x45, 0x4b, 0x88, 0xc1):
            set_mode('all_incoming_mode_bytes_special_destinations', old, 4, mode, 0)
    for sub in range(256):
        for mode in (3, 6, 7, 12, 0x45, 0x4b, 0x88, 0xc1):
            set_mode('all_submode_bytes_same_mode', mode, sub, mode, sub)
            set_mode('all_submode_bytes_mode_change', 0xc4, 0, mode, sub)
    for index in range(args.random_cases):
        set_mode('random_mode_transitions', rng.randrange(256), rng.randrange(256),
                 rng.choice((3, 6, 7, 12, 0x45, 0x4b, 0x88, 0xc1, rng.randrange(256))), rng.randrange(256))
    for old in range(256):
        prepare(old); lib.fx_mode_reset_statistics(C.byref(p)); m.call(0x1d60a)
        equal('statistics_reset_mode_gate', old)
        prepare(old); lib.fx_mode_reset_table(C.byref(p)); m.call(0x1f8a0)
        equal('table_reset_mode_gate', old)
    for screen, entry in ((21, 0x1d31a), (23, 0x1d346), (24, 0x1d354)):
        prepare(); lib.fx_mode_initialize_equation(C.byref(p), screen); m.call(entry)
        equal('equation_slot_initializers', screen)
    prepare(); lib.fx_mode_reset_bank(C.byref(p)); m.call(0x1d2fc); equal('bank_layout_reset', 0)
    for old in (2, 3, 6, 7, 12, 0x45, 0x4a, 0x4b, 0x88, 0x89, 0xc1, 0xc4):
        for screen in (1, 18, 0x80):
            for flag in (1, 3, 5, 0xf3):
                for natural in (0, 1):
                    prepare(old, sub=9 if old == 2 else 0, screen=screen, flag=flag)
                    result = lib.fx_setup_set_layout(C.byref(p), natural)
                    assert result == 0, (old, screen, flag, natural, result)
                    m.reg(0, natural); m.call(0xcbba)
                    equal('layout_switch_persistent_display_policy', (old, screen, flag, natural), numeric_gap=True)
    for old in (0xc1, 3, 0x45, 0x88):
        for choice in range(1, 29): caller_choice(2, choice, old=old)
    for choice in (0, 29, 127, 128, 255): caller_choice(2, choice)
    for result in (0, 1, 2, 3, 255):
        caller_choice(2, 4, result)
        caller_choice(1, 0xc1, result)
    for choice in (0, 2, 3, 6, 7, 12, 0x45, 0x4b, 0x88, 0x89, 0xc1, 0xc4):
        caller_choice(1, choice)
    # Each nested MODE caller retains a genuine native parent frame. Execute
    # all admitted selection bytes plus navigation/cancel return classes.
    nested = {3:(2, 0xcf8e, 0xcf92), 0x45:(3, 0xca68, 0xca6c),
              0x4b:(4, 0xd59a, 0xd59e), 12:(5, 0xd638, 0xd63c)}
    for mode, (phase, before, after) in nested.items():
        for result in (0, 1, 2, 3):
            for choice in (0, *range(1, 18), 0xff):
                prepare(); m.lib.harness_set_sp(0x8dee); m.lib.harness_set_lr(0x2fffe)
                run(0xca42, 0xc978); m.ram[(m.er(14)-1) & 0xffff] = mode
                m.reg(0, 3); run(before, 0xca46)
                m.ram[(m.er(14)-1) & 0xffff] = choice
                C.memmove(ram, m.ram, 65536); p.callback_pending = p.status = 0
                state = ModeSetup(); state.kind = state.active = 1
                state.mode = mode; state.phase = phase; state.submode = 1 if mode == 12 else 0
                status = lib.fx_mode_setup_accept_menu(C.byref(p), C.byref(state), choice, result)
                m.reg(0, result); m.lib.harness_set_pc(after)
                # Impossible selections for the standalone STAT46 selector
                # would transfer to another STAT operation, outside MODE.
                if mode == 3 and result == 3 and not 1 <= choice <= 8: continue
                compare_controller(state, status, ('nested', mode, choice, result), mode == 3 and status == 1)
    for option in (6, 7, 8):
        for token in range(256):
            prepare(); m.reg(0, option); m.lib.harness_set_sp(0x8dee); m.lib.harness_set_lr(0x2fffe)
            run(0xcccc, 0xcc52)
            C.memmove(ram, m.ram, 65536); p.callback_pending = p.status = 0
            state = ModeSetup(); state.kind = 2; state.phase = 6; state.option = option; state.active = 1
            status = lib.fx_mode_setup_accept_token(C.byref(p), C.byref(state), token)
            m.reg(0, token); m.lib.harness_set_pc(0xccd0)
            compare_controller(state, status, ('precision', option, token))
    for value in range(256):
        for token in (0, 0xe2, 0xe3, 0xe5, 0xe6):
            prepare(); ram[0x8112] = m.ram[0x8112] = value
            m.reg(0, 0); m.lib.harness_set_sp(0x8dee); m.lib.harness_set_lr(0x2fffe)
            run(0xcd20, 0xccf4)
            C.memmove(ram, m.ram, 65536); p.callback_pending = p.status = 0
            state = ModeSetup(); state.kind = 2; state.phase = 7; state.active = 1
            state.contrast.value = value; state.contrast.minimum = 4; state.contrast.maximum = 29; state.contrast.active = 1
            status = lib.fx_mode_setup_accept_token(C.byref(p), C.byref(state), token)
            m.reg(0, token); m.lib.harness_set_pc(0xcd24)
            run(0x2fffe if status == 1 else 0x1d8a4)
            equal('contrast_wait_policy_all_values', (value, token))
            if status == 1: assert state.result == 0
    normal = {rom[0x7fe+c*8+r]:(1 << c, 1 << r) for c in range(8) for r in range(8)}
    def full_begin(kind):
        prepare(); state = ModeSetup()
        begin = lib.fx_mode_menu_begin if kind == 1 else lib.fx_setup_menu_begin
        assert begin(C.byref(p), C.byref(state)) == 0
        m.lib.harness_set_sp(0x8dee); m.lib.harness_set_lr(0x2fffe)
        run(0x1d8a4, 0xc978 if kind == 1 else 0xca7c)
        equal('full_controller_entry_paint_and_wait', kind)
        return state
    sequences = [(1, (0x31,)), (1, (0x32,)), (1, (0x33, 0x38)),
                 (1, (0x35, 0x34)), (1, (0xe1, 0x31, 0x31, 0x34)),
                 (1, (0xe1, 0x33, 0x34, 0x32)),
                 (2, (0x36, 0x30)), (2, (0x37, 0x39)), (2, (0x38, 0x32)),
                 (2, (0xe1, 0x33, 0x31)), (2, (0xe1, 0x34, 0x32)),
                 (2, (0xe1, 0x36, 0x32)), (2, (0xe1, 0x38, 0xe2, 0xe3, 0xe6)),
                 (2, (0x30, 0x33)), (2, (0xe6,))]
    for kind, tokens in sequences:
        state = full_begin(kind)
        for index, token in enumerate(tokens):
            pair = normal[token]
            for a, v in ((0x8e01, pair[0]), (0x8e02, pair[1])): ram[a] = m.ram[a] = v
            old_phase = state.phase
            status = lib.fx_mode_setup_tick(C.byref(p), C.byref(state))
            run(0xe04e if old_phase <= 5 else 0xccd0 if old_phase == 6 else 0xcd24)
            if status == 4:
                run(0x53ce); equal('full_menu_timer_request', (kind, tokens, index))
                status = lib.fx_mode_setup_resume_timer(C.byref(p), C.byref(state))
            assert status in (0, 1), (kind, tokens, index, status)
            run(0x2fffe if status == 1 else 0x1d8a4)
            equal('full_raw_controller_event_sequence', (kind, tokens, index), kind == 1 and token == 0x32 and index == 0)
            if status == 1:
                assert state.result == m.reg(0)
                assert index == len(tokens)-1, (kind, tokens, index)
    for kind in (1, 2):
        state = full_begin(kind)
        for column in (0x20, 0x40, 0x80):
            for a, v in ((0x8e01, column), (0x8e02, 0x80)): ram[a] = m.ram[a] = v
            assert lib.fx_mode_setup_tick(C.byref(p), C.byref(state)) == 3
            run(0x1d8a4); equal('full_controller_host_export', (kind, column))
        for a, v in ((0x8e01, 0x10), (0x8e02, 0x80)): ram[a] = m.ram[a] = v
        assert lib.fx_mode_setup_tick(C.byref(p), C.byref(state)) == 2
        run(0x1824e); equal('full_controller_host_reset_request', kind)
    for flag in range(256):
        prepare(flag=flag); state = ModeSetup()
        status = lib.fx_setup_menu_begin(C.byref(p), C.byref(state))
        m.lib.harness_set_sp(0x8dee); m.lib.harness_set_lr(0x2fffe)
        run(0x2fffe if status == 1 else 0x1d8a4, 0xca7c)
        equal('all_setup_blocker_flag_bytes', flag)
        assert (status == 1) == bool(flag & 0x40)
    for mode in (6, 7):
        for result in range(256):
            state, status = caller_choice(1, mode)
            assert status == 5
            m.reg(0, result); m.lib.harness_set_pc(0xc9e8 if mode == 6 else 0xc9f4)
            assert lib.fx_mode_setup_accept_handler(C.byref(p), C.byref(state), result) == 1
            run(0x2fffe); equal('all_pending_bank_controller_return_bytes', (mode, result))
            assert state.result == mode and m.reg(0) == mode
    saved = bytes(ram)
    assert lib.fx_mode_set(None, 1, 2) == -1
    invalid = Platform(rd, len(rom), None, 0, 0)
    assert lib.fx_mode_set(C.byref(invalid), 1, 2) == -1
    assert bytes(ram) == saved; bounds['invalid_arguments'] = 2
    headers, pending = set(), [ROOT/f for f in SOURCES]
    while pending:
        source = pending.pop()
        for include in re.findall(r'^\s*#include\s+"([^"]+)"', source.read_text(), re.M):
            dep = (source.parent/include).resolve(); name = str(dep.relative_to(ROOT))
            if name not in headers: headers.add(name); pending.append(dep)
    report = {'cases': sum(counts.values())+sum(bounds.values()), 'native_cases': sum(counts.values()),
              'groups': counts, 'bounds_cases': sum(bounds.values()), 'bounds_groups': bounds,
              'numeric_workspace_residual_counts': numeric_residuals,
              'comparison': 'Complete observable RAM/MMIO and F000 write observer, except CPU stack8B00..8DED and explicitly labelled zero-format numeric-workspace groups8000..80DB.',
              'limits': ['Zero result rendering inherits the existing boot supplied-record formatter operand/saved-argument scratch gap; its observed residual addresses are recorded separately.',
                         'MATRIX/VECTOR D0CC bodies are typed pending requests; caller boundaries and return policies are tested separately.',
                         'The 0770 menu timer is a host request, not physical STOP/IRQ emulation.']}
    report = write_report('analysis/c-verification/mode_setup.json', report,
                          SOURCES+sorted(headers)+['tools/c_verification.py', 'tools/test_platform_c.py',
                          'tools/test_menu_navigator_c.py', 'tools/test_key_controller_c.py',
                          'tools/test_key_wait_c.py', 'tools/test_boot_events_c.py', 'tools/test_boot_c.py',
                          'tools/test_diagnostic_contrast_c.py'], 'tools/test_mode_setup_c.py')
    print(json.dumps(report, indent=2))


if __name__ == '__main__': main()
