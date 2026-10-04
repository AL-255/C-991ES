#!/usr/bin/env python3
"""Live original171F4 parity for Ran#/RanInt grammar and eager session seeds.

All corpus rows are input-only. Existing host UNIMPLEMENTED domain gaps remain
in the report as explicit limits and are never counted as native parity.
"""
import argparse
from collections import Counter
import ctypes as C
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import subprocess

from c_build_inputs import implementation_inputs
from c_verification import ROOT, write_report
from nxu8.machine import Machine
from test_eval_variables_c import Number, Options, Result, Variables, SOURCES

INPUTS = 'analysis/native-fixtures/parser-random-expression/ordinary-inputs.json'
INPUT_SHA256 = '40a742b14dda0be0c586c52e3df9776e67df62c238857f0d924759db5c66a3a1'
EXPECTED_GROUPS = {'independent_c2': 756, 'independent_comma': 204,
    'independent_comma_errors': 72, 'independent_fresh': 1000,
    'independent_ran': 568, 'independent_stack': 100,
    'independent_terminal': 96, 'main_ran': 3198,
    'parent_fresh': 3000, 'parent_reused': 66}

class Environment(C.Structure):
    _fields_ = [(name, C.c_uint8) for name in ('screen', 'prior_operation',
        'complex_format', 'restricted_state', 'display_mode', 'digits',
        'selected_base')]
class State(C.Structure):
    _fields_ = [('variables', C.POINTER(Variables)), ('bank', C.c_void_p)]
class Storage(C.Structure):
    _fields_ = [('ram', C.POINTER(C.c_uint8)), ('ram_size', C.c_size_t),
               ('rom', C.POINTER(C.c_uint8)), ('rom_size', C.c_size_t)]
class Effects(C.Structure):
    _fields_ = [('equation_used', C.c_uint8), ('restricted_state', C.c_uint8)]

ABI_PROBE = r'''
#include <stddef.h>
#include "parse/fx_eval.h"
size_t random_test_abi(unsigned index) {
    const size_t sizes[] = {sizeof(fx_eval_options), sizeof(fx_eval_environment),
        sizeof(fx_eval_variables), sizeof(fx_eval_result), sizeof(fx_eval_state),
        offsetof(fx_eval_result, consumed), offsetof(fx_eval_result, unsupported_token),
        sizeof(fx_eval_storage), sizeof(fx_eval_effects)};
    return sizes[index];
}
'''

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def decimal(text):
    value = Decimal(str(text))
    if not value: return bytes(10)
    tup = value.as_tuple()
    digits = ''.join(map(str, tup.digits))
    exponent = len(digits)-1+tup.exponent
    assert len(digits) <= 15 and abs(exponent) <= 99
    digits = digits.ljust(15, '0')
    return bytes([int(digits[0]), *[int(digits[i:i+2],16)
        for i in range(1,15,2)],
        int(f'{exponent if exponent >= 0 else exponent+100:02}',16),
        (6 if tup.sign else 1)-(exponent < 0)])

def put_word(ram, address, value):
    ram[address:address+2] = bytes((value&255, value>>8))

def coordinates(case):
    return (0x8600,0x9c00,0x8900) if case['profile']=='c2' else (0x9000,0x8190,0x8500)

def initial_ram(case):
    ram = bytearray(65536)
    profile = case['profile']
    if profile in ('main','parent_fresh'):
        ram[0x8121] = 1
        put_word(ram,0x812c,0x8200)
    if profile == 'parent_fresh' and case.get('poison'):
        poison = case['poison']
        for address in range(0x8000,0x9000):
            ram[address]=(address*73+poison*31)&255
        ram[0x80dc:0x80ee]=bytes(18)
        ram[0x829e:0x8408]=bytes(362)
    for address,value in [(0x80f9,case['context']), (0x80fc,case['screen']),
        (0x8106,case['math']), (0x8105,4), (0x80fa,case['base']),
        (0x80f5,case['prior']), (0x8124,case.get('restricted',0))]:
        ram[address]=value
    if profile == 'parent_fresh':
        for address in (0x8102,0x8103,0x810c,0x8124,0x8125):ram[address]=0
        ram[0x8121]=1
        ram[0x828a:0x8294]=bytes(10)
    if profile == 'ran_child':
        ram[0x8121]=1
        ram[0x83fc]=8
    ram[0x821c:0x8226]=bytes.fromhex(case['seed'])
    for slot in range(10):
        ram[0x8226+slot*10:0x8230+slot*10] = decimal(1 if profile=='ran_child' else slot+1)
        imaginary = slot+11 if profile=='main' or (
            profile=='parent_fresh' and case['context']==0xc4) else 0
        ram[0x8408+slot*10:0x8412+slot*10] = decimal(imaginary)
    for name,address in [('records',0x8226),('imaginary',0x8408)]:
        for slot,record in case.get(name,{}).items():
            start=address+int(slot)*10
            ram[start:start+10]=bytes.fromhex(record)
    _,_,output=coordinates(case)
    first=b'\xad'*10 if profile in ('c2','ran_child') else decimal(6)
    ram[output:output+20] = first+bytes.fromhex(case['secondary'])
    return ram

def logical_banks(ram):
    return (bytes(ram[0x8226:0x828a])+bytes(ram[0x8408:0x846c])).hex()

def complete_banks(ram):
    return (bytes(ram[0x8226:0x829e])+bytes(ram[0x8408:0x8476])).hex()

def native(machine, case, initial):
    machine.reset()
    machine.ram[:]=initial
    source,pointer,output=coordinates(case)
    raw=bytes.fromhex(case['tokens'])+b'\0'
    machine.ram[source:source+len(raw)]=raw
    machine.word(pointer,source)
    machine.er(0,pointer)
    machine.er(2,output)
    execution=100
    try:
        machine.call(0x171f4,limit=5000000)
    except RuntimeError:
        execution=103
    after=bytes(machine.ram)
    result={'status':machine.reg(0),'result20':after[output:output+20].hex(),
        'consumed':(machine.word(pointer)-source)&65535,
        'seed':after[0x821c:0x8226].hex(),'banks':logical_banks(after),
        'complete_banks':complete_banks(after),
        'equation_used':after[0x8125]&1,'equation_mask':after[0x8125],
        'restricted_state':after[0x8124],
        'immutable_input':after[source:source+len(raw)]==raw}
    evidence={'execution':execution,'pc':f'{machine.lib.harness_get_pc():05X}',
        'draws':int(machine.counts[0x13db8//2]),
        'ranint_calls':int(machine.counts[0x13ebe//2])}
    return result,evidence,after

def candidate(lib, rom, case, initial, use_storage):
    raw=bytes.fromhex(case['tokens'])+b'\0'
    source=(C.c_uint8*len(raw)).from_buffer_copy(raw)
    secondary=Number.from_buffer_copy(initial[coordinates(case)[2]+10:coordinates(case)[2]+20])
    variables=Variables()
    for slot in range(10):
        for part,address in [(0,0x8226),(1,0x8408)]:
            start=address+slot*10
            variables.values[slot][part]=Number.from_buffer_copy(initial[start:start+10])
    state=State(C.pointer(variables),None)
    effects=Effects()
    result=Result()
    if use_storage:
        ram=(C.c_uint8*65536).from_buffer_copy(initial)
        storage=Storage(ram,65536,rom,len(rom))
        status=lib.fx_evaluate_prepared_with_storage(source,len(raw),None,None,
            C.byref(state),None,C.byref(secondary),None,C.byref(storage),
            C.byref(effects),C.byref(result))
        after=bytearray(ram)
    else:
        options=Options(case['context'],case['math'],4)
        environment=Environment(case['screen'],case['prior'],initial[0x810c],
            initial[0x8124],initial[0x8102],initial[0x8103],case['base'])
        seed=Number.from_buffer_copy(initial[0x821c:0x8226])
        prior_answer=Number.from_buffer_copy(initial[0x828a:0x8294])
        status=lib.fx_evaluate_prepared_random(source,len(raw),C.byref(options),
            C.byref(environment),C.byref(state),None,C.byref(secondary),
            C.byref(prior_answer),C.byref(seed),C.byref(effects),C.byref(result))
        after=bytearray(initial)
        after[0x821c:0x8226]=bytes(seed)
        for slot in range(10):
            for part,address in [(0,0x8226),(1,0x8408)]:
                start=address+slot*10
                after[start:start+10]=bytes(variables.values[slot][part])
        after[0x8124]=effects.restricted_state
        after[0x8125]=effects.equation_used
    # The caller owns these disjoint output records. Copying them back is
    # required before the next call in a reused physical-RAM sequence.
    _,_,output=coordinates(case)
    after[output:output+20]=bytes(result.value)
    actual={'status':status,'result20':bytes(result.value).hex(),
        'consumed':result.consumed,'seed':after[0x821c:0x8226].hex(),
        'banks':logical_banks(after),'equation_used':effects.equation_used,
        'restricted_state':effects.restricted_state,
        'immutable_input':bytes(source)==raw}
    if use_storage:
        actual['complete_banks']=complete_banks(after)
        actual['equation_mask']=after[0x8125]
    return actual,after,result.unsupported_token

def known_limit(case, actual, unsupported_token):
    if actual['status'] != -1: return None
    if case['context'] not in (0xc1,0xc4,2):
        return 'Existing calculation-context domain: native prepared call returns, while the host API reports UNIMPLEMENTED before evaluation.'
    if case['context']==2 and case['base'] not in (1,7,9,15):
        return 'Existing selected-base domain: only complete selectors1/7/9/15 are admitted by this frontend API. Other original prepared masks are retained as explicit limits.'
    if unsupported_token in (0x8a,0xff):
        return f'Existing unsupported raw token{unsupported_token:02X}: its original returned status and already-completed seed/variable effects are recorded; this call is not native parity.'
    return None

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-report',action='store_true')
    parser.add_argument('--ordinary-only',action='store_true',help='Diagnostic only; requires --no-report')
    args=parser.parse_args()
    if args.ordinary_only and not args.no_report:parser.error('--ordinary-only requires --no-report')
    assert digest(ROOT/INPUTS)==INPUT_SHA256
    fixture=json.loads((ROOT/INPUTS).read_text())
    assert fixture['counts']==EXPECTED_GROUPS
    cases=fixture['rows']
    assert len(cases)==9060
    sources=list(SOURCES)
    assert 'numeric/fx_random.c' in sources
    dependencies=implementation_inputs(ROOT,['csrc/'+name for name in sources])
    dependencies += [INPUTS,'tools/test_eval_random_c.py','tools/test_eval_variables_c.py',
        'tools/test_eval_complex_c.py','tools/c_build_inputs.py','tools/c_verification.py',
        'tools/trace_natural_result.py','tools/verify_firmware.py','tools/nxu8/decoder.py',
        'tools/nxu8/machine.py','tools/nxu8/harness.c','tools/nxu8/vendor/SimU8/core.c',
        'firmware/fx-991es-plus-c-ver4.bin','analysis/disassembly/complete.asm',
        'csrc/parse/random/EXECUTION.md','csrc/parse/random/manifest.json']
    dependencies += [str(path.relative_to(ROOT))for path in (ROOT/'tools/nxu8/vendor/SimU8').glob('*.h')]
    if not args.ordinary_only:
        from eval_random_calculus import run_calculus, SOURCE_INPUTS
        dependencies += SOURCE_INPUTS
    # c_verification only snapshots JSON/C/H/Python/ROM. Static assembly and
    # Markdown are pinned independently below and checked again after the run.
    report_dependencies=[name for name in dependencies
                         if Path(name).suffix not in ('.md','.asm')]
    pinned={name:digest(ROOT/name)for name in sorted(set(dependencies))}
    build=ROOT/'analysis/build/eval-random'
    build.mkdir(parents=True,exist_ok=True)
    shared=build/'eval-random.so'
    subprocess.run(['gcc','-std=c99','-O3','-Wall','-Wextra','-Werror','-pedantic',
        '-shared','-fPIC','-I',str(ROOT/'csrc'),*[str(ROOT/'csrc'/name)for name in sources],
        '-x','c','-','-o',str(shared)],input=ABI_PROBE,text=True,check=True)
    lib=C.CDLL(str(shared))
    for name in ('fx_evaluate_prepared_random','fx_evaluate_prepared_with_storage'):
        getattr(lib,name).argtypes=[C.c_void_p,C.c_size_t]+[C.c_void_p]*9
        getattr(lib,name).restype=C.c_int
    lib.random_test_abi.argtypes=[C.c_uint]
    lib.random_test_abi.restype=C.c_size_t
    sizes=[C.sizeof(Options),C.sizeof(Environment),C.sizeof(Variables),C.sizeof(Result),
        C.sizeof(State),Result.consumed.offset,Result.unsupported_token.offset,
        C.sizeof(Storage),C.sizeof(Effects)]
    assert [lib.random_test_abi(i)for i in range(len(sizes))]==sizes
    rom_data=(ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    rom=(C.c_uint8*len(rom_data)).from_buffer_copy(rom_data)
    machine=Machine(rom_data,build/'oracle')
    failures,limits,native_nonreturns=[],[],[]
    native_statuses=Counter(); domains=Counter(); draw_count=0
    checks=len(sizes); matching_calls=0; parity_attempts=0
    reused_native={};reused_c={}
    for index,case in enumerate(cases):
        sequence=case.get('sequence')
        inherited=sequence and case['sequence_step']>0
        initial=reused_native[sequence] if inherited else initial_ram(case)
        expected,evidence,native_after=native(machine,case,initial)
        if sequence:reused_native[sequence]=native_after
        domains[case['group']]+=1
        native_statuses[expected['status']]+=1
        draw_count+=evidence['draws']
        if evidence['execution']!=100 or evidence['pc']!='2FFFE':
            native_nonreturns.append({'case':case,'native':expected,'evidence':evidence})
        if case.get('native_guard'):
            guard={'status':expected['status'],'draws':evidence['draws'],
                   'ranint_calls':evidence['ranint_calls']}
            if guard!=case['native_guard']:
                failures.append({'case':case,'native':expected,'evidence':evidence,
                    'semantic_diagnosis':'Mandatory native fixture contract failed; do not claim C/native parity from a mistaken prepared state.'})
        for mode in (False,True):
            entry='storage' if mode else 'explicit_seed'
            key=(sequence,mode)
            c_initial=reused_c[key]if inherited else initial_ram(case)
            actual,c_after,unsupported_token=candidate(lib,rom,case,c_initial,mode)
            if sequence:reused_c[key]=c_after
            difference={name:{'actual':value,'native':expected[name]}
                        for name,value in actual.items()if value!=expected[name]}
            detail={'case':case,'entry':entry,'actual':actual,'native':expected,
                    'evidence':evidence,'unsupported_token':unsupported_token,
                    'differences':difference}
            limit=known_limit(case,actual,unsupported_token)
            if limit:
                detail['semantic_diagnosis']=limit
                limits.append(detail)
                # This checks the host's admitted-domain boundary, not its
                # equality with native outputs. Every mismatch is retained.
                checks+=1
            else:
                parity_attempts+=1
                checks+=len(actual)
                if difference or evidence['execution']!=100:
                    detail['semantic_diagnosis']='Unfiltered admitted-domain discrepancy; exact input, native return and C outputs retained.'
                    failures.append(detail)
                else:matching_calls+=1
        if (index+1)%2000==0:
            print(json.dumps({'ordinary_native_done':index+1,'failures':len(failures),
                              'explicit_limits':len(limits)}),flush=True)
    calculus=None
    if not args.ordinary_only:
        calculus=run_calculus(lib,build,rom_data)
        assert calculus['cases']==400
        failures.extend(calculus['failures'])
        native_nonreturns.extend(calculus['native_nonreturns'])
        checks+=calculus['checks']
        matching_calls+=calculus['matching_calls']
        domains.update(calculus['domains'])
        native_statuses.update({int(key):value for key,value in calculus['native_statuses'].items()})
        draw_count+=calculus['native_draws']
    source_changes={name:[value,digest(ROOT/name)]for name,value in pinned.items()
                    if digest(ROOT/name)!=value}
    data={'native_cases':len(cases)+(calculus['cases']if calculus else 0),
        'ordinary_api_calls':len(cases)*2,'calculus_api_calls':calculus['cases']if calculus else 0,
        'checks':checks,'matching_native_calls':matching_calls,
        'native_parity_attempts':parity_attempts+(calculus['cases']if calculus else 0),
        'domains':dict(domains),'native_statuses':dict(sorted(native_statuses.items())),
        'native_random_draws':draw_count,'explicit_limit_calls':len(limits),
        'limits':limits,'failures':failures,'native_nonreturns':native_nonreturns,
        'source_changes':source_changes,'source_pins_before_build':pinned,
        'compiled_library_sha256':digest(shared),
        'comparison':'Live original171F4 status, both10-byte result records, consumed cursor, full eager seed, all ten real/imaginary banks, raw storage mask/extended bank fields, named effects and immutable inputs; reused/poisoned state and live original finite-series cancellation polls.',
        'scope':'Prepared ordinary COMP/CMPLX and supported BASE-N random expression grammar. All corpus rows execute original ROM live. Declared unsupported contexts, incomplete base masks and raw8A/FF are retained as limits and excluded from matching-native counts, never represented as success parity. CPU-frame/output aliases, UI lifecycle and arbitrary malformed seeds remain outside this entry.'}
    (build/'diagnostics.json').write_text(json.dumps(data,indent=2)+'\n')
    print(json.dumps({key:data[key]for key in ('native_cases','checks','matching_native_calls',
        'explicit_limit_calls','source_changes')},sort_keys=True))
    if failures or native_nonreturns or source_changes:
        for failure in failures[:8]:print(json.dumps(failure))
        raise AssertionError(f'{len(failures)} mismatches, {len(native_nonreturns)} native nonreturns, {len(source_changes)} changed inputs')
    if not args.no_report:
        write_report('analysis/c-verification/eval_random.json',data,
                     sorted(set(report_dependencies)),
                     str(Path(__file__).resolve().relative_to(ROOT)))
    print('PASS (explicit native-returning domain limits retained)')

if __name__=='__main__':
    main()
