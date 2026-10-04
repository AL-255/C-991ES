#!/usr/bin/env python3
"""Genuine reset through the main caller, UI completion and raw keyboard input.

All native continuations remain live from6F82. Original instructions execute
only in the independent oracle. Numeric evaluation scratch is explicitly
inventoried rather than presented as complete observable-RAM parity.
GPL-3.0-only.
"""
import argparse
import ctypes as C
import json
import random
import subprocess

from c_build_inputs import implementation_inputs
from c_verification import ROOT, write_report
from nxu8.machine import Machine
from test_main_loop_c import Main, SOURCES as MAIN_SOURCES
from test_platform_c import Platform
from test_ui_controller_c import Controller as UI, Control, MODULES


SOURCES = sorted(set(MAIN_SOURCES + [
    'csrc/ui/fx_ui_controller.c', 'csrc/ui/fx_construct_editor.c',
    *['csrc/'+module+'.c' for module in MODULES]]))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--no-report', action='store_true')
    args = ap.parse_args()
    build = ROOT/'analysis/build/boot-main-ui'
    build.mkdir(parents=True, exist_ok=True)
    output = build/'controller.so'
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-shared', '-fPIC', '-Wl,--no-undefined',
                    *[str(ROOT/source) for source in SOURCES], '-o', str(output)], check=True)
    lib = C.CDLL(str(output))
    pp, ms, us = C.POINTER(Platform), C.POINTER(Main), C.POINTER(UI)
    lib.fx_boot_reset.argtypes = [pp]
    lib.fx_main_loop_begin.argtypes = [ms]
    lib.fx_main_loop_tick.argtypes = [pp, ms]
    lib.fx_main_loop_accept_handler.argtypes = [pp, ms, C.c_uint8]
    lib.fx_ui_controller_begin.argtypes = [pp, us, C.c_uint8, C.POINTER(Control)]
    lib.fx_ui_controller_tick.argtypes = [pp, us]
    lib.fx_ui_controller_finish.argtypes = [us, C.POINTER(C.c_uint8)]
    lib.fx_take_callback.argtypes = [pp]
    rom = (ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    rom_data = (C.c_uint8*len(rom)).from_buffer_copy(rom)
    ram = (C.c_uint8*65536)()
    platform = Platform(rom_data, len(rom), ram, 0, 0)
    native = Machine(rom, build/'oracle')
    pairs = {rom[0x7fe+column*8+row]: (1 << column, 1 << row)
             for column in range(8) for row in range(8)}
    counts, residuals = {}, []

    def count(group):
        counts[group] = counts.get(group, 0)+1

    def run(stop):
        # No PC/register/stack replacement occurs between reset and later
        # checkpoints. The native call chain supplies its real continuations.
        status = native.lib.harness_run(50000000, stop, False)
        assert status == 100, (status, hex(native.lib.harness_get_pc()), hex(stop))

    def compare(stage, numeric_evaluation=False):
        differences = [(address, ram[address], native.ram[address])
                       for address in range(65536)
                       if not 0x8b00 <= address < 0x8dee and
                       ram[address] != native.ram[address]]
        unexpected = [difference for difference in differences
                      if not numeric_evaluation or not 0x8000 <= difference[0] < 0x80dc]
        assert not unexpected, (stage, [(hex(a), c, n) for a, c, n in unexpected[:30]])
        assert lib.fx_take_callback(C.byref(platform)) == native.lib.harness_callback(), (stage, 'callback')
        if numeric_evaluation:
            residuals.append({'stage': stage, 'different_bytes': len(differences),
                              'bytes': [(hex(a), c, n) for a, c, n in differences]})
        count('numeric_evaluation_with_disclosed_scratch' if numeric_evaluation
              else 'complete_observable_RAM_MMIO_F000_observer')

    # Retained fixtures derive their settings from a verified original cold
    # boot snapshot. They change only the retained calculation mode/signature.
    for port in (0, 3, 7):
        for mode in (None, 0xc1, 0xc4):
            initial = bytearray(random.Random(0x991+port).randbytes(65536))
            initial[0xf040], initial[0xf050] = 255, port
            if mode is not None:
                initial = bytearray(cold_settings)
                initial[0x860e:0x861d] = bytes(range(15, 0, -1))
                initial[0x8226:0x828a] = bytes(100)
                initial[0x80dc], initial[0x80f9], initial[0x8112] = port, mode, 17
            native.reset()
            C.memmove(native.ram, bytes(initial), 65536)
            C.memmove(ram, bytes(initial), 65536)
            platform.callback_pending = platform.status = 0
            caller = Main()
            assert lib.fx_boot_reset(C.byref(platform)) == 0
            lib.fx_main_loop_begin(C.byref(caller))
            assert lib.fx_main_loop_tick(C.byref(platform), C.byref(caller)) == 4
            assert caller.pending_request == 1
            native.lib.harness_set_pc(0x6f82)
            run(0xd9ee)
            compare((port, mode, 'initial_UI_entry'))
            if mode is None:
                cold_settings = bytes(native.ram)

            for token in (None, 0x31, 0x2b, 0x32, 0xf0):
                if token is not None:
                    columns, rows = pairs[token]
                    ram[0x8e01] = native.ram[0x8e01] = columns
                    ram[0x8e02] = native.ram[0x8e02] = rows
                    assert lib.fx_main_loop_tick(C.byref(platform), C.byref(caller)) == 4
                    assert caller.pending_request == 1
                    run(0xd9ee)
                    compare((port, mode, token, 'actual_key_to_UI'))
                ui = UI()
                assert lib.fx_ui_controller_begin(C.byref(platform), C.byref(ui), 0, None) == 4
                run(0xda58)
                compare((port, mode, token, 'UI_preparation'))
                for _ in range(5):
                    status = lib.fx_ui_controller_tick(C.byref(platform), C.byref(ui))
                    if status != 4:
                        break
                assert status == 1, (port, mode, token, status, ui.request)
                run(0xd87e)
                evaluating = token == 0xf0
                compare((port, mode, token, 'UI_completion'), evaluating)
                returned = C.c_uint8()
                assert lib.fx_ui_controller_finish(C.byref(ui), C.byref(returned)) == 1
                assert returned.value == native.reg(0)
                assert lib.fx_main_loop_accept_handler(C.byref(platform), C.byref(caller), returned) == 1
                run(0xd7b4)
                compare((port, mode, token, 'caller_completion'), evaluating)
                assert caller.wait_required == native.reg(5)
                assert caller.last_menu_result == native.reg(4)
                if evaluating:
                    assert bytes(ram[0x8140:0x814a]) == bytes.fromhex('03000000000000000001')
                    assert bytes(ram[0x814a:0x8154]) == bytes(10)
                    count('literal_1_plus_2_result')
                # The GUI host releases its matrix pair between completed
                # actions. Apply that external event equally to C and oracle.
                ram[0x8e01] = native.ram[0x8e01] = 0
                ram[0x8e02] = native.ram[0x8e02] = 0
                assert lib.fx_main_loop_tick(C.byref(platform), C.byref(caller)) == 0
                run(0x1d8a4)
                compare((port, mode, token, 'actual_next_wait'), evaluating)

    report = {
        'cases': sum(counts.values()), 'domains': counts,
        'scope': 'Live original6F82 continuation through bootE6/UI/main/first wait and raw1,+,2,EXE; cold and retained COMP/CMPLX, F050ports0/3/7.',
        'comparison': 'Complete observable RAM/MMIO and the harness F000-write observer through typing; CPU stack8B00..8DED excluded. After EXE only numeric workspace8000..80DB is exempted and every differing byte is inventoried; all remaining RAM, display, results, Ans/replay and observer are compared.',
        'numeric_scratch_residuals': residuals,
        'limits': ['Ordinary natural/default settings only; linear formatted-zero boot scratch is a separate disclosed boot limitation.',
                   'Numeric evaluator/formatter scratch serialization is not complete; residual entries prevent a full-RAM evaluation claim.',
                   'The F000-write observer is a test/platform convention, distinct from original Windows SimU8 STOP callback service. This passive-peripheral oracle does not emulate its interrupt injection.',
                   'Physical GUI timer cadence, menus and specialized controller request bodies are outside this ordinary sequence.']}
    if not args.no_report:
        dependencies = implementation_inputs(ROOT, SOURCES)+[
            'tools/test_main_loop_c.py', 'tools/test_ui_controller_c.py',
            'tools/test_input_controller_c.py', 'tools/test_error_event_c.py',
            'tools/test_key_controller_c.py', 'tools/test_key_wait_c.py',
            'tools/test_boot_events_c.py', 'tools/test_boot_c.py',
            'tools/test_diagnostic_contrast_c.py', 'tools/test_platform_c.py',
            'tools/trace_natural_result.py', 'tools/verify_firmware.py',
            'tools/nxu8/decoder.py',
            'tools/c_build_inputs.py', 'tools/c_verification.py']
        report = write_report('analysis/c-verification/boot_main_ui.json', report,
                              dependencies, 'tools/test_boot_main_ui_c.py')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
