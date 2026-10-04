#!/usr/bin/env python3
"""Actual whole-D9EE TABLE error wait/export/reset continuation controls."""
import os
from pathlib import Path
import base64
import ctypes as C
import gzip
import importlib.util
import itertools
import subprocess
import json
import sys
import zlib
from evidence import pins, stable, sha

HERE = Path(os.environ['FX_TABLE_BUILD_ROOT'])
ROOT = Path(os.environ['FX_TABLE_REPOSITORY_ROOT'])
sys.path.insert(0, str(ROOT / 'tools'))
from nxu8.machine import Machine
from test_platform_c import Platform
from test_input_controller_c import Context, Controller as Input, Control
from test_table_controller_c import Controller as Table

class UI(C.Structure):
    _fields_ = [('context', Context), ('input', Input), ('cancellation', Control),
                ('request', C.c_int), *[(name, C.c_uint8) for name in
                ('phase', 'active', 'refresh_only', 'structured_input', 'command_token',
                 'command_index', 'handler_action', 'saved_result_state')], ('table', Table)]

optimization = sys.argv[1]
build = HERE / ('transitions-' + optimization)
build.mkdir(exist_ok=True)
seed_path = ROOT / 'analysis/native-fixtures/table-controller-lifecycle/controller-final/collect.py'
spec = importlib.util.spec_from_file_location('table_seeds', seed_path)
seeds = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seeds)
rom = (ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
rom_array = (C.c_uint8 * len(rom)).from_buffer_copy(rom)
library = HERE / ('table-ui-' + optimization + '.so')
lib = C.CDLL(str(library))
pp, ss = C.POINTER(Platform), C.POINTER(UI)
lib.fx_ui_controller_begin.argtypes = [pp, ss, C.c_uint8, C.POINTER(Control)]
lib.fx_ui_controller_tick.argtypes = [pp, ss]
lib.fx_ui_controller_export_mask.argtypes = [ss]
lib.fx_ui_controller_export_mask.restype = C.c_uint8
assert lib.ui_size() == C.sizeof(UI) and lib.ui_table_offset() == UI.table.offset
native = Machine(rom, build / 'native')
observer_source = build / 'export-observer.c'
observer_source.write_text((ROOT / 'tools/nxu8/table_composition_events.c').read_text().replace('switch(pc) {', 'switch(pc) {\n case 0x742c: case 0x747a: case 0xaf5a:'))
observer_path = build / 'export-observer.so'
subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
                '-I' + str(ROOT / 'tools/nxu8'), str(observer_source),
                str(ROOT / 'tools/nxu8/vendor/SimU8/core.c'), '-o', str(observer_path)], check=True)
observer = C.CDLL(str(observer_path))
for name in ('harness_init', 'harness_set_pc', 'harness_get_pc', 'harness_set_reg',
             'harness_get_reg', 'harness_set_sp', 'harness_get_sp', 'harness_set_lr',
             'harness_ram', 'harness_run', 'harness_callback'):
    getattr(observer, name).argtypes = getattr(native.lib, name).argtypes
    getattr(observer, name).restype = getattr(native.lib, name).restype
native.lib = observer
native.ram = observer.harness_ram().contents
observer.observer_reset.argtypes = [C.c_uint]
observer.observer_run.argtypes = [C.c_uint64, C.c_uint32]
floor = C.c_uint.in_dll(observer, 'minimum_sp')
ram = (C.c_uint8 * 65536)()
platform = Platform(rom_array, len(rom), ram, 0, 0)
source_pins = pins([Path(__file__), library, observer_source, observer_path, seed_path])
event_count = C.c_uint.in_dll(observer, 'event_count')
event_pc = (C.c_uint32 * 128).in_dll(observer, 'event_pc')
rows, recipes, failures = [], [], []
checks = 0
pairs = ((4, 16), (64, 4), (128, 8), (1, 1), (1, 8), (2, 64),
         (0, 0), (128, 128), (64, 128), (32, 128), (16, 128))

def packed(value):
    return base64.b64encode(zlib.compress(value)).decode()

with gzip.open(build / 'observations.jsonl.gz', 'wt') as archive:
    for math, expression, item, pair in itertools.product((0, 1), (b'1+', b'1O0'), (1, 3), pairs):
        seeds.seed(native, expression=expression, math=math, screen=6, item=item)
        initial = bytes(native.ram)
        C.memmove(ram, native.ram, 65536)
        platform.callback_pending = 0
        state = UI()
        assert lib.fx_ui_controller_begin(C.byref(platform), C.byref(state), 0, None) == 4
        native.er(0, 0)
        native.lib.harness_set_sp(0x8dee)
        native.lib.harness_set_lr(0x2fffe)
        observer.observer_reset(0)
        native.lib.harness_set_pc(0xd9ee)
        assert observer.observer_run(10_000_000, 0xda58) == 100
        for _ in range(8):
            status = lib.fx_ui_controller_tick(C.byref(platform), C.byref(state))
            if status != 4:
                break
        outcome = observer.observer_run(20_000_000, 0x2fffe)
        assert status == 0 and outcome == 105
        case_id = len(rows)
        recipes.append(dict(case_id=case_id, math=math, expression=expression.hex(), item=item,
                            resume_pair=pair, initial_ram_zlib_base64=packed(initial)))
        export_start = event_count.value
        ram[0x8e01], ram[0x8e02] = pair
        native.ram[0x8e01], native.ram[0x8e02] = pair
        status = lib.fx_ui_controller_tick(C.byref(platform), C.byref(state))
        native.lib.harness_run(1, 0x2fffe, False)
        if pair == (0, 0):
            native.lib.harness_run(1, 0x2fffe, False)
        stop = 0x1d8d2 if pair == (0, 0) else 0x1824e if pair == (16, 128) else 0x2fffe
        outcome = observer.observer_run(20_000_000, stop)
        expected_status = (2 if pair == (16, 128) else
                           3 if pair[1] == 128 and pair[0] in (128, 64, 32) else
                           1 if outcome == 100 and stop == 0x2fffe else 0)
        differences = [(address, ram[address], native.ram[address]) for address in range(65536)
                       if ram[address] != native.ram[address]
                       and not floor.value <= address < 0x8dee]
        numeric_residuals = [difference for difference in differences if 0x8000 <= difference[0] < 0x80dc]
        persistent_differences = [difference for difference in differences if difference not in numeric_residuals]
        callback, native_callback = platform.callback_pending, native.lib.harness_callback()
        platform.callback_pending = 0
        mask = lib.fx_ui_controller_export_mask(C.byref(state))
        native_export_leaves = [event_pc[index] for index in range(export_start, event_count.value)
                                if event_pc[index] in (0x742c, 0x747a, 0xaf5a)]
        expected_mask = 0
        if expected_status == 3:
            for leaf in native_export_leaves:
                expected_mask |= {0xaf5a: 1, 0x742c: 2, 0x747a: 4}[leaf]
        checks += 4
        row = dict(case_id=case_id, math=math, expression=expression.hex(), item=item, resume_pair=pair,
                   status=status, expected_status=expected_status, native_outcome=outcome,
                   native_pc=native.lib.harness_get_pc(), minimum_sp=floor.value,
                   callback=callback, native_callback=native_callback,
                   export_mask=mask, expected_export_mask=expected_mask, native_export_leaves=native_export_leaves,
                   numeric_residuals=numeric_residuals, persistent_differences=persistent_differences)
        rows.append(row)
        archive.write(json.dumps(dict(**row, c_ram_zlib_base64=packed(bytes(ram)),
                                      native_ram_zlib_base64=packed(bytes(native.ram)))) + '\n')
        if status != expected_status or persistent_differences or callback != native_callback or mask != expected_mask:
            failures.append(row)
            if len(failures) <= 3:
                print(json.dumps(row), flush=True)
(build / 'inputs.json').write_text(json.dumps(dict(rows=recipes), indent=2) + '\n')
report = dict(scope='Whole D9EE TABLE error continuations', optimization=optimization,
              observations=len(rows), checks=checks, failures=failures, input_pins=source_pins,
              source_changes=stable(source_pins), rows=rows,
              archive_sha256=sha(build / 'observations.jsonl.gz'),
              input_archive_sha256=sha(build / 'inputs.json'),
              limits=['Actual original D9EE starts once per case; native error continuations retain CPU state.',
                      'Only measured CPU-frame addresses are omitted; numeric arena8000..80DB is inventoried separately.',
                      'This caller proof does not implement or claim the subordinate firmware reset body at1824E.'])
(build / 'proof.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(dict(observations=len(rows), checks=checks, failures=len(failures))))
raise SystemExit(bool(failures))
