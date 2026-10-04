#!/usr/bin/env python3
"""Full observable native DFDE menu painting, choices, waits and delay phases."""
import argparse
import ctypes as C
import json
import random
import re
import subprocess
from c_verification import ROOT, write_report
from nxu8.machine import Machine
from test_platform_c import Platform
from test_key_controller_c import Controller
from test_boot_events_c import MODULES


class Menu(C.Structure):
    _fields_ = [('keys', Controller), ('heading', C.c_uint16),
                ('timer_period', C.c_uint16), *[(n, C.c_uint8) for n in
                ('page', 'selection', 'result', 'mode_close_policy', 'phase',
                 'cancel_after_timer', 'active')]]


SOURCES = ['csrc/'+m+'.c' for m in [*MODULES, 'ui/fx_menu_navigator']]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--pages', type=int, default=63)
    args = ap.parse_args()
    build = ROOT/'analysis/build/menu-navigator'; build.mkdir(parents=True, exist_ok=True)
    library = build/'menu.so'
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-shared', '-fPIC', '-Wl,--no-undefined',
                    *[str(ROOT/f) for f in SOURCES], '-o', str(library)], check=True)
    lib = C.CDLL(str(library)); pp, ss = C.POINTER(Platform), C.POINTER(Menu)
    lib.fx_menu_navigator_begin.argtypes = [pp, ss, C.c_uint8, C.c_uint16]
    lib.fx_menu_navigator_tick.argtypes = [pp, ss]
    lib.fx_menu_navigator_accept_token.argtypes = [pp, ss, C.c_uint8]
    lib.fx_menu_navigator_resume_timer.argtypes = [pp, ss]
    lib.fx_menu_navigator_finish.argtypes = [ss, C.POINTER(C.c_uint8), C.POINTER(C.c_uint8)]
    lib.fx_menu_paint_lines.argtypes = [pp, C.POINTER(C.c_uint16)]
    lib.fx_menu_paint_body.argtypes = [pp, C.c_uint16, C.c_uint16]
    lib.fx_take_callback.argtypes = [pp]; lib.fx_take_callback.restype = C.c_uint8
    rom = (ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    rd = (C.c_uint8*len(rom)).from_buffer_copy(rom); ram = (C.c_uint8*65536)()
    p = Platform(rd, len(rom), ram, 0, 0); m = Machine(rom, build/'oracle')
    rng = random.Random(0xdfde); background = bytearray(rng.randbytes(65536))
    background[0x8dee:0x8e00] = rom[0x1f8be:0x1f8d0]
    counts, bounds = {}, {}
    def count(group): counts[group] = counts.get(group, 0)+1
    def prepare(menu=1):
        m.reset(); C.memmove(m.ram, bytes(background), 65536)
        for a, v in [(0x80f9, 0xc1), (0x80fb, menu), (0x80fc, 1), (0x80fe, 1),
                     (0x80f8, 0), (0x80f4, 0), (0x80dd, 0), (0x80f5, 0xe4),
                     (0x8102, 0), (0x8105, 4), (0x8106, 1), (0x8112, 17),
                     (0x8114, 0), (0x8117, 1), (0x8118, 0), (0x8119, 1),
                     (0x811a, 0x7c), (0x811b, 10), (0x811f, 10), (0x8120, 0),
                     (0x8121, 1), (0x8127, 0), (0x8128, 0), (0x8129, 0),
                     (0x8e00, 0), (0x8e01, 0), (0x8e02, 0), (0xf040, 255)]:
            m.ram[a] = v
        for a in (0x8226, 0x8408): m.ram[a:a+10] = bytes(10)
        for a in (0x8154, 0x81b8): m.ram[a:a+100] = bytes(100)
        C.memmove(ram, m.ram, 65536); p.callback_pending = p.status = 0
        m.lib.harness_set_sp(0x8de0); m.lib.harness_set_lr(0x2fffe)
    def run(stop, entry=None):
        if entry is not None: m.lib.harness_set_pc(entry)
        if m.lib.harness_get_pc() == stop:
            assert m.lib.harness_run(1, 0x2fffe, False) == 103
        status = m.lib.harness_run(3000000, stop, False)
        assert status == 100, (status, hex(m.lib.harness_get_pc()), hex(stop))
    def equal(group, detail):
        actual, expected = bytes(ram), bytes(m.ram)
        assert actual[:0x8b00] == expected[:0x8b00] and actual[0x8dee:] == expected[0x8dee:], (
            group, detail, [(hex(a), actual[a], expected[a]) for a in range(65536)
                            if not 0x8b00 <= a < 0x8dee and actual[a] != expected[a]][:24])
        assert lib.fx_take_callback(C.byref(p)) == m.lib.harness_callback()
        count(group)
    def begin(page, heading=0, menu=1, prepared=False):
        prepare(menu); m.ram[0x8de1] = page; m.er(0, 0x8de1); m.er(2, heading)
        state = Menu(); assert lib.fx_menu_navigator_begin(C.byref(p), C.byref(state), page, heading) == 0
        run(0xe04a if prepared else 0x1d8a4, 0xdfde)
        if prepared:
            # Genuine DFDE frame at its key-call boundary. The prepared token
            # adapter begins after that call, with native RAM as its input.
            C.memmove(ram, m.ram, 65536); p.callback_pending = p.status = 0
            m.lib.harness_callback()
        else: equal('full_entry_menu_paint_and_wait', (page, heading, menu))
        return state
    def finish_native(state, status, detail):
        if status == 4:
            run(0x53ce); equal('prepared_delay_request', detail)
            saved = bytes(ram); assert lib.fx_menu_navigator_tick(C.byref(p), C.byref(state)) == 4
            assert bytes(ram) == saved; bounds['retained_delay'] = bounds.get('retained_delay', 0)+1
            status = lib.fx_menu_navigator_resume_timer(C.byref(p), C.byref(state))
            assert status in (0, 1)
        run(0x2fffe if status == 1 else 0x1d8a4)
        equal('prepared_token_complete_or_wait', detail)
        if status == 1:
            assert state.selection == m.ram[0x8de1] and state.result == m.reg(0), (
                detail, state.selection, m.ram[0x8de1], state.result, m.reg(0))
            selected, result = C.c_uint8(), C.c_uint8()
            assert lib.fx_menu_navigator_finish(C.byref(state), C.byref(selected), C.byref(result)) == 1
            assert (selected.value, result.value) == (m.ram[0x8de1], m.reg(0))
        else:
            assert state.heading == m.er(10), (detail, state.heading, m.er(10))
        return status

    for page in range(args.pages):
        for heading in (0, 0xffff, 0x11a1, 0x1321): begin(page, heading)
    # Actual table pages0..62, every token byte and both close policies.
    for page in range(args.pages):
        for heading in (0, 0xffff):
            for token in range(256):
                state = begin(page, heading, prepared=True)
                status = lib.fx_menu_navigator_accept_token(C.byref(p), C.byref(state), token)
                assert status in (0, 1, 4), (page, heading, token, status)
                m.reg(0, token); m.lib.harness_set_pc(0xe04e)
                finish_native(state, status, (page, heading, token))
    for menu in (0, 2, 255):
        for page in (1, 2, 17, 47, 48, 50):
            close = rom[0xb9a+16*page+15]
            for heading in (0, 0xffff, 0x1321):
                state = begin(page, heading, menu, prepared=True)
                status = lib.fx_menu_navigator_accept_token(C.byref(p), C.byref(state), close)
                m.reg(0, close); m.lib.harness_set_pc(0xe04e)
                finish_native(state, status, ('close', menu, page, heading))
    # All normal raw keys through the actual nested keyboard lifecycle.
    normal = {rom[0x7fe+c*8+r]: (1 << c, 1 << r) for c in range(8) for r in range(8)}
    for page in (2, 43, 47, 48):
        for token in (0x31, 0x32, 0x35, 0xe0, 0xe1, 0xe3, 0xe6):
            state = begin(page, 0xffff if page == 47 else 0)
            pair = normal[token]
            for a, v in ((0x8e01, pair[0]), (0x8e02, pair[1])): ram[a] = m.ram[a] = v
            status = lib.fx_menu_navigator_tick(C.byref(p), C.byref(state))
            run(0xe04e)
            finish_native(state, status, ('raw', page, token))
    for heading, body in ((0, 0x9be), (0x1321, 0x9be), (0x1321, 0), (0, 0)):
        prepare(); lib.fx_menu_paint_body(C.byref(p), heading, body)
        if heading: m.er(0, heading); m.er(2, body); m.call(0x3fee)
        else: m.er(0, body); m.call(0x400c)
        equal('standalone_body_heading_painter', (heading, body))
    for caption in (0x11b2, 0x11bb, 0x11c4, 0x9be):
        prepare(); lines = (C.c_uint16*4)(caption, 0x11a1, 0x11a1, 0x11a1)
        lib.fx_menu_paint_lines(C.byref(p), lines)
        m.er(0, caption); m.er(2, 0x11a1)
        m.word(0x8dee, 0x11a1); m.word(0x8df0, 0x11a1); m.call(0x3fba)
        # Standalone native call uses argument words over startup data; those
        # are caller arguments, restored after the comparison's live stores.
        ram[0x8dee:0x8df2] = m.ram[0x8dee:0x8df2]
        equal('standalone_four_explicit_lines', caption)
    saved = bytes(ram); inactive = Menu()
    assert lib.fx_menu_navigator_tick(None, C.byref(inactive)) == -1
    assert lib.fx_menu_navigator_tick(C.byref(p), None) == -1
    assert lib.fx_menu_navigator_tick(C.byref(p), C.byref(inactive)) == -1
    assert lib.fx_menu_navigator_resume_timer(C.byref(p), C.byref(inactive)) == -1
    assert bytes(ram) == saved; bounds['invalid_arguments'] = 4
    headers, pending = set(), [ROOT/f for f in SOURCES]
    while pending:
        source = pending.pop()
        for include in re.findall(r'^\s*#include\s+"([^"]+)"', source.read_text(), re.M):
            dep = (source.parent/include).resolve(); name = str(dep.relative_to(ROOT))
            if name not in headers: headers.add(name); pending.append(dep)
    report = {'cases': sum(counts.values())+sum(bounds.values()), 'native_cases': sum(counts.values()),
              'groups': counts, 'bounds_cases': sum(bounds.values()), 'bounds_groups': bounds,
              'comparison': 'Complete observable RAM/MMIO, F000 write observer, native selected byte and result; only CPU stack8B00..8DED excluded.',
              'limits': ['The 0770 delay is a retained host timer request; physical STOP/IRQ scheduling is external.',
                         'Prepared E04E fixtures preserve a genuine native menu frame but deliver the semantic token directly.',
                         'Table pages0..62 are actual menu data; arbitrary pages that alias CPU-frame text are outside the fixture domain.']}
    report = write_report('analysis/c-verification/menu_navigator.json', report,
                          SOURCES+sorted(headers)+['tools/c_verification.py', 'tools/test_platform_c.py',
                          'tools/test_key_controller_c.py', 'tools/test_key_wait_c.py', 'tools/test_boot_events_c.py',
                          'tools/test_boot_c.py', 'tools/test_diagnostic_contrast_c.py'], 'tools/test_menu_navigator_c.py')
    print(json.dumps(report, indent=2))


if __name__ == '__main__': main()
