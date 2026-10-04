#!/usr/bin/env python3
"""Fresh 7334 oracle and optimized C diagnostic-resource tests.

Original successes execute the unmodified CPU core. Fault controls are explicitly
software-resource tests of the high-level C algorithm, never native failures.
"""
import argparse
import ctypes as C
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SUPPORT = ROOT / 'tools/diagnostic_rom_status_support'
FIXTURE = ROOT / 'analysis/native-fixtures/diagnostic-rom-status/inputs.json'
ROM = ROOT / 'firmware/fx-991es-plus-c-ver4.bin'
TOTAL = 131068
FRAME_WRITES = set(range(0x8de2, 0x8ded))


def sha_bytes(value):
    return hashlib.sha256(value).hexdigest()


def pin(paths):
    return {str(path.relative_to(ROOT)): sha_bytes(path.read_bytes())
            for path in sorted(set(paths))}


def ram_recipe(seed):
    return bytes((address * 17 + seed * 29 + 0x5a) & 255
                 for address in range(65536))


def image_recipe(base, patches):
    result = bytearray(base)
    for patch in patches:
        address = patch['address']
        if 0x7334 <= address < 0x7382:
            raise AssertionError('Fixture changes an executed instruction')
        result[address] ^= patch['xor']
    return bytes(result)


def expected_stream(image, fault_cycle=0, sampled=0x44, retention_fault=False):
    output = bytearray()
    cycle = 0
    returned = 0xa5
    for segment, count in [(8, 65536), (1, 65532)]:
        if segment == 1:
            output.extend(struct.pack('<BBHB', 4, 0, 0, 0x5a))
        for address in range(count):
            cycle += 1
            mapped = address if segment == 8 else 65536 + address
            byte = image[mapped] if mapped < len(image) else 0
            value = sampled if cycle == fault_cycle else 0x44
            output.extend(struct.pack('<BBHB', 1, segment, address, byte))
            output.extend(struct.pack('<BBHB', 2, 0, 0, 0x44))
            output.extend(struct.pack('<BBHB', 3, 0, 0, value))
            if value & 0xf4 != 0x44:
                return bytes(output), 0, cycle
    output.extend(struct.pack('<BBHB', 5, 0, 0, 0x5b if retention_fault else 0x5a))
    if retention_fault:
        returned = 0
    return bytes(output), returned, cycle


def stream_summary(stream):
    rows = [struct.unpack_from('<BBHB', stream, index * 5)
            for index in range(len(stream) // 5)]
    counts = {str(kind): sum(row[0] == kind for row in rows)
              for kind in range(1, 6)}
    reads = [row for row in rows if row[0] == 1]
    boundary = [row for row in reads if row[2] in (0, 1, 0xfffb, 0xfffc, 0xffff)]
    return {'sha256': sha_bytes(stream), 'event_count': len(rows),
            'kind_counts': counts, 'first_events': rows[:9],
            'last_events': rows[-10:], 'bank_boundary_reads': boundary}


def event_bytes(library, prefix):
    count = getattr(library, prefix + '_event_count')()
    if getattr(library, prefix + '_overflow')():
        raise AssertionError('Transaction recorder overflow')
    return C.string_at(getattr(library, prefix + '_events')(), count * 5)


def bind_event_api(library, prefix):
    getattr(library, prefix + '_event_count').restype = C.c_size_t
    getattr(library, prefix + '_events').restype = C.c_void_p


def compile_library(command, log, env):
    run = subprocess.run(command, text=True, capture_output=True, env=env)
    log.write_text(json.dumps({'command': command, 'exit': run.returncode,
                               'stdout': run.stdout, 'stderr': run.stderr}, indent=2) + '\n')
    run.check_returncode()


def original_library(output, env):
    artifact = output / 'original.so'
    command = ['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-fPIC', '-shared',
               '-I' + str(ROOT / 'tools'), str(SUPPORT / 'native.c'),
               str(ROOT / 'tools/nxu8/vendor/SimU8/core.c'), '-o', str(artifact)]
    compile_library(command, output / 'original-compile.json', env)
    library = C.CDLL(str(artifact))
    library.harness_init.argtypes = [C.c_void_p, C.c_size_t]
    library.harness_set_pc.argtypes = [C.c_uint32]
    library.harness_get_pc.restype = C.c_uint32
    library.harness_set_lr.argtypes = [C.c_uint32]
    library.harness_set_sp.argtypes = [C.c_uint16]
    library.harness_get_sp.restype = C.c_uint16
    library.harness_set_reg.argtypes = [C.c_uint, C.c_uint8]
    library.harness_get_reg.argtypes = [C.c_uint]
    library.harness_get_reg.restype = C.c_uint8
    library.harness_ram.restype = C.c_void_p
    library.diagnostic_native_seed.argtypes = [C.c_uint8]
    library.diagnostic_native_run.argtypes = [C.c_uint64, C.c_uint32]
    bind_event_api(library, 'diagnostic_native')
    return library, artifact


def candidate_library(output, optimization, env):
    artifact = output / (optimization + '.so')
    command = ['gcc', '-std=c99', '-' + optimization, '-Wall', '-Wextra',
               '-Werror', '-pedantic', '-fPIC', '-shared',
               '-I' + str(ROOT / 'csrc/platform'),
               str(SUPPORT / 'candidate.c'),
               str(ROOT / 'csrc/platform/fx_diagnostic_rom_status.c'),
               str(ROOT / 'csrc/platform/fx_platform.c'),
               '-Wl,--wrap=fx_data_read', '-o', str(artifact)]
    compile_library(command, output / (optimization + '-compile.json'), env)
    library = C.CDLL(str(artifact))
    library.diagnostic_candidate_run.argtypes = [
        C.c_void_p, C.c_size_t, C.c_void_p, C.c_uint8, C.c_uint8,
        C.c_uint32, C.c_uint8, C.c_uint8, C.c_uint, C.c_uint, C.c_uint]
    library.diagnostic_candidate_ram.restype = C.c_void_p
    library.diagnostic_candidate_storage_roundtrip.argtypes = [C.c_uint8, C.c_uint8]
    library.diagnostic_candidate_storage_roundtrip.restype = C.c_uint
    bind_event_api(library, 'diagnostic_candidate')
    return library, artifact


def run_original(library, recipe, image, output):
    image_buffer = C.create_string_buffer(image)
    library.harness_init(image_buffer, len(image))
    ram = ram_recipe(recipe['ram_seed'])
    C.memmove(library.harness_ram(), ram, len(ram))
    registers = [(index * 13 + recipe['register_seed'] * 17) & 255
                 for index in range(16)]
    for index, value in enumerate(registers):
        library.harness_set_reg(index, value)
    library.harness_set_sp(0x8dee)
    library.harness_set_lr(0x2fffe)
    library.harness_set_pc(0x7334)
    library.diagnostic_native_seed(recipe['initial_status'])
    terminal = library.diagnostic_native_run(2000000, 0x2fffe)
    returned = [library.harness_get_reg(index) for index in range(16)]
    if terminal != 100 or returned[0] != 0xa5:
        raise AssertionError(('original did not return A5', recipe['id'], terminal, returned))
    if returned[1:] != registers[1:] or library.harness_get_sp() != 0x8dee:
        raise AssertionError('Original caller-register/stack preservation failed')
    stream = event_bytes(library, 'diagnostic_native')
    expected, _, _ = expected_stream(image)
    if stream != expected:
        raise AssertionError(('Original complete ordered transaction mismatch', recipe['id']))
    after = C.string_at(library.harness_ram(), 65536)
    writes = (C.c_uint64 * 65536).in_dll(library, 'ram_write_counts')
    written = {address for address in range(65536) if writes[address]}
    changed = [address for address in range(65536) if ram[address] != after[address]]
    if written != FRAME_WRITES or any(address not in written for address in changed):
        raise AssertionError(('Original wrote outside the actual eleven-byte frame', written, changed))
    if any(after[address] != ram[address] for address in range(65536) if address not in written):
        raise AssertionError('Original persistent RAM/MMIO changed')
    counts = (C.c_uint64 * 0x18000).in_dll(library, 'execution_counts')
    reads = (C.c_uint64 * 0x30000).in_dll(library, 'rom_read_counts')
    if sum(reads) != TOTAL or sum(reads[:65536]) != 65536 or sum(reads[65536:131072]) != 65532:
        raise AssertionError('Original complete ROM-read counts mismatch')
    if counts[0x737e >> 1] or counts[0x7380 >> 1]:
        raise AssertionError('Unexpected original failure branch')
    ram_path = output / ('original-' + recipe['id'] + '-ram.bin')
    ram_path.write_bytes(after)
    stream_path = output / ('stream-' + sha_bytes(stream) + '.bin')
    if not stream_path.exists():
        stream_path.write_bytes(stream)
    return {'id': recipe['id'], 'rom_sha256': sha_bytes(image), 'return': returned[0],
            'steps': sum(counts), 'stream': stream_summary(stream),
            'stream_file': stream_path.name, 'ram_file': ram_path.name,
            'ram_sha256': sha_bytes(after), 'initial_ram_sha256': sha_bytes(ram),
            'actual_frame_written_addresses': sorted(written),
            'changed_ram_addresses': changed, 'initial_registers': registers,
            'returned_registers': returned, 'stack_preserved': True,
            'ram_mmio_outside_actual_frame_equal': True,
            'callback': library.harness_callback(),
            'native_final_psw': library.diagnostic_native_status(),
            'status_failure_branches_reached': False}, stream


def run_candidate(library, image, ram, status=0, retention=0,
                  cycle=0, sampled=0x44, retention_fault=False,
                  callbacks=15, present=1, platform_kind=0):
    image_buffer = C.create_string_buffer(image)
    ram_buffer = C.create_string_buffer(ram)
    result = library.diagnostic_candidate_run(
        image_buffer, len(image), ram_buffer, status, retention,
        cycle, sampled, retention_fault, callbacks, present, platform_kind)
    stream = event_bytes(library, 'diagnostic_candidate')
    if C.string_at(library.diagnostic_candidate_ram(), 65536) != ram:
        raise AssertionError('Candidate diagnostic changed calculator RAM')
    return result, library.diagnostic_candidate_value(), stream


def candidate_controls(library, image, fixture):
    ram = ram_recipe(91)
    controls = []
    # All status bytes at the first sample: exactly eight are accepted.
    for sampled in range(256):
        expected, value, reads = expected_stream(image, 1, sampled)
        status, actual, stream = run_candidate(library, image, ram, cycle=1, sampled=sampled)
        if (status, actual, stream) != (0, value, expected):
            raise AssertionError(('Modeled first status byte', sampled))
        controls.append({'kind': 'modeled_status_byte', 'sampled': sampled,
                         'return': actual, 'rom_reads': reads, 'stream_sha256': sha_bytes(stream)})
    # Stop exactly at each boundary and check every predicate bit independently.
    for cycle in fixture['fault_cycles']:
        for bit in [2, 4, 5, 6, 7]:
            sampled = 0x44 ^ (1 << bit)
            expected, value, reads = expected_stream(image, cycle, sampled)
            status, actual, stream = run_candidate(library, image, ram, cycle=cycle, sampled=sampled)
            if (status, actual, stream) != (0, value, expected):
                raise AssertionError(('Modeled boundary fault', cycle, bit))
            controls.append({'kind': 'modeled_boundary_status_fault', 'cycle': cycle,
                             'changed_bit': bit, 'return': actual, 'rom_reads': reads,
                             'stream_sha256': sha_bytes(stream)})
    for sampled in [0x44, 0x45, 0x46, 0x47, 0x4c, 0x4d, 0x4e, 0x4f]:
        expected, value, reads = expected_stream(image, TOTAL, sampled)
        status, actual, stream = run_candidate(library, image, ram, cycle=TOTAL, sampled=sampled)
        if (status, actual, stream) != (0, value, expected):
            raise AssertionError(('Modeled final accepted status byte', sampled))
        controls.append({'kind': 'modeled_final_ignored_bits', 'sampled': sampled,
                         'return': actual, 'rom_reads': reads, 'stream_sha256': sha_bytes(stream)})
    expected, value, reads = expected_stream(image, retention_fault=True)
    status, actual, stream = run_candidate(library, image, ram, retention_fault=True)
    if (status, actual, stream) != (0, value, expected):
        raise AssertionError('Modeled retention corruption')
    controls.append({'kind': 'modeled_retention_corruption', 'return': actual,
                     'rom_reads': reads, 'stream_sha256': sha_bytes(stream)})
    for callbacks in range(15):
        status, actual, stream = run_candidate(library, image, ram, callbacks=callbacks)
        if status != -2 or actual != 0 or stream:
            raise AssertionError(('Unavailable callback provider performed work', callbacks))
        controls.append({'kind': 'unavailable_provider_mask', 'mask': callbacks, 'status': status})
    status, actual, stream = run_candidate(library, image, ram, present=0)
    if status != -2 or actual != 0 or stream:
        raise AssertionError('Null resource provider performed work')
    controls.append({'kind': 'unavailable_null_provider', 'status': status})
    status = library.diagnostic_candidate_null_binding()
    if status != -2 or library.diagnostic_candidate_value() != 0 or event_bytes(library, 'diagnostic_candidate'):
        raise AssertionError('Production bind(NULL) provider performed work')
    controls.append({'kind': 'unavailable_model_bind_null', 'status': status})
    for platform_kind in [1, 2, 3]:
        status, actual, stream = run_candidate(library, image, ram, platform_kind=platform_kind)
        if status != -1 or actual != 0 or stream:
            raise AssertionError(('Invalid platform performed work', platform_kind))
        controls.append({'kind': 'invalid_platform', 'platform_kind': platform_kind, 'status': status})
    expected, value, reads = expected_stream(b'')
    status, actual, stream = run_candidate(library, b'', ram)
    if (status, actual, stream) != (0, value, expected) or library.diagnostic_candidate_memory_status() != 1:
        raise AssertionError('Unmapped ROM changed status predicate into a checksum')
    controls.append({'kind': 'modeled_unmapped_rom', 'return': actual, 'rom_reads': reads,
                     'stream_sha256': sha_bytes(stream), 'memory_status': 1})
    status, actual, stream = run_candidate(library, b'', ram, platform_kind=3)
    if (status, actual, stream) != (0, value, expected) or library.diagnostic_candidate_memory_status() != 1:
        raise AssertionError('Null ROM with zero size is not the admitted unmapped model')
    controls.append({'kind': 'modeled_null_zero_size_rom', 'return': actual,
                     'rom_reads': reads, 'stream_sha256': sha_bytes(stream), 'memory_status': 1})
    for status_byte, retention_byte in [(0, 0), (255, 255), (0x44, 0x5a), (0x93, 0x26)]:
        actual = library.diagnostic_candidate_storage_roundtrip(status_byte, retention_byte)
        if actual != status_byte | retention_byte << 8:
            raise AssertionError('Production software resource model is not actual storage')
        controls.append({'kind': 'actual_storage_roundtrip', 'status_byte': status_byte,
                         'retention_byte': retention_byte, 'readback': actual})
    return controls


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    output = (args.output or ROOT / 'analysis/build/boot-diagnostic-review' / stamp).resolve()
    output.mkdir(parents=True, exist_ok=False)
    temporary = output / 'compiler-tmp'
    temporary.mkdir()
    env = dict(os.environ, TMPDIR=str(temporary))
    sources = [Path(__file__).resolve(), FIXTURE, ROM,
               ROOT / 'analysis/disassembly/complete.asm',
               ROOT / 'csrc/platform/fx_diagnostic_rom_status.c',
               ROOT / 'csrc/platform/fx_diagnostic_rom_status.h',
               ROOT / 'csrc/platform/fx_platform.c', ROOT / 'csrc/platform/fx_platform.h',
               ROOT / 'tools/nxu8/harness.c', ROOT / 'tools/nxu8/vendor/SimU8/core.c']
    sources += list(SUPPORT.glob('*.c')) + list((ROOT / 'tools/nxu8/vendor/SimU8').glob('*.h'))
    before = pin(sources)
    fixture = json.loads(FIXTURE.read_text())
    base = ROM.read_bytes()
    native, native_artifact = original_library(output, env)
    artifacts = {native_artifact.name: sha_bytes(native_artifact.read_bytes())}
    original_rows = []
    observations = {}
    for recipe in fixture['original_recipes']:
        image = image_recipe(base, recipe['rom_patches'])
        row, stream = run_original(native, recipe, image, output)
        original_rows.append(row)
        observations[recipe['id']] = (image, ram_recipe(recipe['ram_seed']), stream)
    builds = {}
    for optimization in ['O2', 'O3']:
        candidate, artifact = candidate_library(output, optimization, env)
        artifacts[artifact.name] = sha_bytes(artifact.read_bytes())
        pairs = []
        for recipe in fixture['original_recipes']:
            image, ram, stream = observations[recipe['id']]
            status, value, candidate_stream = run_candidate(
                candidate, image, ram, recipe['initial_status'], recipe['initial_retention'])
            if (status, value, candidate_stream) != (0, 0xa5, stream):
                raise AssertionError(('Fresh original/C transaction mismatch', optimization, recipe['id']))
            if candidate.diagnostic_candidate_resource_storage() != 0x5a44:
                raise AssertionError('Completed normal model did not retain actual status44/retention5A')
            pairs.append({'id': recipe['id'], 'status': status, 'return': value,
                          'all_ordered_transactions_equal': True,
                          'all_calculator_ram_equal_authored_input': True,
                          'software_resource_status': 0x44, 'software_resource_retention': 0x5a,
                          'stream_sha256': sha_bytes(candidate_stream)})
        controls = candidate_controls(candidate, base, fixture)
        builds[optimization] = {'original_pairs': pairs,
                                'modeled_resource_and_api_controls': controls,
                                'control_count': len(controls)}
    after = pin(sources)
    if after != before:
        raise AssertionError('Source/oracle/fixture changed during execution')
    artifact_after = {name: sha_bytes((output / name).read_bytes()) for name in artifacts}
    if artifact_after != artifacts:
        raise AssertionError('Compiled artifact changed during execution')
    report = {'schema': 1, 'status': 'pass', 'generated_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
              'source_pins_before': before, 'source_pins_after': after,
              'artifacts_before': artifacts, 'artifacts_after': artifact_after,
              'original_executions': len(original_rows), 'original_rows': original_rows,
              'candidate_builds': builds,
              'evidence_boundaries': {
                  'original_cpu_core_unmodified': True,
                  'original_cpu_register_pc_patching_after_entry': False,
                  'ordered_event_encoding': '<BBHB: kind, segment, offset, byte',
                  'kind_legend': {'1': 'ROM byte read', '2': 'actual status write',
                                  '3': 'actual status read', '4': 'retention write', '5': 'retention read'},
                  'native_success_only': True, 'native_failure_branches_executed': False,
                  'fault_controls': 'C software diagnostic-resource model only; no claimed original failure executions',
                  'candidate_calculator_ram_cpu_frame': False,
                  'native_final_psw_not_candidate_resource_storage': True,
                  'composed_71ec_screen_not_in_this_test': True,
                  'full_firmware_complete': False}}
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'status': 'pass', 'report': str(output / 'report.json'),
                      'report_sha256': sha_bytes((output / 'report.json').read_bytes()),
                      'original_executions': len(original_rows),
                      'normal_transaction_pairs': sum(len(build['original_pairs']) for build in builds.values()),
                      'modeled_controls_per_build': builds['O2']['control_count'],
                      'source_pins': len(before)}, indent=2))


if __name__ == '__main__':
    main()
