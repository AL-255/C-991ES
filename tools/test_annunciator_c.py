#!/usr/bin/env python3
"""Verify high-level003D62 annunciators against the independent original ROM.

The C implementation has no CPU runtime or register frame. Numeric
workspaces are reconstructed from their documented decimal fields. Every persistent write is compared, including the twelve-byte LCD
copy, and scalar input records remain immutable. GPL-3.0-or-later.
"""
import argparse
import ctypes as C
import json
from pathlib import Path
import random
import subprocess

from c_verification import ROOT, write_report
from nxu8.machine import Machine
from test_platform_c import Platform
from trace_natural_result import settings


SOURCES = ['csrc/ui/fx_annunciator.c', 'csrc/platform/fx_result_classify.c',
           'csrc/numeric/fx_numeric.c', 'csrc/platform/fx_platform.c']
# Complete final RAM parity, including native classifier workspaces. Repeated
# intermediate arithmetic store counts are not a semantic arithmetic API.
EXCLUDED = [(0x8d00, 0x8dee)]
NUMERIC = [(0x8000, 0x8060), (0x8640, 0x867c)]
PERSISTENT = [(0, 0x8d00), (0x8dee, 65536)]
COUNTED = [(0,0x8000),(0x8060,0x8640),(0x867c,0x8d00),(0x8dee,65536)]
ROW, LCD, WIDTH = 0x87d0, 0xf800, 12
SETTINGS = [0x80f8, 0x80f9, 0x8105, 0x8102, 0x8106, 0x80fe, 0x8129]
BASE = [0, 193, 4, 0, 0, 1, 0]
RECORDS = [bytes.fromhex(record) for record in (
    '00000000000000000000',  # zero
    '01000000000000000001',  # positive decimal
    '01000000000000000006',  # negative decimal
    '21a30000000000000301',  # rational1/3
    '80020102000301020101',  # two positive compact surds
    '80020102000301020106',  # opposite signs, negative result
    'f3000000000000000000',  # numerical error
    '80020101000201010601',  # compact surd cancellation to decimal zero
    '80020201000201010601',  # opposite signs, positive result
    '80020101000100010006',  # one negative compact surd
    '41000000000000000001',  # marked decimal
    '40000000000000000000',  # marked zero
    '61a30000000000000301',  # marked rational admission error
)] + [bytes([0xf0 | code]) + bytes(9) for code in range(16)]

# Test-only linker instrumentation: the production function still calls the
# real data bus for every store. Counts catch clear/set/copy writes even when
# their final values were already present in the initial memory.
BUS_INSTRUMENTATION = r'''
#include "csrc/platform/fx_platform.h"
#include <string.h>
uint64_t fx_annunciator_test_writes[65536];
uint16_t fx_annunciator_test_addresses[64];
uint8_t fx_annunciator_test_values[64];
unsigned fx_annunciator_test_events;
void __real_fx_data_write(fx_platform *, uint8_t, uint16_t, uint8_t);
void __wrap_fx_data_write(fx_platform *p, uint8_t s, uint16_t a, uint8_t v)
{
    if (!s && a >= 0x8000) {
        ++fx_annunciator_test_writes[a];
        if ((a >= 0x87d0 && a < 0x87dc) || (a >= 0xf800 && a < 0xf80c)) {
        if (fx_annunciator_test_events < 64) {
            fx_annunciator_test_addresses[fx_annunciator_test_events] = a;
            fx_annunciator_test_values[fx_annunciator_test_events] = v;
        }
        ++fx_annunciator_test_events;
        }
    }
    __real_fx_data_write(p, s, a, v);
}
void fx_annunciator_test_reset(void)
{
    memset(fx_annunciator_test_writes, 0, sizeof(fx_annunciator_test_writes));
    fx_annunciator_test_events = 0;
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--random-cases', type=int, default=4096)
    args = parser.parse_args()
    build = ROOT / 'analysis/build/annunciator'
    build.mkdir(parents=True, exist_ok=True)
    instrumentation = build / 'bus_instrumentation.c'
    instrumentation.write_text(BUS_INSTRUMENTATION)
    library = build / 'annunciator.so'
    options = ['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror', '-pedantic',
               '-shared', '-fPIC', '-I', str(ROOT)]
    subprocess.run([*options, *[str(ROOT/path) for path in SOURCES],
                    str(instrumentation), '-Wl,--wrap=fx_data_write', '-o', str(library)], check=True)
    lib = C.CDLL(str(library))
    lib.fx_annunciator_draw.argtypes = [C.POINTER(Platform)]
    lib.fx_annunciator_draw.restype = C.c_int
    lib.fx_take_callback.argtypes = [C.POINTER(Platform)]
    lib.fx_take_callback.restype = C.c_uint8
    lib.fx_data_write.argtypes = [C.POINTER(Platform), C.c_uint8, C.c_uint16, C.c_uint8]
    writes = (C.c_uint64*65536).in_dll(lib, 'fx_annunciator_test_writes')
    event_addresses = (C.c_uint16*64).in_dll(lib, 'fx_annunciator_test_addresses')
    event_values = (C.c_uint8*64).in_dll(lib, 'fx_annunciator_test_values')
    event_count = C.c_uint.in_dll(lib, 'fx_annunciator_test_events')
    rom = (ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    rom_buffer = (C.c_uint8*len(rom)).from_buffer_copy(rom)
    ram = (C.c_uint8*65536)()
    platform = Platform(rom_buffer, len(rom), ram, 0, 0)
    native = Machine(rom, build/'oracle')
    native.lib.memorySetData.argtypes = [C.c_uint8, C.c_uint16, C.c_size_t, C.c_uint64]
    rng = random.Random(0x3d62)
    backgrounds = [rng.randbytes(65536), bytes(65536), bytes([255])*65536]
    counts = {}
    scratch_writes = set()

    def record(group):
        counts[group] = counts.get(group, 0) + 1

    def prepare(values, first, second, background=0, pending=0):
        native.reset()
        C.memmove(native.ram, backgrounds[background], 65536)
        settings(native)
        for address, value in zip(SETTINGS, values): native.ram[address] = value
        for address, value in ((0x8226, first), (0x8408, second)):
            for offset, byte in enumerate(value): native.ram[address+offset] = byte
        # These distinct sentinels force the row clear and complete LCD copy.
        for offset in range(WIDTH):
            native.ram[ROW+offset] = 0xa5
            native.ram[LCD+offset] = 0x5a
        C.memmove(ram, native.ram, 65536)
        platform.callback_pending = platform.status = 0
        if pending:
            lib.fx_data_write(C.byref(platform), 0, 0xf000, pending)
            native.lib.memorySetData(0, 0xf000, 1, pending)
            native.ram_writes[0xf000] = 0
        lib.fx_annunciator_test_reset()
        return bytes(ram)

    def events():
        assert event_count.value <= 64
        return [(event_addresses[i], event_values[i]) for i in range(event_count.value)]

    def persistent(address):
        return not any(start <= address < end for start, end in EXCLUDED)

    def compare(group, detail, before, first, second):
        actual, expected = bytes(ram), bytes(native.ram)
        actual_writes, expected_writes = bytes(writes), bytes(native.ram_writes)
        for start, end in PERSISTENT:
            if actual[start:end] != expected[start:end]:
                differences = [(hex(a), actual[a], expected[a]) for a in range(start, end)
                               if actual[a] != expected[a]]
                raise AssertionError((group, detail, 'memory', differences[:20]))
        for start,end in COUNTED:
            if actual_writes[8*start:8*end] != expected_writes[8*start:8*end]:
                differences = [(hex(a), writes[a], native.ram_writes[a]) for a in range(start, end)
                               if writes[a] != native.ram_writes[a]]
                raise AssertionError((group, detail, 'write count', differences[:20]))
        for address, source in ((0x8226, first), (0x8408, second)):
            assert actual[address:address+10] == expected[address:address+10] == source
            assert not any(writes[address:address+10])
            assert not any(native.ram_writes[address:address+10])
        assert actual[ROW:ROW+WIDTH] == actual[LCD:LCD+WIDTH]
        assert all(writes[LCD+offset] == 1 for offset in range(WIDTH))
        assert lib.fx_take_callback(C.byref(platform)) == native.lib.harness_callback()
        assert platform.status == 0
        # Retain evidence for every native numeric address compared.
        for start, end in NUMERIC:
            scratch_writes.update(a for a in range(start, end) if native.ram_writes[a])
        record(group)

    def check(group, values, a=0, b=0, background=0, pending=0, trace=False):
        first, second = RECORDS[a], RECORDS[b]
        before = prepare(values, first, second, background, pending)
        assert lib.fx_annunciator_draw(C.byref(platform)) == 0, (group, values, a, b)
        trace_path = build/'native-writes.csv'
        if trace: native.trace_open(trace_path, reads=False)
        try: native.call(0x3d62, limit=3000000)
        finally:
            if trace: native.trace_close()
        compare(group, (values, a, b, background, pending), before, first, second)
        if trace:
            expected_events = []
            for line in trace_path.read_text().splitlines():
                fields = line.split(',')
                if fields[0] != 'W': continue
                segment, address = int(fields[3], 16), int(fields[4], 16)
                size, value = int(fields[5]), int(fields[6], 16)
                for offset in range(size):
                    destination = (address+offset) & 65535
                    if segment == 0 and destination >= 0x8000 and (ROW <= destination < ROW+WIDTH or LCD <= destination < LCD+WIDTH):
                        expected_events.append((destination, (value >> (8*offset)) & 255))
            assert events() == expected_events, (group, 'ordered bus writes', events(), expected_events)
            record('ordered_native_persistent_bus_writes')

    # Match the independently mapped5888 native-only cases, now against C.
    for field in range(len(SETTINGS)):
        for value in range(256):
            values = BASE.copy(); values[field] = value
            check('all_settings_bytes', values)
    for index in range(args.random_cases):
        values = [rng.randrange(256), rng.choice((0,2,3,6,7,12,69,74,129,136,137,193,196)),
                  rng.choice((0,4,5,6,255)), rng.choice((0,4,8,9,255)),
                  rng.randrange(256), rng.randrange(256), rng.randrange(256)]
        check('random_settings_and_numeric_records', values, rng.randrange(7), rng.randrange(7), index%3)

    # All scalar pairs reach the complex second-source branch. BASE-N and
    # ordinary modes also establish that the second scalar cannot light it.
    for mode in (2, 0xc1, 0xc4):
        values = [15, mode, 6, 9, 1, 0x40, 15]
        for first in range(len(RECORDS)):
            for second in range(len(RECORDS)):
                check('scalar_pair_grid', values, first, second)

    for mode in (2, 3, 6, 7, 0xc1, 0xc4):
        for state in (0, 0x40, 0x80, 0xc0):
            check('ordered_indicator_and_lcd_copy', [15, mode, 6, 9, 1, state, 15], 1, 2, trace=True)
    for pending in range(256):
        check('existing_callback_retained', [15,0xc4,4,8,1,0x40,15], 8, 7, pending=pending)

    # An opposite-sign exact cancellation still has native nonzero class4.
    check('compact_surd_cancellation_is_nonzero', BASE, 7, 0, trace=True)
    assert ram[ROW+1] & 0x10
    for values in ([0,0xc1,4,0,0,1,0], [0,0xc4,4,0,0,1,0]):
        check('secondary_record_only_in_complex_mode', values, 0, 7)
        assert bool(ram[ROW+1] & 0x10) == (values[1] == 0xc4)

    # Invalid platform arguments must not read or write caller memory.
    before = bytes(ram)
    assert lib.fx_annunciator_draw(None) == -1
    missing_ram = Platform(rom_buffer, len(rom), None, 0x42, 0)
    assert lib.fx_annunciator_draw(C.byref(missing_ram)) == -1
    assert bytes(ram) == before and missing_ram.callback_pending == 0x42
    record('invalid_arguments_do_not_write')

    # Inject the address classifier's explicit negative statuses to verify the
    # caller's failure boundary without inventing an oracle outcome for a
    # malformed scalar. The row retains preceding native-order writes and
    # the old LCD row survives. Successful classification itself is covered
    # by all the original-ROM comparisons above.
    failing_classifier = build/'failing_classifier.c'
    failing_classifier.write_text(r'''
#include "csrc/platform/fx_result_classify.h"
int test_fail_at, test_fail_status, test_classifier_calls;
fx_numeric_status fx_result_classify_address(fx_platform *platform,
    uint16_t source, uint16_t companion, fx_result_classification *result)
{
    (void)platform; (void)source;
    if (++test_classifier_calls == test_fail_at)
        return (fx_numeric_status)test_fail_status;
    result->classification = 4;
    result->continuation = companion;
    return FX_NUMERIC_OK;
}
''')
    failure_library = build/'annunciator-failure.so'
    subprocess.run([*options, str(ROOT/SOURCES[0]), str(ROOT/SOURCES[3]),
                    str(failing_classifier), '-o', str(failure_library)], check=True)
    failure_lib = C.CDLL(str(failure_library))
    failure_lib.fx_annunciator_draw.argtypes = [C.POINTER(Platform)]
    failure_lib.fx_annunciator_draw.restype = C.c_int
    fail_at = C.c_int.in_dll(failure_lib, 'test_fail_at')
    fail_status = C.c_int.in_dll(failure_lib, 'test_fail_status')
    calls = C.c_int.in_dll(failure_lib, 'test_classifier_calls')
    for position in (1,2):
        for status in (-1,-2,-3):
            before = prepare([15,0xc4,6,9,1,0x40,15], RECORDS[1], RECORDS[2])
            fail_at.value, fail_status.value, calls.value = position, status, 0
            assert failure_lib.fx_annunciator_draw(C.byref(platform)) == status
            expected_row = bytearray(WIDTH)
            expected_row[:3] = bytes((0x14,0x02,0x40))
            if position == 2: expected_row[1], expected_row[4] = 0x12, 0x80
            expected = bytearray(before); expected[ROW:ROW+WIDTH] = expected_row
            assert bytes(ram) == bytes(expected) and calls.value == position
            record('classifier_failure_status_and_partial_row')

    report = write_report('analysis/c-verification/annunciator.json', {
        'cases': sum(counts.values()), 'domains': counts, 'failures': 0,
        'random_cases': args.random_cases, 'seed': '0x3d62',
        'input': 'identical persistent RAM/MMIO, seven arbitrary settings bytes, canonical decimal/rational/compact-surd/error records8226 and8408, and retained callback events',
        'output': 'complete persistent RAM/LCD/MMIO including all numeric scratch, per-address bus counts outside arithmetic scratch; selected ordered header writes; immutable scalar sources; callbacks',
        'scope': 'original003D62 through003E74return: complete twelve-byte87D0rowclear, modifier/numeric/mode/angle/format/math/result/history indicators and complete F800copy',
        'excluded_native_memory': [{'start':hex(start), 'end_exclusive':hex(end),
                                    'reason':'CPU call stack' if start == 0x8d00 else 'shared scalar classifier numeric scratch'}
                                   for start,end in EXCLUDED],
        'observed_native_numeric_scratch_addresses': [hex(address) for address in sorted(scratch_writes)],
        'limitation': 'CPU stack effects are absent; malformed compact-surds outside the prepared BCD classifier domain, physical LCD timing and outer controllers remain outside this routine API; no full firmware completion claim'},
        [*SOURCES, 'csrc/ui/fx_annunciator.h', 'csrc/platform/fx_result_classify.h',
         'csrc/numeric/fx_numeric.h', 'csrc/platform/fx_platform.h',
         'tools/test_platform_c.py', 'tools/trace_natural_result.py', 'tools/c_verification.py'],
        'tools/test_annunciator_c.py')
    print(json.dumps({key:value for key,value in report.items()
                      if key not in ('tested_inputs_sha256','observed_native_numeric_scratch_addresses')}, indent=2))


if __name__ == '__main__': main()
