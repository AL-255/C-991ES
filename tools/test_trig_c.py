#!/usr/bin/env python3
"""Fresh original special-result recognition, thresholds and eligibility.

The existing1517 controls are preserved. The additional544 native controls
come from input-only ROM-byte recipes; expected records are executed afresh.
Host invalid-argument checks are counted separately from original calls.
GPL-3.0-or-later.
"""
import argparse
import ctypes as C
import decimal
import hashlib
import itertools
import json
from pathlib import Path
import random
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if not (ROOT / 'csrc').is_dir():
    ROOT = Path.cwd().resolve()
sys.path.insert(0, str(ROOT / 'tools'))
from nxu8.machine import Machine
from trace_natural_result import settings
from c_build_inputs import implementation_inputs
from c_verification import write_report

SOURCES = ['csrc/trig/fx_trig.c', 'csrc/trig/fx_math_context.c',
           'csrc/numeric/fx_numeric.c']
FIXTURE = 'analysis/special-angle-trace/manifest.json'
ROM_SHA256 = '28b5c3907a67426a1601dbf82ebf62b850333e889fcc958d698786d3e5f5fb7d'
LEGACY_INPUT_SHA256 = '42e998f42d7cf53e0b28495243442c30f0d8910b9057b83b491d5dd356cd0680'
CONTEXTS = [
    ('enabled', {}, 1), ('operation-ED', {0x80f5: 0xed}, 0),
    ('operation-bit6', {0x80fc: 0x40}, 0), ('linear-output', {0x8106: 0}, 0),
    ('complex-format-one', {0x810c: 1}, 0),
    ('mode-no-bit6', {0x80f9: 0x81}, 0), ('restricted-state', {0x8124: 1}, 0),
    ('other-bits-and-nonzero', {0x80f5: 0xec, 0x80fc: 0xbf, 0x8106: 0xff,
                                0x810c: 2, 0x80f9: 0xff, 0x8124: 0xfe}, 1),
]

class Number(C.Structure):
    _fields_ = [('bytes', C.c_uint8 * 10)]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pointer(memory, offset):
    return C.cast(C.byref(memory, offset), C.POINTER(Number))


def prepare_context(machine, changes):
    machine.reset(); settings(machine)
    for address, value in changes.items():
        machine.ram[address] = value


def oracle(machine, record, function, changes):
    prepare_context(machine, changes)
    for index, value in enumerate(record): machine.ram[0x8300 + index] = value
    # Original post-numeric wrapper stack: source pointer and large-modelPC.
    machine.word(0x8de8, 0x8300); machine.word(0x8dea, 0xfffe)
    machine.ram[0x8dec] = 2
    machine.reg(0, 0); machine.reg(11, 0)
    machine.lib.harness_set_sp(0x8de8)
    machine.lib.harness_set_pc(0x16318 if function == 2 else 0x1627a)
    before = bytes(machine.ram)
    stop = machine.lib.harness_run(1000000, 0x2fffe, False)
    if stop != 100:
        raise RuntimeError(f'Native matcher did not return: stop={stop}, pc={machine.lib.harness_get_pc():x}')
    exact_reads = [sum(machine.rom_reads[address:address+10]) for address in
                   list(range(0x2a28, 0x2a5a, 10)) + list(range(0x2a82, 0x2aaa, 10))]
    return dict(record=bytes(machine.ram[0x8300:0x830a]),
                matched=bool(machine.counts[0x162de // 2]),
                native_status=machine.reg(0), instructions=sum(machine.counts),
                memory=before, exact_reads=exact_reads)


def decimal_value(record):
    digits = str(record[0] & 15) + ''.join(f'{value:02x}' for value in record[1:8])
    exponent = (record[8] >> 4) * 10 + (record[8] & 15)
    if record[9] % 5 == 0: exponent -= 100
    return decimal.Decimal(int(digits)) * decimal.Decimal(10) ** (exponent - 14)


def legacy_cases(lib, fixture):
    cases = []
    for row in fixture['cases']:
        if row['numeric_record_before_table'] is None: continue
        function = 2 if row['name'].startswith('tan') else 1 if row['name'].startswith('cos') else 0
        cases.append((row['name'], bytes.fromhex(row['numeric_record_before_table']),
                      function, row['math_output_8106']))
    with decimal.localcontext() as context:
        context.prec = 50
        for i, row in enumerate(fixture['tables']):
            value = decimal_value(bytes.fromhex(row['numeric_record']))
            threshold = decimal.Decimal('5e-12' if i >= 7 else '5e-13')
            for sign in [-1, 1]:
                for scale in ['-1.0001','-1','-.9999','-.5','0','.5','.9999','1','1.0001']:
                    number = Number()
                    literal = str(sign * (value + decimal.Decimal(scale) * threshold))
                    assert lib.fx_decimal_parse(C.byref(number), literal.encode()) == 0
                    for exact in [0, 1]:
                        for function in ([0, 1] if row['family'] == 'sin/cos' else [2]):
                            cases.append((f'boundary-{i}-{sign}-{scale}-{exact}-{function}',
                                          bytes(number.bytes), function, exact))
        randomizer = random.Random(16298)
        for i in range(1000):
            value = decimal.Decimal(randomizer.randrange(-1000000000000000,1000000000000000))
            value *= decimal.Decimal(10) ** randomizer.randrange(-28,-10)
            number = Number(); assert lib.fx_decimal_parse(C.byref(number), str(value).encode()) == 0
            cases.append((f'random-{i}', bytes(number.bytes), i%3, i%2))
    if len(cases) != 1517:
        raise ValueError('The unchanged legacy input inventory must contain1517 controls')
    inventory = json.dumps([(name, record.hex(), function, exact)
                            for name, record, function, exact in cases], separators=(',', ':')).encode()
    if hashlib.sha256(inventory).hexdigest() != LEGACY_INPUT_SHA256:
        raise ValueError('The unchanged1517 legacy input bytes/settings differ')
    return cases


def rom_cases(rom):
    # Integer mantissa changes avoid C/host decimal parsing at strict edges.
    pairs = [(a, a + 50, [0, 1]) for a in range(0x29f6, 0x2a28, 10)]
    pairs += [(a, a + 40, [2]) for a in range(0x2a5a, 0x2a82, 10)]
    cases = []
    for table, (address, exact_address, functions) in enumerate(pairs):
        record = rom[address:address + 10]
        if len(record) != 10 or record[0] >= 10:
            raise ValueError('Invalid stored decimal result')
        digits = str(record[0]) + ''.join(f'{value:02x}' for value in record[1:8])
        magnitude = int(digits)
        def perturbed(offset, negative):
            digits = f'{magnitude + offset:015d}'
            if len(digits) != 15 or digits[0] == '0':
                raise ValueError('A threshold recipe is outside normalized precision')
            return bytes([int(digits[0]), *(int(digits[i:i+2], 16) for i in range(1,15,2)),
                          record[8], record[9] + (5 if negative else 0)])
        for offset, negative, exact, function in itertools.product(
                [-501, -500, -499, 0, 499, 500, 501], [False, True], [0, 1], functions):
            cases.append(dict(name=f'rom-threshold-{table}-{offset}-{negative}-{exact}-{function}',
                              record=perturbed(offset, negative), function=function,
                              changes={0x8106: exact}, table=table, offset=offset,
                              negative=negative, decimal=record, exact=rom[exact_address:exact_address+10]))
        for name, changes, permission in CONTEXTS:
            for negative in [False, True]:
                cases.append(dict(name=f'rom-context-{table}-{negative}-{name}',
                                  record=perturbed(0, negative), function=functions[0],
                                  changes=changes, table=table, offset=0, negative=negative,
                                  decimal=record, exact=rom[exact_address:exact_address+10]))
    if len(cases) != 536:
        raise ValueError('The ROM-byte recipes must generate536 matcher controls')
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-dir', type=Path)
    parser.add_argument('--private-report', type=Path)
    parser.add_argument('--no-report', action='store_true')
    args = parser.parse_args()
    canonical_tool = Path(__file__).resolve() == (ROOT / 'tools/test_trig_c.py').resolve()
    if not canonical_tool and not (args.private_report or args.no_report):
        parser.error('A private tool requires --private-report or --no-report')
    if args.private_report and args.private_report.resolve().is_relative_to(
            (ROOT / 'analysis/c-verification').resolve()):
        parser.error('A private report must be outside analysis/c-verification')
    build = (args.build_dir or (ROOT / 'analysis/build/trig' if canonical_tool
                               else Path(__file__).resolve().parent / 'build')).resolve()
    # Capture the complete executed local C/Python/oracle closure before builds.
    inputs = [ROOT / name for name in implementation_inputs(ROOT, SOURCES)]
    helpers = ['tools/nxu8/machine.py', 'tools/nxu8/harness.c',
               'tools/nxu8/vendor/SimU8/core.c', 'tools/trace_natural_result.py',
               'tools/nxu8/decoder.py', 'tools/nxu8/isa.txt', 'tools/verify_firmware.py',
               'tools/c_verification.py', 'tools/c_build_inputs.py', FIXTURE,
               'firmware/fx-991es-plus-c-ver4.bin']
    inputs += [ROOT / name for name in helpers]
    inputs += list((ROOT / 'tools/nxu8/vendor/SimU8').glob('*.h'))
    inputs += [Path(__file__).resolve()]
    pins = {str(path): digest(path) for path in inputs}
    rom = (ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    if digest(ROOT / 'firmware/fx-991es-plus-c-ver4.bin') != ROM_SHA256 or rom[0x1ffe1] != 0:
        parser.error('The original ROM identity or fixed capability differs')
    fixture = json.loads((ROOT / FIXTURE).read_text())
    build.mkdir(parents=True, exist_ok=True)
    abi_source = build / 'trig-abi.c'
    abi_source.write_text('#include <stddef.h>\n#include "' + str(ROOT / 'csrc/trig/fx_trig.h') + '"\n' +
        'size_t trig_number_size(void) { return sizeof(fx_number); }\n' +
        'size_t trig_number_offset(void) { return offsetof(fx_number, bytes); }\n' +
        'size_t trig_number_payload(void) { return sizeof(((fx_number *)0)->bytes); }\n' +
        'size_t trig_unsigned_size(void) { return sizeof(unsigned); }\n')
    artifacts = {str(abi_source): digest(abi_source)}
    libraries = {}
    abi = {}
    for optimization in ['O2', 'O3']:
        path = build / f'trig-{optimization}.so'
        subprocess.run(['gcc', '-std=c99', '-' + optimization, '-Wall', '-Wextra',
                        '-Werror', '-pedantic', '-shared', '-fPIC',
                        *(str(ROOT / source) for source in SOURCES), str(abi_source),
                        '-o', str(path)], check=True)
        lib = C.CDLL(str(path)); ptr = C.POINTER(Number)
        lib.fx_trig_special_result.argtypes = [ptr, ptr, C.c_int, C.c_int, C.POINTER(C.c_uint)]
        lib.fx_trig_special_result.restype = C.c_int
        lib.fx_decimal_parse.argtypes = [ptr, C.c_char_p]
        lib.fx_decimal_parse.restype = C.c_int
        lib.fx_exact_output_allowed.argtypes = [C.POINTER(C.c_uint8)]
        lib.fx_exact_output_allowed.restype = C.c_int
        values = {}
        for name in ['trig_number_size', 'trig_number_offset', 'trig_number_payload', 'trig_unsigned_size']:
            probe = getattr(lib, name); probe.argtypes = []; probe.restype = C.c_size_t
            values[name] = probe()
        abi[optimization] = values
        libraries[optimization] = lib
        artifacts[str(path)] = digest(path)
    legacy = legacy_cases(libraries['O2'], fixture)
    added = rom_cases(rom)
    cases = [dict(name=name, record=record, function=function, changes={0x8106:exact})
             for name, record, function, exact in legacy] + added
    machine = Machine(rom, build / 'oracle')
    artifacts[str(build / 'oracle/nxu8-harness.so')] = digest(build / 'oracle/nxu8-harness.so')
    counts, failures = {}, []
    original_instructions = 0
    observations = []
    def check(group, condition, detail):
        counts[group] = counts.get(group, 0) + 1
        if not condition:
            if len(failures) < 40: print(json.dumps(dict(group=group, **detail)), flush=True)
            failures.append(dict(group=group, **detail))
    for optimization, values in abi.items():
        expected = {'trig_number_size': C.sizeof(Number), 'trig_number_offset': Number.bytes.offset,
                    'trig_number_payload': 10, 'trig_unsigned_size': C.sizeof(C.c_uint)}
        for name, value in values.items():
            check('compiled-abi', value == expected[name], dict(optimization=optimization, name=name, value=value))
    for index, case in enumerate(cases):
        observed = oracle(machine, case['record'], case['function'], case['changes'])
        original_instructions += observed['instructions']
        context_memory = observed['memory']
        expected_index = None
        if index >= len(legacy):
            table = case['table']; admitted = abs(case['offset']) < 500
            expected_index = (table + 1 if table < 5 else table - 4) if admitted else 0
            check('native-strict-ROM-boundary', observed['matched'] == admitted, dict(index=index, name=case['name']))
        for optimization, lib in libraries.items():
            context_image = (C.c_uint8 * 65536).from_buffer_copy(context_memory)
            permission = lib.fx_exact_output_allowed(context_image)
            check('immutable-context', bytes(context_image) == context_memory, dict(optimization=optimization, index=index))
            # The existing contexts use8106 alone; the new contexts can veto
            # an otherwise exact table match through any of the six gates.
            if index < len(legacy):
                check('legacy-permission', permission == case['changes'][0x8106], dict(optimization=optimization, index=index))
            layouts = [('separate', 48)]
            if index >= len(legacy):
                layouts += [(f'offset{offset:+}', 24+offset) for offset in [-9,-5,-1,0,1,5,9]]
            elif index < 100:
                layouts += [('input-alias', 24)]
            for label, destination in layouts:
                memory = (C.c_uint8 * 80)(*([0xa7] * 80)); memory[24:34] = case['record']
                before = bytes(memory)
                matched_words = (C.c_uint * 3)(0x12345678,0xdeadbeef,0x87654321)
                matched_ptr = C.cast(C.byref(matched_words,C.sizeof(C.c_uint)),C.POINTER(C.c_uint))
                status = lib.fx_trig_special_result(pointer(memory,destination),pointer(memory,24),
                                                     case['function'],permission,matched_ptr)
                wanted = bytearray(before); wanted[destination:destination+10] = observed['record']
                detail = dict(optimization=optimization,index=index,name=case['name'],alias=label)
                check('host-status', status == 0, detail)
                check('result-input-guards', bytes(memory) == wanted, detail)
                check('match-index', matched_words[1] == expected_index if expected_index is not None
                      else bool(matched_words[1]) == observed['matched'], detail)
                check('matched-word-guards', matched_words[0] == 0x12345678 and matched_words[2] == 0x87654321, detail)
            if index >= len(legacy) or index < 100:
                number = Number.from_buffer_copy(case['record']); output = Number()
                status = lib.fx_trig_special_result(C.byref(output),C.byref(number),case['function'],permission,None)
                check('optional-NULL-matched', status == 0 and bytes(output.bytes) == observed['record']
                      and bytes(number.bytes) == case['record'], dict(optimization=optimization,index=index))
            if index >= len(legacy):
                reads = observed['exact_reads']
                if observed['matched'] and permission:
                    check('selected-exact-ROM-block', reads[case['table']] >= 10 and
                          not any(value for table,value in enumerate(reads) if table != case['table']),
                          dict(optimization=optimization,index=index))
                    if not case['negative']:
                        check('positive-ROM-record', observed['record'] == case['exact'], dict(optimization=optimization,index=index))
                else:
                    check('no-exact-ROM-block-read', not any(reads), dict(optimization=optimization,index=index))
            if index < 100:
                number = Number.from_buffer_copy(case['record'])
                status = lib.fx_trig_special_result(C.byref(number),C.byref(number),case['function'],permission,None)
                check('legacy-NULL-matched-input-alias', status == 0 and bytes(number.bytes) == observed['record'],
                      dict(optimization=optimization,index=index))
        observations.append(dict(index=index,name=case['name'],input=case['record'].hex(),function=case['function'],
                                 context_changes={hex(k):v for k,v in case['changes'].items()},
                                 native_result=observed['record'].hex(),native_matched=observed['matched'],
                                 native_status=observed['native_status'],instructions=observed['instructions']))
    for name, changes, expected_permission in CONTEXTS:
        prepare_context(machine, changes); memory = bytes(machine.ram)
        machine.call(0x18212); original_instructions += sum(machine.counts)
        native_permission = machine.reg(0)
        check('native-eligibility-control', native_permission == expected_permission, dict(name=name))
        for optimization, lib in libraries.items():
            image = (C.c_uint8 * 65536).from_buffer_copy(memory)
            permission = lib.fx_exact_output_allowed(image)
            check('fresh-native-eligibility', permission == native_permission and bytes(image) == memory,
                  dict(optimization=optimization,name=name))
    # These test the host ABI only; the firmware is never called with a host
    # NULL address or an invalid C enum. Keep their inventory separate.
    host_negative_cases = 0
    for optimization, lib in libraries.items():
        for function, null_out, null_input in [(-2147483648,False,False),(-1,False,False),
                (3,False,False),(2147483647,False,False),(0,True,False),(0,False,True)]:
            memory = (C.c_uint8 * 80)(*([0x97] * 80)); memory[24:34] = rom[0x2a00:0x2a0a]
            before = bytes(memory)
            matched_words = (C.c_uint * 3)(0x12345678,0xdeadbeef,0x87654321)
            matched_ptr = C.cast(C.byref(matched_words,C.sizeof(C.c_uint)),C.POINTER(C.c_uint))
            status = lib.fx_trig_special_result(None if null_out else pointer(memory,48),
                    None if null_input else pointer(memory,24),function,1,matched_ptr)
            check('host-only-negative-arguments', status == -1 and bytes(memory) == before and
                  list(matched_words) == [0x12345678,0xdeadbeef,0x87654321],
                  dict(optimization=optimization,function=function,null_out=null_out,null_input=null_input))
            host_negative_cases += 1
        check('host-only-NULL-context', lib.fx_exact_output_allowed(None) == 0, dict(optimization=optimization))
        host_negative_cases += 1
    changed = [path for path,value in pins.items() if digest(path) != value]
    artifact_changes = [path for path,value in artifacts.items() if digest(path) != value]
    report = dict(status='fail' if failures or changed or artifact_changes else 'pass',
                  cases=sum(counts.values()), checks=counts, failures=len(failures), mismatches=failures,
                  legacy_native_calls=len(legacy), legacy_input_inventory_sha256=LEGACY_INPUT_SHA256,
                  rom_recipe_native_calls=len(added)+len(CONTEXTS),
                  native_calls=len(cases)+len(CONTEXTS), native_returned=len(cases)+len(CONTEXTS),
                  original_instructions=original_instructions, alias_cases=100,
                  threshold_overlap_offsets=[-9,-5,-1,0,1,5,9],
                  host_only_negative_cases=host_negative_cases, optimization_builds=['O2','O3'],
                  compiled_abi=abi, pre_execution_inputs_sha256=pins, input_changes=changed,
                  compiled_artifacts_sha256=artifacts, artifact_changes=artifact_changes,
                  native_observations=observations,
                  scope='native1627A/16318 matcher stage, original1517 controls plus536 ROM-byte thresholds/gate controls and8 original18212 eligibility calls',
                  input='identical computed records and input-only ROM mantissa/context recipes; existing decimal generator unchanged',
                  output='all10 result bytes, native match branch and selected exact ROM reads, source/guard preservation, aliases and eligibility',
                  limitation='prepared post-numeric wrapper contexts; full angle cores, malformedBCD, physical scratch/MMIO and reset/keyscan behavior are excluded')
    if args.private_report:
        args.private_report.parent.mkdir(parents=True,exist_ok=True)
        args.private_report.write_text(json.dumps(report,indent=2)+'\n')
    elif not args.no_report:
        path = ROOT / 'analysis/c-verification/trig.json'
        if report['status'] == 'pass':
            # The shared publisher snapshots C/Python/JSON/BIN dependencies.
            # isa.txt is additionally pinned by this suite's complete closure.
            publication_inputs = [name for name in helpers if Path(name).suffix != '.txt']
            write_report(path,report,SOURCES+publication_inputs,'tools/test_trig_c.py')
        else:
            path.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({key:report[key] for key in ['status','cases','legacy_native_calls',
                    'rom_recipe_native_calls','native_calls','original_instructions','host_only_negative_cases','failures']}))
    if report['status'] != 'pass': raise SystemExit(1)


if __name__ == '__main__': main()
