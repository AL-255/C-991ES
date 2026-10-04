#!/usr/bin/env python3
"""Compare explicit evaluator globals and preserved output with original171F4.

The unmodified ROM supplies expected records, cursors, variable transactions,
and18212 permission. This covers prepared calls, not SOLVE's equation grammar.
"""
import argparse
import ctypes as C
import hashlib
import itertools
import json
import random
import subprocess
from collections import Counter

from c_build_inputs import implementation_inputs
from c_verification import ROOT, write_report
from nxu8.machine import Machine
from trace_natural_result import settings
from test_eval_variables_c import Number, Options, Result, Variables, SOURCES


class Environment(C.Structure):
    _fields_ = [(name, C.c_uint8) for name in
                ('screen', 'prior_operation', 'complex_format', 'restricted_state',
                 'display_mode', 'digits', 'selected_base')]


class State(C.Structure):
    _fields_ = [('variables', C.POINTER(Variables)), ('linear_algebra', C.c_void_p)]


class Storage(C.Structure):
    _fields_ = [('ram', C.POINTER(C.c_uint8)), ('ram_size', C.c_size_t),
                ('rom', C.POINTER(C.c_uint8)), ('rom_size', C.c_size_t)]


class Effects(C.Structure):
    _fields_ = [('equation_used', C.c_uint8), ('restricted_state', C.c_uint8)]


ABI_PROBE = r'''
#include <stddef.h>
#include "parse/fx_eval.h"
size_t environment_test_abi(unsigned index) {
    const size_t sizes[] = {sizeof(fx_eval_options), sizeof(fx_eval_environment),
        sizeof(fx_eval_variables), sizeof(fx_eval_result), sizeof(fx_eval_state),
        offsetof(fx_eval_result, consumed), offsetof(fx_eval_result, unsupported_token),
        sizeof(fx_eval_storage), sizeof(fx_eval_effects)};
    return sizes[index];
}
'''


NATIVE_WRITE_PROBE = r'''/* Passive write-PC observation; original CPU unchanged. */
#define memorySetData environment_original_memory_set
#define harness_init environment_original_init
#include "harness.c"
#undef memorySetData
#undef harness_init
uint32_t environment_write_pc[65536];
void memorySetData(SR_t segment,EA_t offset,size_t size,uint64_t value) {
    environment_original_memory_set(segment,offset,size,value);
    if(!segment)for(size_t i=0;i<size;++i) {
        uint16_t address=(uint16_t)(offset+i);
        if(address>=0x8000)environment_write_pc[address]=last_address;
    }
}
void harness_init(const uint8_t *bytes,size_t size) {
    memset(environment_write_pc,0,sizeof environment_write_pc);
    environment_original_init(bytes,size);
}
'''


# Native numerical serializers/record copies observed independently from the
# C entry. A new writer remains a mismatch until its instruction is reviewed.
NUMERICAL_WORKSPACE_WRITERS = frozenset((
    0x0b958, 0x17816, 0x17818, 0x1786e, 0x17870, 0x178b4, 0x178b6,
    0x17912, 0x17914, 0x17926, 0x17928, 0x17936, 0x17938,
    0x1bb04, 0x1bb06, 0x1bb08, 0x1bb0a, 0x1bb0c, 0x1bb0e,
    0x1bb10, 0x1bb12, 0x1bb14, 0x1cdc4, 0x1cdcc, 0x1d14e, 0x1d150))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--random-cases', type=int, default=600)
    ap.add_argument('--no-report', action='store_true')
    ap.add_argument('--typed-only', action='store_true',
                    help='Replay unfiltered typed API diagnostics; never publish a canonical report')
    args = ap.parse_args()
    if args.random_cases < 0: ap.error('--random-cases must be nonnegative')
    sources = list(SOURCES)
    if 'parse/fx_eval_storage.c' not in sources: sources.append('parse/fx_eval_storage.c')
    build = ROOT / 'analysis/build/eval-environment'
    build.mkdir(parents=True, exist_ok=True)
    dependencies = implementation_inputs(ROOT, ['csrc/'+name for name in sources])
    dependencies += ['tools/test_eval_environment_c.py', 'tools/test_eval_variables_c.py',
                     'tools/test_eval_complex_c.py', 'tools/c_build_inputs.py',
                     'tools/c_verification.py', 'tools/trace_natural_result.py',
                     'tools/verify_firmware.py', 'tools/nxu8/decoder.py',
                     'tools/nxu8/machine.py', 'tools/nxu8/harness.c',
                     'tools/nxu8/vendor/SimU8/core.c',
                     'firmware/fx-991es-plus-c-ver4.bin']
    dependencies += [str(p.relative_to(ROOT)) for p in
                     (ROOT/'tools/nxu8/vendor/SimU8').glob('*.h')]
    # Pin before compiling, even for a no-report preview. Concurrent edits must
    # not attach results from an older shared library to newer source hashes.
    pinned = {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
              for name in sorted(set(dependencies))}
    shared = build / 'eval-environment.so'
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-shared', '-fPIC', '-I', str(ROOT/'csrc'),
                    *[str(ROOT/'csrc'/name) for name in sources],
                    '-x', 'c', '-', '-o', str(shared)], input=ABI_PROBE,
                   text=True, check=True)
    lib = C.CDLL(str(shared))
    lib.fx_evaluate_prepared.argtypes = [C.POINTER(C.c_uint8), C.c_size_t,
        C.POINTER(Options), C.POINTER(Environment), C.POINTER(State), C.c_void_p,
        C.POINTER(Number), C.POINTER(Result)]
    lib.fx_evaluate_prepared.restype = C.c_int
    lib.fx_evaluate_prepared_with_prior_answer.argtypes = [C.POINTER(C.c_uint8), C.c_size_t,
        C.POINTER(Options), C.POINTER(Environment), C.POINTER(State), C.c_void_p,
        C.POINTER(Number), C.POINTER(Number), C.POINTER(Result)]
    lib.fx_evaluate_prepared_with_prior_answer.restype = C.c_int
    lib.fx_evaluate_prepared_with_storage.argtypes = [C.POINTER(C.c_uint8), C.c_size_t,
        C.POINTER(Options), C.POINTER(Environment), C.POINTER(State), C.c_void_p,
        C.POINTER(Number), C.POINTER(Number), C.POINTER(Storage), C.POINTER(Effects),
        C.POINTER(Result)]
    lib.fx_evaluate_prepared_with_storage.restype = C.c_int
    lib.fx_evaluate_with_variables.argtypes = [C.POINTER(C.c_uint8), C.c_size_t,
        C.POINTER(Options), C.POINTER(Variables), C.POINTER(Result)]
    lib.fx_evaluate_with_variables.restype = C.c_int
    lib.fx_evaluate.argtypes = [C.POINTER(C.c_uint8), C.c_size_t,
                              C.POINTER(Options), C.POINTER(Result)]
    lib.fx_evaluate.restype = C.c_int
    lib.fx_eval_default_options.restype = Options
    lib.fx_eval_default_environment.restype = Environment
    lib.fx_decimal_parse.argtypes = [C.POINTER(Number), C.c_char_p]
    lib.environment_test_abi.argtypes = [C.c_uint]
    lib.environment_test_abi.restype = C.c_size_t
    rom = (ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    rom_buffer = (C.c_uint8*len(rom)).from_buffer_copy(rom)
    machine = Machine(rom, build/'oracle')
    observer_source = build/'native-write-pc.c'; observer_source.write_text(NATIVE_WRITE_PROBE)
    observer_shared = build/'native-write-pc.so'
    subprocess.run(['gcc','-std=c99','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',
        '-I',str(ROOT/'tools/nxu8'),str(observer_source),
        str(ROOT/'tools/nxu8/vendor/SimU8/core.c'),'-o',str(observer_shared)],check=True)
    observer = C.CDLL(str(observer_shared))
    for name in ('harness_init','harness_set_pc','harness_get_pc','harness_set_reg','harness_get_reg',
                 'harness_set_sp','harness_get_sp','harness_set_lr','harness_ram','harness_run'):
        getattr(observer,name).argtypes=getattr(machine.lib,name).argtypes
        getattr(observer,name).restype=getattr(machine.lib,name).restype
    machine.lib=observer;machine.ram=observer.harness_ram().contents
    machine.counts=(C.c_uint64*0x18000).in_dll(observer,'execution_counts')
    machine.ram_writes=(C.c_uint64*65536).in_dll(observer,'ram_write_counts')
    machine.rom_reads=(C.c_uint64*0x30000).in_dll(observer,'rom_read_counts')
    native_writer=(C.c_uint32*65536).in_dll(observer,'environment_write_pc')
    machine.reset()
    failures, domains, witnesses = [], Counter(), {}
    typed_failures, typed_domains = [], Counter()
    raw_storage_differences, workspace_witnesses = [], []
    storage_calls = 0
    rng = random.Random(0x18212171f4)

    def decimal(text):
        n = Number()
        assert lib.fx_decimal_parse(C.byref(n), str(text).encode()) == 0
        return bytes(n)

    zero = bytes(10)
    surd = bytes.fromhex('80000001000201010100')
    fraction = bytes.fromhex('21a30000000000000301')
    marked = bytes.fromhex('41000000000000000001')
    rounded = decimal('1.23456789012345')
    retained = decimal('-7.25')

    def bank(real=surd, imaginary=zero):
        values = Variables()
        for slot in range(10):
            values.values[slot][0] = Number.from_buffer_copy(decimal(slot+2))
            values.values[slot][1] = Number.from_buffer_copy(decimal(-slot-1))
        values.values[2][0] = Number.from_buffer_copy(real)
        values.values[2][1] = Number.from_buffer_copy(imaginary)
        return values

    def mismatch(group, expected, actual, detail):
        domains[group] += 1
        if expected != actual:
            failure = dict(group=group, expected=expected, actual=actual, **detail)
            failures.append(failure)
            if len(failures) <= 12:
                preview = {key: value for key, value in failure.items()
                           if key not in ('initial_variables', 'expected', 'actual')}
                preview['expected'] = expected[:3] if len(expected) == 4 else expected
                preview['actual'] = actual[:3] if len(actual) == 4 else actual
                print(json.dumps(preview), flush=True)

    abi_expected = [3, 7, 200, C.sizeof(Result), C.sizeof(State),
                    Result.consumed.offset, Result.unsupported_token.offset,
                    C.sizeof(Storage), C.sizeof(Effects)]
    mismatch('public_ABI', abi_expected,
             [lib.environment_test_abi(i) for i in range(9)], {})
    mismatch('options_default_ABI', 'c10104', bytes(lib.fx_eval_default_options()).hex(), {})
    mismatch('environment_default', '01000000000009',
             bytes(lib.fx_eval_default_environment()).hex(), {})
    for tokens in (b'1', b'1\x4f3', b'\x982)', b'A+', b'1\x4f0',
                   b'\xc8', b'2\xc8', b'\x6c\xc8,4)'):
        raw = tokens+b'\0'
        buffer = (C.c_uint8*len(raw)).from_buffer_copy(raw)
        old, prepared, with_prior = Result(), Result(), Result()
        old_status = lib.fx_evaluate(buffer, len(raw), None, C.byref(old))
        prepared_status = lib.fx_evaluate_prepared(buffer, len(raw), None, None,
                                                  None, None, None, C.byref(prepared))
        prior_status = lib.fx_evaluate_prepared_with_prior_answer(buffer, len(raw),
            None, None, None, None, None, None, C.byref(with_prior))
        mismatch('NULL_defaults_public_API',
                 [old_status, bytes(old.value).hex(), old.consumed, old.unsupported_token],
                 [prepared_status, bytes(prepared.value).hex(), prepared.consumed,
                  prepared.unsupported_token], dict(tokens=raw.hex()))
        mismatch('NULL_prior_answer_public_API',
                 [prepared_status, bytes(prepared.value).hex(), prepared.consumed,
                  prepared.unsupported_token],
                 [prior_status, bytes(with_prior.value).hex(), with_prior.consumed,
                  with_prior.unsupported_token], dict(tokens=raw.hex()))
        assert bytes(buffer) == raw

    def check(tokens, group, env=None, context=0xc1, math_output=1,
              values=None, secondary=zero, unit=4, legacy=False, prior_answer=None,
              capture_globals=False, state_from_memory=False):
        nonlocal storage_calls
        environment = env or Environment(1, 0, 0, 0, 0, 0, 9)
        values = values if values is not None else bank()
        before = bytes(values)
        raw = tokens if tokens.endswith(b'\0') else tokens+b'\0'
        assert len(raw) <= 38, 'Prepared input must not overlap native variable M'
        machine.reset(); settings(machine)
        for address, value in [(0x80f9, context), (0x80fc, environment.screen),
                (0x80f5, environment.prior_operation), (0x810c, environment.complex_format),
                (0x8124, environment.restricted_state), (0x8102, environment.display_mode),
                (0x8103, environment.digits), (0x80fa, environment.selected_base),
                (0x8106, math_output), (0x8105, unit)]:
            machine.ram[address] = value
        machine.call(0x18212)
        permission = machine.reg(0)
        for slot in range(10):
            for part, base in ((0, 0x8226), (1, 0x8408)):
                for index, byte in enumerate(bytes(values.values[slot][part])):
                    machine.ram[base+slot*10+index] = byte
        prior_raw = prior_answer if prior_answer is not None else zero
        for index, byte in enumerate(prior_raw): machine.ram[0x828a+index] = byte
        for index, byte in enumerate(raw): machine.ram[0x8200+index] = byte
        for index, byte in enumerate(bytes([0xad])*10+secondary):
            machine.ram[0x8900+index] = byte
        machine.word(0x8190, 0x8200)
        machine.er(0, 0x8190); machine.er(2, 0x8900)
        # Keep the actual caller preimage. A post-native copy would already
        # contain the aliases this API must reproduce and is not an oracle.
        pre_native_ram = bytes(machine.ram)
        machine.call(0x171f4, limit=3000000)
        post_native_ram = bytes(machine.ram)
        expected_bank = Variables()
        for slot in range(10):
            for part, base in ((0, 0x8226), (1, 0x8408)):
                expected_bank.values[slot][part] = Number.from_buffer_copy(
                    bytes(machine.ram[base+10*slot:base+10*slot+10]))
        expected = [machine.reg(0), bytes(machine.ram[0x8900:0x8914]).hex(),
                    machine.word(0x8190)-0x8200, bytes(expected_bank).hex()]
        buffer = (C.c_uint8*len(raw)).from_buffer_copy(raw)
        option = Options(context, math_output, unit)
        typed_values = Variables.from_buffer_copy(before)
        typed_state = State(C.pointer(typed_values), None)
        initial = Number.from_buffer_copy(secondary)
        prior_number = Number.from_buffer_copy(prior_raw)
        result, typed_result = Result(), Result()
        option_before, environment_before = bytes(option), bytes(environment)
        call_args = [buffer, len(raw), C.byref(option),
            C.byref(environment) if env is not None else None, C.byref(typed_state),
            None, C.byref(initial)]
        if prior_answer is None:
            typed_status = lib.fx_evaluate_prepared(*call_args, C.byref(typed_result))
        else:
            typed_status = lib.fx_evaluate_prepared_with_prior_answer(*call_args,
                C.byref(prior_number), C.byref(typed_result))
        typed_actual = [typed_status, bytes(typed_result.value).hex(), typed_result.consumed,
                        bytes(typed_values).hex()]
        detail = dict(tokens=raw.hex(), corpus_group=group, context=context, math_output=math_output,
                      angle_unit=unit, environment=list(bytes(environment)),
                      native_permission=permission, initial_secondary=secondary.hex(),
                      initial_variables=before.hex(), initial_prior_answer=prior_raw.hex(),
                      capture_globals=capture_globals, state_from_memory=state_from_memory,
                      pre_native_ram_sha256=hashlib.sha256(pre_native_ram).hexdigest())
        typed_domains[group] += 1
        if expected != typed_actual:
            typed_failures.append(dict(group=group, expected=expected, actual=typed_actual, **detail))
        if args.typed_only:
            result = typed_result; actual = typed_actual
        else:
            bus_ram = (C.c_uint8*65536).from_buffer_copy(pre_native_ram)
            storage = Storage(bus_ram, len(bus_ram), rom_buffer, len(rom))
            state = State(None if state_from_memory else C.pointer(values), None)
            effects = Effects(0xad, 0xad)
            status = lib.fx_evaluate_prepared_with_storage(buffer, len(raw),
                None if capture_globals else C.byref(option),
                None if capture_globals or env is None else C.byref(environment),
                C.byref(state), None, C.byref(initial),
                C.byref(prior_number) if prior_answer is not None else None,
                C.byref(storage), C.byref(effects), C.byref(result))
            storage_calls += 1
            post_bus_ram = bytes(bus_ram)
            bus_bank = Variables()
            for slot in range(10):
                for part, base in ((0, 0x8226), (1, 0x8408)):
                    bus_bank.values[slot][part] = Number.from_buffer_copy(
                        bytes(bus_ram[base+10*slot:base+10*slot+10]))
            actual = [status, bytes(result.value).hex(), result.consumed, bytes(bus_bank).hex()]
            if not state_from_memory:
                mismatch('logical_and_physical_bank_coherence', bytes(bus_bank).hex(),
                         bytes(values).hex(), detail)
            mismatch('storage_policy_effects',
                     [machine.ram[0x8125]&1, machine.ram[0x8124]], list(bytes(effects)), detail)
            # All sixteen1695C slots include history/editor/ordinary imaginary
            # aliases. Compare inactive payload as well as active numbers.
            regions = [(0x80e0,0x8100), (0x8124,0x8126), (0x8226,0x8294),
                       (0x829e,0x883e)]
            differences = [(f'{address:04X}', post_native_ram[address], post_bus_ram[address])
                for lo,hi in regions for address in range(lo,hi)
                if post_native_ram[address] != post_bus_ram[address]]
            active_slots=set()
            for record in [before[i:i+10] for i in range(0,len(before),10)]+[prior_raw]:
                if record[0]>=0x90 or 0x60<=record[0]<0x80:active_slots.add(record[0]&15)
            # Allocation can create only4..8. Conservatively keep every
            # supplied rich source identity active, even if not consumed.
            active_slots.update(range(4,9))
            active_regions=[(0x829e+90*slot,0x829e+90*(slot+1)) for slot in active_slots]
            inactive_scratch=[]; semantic_differences=[]
            for difference in differences:
                address=int(difference[0],16)
                if (0x8640<=address<0x87d0 and
                    native_writer[address] in NUMERICAL_WORKSPACE_WRITERS and
                    not any(lo<=address<hi for lo,hi in active_regions)):
                    inactive_scratch.append([*difference,f'{native_writer[address]:05X}'])
                else:semantic_differences.append(difference)
            if differences:
                raw_storage_differences.append(dict(differences=differences,
                    active_slots=sorted(active_slots),**detail))
            if inactive_scratch:
                assert all(row[3]!='00000' for row in inactive_scratch)
                workspace_witnesses.append(dict(differences_with_last_native_write_pc=inactive_scratch,
                    active_slots=sorted(active_slots),**detail))
            mismatch('physical_storage_banks_pools_dimensions_and_masks', [], semantic_differences, detail)
            # The named API does not write the caller's native cursor/result
            # addresses or reproduce a CPU/numeric scratch frame. Every other
            # supplied byte must remain unchanged by the C entry.
            mutable = regions+[(0x8078,0x80dc)]
            scratch_staging = [(f'{address:04X}',post_native_ram[address],post_bus_ram[address])
                for address in range(0x8078,0x80dc)
                if pre_native_ram[address]!=post_bus_ram[address] and
                   post_native_ram[address]!=post_bus_ram[address]]
            mismatch('storage_scratch_staging_writes_match_native', [], scratch_staging, detail)
            outside = [(f'{address:04X}', old, new)
                for address,(old,new) in enumerate(zip(pre_native_ram,post_bus_ram)) if old!=new
                and not any(lo <= address < hi for lo,hi in mutable)]
            mismatch('storage_outside_prepared_region_preservation', [], outside, detail)
            mismatch('storage_prior_answer_preservation', prior_raw.hex(),
                     bytes(bus_ram[0x828a:0x8294]).hex(), detail)
        detail['unsupported_token'] = result.unsupported_token
        mismatch(group, expected, actual, detail)
        mismatch('input_and_option_preservation',
                 [raw.hex(), option_before.hex(), environment_before.hex(), secondary.hex()],
                 [bytes(buffer).hex(), bytes(option).hex(), bytes(environment).hex(), bytes(initial).hex()],
                 dict(tokens=raw.hex()))
        mismatch('native_input_and_global_Math_preservation',
                 [raw.hex(), math_output],
                 [bytes(machine.ram[0x8200:0x8200+len(raw)]).hex(), machine.ram[0x8106]],
                 dict(tokens=raw.hex()))
        mismatch('prior_answer_preservation', [prior_raw.hex(), prior_raw.hex()],
                 [bytes(prior_number).hex(), bytes(machine.ram[0x828a:0x8294]).hex()],
                 dict(tokens=raw.hex(), context=context))
        if tokens == b'A' and context == 0xc1 and before[40:50] == surd:
            witnesses[(environment.screen, math_output, permission)] = expected[1][:20]
        if legacy:
            old_values = Variables.from_buffer_copy(before); old = Result()
            old_status = lib.fx_evaluate_with_variables(buffer, len(raw), C.byref(option),
                                                        C.byref(old_values), C.byref(old))
            mismatch('legacy_default_equivalence', actual,
                     [old_status, bytes(old.value).hex(), old.consumed, bytes(old_values).hex()],
                     dict(tokens=raw.hex(), context=context, math_output=math_output))

    # The crossed gate corpus compares actual load/root behavior to native
    # output. It does not compute expected permission using the C predicate.
    for screen, prior, fmt, restricted, context, math_output in itertools.product(
            (1, 0x41, 0x81, 0xc0), (0xf0, 0xed), (0, 1, 2), (0, 1, 2, 3),
            (0xc1, 0xc4, 2), (0, 1, 2, 255)):
        env = Environment(screen, prior, fmt, restricted, 0, 0, 9)
        check(b'A', 'stored_surd_permission_gates', env, context, math_output)
        check(b'\x982)', 'new_surd_permission_gates', env, context, math_output)

    for screen, math_output, context in itertools.product(
            (1, 0x41, 0x81, 0xc0), (0, 1, 2, 255), (0xc1, 0xc4, 2)):
        env = Environment(screen, 0xf0, 0, 0, 0, 0, 9)
        for tokens in (b'1\x4f3', b'A+1', b'A\x47', b'3\x47', b'A+', b'1\x4f0', b'\x98\x601)'):
            check(tokens, 'fraction_arithmetic_store_and_error', env, context, math_output,
                  values=bank(fraction), secondary=retained if tokens in
                  (b'A+', b'1\x4f0', b'\x98\x601)') else zero)

    round_overflow = decimal('9.99999999999999e99')
    round_records = [rounded, decimal('-1.23456789012345'), decimal('999999999999999'),
                     decimal('.00000000005'), round_overflow,
                     fraction, surd, marked]
    for context, mode, digits in itertools.product((0xc1, 0xc4, 2), (0, 4, 8, 9), range(10)):
        env = Environment(1, 0xf0, 0, 0, mode, digits, 9)
        for record in round_records:
            check(b'\xb3A)', 'Rnd_display_precision', env, context, 1,
                  bank(record, decimal('-2.71828182845904') if context == 0xc4 else zero),
                  retained if record == round_overflow else zero)

    for context, math_output, tokens in itertools.product((0xc1, 0xc4, 2),
            (0, 1, 2, 255), (b'1', b'A', b'A+1', b'1\x4f3', b'\x982)', b'A+', b'1\x4f0')):
        check(tokens, 'NULL_environment_legacy_ABI', context=context,
              math_output=math_output, legacy=True)

    # Native1703C overrides C8 only in COMP and loads ID10 at828A. Keep it
    # separate from the ten public variable pairs and check context admission
    # as well as load conversion, implicit multiplication and coordinate writes.
    prior_records = [decimal('3'), decimal('-2'), rounded, fraction, surd,
                     bytes.fromhex('f1000000000000000000'),
                     bytes.fromhex('f3000000000000000000'),
                     bytes.fromhex('f6000000000000000000'),
                     bytes.fromhex('f9000000000000000000')]
    for screen, context, math_output, record, tokens in itertools.product(
            (1, 0x41, 0x81, 0xc0), (0xc1, 0xc4, 2), (0, 1, 2, 255),
            prior_records, (b'\xc8', b'2\xc8', b'\xc8A', b'\xc8+1',
                            b'\x6c\xc8,4)', b'\x6d\xc8,30)')):
        check(tokens, 'PreAns_context_load_and_coordinates',
              Environment(screen, 0xf0, 0, 0, 0, 0, 9), context, math_output,
              values=bank(fraction), secondary=retained, prior_answer=record)

    for index in range(args.random_cases):
        context = (0xc1, 0xc4, 2)[index % 3]
        env = Environment(rng.choice((1, 0x41, 0x81, 0xc0)), rng.choice((0xf0, 0xed, 0)),
                          rng.choice((0, 1, 2)), rng.randrange(4),
                          rng.choice((0, 4, 8, 9)), rng.randrange(10), 9)
        record = rng.choice(round_records)
        tokens = rng.choice((b'A', b'A+B', b'A\x4f3', b'\x982)', b'\xb3A)', b'A\x47', b'A+', b'1\x4f0'))
        check(tokens, 'random_environment_transactions', env, context,
              rng.choice((0, 1, 2, 255)), bank(record),
              retained if tokens in (b'A+', b'1\x4f0') else zero)

    for context, screen, tokens in itertools.product((0xc1,0xc4,2),
            (1,0x41,0x81,0xc0), (b'A',b'A+1',b'\xc8',b'3\x47',b'A+')):
        check(tokens, 'storage_NULL_globals_and_physical_bank_capture',
              Environment(screen,0xed,0,3,8,2,9), context, 0,
              values=bank(fraction), secondary=retained, prior_answer=surd,
              capture_globals=True, state_from_memory=True)

    # These records name high source slots that overlap numerical workspace.
    # Keep every such byte active and strict; the inactive-workspace rule must
    # never hide physical aliases from a supplied named reference.
    for identity, context, screen, tokens in itertools.product(range(10,16),
            (0xc1,0xc4,2), (1,0x41,0x81,0xc0), (b'A+1',b'2\xc8',b'\xc8+1')):
        record=bytes([0xf0|identity])+bytes(9)
        check(tokens, 'active_high_identity_physical_aliases',
              Environment(screen,0xf0,0,0,0,0,9), context, 1,
              values=bank(record), secondary=retained, prior_answer=record)

    # Native witnesses demonstrate that this corpus distinguishes global Math
    # from exact permission and bit6 from bit7; no implementation calculation
    # supplies these reference records.
    assert witnesses[(1, 1, 1)] == surd.hex()
    assert witnesses[(0x81, 1, 1)] == surd.hex()
    assert witnesses[(0x41, 1, 0)] != surd.hex()
    assert witnesses[(0xc0, 1, 0)] != surd.hex()
    assert witnesses[(1, 0, 0)] != surd.hex()
    changed = [name for name, digest in pinned.items()
               if hashlib.sha256((ROOT/name).read_bytes()).hexdigest() != digest]
    data = dict(cases=sum(domains.values()), domains=dict(domains), failures=failures,
                storage_calls=storage_calls, typed_diagnostic_cases=sum(typed_domains.values()),
                typed_diagnostic_mismatches=len(typed_failures), typed_only=args.typed_only,
                source_changed_during_run=changed, tested_inputs_sha256=pinned,
                comparison='Original18212 permission and171F4 status, full20-byte result, cursor, all200 logical/physical variable bytes, active physical storage payloads/all16 dimensions, full8124/8125 masks, policy effects and immutable caller inputs; all16 unfiltered raw payload differences are retained separately. Storage starts from the pre-native full RAM snapshot.',
                scope='Prepared COMP/CMPLX/DEC BASE-N environments, Rnd and arbitrary PreAns including all unfiltered raw-F arithmetic aliases. Numerical leaves, CPU frames and caller cursor/output aliases use named API outputs. Full rich arithmetic and SOLVE controller orchestration remain separate.',
                physical_storage_regions=[['80E0','8100'],['8124','8126'],['8226','8294'],['829E','883E']])
    data['raw_storage_difference_cases']=len(raw_storage_differences)
    data['inactive_numerical_workspace_difference_cases']=len(workspace_witnesses)
    data['workspace_comparison_contract']={
        'inactive_payload_range':['8640','87D0'],
        'condition':'Only bytes outside every supplied rich identity and allocator slots4..8; active high identities always remain strict comparisons.',
        'reviewed_native_write_pcs':[f'{pc:05X}' for pc in sorted(NUMERICAL_WORKSPACE_WRITERS)],
        'staging_operand_data':['8078','80DC'],
        'operand_condition':'Every C-mutated staging byte is compared to original native final RAM; unmodeled ordinary numeric scratch is not reproduced.',
        'claim':'Physical staging semantics, not all16 whole-CPU numerical workspace replay.',
        'write_pc_witnesses':'analysis/build/eval-environment/raw-storage-diagnostics.json'}
    (build/'raw-storage-diagnostics.json').write_text(json.dumps(dict(
        canonical=False,scope='Unfiltered all16 physical payload/dimension/mask differences and per-case native write-PC witnesses',
        raw_differences=raw_storage_differences,inactive_workspace_witnesses=workspace_witnesses,
        tested_inputs_sha256=pinned,source_changed_during_run=changed),indent=2)+'\n')
    (build/'result.json').write_text(json.dumps(data,indent=2)+'\n')
    (build/'typed-diagnostics.json').write_text(json.dumps(dict(
        scope='Unfiltered typed-only evaluator diagnostics; physical bus aliases are outside this API',
        canonical=False, cases=sum(typed_domains.values()), domains=dict(typed_domains),
        failures=typed_failures, tested_inputs_sha256=pinned,
        source_changed_during_run=changed),indent=2)+'\n')
    if failures or changed:
        (build/'failures.json').write_text(json.dumps(data, indent=2)+'\n')
        raise AssertionError(f'{len(failures)} environment mismatches; changed inputs: {changed}')
    if not args.no_report and not args.typed_only:
        data = write_report('analysis/c-verification/eval_environment.json', data,
                            dependencies, 'tools/test_eval_environment_c.py')
    print(json.dumps(dict(status='pass', cases=data['cases'], domains=dict(domains)), indent=2))


if __name__ == '__main__': main()
