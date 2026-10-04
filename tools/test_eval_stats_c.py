#!/usr/bin/env python3
"""Fresh original171F4 proof for raw8A mean-Y parser integration.

Input-only recipes retain the complete whole-parser diagnostic corpus.
Known host and persistent-RAM gaps are reported separately from strict matches.
GPL-3.0-only.
"""
import argparse
import ctypes as C
import hashlib
import json
import re
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from c_build_inputs import implementation_inputs
from c_verification import ROOT, write_report
from nxu8.machine import Machine

INPUT = 'analysis/native-fixtures/stats-parser/inputs.json'
BUILD = ROOT / 'analysis/build/eval-stats'
OBSERVER = 'tools/nxu8/rich_parser_host_events.c'


class Number(C.Structure):
    _fields_ = [('bytes', C.c_uint8 * 10)]


class Result(C.Structure):
    _fields_ = [('value', Number * 2), ('consumed', C.c_size_t),
               ('unsupported_token', C.c_uint8)]


class Storage(C.Structure):
    _fields_ = [('ram', C.POINTER(C.c_uint8)), ('ram_size', C.c_size_t),
               ('rom', C.POINTER(C.c_uint8)), ('rom_size', C.c_size_t)]


class Effects(C.Structure):
    _fields_ = [('equation_used', C.c_uint8), ('restricted_state', C.c_uint8)]


Cancel = C.CFUNCTYPE(C.c_int, C.c_void_p)


class Control(C.Structure):
    _fields_ = [('cancelled', Cancel), ('userdata', C.c_void_p)]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--optimization', choices=('O2', 'O3'), default='O2')
    ap.add_argument('--no-report', action='store_true')
    ap.add_argument('--only-family', choices=('whole', 'finite-series'))
    args = ap.parse_args()
    if args.only_family and not args.no_report:
        ap.error('--only-family requires --no-report')
    fixture = json.loads((ROOT / INPUT).read_text())
    if fixture['schema'] != 'whole-parser-mean-y-inputs-v1':
        raise ValueError('Unsupported input-only fixture schema')
    allowed = {'id', 'family', 'label', 'mode', 'selected', 'frequency', 'count',
               'tokens', 'table', 'screen', 'math', 'diagnostic'}
    cases = fixture['cases']
    if len(cases) != 6092 or len({c['id'] for c in cases}) != len(cases):
        raise ValueError('Expected6092 uniquely retained inputs')
    if any(set(c) - allowed for c in cases):
        raise ValueError('Fixture contains fields outside input-only preparation')
    diagnostic_names = {'invalid-base-selector', 'table-input-output-frame-alias',
                        'exact-sqrt-workspace', 'screen-ff-result-alias'}
    if any(c.get('diagnostic') not in diagnostic_names | {None} for c in cases):
        raise ValueError('Unknown diagnostic input class')
    cmake = (ROOT / 'csrc/CMakeLists.txt').read_text().split('target_include_directories')[0]
    sources = ['csrc/' + s for s in re.findall(r'(?<![\w/])([\w/]+\.c)(?!\w)', cmake)]
    sources += ['csrc/stats/fx_stats.c', 'csrc/stats/fx_stats_value.c']
    sources = list(dict.fromkeys(sources))
    dependencies = implementation_inputs(ROOT, sources) + [
        'csrc/CMakeLists.txt', INPUT, 'tools/test_eval_stats_c.py',
        'tools/c_build_inputs.py', 'tools/c_verification.py', OBSERVER,
        'tools/nxu8/machine.py', 'tools/nxu8/harness.c',
        'tools/nxu8/vendor/SimU8/core.c', 'firmware/fx-991es-plus-c-ver4.bin',
    ] + [str(p.relative_to(ROOT)) for p in sorted((ROOT / 'tools/nxu8/vendor/SimU8').glob('*.h'))]
    dependencies = list(dict.fromkeys(dependencies))
    before = {p: digest(ROOT / p) for p in dependencies}
    BUILD.mkdir(parents=True, exist_ok=True)
    abi = BUILD / 'abi.c'
    abi.write_text('#include <stddef.h>\n#include "parse/fx_eval.h"\n'
                   'size_t stats_test_abi(unsigned i){const size_t a[]={sizeof(fx_number),'
                   'sizeof(fx_eval_result),offsetof(fx_eval_result,value),'
                   'offsetof(fx_eval_result,consumed),offsetof(fx_eval_result,unsupported_token),'
                   'sizeof(fx_eval_storage),offsetof(fx_eval_storage,ram),'
                   'offsetof(fx_eval_storage,ram_size),offsetof(fx_eval_storage,rom),'
                   'offsetof(fx_eval_storage,rom_size),sizeof(fx_eval_effects),'
                   'offsetof(fx_eval_effects,equation_used),'
                   'offsetof(fx_eval_effects,restricted_state),sizeof(fx_calculus_control),'
                   'offsetof(fx_calculus_control,cancelled),'
                   'offsetof(fx_calculus_control,userdata)};return a[i];}\n')
    library = BUILD / ('parser-' + args.optimization + '.so')
    subprocess.run(['gcc', '-std=c99', '-' + args.optimization, '-Wall', '-Wextra',
                    '-Werror', '-shared', '-fPIC', '-Wl,--no-undefined',
                    '-I', str(ROOT / 'csrc'), *[str(ROOT / p) for p in sources],
                    str(abi), '-o', str(library)], check=True)
    lib = C.CDLL(str(library))
    lib.stats_test_abi.argtypes = [C.c_uint]
    lib.stats_test_abi.restype = C.c_size_t
    expected_abi = [C.sizeof(Number), C.sizeof(Result), Result.value.offset,
                    Result.consumed.offset, Result.unsupported_token.offset,
                    C.sizeof(Storage), Storage.ram.offset, Storage.ram_size.offset,
                    Storage.rom.offset, Storage.rom_size.offset, C.sizeof(Effects),
                    Effects.equation_used.offset, Effects.restricted_state.offset,
                    C.sizeof(Control), Control.cancelled.offset, Control.userdata.offset]
    actual_abi = [lib.stats_test_abi(i) for i in range(len(expected_abi))]
    if actual_abi != expected_abi:
        raise AssertionError(('ABI mismatch', actual_abi, expected_abi))
    lib.fx_evaluate_prepared_with_storage.argtypes = [C.POINTER(C.c_uint8), C.c_size_t,
        C.c_void_p, C.c_void_p, C.c_void_p, C.c_void_p, C.POINTER(Number), C.c_void_p,
        C.POINTER(Storage), C.POINTER(Effects), C.POINTER(Result)]
    lib.fx_evaluate_prepared_with_storage.restype = C.c_int
    oracle_dir = BUILD / ('native-' + args.optimization)
    oracle_dir.mkdir(exist_ok=True)
    oracle = oracle_dir / 'nxu8-harness.so'
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-shared', '-fPIC', str(ROOT / OBSERVER),
                    str(ROOT / 'tools/nxu8/vendor/SimU8/core.c'), '-o', str(oracle)], check=True)
    rom = (ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    native = Machine(rom, oracle_dir)
    native.lib.review_run.argtypes = []
    native.lib.review_run.restype = C.c_int
    frame = (C.c_uint8 * 65536).in_dll(native.lib, 'review_frame_writes')
    rom_buffer = (C.c_uint8 * len(rom)).from_buffer_copy(rom)
    ram = (C.c_uint8 * 65536)()
    storage = Storage(ram, 65536, rom_buffer, len(rom))
    secondary = Number.from_buffer_copy(b'\xee' * 10)
    rows, failures, counts = [], [], Counter()
    checks = len(actual_abi)
    for case in cases:
        if args.only_family and case['family'] != args.only_family:
            continue
        native.reset()
        for address, value in [(0x80f9, case['mode']), (0x80fa, case['selected']),
            (0x80de, case['count']), (0x8109, case['frequency']), (0x80fc, case['screen']),
            (0x80f5, 0xf0), (0x8105, 4), (0x8106, case['math']), (0x8121, 1), (0x812a, 0xa5)]:
            native.ram[address] = value
        raw = bytes.fromhex(case['tokens']) + b'\0'
        for address, value in [(0x829e, b'\x77' * 80), (0x82ee, bytes.fromhex(case['table'])),
                               (0x8900, b'\xee' * 20), (0x8600, raw), (0x8190, b'\0\x86')]:
            C.memmove(C.byref(native.ram, address), value, len(value))
        initial = bytes(native.ram)
        C.memmove(ram, initial, 65536)
        native.er(0, 0x8190)
        native.er(2, 0x8900)
        native.lib.harness_set_sp(0x8dee)
        native.lib.harness_set_lr(0x2fffe)
        native.lib.harness_set_pc(0x171f4)
        stop = native.lib.review_run()
        final = bytes(native.ram)
        native_status, native_cursor = native.reg(0), native.word(0x8190) - 0x8600
        polls = C.c_uint.in_dll(native.lib, 'review_polls').value
        source = (C.c_uint8 * len(raw)).from_buffer_copy(raw)
        result, effects = Result(), Effects()
        host_polls = []

        @Cancel
        def cancelled(_):
            host_polls.append(bytes(ram[0x8276:0x8280]).hex())
            return 0

        control = Control(cancelled, None)
        status = lib.fx_evaluate_prepared_with_storage(source, len(raw), None, None, None,
            C.byref(control), C.byref(secondary), None, C.byref(storage), C.byref(effects), C.byref(result))
        C.memmove(C.byref(ram, 0x8900), bytes(result.value), 20)
        cursor = 0x8600 + result.consumed
        ram[0x8190], ram[0x8191] = cursor & 255, cursor >> 8 & 255
        actual = bytes(ram)
        differences = [[f'{a:04x}', final[a], actual[a]] for a in range(0x80dc, 65536)
                       if final[a] != actual[a] and not frame[a]]
        semantic = status == native_status and result.consumed == native_cursor and bytes(result.value) == final[0x8900:0x8914]
        diagnostic = case.get('diagnostic')
        errors = []
        checks += 1
        if stop != 100:
            errors.append('original did not return normally')
        checks += 1
        if len(host_polls) != polls:
            errors.append('native timer/host callback count mismatch')
        if diagnostic in ('invalid-base-selector', 'table-input-output-frame-alias'):
            checks += 1
            if semantic and not differences:
                checks += 3
                counts['strict_controls'] += 1
                counts['resolved_host_inputs'] += 1
            elif status != -1:
                errors.append('declared host boundary did not remain explicit UNIMPLEMENTED')
            else:
                counts['host_boundaries'] += 1
        else:
            checks += 3
            if not semantic:
                errors.append('status/cursor/result20 mismatch')
            if diagnostic:
                allowed_ram = range(0x8654, 0x8686) if diagnostic == 'exact-sqrt-workspace' else range(0x830c, 0x8316)
                checks += 1
                if any(int(a, 16) not in allowed_ram for a, _, _ in differences):
                    errors.append('additional persistent RAM difference outside declared diagnostic domain')
                if semantic and not differences:
                    counts['strict_controls'] += 1
                    counts['resolved_RAM_inputs'] += 1
                else:
                    counts['ram_diagnostics'] += 1
            else:
                checks += 1
                if differences:
                    errors.append('persistent RAM mismatch')
                counts['strict_controls'] += 1
        if case['family'] == 'finite-series' and case['count'] == 0:
            checks += 2
            if native_status != 3 or polls:
                errors.append('empty-table dynamic preflight failed to remain fatal before polling')
            counts['fatal_preflight_controls'] += 1
        counts[diagnostic or 'strict'] += 1
        rows.append(dict(id=case['id'],family=case['family'],diagnostic=diagnostic,
            tokens=case['tokens'],initial_sha256=hashlib.sha256(initial).hexdigest(),
            native=dict(stop=stop,status=native_status,cursor=native_cursor,record20=final[0x8900:0x8914].hex(),polls=polls,final_ram_sha256=hashlib.sha256(final).hexdigest()),
            actual=dict(status=status,cursor=result.consumed,record20=bytes(result.value).hex(),unsupported_token=result.unsupported_token,final_ram_sha256=hashlib.sha256(actual).hexdigest(),polls=len(host_polls),callback_X=host_polls),
            differences=differences,semantic_match=semantic,strict_RAM_match=not differences,
            observed_domain='strict-match' if semantic and not differences else
                'host-boundary' if status==-1 and diagnostic in ('invalid-base-selector','table-input-output-frame-alias') else 'RAM-diagnostic',
            minimum_sp=C.c_uint.in_dll(native.lib,'review_floor').value,witnessed_frame_bytes=sum(frame),errors=errors))
        if errors:
            failures.append(dict(id=case['id'],errors=errors))
        if len(rows) % 100 == 0:
            print('completed', len(rows), flush=True)
    after = {p: digest(ROOT / p) for p in dependencies}
    changes = [p for p in before if before[p] != after[p]]
    report = dict(cases=len(rows),checks=checks,original_calls=len(rows),optimization=args.optimization,
        diagnostic_subset=args.only_family,counts=dict(counts),failures=failures,source_changes=changes,
        native_nonreturns=sum(r['native']['stop']!=100 for r in rows),
        unfiltered_semantic_mismatches=sum(not r['semantic_match'] for r in rows),
        unfiltered_RAM_mismatches=sum(bool(r['differences']) for r in rows),
        input_hashes_start=before,input_hashes_end=after,abi_actual=actual_abi,
        abi_probe_sha256=digest(abi),compiled_artifact_sha256=digest(library),original_compiled_sha256=digest(oracle),rows=rows)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    output = BUILD / ('run-' + args.optimization + '-' + stamp + '.json')
    output.write_text(json.dumps(report,indent=2)+'\n')
    (BUILD / ('observations-' + args.optimization + '.json')).write_bytes(output.read_bytes())
    print(json.dumps({k:report[k] for k in ('cases','checks','counts','failures','source_changes')}))
    if failures or changes:
        raise AssertionError('Unclassified stats parser/native/source mismatch; complete observations retained')
    if not args.no_report:
        canonical = {k:v for k,v in report.items() if k not in ('rows','input_hashes_start','input_hashes_end')}
        canonical.update(observations=str(output.relative_to(ROOT)),
            scope='Strict bounded raw8A whole-parser controls plus explicitly retained host/RAM diagnostics; known diagnostics are not full-RAM parity claims.',
            exclusions='Only numeric-register arena8000..80DB and individually witnessed native CPU-frame writes; every public bank/flag/MMIO byte otherwise compared.',
            limitations=['831 inherited BASE/table alias host boundaries and119 known exact-sqrt/SCREENFF RAM diagnostic inputs remain visible.',
                         'No continuous calculus workspace, arbitrary table/input/output/CPU-frame alias or UI workflow completeness claim.'])
        write_report('analysis/c-verification/eval_stats.json',canonical,dependencies,'tools/test_eval_stats_c.py')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
