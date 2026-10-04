#!/usr/bin/env python3
"""Differential prepared SOLVE equation grammar and numerical callback bridge."""
import argparse
import ctypes as C
import hashlib
import importlib.util
import json
import random
import subprocess
import zlib
from pathlib import Path

import c_verification
from c_verification import ROOT, write_report
from c_build_inputs import implementation_inputs
from test_eval_complex_c import Number, Options, Result
from test_eval_variables_c import SOURCES, Variables

BASE = ROOT / 'analysis/native-fixtures/solve-expression-grammar/grammar-review'
FIX = BASE.parent/'fix-review'

class Environment(C.Structure):
    _fields_ = [(name, C.c_uint8) for name in ('screen', 'prior_operation',
        'complex_format', 'restricted_state', 'display_mode', 'digits', 'selected_base')]
class State(C.Structure):
    _fields_ = [('variables', C.POINTER(Variables)), ('linear_algebra', C.c_void_p)]
class Effects(C.Structure):
    _fields_ = [('equation_used', C.c_uint8), ('restricted_state', C.c_uint8)]
class SolveResult(C.Structure):
    _fields_ = [('root', Number), ('residual', Number), ('variable', Number),
        ('firmware_status', C.c_uint8), ('evaluations', C.c_uint32),
        ('cancellation_checks', C.c_uint32), ('alternate_starts', C.c_uint8)]
class Storage(C.Structure):
    _fields_ = [('ram', C.POINTER(C.c_uint8)), ('ram_size', C.c_size_t),
        ('rom', C.POINTER(C.c_uint8)), ('rom_size', C.c_size_t)]
class Expression(C.Structure):
    _fields_ = [('input', C.POINTER(C.c_uint8)), ('length', C.c_size_t),
        ('options', Options), ('environment', Environment), ('state', State),
        ('control', C.c_void_p), ('prior_answer', Number), ('selected_id', C.c_uint8),
        ('last_evaluation', Result), ('effects', Effects), ('evaluations', C.c_uint32),
        ('storage', C.POINTER(Storage))]

CALLBACK = C.CFUNCTYPE(C.c_int, C.POINTER(Number), C.POINTER(Number), C.c_void_p)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parser-source', type=Path, default=ROOT/'csrc/parse/fx_eval.c')
    parser.add_argument('--bridge-source', type=Path)
    parser.add_argument('--no-report', action='store_true')
    parser.add_argument('--random-cases', type=int, default=10000)
    parser.add_argument('--saved-only', action='store_true', help='Research smoke only; cannot publish canonical report')
    args = parser.parse_args()
    source = args.parser_source.resolve()
    if args.random_cases < 0: parser.error('--random-cases must be nonnegative')
    if args.saved_only and not args.no_report:
        parser.error('--saved-only requires --no-report')
    if source != ROOT/'csrc/parse/fx_eval.c' and not args.no_report:
        parser.error('A candidate parser requires --no-report')
    fixture_files = ['native-direct-pilot.json', 'native-expanded-fixtures.json',
        'native-callback-guard.json', 'native-suffix-fixtures.json',
        'native-prompt-stack-fixtures.json', 'native-shape-policy-fixtures.json',
        'native-stored-load-fixtures.json']
    manifest = json.loads((BASE/'research-manifest.json').read_text())
    for name in fixture_files:
        expected = manifest['fixture_files'][name]['sha256']
        if hashlib.sha256((BASE/name).read_bytes()).hexdigest() != expected:
            raise RuntimeError(f'Original immutable fixture changed: {name}')
    evidence_inputs = [str((BASE/name).relative_to(ROOT)) for name in fixture_files +
        ['research-manifest.json', 'assembly-stack7-probes.json',
         'assembly-callback-guard-probes.json', 'oracle.c', 'probe.py']]
    fix_manifest = json.loads((FIX/'manifest.json').read_text())
    fix_files = list(fix_manifest['fixture_files'])
    for name, item in fix_manifest['fixture_files'].items():
        if hashlib.sha256((FIX/name).read_bytes()).hexdigest() != item['sha256']:
            raise RuntimeError(f'Original independent-review fixture changed: {name}')
    evidence_inputs += [str((FIX/name).relative_to(ROOT))
        for name in fix_files+['manifest.json', 'collect.py']]
    for name in evidence_inputs:
        c_verification._BASELINE[name] = hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
    build = ROOT/'analysis/build/solve-parser'
    build.mkdir(parents=True, exist_ok=True)
    shared = build/'eval-solve.so'
    sources = [source if name == 'parse/fx_eval.c' else ROOT/'csrc'/name for name in SOURCES]
    if ROOT/'csrc/parse/fx_eval_storage.c' not in sources:
        sources.append(ROOT/'csrc/parse/fx_eval_storage.c')
    sources += [ROOT/'csrc/numeric/fx_solve.c']
    if args.bridge_source: sources.append(args.bridge_source.resolve())
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror',
        '-pedantic', '-shared', '-fPIC', '-I'+str(ROOT/'csrc/parse'),
        *map(str, sources), '-o', str(shared)], check=True)
    lib = C.CDLL(str(shared))
    lib.fx_evaluate_prepared_observed.argtypes = [C.POINTER(C.c_uint8), C.c_size_t,
        C.POINTER(Options), C.POINTER(Environment), C.POINTER(State), C.c_void_p,
        C.POINTER(Number), C.POINTER(Number), C.POINTER(Effects), C.POINTER(Result)]
    lib.fx_evaluate_prepared_observed.restype = C.c_int
    lib.fx_evaluate_prepared_with_storage.argtypes = [C.POINTER(C.c_uint8), C.c_size_t,
        C.POINTER(Options), C.POINTER(Environment), C.POINTER(State), C.c_void_p,
        C.POINTER(Number), C.POINTER(Number), C.POINTER(Storage), C.POINTER(Effects),
        C.POINTER(Result)]
    lib.fx_evaluate_prepared_with_storage.restype = C.c_int
    lib.fx_solve_root.argtypes = [C.POINTER(SolveResult), C.POINTER(Number), CALLBACK,
                                 C.c_void_p, C.c_void_p]
    lib.fx_solve_root.restype = C.c_int
    lib.fx_decimal_parse.argtypes = [C.POINTER(Number), C.c_char_p]
    lib.fx_decimal_integer_cleanup.argtypes = [C.POINTER(Number)]
    if args.bridge_source:
        lib.fx_solve_expression_init.argtypes = [C.POINTER(Expression),
            C.POINTER(C.c_uint8), C.c_size_t, C.c_uint8, C.POINTER(Options),
            C.POINTER(Environment), C.POINTER(State), C.c_void_p, C.POINTER(Number)]
        lib.fx_solve_expression_init.restype = C.c_int
        lib.fx_solve_expression_root.argtypes = [C.POINTER(SolveResult), C.POINTER(Expression)]
        lib.fx_solve_expression_root.restype = C.c_int
        lib.fx_solve_expression_set_storage.argtypes = [C.POINTER(Expression), C.POINTER(Storage)]
        lib.fx_solve_expression_set_storage.restype = C.c_int
    files = fixture_files
    rows = [(name, row) for name in files for row in json.loads((BASE/name).read_text())]
    rows += [('fix-review/'+name, row) for name in fix_files
        for row in json.loads((FIX/name).read_text())]
    child = json.loads((BASE/'assembly-stack7-probes.json').read_text())['fixtures']
    rows += [('assembly-stack7-probes.json', row) for row in child]
    guard_child = json.loads((BASE/'assembly-callback-guard-probes.json').read_text())
    for row in guard_child:
        rows.append(('assembly-callback-guard-probes.json', {
            'entry': '1074C', 'tokens': '583d3300', 'screen': 0xc0, 'descriptor': 4,
            'math': 1, 'context': 0xc1, 'selected': 8, 'initial': row['incoming'],
            'input_variables': {'8': '05000000000000000001'}, 'input_imaginary': {},
            'input_cursor': 0x8202, 'input_start': 0x8200, 'output_address': 0x8500,
            'prepared_trial_source': row['guard'], 'firmware_status': row['status'],
            'cursor': row['cursor'], 'result40': 'ad'*40,
            'callback_wrapper_pair': row['pair'], 'selected_record': row['selected'],
            'callback_count': row['parser_calls'], 'polls': 0}))
    failures, counts = [], {}
    checks = 0
    native = None
    native_storage_before = None
    if not args.saved_only:
        spec = importlib.util.spec_from_file_location('solve_native_grammar', BASE/'probe.py')
        native = importlib.util.module_from_spec(spec); spec.loader.exec_module(native)
        original = build/'original-grammar.so'
        subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror',
            '-pedantic', '-shared', '-fPIC', str(BASE/'oracle.c'),
            str(ROOT/'tools/nxu8/vendor/SimU8/core.c'), '-o', str(original)], check=True)
        fixture_builder = build/'original-input-builder.so'
        subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror',
            '-pedantic', '-shared', '-fPIC', str(ROOT/'csrc/numeric/fx_numeric.c'),
            '-o', str(fixture_builder)], check=True)
        native.lib = C.CDLL(str(fixture_builder))
        native.lib.fx_decimal_parse.argtypes = [C.POINTER(native.Number), C.c_char_p]
        native.lib.fx_rational_encode.argtypes = [C.POINTER(native.Number), C.POINTER(native.Rational)]
        previous = native.native
        native.native = C.CDLL(str(original))
        for function in ('harness_init', 'harness_ram', 'harness_set_reg', 'harness_get_pc', 'grammar_call'):
            getattr(native.native, function).argtypes = getattr(previous, function).argtypes
            getattr(native.native, function).restype = getattr(previous, function).restype
        original_call = native.native.grammar_call
        def capture_native_call(*arguments):
            nonlocal native_storage_before
            native_storage_before = bytes(native.native.harness_ram().contents)
            return original_call(*arguments)
        native.native.grammar_call = capture_native_call
        rom = (C.c_uint8*len(native.ROM)).from_buffer_copy(native.ROM)

    def storage_from_before(snapshot):
        # Capture precedes original execution; post-native RAM already includes
        # temporary copies and cannot serve as a differential's starting state.
        ram = (C.c_uint8*65536).from_buffer_copy(snapshot)
        return ram, Storage(ram, len(ram), rom, len(rom))

    def fail(kind, row, expected, actual):
        item = {'kind': kind, 'entry': row['entry'], 'tokens': row['tokens'],
            'screen': row['screen'], 'math': row['math'], 'selected': row['selected'],
            'initial': row['initial'], 'input_variables': row.get('input_variables', {}),
            'expected': expected, 'actual': actual}
        failures.append(item)
        if len(failures) <= 30: print(json.dumps(item))

    def compare(kind, row, expected, actual):
        nonlocal checks
        checks += 1
        if expected != actual: fail(kind, row, expected, actual)

    def prepared(row):
        values = Variables()
        real = bytes.fromhex(row.get('bank_before', ''))
        imaginary = bytes.fromhex(row.get('imaginary_before', ''))
        if not real:
            numbers = []
            for slot in range(11):
                value = Number()
                assert lib.fx_decimal_parse(C.byref(value), str(slot+2).encode()) == 0
                numbers.append(bytes(value))
            numbers[row['selected']] = bytes.fromhex(row['initial'])
            for slot, value in row.get('input_variables', {}).items(): numbers[int(slot)] = bytes.fromhex(value)
            real = b''.join(numbers)
        for slot in range(10):
            values.values[slot][0] = Number.from_buffer_copy(real[slot*10:slot*10+10])
            values.values[slot][1] = Number.from_buffer_copy(imaginary[slot*10:slot*10+10] or bytes(10))
        prior = Number.from_buffer_copy(real[100:110])
        metadata = bytes.fromhex(row.get('metadata_before', '00'*63))
        options = Options(row['context'], row['math'], 4)
        environment = Environment(row['screen'], 0xf0, 0, metadata[0x24], 0, 0, 0)
        state = State(C.pointer(values), None)
        return values, prior, options, environment, state

    def evaluate(raw, options, environment, state, prior, secondary, storage=None):
        buffer = (C.c_uint8*len(raw)).from_buffer_copy(raw)
        result, effects = Result(), Effects()
        arguments = [buffer, len(raw), C.byref(options), C.byref(environment),
            C.byref(state), None, C.byref(secondary), C.byref(prior)]
        if storage is None:
            status = lib.fx_evaluate_prepared_observed(*arguments,
                C.byref(effects), C.byref(result))
        else:
            status = lib.fx_evaluate_prepared_with_storage(*arguments,
                C.byref(storage), C.byref(effects), C.byref(result))
        assert bytes(buffer) == raw
        return status, result, effects

    if native:
        rng = random.Random(0x171f41074c)
        def remember_fresh(row):
            row['fresh_original'] = True
            # Sparse prepared RAM compresses cheaply, allowing every fresh
            # random case to retain its own pre-native memory without a 64K
            # allocation per saved row.
            row['_storage_before'] = zlib.compress(native_storage_before)
        atoms = [b'X', b'A', b'B', b'0', b'1', b'3', b'1\xae3', b'\x982)', b'\xa030)', b'\x821\xae3']
        suffixes = [b'', b',X', b',A', b',\x54', b',Y', b',\x8b', b',\xc8', b',2', b',', b':A', b')']
        def side(depth):
            if depth == 0 or rng.randrange(4) == 0: return rng.choice(atoms)
            choice = rng.randrange(6)
            if choice == 0: return b'('+side(depth-1)+b')'
            if choice == 1: return b'\x98'+side(depth-1)+b')'
            if choice == 2: return b'-'+side(depth-1)
            if choice == 3: return side(depth-1)+rng.choice([b'+', b'-', b'\x4e', b'\x4f', b'\xae'])+side(depth-1)
            if choice == 4: return side(depth-1)+b'\x75'
            return side(depth-1)+b'^'+side(depth-1)+b')'
        direct_boundaries = [
            b'(X=1', b'(X=1,A', b'X^1=2', b'\x981=1', b'((X=1',
            b'(X=1\x4f0)', b'(1\x4f0=X)', b'(X=\x98-1))', b'(X=(1\x4f0))',
            b'(X=1\x4f0', b'(X=1\x4f0,A', b'(X=1\x4f0:', b'(X=1\x4f0+1)',
            b'(X=1\xae0)', b'X=(1\x4f0=2)', b'(X=1\x4f0,2', b'1\xae0)',
            b'\x981\xae9)', b'\x984\xae9)', b'\x982\xae3)', b'\x981\xae3\x75)',
            b'1\xae3\xae-1,A', b'-1\xae3\xae-1,A', b'1\xae3\xae1\xae3',
            b'X=1\x4f0,2', b'X=1\x4f0,\xc8', b'X=1\x4f0,A,A', b'X=1\x4f0:1',
            b'X=1\x4f0)', b'X=3,A:tail']
        for context in (0xc1, 0xc4):
            for screen in (1, 0xc0):
                for depth in (4, 5, 6, 9, 10, 11):
                    row = native.run(b'1^'*depth+b'2', context=context, screen=screen,
                        name='fresh-numeric-stack-boundaries')
                    remember_fresh(row)
                    rows.append(('fresh-numeric-stack-boundaries', row))
                for depth in (23, 24, 25):
                    for prefix in (b'(', b'\x98'):
                        row = native.run(prefix*depth+b'1'+b')'*depth,
                            context=context, screen=screen, name='fresh-operator-stack-boundaries')
                        remember_fresh(row)
                        rows.append(('fresh-operator-stack-boundaries', row))
        for index, tokens in enumerate(direct_boundaries):
            row = native.run(tokens, screen=0xc0, math=index % 2, initial='1',
                name='fresh-boundary-equations')
            remember_fresh(row)
            rows.append(('fresh-boundary-equations', row))
        for index in range(args.random_cases):
            left, right = side(2), side(2)
            text = rng.choice([left, left+b'='+right, b'('+left+b'='+right+b')',
                left+b'='+right+b'=1', left+b'='+right+b',A'])+rng.choice(suffixes)
            row = native.run(text, screen=0xc0, math=index % 2, initial=str(rng.randint(-5, 5)),
                variables={2: str(rng.randint(-5, 5)), 3: str(rng.randint(-5, 5))},
                name='fresh-random-equations')
            remember_fresh(row)
            rows.append(('fresh-random-equations', row))

    for name, row in rows:
        entry = int(row['entry'], 16)
        counts[name] = counts.get(name, 0)+1
        memory_before = zlib.decompress(row['_storage_before']) if '_storage_before' in row else None
        if native and not row.get('fresh_original'):
            kwargs = dict(entry=entry, screen=row['screen'], math=row['math'],
                context=row['context'], selected=row['selected'],
                initial=bytes.fromhex(row['initial']),
                variables={int(k): bytes.fromhex(v) for k, v in row.get('input_variables', {}).items()},
                imaginary={int(k): bytes.fromhex(v) for k, v in row.get('input_imaginary', {}).items()},
                cursor=row['input_cursor'], start=row['input_start'],
                output=row.get('output_address', 0x8500), descriptor=row.get('descriptor', 4))
            if 'prepared_trial_source' in row: kwargs['trial_source'] = bytes.fromhex(row['prepared_trial_source'])
            current = native.run(bytes.fromhex(row['tokens']), **kwargs)
            memory_before = native_storage_before
            for key in ('firmware_status', 'cursor', 'result40', 'callback_wrapper_pair',
                        'selected_record', 'callback_count', 'callbacks', 'polls'):
                if key in row: compare('native-replay-'+key, row, row[key], current[key])
            for key in ('bank_after', 'imaginary_after', 'metadata_after'):
                if key in row: compare('native-replay-'+key, row, row[key], current[key])
        values, prior, options, environment, state = prepared(row)
        raw = bytes.fromhex(row['tokens'])
        if entry == 0x171f4:
            secondary = Number.from_buffer_copy(bytes.fromhex(row['result40'])[10:20])
            # Caller canary is AD; successes may replace it.
            secondary = Number.from_buffer_copy(bytes([0xad]*10))
            status, result, effects = evaluate(raw, options, environment, state, prior, secondary)
            compare('parser-status', row, row['firmware_status'], status)
            compare('parser-pair', row, row['result40'][:40], bytes(result.value).hex())
            compare('parser-cursor', row, (row['cursor']-row['input_start']) & 65535, result.consumed)
            if 'metadata_after' in row:
                meta = bytes.fromhex(row['metadata_after'])
                compare('parser-effects', row, [meta[0x25] & 1, meta[0x24]],
                        [effects.equation_used, effects.restricted_state])
            if 'bank_after' in row:
                got_real = b''.join(bytes(values.values[i][0]) for i in range(10))+bytes(prior)
                got_imag = b''.join(bytes(values.values[i][1]) for i in range(10))+bytes(10)
                compare('parser-bank', row, row['bank_after'], got_real.hex())
                compare('parser-imaginary', row, row['imaginary_after'], got_imag.hex())
            if memory_before is not None:
                memory_values, memory_prior, memory_options, memory_environment, memory_state = prepared(row)
                memory_ram, memory_storage = storage_from_before(memory_before)
                memory_status, memory_result, memory_effects = evaluate(raw, memory_options,
                    memory_environment, memory_state, memory_prior, secondary, memory_storage)
                compare('memory-parser-status', row, row['firmware_status'], memory_status)
                compare('memory-parser-pair', row, row['result40'][:40], bytes(memory_result.value).hex())
                compare('memory-parser-cursor', row,
                    (row['cursor']-row['input_start']) & 65535, memory_result.consumed)
                if 'bank_after' in row:
                    compare('memory-parser-bank', row, row['bank_after'], bytes(memory_ram[0x8226:0x8294]).hex())
                    compare('memory-parser-imaginary', row, row['imaginary_after'], bytes(memory_ram[0x8408:0x8476]).hex())
                if 'metadata_after' in row:
                    meta = bytes.fromhex(row['metadata_after'])
                    compare('memory-parser-effects', row, [meta[0x25] & 1, meta[0x24]],
                        [memory_effects.equation_used, memory_effects.restricted_state])
                    compare('memory-parser-mask', row, meta[0x25], memory_ram[0x8125])
        elif entry == 0x1074c:
            # Frozen numeric kernel owns source guard and cleanup. This direct
            # adapter reproduces their contract to exercise original wrappers.
            source_record = bytes.fromhex(row.get('prepared_trial_source', row['initial']))
            guard = source_record[0] & 15 if source_record[0] >= 0xf0 else 0
            if guard:
                status = guard
                pair = bytes([0xf0|guard])+bytes(9)
                actual_pair = pair+pair
                consumed = (row['input_cursor']-row['input_start']) & 65535
            else:
                point = Number.from_buffer_copy(source_record)
                lib.fx_decimal_integer_cleanup(C.byref(point))
                values.values[row['selected']][0] = point
                status, result, effects = evaluate(raw, options, environment, state, prior,
                                                   Number.from_buffer_copy(bytes([0xad]*10)))
                if status:
                    pair = bytes([0xf0|(status if 0 < status < 16 else 3)])+bytes(9)
                    actual_pair = pair+pair
                else: actual_pair = bytes(result.value)
                consumed = result.consumed
            compare('callback-status', row, row['firmware_status'], status)
            compare('callback-pair', row, row['callback_wrapper_pair'], actual_pair.hex())
            compare('callback-cursor', row, (row['cursor']-row['input_start']) & 65535, consumed)
            if memory_before is not None and not guard:
                memory_values, memory_prior, memory_options, memory_environment, memory_state = prepared(row)
                memory_values.values[row['selected']][0] = point
                memory_ram, memory_storage = storage_from_before(memory_before)
                memory_status, memory_result, memory_effects = evaluate(raw, memory_options,
                    memory_environment, memory_state, memory_prior,
                    Number.from_buffer_copy(bytes([0xad]*10)), memory_storage)
                if memory_status:
                    pair = bytes([0xf0|(memory_status if 0 < memory_status < 16 else 3)])+bytes(9)
                    memory_pair = pair+pair
                else: memory_pair = bytes(memory_result.value)
                compare('memory-callback-status', row, row['firmware_status'], memory_status)
                compare('memory-callback-pair', row, row['callback_wrapper_pair'], memory_pair.hex())
                compare('memory-callback-cursor', row,
                    (row['cursor']-row['input_start']) & 65535, memory_result.consumed)
        elif entry == 0x10000:
            if args.bridge_source:
                bridge_values, bridge_prior, bridge_options, bridge_environment, bridge_state = prepared(row)
                token_buffer = (C.c_uint8*len(raw)).from_buffer_copy(raw)
                expression, bridge_output = Expression(), SolveResult()
                ready = lib.fx_solve_expression_init(C.byref(expression), token_buffer, len(raw),
                    row['selected'], C.byref(bridge_options), C.byref(bridge_environment),
                    C.byref(bridge_state), None, C.byref(bridge_prior))
                compare('bridge-init', row, 0, ready)
                bridge_status = lib.fx_solve_expression_root(C.byref(bridge_output), C.byref(expression))
                compare('bridge-host-status', row, 0, bridge_status)
                if bridge_status == 0:
                    compare('bridge-status', row, row['firmware_status'], bridge_output.firmware_status)
                    compare('bridge-pair', row, row['result40'][:40],
                        (bytes(bridge_output.root)+bytes(bridge_output.residual)).hex())
                    compare('bridge-variable', row, row['selected_record'],
                        bytes(bridge_values.values[row['selected']][0]).hex())
                    compare('bridge-evaluations', row, row['callback_count'], expression.evaluations)
                    compare('bridge-polls', row, row['polls'], bridge_output.cancellation_checks)
                    if row['callbacks']:
                        last = row['callbacks'][-1]
                        compare('bridge-last-cursor', row,
                            (last['cursor']-row['input_start']) & 65535, expression.last_evaluation.consumed)
                        if last['status'] == 0:
                            compare('bridge-last-pair', row, last['pair'], bytes(expression.last_evaluation.value).hex())
                if memory_before is not None:
                    memory_values, memory_prior, memory_options, memory_environment, memory_state = prepared(row)
                    memory_ram, memory_storage = storage_from_before(memory_before)
                    memory_expression, memory_output = Expression(), SolveResult()
                    ready = lib.fx_solve_expression_init(C.byref(memory_expression), token_buffer,
                        len(raw), row['selected'], C.byref(memory_options), C.byref(memory_environment),
                        C.byref(memory_state), None, C.byref(memory_prior))
                    compare('memory-bridge-init', row, 0, ready)
                    attached = lib.fx_solve_expression_set_storage(C.byref(memory_expression), C.byref(memory_storage))
                    compare('memory-bridge-storage', row, 0, attached)
                    memory_status = lib.fx_solve_expression_root(C.byref(memory_output), C.byref(memory_expression))
                    compare('memory-bridge-host-status', row, 0, memory_status)
                    if memory_status == 0:
                        compare('memory-bridge-status', row, row['firmware_status'], memory_output.firmware_status)
                        compare('memory-bridge-pair', row, row['result40'][:40],
                            (bytes(memory_output.root)+bytes(memory_output.residual)).hex())
                        compare('memory-bridge-variable', row, row['selected_record'],
                            bytes(memory_values.values[row['selected']][0]).hex())
                        compare('memory-bridge-physical-variable', row, row['selected_record'],
                            bytes(memory_ram[0x8226+10*row['selected']:0x8230+10*row['selected']]).hex())
                        compare('memory-bridge-evaluations', row, row['callback_count'], memory_expression.evaluations)
                        compare('memory-bridge-polls', row, row['polls'], memory_output.cancellation_checks)
                        if row['callbacks']:
                            last = row['callbacks'][-1]
                            compare('memory-bridge-last-cursor', row,
                                (last['cursor']-row['input_start']) & 65535,
                                memory_expression.last_evaluation.consumed)
                            if last['status'] == 0:
                                compare('memory-bridge-last-pair', row, last['pair'],
                                    bytes(memory_expression.last_evaluation.value).hex())
            records, statuses, positions = [], [], []
            last_secondary = Number()
            @CALLBACK
            def callback(sides, point, userdata):
                nonlocal last_secondary
                values.values[row['selected']][0] = point[0]
                status, result, effects = evaluate(raw, options, environment, state, prior, last_secondary)
                sides[0] = result.value[0]; sides[1] = result.value[1]
                last_secondary = result.value[1]
                records.append(bytes(result.value).hex()); statuses.append(status); positions.append(result.consumed)
                return status
            output = SolveResult(); initial = Number.from_buffer_copy(bytes.fromhex(row['initial']))
            host_status = lib.fx_solve_root(C.byref(output), C.byref(initial), callback, None, None)
            compare('solve-host-status', row, 0, host_status)
            if host_status == 0:
                compare('solve-status', row, row['firmware_status'], output.firmware_status)
                compare('solve-pair', row, row['result40'][:40], (bytes(output.root)+bytes(output.residual)).hex())
                compare('solve-variable', row, row['selected_record'], bytes(output.variable).hex())
                compare('solve-evaluations', row, row['callback_count'], output.evaluations)
                compare('solve-polls', row, row['polls'], output.cancellation_checks)
                compare('solve-callback-statuses', row, [r['status'] for r in row['callbacks']], statuses)
                compare('solve-callback-cursors', row,
                    [(r['cursor']-row['input_start']) & 65535 for r in row['callbacks']], positions)
                # Callback error scratch retention is caller-specific; successful
                # original raw sides are the complete arithmetic contract.
                for index, expected in enumerate(row['callbacks']):
                    if expected['status'] == 0 and index < len(records):
                        compare('solve-successful-callback-pair', row, expected['pair'], records[index])
    data = {'status': 'pass' if not failures else 'fail', 'cases': len(rows), 'checks': checks,
        'groups': counts, 'failures': failures,
        'scope': 'Original prepared171F4 equation grammar,1074C callback contract and10000 numerical composition; no editor/UI/history claim.',
        'parser_source': str(source.relative_to(ROOT)), 'native_replayed': not args.saved_only,
        'parser_sha256': hashlib.sha256(source.read_bytes()).hexdigest()}
    (build/'result.json').write_text(json.dumps(data, indent=2)+'\n')
    print(json.dumps({k: v for k, v in data.items() if k != 'failures'}, indent=2))
    if failures: raise AssertionError(f'{len(failures)} SOLVE grammar mismatches')
    if not args.no_report:
        compiled = implementation_inputs(ROOT, [str(path.relative_to(ROOT)) for path in sources])
        inputs = compiled + evidence_inputs + [
            'tools/test_eval_complex_c.py', 'tools/test_eval_variables_c.py',
            'tools/c_build_inputs.py', 'tools/c_verification.py']
        write_report('analysis/c-verification/eval_solve.json', data, inputs,
                     'tools/test_eval_solve_c.py')

if __name__ == '__main__': main()
