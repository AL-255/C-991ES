#!/usr/bin/env python3
"""Complete integral/derivative parser parity, including every sample and poll."""
import argparse
import ctypes as C
import json
import random
import subprocess

from c_verification import ROOT, write_report
from c_build_inputs import implementation_inputs
from test_eval_variables_c import Number, Options, Result, Variables, SOURCES
from test_numeric_calculus_c import Control, Cancel


class LinalgSlot(C.Structure):
    _fields_=[('rows',C.c_uint8),('columns',C.c_uint8),('cells',Number*9)]


class LinalgBank(C.Structure):
    _fields_=[('slots',LinalgSlot*9),('temporary_mask',C.c_uint8)]


class State(C.Structure):
    _fields_=[('variables',C.POINTER(Variables)),('linear_algebra',C.POINTER(LinalgBank))]


OBSERVER = r'''
#include "numeric/fx_integral.h"
#include "numeric/fx_derivative.h"
#include <string.h>
unsigned parser_observed_calls;
fx_number parser_observed_x[8192];
typedef struct { fx_calculus_function function; void *userdata; } observation;
static fx_numeric_status observe(fx_number *out,const fx_number *x,void *userdata) {
    observation *state=userdata;
    if(parser_observed_calls<8192) parser_observed_x[parser_observed_calls]=*x;
    ++parser_observed_calls;
    return state->function(out,x,state->userdata);
}
extern fx_numeric_status __real_fx_number_integral(fx_number*,const fx_number*,const fx_number*,const fx_number*,fx_calculus_function,void*,const fx_calculus_control*);
extern fx_numeric_status __real_fx_number_derivative(fx_number*,const fx_number*,const fx_number*,fx_calculus_function,void*,const fx_calculus_control*);
fx_numeric_status __wrap_fx_number_integral(fx_number*out,const fx_number*a,const fx_number*b,const fx_number*t,fx_calculus_function f,void*u,const fx_calculus_control*c) {
    observation state={f,u};
    return __real_fx_number_integral(out,a,b,t,observe,&state,c);
}
fx_numeric_status __wrap_fx_number_derivative(fx_number*out,const fx_number*a,const fx_number*t,fx_calculus_function f,void*u,const fx_calculus_control*c) {
    observation state={f,u};
    return __real_fx_number_derivative(out,a,t,observe,&state,c);
}
'''


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--random-cases', type=int, default=1000)
    ap.add_argument('--no-report', action='store_true')
    args = ap.parse_args()
    build = ROOT/'analysis/build/eval-continuous'
    build.mkdir(parents=True, exist_ok=True)
    observer = build/'sample-observer.c'; observer.write_text(OBSERVER)
    shared = build/'eval.so'
    subprocess.run(['gcc','-std=c99','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',
                    '-I'+str(ROOT/'csrc'),*[str(ROOT/'csrc'/p) for p in SOURCES],str(observer),
                    '-Wl,--wrap=fx_number_integral','-Wl,--wrap=fx_number_derivative','-o',str(shared)],check=True)
    lib = C.CDLL(str(shared))
    lib.fx_evaluate_controlled.argtypes = [C.POINTER(C.c_uint8),C.c_size_t,C.POINTER(Options),
                                         C.POINTER(Variables),C.POINTER(Control),C.POINTER(Result)]
    lib.fx_evaluate_controlled.restype = C.c_int
    lib.fx_evaluate_with_state.argtypes = [C.POINTER(C.c_uint8),C.c_size_t,C.POINTER(Options),
                                         C.POINTER(State),C.POINTER(Control),C.POINTER(Result)]
    lib.fx_evaluate_with_state.restype = C.c_int
    lib.fx_decimal_parse.argtypes = [C.POINTER(Number),C.c_char_p]
    observed_x = (Number*8192).in_dll(lib,'parser_observed_x')
    observed_count = C.c_uint.in_dll(lib,'parser_observed_calls')
    adapter = 'tools/nxu8/calculus_expression_events.c'
    native_path = build/'oracle.so'
    subprocess.run(['gcc','-std=c99','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',
                    str(ROOT/adapter),str(ROOT/'tools/nxu8/vendor/SimU8/core.c'),'-o',str(native_path)],check=True)
    native = C.CDLL(str(native_path))
    native.harness_init.argtypes = [C.c_void_p,C.c_size_t]
    native.harness_ram.restype = C.POINTER(C.c_uint8*65536)
    native.harness_set_reg.argtypes = [C.c_uint,C.c_uint8]
    native.harness_get_reg.argtypes = [C.c_uint]
    native.harness_get_reg.restype = C.c_uint8
    native.calculus_expression_call.argtypes = [C.c_uint32,C.c_uint64,C.c_uint]
    native_x = ((C.c_uint8*10)*8192).in_dll(native,'calculus_expression_x')
    native_poll_x = ((C.c_uint8*10)*8192).in_dll(native,'calculus_expression_poll_x')
    native_count = C.c_uint.in_dll(native,'calculus_expression_callbacks')
    native_polls = C.c_uint.in_dll(native,'calculus_expression_polls')
    rom = (ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes(); rb=C.create_string_buffer(rom)
    rng = random.Random(0x6a6b171f4)
    counts, failures = {}, []

    def decimal(text):
        n=Number(); assert lib.fx_decimal_parse(C.byref(n),str(text).encode())==0
        return bytes(n)

    def check(tokens,group,math=1,unit=4,abort=0,x=None,a=None,initial_bank=None,fixture=None,rich_slot=None):
        values=Variables()
        values.values[8][0]=Number.from_buffer_copy(x or decimal(37))
        values.values[2][0]=Number.from_buffer_copy(a or decimal(2))
        if initial_bank:
            for slot,name in enumerate(('A','B','C','D','E','F','X','Y'),2):
                values.values[slot][0]=Number.from_buffer_copy(bytes.fromhex(initial_bank[name]))
        before=bytes(values)
        native.harness_init(rb,len(rom)); ram=native.harness_ram().contents
        for address,value in [(0x80f9,0xc1),(0x80fc,1),(0x80f5,0xf0),(0x8105,unit),(0x8106,math),(0x8121,1)]:ram[address]=value
        raw=tokens+b'\0'
        for i,value in enumerate(raw):ram[0x8200+i]=value
        for address in (0x812c,0x8190):ram[address]=0;ram[address+1]=0x82
        for slot in range(10):
            for part,base in ((0,0x8226),(1,0x8408)):
                for i,value in enumerate(bytes(values.values[slot][part])):ram[base+10*slot+i]=value
        rich_bank=LinalgBank()
        if rich_slot:
            identity,rows,columns,cells=rich_slot
            entry=rich_bank.slots[identity];entry.rows=rows;entry.columns=columns
            ram[0x80e0+2*identity]=rows;ram[0x80e1+2*identity]=columns
            for cell,record in enumerate(cells):
                entry.cells[cell]=Number.from_buffer_copy(record)
                for offset,value in enumerate(record):ram[0x829e+90*identity+10*cell+offset]=value
        # Keep the result outside the matrix bank, variable banks and native
        # calculus workspace so typed state has no CPU-address aliases.
        for i,value in enumerate([0x90,0x81,0,0x90]):native.harness_set_reg(i,value)
        returned=native.calculus_expression_call(0x171f4,200000000,abort)
        assert returned==100,(tokens.hex(),returned)
        bank=Variables()
        for slot in range(10):
            for part,base in ((0,0x8226),(1,0x8408)):
                bank.values[slot][part]=Number.from_buffer_copy(bytes(ram[base+10*slot:base+10*slot+10]))
        assert native_count.value<=8192 and native_polls.value<=8192
        expected=[native.harness_get_reg(0),bytes(ram[0x9000:0x9014]).hex(),ram[0x8190]+256*ram[0x8191]-0x8200,
                  bytes(bank).hex(),[bytes(native_x[i]).hex() for i in range(native_count.value)],
                  [bytes(native_poll_x[i]).hex() for i in range(native_polls.value)]]
        if fixture:
            final={name:bytes(bank.values[slot][0]).hex() for slot,name in enumerate(('A','B','C','D','E','F','X','Y'),2)}
            saved=[fixture['native_status'],fixture['value'],fixture['consumed'],fixture['final_variables'],fixture['callback_x'],fixture['polls']]
            rerun=[expected[0],expected[1],expected[2],final,expected[4],len(expected[5])]
            assert saved==rerun,(fixture['name'],'saved native fixture is not reproducible',saved,rerun)
        polls=[]
        def cancel(_):
            polls.append(bytes(values.values[8][0]).hex())
            return bool(abort and len(polls)==abort)
        cb=Cancel(cancel);control=Control(cb,None);observed_count.value=0
        buf=(C.c_uint8*len(raw)).from_buffer_copy(raw);result=Result()
        if rich_slot:
            state=State(C.pointer(values),C.pointer(rich_bank))
            status=lib.fx_evaluate_with_state(buf,len(raw),C.byref(Options(0xc1,math,unit)),C.byref(state),C.byref(control),C.byref(result))
        else:
            status=lib.fx_evaluate_controlled(buf,len(raw),C.byref(Options(0xc1,math,unit)),C.byref(values),C.byref(control),C.byref(result))
        assert observed_count.value<=8192
        actual=[status,bytes(result.value).hex(),result.consumed,bytes(values).hex(),
                [bytes(observed_x[i]).hex() for i in range(observed_count.value)],polls]
        if rich_slot:
            entry=rich_bank.slots[identity]
            active=[row*3+column for row in range(rows) for column in range(columns)]
            actual.append([entry.rows,entry.columns,[bytes(entry.cells[cell]).hex() for cell in active]])
            expected.append([ram[0x80e0+2*identity],ram[0x80e1+2*identity],
                             [bytes(ram[0x829e+90*identity+10*cell:0x829e+90*identity+10*cell+10]).hex() for cell in active]])
        assert bytes(buf)==raw
        counts[group]=counts.get(group,0)+1
        if actual!=expected:
            row={'tokens':tokens.hex(),'group':group,'math':math,'unit':unit,'abort':abort,'initial_variables':before.hex(),
                 'actual':actual,'expected':expected,'unsupported_token':result.unsupported_token}
            failures.append(row)
            if len(failures)<=12:print(json.dumps(row))

    fixture_path=ROOT/'analysis/regressions/continuous-calculus-grammar.json'
    for row in json.loads(fixture_path.read_text())['fixtures']:
        settings=row['initial_settings']
        check(bytes.fromhex(row['tokens']),'saved_native_grammar',settings['8106'],settings['8105'],row['abort_poll'],
              initial_bank=row['initial_variables'],fixture=row)
    tails={0x6a:[b'X,0,1)',b'X,1,0)',b'X,1,1)',b'X,0,1',b'X,0,1,1\x74\x6010)',
                b'X,0,1,0)',b'X,0,1,\x601)',b'X,0,1,1,2)',b'X,0,1,)',b'X,0)',b'X,,1)',b',0,1)',
                b'(X+1),0,1)',b'\x98X),0,1)',b'1\x4f0,0,1)',b'X,0,1)+A',b'X,0,1)\x47'],
           0x6b:[b'X,1)',b'X,0)',b'X,1',b'X,1,1\x74\x6010)',b'X,1,0)',b'X,1,\x601)',
                b'X,1,1,2)',b'X,1,)',b'X,)',b'X)',b',1)',b'(X+1),1)',b'\x98X),0)',
                b'1\x4f0,1)',b'X,1)+A',b'X,1)\x47']}
    for token,forms in tails.items():
        for tail in forms:
            for math in (0,1):
                check(bytes([token])+tail,'grammar_and_errors',math,x=bytes.fromhex('80000001000201020100'))
        for abort in (1,2,3,7,8,15,16):check(bytes([token])+(b'X,0,1)' if token==0x6a else b'X,1)'),'cancellation',abort=abort)
        for nested in (0x5d,0x69,0x6a,0x6b):
            check(bytes([token,nested])+b'X,1,2),0,1)','nested_calculus_admission')
        for math in (0,1):
            suffix=b',0,1)' if token==0x6a else b',1)'
            for tag in range(16):
                check(bytes([token])+b'A'+suffix,'error_valued_variable',math,
                      a=bytes([0xf0|tag])+b'\0'*9)
            for kind in (0x60,0x90):
                for identity in range(9):
                    check(bytes([token])+b'A'+suffix,'empty_rich_slot',math,
                          a=bytes([kind|identity])+b'\0'*9)
                for cells in ([decimal(1)], [decimal('1.00000000000001')],
                              [bytes.fromhex('f9000000000000000000')]):
                    reference=bytes([kind|1])+bytes.fromhex('a30000000000000301')
                    check(bytes([token])+b'A'+suffix,'backed_rich_slot',math,
                          a=reference,rich_slot=(1,1,1,cells))
    bodies=[b'X',b'X\x75',b'X\x76',b'\x98X)',b'\xa0X)',b'\xa1X)',b'\x73X)',b'\xa3X)',
            b'1\x4fX',b'\x63X-A)',b'A\x4eX+1',b'\x88X)',b'\x682,X+3)',b'1\x4f(X-A)']
    for i in range(args.random_cases):
        token=rng.choice((0x6a,0x6b));body=rng.choice(bodies)
        low=str(rng.randrange(1,6)).encode();high=str(rng.randrange(1,6)).encode()
        bound=low+(b','+high if token==0x6a else b'')
        tolerance=rng.choice([b'',b',1\x74\x6010',b',.01',b',0',b',\x601'])
        expression=bytes([token])+body+b','+bound+tolerance+b')'
        initial_x=rng.choice([decimal(37),bytes.fromhex('80000001000201020100'),bytes.fromhex('21a30000000000000301')])
        initial_a=rng.choice([decimal(2),decimal('-1.23456789012345'),bytes.fromhex('80000001000201020100')])
        check(expression,'random_expressions',i%2,4+i%3,x=initial_x,a=initial_a)
        check(expression+b'+A','random_outer_arithmetic',i%2,4+i%3,x=initial_x,a=initial_a)
        check(expression,'random_cancellation',i%2,4+i%3,rng.randrange(1,17),initial_x,initial_a)
    report={'cases':sum(counts.values()),'domains':counts,'failures':failures,
            'comparison':'Complete171F4 status,20-byte result,cursor,all200variable bytes,every callbackX coordinate and every cancellation-pollX coordinate.',
            'scope':'Shared prepared ordinary COMP grammar for integral/derivative; default/explicit tolerances, localX, errors,cancellation,stores and outer arithmetic. Fullkey scheduling remains pending.',
            'test_observer':'Linker wrappers only record callback argument X then forward unchanged; original kernels execute every arithmetic operation.'}
    if failures:
        (build/'failures.json').write_text(json.dumps(report,indent=2)+'\n')
        raise AssertionError(f'{len(failures)} complete continuous-calculus mismatches')
    if not args.no_report:
        report=write_report('analysis/c-verification/eval_continuous.json',report,
                            implementation_inputs(ROOT,['csrc/'+p for p in SOURCES])+
                            [adapter,str(fixture_path.relative_to(ROOT)),'tools/c_build_inputs.py', 'tools/trace_natural_result.py', 'tools/verify_firmware.py', 'tools/nxu8/decoder.py','tools/c_verification.py','tools/test_eval_variables_c.py',
                             'tools/test_eval_complex_c.py','tools/test_numeric_calculus_c.py'],
                            'tools/test_eval_continuous_c.py')
    print(json.dumps({'status':'pass','cases':report['cases'],'domains':counts},indent=2))


if __name__=='__main__':main()
