#!/usr/bin/env python3
"""Live original-ROM verification of prepared linear EQN poll publication.

The fixed input-only corpus includes every cancellation boundary in the two
non-singular examples. Expected records and stages are collected afresh at
original14F0C; archived observations are never imported as expected outputs.
"""
from pathlib import Path
import argparse
import ctypes as C
import gzip
import hashlib
import json
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
if not (ROOT / 'tools/nxu8/machine.py').is_file():
    ROOT = Path.cwd().resolve()
sys.path.insert(0, str(ROOT / 'tools'))
from nxu8.machine import Machine
from trace_natural_result import settings
from c_build_inputs import implementation_inputs
from c_verification import write_report

SELF = Path(__file__).resolve()
TEST = 'tools/test_numeric_solver_stage_c.py'
FIXTURE = 'analysis/native-fixtures/numeric-solver-stage/inputs.json'
FIXTURE_SHA = '4bb553e948ce3e146d508e9345a6d843afbe6b08aec32a1747cbe99f3df6f7fa'
ORACLE = 'tools/nxu8/numeric_solver_stage_events.c'
ADAPTER = 'tools/nxu8/numeric_solver_stage_adapter.c'
SOURCES = [
    'csrc/numeric/fx_solver.c', 'csrc/numeric/fx_solver_classifier.c',
    'csrc/numeric/fx_numeric.c', 'csrc/linalg/fx_linalg.c',
    'csrc/complex/fx_complex.c', 'csrc/complex/fx_complex_round.c',
    'csrc/numeric/fx_root.c', 'csrc/numeric/fx_transcend.c',
    'csrc/trig/fx_trig_inverse.c', 'csrc/trig/fx_trig_math.c', 'csrc/trig/fx_trig.c',
    'csrc/numeric/fx_surd_components.c',
    'csrc/numeric/fx_raw_decimal_divide.c',
    'csrc/numeric/fx_raw_decimal_multiply_add.c',
    'csrc/numeric/fx_raw_decimal_parts.c'
]

class Number(C.Structure):
    _fields_ = [('bytes', C.c_uint8 * 10)]
    def raw(self): return bytes(self.bytes)
class Complex(C.Structure):
    _fields_ = [('real', Number), ('imaginary', Number)]
class Context(C.Structure):
    _fields_ = [('exact_math', C.c_uint8), ('real_only', C.c_uint8), ('cancel_at', C.c_uint32)]
class Result(C.Structure):
    _fields_ = [('roots', Complex * 3), ('count', C.c_uint8), ('firmware_status', C.c_uint8),
        ('cancellation_checks', C.c_uint32), ('coefficient_work', Number * 9),
        ('root_work', Number * 9), ('coefficient_rows', C.c_uint8),
        ('coefficient_columns', C.c_uint8), ('root_rows', C.c_uint8), ('root_columns', C.c_uint8)]
class Guard(C.Structure):
    _fields_ = [('before', C.c_uint8 * 16), ('result', Result), ('after', C.c_uint8 * 16)]
Callback = C.CFUNCTYPE(C.c_int, C.POINTER(Result), C.c_int, C.c_void_p)

def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def current_state(value):
    return {'work4': [n.raw().hex() for n in value.coefficient_work],
        'work5': [n.raw().hex() for n in value.root_work],
        'dims': bytes([value.coefficient_rows, value.coefficient_columns,
                      value.root_rows, value.root_columns]).hex()}
def ram_state(raw):
    return {'work4': [raw[0x8406 + i*10:0x8410 + i*10].hex() for i in range(9)],
        'work5': [raw[0x8460 + i*10:0x846a + i*10].hex() for i in range(9)],
        'dims': raw[0x80e8:0x80ec].hex()}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path)
    parser.add_argument('--fixture', type=Path)
    parser.add_argument('--oracle-source', type=Path)
    parser.add_argument('--adapter-source', type=Path)
    parser.add_argument('--optimization', choices=['O2', 'O3'])
    parser.add_argument('--private-report', type=Path)
    parser.add_argument('--no-report', action='store_true')
    args = parser.parse_args()
    source_root = args.source_root.resolve() if args.source_root else ROOT
    fixture = args.fixture.resolve() if args.fixture else ROOT / FIXTURE
    oracle_source = args.oracle_source.resolve() if args.oracle_source else ROOT / ORACLE
    adapter_source = args.adapter_source.resolve() if args.adapter_source else ROOT / ADAPTER
    private = bool(args.private_report or args.no_report)
    if (source_root != ROOT or args.fixture or args.oracle_source or args.adapter_source or
            args.optimization or not SELF.is_relative_to(ROOT)) and not private:
        parser.error('Custom/private or single-optimization runs cannot publish canonical reports')
    if args.private_report and args.private_report.resolve().is_relative_to(ROOT / 'analysis/c-verification'):
        parser.error('A private report cannot replace a canonical report')
    data = json.loads(fixture.read_text())
    if set(data) != {'basis', 'cases'} or len(data['cases']) != 58:
        parser.error('All 58 input-only recipes are required')
    if not args.fixture and digest(fixture) != FIXTURE_SHA:
        parser.error('Canonical input-only recipes changed')
    recipes = data['cases']
    for recipe in recipes:
        if set(recipe) != {'label', 'selector', 'mode', 'math', 'cancel_at', 'input'}:
            parser.error('Malformed input-only recipe')
        if recipe['selector'] not in [1, 2] or recipe['mode'] not in [0x45, 0x49] or recipe['math'] not in [0, 1]:
            parser.error('Recipe outside the prepared linear domain')
        if len(recipe['input']) != (6 if recipe['selector'] == 1 else 12):
            parser.error('Incomplete coefficient recipe')
        for raw in recipe['input']:
            if len(bytes.fromhex(raw)) != 10:
                parser.error('Each coefficient must contain ten raw bytes')
    paths = [source_root / name for name in implementation_inputs(source_root, SOURCES)]
    paths += [fixture, SELF, oracle_source, adapter_source,
        ROOT / 'firmware/fx-991es-plus-c-ver4.bin', ROOT / 'tools/nxu8/harness.c',
        ROOT / 'tools/nxu8/vendor/SimU8/core.c']
    paths += sorted((ROOT / 'tools/nxu8/vendor/SimU8').glob('*.h'))
    paths += [Path(module.__file__).resolve() for module in sys.modules.values()
        if getattr(module, '__file__', None) and Path(module.__file__).resolve().is_relative_to(ROOT / 'tools')]
    pins = {str(path): digest(path) for path in set(paths)}
    build_base = args.private_report.resolve().parent if args.private_report else ROOT / 'analysis/build/numeric/solver-stage'
    build = build_base / ('solver-stage-' + uuid.uuid4().hex)
    build.mkdir(parents=True, exist_ok=True)
    rom = (ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    optimizations = [args.optimization] if args.optimization else ['O2', 'O3']
    variants = []
    all_failures = []

    for optimization in optimizations:
        work = build / optimization
        work.mkdir()
        library = work / 'solver-stage.so'
        oracle = work / 'oracle'
        oracle.mkdir()
        subprocess.run(['gcc', '-std=c99', '-' + optimization, '-Wall', '-Wextra', '-Werror',
            '-pedantic', '-shared', '-fPIC', '-Wl,--no-undefined', '-I', str(source_root / 'csrc'),
            *[str(source_root / name) for name in SOURCES], str(adapter_source), '-o', str(library)], check=True)
        subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
            '-I', str(ROOT / 'tools/nxu8'), str(oracle_source), str(ROOT / 'tools/nxu8/vendor/SimU8/core.c'),
            '-o', str(oracle / 'nxu8-harness.so')], check=True)
        artifact_paths = {'solver': library, 'oracle': oracle / 'nxu8-harness.so'}
        artifacts_before = {name: digest(path) for name, path in artifact_paths.items()}
        machine = Machine(rom, oracle)
        machine.lib.solver_stage_run.argtypes = [C.c_uint64, C.c_uint]
        native_ram = (C.c_uint8 * (160 * 65536)).in_dll(machine.lib, 'solver_stage_ram')
        native_pc = (C.c_uint32 * 160).in_dll(machine.lib, 'solver_stage_pc')
        native_lr = (C.c_uint32 * 160).in_dll(machine.lib, 'solver_stage_lr')
        native_count = C.c_uint.in_dll(machine.lib, 'solver_stage_count')
        native_polls = C.c_uint.in_dll(machine.lib, 'solver_stage_polls')
        lib = C.CDLL(str(library))
        lib.solver_stage_abi.argtypes = [C.c_uint]
        lib.solver_stage_abi.restype = C.c_uint64
        observed = lib.fx_solver_solve_linear_observed
        observed.argtypes = [C.POINTER(Result), C.POINTER(Number), C.c_int,
                             C.POINTER(Context), Callback, C.c_void_p]
        old = lib.fx_solver_solve
        old.argtypes = [C.POINTER(Result), C.POINTER(Number), C.c_int, C.POINTER(Context)]
        failures, rows, nonreturns = [], [], []
        checks = c_calls = native_calls = callback_snapshots = 0
        def check(label, actual, expected, detail=None):
            nonlocal checks
            checks += 1
            if actual != expected:
                failures.append({'label': label, 'actual': actual, 'expected': expected, 'detail': detail})
        abi = [C.sizeof(Number), C.sizeof(Complex), C.sizeof(Context), C.sizeof(Result), C.sizeof(C.c_int),
            *[getattr(Context, name).offset for name in ['exact_math', 'real_only', 'cancel_at']],
            *[getattr(Result, name).offset for name in ['roots', 'count', 'firmware_status',
                'cancellation_checks', 'coefficient_work', 'root_work', 'coefficient_rows',
                'coefficient_columns', 'root_rows', 'root_columns']]]
        for index, expected in enumerate(abi):
            check(f'ABI/{index}', lib.solver_stage_abi(index), expected)
        with gzip.open(work / 'original-ram.bin.gz', 'wb') as archive:
            for recipe in recipes:
                machine.reset()
                settings(machine)
                machine.ram[0x80f9] = recipe['mode']
                machine.ram[0x80fa] = recipe['selector']
                machine.ram[0x8106] = recipe['math']
                # Deliberately invalid old dimensions/payload prove the entry initializes work.
                for i in range(16): machine.ram[0x80e0 + i] = 0xc0 + i
                for i in range(270): machine.ram[0x8406 + i] = (i*73 + 29) & 255
                records = [bytes.fromhex(raw) for raw in recipe['input']]
                for i, raw in enumerate(records):
                    for j, byte in enumerate(raw): machine.ram[0x829e + i*10 + j] = byte
                initial = bytes(machine.ram)
                archive.write(initial)
                machine.lib.solver_stage_reset()
                machine.lib.harness_set_sp(0x8dee)
                machine.lib.harness_set_lr(0x2fffe)
                machine.lib.harness_set_pc(0x14f0c)
                boundary = machine.lib.solver_stage_run(30000000, recipe['cancel_at'])
                native_calls += 1
                events = []
                for index in range(native_count.value):
                    raw = bytes(native_ram[index*65536:(index + 1)*65536])
                    archive.write(raw)
                    events.append({'pc': f'{native_pc[index]:06x}', 'lr': f'{native_lr[index]:06x}', **ram_state(raw)})
                if boundary not in [100, 105]:
                    nonreturns.append({'recipe': recipe, 'boundary': boundary, 'pc': machine.lib.harness_get_pc()})
                    failures.append({'label': recipe['label'], 'native_nonreturn': nonreturns[-1]})
                    continue
                expected_events = [event for event in events if event['pc'] == '005550']
                expected_final = {key: events[-1][key] for key in ['work4', 'work5', 'dims']}
                expected_status = 0 if boundary == 105 else machine.reg(0)
                expected_count = recipe['selector'] + 1 if boundary == 105 else 0
                expected_poll_count = native_polls.value
                # These assertions depend only on previously established original controls.
                label = recipe['label']
                if recipe['cancel_at']:
                    check(label + '/native_cancel', [boundary, machine.reg(0), expected_poll_count],
                          [100, 1, recipe['cancel_at']], recipe)
                elif label.startswith('linear'):
                    check(label + '/native_success', [boundary, expected_poll_count],
                          [105, 16 if recipe['selector'] == 1 else 34], recipe)
                else:
                    established = {'singular2': 6, 'singular3': 12, 'error-rhs': 12, 'error-matrix': 5}
                    check(label + '/native_error', [boundary, machine.reg(0), expected_poll_count],
                          [100, 3, established[label]], recipe)
                for cancellation in ['context', 'hook']:
                    inputs = (Number * 12)()
                    for i, raw in enumerate(records): inputs[i] = Number.from_buffer_copy(raw)
                    original_inputs = bytes(inputs)
                    context = Context(recipe['math'], 0, recipe['cancel_at'] if cancellation == 'context' else 0)
                    guarded = Guard()
                    C.memset(C.byref(guarded), 0xad, C.sizeof(guarded))
                    snapshots = []
                    @Callback
                    def callback(pointer, phase, userdata):
                        nonlocal callback_snapshots
                        value = pointer.contents
                        snapshots.append({'phase': phase, 'checks': value.cancellation_checks, **current_state(value)})
                        callback_snapshots += 1
                        return int(cancellation == 'hook' and recipe['cancel_at'] and
                                   value.cancellation_checks == recipe['cancel_at'])
                    host = observed(C.byref(guarded.result), inputs, recipe['selector'], C.byref(context), callback, None)
                    c_calls += 1
                    prefix = label + '/' + cancellation
                    check(prefix + '/host', host, 0, recipe)
                    check(prefix + '/inputs', bytes(inputs).hex(), original_inputs.hex(), recipe)
                    check(prefix + '/canaries', [bytes(guarded.before).hex(), bytes(guarded.after).hex()], ['ad'*16, 'ad'*16], recipe)
                    check(prefix + '/polls', len(snapshots), len(expected_events), recipe)
                    for index, (actual, event) in enumerate(zip(snapshots, expected_events)):
                        lr = int(event['lr'], 16)
                        phase = 0 if lr == 0x14fc0 else 2 if lr == 0x14fd8 else 3 if lr == 0x14200 else 1
                        expected = {'phase': phase, 'checks': index + 1,
                                    **{key: event[key] for key in ['work4', 'work5', 'dims']}}
                        check(prefix + f'/snapshot/{index + 1}', actual, expected, {'recipe': recipe, 'lr': event['lr']})
                    check(prefix + '/final_work', current_state(guarded.result), expected_final, recipe)
                    check(prefix + '/status', guarded.result.firmware_status, expected_status, recipe)
                    check(prefix + '/count', guarded.result.count, expected_count, recipe)
                    check(prefix + '/checks', guarded.result.cancellation_checks, expected_poll_count, recipe)
                    if cancellation == 'context':
                        baseline = Result()
                        old_status = old(C.byref(baseline), inputs, recipe['selector'], C.byref(context))
                        c_calls += 1
                        check(prefix + '/old_API', [old_status, bytes(baseline).hex()], [host, bytes(guarded.result).hex()], recipe)
                    rows.append({'label': prefix, 'native_boundary': boundary, 'native_status': expected_status,
                        'polls': expected_poll_count, 'host_status': host, 'snapshots': snapshots,
                        'final': current_state(guarded.result)})
        valid_inputs = (Number * 12)()
        for i, raw in enumerate(recipes[0]['input']): valid_inputs[i] = Number.from_buffer_copy(bytes.fromhex(raw))
        valid_context = Context(1, 0, 0)
        null_callback = Callback()
        for label, inputs, kind, context in [
            ('null_coefficients', None, 1, C.byref(valid_context)),
            ('null_context', valid_inputs, 1, None),
            ('kind0', valid_inputs, 0, C.byref(valid_context)),
            ('polynomial3', valid_inputs, 3, C.byref(valid_context)),
            ('kind255', valid_inputs, 255, C.byref(valid_context)),
            ('math2', valid_inputs, 1, C.byref(Context(2, 0, 0))),
            ('real_only2', valid_inputs, 1, C.byref(Context(1, 2, 0)))]:
            guarded = Guard()
            C.memset(C.byref(guarded), 0x5a, C.sizeof(guarded))
            before = bytes(guarded)
            status = observed(C.byref(guarded.result), inputs, kind, context, null_callback, None)
            c_calls += 1
            check(label, [status, bytes(guarded).hex()], [-1, before.hex()])
        check('null_output', observed(None, valid_inputs, 1, C.byref(valid_context), null_callback, None), -1)
        c_calls += 1
        expected = Result()
        check('alias_reference', observed(C.byref(expected), valid_inputs, 1, C.byref(valid_context), null_callback, None), 0)
        c_calls += 1
        for offset in [0, 10, 70, 119]:
            buffer = (C.c_uint8 * 640)()
            C.memset(buffer, 0x5c, C.sizeof(buffer))
            C.memmove(C.byref(buffer, 160), valid_inputs, C.sizeof(valid_inputs))
            output = C.cast(C.byref(buffer, 160 - offset), C.POINTER(Result))
            input_pointer = C.cast(C.byref(buffer, 160), C.POINTER(Number))
            before = bytes(buffer)
            status = observed(output, input_pointer, 1, C.byref(valid_context), null_callback, None)
            c_calls += 1
            start, end = 160 - offset, 160 - offset + C.sizeof(Result)
            check(f'alias/{offset}', [status, bytes(output.contents).hex()], [0, bytes(expected).hex()])
            check(f'alias/{offset}/outside', bytes(buffer[:start]).hex() + bytes(buffer[end:]).hex(), before[:start].hex() + before[end:].hex())
        artifacts_after = {name: digest(path) for name, path in artifact_paths.items()}
        artifact_changes = {name: {'before': artifacts_before[name], 'after': artifacts_after[name]}
            for name in artifact_paths if artifacts_before[name] != artifacts_after[name]}
        for name in artifact_paths:
            check('compiled_artifact/' + name, artifacts_after[name], artifacts_before[name])
        variant = {'optimization': optimization, 'native_calls': native_calls, 'c_calls': c_calls,
            'checks': checks, 'callback_snapshots': callback_snapshots, 'failures': failures,
            'native_nonreturns': nonreturns, 'rows': rows,
            'library_sha256': digest(library), 'oracle_library_sha256': digest(oracle / 'nxu8-harness.so'),
            'compiled_artifacts_before': artifacts_before, 'compiled_artifacts_after': artifacts_after,
            'compiled_artifact_changes': artifact_changes,
            'original_ram_archive': str(work / 'original-ram.bin.gz'),
            'original_ram_archive_sha256': digest(work / 'original-ram.bin.gz')}
        (work / 'observations.json').write_text(json.dumps(variant, indent=2) + '\n')
        variants.append(variant)
        all_failures.extend(failures)
        print(json.dumps({key: variant[key] for key in ['optimization', 'native_calls', 'c_calls', 'checks', 'callback_snapshots']}, indent=2), flush=True)
    changed = {path: {'before': before, 'after': digest(Path(path))}
        for path, before in pins.items() if digest(Path(path)) != before}
    report = {'status': 'pass' if not all_failures and not changed else 'fail', 'full_firmware_complete': False,
        'native_cases': 58, 'checks': sum(variant['checks'] for variant in variants),
        'variants': variants, 'failures': all_failures, 'source_changes': changed,
        'before_build_inputs_sha256': pins,
        'scope': 'Prepared immutable LINEAR2/LINEAR3 coefficients. Exact slot4/slot5 work and dimensions before every native timer poll, cancellation partial state, final numeric state, old API parity, input/output canaries, aliases, invalid host arguments and compiled ABI.',
        'limits': ['Physical timer/display/key scheduling is owned by the caller.',
            'Borrowed callback state and captured coefficient input are immutable.',
            'Caller15658 result/history export and E862 error-key continuation are outside this numerical stage API.']}
    (build / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    if args.private_report:
        args.private_report.parent.mkdir(parents=True, exist_ok=True)
        args.private_report.write_text(json.dumps(report, indent=2) + '\n')
    elif not args.no_report and report['status'] == 'pass':
        write_report('analysis/c-verification/numeric_solver_stage.json', report,
                     [str(path.relative_to(ROOT)) for path in paths], TEST)
    print(json.dumps({'status': report['status'], 'checks': report['checks'],
        'failures': len(all_failures), 'source_changes': changed, 'build': str(build)}, indent=2))
    return 0 if report['status'] == 'pass' else 1

if __name__ == '__main__':
    raise SystemExit(main())
