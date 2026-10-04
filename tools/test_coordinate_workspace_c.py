#!/usr/bin/env python3
"""Original-ROM differential proof for physical Rec/Pol/root workspaces.

Expected values are never fixture inputs. GPL-3.0-or-later.
"""
import argparse
import ast
from collections import Counter
import ctypes as C
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys


class Number(C.Structure):
    _fields_ = [('bytes', C.c_uint8 * 10)]


class Result(C.Structure):
    _fields_ = [('value', Number * 2), ('consumed', C.c_size_t),
                ('unsupported_token', C.c_uint8)]


class Storage(C.Structure):
    _fields_ = [('ram', C.POINTER(C.c_uint8)), ('ram_size', C.c_size_t),
                ('rom', C.POINTER(C.c_uint8)), ('rom_size', C.c_size_t)]


class Source(C.Structure):
    _fields_ = [('input_address', C.c_uint16), ('output_address', C.c_uint16),
                ('before_sample', C.c_void_p), ('userdata', C.c_void_p)]


ABI_PROBE = r'''
#include <stddef.h>
#include "parse/fx_eval_transport.h"
size_t coordinate_test_abi(unsigned index) {
    const size_t values[] = {
        sizeof(fx_number), sizeof(fx_eval_result),
        offsetof(fx_eval_result, value), offsetof(fx_eval_result, consumed),
        offsetof(fx_eval_result, unsupported_token), sizeof(fx_eval_storage),
        offsetof(fx_eval_storage, ram), offsetof(fx_eval_storage, ram_size),
        offsetof(fx_eval_storage, rom), offsetof(fx_eval_storage, rom_size),
        sizeof(fx_eval_source), offsetof(fx_eval_source, input_address),
        offsetof(fx_eval_source, output_address),
        offsetof(fx_eval_source, before_sample), offsetof(fx_eval_source, userdata)
    };
    return index < sizeof(values)/sizeof(values[0]) ? values[index] : (size_t)-1;
}
'''


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require_unchanged(pins):
    for filename, pin in pins.items():
        if digest(filename) != pin:
            raise RuntimeError(f'Tested input/artifact changed during run: {filename}')


def require_abi(actual, expected):
    if actual != expected:
        raise RuntimeError(f'Compiled/ctypes ABI mismatch: {actual}')


def check_negative_guards(build, abi, header, artifact, fixture, fixture_pin):
    """Exercise the real rejection functions on changed private copies."""
    passed = []
    changed_abi = list(abi)
    changed_abi[1] += 1
    try:
        require_abi(changed_abi, abi)
    except RuntimeError:
        passed.append('compiled/ctypes ABI mismatch rejected')
    else:
        raise RuntimeError('ABI negative guard failed')
    for label, source in [('source', header), ('artifact', artifact), ('fixture', fixture)]:
        probe = build / ('guard-' + label + '.bin')
        probe.write_bytes(source.read_bytes())
        original = digest(probe)
        if label == 'fixture' and original != fixture_pin:
            raise RuntimeError('Negative fixture probe is not the canonical input')
        altered = bytearray(probe.read_bytes())
        altered[len(altered)//2] ^= 1
        probe.write_bytes(altered)
        try:
            require_unchanged({str(probe): original})
        except RuntimeError:
            passed.append(label + ' mutation rejected')
        else:
            raise RuntimeError(label + ' negative guard failed')
        finally:
            probe.unlink()
    return passed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-report', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    implementation = root
    fixture = root / 'analysis/coordinate-workspace-inputs.json'
    build = root / 'analysis/build/coordinate-workspace'
    build.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(root / 'tools'))
    from c_build_inputs import implementation_inputs
    from c_verification import write_report
    from nxu8.machine import Machine
    from trace_natural_result import settings

    # Capture declared inputs before reading fixture or compiling. Close all
    # implementation dependencies over their actual local quoted includes.
    source_list_path = root / 'tools/test_eval_c.py'
    source_list_pin = digest(source_list_path)
    tree = ast.parse(source_list_path.read_text())
    sources = ast.literal_eval(next(n.value for f in tree.body
        if isinstance(f, ast.FunctionDef) and f.name == 'main'
        for n in f.body if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == 'sources' for t in n.targets)))
    sources = ['csrc/' + name for name in sources]
    closure = implementation_inputs(implementation, sources)
    declared = [implementation / name for name in closure]
    declared += [Path(__file__).resolve(), fixture, source_list_path,
        root / 'tools/c_build_inputs.py', root / 'tools/c_verification.py',
        root / 'tools/trace_natural_result.py',
        root / 'tools/nxu8/machine.py', root / 'tools/nxu8/harness.c',
        root / 'tools/nxu8/integral_storage_events.c',
        root / 'tools/nxu8/vendor/SimU8/core.c',
        root / 'firmware/fx-991es-plus-c-ver4.bin']
    declared += list((root / 'tools/nxu8/vendor/SimU8').glob('*.h'))
    input_pins = {str(path.resolve()): digest(path) for path in declared}
    if input_pins[str(source_list_path.resolve())] != source_list_pin:
        raise RuntimeError('Compilation source list changed while being read')
    if digest(fixture) != '84a37e53f67fafb57ada48722da9e95bbf9d875719151fc358febc62c5334dff':
        raise RuntimeError('Canonical coordinate input fixture changed; full controls required')
    inputs = json.loads(fixture.read_text())
    if inputs['schema'] != 1:
        raise ValueError('Unsupported input fixture schema')
    counts = Counter(x['group'] for x in inputs['parser'])
    if counts != {'rec-540': 540, 'pol-whole-480': 480, 'historical-nine': 9, 'coordinate-publication-36': 36}:
        raise ValueError(f'Incomplete retained parser controls: {counts}')
    if len(inputs['root']) != 44:
        raise ValueError('Expected44 root inputs per optimization')
    allowed_parser = {'group', 'tokens', 'mode', 'output', 'input_address'}
    if any(set(x) != allowed_parser for x in inputs['parser']):
        raise ValueError('Parser fixtures must contain inputs only')
    if any(set(x) != {'input', 'record', 'exact'} for x in inputs['root']):
        raise ValueError('Root fixtures must contain inputs only')

    snapshot = build / 'snapshot'
    for name in closure:
        target = snapshot / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(implementation / name, target)
        if digest(target) != input_pins[str((implementation / name).resolve())]:
            raise RuntimeError(f'Source changed during snapshot: {name}')
    abi_source = build / 'coordinate_abi.c'
    abi_source.write_text(ABI_PROBE)
    generated_inputs = {str(abi_source): digest(abi_source)}
    artifacts = {}
    libs = {}
    expected_abi = [C.sizeof(Number), C.sizeof(Result), Result.value.offset,
        Result.consumed.offset, Result.unsupported_token.offset, C.sizeof(Storage),
        Storage.ram.offset, Storage.ram_size.offset, Storage.rom.offset,
        Storage.rom_size.offset, C.sizeof(Source), Source.input_address.offset,
        Source.output_address.offset, Source.before_sample.offset,
        Source.userdata.offset]
    for opt in ('O2', 'O3'):
        shared = build / ('coordinate-' + opt + '.so')
        subprocess.run(['gcc', '-std=c99', '-' + opt, '-Wall', '-Wextra',
            '-Werror', '-shared', '-fPIC',
            '-I' + str(snapshot / 'csrc'),
            *[str(snapshot / name) for name in sources], str(abi_source),
            '-o', str(shared)], check=True)
        artifacts[str(shared)] = digest(shared)
        lib = C.CDLL(str(shared))
        lib.coordinate_test_abi.argtypes = [C.c_uint]
        lib.coordinate_test_abi.restype = C.c_size_t
        actual_abi = [lib.coordinate_test_abi(i) for i in range(len(expected_abi))]
        require_abi(actual_abi, expected_abi)
        fn = lib.fx_evaluate_prepared_source
        fn.argtypes = [C.c_size_t, C.c_void_p, C.c_void_p, C.c_void_p,
            C.c_void_p, C.c_void_p, C.POINTER(Storage), C.POINTER(Source),
            C.POINTER(C.c_uint16), C.c_void_p, C.POINTER(Result)]
        fn.restype = C.c_int
        lib.fx_decimal_parse.argtypes = [C.POINTER(Number), C.c_char_p]
        lib.fx_decimal_parse.restype = C.c_int
        lib.fx_eval_surd_workspace_sqrt.argtypes = [C.POINTER(Number),
            C.POINTER(C.c_uint8), C.POINTER(Number), C.c_int]
        lib.fx_eval_surd_workspace_sqrt.restype = C.c_int
        libs[opt] = lib

    # Original instruction execution with a passive observed minimum SP.
    # integral mutation/cancellation controls remain their zero defaults.
    rom = (root / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    rom_array = (C.c_uint8 * len(rom)).from_buffer_copy(rom)
    machine = Machine(rom, build / 'oracle')
    native = build / 'observer.so'
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror',
        '-shared', '-fPIC', str(root / 'tools/nxu8/integral_storage_events.c'),
        str(root / 'tools/nxu8/vendor/SimU8/core.c'), '-o', str(native)], check=True)
    artifacts[str(native)] = digest(native)
    observer = C.CDLL(str(native))
    for name in ('harness_init', 'harness_ram', 'harness_set_pc',
            'harness_get_pc', 'harness_set_reg', 'harness_get_reg',
            'harness_set_sp', 'harness_get_sp', 'harness_set_lr'):
        getattr(observer, name).argtypes = getattr(machine.lib, name).argtypes
        getattr(observer, name).restype = getattr(machine.lib, name).restype
    observer.integral_observer_reset.argtypes = []
    observer.integral_observer_reset.restype = None
    observer.integral_observer_run.argtypes = [C.c_uint64, C.c_uint32]
    observer.integral_observer_run.restype = C.c_int
    machine.lib = observer
    machine.ram = observer.harness_ram().contents

    def run_original(entry):
        observer.integral_observer_reset()
        observer.harness_set_sp(0x8dee)
        observer.harness_set_lr(0x2fffe)
        observer.harness_set_pc(entry)
        completion = observer.integral_observer_run(3_000_000, 0x2fffe)
        if completion != 100:
            raise RuntimeError(f'Original failed to return: entry={entry:x}, '
                f'completion={completion}, PC={observer.harness_get_pc():x}')
        floor = C.c_uint.in_dll(observer, 'integral_floor').value
        if not 0x8780 <= floor <= 0x8dee:
            raise RuntimeError(f'Observed CPU frame overlaps persistent pool: {floor:x}')
        return floor

    parser_rows = []
    failures = []
    for index, case in enumerate(inputs['parser']):
        raw = bytes.fromhex(case['tokens'])
        if not raw or raw[-1] != 0:
            raise ValueError('Expected complete zero-terminated calculator tokens')
        machine.reset()
        settings(machine)
        machine.ram[0x80f9] = case['mode']
        machine.ram[0x80fc] = 1
        machine.ram[0x8105] = 4
        machine.ram[0x8125] = 0
        for n in range(20):
            machine.ram[case['output'] + n] = 0xee
        for n, byte in enumerate(raw):
            machine.ram[case['input_address'] + n] = byte
        machine.word(0x9900, case['input_address'])
        initial = bytes(machine.ram)
        machine.er(0, 0x9900)
        machine.er(2, case['output'])
        floor = run_original(0x171f4)
        expected = bytes(machine.ram)
        status = machine.reg(0)
        cursor = machine.word(0x9900)
        row = dict(case, native_status=status, native_cursor=cursor,
            observed_cpu_frame=[floor, 0x8dee], comparisons={})
        for opt, lib in libs.items():
            ram = (C.c_uint8 * 65536).from_buffer_copy(initial)
            storage = Storage(ram, 65536, rom_array, len(rom))
            source = Source(case['input_address'], case['output'], None, None)
            returned = C.c_uint16(case['input_address'])
            result = Result()
            actual_status = lib.fx_evaluate_prepared_source(len(raw), None,
                None, None, None, None, C.byref(storage), C.byref(source),
                C.byref(returned), None, C.byref(result))
            actual = bytes(ram)
            output = case['output']
            pair_ok = actual[output:output + 20] == expected[output:output + 20]
            # Exclude only numeric scratch and the observed active CPU frame;
            # the native local source word is checked independently below.
            differences = [[address, expected[address], actual[address]]
                for address in range(0x80dc, 65536)
                if not floor <= address < 0x8dee
                and address not in (0x9900, 0x9901)
                and expected[address] != actual[address]]
            detail = dict(status=actual_status, cursor=returned.value,
                physical_output_match=pair_ok, ram_differences=differences)
            row['comparisons'][opt] = detail
            if actual_status != status or returned.value != cursor or not pair_ok or differences:
                failures.append(dict(group=case['group'], index=index,
                    optimization=opt, detail=detail))
        parser_rows.append(row)
        if (index + 1) % 100 == 0:
            print(f'Original parser controls {index + 1}/{len(inputs["parser"])}', flush=True)

    # Preserve44 original root calls per optimization, as in the initial88
    # control proof, and compare every record in the nonzero-seeded pool.
    root_rows = []
    for opt, lib in libs.items():
        for case in inputs['root']:
            source = Number.from_buffer_copy(bytes.fromhex(case['record']))
            parsed = Number()
            if (lib.fx_decimal_parse(C.byref(parsed), case['input'].encode()) != 0
                    or bytes(parsed) != bytes(source)):
                raise RuntimeError('Root fixture input record/decimal disagree')
            machine.reset()
            settings(machine)
            machine.ram[0x8106] = case['exact']
            for address in range(0x8640, 0x8780):
                machine.ram[address] = (address * 11 + 3) & 255
            for n, byte in enumerate(source.bytes):
                machine.ram[0x8300 + n] = byte
            initial = bytes(machine.ram)
            machine.er(0, 0x8300)
            floor = run_original(0x1c780)
            expected = bytes(machine.ram)
            ram = (C.c_uint8 * 65536).from_buffer_copy(initial)
            output = Number()
            status = lib.fx_eval_surd_workspace_sqrt(C.byref(output), ram,
                C.byref(source), case['exact'])
            actual = bytes(ram)
            differences = [[address, expected[address], actual[address]]
                for address in range(0x8640, 0x8780)
                if expected[address] != actual[address]]
            root_row = dict(case, optimization=opt, status=status,
                native_record=expected[0x8300:0x830a].hex(),
                C_record=bytes(output.bytes).hex(), observed_cpu_frame=[floor,0x8dee],
                pool_differences=differences)
            root_rows.append(root_row)
            if status != 0 or bytes(output.bytes) != expected[0x8300:0x830a] or differences:
                failures.append(dict(group='root-88', detail=root_row))

    # Refuse even a --no-report result attributed to changed source/oracle,
    # generated ABI, compiler artifacts, or any implementation snapshot.
    require_unchanged(input_pins)
    require_unchanged({str(snapshot / name):
        input_pins[str((implementation / name).resolve())] for name in closure})
    require_unchanged({**artifacts, **generated_inputs})
    negative_guards = check_negative_guards(build, expected_abi,
        snapshot / 'csrc/parse/fx_eval_transport.h',
        build / 'coordinate-O2.so', fixture,
        '84a37e53f67fafb57ada48722da9e95bbf9d875719151fc358febc62c5334dff')
    report = dict(status='pass' if not failures else 'fail', failures=failures,
        cases=len(parser_rows)*2 + len(root_rows) + len(expected_abi)*2 + len(negative_guards),
        negative_guards=negative_guards,
        full_firmware_complete=False, parser_native_calls=len(parser_rows),
        parser_comparisons_per_optimization=len(parser_rows), root_native_calls=len(root_rows),
        groups=dict(counts), abi_values=expected_abi, tested_inputs_sha256=input_pins,
        compiled_artifacts_sha256=artifacts, generated_inputs_sha256=generated_inputs,
        exclusions=['Parser numeric scratch8000..80DB',
            'Per-call actually observed minSP..8DED CPU frame',
            'Native harness cursor9900/9901, independently checked as returned source'],
        root_scope='Result and entire32-record SURD pool; no claim about other root RAM.',
        limitations=['Prepared original171F4 calls, not a full UI lifecycle.',
            'Physical SURD coordinate input/argument conversion is outside this fixture.'],
        parser_rows=parser_rows, root_rows=root_rows)
    if failures:
        (build / 'failure-diagnostics.json').write_text(json.dumps(report, indent=2) + '\n')
        raise SystemExit(f'{len(failures)} mismatches; retained failure diagnostics')
    if not args.no_report:
        write_report(root / 'analysis/c-verification/coordinate_workspace.json',
            report, sources + ['analysis/coordinate-workspace-inputs.json',
                'tools/test_eval_c.py', 'tools/trace_natural_result.py',
                'tools/nxu8/integral_storage_events.c'],
            'tools/test_coordinate_workspace_c.py')
    print(json.dumps(dict(status='pass', groups=dict(counts),
        parser_native_calls=len(parser_rows), root_native_calls=len(root_rows),
        parser_comparisons_per_optimization=len(parser_rows), failures=0)), flush=True)


if __name__ == '__main__':
    main()
