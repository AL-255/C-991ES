#!/usr/bin/env python3
import os
"""Fresh original-vs-C TABLE odd result/source-address regressions."""
from pathlib import Path
import base64
import ctypes as C
import gzip
import json
import sys
import zlib

from evidence import pins, stable, sha

HERE = Path(os.environ['FX_TABLE_BUILD_ROOT'])
ROOT = Path(os.environ['FX_TABLE_REPOSITORY_ROOT'])
sys.path.insert(0, str(ROOT / 'tools'))
from nxu8.machine import Machine
from test_platform_c import Platform
from test_input_controller_c import Context
from test_table_controller_c import Controller
from test_table_composition_c import Execution
from test_table_c import Poll
from trace_natural_result import settings

optimization = sys.argv[1] if len(sys.argv) > 1 else 'O2'
if optimization not in ('O2', 'O3'):
    raise SystemExit('Optimization must be O2 or O3')
build = HERE / ('odd-' + optimization)
build.mkdir(exist_ok=True)
rom = (ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
rom_array = (C.c_uint8 * len(rom)).from_buffer_copy(rom)
native = Machine(rom, build / 'native')
library_path = HERE / ('table-ui-' + optimization + '.so')
lib = C.CDLL(str(library_path))
pp, ss = C.POINTER(Platform), C.POINTER(Controller)
lib.fx_table_controller_accept_execution.argtypes = [pp, ss, C.c_int, C.c_uint16]
lib.fx_table_controller_begin.argtypes = [pp, ss, C.POINTER(Context)]
lib.fx_table_execute_request.argtypes = [pp, ss, Poll, C.c_void_p, C.POINTER(Execution)]
input_pins = pins([Path(__file__), library_path, build / 'native/nxu8-harness.so'])
rows, failures, recipes = [], [], []
checks = 0

def packed(value):
    return base64.b64encode(zlib.compress(value)).decode()

with gzip.open(build / 'observations.jsonl.gz', 'wt') as archive:
    for whole_f12a, item, source in [
        (False, item, address) for item in (1, 2, 3)
        for address in (0x8140, 0x8141, 0x8142, 0x828f, 0x8290, 0x8291)
    ] + [
        (True, item, address) for address in (0x8140, 0x8141, 0x8142)
        for item in (1, 2, 3)
    ]:
        native.reset()
        settings(native)
        common = [(0x80f9, 0x88), (0x80fc, 6), (0x80fd, item),
                  (0x80ff, 0), (0x80f5, 0xed)]
        specific = ([(0x80fe, 1), (0x8100, 0), (0x8101, 0),
                     (0x8130, 0), (0x8106, 0), (0x810c, 0)] if whole_f12a else
                    [(0x80fe, 3), (0x8100, 0xac), (0x8101, 2), (0x8130, 1)])
        for address, value in common + specific:
            native.ram[address] = value
        context = Context(0x8154, source, 1, 0x88, 0, 0, 0, 1)
        if whole_f12a:
            native.ram[source:source + 20] = bytes(20)
            native.ram[0x8154:0x8156] = b'1\0'
            native.ram[0x9d00:0x9d00 + C.sizeof(context)] = bytes(context)
        else:
            native.ram[source:source + 10] = bytes.fromhex('01000000000000000101')
            native.ram[source + 10:source + 20] = bytes(10)
        initial = bytes(native.ram)
        case_id = len(rows)
        recipes.append(dict(case_id=case_id, scope='whole-F12A' if whole_f12a else 'E680',
                            item=item, result_address=source, initial_ram_zlib_base64=packed(initial)))
        ram = (C.c_uint8 * 65536).from_buffer_copy(initial)
        platform = Platform(rom_array, len(rom), ram, 0, 0)
        state = Controller()
        if whole_f12a:
            host_status = lib.fx_table_controller_begin(C.byref(platform), C.byref(state), C.byref(context))
            execution = Execution()
            if host_status == 5:
                host_status = lib.fx_table_execute_request(C.byref(platform), C.byref(state),
                                                          Poll(), None, C.byref(execution))
            native.er(0, 0x9d00)
            native.er(8, 0x9d00)
            entry = 0x1f12a
        else:
            state.context = context
            state.active = 1
            state.phase = 1
            state.request = 1
            host_status = lib.fx_table_controller_accept_execution(C.byref(platform), C.byref(state), 0, 0x8200)
            native.er(0, source)
            entry = 0xe680
        try:
            native.call(entry, limit=5_000_000)
            native_outcome = 100
        except RuntimeError as error:
            native_outcome = str(error)
        # CPU-local stack writes are individually witnessed by the original core.
        differences = [(address, ram[address], native.ram[address]) for address in range(65536)
                       if ram[address] != native.ram[address]
                       and not (0x8b00 <= address < 0x8dee and native.ram_writes[address])
                       and not (whole_f12a and 0x9d00 <= address < 0x9d0c)]
        numeric_residuals = [difference for difference in differences if 0x8000 <= difference[0] < 0x80dc]
        persistent_differences = [difference for difference in differences if difference not in numeric_residuals]
        destination = 0x829e + 10 * (item - 1)
        semantic_failure = host_status != 1 or native_outcome != 100
        checks += 2
        row = dict(case_id=case_id, scope='whole-F12A' if whole_f12a else 'E680', item=item,
                   result_address=source, host_status=host_status, native_outcome=native_outcome,
                   native_r0=native.reg(0), destination=destination,
                   stored_c=bytes(ram[destination:destination + 10]).hex(),
                   stored_native=bytes(native.ram[destination:destination + 10]).hex(),
                   numeric_residuals=numeric_residuals, persistent_differences=persistent_differences)
        rows.append(row)
        archive.write(json.dumps(dict(**row, initial_ram_zlib_base64=packed(initial),
                                      c_ram_zlib_base64=packed(bytes(ram)),
                                      native_ram_zlib_base64=packed(bytes(native.ram)),
                                      native_written_addresses=[address for address in range(65536)
                                                                if native.ram_writes[address]])) + '\n')
        if semantic_failure or persistent_differences:
            failures.append(row)

(build / 'inputs.json').write_text(json.dumps(dict(rows=recipes), indent=2) + '\n')
report = dict(scope='TABLE E680 ordered conversion/copy and whole F12A physical secondary zero',
              optimization=optimization, observations=len(rows), checks=checks, failures=failures,
              input_pins=input_pins, source_changes=stable(input_pins), rows=rows,
              archive_sha256=sha(build / 'observations.jsonl.gz'), input_archive_sha256=sha(build / 'inputs.json'),
              limits=['Original numeric register scratch 8000..80DB is inventoried separately.',
                      'Only witnessed original CPU-local stack writes and the supplied whole-F12A CPU context are excluded.',
                      'No general malformed/odd SURD conversion claim.'])
(build / 'proof.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(dict(observations=len(rows), checks=checks, failures=len(failures))))
raise SystemExit(bool(failures))
