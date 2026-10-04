#!/usr/bin/env python3
"""Fresh original-ROM comparisons for random expressions inside sum/product.

The fixture supplies preparation and input only. The native timer adapter
supplies a cancellation sample without changing executed CPU instructions.
This helper returns evidence to its caller and never publishes a report.
GPL-3.0-or-later.
"""
import ctypes as C
import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path

from nxu8.machine import Machine
from test_eval_variables_c import Number, Result, Variables
from test_eval_environment_c import Effects, State, Storage
from test_numeric_calculus_c import Cancel, Control


ROOT = Path(__file__).resolve().parents[1]
INPUT_PATH = ROOT / 'analysis/native-fixtures/parser-random-expression/calculus-inputs.json'
SOURCE_INPUTS = [
    'tools/eval_random_calculus.py', str(INPUT_PATH.relative_to(ROOT)),
    'tools/test_eval_variables_c.py', 'tools/test_eval_environment_c.py',
    'tools/test_eval_complex_c.py', 'tools/test_numeric_calculus_c.py',
    'tools/nxu8/calculus_host_events.c', 'tools/nxu8/machine.py',
    'tools/nxu8/harness.c', 'tools/nxu8/vendor/SimU8/core.c',
] + [str(p.relative_to(ROOT)) for p in sorted(
    (ROOT / 'tools/nxu8/vendor/SimU8').glob('*.h'))]


def _prepare(preparation, case):
    ram = bytearray(65536)
    flags = {
        0x80f9: preparation['context'], 0x80fc: preparation['screen'],
        0x80f5: preparation['prior_operation'], 0x8105: preparation['angle_unit'],
        0x8106: case['math_output'], 0x80fa: preparation['selected_base'],
        0x8124: preparation['restricted_state'], 0x8121: 1,
    }
    for address, value in flags.items():
        ram[address] = value
    for address, value in (
        (0x821c, preparation['seed']), (0x8500, preparation['initial_pair']),
        (0x8226, preparation['real_variables100']),
        (0x8408, preparation['imaginary_variables100']),
        (0x828a, preparation['prior_answer']),
    ):
        raw = bytes.fromhex(value)
        ram[address:address + len(raw)] = raw
    for variable, value in case['real_overrides'].items():
        address = 0x8226 + 10 * int(variable)
        ram[address:address + 10] = bytes.fromhex(value)
    raw = bytes.fromhex(case['tokens']) + b'\0'
    address = preparation['input_address']
    ram[address:address + len(raw)] = raw
    for pointer in (preparation['cursor_address'], 0x812c):
        ram[pointer:pointer + 2] = address.to_bytes(2, 'little')
    return bytes(ram), raw


def run_calculus(lib, build, rom_bytes):
    """Run all 400 live inputs and return unfiltered comparison evidence."""
    source_hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                     for name in SOURCE_INPUTS}
    fixture = json.loads(INPUT_PATH.read_text())
    cases = fixture['cases']
    if len(cases) != 400 or len({row['id'] for row in cases}) != 400:
        raise ValueError('The normalized calculus fixture must contain 400 unique inputs')
    oracle = Path(build) / 'calculus-oracle'
    oracle.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        'gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror',
        '-shared', '-fPIC', str(ROOT / 'tools/nxu8/calculus_host_events.c'),
        str(ROOT / 'tools/nxu8/vendor/SimU8/core.c'),
        '-o', str(oracle / 'nxu8-harness.so'),
    ], check=True)
    native = Machine(rom_bytes, oracle)
    native.lib.calculus_oracle_call.argtypes = [C.c_uint32, C.c_uint64, C.c_uint]
    native.lib.calculus_oracle_call.restype = C.c_int
    poll_count = C.c_uint.in_dll(native.lib, 'calculus_oracle_polls')
    callback_count = C.c_uint.in_dll(native.lib, 'calculus_oracle_callbacks')
    callback_x = ((C.c_uint8 * 10) * 256).in_dll(native.lib, 'calculus_oracle_x')
    lib.fx_evaluate_prepared_with_storage.argtypes = [C.c_void_p, C.c_size_t] + [C.c_void_p] * 9
    lib.fx_evaluate_prepared_with_storage.restype = C.c_int
    rom_buffer = (C.c_uint8 * len(rom_bytes)).from_buffer_copy(rom_bytes)
    preparation = fixture['preparation']
    failures, native_nonreturns, observations = [], [], []
    domains, native_statuses, stops = Counter(), Counter(), Counter()
    checks = matching_calls = native_draws = 0
    for case in cases:
        initial, raw = _prepare(preparation, case)
        native.reset()
        native.ram[:] = initial
        native.er(0, preparation['cursor_address'])
        native.er(2, preparation['output_address'])
        execution = native.lib.calculus_oracle_call(0x171f4, 30000000, case['abort_poll'])
        after = bytes(native.ram)
        expected = {
            'status': native.reg(0), 'result20': after[0x8500:0x8514].hex(),
            'cursor': native.word(0x8190) - preparation['input_address'],
            'seed': after[0x821c:0x8226].hex(),
            'banks': (after[0x8226:0x829e] + after[0x8408:0x8476]).hex(),
            'polls': poll_count.value,
            'input_immutable': after[0x9000:0x9000 + len(raw)] == raw,
            'mask': after[0x8125], 'restricted_byte': after[0x8124],
            'equation_effect': after[0x8125] & 1,
            'restricted_effect': after[0x8124] & 1,
        }
        callbacks = callback_count.value
        sampled_x = [bytes(callback_x[index]).hex()
                     for index in range(min(callbacks, 256))]
        draws = int(native.counts[0x13db8 // 2])
        native_draws += draws
        ram = (C.c_uint8 * 65536).from_buffer_copy(initial)
        storage = Storage(ram, 65536, rom_buffer, len(rom_bytes))
        variables = Variables()
        for index in range(10):
            variables.values[index][0] = Number.from_buffer_copy(
                initial[0x8226 + 10 * index:0x8230 + 10 * index])
            variables.values[index][1] = Number.from_buffer_copy(
                initial[0x8408 + 10 * index:0x8412 + 10 * index])
        state = State(C.pointer(variables), None)
        published_x = []

        def cancel(_):
            published_x.append(bytes(variables.values[8][0]).hex())
            return int(bool(case['abort_poll'] and len(published_x) == case['abort_poll']))

        cancellation = Cancel(cancel)
        control = Control(cancellation, None)
        secondary = Number.from_buffer_copy(initial[0x850a:0x8514])
        source = C.create_string_buffer(raw)
        result, effects = Result(), Effects()
        status = lib.fx_evaluate_prepared_with_storage(
            source, len(raw), None, None, C.byref(state), C.byref(control),
            C.byref(secondary), None, C.byref(storage), C.byref(effects), C.byref(result))
        actual = {
            'status': status, 'result20': bytes(result.value).hex(),
            'cursor': result.consumed, 'seed': bytes(ram[0x821c:0x8226]).hex(),
            'banks': (bytes(ram[0x8226:0x829e]) + bytes(ram[0x8408:0x8476])).hex(),
            'polls': len(published_x), 'input_immutable': source.raw[:len(raw)] == raw,
            'mask': ram[0x8125], 'restricted_byte': ram[0x8124],
            'equation_effect': effects.equation_used,
            'restricted_effect': effects.restricted_state,
        }
        # The native adapter records X at callback entry after a successful
        # timer sample. A cancelling sample has no following body callback.
        actual['callback_x'] = published_x[:callbacks]
        expected['callback_x'] = sampled_x
        differences = {key: {'actual': actual[key], 'expected': value}
                       for key, value in expected.items() if actual[key] != value}
        checks += len(expected) + 1  # Includes the original normal-return guard.
        domain = 'sum' if raw[0] == 0x69 else 'product'
        domains[domain] += 1
        native_statuses[str(expected['status'])] += 1
        stops[str(execution)] += 1
        observation = {
            'id': case['id'], 'tokens': case['tokens'], 'domain': domain,
            'math_output': case['math_output'], 'abort_poll': case['abort_poll'],
            'native_stop': execution, 'native_callbacks': callbacks,
            'native_draws': draws, 'actual': actual, 'expected': expected,
            'published_x': published_x, 'differences': differences,
            'unsupported_token': result.unsupported_token,
        }
        observations.append(observation)
        if execution != 100:
            native_nonreturns.append(observation)
        if differences:
            failures.append(observation)
        elif execution == 100:
            matching_calls += 1
    changed = [name for name, digest in source_hashes.items()
               if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest]
    if changed:
        failures.append({'source_pin_changes': changed})
    return {
        'cases': len(cases), 'checks': checks, 'failures': failures,
        'native_nonreturns': native_nonreturns, 'matching_calls': matching_calls,
        'domains': dict(domains), 'native_statuses': dict(native_statuses),
        'native_draws': native_draws, 'native_stops': dict(stops),
        'source_inputs': SOURCE_INPUTS, 'source_hashes': source_hashes,
        'source_pin_changes': changed, 'observations': observations,
        'scope': 'Prepared COMP sum/product; status, result20, cursor, seed, full scalar banks, timer polls, published callback X, immutable input and storage effects. No whole-CPU scratch parity claim.',
    }
