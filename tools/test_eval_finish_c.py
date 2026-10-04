#!/usr/bin/env python3
"""Prepared physical1415A cleanup against unmodified original CPU instructions.

All2,600 original observations are retained, including82 explicit host limits.
The live comparison masks only the numeric leaf workspace and measured CPU
stack. Physical slots8640..87D0 are compared, not discarded as parser scratch.
"""
import argparse
import collections
import ctypes as C
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess

from c_build_inputs import implementation_inputs
from c_verification import ROOT,write_report
import c_verification

HERE=ROOT/'analysis/native-fixtures/eval-finish'


class Number(C.Structure):
    _fields_=[('bytes',C.c_uint8*10)]


class Storage(C.Structure):
    _fields_=[('ram',C.POINTER(C.c_uint8)),('ram_size',C.c_size_t),
              ('rom',C.POINTER(C.c_uint8)),('rom_size',C.c_size_t)]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_helpers():
    spec=importlib.util.spec_from_file_location('eval_finish_collector',HERE/'collect.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.load_helpers()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-report',action='store_true')
    args=parser.parse_args()
    build=ROOT/'analysis/build/eval-finish';build.mkdir(parents=True,exist_ok=True)
    fixture_inputs=[HERE/name for name in ('__init__.py','cases.py','oracle.py',
        'oracle.c','collect.py','unsupported.json','observations.jsonl.gz','summary.json')]
    # The common reporter scans only JSON under analysis. Capture the actual
    # native source/archive inputs before compiling or executing, as the
    # other prepared evaluator suites do for their additional fixture inputs.
    for path in fixture_inputs:
        c_verification._BASELINE[str(path.relative_to(ROOT))]=digest(path)
    sources=['csrc/parse/fx_eval_finish.c','csrc/numeric/fx_numeric.c']
    compiled=implementation_inputs(ROOT,sources)
    initial_hashes={name:digest(ROOT/name) for name in compiled}
    shared=build/'finish.so'
    subprocess.run(['gcc','-std=c99','-O2','-Wall','-Wextra','-Werror','-pedantic',
        '-shared','-fPIC','-Wl,--no-undefined',*[str(ROOT/name) for name in sources],
        '-o',str(shared)],check=True)
    lib=C.CDLL(str(shared))
    lib.fx_eval_finish_cleanup.argtypes=[C.POINTER(Storage),C.POINTER(Number),C.POINTER(C.c_uint8)]
    lib.fx_eval_finish_cleanup_address.argtypes=[C.POINTER(Storage),C.c_uint16,C.POINTER(C.c_uint8)]
    oracle_module,case_module=load_helpers()
    native=oracle_module.NativeCleanupOracle(build/'live-oracle.so')
    rom=(C.c_uint8*len(native.rom)).from_buffer_copy(native.rom)
    declared={row['case_id']:row for row in json.loads((HERE/'unsupported.json').read_text())['cases']}
    failures=[];checks=0;cases=0;completes=0;bounded=0;native_calls=0
    counts=collections.Counter();minimum_sp=0x8dee;boundaries=[];caller_controls=[]

    def check(group,key,wanted,actual,case_id=None):
        nonlocal checks
        checks+=1
        if actual!=wanted:
            failure=dict(group=group,key=key,case_id=case_id,expected=wanted,actual=actual)
            failures.append(failure)
            if len(failures)<=8:print(json.dumps(failure),flush=True)

    archive=gzip.open(HERE/'observations.jsonl.gz','rt')
    for case_id,(seed,reference,pointer,physical,group) in enumerate(case_module.cases()):
        expected=native.run(seed,0,pair=pointer,limit=1000000)
        archived=json.loads(next(archive))
        check(group,'archive_input_hash',hashlib.sha256(seed).hexdigest(),
            hashlib.sha256(bytes.fromhex(archived['initial_ram'])).hexdigest(),case_id)
        for key in ('run_status','native_status','pc','final_ram_sha256','registers'):
            check(group,'archive_replay_'+key,archived['native'][key],expected[key],case_id)
        native_calls+=1;cases+=1
        floor=int(expected['minimum_sp'],16);minimum_sp=min(minimum_sp,floor)
        ram=(C.c_uint8*65536).from_buffer_copy(seed)
        storage=Storage(ram,65536,rom,len(native.rom))
        current=Number.from_buffer_copy(reference);status=C.c_uint8(0xa5)
        if physical:
            host=lib.fx_eval_finish_cleanup_address(C.byref(storage),pointer,C.byref(status))
        else:
            host=lib.fx_eval_finish_cleanup(C.byref(storage),C.byref(current),C.byref(status))
            # Named host current is projected solely at the observed native
            # record address. The numeric leaf writes that native record.
            C.memmove(C.byref(ram,pointer),bytes(current),10)
        actual=bytes(ram)
        check(group,'no_timer_polls',0,expected['poll_count'],case_id)
        check(group,'allocation_mask_unchanged',seed[0x8125],ram[0x8125],case_id)
        if case_id in declared:
            bound=declared[case_id];bounded+=1
            check(group,'bounded_host_status',bound['host_status'],host,case_id)
            check(group,'bounded_fixture_hash',bound['initial_ram_sha256'],hashlib.sha256(seed).hexdigest(),case_id)
            check(group,'original_run_status',bound['original_run_status'],expected['run_status'],case_id)
            check(group,'original_status',bound['original_native_status'],expected['native_status'],case_id)
            check(group,'original_pc',bound['original_pc'],expected['pc'],case_id)
            check(group,'original_full_ram',bound['original_full_ram_sha256'],expected['final_ram_sha256'],case_id)
            boundaries.append(dict(case_id=case_id,group=group,host_status=host,
                reason=bound['reason'],native=expected,
                candidate_current=actual[pointer:pointer+10].hex(),
                candidate_ram_sha256=hashlib.sha256(actual).hexdigest()))
        else:
            completes+=1
            check(group,'host_status',0,host,case_id)
            check(group,'native_return_boundary',100,expected['run_status'],case_id)
            check(group,'leaf_status',expected['native_status'],status.value,case_id)
            differences=[(f'{address:04x}',a,b) for address,(a,b) in enumerate(zip(actual,native.after))
                if a!=b and not 0x8000<=address<0x80dc and not floor<=address<0x8dee]
            check(group,'persistent_ram_including_all16_slots',[],differences,case_id)
        counts[(group,host,expected['run_status'],expected['native_status'])]+=1
    check('corpus','all_unfiltered_cases',2600,cases)
    check('corpus','archive_fully_consumed','',archive.read())
    archive.close()
    check('corpus','bounded_cases',82,bounded)
    check('corpus','parity_completes',2518,completes)

    # Original17274 preserves the enclosing terminal status even when the
    # cleanup changes the record or returns a different leaf error.
    for header in (0x64,0xf0,0xf3):
        for incoming in (0,3,36,255):
            seed,reference=case_module.fixture(header,2,(1,2),0x8a00,error_index=1,error_code=13)
            native.prepare(seed,0,pair=0x8a00)
            native.reg(2,incoming);native.lib.harness_set_pc(0x17274)
            native.lib.unary_observer_reset(0x8a00,0)
            result=native.lib.unary_observer_run(1000000,0x1727c)
            native_calls+=1
            check('terminal_caller','return_boundary',100,result)
            check('terminal_caller','incoming_status_retained',incoming,native.reg(2))
            caller_controls.append(dict(header=header,incoming_status=incoming,
                leaf_status=native.reg(0),retained_status=native.reg(2),
                record=native.data(0x8a00,20).hex(),pc=f'{native.lib.harness_get_pc():06x}'))

    # Guard checks exercise rejected API objects and physical ranges. They
    # preserve the supplied RAM/current/status and use no native fallback.
    seed,reference=case_module.fixture(0x64,2,(1,2),0x8a00)
    ram=(C.c_uint8*65536).from_buffer_copy(seed)
    storage=Storage(ram,65536,rom,len(native.rom));current=Number.from_buffer_copy(reference)
    status=C.c_uint8(0xa5);guards=0

    def guard(name,call,wanted):
        nonlocal guards
        before=bytes(ram),bytes(current),status.value
        check('api_guard',name,wanted,call())
        check('api_guard',name+'_unchanged',before,(bytes(ram),bytes(current),status.value))
        guards+=1

    guard('null_storage',lambda:lib.fx_eval_finish_cleanup(None,C.byref(current),C.byref(status)),-1)
    guard('null_current',lambda:lib.fx_eval_finish_cleanup(C.byref(storage),None,C.byref(status)),-1)
    guard('null_status',lambda:lib.fx_eval_finish_cleanup(C.byref(storage),C.byref(current),None),-1)
    short=Storage(ram,65535,rom,len(native.rom))
    guard('short_ram',lambda:lib.fx_eval_finish_cleanup(C.byref(short),C.byref(current),C.byref(status)),-1)
    empty=Storage(None,65536,rom,len(native.rom))
    guard('null_ram',lambda:lib.fx_eval_finish_cleanup(C.byref(empty),C.byref(current),C.byref(status)),-1)
    guard('named_current_in_ram',lambda:lib.fx_eval_finish_cleanup(C.byref(storage),C.cast(C.byref(ram,0x8a00),C.POINTER(Number)),C.byref(status)),-1)
    guard('named_status_in_ram',lambda:lib.fx_eval_finish_cleanup(C.byref(storage),C.byref(current),C.cast(C.byref(ram,0x8100),C.POINTER(C.c_uint8))),-1)
    for offset in (0,9):
        guard('status_current_overlap_'+str(offset),lambda offset=offset:lib.fx_eval_finish_cleanup(C.byref(storage),C.byref(current),C.cast(C.byref(current,offset),C.POINTER(C.c_uint8))),-1)
    guard('physical_status_in_ram',lambda:lib.fx_eval_finish_cleanup_address(C.byref(storage),0x8a00,C.cast(C.byref(ram,0x8100),C.POINTER(C.c_uint8))),-1)
    guard('physical_null_storage',lambda:lib.fx_eval_finish_cleanup_address(None,0x8a00,C.byref(status)),-1)
    guard('physical_null_status',lambda:lib.fx_eval_finish_cleanup_address(C.byref(storage),0x8a00,None),-1)
    for address in (0x7fff,0x8000,0x80d2,0x8cf7,0x8d00,0x8de0,0xfff7,0xffff):
        guard('physical_range_'+hex(address),lambda address=address:lib.fx_eval_finish_cleanup_address(C.byref(storage),address,C.byref(status)),-3)

    changed={name:{'before':value,'after':digest(ROOT/name)} for name,value in initial_hashes.items() if digest(ROOT/name)!=value}
    report=dict(cases=cases+len(caller_controls)+guards,checks=checks,parity_completes=completes,
        bounded_cases=bounded,api_guards=guards,terminal_caller_frames=len(caller_controls),native_calls=native_calls,
        domains=[{'group':g,'host_status':h,'original_run_status':r,'native_status':s,'count':n}
            for (g,h,r,s),n in sorted(counts.items(),key=lambda item:str(item[0]))],
        failures=failures,compiled_inputs_sha256=initial_hashes,source_changes_during_run=changed,
        compiled_library_sha256=digest(shared),minimum_native_sp=f'{minimum_sp:04x}',
        terminal_caller_controls=caller_controls,bounded_observations=boundaries,
        scope='Prepared1415A physical16-slot cleanup; native17274 status preservation; named/current physical aliases; explicit API and unsupported boundaries. No complete parser/controller claim.',
        comparison='Full64KiB RAM including16 physical dimensions and1440 payload bytes, excluding only8000..80DB leaf numeric workspace and measured minimumSP..8DED CPU stack. No8640..87D0 exclusion.',
        unsupported_policy='All82 original0/3/CPU101 observations are retained and replayed. Explicit host limits are checked but not counted as native parity.')
    (build/'diagnostics.json').write_text(json.dumps(report,indent=2)+'\n')
    if failures:raise AssertionError(f'{len(failures)} physical cleanup mismatches')
    if changed:raise AssertionError('Compiled inputs changed during the run')
    if not args.no_report:
        dependencies=compiled+[str(p.relative_to(ROOT)) for p in fixture_inputs]
        dependencies+=['tools/c_build_inputs.py','tools/c_verification.py']
        report=write_report('analysis/c-verification/eval_finish.json',report,dependencies,'tools/test_eval_finish_c.py')
    print(json.dumps({key:report[key] for key in ('cases','checks','parity_completes','bounded_cases','api_guards','terminal_caller_frames','native_calls')},indent=2))


if __name__=='__main__':main()
