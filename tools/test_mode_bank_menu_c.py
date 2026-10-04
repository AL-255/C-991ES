#!/usr/bin/env python3
"""Original D0CC MATRIX/VECTOR menu and dimension-storage differentials."""
import argparse
import ctypes as C
import json
import random
import re
import subprocess
from c_verification import ROOT, write_report
from nxu8.machine import Machine
from test_platform_c import Platform
from test_menu_navigator_c import Menu
from test_mode_setup_c import ModeSetup, SOURCES as MODE_SOURCES


class BankMenu(C.Structure):
    _fields_ = [('menu', Menu), ('heading', C.c_uint16),
                *[(n, C.c_uint8) for n in ('initial_page', 'page', 'action',
                 'previous_page', 'return_page', 'slot', 'screen', 'mode_entry',
                 'result', 'phase', 'active')]]


SOURCES = [*MODE_SOURCES, 'csrc/linalg/fx_linalg_store.c', 'csrc/ui/fx_mode_bank_menu.c']


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--random-cases', type=int, default=4096)
    args = ap.parse_args()
    build = ROOT/'analysis/build/mode-bank-menu'; build.mkdir(parents=True, exist_ok=True)
    library = build/'bank.so'
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror', '-shared',
                    '-fPIC', '-Wl,--no-undefined', *[str(ROOT/f) for f in SOURCES], '-o', str(library)], check=True)
    lib = C.CDLL(str(library)); pp, ss = C.POINTER(Platform), C.POINTER(BankMenu)
    lib.fx_mode_bank_menu_begin.argtypes = [pp, ss, C.c_uint8, C.c_uint8]
    lib.fx_matrix_menu_begin.argtypes = [pp, ss]
    lib.fx_vector_menu_begin.argtypes = [pp, ss]
    lib.fx_mode_bank_menu_tick.argtypes = [pp, ss]
    lib.fx_mode_bank_menu_resume_timer.argtypes = [pp, ss]
    lib.fx_mode_bank_menu_accept_menu.argtypes = [pp, ss, C.c_uint8, C.c_uint8]
    lib.fx_mode_bank_menu_finish.argtypes = [ss, C.POINTER(C.c_uint8)]
    lib.fx_mode_bank_ensure_dimensions.argtypes = [pp, C.c_uint8, C.c_uint8, C.c_uint8]
    lib.fx_mode_menu_begin.argtypes = [pp, C.POINTER(ModeSetup)]
    lib.fx_mode_setup_tick.argtypes = [pp, C.POINTER(ModeSetup)]
    lib.fx_mode_setup_accept_handler.argtypes = [pp, C.POINTER(ModeSetup), C.c_uint8]
    lib.fx_take_callback.argtypes = [pp]; lib.fx_take_callback.restype = C.c_uint8
    rom = (ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    rd = (C.c_uint8*len(rom)).from_buffer_copy(rom); ram = (C.c_uint8*65536)()
    p = Platform(rd, len(rom), ram, 0, 0); m = Machine(rom, build/'oracle')
    rng = random.Random(0xd0ccd312); background = bytearray(rng.randbytes(65536))
    background[0x8dee:0x8e00] = rom[0x1f8be:0x1f8d0]
    counts, bounds = {}, {}
    def prepare(mode=6):
        m.reset(); C.memmove(m.ram, bytes(background), 65536)
        for a, v in [(0x80f9, mode), (0x80fa, 1), (0x80fc, 1), (0x80fe, 1),
                     (0x80fb, 1), (0x80f8, 0), (0x80f4, 0), (0x80dd, 0),
                     (0x8102, 0), (0x8103, 0), (0x8105, 4), (0x8106, 1),
                     (0x8112, 17), (0x8114, 0), (0x8117, 1), (0x8118, 0),
                     (0x8119, 1), (0x811a, 0x7c), (0x811b, 10), (0x811f, 10),
                     (0x8120, 0), (0x8121, 1), (0x8127, 0), (0x8128, 0),
                     (0x8129, 0), (0x8e00, 0), (0x8e01, 0), (0x8e02, 0), (0xf040, 255)]:
            m.ram[a] = v
        for a in (0x8154, 0x81b8): m.ram[a:a+100] = bytes(100)
        for a in (0x8226, 0x8408): m.ram[a:a+10] = bytes(10)
        C.memmove(ram, m.ram, 65536); p.callback_pending = p.status = 0
        m.lib.harness_set_sp(0x8dee); m.lib.harness_set_lr(0x2fffe)
    def run(stop, entry=None):
        if entry is not None: m.lib.harness_set_pc(entry)
        if m.lib.harness_get_pc() == stop:
            assert m.lib.harness_run(1, 0x2fffe, False) == 103
        result = m.lib.harness_run(3000000, stop, False)
        assert result == 100, (result, hex(m.lib.harness_get_pc()), hex(stop))
    def equal(group, detail):
        actual, expected = bytes(ram), bytes(m.ram)
        assert actual[:0x8b00] == expected[:0x8b00] and actual[0x8dee:] == expected[0x8dee:], (
            group, detail, [(hex(a), actual[a], expected[a]) for a in range(65536)
                            if not 0x8b00 <= a < 0x8dee and actual[a] != expected[a]][:24])
        assert lib.fx_take_callback(C.byref(p)) == m.lib.harness_callback()
        counts[group] = counts.get(group, 0)+1
    def prepared(page, mode_entry, selection, result, mode=6, action=None,
                 previous=0, returned=None, slot=0, shape=(0, 0)):
        prepare(mode); m.er(0, page | mode_entry << 8)
        run(0xd29c, 0xd0cc)
        state = BankMenu()
        assert lib.fx_mode_bank_menu_begin(C.byref(p), C.byref(state), page, mode_entry) == 0
        C.memmove(ram, m.ram, 65536); p.callback_pending = p.status = 0
        if action is not None: state.action = action; m.reg(6, action)
        state.previous_page = previous; m.reg(10, previous)
        state.return_page = page if returned is None else returned; m.reg(11, state.return_page)
        state.slot = slot; m.reg(4, slot)
        for n, v in enumerate(shape): ram[0x80e0+2*slot+n] = m.ram[0x80e0+2*slot+n] = v
        m.ram[(m.er(14)-13) & 0xffff] = selection
        status = lib.fx_mode_bank_menu_accept_menu(C.byref(p), C.byref(state), selection, result)
        m.reg(0, result); m.lib.harness_set_pc(0xd2a0)
        assert status in (0, 1)
        run(0x2fffe if status == 1 else 0x1d8a4)
        equal('prepared_bank_menu_caller_policy', (page, mode_entry, selection, result,
              mode, action, previous, returned, slot, shape))
        if status == 1: assert state.result == m.reg(0)

    for page, mode_entry in ((12, 0), (17, 0), (19, 0), (23, 0), (44, 1), (45, 1)):
        for result in (0, 1, 2, 3, 255):
            for selection in range(256): prepared(page, mode_entry, selection, result)
    for result in range(256):
        for page, mode_entry in ((12, 0), (19, 0), (44, 1), (45, 1)):
            prepared(page, mode_entry, 0xe4, result)
    for mode in range(256):
        for matrix in (False, True):
            for screen, slot in ((1, 0), (19, 0), (20, 2), (19, 3), (20, 3), (255, 255)):
                prepare(mode); ram[0x80fc] = m.ram[0x80fc] = screen
                ram[0x80fa] = m.ram[0x80fa] = slot
                state = BankMenu(); begin = lib.fx_matrix_menu_begin if matrix else lib.fx_vector_menu_begin
                status = begin(C.byref(p), C.byref(state))
                assert status in (0, 1)
                run(0x2fffe if status == 1 else 0x1d8a4, 0xd074 if matrix else 0xd0a0)
                equal('all_ordinary_matrix_vector_entry_gates', (mode, matrix, screen, slot))
                if status == 1: assert state.result == m.reg(0) == 0
    for mode in (6, 7, 0xc1):
        for page in (13, 15, 20, 22, 44, 45):
            for selection in (0xff, 0xfc, 0xfd, 0xfa, 0, 1):
                prepared(page, page >= 44, selection, 1, mode, previous=44, returned=17)
    for selection in (3, 4, 5, 20, 21, 22):
        for mode in (6, 7, 0xc1):
            for action in (1, 2, 18, 19):
                for shape in ((0, 0), (0, 3), (2, 0), (2, 3)):
                    prepared(44 if selection <= 5 else 45, 0, selection, 3,
                             mode, action, slot=selection-3 if selection <= 5 else selection-20, shape=shape)
    for index in range(args.random_cases):
        page = rng.choice((12, 13, 15, 16, 17, 19, 20, 22, 23, 44, 45))
        prepared(page, int(page >= 44), rng.randrange(256), rng.choice((0, 1, 2, 3, 255)),
                 rng.choice((6, 7, 0xc1)), rng.choice((1, 2, 18, 19, page)),
                 rng.choice((0, 12, 17, 19, 23, 44, 45)), rng.choice((12, 17, 19, 23, 44, 45)),
                 rng.randrange(3), (rng.randrange(4), rng.randrange(4)))
    for slot in range(9):
        for rows in range(256):
            for unchanged in (False, True):
                prepare(); columns = rng.randrange(256)
                if unchanged:
                    ram[0x80e0+2*slot] = m.ram[0x80e0+2*slot] = rows
                    ram[0x80e1+2*slot] = m.ram[0x80e1+2*slot] = columns
                ram[0x9d00] = m.ram[0x9d00] = rows
                ram[0x9d01] = m.ram[0x9d01] = columns
                assert lib.fx_mode_bank_ensure_dimensions(C.byref(p), slot, rows, columns) == 0
                m.reg(0, slot); m.er(2, 0x9d00); m.call(0xd2d8)
                equal('all_dimension_bytes_and_bank_slots', (slot, rows, columns, unchanged))
    normal = {rom[0x7fe+c*8+r]:(1 << c, 1 << r) for c in range(8) for r in range(8)}
    sequences = [(44, 1, (0x31, 0x35)), (44, 1, (0x32, 0xe1, 0x33)),
                 (44, 1, (0x33, 0xe3, 0x31, 0x31)),
                 (45, 1, (0x31, 0x32)), (45, 1, (0x33, 0xe3, 0x32, 0x31)),
                 (12, 0, (0x32, 0x31)), (19, 0, (0x32, 0x32)), (44, 1, (0xe6,))]
    for page, mode_entry, tokens in sequences:
        prepare(); state = BankMenu(); m.er(0, page | mode_entry << 8)
        assert lib.fx_mode_bank_menu_begin(C.byref(p), C.byref(state), page, mode_entry) == 0
        run(0x1d8a4, 0xd0cc); equal('full_bank_menu_begin', (page, mode_entry))
        for index, token in enumerate(tokens):
            pair = normal[token]
            for a, v in ((0x8e01, pair[0]), (0x8e02, pair[1])): ram[a] = m.ram[a] = v
            status = lib.fx_mode_bank_menu_tick(C.byref(p), C.byref(state))
            run(0xe04e)
            if status == 4:
                run(0x53ce); equal('full_bank_menu_timer_request', (page, index))
                status = lib.fx_mode_bank_menu_resume_timer(C.byref(p), C.byref(state))
            run(0x2fffe if status == 1 else 0x1d8a4)
            equal('full_bank_menu_raw_sequence', (page, mode_entry, tokens, index))
            if status == 1:
                assert state.result == m.reg(0) and index == len(tokens)-1
    # Genuine parent MODE -> D0CC request -> MATRIX definition -> MODE return.
    prepare(0xc1); parent = ModeSetup(); state = BankMenu()
    assert lib.fx_mode_menu_begin(C.byref(p), C.byref(parent)) == 0
    run(0x1d8a4, 0xc978)
    for a, v in ((0x8e01, normal[0x36][0]), (0x8e02, normal[0x36][1])): ram[a] = m.ram[a] = v
    assert lib.fx_mode_setup_tick(C.byref(p), C.byref(parent)) == 5
    run(0xd0cc); equal('true_parent_MODE_matrix_request', 6)
    assert lib.fx_mode_bank_menu_begin(C.byref(p), C.byref(state), 44, 1) == 0
    run(0x1d8a4); equal('true_parent_MODE_matrix_begin', 6)
    for token in (0x31, 0x35):
        for a, v in ((0x8e01, normal[token][0]), (0x8e02, normal[token][1])): ram[a] = m.ram[a] = v
        status = lib.fx_mode_bank_menu_tick(C.byref(p), C.byref(state))
        run(0xc9e8 if status == 1 else 0x1d8a4)
        equal('true_parent_MODE_matrix_definition', token)
    assert state.result == 0xff
    assert lib.fx_mode_setup_accept_handler(C.byref(p), C.byref(parent), state.result) == 1
    run(0x2fffe); equal('true_parent_MODE_matrix_completion', 6)
    assert parent.result == m.reg(0) == 6
    for page, mode_entry in ((12, 0), (19, 0), (44, 1), (45, 1)):
        prepare(); state = BankMenu(); m.er(0, page | mode_entry << 8)
        assert lib.fx_mode_bank_menu_begin(C.byref(p), C.byref(state), page, mode_entry) == 0
        run(0x1d8a4, 0xd0cc)
        for index in range(16):
            assert lib.fx_mode_bank_menu_tick(C.byref(p), C.byref(state)) == 0
            run(0x1d8a6); run(0x1d8d2)
            equal('full_bank_menu_idle_iterations', (page, index))
        for column in (0x20, 0x40, 0x80):
            for a, v in ((0x8e01, column), (0x8e02, 0x80)): ram[a] = m.ram[a] = v
            assert lib.fx_mode_bank_menu_tick(C.byref(p), C.byref(state)) == 3
            run(0x1d8a4); equal('full_bank_menu_host_export', (page, column))
        for a, v in ((0x8e01, 0x10), (0x8e02, 0x80)): ram[a] = m.ram[a] = v
        assert lib.fx_mode_bank_menu_tick(C.byref(p), C.byref(state)) == 2
        run(0x1824e); equal('full_bank_menu_host_reset_request', page)
    saved = bytes(ram); inactive = BankMenu()
    assert lib.fx_mode_bank_menu_tick(None, C.byref(inactive)) == -1
    assert lib.fx_mode_bank_menu_tick(C.byref(p), C.byref(inactive)) == -1
    assert lib.fx_mode_bank_ensure_dimensions(C.byref(p), 9, 2, 3) == -1
    assert bytes(ram) == saved; bounds['invalid_arguments'] = 3
    headers, pending = set(), [ROOT/f for f in SOURCES]
    while pending:
        source = pending.pop()
        for include in re.findall(r'^\s*#include\s+"([^"]+)"', source.read_text(), re.M):
            dep = (source.parent/include).resolve(); name = str(dep.relative_to(ROOT))
            if name not in headers: headers.add(name); pending.append(dep)
    report = {'cases':sum(counts.values())+sum(bounds.values()), 'native_cases':sum(counts.values()),
              'groups':counts, 'bounds_cases':sum(bounds.values()), 'bounds_groups':bounds,
              'comparison':'Complete observable RAM/MMIO, F000 write observer and actual return byte; only CPU stack8B00..8DED excluded.',
              'limits':['Prepared D2A0 fixtures preserve a genuine caller frame but supply the generic-menu selection/result pair.',
                        'Physical STOP/IRQ timing remains host-owned. No operand-workspace or ready-flag exclusions are used.']}
    report = write_report('analysis/c-verification/mode_bank_menu.json', report,
                          SOURCES+sorted(headers)+['tools/c_verification.py', 'tools/test_platform_c.py',
                          'tools/test_mode_setup_c.py', 'tools/test_menu_navigator_c.py', 'tools/test_key_controller_c.py',
                          'tools/test_key_wait_c.py', 'tools/test_boot_events_c.py', 'tools/test_boot_c.py',
                          'tools/test_diagnostic_contrast_c.py'], 'tools/test_mode_bank_menu_c.py')
    print(json.dumps(report, indent=2))


if __name__ == '__main__': main()
