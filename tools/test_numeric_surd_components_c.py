#!/usr/bin/env python3
"""Fresh original-ROM proof of ordered SURD components and their prepared root.

The fixture contains inputs only. Both optimization levels compile the actual
production C, execute the unchanged original ROM, and retain every observation.
This tests a conversion facade, not a replacement ABS/ROUND or TABLE parser.
"""
import argparse
import base64
import collections
import ctypes as C
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import zlib

from c_build_inputs import implementation_inputs
from c_verification import ROOT, write_report

FIXTURE = 'analysis/native-fixtures/numeric-surd-components/inputs.json'
REPORT = 'analysis/c-verification/numeric_surd_components.json'
BUILD = ROOT / 'analysis/build/numeric-surd-components'
SOURCES = ['csrc/numeric/fx_surd_components.c', 'csrc/numeric/fx_numeric.c',
           'csrc/numeric/fx_raw_decimal_parts.c',
           'csrc/numeric/fx_raw_decimal_divide.c',
           'csrc/numeric/fx_raw_decimal_multiply_add.c',
           'csrc/complex/fx_complex_round.c']
STOP = 0x2fffe

ORACLE = r'''
/* Observation only: no numerical code or CPU/ROM instruction substitutions. */
#include "harness.c"
enum { MAX_CONVERSIONS = 64 };
uint64_t component_steps, component_polls;
unsigned component_minimum_sp, component_count, component_overflow;
uint16_t component_source[MAX_CONVERSIONS];
uint8_t component_before[MAX_CONVERSIONS][65536];
uint8_t component_pool[MAX_CONVERSIONS][60];
uint8_t component_result[MAX_CONVERSIONS][10];
uint8_t component_ready[MAX_CONVERSIONS], component_finished[MAX_CONVERSIONS];
void component_observer_reset(void) {
    component_steps = component_polls = 0;
    component_minimum_sp = harness_get_sp();
    component_count = component_overflow = 0;
    memset(component_ready, 0, sizeof component_ready);
    memset(component_finished, 0, sizeof component_finished);
}
int component_observer_run(uint64_t limit, uint32_t stop) {
    for (uint64_t step = 0; step < limit; ++step) {
        uint32_t pc = harness_get_pc();
        unsigned sp = harness_get_sp();
        if (sp < component_minimum_sp) component_minimum_sp = sp;
        if (pc == stop) return 100;
        if (pc == 0x178ba) {
            unsigned index = component_count++;
            if (index < MAX_CONVERSIONS) {
                component_source[index] = (uint16_t)(harness_get_reg(0) |
                                             (harness_get_reg(1) << 8));
                memcpy(component_before[index], ram, 65536);
            } else component_overflow = 1;
        }
        if (component_count && component_count <= MAX_CONVERSIONS) {
            unsigned index = component_count - 1;
            if (pc == 0x17576) {
                memcpy(component_pool[index], ram + 0x8640, 60);
                component_ready[index] = 1;
            }
            if (pc == 0x175e4 && component_ready[index]) {
                /* External ten-byte record from reversed numeric workspace. */
                for (unsigned i = 0; i < 8; ++i)
                    component_result[index][i] = ram[0x8009 - i];
                component_result[index][8] = ram[0x8000];
                component_result[index][9] = ram[0x8001];
                component_finished[index] = 1;
            }
        }
        if (pc == 0x5564) {
            ++component_polls;
            /* Prepared uninterrupted timer response, supplied at its boundary. */
            ram[0x8e00] = 0;
        }
        int status = harness_run(1, stop, false);
        ++component_steps;
        if (status != 103) return status;
    }
    return 103;
}
'''

ABI = r'''
#include "fx_surd_components.h"
#include <stddef.h>
size_t component_number_size(void) { return sizeof(fx_number); }
size_t component_number_offset(void) { return offsetof(fx_number, bytes); }
size_t component_number_alignment(void) {
    struct aligned_number { char preceding; fx_number number; };
    return offsetof(struct aligned_number, number);
}
size_t component_status_size(void) { return sizeof(fx_numeric_status); }
'''


class Number(C.Structure):
    _fields_ = [('bytes', C.c_uint8 * 10)]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def packed(data):
    return base64.b64encode(zlib.compress(data, 9)).decode()


def unpacked(row):
    value = zlib.decompress(base64.b64decode(row['initial_ram_zlib_base64']))
    if len(value) != 65536 or hashlib.sha256(value).hexdigest() != row['initial_ram_sha256']:
        raise ValueError('Corrupt input-only RAM seed')
    return value


def printable(value):
    return value.hex() if isinstance(value, bytes) else value


class Checks:
    def __init__(self):
        self.count = 0
        self.failures = []

    def fields(self, group, identity, values):
        self.count += len(values)
        differences = {name: dict(expected=printable(expected), actual=printable(actual))
                       for name, (expected, actual) in values.items() if expected != actual}
        if differences:
            self.failures.append(dict(group=group, case_id=identity, differences=differences))


class Native:
    def __init__(self, path):
        self.lib = C.CDLL(str(path))
        self.rom = C.create_string_buffer((ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes())
        self.lib.harness_init.argtypes = [C.c_void_p, C.c_size_t]
        self.lib.harness_ram.restype = C.POINTER(C.c_uint8 * 65536)
        self.lib.harness_set_pc.argtypes = [C.c_uint32]
        self.lib.harness_get_pc.restype = C.c_uint32
        self.lib.harness_set_reg.argtypes = [C.c_uint, C.c_uint8]
        self.lib.harness_get_reg.argtypes = [C.c_uint]
        self.lib.harness_get_reg.restype = C.c_uint8
        self.lib.harness_set_sp.argtypes = [C.c_uint16]
        self.lib.harness_set_lr.argtypes = [C.c_uint32]
        self.lib.component_observer_run.argtypes = [C.c_uint64, C.c_uint32]
        self.ram = self.lib.harness_ram().contents
        self.writes = (C.c_uint64 * 65536).in_dll(self.lib, 'ram_write_counts')

    def er(self, register, value):
        self.lib.harness_set_reg(register, value & 255)
        self.lib.harness_set_reg(register + 1, value >> 8)

    def run(self, seed, entry, stop=STOP, sp=0x8dee, er=None, registers=None):
        self.lib.harness_init(self.rom, len(self.rom) - 1)
        C.memmove(self.ram, seed, 65536)
        for index, value in (er or {}).items():
            self.er(index, value)
        for index, value in (registers or {}).items():
            self.lib.harness_set_reg(index, value)
        self.lib.harness_set_sp(sp)
        self.lib.harness_set_lr(STOP)
        self.lib.harness_set_pc(entry)
        self.lib.component_observer_reset()
        run = self.lib.component_observer_run(5000000, stop)
        after = bytes(self.ram)
        minimum = C.c_uint.in_dll(self.lib, 'component_minimum_sp').value
        frame = [address for address in range(minimum, sp) if self.writes[address]]
        count = C.c_uint.in_dll(self.lib, 'component_count').value
        sources = (C.c_uint16 * 64).in_dll(self.lib, 'component_source')
        before = ((C.c_uint8 * 65536) * 64).in_dll(self.lib, 'component_before')
        pools = ((C.c_uint8 * 60) * 64).in_dll(self.lib, 'component_pool')
        results = ((C.c_uint8 * 10) * 64).in_dll(self.lib, 'component_result')
        ready = (C.c_uint8 * 64).in_dll(self.lib, 'component_ready')
        finished = (C.c_uint8 * 64).in_dll(self.lib, 'component_finished')
        conversions = [dict(source=sources[i], before=bytes(before[i]),
                            pool=bytes(pools[i]), result=bytes(results[i]),
                            ready=ready[i], finished=finished[i])
                       for i in range(min(count, 64))]
        observation = dict(entry=entry, stop=stop, run_status=run,
                           final_pc=self.lib.harness_get_pc(), native_R0=self.lib.harness_get_reg(0),
                           steps=C.c_uint64.in_dll(self.lib, 'component_steps').value,
                           polls=C.c_uint64.in_dll(self.lib, 'component_polls').value,
                           minimum_sp=minimum, initial_sp=sp,
                           native_frame_write_addresses=frame,
                           observer_overflow=C.c_uint.in_dll(self.lib, 'component_overflow').value,
                           initial_ram_zlib_base64=packed(seed),
                           final_ram_zlib_base64=packed(after),
                           initial_ram_sha256=hashlib.sha256(seed).hexdigest(),
                           final_ram_sha256=hashlib.sha256(after).hexdigest())
        return after, observation, conversions


def candidate(path):
    lib = C.CDLL(str(path))
    pointer = C.POINTER(Number)
    memory = C.POINTER(C.c_uint8)
    lib.fx_surd_components_emit_live.argtypes = [memory, C.c_uint16]
    lib.fx_surd_components_emit_copy.argtypes = [memory, pointer]
    lib.fx_surd_components_decimal.argtypes = [pointer, pointer]
    lib.fx_surd_components_convert_live.argtypes = [memory, C.c_uint16, C.c_uint16]
    lib.fx_surd_components_convert_copy.argtypes = [memory, pointer, pointer]
    lib.fx_numeric_component_sqrt.argtypes = [pointer, pointer]
    lib.fx_number_negate.argtypes = [pointer, pointer]
    lib.fx_scalar_display_round.argtypes = [pointer, pointer, C.c_uint8, C.c_uint8, C.POINTER(C.c_uint8)]
    for name in ('component_number_size', 'component_number_offset',
                 'component_number_alignment', 'component_status_size'):
        getattr(lib, name).restype = C.c_size_t
    return lib


def convert(lib, ram, source, destination):
    return lib.fx_surd_components_convert_live((C.c_uint8 * 65536).from_buffer(ram), source, destination)


def abs_cell(lib, ram, address):
    original = bytes(ram[address:address + 10])
    header = original[0] & 0xf0
    if not original[0]:
        classification = 1
    elif header == 0x80:
        sign = original[8] + original[9] if original[9] else original[8]
        if original[9] and sign == 7:
            host = convert(lib, ram, address, 0x8640)
            if host:
                return host, None
            sign = ram[0x8649]
        classification = 2 if sign >= 4 else 4
    elif header >= 0x50:
        classification = 0xf0
    elif not (original[8] | original[9]):
        classification = 1
    else:
        classification = 2 if original[9] >= 4 else 4
    if classification == 0xf0:
        ram[address:address + 10] = bytes([0xf3]) + bytes(9)
        return 0, 3
    value = bytearray(ram[address:address + 10])
    value[0] &= 0xbf
    if classification == 2:
        out, number = Number(), Number.from_buffer_copy(value)
        host = lib.fx_number_negate(C.byref(out), C.byref(number))
        if host:
            return host, None
        value = bytes(out)
    ram[address:address + 10] = value
    return 0, 0


def round_cell(lib, ram, address):
    # Native15C9E preserves ten bytes at source+20 even on numerical errors.
    saved = bytes(ram[address + 20:address + 30])
    if ram[address] & 0xf0 == 0x80:
        host = convert(lib, ram, address, address)
        if host:
            return host, None
    out, number = Number(), Number.from_buffer_copy(ram[address:address + 10])
    native = C.c_uint8()
    host = lib.fx_scalar_display_round(C.byref(out), C.byref(number),
                                       ram[0x8102], ram[0x8103], C.byref(native))
    if host:
        return host, None
    ram[address:address + 10] = bytes(out)
    ram[address + 20:address + 30] = saved
    return 0, 0  # Native14114 discards the scalar leaf's status.


def persistent_differences(native, actual, frame):
    excluded = set(frame)
    return [(f'{address:04x}', expected, found)
            for address, (expected, found) in enumerate(zip(native, actual))
            if expected != found and not 0x8000 <= address < 0x80dc and address not in excluded]


def conversion_checks(lib, checks, identity, conversions, stream):
    completed = aliases = 0
    for index, event in enumerate(conversions):
        item_id = f'{identity}:{index}'
        checks.fields('conversion-checkpoint', item_id,
                      {'prepared': (1, event['ready']), 'completed': (1, event['finished'])})
        if not event['ready'] or not event['finished']:
            continue
        completed += 1
        ram = bytearray(event['before'])
        host = lib.fx_surd_components_emit_live((C.c_uint8 * 65536).from_buffer(ram), event['source'])
        expected = bytearray(event['before'])
        expected[0x8640:0x867c] = event['pool']
        checks.fields('ordered-emitter', item_id,
                      {'host_status': (0, host), 'full_ram': (bytes(expected), bytes(ram))})
        numbers = (Number * 6).from_buffer_copy(event['pool'])
        for output_index in range(6):
            numbers = (Number * 6).from_buffer_copy(event['pool'])
            out = C.cast(C.byref(numbers, output_index * 10), C.POINTER(Number))
            status = lib.fx_surd_components_decimal(out, numbers)
            expected_pool = (event['pool'][:output_index * 10] + event['result'] +
                             event['pool'][(output_index + 1) * 10:])
            checks.fields('completed-output-alias', f'{item_id}:{output_index}',
                          {'host_status': (0, status), 'output10': (event['result'], bytes(out.contents)),
                           'other_components': (expected_pool, bytes(numbers))})
            aliases += 1
        stream.write(json.dumps(dict(group='conversion-checkpoint', case_id=item_id,
                         source=event['source'], components60=event['pool'].hex(),
                         numerical_result10=event['result'].hex()), separators=(',', ':')) + '\n')
    return completed, aliases


def radical(integer, sign=1):
    out = bytearray(10)
    if integer < 10:
        out[0] = integer
    elif integer < 100:
        out[0], out[1], out[8] = integer // 10, integer % 10 << 4, 1
    else:
        out[0], out[1], out[8] = integer // 100, integer % 100 // 10 * 16 + integer % 10, 2
    out[9] = sign
    return bytes(out)


def root_inputs():
    cases = [('positive-integer-radicand', radical(integer)) for integer in range(1000)]
    cases.append(('skipped-canonical-zero-control', bytes(10)))
    cases += [('full-error-record', bytes([0xf0 | error]) +
               bytes((17 * error + 29 * index) & 255 for index in range(1, 10)))
              for error in range(16)]
    cases += [('negative-nonzero-control', radical(integer, 6)) for integer in (1, 2, 9, 10, 100, 999)]
    return cases


def portable_checks(lib, checks):
    ram = (C.c_uint8 * 65536).from_buffer_copy(bytes([0x55]) * 65536)
    seed = bytes(ram)
    source = Number.from_buffer_copy(bytes.fromhex('80000001000201010100'))
    controls = [('null-live-ram', lambda: lib.fx_surd_components_emit_live(None, 0x8640)),
                ('null-copy-ram', lambda: lib.fx_surd_components_emit_copy(None, C.byref(source))),
                ('null-copy-source', lambda: lib.fx_surd_components_emit_copy(ram, None)),
                ('bad-convert-source', lambda: lib.fx_surd_components_convert_live(ram, 65527, 0x9000)),
                ('bad-convert-destination', lambda: lib.fx_surd_components_convert_live(ram, 0x9000, 65527)),
                ('null-convert-live-ram', lambda: lib.fx_surd_components_convert_live(None, 0x9000, 0x9010)),
                ('null-convert-copy-output', lambda: lib.fx_surd_components_convert_copy(ram, None, C.byref(source))),
                ('null-convert-copy-source', lambda: lib.fx_surd_components_convert_copy(ram, C.byref(source), None))]
    controls += [(f'bad-live-source-{address}',
                  lambda address=address: lib.fx_surd_components_emit_live(ram, address))
                 for address in range(65527, 65536)]
    for name, operation in controls:
        checks.fields('portable-api', name, {'host_status': (-1, operation()), 'ram_noncommit': (seed, bytes(ram))})
    out = Number.from_buffer_copy(bytes([0xaa]) * 10)
    checks.fields('portable-api', 'root-null-input',
                  {'host_status': (-1, lib.fx_numeric_component_sqrt(C.byref(out), None)),
                   'output_noncommit': (bytes([0xaa]) * 10, bytes(out))})
    checks.fields('portable-api', 'root-null-output',
                  {'host_status': (-1, lib.fx_numeric_component_sqrt(None, C.byref(source)))})
    checks.fields('portable-api', 'root-both-null',
                  {'host_status': (-1, lib.fx_numeric_component_sqrt(None, None))})
    numbers = (Number * 6)()
    numbers[0].bytes[0] = numbers[0].bytes[9] = 1
    numbers[1].bytes[0], numbers[1].bytes[9] = 0xa0, 1
    status = lib.fx_surd_components_decimal(C.byref(out), numbers)
    checks.fields('portable-api', 'unsupported-radical-noncommit',
                  {'host_gap': (True, status != 0), 'output_noncommit': (bytes([0xaa]) * 10, bytes(out))})
    # A host gap follows successful emission: retain those writes, but do not
    # commit the numerical destination. No ROM equivalence is claimed here.
    seed = bytearray(bytes([0x55]) * 65536)
    seed[0x9000:0x900a] = bytes.fromhex('8a000101000000010001')
    expected = bytearray(seed)
    emit_status = lib.fx_surd_components_emit_live((C.c_uint8 * 65536).from_buffer(expected), 0x9000)
    actual = bytearray(seed)
    status = convert(lib, actual, 0x9000, 0x9010)
    checks.fields('portable-api', 'live-host-gap-emission-retained',
                  {'emit_status': (0, emit_status), 'host_gap': (True, status != 0),
                   'retained_emission_and_destination_noncommit': (bytes(expected), bytes(actual))})


def run_optimization(optimization, fixture):
    build = BUILD / optimization
    build.mkdir(parents=True, exist_ok=True)
    oracle, abi = build / 'oracle.c', build / 'abi.c'
    oracle.write_text(ORACLE)
    abi.write_text(ABI)
    native_path, candidate_path = build / 'original.so', build / 'candidate.so'
    common = ['gcc', '-std=c99', '-' + optimization, '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC']
    subprocess.run(common + ['-I', str(ROOT / 'tools/nxu8'), str(oracle),
                             str(ROOT / 'tools/nxu8/vendor/SimU8/core.c'), '-o', str(native_path)], check=True)
    subprocess.run(common + ['-I', str(ROOT / 'csrc/numeric'), '-Wl,--no-undefined', str(abi),
                             *[str(ROOT / source) for source in SOURCES], '-o', str(candidate_path)], check=True)
    native, lib, checks = Native(native_path), candidate(candidate_path), Checks()
    checks.fields('ffi-abi', optimization, {'number_size': (C.sizeof(Number), lib.component_number_size()),
                  'number_offset': (Number.bytes.offset, lib.component_number_offset()),
                  'number_alignment': (C.alignment(Number), lib.component_number_alignment()),
                  'status_size': (C.sizeof(C.c_int), lib.component_status_size())})
    calls = checkpoints = aliases = 0
    group_counts = collections.Counter()
    retained = build / 'observations.jsonl.gz'
    with gzip.open(retained, 'wt') as stream:
        for row in fixture['aliases']:
            seed = unpacked(row)
            after, observation, events = native.run(seed, 0x16538, 0x16588, row['sp'],
                                                    er={12: row['pair']}, registers={1: row['selector']})
            calls += 1
            ram = bytearray(seed)
            identity = seed[row['pair']] & 15
            rows, columns = seed[0x80e0 + 2 * identity:0x80e2 + 2 * identity]
            host, status = 0, 0
            for r in range(rows):
                for c in range(columns):
                    address = 0x829e + 90 * identity + 10 * ((3 * r + c) & 255)
                    host, status = (abs_cell if row['selector'] == 1 else round_cell)(lib, ram, address)
                    if host or status:
                        break
                if host or status:
                    break
            checks.fields('prepared-alias', row['case_id'],
                          {'native_return': (100, observation['run_status']), 'host_status': (0, host),
                           'native_R0': (observation['native_R0'], status),
                           'current20': (after[row['pair']:row['pair'] + 20], bytes(ram[row['pair']:row['pair'] + 20])),
                           'other20': (after[row['pair'] + 20:row['pair'] + 40], bytes(ram[row['pair'] + 20:row['pair'] + 40])),
                           'payload1440': (after[0x829e:0x883e], bytes(ram[0x829e:0x883e])),
                           'persistent_RAM': ([], persistent_differences(after, ram, observation['native_frame_write_addresses'])),
                           'polls': (0, observation['polls']), 'observer_overflow': (0, observation['observer_overflow'])})
            completed, output_aliases = conversion_checks(lib, checks, row['case_id'], events, stream)
            checkpoints += completed
            aliases += output_aliases
            group_counts['alias:' + row['group']] += 1
            stream.write(json.dumps(dict(group='prepared-alias', case_id=row['case_id'],
                         host_status=host, host_native_status=status, **observation), separators=(',', ':')) + '\n')
            if calls % 100 == 0:
                print(f'{optimization} fresh aliases {calls}/{len(fixture["aliases"])}', flush=True)
        for row in fixture['table']:
            initial = unpacked(row)
            compact = bytes.fromhex(row['source_record'])
            # Whole native TABLE establishes the real caller's private-copy pool.
            outer, observation, _ = native.run(initial, 0x171ea, er={12: 0x9000, 14: 0x8200,
                                           10: 0, 8: 0x0103}, registers={6: 1})
            calls += 1
            seed = bytearray(initial)
            seed[0x9000:0x9014] = compact + bytes([0xee]) * 10
            after, leaf, _ = native.run(bytes(seed), 0x173fa, er={0: 0x9000})
            calls += 1
            ram, out, source = bytearray(seed), Number(), Number.from_buffer_copy(compact)
            host = lib.fx_surd_components_convert_copy((C.c_uint8 * 65536).from_buffer(ram), C.byref(out), C.byref(source))
            if not host:
                ram[0x9000:0x900a] = bytes(out)
            alias_ram = bytearray(seed)
            source_alias = Number.from_buffer_copy(compact)
            alias_host = lib.fx_surd_components_convert_copy(
                (C.c_uint8 * 65536).from_buffer(alias_ram), C.byref(source_alias), C.byref(source_alias))
            checks.fields('TABLE-private-copy', row['case_id'],
                          {'native_outer_return': (100, observation['run_status']),
                           'native_leaf_return': (100, leaf['run_status']), 'host_status': (0, host),
                           'source_preserved': (compact, bytes(source)),
                           'result20': (after[0x9000:0x9014], bytes(ram[0x9000:0x9014])),
                           'native_leaf_pool': (after[0x8640:0x867c], bytes(ram[0x8640:0x867c])),
                           'native_TABLE_pool': (outer[0x8640:0x867c], bytes(ram[0x8640:0x867c])),
                           'persistent_RAM': ([], persistent_differences(after, ram, leaf['native_frame_write_addresses'])),
                           'source_output_alias_status': (0, alias_host),
                           'source_output_alias_result10': (after[0x9000:0x900a], bytes(source_alias)),
                           'source_output_alias_pool': (after[0x8640:0x867c], bytes(alias_ram[0x8640:0x867c]))})
            for phase, data in [('whole-TABLE', observation), ('private-copy-leaf', leaf)]:
                stream.write(json.dumps(dict(group=phase, case_id=row['case_id'], **data), separators=(',', ':')) + '\n')
                group_counts[phase] += 1
        for case_id, (group, record) in enumerate(root_inputs()):
            seed = bytearray(65536)
            seed[0x8000:0x800a] = record[8:10] + record[:8][::-1]
            after, observation, _ = native.run(bytes(seed), 0x1b5a6)
            calls += 1
            working = after[0x8000:0x800a]
            expected = working[2:10][::-1] + working[:2]
            source, out = Number.from_buffer_copy(record), Number.from_buffer_copy(bytes([0xaa]) * 10)
            status = lib.fx_numeric_component_sqrt(C.byref(out), C.byref(source))
            alias = Number.from_buffer_copy(record)
            alias_status = lib.fx_numeric_component_sqrt(C.byref(alias), C.byref(alias))
            storage = (C.c_uint8 * 30).from_buffer_copy(bytes([0x55]) * 10 + record + bytes([0xaa]) * 10)
            middle = C.cast(C.byref(storage, 10), C.POINTER(Number))
            middle_status = lib.fx_numeric_component_sqrt(middle, middle)
            checks.fields('prepared-root', case_id,
                          {'native_return': (100, observation['run_status']), 'host_status': (0, status),
                           'output10': (expected, bytes(out)), 'input_preserved': (record, bytes(source)),
                           'alias_status': (0, alias_status), 'alias_output10': (expected, bytes(alias)),
                           'embedded_status': (0, middle_status), 'embedded_output10': (expected, bytes(storage)[10:20]),
                           'embedded_prefix': (bytes([0x55]) * 10, bytes(storage)[:10]),
                           'embedded_suffix': (bytes([0xaa]) * 10, bytes(storage)[20:])})
            group_counts['root:' + group] += 1
            stream.write(json.dumps(dict(group='prepared-root', case_id=case_id, domain=group,
                         input10=record.hex(), native_output10=expected.hex(), host_status=status,
                         host_output10=bytes(out).hex(), **observation), separators=(',', ':')) + '\n')
            if (case_id + 1) % 200 == 0:
                print(f'{optimization} fresh roots {case_id + 1}/1023', flush=True)
    portable_checks(lib, checks)
    detail = dict(optimization=optimization, original_calls=calls, checks=checks.count,
                  failures=checks.failures, groups=dict(group_counts),
                  fresh_conversion_checkpoints=checkpoints, completed_component_output_alias_cases=aliases,
                  retained_observations=str(retained.relative_to(ROOT)),
                  actual_compiled_artifacts_sha256={str(path.relative_to(ROOT)): digest(path)
                           for path in (oracle, abi, native_path, candidate_path, retained)})
    (build / 'result.json').write_text(json.dumps(detail, indent=2) + '\n')
    return detail


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--optimization', choices=('both', 'O2', 'O3'), default='both')
    parser.add_argument('--no-report', action='store_true')
    args = parser.parse_args()
    fixture = json.loads((ROOT / FIXTURE).read_text())
    if (fixture['schema'], fixture['alias_case_count'], fixture['table_case_count']) != (1, 545, 10):
        raise ValueError('Unexpected prepared input corpus')
    if len(fixture['aliases']) != 545 or len(fixture['table']) != 10:
        raise ValueError('Incomplete prepared input corpus')
    inputs = implementation_inputs(ROOT, SOURCES) + [FIXTURE,
              'tools/test_numeric_surd_components_c.py', 'tools/c_build_inputs.py', 'tools/c_verification.py',
              'tools/nxu8/machine.py', 'tools/nxu8/harness.c', 'tools/nxu8/vendor/SimU8/core.c',
              'firmware/fx-991es-plus-c-ver4.bin']
    inputs += [str(path.relative_to(ROOT)) for path in (ROOT / 'tools/nxu8/vendor/SimU8').glob('*.h')]
    before = {name: digest(ROOT / name) for name in sorted(set(inputs))}
    optimizations = ('O2', 'O3') if args.optimization == 'both' else (args.optimization,)
    details = [run_optimization(optimization, fixture) for optimization in optimizations]
    after = {name: digest(ROOT / name) for name in before}
    if before != after:
        raise RuntimeError('A tested input changed during execution; rerun this suite')
    report = dict(suite='numeric_surd_components', original_calls=sum(d['original_calls'] for d in details),
                  cases=sum(d['original_calls'] for d in details), checks=sum(d['checks'] for d in details),
                  failures=[dict(optimization=d['optimization'], **failure) for d in details for failure in d['failures']],
                  optimization_levels=list(optimizations), details=details,
                  input_only_fixture=FIXTURE, pre_execution_inputs_sha256=before,
                  post_execution_inputs_sha256=after,
                  scope='Ordered physical SURD component emission and prepared conversion; copied TABLE loader and original component root.',
                  limits=['Active positive-tagged packed integer radicands0..999, prepared aliases and raw sign2 coefficients observed in this corpus; arbitrary malformed roots remain unsupported.',
                          'The test composes ABS/ROUND cell policy around the new helper. It does not change or claim closure of the frozen rich unary leaf.',
                          'Full persistent RAM comparisons exclude numerical workspace8000..80DB and individually witnessed CPU stack writes only; all1440 physical payload bytes and timer state remain compared.',
                          'Direct1B5A6 rawR0 is retained separately; numerical F* output records are successful host results. Host gaps are distinct and noncommitting.',
                          'Root corpus includes canonical-zero, all16 preserved error records and negative nonzero controls. It does not establish arbitrary raw-root or negative-zero equivalence.',
                          'Generic unnormalized raw quotient states beyond the prepared denominator contract, precision>9 and CPU-buffer architectural overlap are outside this facade proof.'])
    BUILD.mkdir(parents=True, exist_ok=True)
    (BUILD / 'last-result.json').write_text(json.dumps(report, indent=2) + '\n')
    if not args.no_report and not report['failures']:
        target = REPORT if args.optimization == 'both' else f'analysis/c-verification/numeric_surd_components_{args.optimization.lower()}.json'
        write_report(target, report, inputs, 'tools/test_numeric_surd_components_c.py')
    print(json.dumps(dict(original_calls=report['original_calls'], checks=report['checks'],
                         failures=len(report['failures']), optimizations=report['optimization_levels'],
                         first_failures=report['failures'][:3]), indent=2))
    return bool(report['failures'])


if __name__ == '__main__':
    raise SystemExit(main())
