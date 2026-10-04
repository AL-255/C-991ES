#!/usr/bin/env python3
"""Compare complete prepared CALC/SOLVE lifecycles with fresh original ROM.

Input-only recipes retain102 whole-cycle controls and450 CALC/error/load
checkpoints. Expected state always comes from the unmodified original CPU.
All raw RAM differences and exact exclusions remain in the evidence.
GPL-3.0-or-later.
"""
import argparse
import ctypes as C
import gzip
import hashlib
import importlib.util
import json
import re
import subprocess
from collections import Counter
from pathlib import Path
from c_build_inputs import implementation_inputs
from c_verification import ROOT, write_report
from nxu8.machine import Machine
from test_platform_c import Platform
from test_main_loop_c import Main
from test_ui_controller_c import Controller as UI
FIXTURE = ROOT / 'tools/eval_solve_outer_inputs.py'
INPUT_CATALOG = 'analysis/native-fixtures/solve-outer/inputs.json'
OBSERVER = 'tools/nxu8/solve_outer_host_events.c'
SHIM = 'tools/nxu8/solve_outer_state.c'

def collect_original(rom, build):
    """Execute both input recipes afresh; retain uninterrupted original state."""
    native_path = build / 'outer-oracle.so'
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC', str(ROOT / OBSERVER), str(ROOT / 'tools/nxu8/vendor/SimU8/core.c'), '-o', str(native_path)], check=True)
    machine = Machine(rom, build / 'native')
    old = machine.lib
    observer = C.CDLL(str(native_path))
    for name in ('harness_init', 'harness_ram', 'harness_set_reg', 'harness_get_reg', 'harness_set_pc', 'harness_get_pc', 'harness_set_sp', 'harness_get_sp', 'harness_set_lr'):
        getattr(observer, name).argtypes = getattr(old, name).argtypes
        getattr(observer, name).restype = getattr(old, name).restype
    machine.lib = observer
    machine.ram = observer.harness_ram().contents
    spec = importlib.util.spec_from_file_location('solve_outer_input_recipes', FIXTURE)
    fixtures = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixtures)
    with gzip.open(build / 'base-original-snapshots.jsonl.gz', 'wt') as base_stream, gzip.open(build / 'calc-original-snapshots.jsonl.gz', 'wt') as lifecycle_stream:
        return fixtures.collect(machine, observer, base_stream, lifecycle_stream)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--optimization', choices=('-O2', '-O3'), default='-O2')
    parser.add_argument('--no-report', action='store_true')
    args = parser.parse_args()
    build = ROOT / 'analysis/build/solve-outer'
    build.mkdir(parents=True, exist_ok=True)
    listed = ['csrc/' + name for name in re.findall('(?<![\\w/])([\\w/]+\\.c)(?!\\w)', (ROOT / 'csrc/CMakeLists.txt').read_text().split('target_include_directories')[0])]
    sources = list(dict.fromkeys(listed + ['csrc/ui/fx_calc_scan.c', 'csrc/ui/fx_solve_outer.c', 'csrc/ui/fx_error_boundary.c']))
    dependencies = implementation_inputs(ROOT, sources) + ['csrc/CMakeLists.txt', 'tools/test_platform_c.py', 'tools/test_main_loop_c.py', 'tools/test_ui_controller_c.py', 'tools/test_input_controller_c.py', 'tools/test_error_event_c.py', 'tools/test_key_controller_c.py', 'tools/test_key_wait_c.py', 'tools/test_boot_c.py', 'tools/c_build_inputs.py', 'tools/c_verification.py', 'tools/nxu8/machine.py', 'tools/nxu8/harness.c', 'tools/nxu8/vendor/SimU8/core.c', 'firmware/fx-991es-plus-c-ver4.bin', str(FIXTURE.relative_to(ROOT)), INPUT_CATALOG, OBSERVER, SHIM, 'tools/test_solve_outer_c.py']
    dependencies += ['tools/test_boot_events_c.py', 'tools/test_diagnostic_contrast_c.py',
        'tools/trace_natural_result.py', 'tools/verify_firmware.py', 'tools/nxu8/decoder.py']
    dependencies += [str(path.relative_to(ROOT)) for path in (ROOT / 'tools/nxu8/vendor/SimU8').glob('*.h')]
    dependencies = sorted(set(dependencies))
    pins = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in dependencies}
    rom = (ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    base_native, lifecycle_native = collect_original(rom, build)
    shared = build / 'solve-outer.so'
    subprocess.run(['gcc', '-std=c99', args.optimization, '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC', '-Wl,--no-undefined', '-I', str(ROOT / 'csrc'), *[str(ROOT / name) for name in sources], str(ROOT / SHIM), '-o', str(shared)], check=True)
    lib = C.CDLL(str(shared))
    pp = C.POINTER(Platform)
    lib.outer_test_new.restype = C.c_void_p
    lib.outer_test_begin.argtypes = [C.c_void_p]
    lib.outer_test_free.argtypes = [C.c_void_p]
    lib.outer_test_dispatch.argtypes = [pp, C.c_void_p, C.c_uint, C.c_uint]
    lib.outer_test_action.argtypes = lib.outer_test_return.argtypes = [C.c_void_p]
    lib.fx_main_loop_begin.argtypes = [C.POINTER(Main)]
    lib.fx_main_loop_accept_token.argtypes = [pp, C.POINTER(Main), C.c_uint8]
    lib.fx_main_loop_tick.argtypes = [pp, C.POINTER(Main)]
    lib.fx_main_loop_accept_handler.argtypes = [pp, C.POINTER(Main), C.c_uint8]
    lib.fx_ui_controller_begin.argtypes = [pp, C.POINTER(UI), C.c_uint8, C.c_void_p]
    lib.fx_ui_controller_tick.argtypes = [pp, C.POINTER(UI)]
    lib.fx_ui_controller_finish.argtypes = [C.POINTER(UI), C.POINTER(C.c_uint8)]
    rom = (ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    rb = (C.c_uint8 * len(rom)).from_buffer_copy(rom)
    ram = (C.c_uint8 * 0x10000)()
    p = Platform(rb, len(rom), ram, 0, 0)
    rows = []
    for line in gzip.open(build / 'base-original-snapshots.jsonl.gz', 'rt'):
        native = json.loads(line)
        before = bytes.fromhex(native['before'])
        expected = bytes.fromhex(native['after'])
        C.memmove(ram, before, 0x10000)
        p.callback_pending = p.status = 0
        state = lib.outer_test_new()
        lib.outer_test_begin(state)
        main = Main()
        lib.fx_main_loop_begin(C.byref(main))
        main.wait_required = native['pre']['wait_required']
        entry = int(native['entry'], 16)
        request = 0
        status = 1
        outer = None
        action = None
        returned = None
        if entry == 0xd9ee:
            ram[0x80f5] = native['supplied_token']
            ram[0x80f7] = 1
            refresh = int('refresh' in native['name'])
            if ram[0x80fc] == 1:
                ui = UI()
                lib.fx_ui_controller_begin(C.byref(p), C.byref(ui), refresh, None)
                status = lib.fx_ui_controller_tick(C.byref(p), C.byref(ui))
                output = C.c_uint8()
                lib.fx_ui_controller_finish(C.byref(ui), C.byref(output))
                returned = output.value
            else:
                request = 1
                outer = lib.outer_test_dispatch(C.byref(p), state, request, refresh)
                returned = lib.outer_test_return(state)
                action = lib.outer_test_action(state)
        else:
            status = lib.fx_main_loop_accept_token(C.byref(p), C.byref(main), native['supplied_token']) if entry == 0xd7c2 else lib.fx_main_loop_tick(C.byref(p), C.byref(main))
            if status == 4:
                request = main.pending_request
                outer = lib.outer_test_dispatch(C.byref(p), state, request, 0)
                returned = lib.outer_test_return(state)
                action = lib.outer_test_action(state)
                if outer == 1:
                    status = lib.fx_main_loop_accept_handler(C.byref(p), C.byref(main), returned)
        actual = bytes(ram)
        numeric = any((e['meaning'] == 'evaluate' for e in native['events'])) or any((e['meaning'] == 'coefficient_or_guess_prompt' for e in native['events'])) or 'refresh' in native['name']
        exclusions = [(native['stack_floor'], 0x8dee, 'measured original CPU frame')]
        if numeric:
            exclusions.extend([(0x8000, 0x80dc, 'held numeric/formatter workspace'), (0x8640, 0x87d0, 'held evaluator workspace')])
        differences = [{'address': f'{a:04x}', 'native': expected[a], 'actual': actual[a]} for a in range(0x10000) if actual[a] != expected[a] and (not any((lo <= a < hi for lo, hi, _ in exclusions)))]
        wait_expected = native['post']['wait_required'] if entry != 0xd9ee else next((e['context']['return_value'] for e in reversed(native['events']) if e['meaning'] == 'UI_context_return'), None)
        wait_actual = main.wait_required if entry != 0xd9ee else returned
        rows.append(dict(raw_differences=[dict(address=f'{a:04x}', native=expected[a], actual=actual[a]) for a in range(0x10000) if actual[a] != expected[a]], name=native['name'], request=request, main_status=status, outer_status=outer, action=action, returned=returned, wait_native=wait_expected, wait_actual=wait_actual, wait_match=wait_actual == wait_expected, callback_match=p.callback_pending == native['callback_pending'], callback_native=native['callback_pending'], callback_actual=p.callback_pending, differences=differences, workspace_boundaries=exclusions))
        lib.outer_test_free(state)
    observations = [json.loads(line) for line in gzip.open(build / 'base-original-snapshots.jsonl.gz', 'rt')]
    continuous = []
    for math in (0, 1):
        sequence = observations[math * 9:(math + 1) * 9]
        C.memmove(ram, bytes.fromhex(sequence[0]['before']), 0x10000)
        p.callback_pending = p.status = 0
        state = lib.outer_test_new()
        lib.outer_test_begin(state)
        main = Main()
        lib.fx_main_loop_begin(C.byref(main))
        main.wait_required = 1
        numeric_workspace_used = False
        for native in sequence:
            entry = int(native['entry'], 16)
            status = lib.fx_main_loop_accept_token(C.byref(p), C.byref(main), native['supplied_token']) if entry == 0xd7c2 else lib.fx_main_loop_tick(C.byref(p), C.byref(main))
            request = main.pending_request
            outer = None
            if status == 4:
                outer = lib.outer_test_dispatch(C.byref(p), state, request, 0)
                if outer == 1:
                    status = lib.fx_main_loop_accept_handler(C.byref(p), C.byref(main), lib.outer_test_return(state))
            numeric_workspace_used |= any((e['meaning'] in ('evaluate', 'coefficient_or_guess_prompt') for e in native['events']))
            exclusions = [(native['stack_floor'], 0x8dee, 'cumulative original measured CPU frame')]
            if numeric_workspace_used:
                exclusions.extend([(0x8000, 0x80dc, 'held numeric/formatter workspace'), (0x8640, 0x87d0, 'held evaluator workspace')])
            expected = bytes.fromhex(native['after'])
            actual = bytes(ram)
            differences = [{'address': f'{a:04x}', 'native': expected[a], 'actual': actual[a]} for a in range(0x10000) if actual[a] != expected[a] and (not any((lo <= a < hi for lo, hi, _ in exclusions)))]
            continuous.append(dict(raw_differences=[dict(address=f'{a:04x}', native=expected[a], actual=actual[a]) for a in range(0x10000) if actual[a] != expected[a]], name=native['name'], main_status=status, outer_status=outer, wait_match=main.wait_required == native['post']['wait_required'], callback_match=p.callback_pending == native['callback_pending'], differences=differences, workspace_boundaries=exclusions))
            p.callback_pending = 0
        lib.outer_test_free(state)
    base_report = dict(cases=len(rows), equal_rows=sum((r['main_status'] == 1 and r['outer_status'] in (None, 1) and (not r['differences']) and r['wait_match'] and r['callback_match'] for r in rows)), continuous_equal=sum((r['main_status'] == 1 and r['outer_status'] == 1 and (not r['differences']) and r['wait_match'] and r['callback_match'] for r in continuous)), rows=rows, continuous=continuous)
    lib.outer_test_pending.argtypes = [C.c_void_p]
    lib.outer_test_size.restype = C.c_size_t
    lib.outer_test_adopt.argtypes = lib.outer_test_restore.argtypes = [pp, C.c_void_p]
    lib.outer_test_load.argtypes = [pp, C.c_uint, C.c_uint]
    originals = [json.loads(line) for line in gzip.open(build / 'calc-original-snapshots.jsonl.gz', 'rt')]
    metadata = {v['name']: v for v in lifecycle_native}
    lib.outer_test_cancel_at.argtypes = [C.c_void_p, C.c_uint]
    lib.outer_test_polls.argtypes = [C.c_void_p]
    lib.outer_test_poll_X.argtypes = [C.c_void_p, C.c_uint, C.POINTER(C.c_uint8)]
    results = []
    ownership_checks = []

    def compare(native, state, main, outer, stage):
        actual = bytes(ram)
        expected = bytes.fromhex(native['after'])
        exclusions = [(native['stack_floor'], 0x8dee, 'measured actual native CPU frame')]
        numeric = any((e['meaning'] in ('evaluate', 'coefficient_or_guess_prompt', 'load_coefficient_pair', 'decimalize_display_reference') for e in native['events'])) or stage in ('continuation', 'continuous_CALC', 'continuous_SUM', 'continuous_result') or native['name'].startswith('load51CA_SURD')
        if numeric:
            exclusions.extend([(0x8000, 0x80dc, 'held numeric/formatter workspace'), (0x8640, 0x87d0, 'held evaluator workspace')])
        raw_differences = [dict(address=f'{a:04x}', native=expected[a], actual=actual[a]) for a in range(0x10000) if actual[a] != expected[a]]
        differences = [dict(address=f'{a:04x}', native=expected[a], actual=actual[a]) for a in range(0x10000) if actual[a] != expected[a] and (not any((lo <= a < hi for lo, hi, _ in exclusions)))]
        natural = native['pc'] in ('0d7b4', '2fffe')
        wait_match = main.wait_required == native['post']['wait_required'] if natural and main else True
        expected_status = 3 if native['pc'] == '1824e' else 4 if native['pc'] == '1db56' else 0 if native['pc'] == '1d8a4' else 1
        semantic_status_match = outer == expected_status
        cancellation_match = True
        if native['name'].startswith('CALC_SUM') and native['name'].endswith('_evaluate'):
            collected = []
            record = (C.c_uint8 * 20)()
            for i in range(lib.outer_test_polls(state)):
                lib.outer_test_poll_X(state, i, record)
                collected.append(bytes(record).hex())
            cancellation_match = lib.outer_test_polls(state) == metadata[native['name']]['polls'] and collected == metadata[native['name']]['poll_X']
        row = dict(name=native['name'], stage=stage, outer_status=outer, expected_status=expected_status, semantic_status_match=semantic_status_match, cancellation_match=cancellation_match, raw_differences=raw_differences, expected_stop=native['pc'], native_execution=native['execution'], semantic_wait_match=wait_match, native_raw_R5=native['post']['wait_required'], callback_match=p.callback_pending == native['callback_pending'], differences=differences, workspace_boundaries=exclusions)
        if stage in ('continuation', 'continuous_SUM') and native['pc'] == '1d8a4':
            saved_bus = bytes(ram)
            saved_owner = C.string_at(state, lib.outer_test_size())
            saved_callback = p.callback_pending
            adoption = lib.outer_test_adopt(C.byref(p), state)
            valid = adoption == -1 and saved_bus == bytes(ram) and (saved_owner == C.string_at(state, lib.outer_test_size())) and (p.callback_pending == saved_callback)
            ownership_checks.append(dict(name=native['name'], operation='reject adoption during owned error', pass_check=valid))
            assert valid
            if ram[0x80fd] == 3:
                restoration = lib.outer_test_restore(C.byref(p), state)
                valid = restoration == -1 and saved_bus == bytes(ram) and (saved_owner == C.string_at(state, lib.outer_test_size())) and (p.callback_pending == saved_callback)
                ownership_checks.append(dict(name=native['name'], operation='reject restore during owned error', pass_check=valid))
                assert valid
        if stage == 'continuation' and native['pc'] == '1824e':
            saved_bus = bytes(ram)
            saved_owner = C.string_at(state, lib.outer_test_size())
            saved_callback = p.callback_pending
            retained = lib.outer_test_dispatch(C.byref(p), state, main.pending_request, 0)
            valid = retained == 3 and saved_bus == bytes(ram) and (saved_owner == C.string_at(state, lib.outer_test_size())) and (p.callback_pending == saved_callback)
            ownership_checks.append(dict(name=native['name'], operation='retain reset request without mutation', pass_check=valid))
            assert valid
        results.append(row)
        return row
    for native in originals:
        if int(native['entry'], 16) in (0x1d8a4, 0x1db56):
            continue
        C.memmove(ram, bytes.fromhex(native['before']), 0x10000)
        p.callback_pending = p.status = 0
        state = lib.outer_test_new()
        lib.outer_test_begin(state)
        if native['name'].startswith('CALC_SUM'):
            lib.outer_test_cancel_at(state, int(native['name'].split('_cancel')[1].split('_')[0]))
        main = Main()
        lib.fx_main_loop_begin(C.byref(main))
        main.wait_required = native['pre']['wait_required']
        if int(native['entry'], 16) == 20938:
            outer = lib.outer_test_load(C.byref(p), 2, 0x8500)
            compare(native, state, None, outer, 'leaf')
        else:
            entry = int(native['entry'], 16)
            status = lib.fx_main_loop_accept_token(C.byref(p), C.byref(main), native['supplied_token']) if entry == 0xd7c2 else lib.fx_main_loop_tick(C.byref(p), C.byref(main))
            outer = None
            if status == 4:
                outer = lib.outer_test_dispatch(C.byref(p), state, main.pending_request, 0)
                if outer == 1:
                    lib.fx_main_loop_accept_handler(C.byref(p), C.byref(main), lib.outer_test_return(state))
            compare(native, state, main, outer, 'isolated')
        lib.outer_test_free(state)
    for mode in (193, 196):
        for stage in ('coefficient', 'equation'):
            for key in ('AC', 'left', 'right', 'reset', 'export'):
                prefix = f'CALC_{mode:02x}_{stage}_{key}_'
                sequence = [v for v in originals if v['name'].startswith(prefix)]
                C.memmove(ram, bytes.fromhex(sequence[0]['before']), 0x10000)
                p.callback_pending = p.status = 0
                state = lib.outer_test_new()
                lib.outer_test_begin(state)
                main = Main()
                lib.fx_main_loop_begin(C.byref(main))
                main.wait_required = 1
                for native in sequence:
                    if int(native['entry'], 16) in (0x1d8a4, 0x1db56):
                        pair = {'AC': (4, 16), 'left': (128, 8), 'right': (64, 4), 'reset': (16, 128), 'export': (128, 128)}[key]
                        ram[0x8e01], ram[0x8e02] = pair
                        outer = lib.outer_test_dispatch(C.byref(p), state, main.pending_request, 0)
                    else:
                        status = lib.fx_main_loop_accept_token(C.byref(p), C.byref(main), native['supplied_token']) if int(native['entry'], 16) == 0xd7c2 else lib.fx_main_loop_tick(C.byref(p), C.byref(main))
                        outer = lib.outer_test_dispatch(C.byref(p), state, main.pending_request, 0) if status == 4 else None
                    if outer == 1:
                        lib.fx_main_loop_accept_handler(C.byref(p), C.byref(main), lib.outer_test_return(state))
                    compare(native, state, main, outer, 'continuation')
                    p.callback_pending = 0
                lib.outer_test_free(state)
    for mode in (193, 196):
        for math in (0, 1):
            prefix = f'CALC_{mode:02x}_math{math}_'
            sequence = [v for v in originals if v['name'].startswith(prefix)]
            C.memmove(ram, bytes.fromhex(sequence[0]['before']), 0x10000)
            p.callback_pending = p.status = 0
            state = lib.outer_test_new()
            lib.outer_test_begin(state)
            main = Main()
            lib.fx_main_loop_begin(C.byref(main))
            main.wait_required = 1
            for native in sequence:
                status = lib.fx_main_loop_accept_token(C.byref(p), C.byref(main), native['supplied_token']) if int(native['entry'], 16) == 0xd7c2 else lib.fx_main_loop_tick(C.byref(p), C.byref(main))
                outer = lib.outer_test_dispatch(C.byref(p), state, main.pending_request, 0) if status == 4 else None
                if outer == 1:
                    lib.fx_main_loop_accept_handler(C.byref(p), C.byref(main), lib.outer_test_return(state))
                compare(native, state, main, outer, 'continuous_CALC')
                p.callback_pending = 0
            lib.outer_test_free(state)
    for math in (0, 1):
        for body in ('58', '582b31'):
            for cancel_at in (0, 1, 2, 3):
                prefix = f'CALC_SUM_math{math}_body{body}_cancel{cancel_at}_'
                sequence = [v for v in originals if v['name'].startswith(prefix)]
                C.memmove(ram, bytes.fromhex(sequence[0]['before']), 0x10000)
                p.callback_pending = p.status = 0
                state = lib.outer_test_new()
                lib.outer_test_begin(state)
                lib.outer_test_cancel_at(state, cancel_at)
                main = Main()
                lib.fx_main_loop_begin(C.byref(main))
                main.wait_required = 1
                for native in sequence:
                    if int(native['entry'], 16) == 0x1d8a4:
                        ram[0x8e01], ram[0x8e02] = (4, 16)
                        outer = lib.outer_test_dispatch(C.byref(p), state, main.pending_request, 0)
                    else:
                        status = lib.fx_main_loop_accept_token(C.byref(p), C.byref(main), native['supplied_token']) if int(native['entry'], 16) == 0xd7c2 else lib.fx_main_loop_tick(C.byref(p), C.byref(main))
                        outer = lib.outer_test_dispatch(C.byref(p), state, main.pending_request, 0) if status == 4 else None
                    if outer == 1:
                        lib.fx_main_loop_accept_handler(C.byref(p), C.byref(main), lib.outer_test_return(state))
                    compare(native, state, main, outer, 'continuous_SUM')
                    p.callback_pending = 0
                lib.outer_test_free(state)
    for mode in (193, 196):
        for math in (0, 1):
            for token in (224, 225, 226, 227, 254, 240, 237):
                prefix = f'CALC_result_{mode:02x}_math{math}_token{token:02x}_'
                sequence = [v for v in originals if v['name'].startswith(prefix)]
                C.memmove(ram, bytes.fromhex(sequence[0]['before']), 0x10000)
                p.callback_pending = p.status = 0
                state = lib.outer_test_new()
                lib.outer_test_begin(state)
                main = Main()
                lib.fx_main_loop_begin(C.byref(main))
                main.wait_required = 1
                for native in sequence:
                    status = lib.fx_main_loop_accept_token(C.byref(p), C.byref(main), native['supplied_token']) if int(native['entry'], 16) == 0xd7c2 else lib.fx_main_loop_tick(C.byref(p), C.byref(main))
                    outer = lib.outer_test_dispatch(C.byref(p), state, main.pending_request, 0) if status == 4 else None
                    if outer == 1:
                        lib.fx_main_loop_accept_handler(C.byref(p), C.byref(main), lib.outer_test_return(state))
                    compare(native, state, main, outer, 'continuous_result')
                    p.callback_pending = 0
                lib.outer_test_free(state)
    failures = [r for r in results if r['differences'] or not r['semantic_wait_match'] or (not r['callback_match']) or (not r['semantic_status_match']) or (not r['cancellation_match'])]
    native_nonreturns = [r for r in base_native + lifecycle_native if r['execution'] not in (100, 200)]
    changed = [name for name, digest in pins.items() if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest]
    boundary_counts = dict(Counter(((r['execution'], r['pc']) for r in lifecycle_native)))
    expected_boundaries = {(100, '0d7b4'): 378, (200, '1d8a4'): 36, (100, '2fffe'): 24, (100, '1824e'): 4, (100, '1db56'): 4, (100, '1d8a4'): 4}
    boundary_match = boundary_counts == expected_boundaries
    all_names_match = {r['name'] for r in results} == {r['name'] for r in originals}
    passed = not failures and (not native_nonreturns) and (not changed) and boundary_match and all_names_match and (base_report['equal_rows'] == 102) and (base_report['continuous_equal'] == 18) and all((r['pass_check'] for r in ownership_checks))
    report = {'status': 'pass' if passed else 'fail', 'optimization': args.optimization, 'cases': len(results) + len(rows) + len(continuous) + len(ownership_checks), 'checks': 5 * (len(results) + len(rows) + len(continuous)) + len(ownership_checks) + 4, 'native_entries': len(base_native) + len(lifecycle_native), 'calc_native_entries': len(lifecycle_native), 'lifecycle_comparisons': len(results), 'base_comparisons': len(rows), 'continuous_SOLVE': len(continuous), 'ownership_guards': len(ownership_checks), 'failures': failures, 'native_nonreturns': native_nonreturns, 'source_pin_changes': changed, 'source_pins_before_build': pins, 'compiled_sources': sources, 'native_boundary_counts': {f'{code}:{pc}': count for (code, pc), count in boundary_counts.items()}, 'native_boundaries_match': boundary_match, 'all_native_names_compared': all_names_match, 'domains': dict(Counter((r['stage'] for r in results))), 'base_report': base_report, 'ownership_checks': ownership_checks, 'rows': results, 'comparison': 'Original prepared main/D9EE cycles and51CA loads; semantic status, completed main wait, callback, cancellation samples and full observable RAM. Every raw RAM difference is retained. Strict scalar comparisons exclude measured original CPU frames and reviewed numeric/formatter8000..80DB/8640..87CF only when those leaves or their inherited continuous scalar transaction execute.', 'scope': 'CALC/SOLVE outer composition with encounter-order prompts, coefficient acceptance, restore/final evaluation, replay/cursor controls, retained evaluator/error/reset/export continuation and SUM cancellation. Active high rich payload aliases, hidden numeric reads, whole CPU scratch replay, physical key acquisition, menu transactions and scanner-error native fixture are outside this bounded corpus.'}
    (build / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    if not passed:
        print(json.dumps({'status': 'FAIL', 'failures': len(failures), 'native_nonreturns': len(native_nonreturns), 'source_pin_changes': changed, 'boundary_match': boundary_match, 'base_equal': base_report['equal_rows'], 'continuous_equal': base_report['continuous_equal']}))
        for row in failures[:10]:
            print(json.dumps(row))
        raise AssertionError('Outer canonical verifier has unfiltered failures or unstable inputs')
    if not args.no_report:
        report = write_report('analysis/c-verification/solve_outer.json', report, dependencies, 'tools/test_solve_outer_c.py')
    print(json.dumps({key: report[key] for key in ('status', 'optimization', 'cases', 'checks', 'native_entries', 'calc_native_entries', 'lifecycle_comparisons', 'base_comparisons', 'continuous_SOLVE', 'ownership_guards')}))
if __name__ == '__main__':
    main()
