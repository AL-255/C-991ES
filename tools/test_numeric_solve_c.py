#!/usr/bin/env python3
"""Original-ROM differential tests of high-level prepared SOLVE iteration."""
import argparse
import ctypes as C
import json
from pathlib import Path
import random
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from c_verification import write_report


class Number(C.Structure):
    _fields_ = [('bytes', C.c_uint8 * 10)]
    def raw(self): return bytes(self.bytes)


class Result(C.Structure):
    _fields_ = [('root', Number), ('residual', Number), ('variable', Number),
                ('firmware_status', C.c_uint8), ('evaluations', C.c_uint32),
                ('cancellation_checks', C.c_uint32), ('alternate_starts', C.c_uint8)]


class Rational(C.Structure):
    _fields_ = [('numerator', C.c_int64), ('denominator', C.c_uint64), ('flags', C.c_uint8)]


Ptr = C.POINTER(Number)
Equation = C.CFUNCTYPE(C.c_int, Ptr, Ptr, C.c_void_p)
Cancel = C.CFUNCTYPE(C.c_int, C.c_void_p)


class Control(C.Structure):
    _fields_ = [('cancelled', Cancel), ('userdata', C.c_void_p)]


class GuardedResult(C.Structure):
    _fields_ = [('before', C.c_uint8 * 16), ('result', Result), ('after', C.c_uint8 * 16)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--random-cases', type=int, default=5000)
    parser.add_argument('--no-report', action='store_true')
    args = parser.parse_args()
    build = ROOT / 'analysis/build/numeric/solve'; build.mkdir(parents=True, exist_ok=True)
    sources = ['csrc/numeric/fx_solve.c', 'csrc/numeric/fx_numeric.c', 'csrc/complex/fx_complex.c',
               'csrc/numeric/fx_transcend.c']
    headers = ['csrc/numeric/fx_solve.h', 'csrc/numeric/fx_calculus.h', 'csrc/numeric/fx_numeric.h',
               'csrc/complex/fx_complex.h', 'csrc/numeric/fx_transcend.h',
               'csrc/numeric/fx_transcend_internal.h', 'csrc/numeric/fx_transcend_guarded.h']
    library = build / 'solve.so'
    subprocess.run(['gcc', '-std=c99', '-O3', '-Wall', '-Wextra', '-Werror', '-pedantic',
                    '-shared', '-fPIC', *(str(ROOT / p) for p in sources), '-o', str(library)], check=True)
    lib = C.CDLL(str(library))
    lib.fx_solve_root.argtypes = [C.POINTER(Result), Ptr, Equation, C.c_void_p, C.POINTER(Control)]
    lib.fx_decimal_parse.argtypes = [Ptr, C.c_char_p]
    lib.fx_rational_encode.argtypes = [Ptr, C.POINTER(Rational)]
    lib.fx_number_binary.argtypes = [Ptr, Ptr, Ptr, C.c_int]
    lib.fx_number_integer_power.argtypes = [Ptr, Ptr, C.c_int]
    lib.fx_number_sqrt.argtypes = [Ptr, Ptr, C.c_int]
    lib.fx_number_ln.argtypes = [Ptr, Ptr]
    lib.fx_number_exp.argtypes = [Ptr, Ptr]
    lib.fx_decimal_integer_cleanup.argtypes = [Ptr]
    lib.fx_number_to_decimal.argtypes = [Ptr, Ptr]
    helper = build / 'solve-oracle.c'
    helper.write_text('''#include "%s"
unsigned solve_evaluations,solve_polls,solve_starts;
unsigned solve_mode,solve_supplied,solve_statuses[8192];
uint8_t solve_pairs[8192][20];
uint8_t solve_points[8192][10],solve_sides[8192][20];
int solve_call(uint64_t limit,unsigned abort_poll) {
 solve_evaluations=solve_polls=solve_starts=0;
 unsigned pending=0;
 harness_set_sp(0x8dee);harness_set_lr(0x2fffe);harness_set_pc(0x10000);
 for(uint64_t i=0;i<limit;++i) {
  uint32_t pc=harness_get_pc();
  if(pc==0x5564) {
   ++solve_polls;
   if(!abort_poll||solve_polls!=abort_poll)ram[0x8e00]=0;
  }
  if(pc==0x171f4&&LCSR==1&&LR==0x786) {
   if(solve_evaluations<8192)memcpy(solve_points[solve_evaluations],ram+0x8226+10*ram[0x83fc],10);
   ++solve_evaluations;
   pending=1;
   if(solve_mode) {
    unsigned row=solve_evaluations<=solve_supplied?solve_evaluations-1:solve_supplied-1;
    memcpy(ram+GR.ers[1],solve_pairs[row],20);
    GR.rs[0]=(uint8_t)solve_statuses[row];
    harness_set_pc(((uint32_t)LCSR<<16)|LR);
    pc=harness_get_pc();
   }
  }
  if((pc==0x1078a||pc==0x107a6)&&pending&&solve_evaluations<=8192) {
   memcpy(solve_sides[solve_evaluations-1],ram+GR.ers[7]-160,20);
   pending=0;
  }
  if(pc==0x104f4)++solve_starts;
  int status=harness_run(1,0x2fffe,false);
  if(status!=103)return status;
 }
 return 103;
}
''' % (ROOT / 'tools/nxu8/harness.c'))
    oracle_library = build / 'oracle.so'
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
                    str(helper), str(ROOT / 'tools/nxu8/vendor/SimU8/core.c'), '-o', str(oracle_library)], check=True)
    oracle = C.CDLL(str(oracle_library))
    oracle.harness_init.argtypes = [C.c_void_p, C.c_size_t]
    oracle.harness_ram.restype = C.POINTER(C.c_uint8 * 65536)
    oracle.harness_set_reg.argtypes = [C.c_uint, C.c_uint8]
    oracle.solve_call.argtypes = [C.c_uint64, C.c_uint]
    points = ((C.c_uint8 * 10) * 8192).in_dll(oracle, 'solve_points')
    sides = ((C.c_uint8 * 20) * 8192).in_dll(oracle, 'solve_sides')
    native_evaluations = C.c_uint.in_dll(oracle, 'solve_evaluations')
    native_polls = C.c_uint.in_dll(oracle, 'solve_polls')
    native_starts = C.c_uint.in_dll(oracle, 'solve_starts')
    native_mode = C.c_uint.in_dll(oracle,'solve_mode')
    native_supplied = C.c_uint.in_dll(oracle,'solve_supplied')
    supplied_pairs = ((C.c_uint8*20)*8192).in_dll(oracle,'solve_pairs')
    supplied_statuses = (C.c_uint*8192).in_dll(oracle,'solve_statuses')
    rom = (ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    rom_buffer = C.create_string_buffer(rom)
    counts, failures, outcomes = {}, [], {}
    rng = random.Random(0x10000)
    formulas = {'linear': b'X-A', 'equation': b'X=A', 'equation_square': b'X\x75=A',
                'affine': b'X\x4eD+E=A', 'offset': b'X+A=A', 'absolute': b'\x63X)-A',
                'pole': b'1\x4f(X-A)=1', 'square': b'X\x75-A', 'cube': b'X\x76-A',
                'sqrt': b'\x98X)-A', 'reciprocal': b'1\x4fX-A',
                'constant': b'A', 'ln': b'\xa3X)-A', 'exp': b'\x73X)-A', 'syntax': b')'}

    def literal(text):
        value = Number(); assert lib.fx_decimal_parse(C.byref(value), str(text).encode()) == 0
        return value

    def native(initial, coefficient, formula, abort,pairs=None):
        oracle.harness_init(rom_buffer, len(rom)); ram = oracle.harness_ram().contents
        native_mode.value = int(bool(pairs)); native_supplied.value = len(pairs or [])
        for i,(left,right,status) in enumerate(pairs or []):
            for j,value in enumerate(bytes.fromhex(left+right)): supplied_pairs[i][j] = value
            supplied_statuses[i] = status
        for address, value in [(0x80f9, 0xc1), (0x80fc, 0xc0), (0x80fd, 4),
                               (0x80f5, 0xf0), (0x8105, 4), (0x8106, 1),
                               (0x8121, 1), (0x83fc, 8)]: ram[address] = value
        for address, value in [(0x8190, 0x8200), (0x812c, 0x8200)]:
            ram[address] = value & 255; ram[address+1] = value >> 8
        tokens = formulas[formula] + b'\0'
        for i, value in enumerate(tokens): ram[0x8200+i] = value
        for address, record in [(0x823a, coefficient.raw()), (0x8276, initial.raw())]:
            for i, value in enumerate(record): ram[address+i] = value
        for address, record in [(0x8258,literal('37').raw()),(0x8262,literal('1').raw())]:
            for i,value in enumerate(record): ram[address+i] = value
        for i, value in enumerate((0x90, 0x81, 0, 0x83)): oracle.harness_set_reg(i, value)
        status = oracle.solve_call(100000000, abort)
        assert status == 100, (status, initial.raw().hex(), coefficient.raw().hex(), formula)
        assert native_evaluations.value <= 8192
        return {'root': bytes(ram[0x8300:0x830a]), 'residual': bytes(ram[0x830a:0x8314]),
                'variable': bytes(ram[0x8276:0x8280]), 'firmware_status': oracle.harness_get_reg(0),
                'evaluations': native_evaluations.value, 'cancellation_checks': native_polls.value,
                'alternate_starts': native_starts.value,
                'points': [bytes(points[i]) for i in range(native_evaluations.value)],
                'sides': [bytes(sides[i]) for i in range(native_evaluations.value)]}

    def run(initial, coefficient, formula, abort, host_error=0,alias=False,pairs=None,host_error_after=1):
        guarded = GuardedResult(); C.memset(C.byref(guarded),0xa5,C.sizeof(guarded))
        result = guarded.result; trace, values, polls = [], [], []
        if alias:
            result.root = initial
            source = C.byref(result.root)
        else: source = C.byref(initial)
        original = C.string_at(C.byref(guarded),C.sizeof(guarded))
        @Equation
        def function(output, x, userdata):
            del userdata
            trace.append(x.contents.raw())
            if host_error and len(trace) >= host_error_after: return host_error
            C.memset(output, 0, 20)
            if pairs:
                left,right,status = pairs[min(len(trace)-1,len(pairs)-1)]
                C.memmove(output,bytes.fromhex(left+right),20)
                if status:
                    record_status = status if status < 16 else 3
                    output[0].bytes[0] = output[1].bytes[0] = 0xf0|record_status
                    for index in range(1,10): output[0].bytes[index] = output[1].bytes[index] = 0
                values.append(C.string_at(output,20)); return status
            if coefficient.bytes[0] >> 4 in (6,15):
                output[0].bytes[0] = output[1].bytes[0] = 0xf3
                values.append(C.string_at(output,20)); return 3
            if formula == 'syntax':
                output[0].bytes[0] = output[1].bytes[0] = 0xf2
                values.append(C.string_at(output,20)); return 2
            if formula in ('equation','equation_square','affine','offset','pole'):
                C.memmove(output, x, 10); C.memmove(C.byref(output[1]),C.byref(coefficient),10)
                status = 0
                if formula == 'equation_square': status = lib.fx_number_integer_power(output,x,2)
                elif formula == 'affine':
                    scale,constant = literal('37'),literal('1')
                    status = lib.fx_number_binary(output,output,C.byref(scale),2)
                    if not status: status = lib.fx_decimal_integer_cleanup(output)
                    if not status: status = lib.fx_number_binary(output,output,C.byref(constant),0)
                elif formula == 'offset': status = lib.fx_number_binary(output,output,C.byref(coefficient),0)
                elif formula == 'pole':
                    constant = literal('1')
                    status = lib.fx_number_binary(output,x,C.byref(coefficient),1)
                    if not status: status = lib.fx_decimal_integer_cleanup(output)
                    if not status: status = lib.fx_number_binary(output,C.byref(constant),output,3)
                    C.memmove(C.byref(output[1]),C.byref(constant),10)
                if not status: status = lib.fx_decimal_integer_cleanup(output)
            elif formula == 'constant':
                C.memmove(output, C.byref(coefficient), 10); status = 0
            else:
                if formula == 'linear': C.memmove(output, x, 10); status = 0
                elif formula in ('square', 'cube'):
                    status = lib.fx_number_integer_power(output, x, 2 if formula == 'square' else 3)
                elif formula == 'sqrt': status = lib.fx_number_sqrt(output, x, 0)
                elif formula == 'ln': status = lib.fx_number_ln(output, x)
                elif formula == 'exp': status = lib.fx_number_exp(output, x)
                elif formula == 'absolute':
                    C.memmove(output,x,10)
                    status = lib.fx_number_negate(output,output) if output[0].bytes[9] >= 5 else 0
                else:
                    one = literal('1'); status = lib.fx_number_binary(output, C.byref(one), x, 3)
                if status == 0: status = lib.fx_decimal_integer_cleanup(output)
                if status == 0: status = lib.fx_number_binary(output, output, C.byref(coefficient), 1)
                if status == 0: status = lib.fx_decimal_integer_cleanup(output)
            if output[0].bytes[0] >= 0xf0: C.memmove(C.byref(output[1]),output,10)
            values.append(C.string_at(output,20))
            if status: return status
            return 3 if output[0].bytes[0] >= 0xf0 else 0
        @Cancel
        def cancelled(userdata):
            del userdata
            polls.append(1); return int(bool(abort and len(polls) == abort))
        control = Control(cancelled, None)
        status = lib.fx_solve_root(C.byref(result), source, function, None, C.byref(control))
        assert bytes(guarded.before) == bytes([0xa5])*16 and bytes(guarded.after) == bytes([0xa5])*16
        if status < 0: assert C.string_at(C.byref(guarded),C.sizeof(guarded)) == original
        return status, {'root': result.root.raw(), 'residual': result.residual.raw(),
                        'variable': result.variable.raw(), 'firmware_status': result.firmware_status,
                        'evaluations': result.evaluations, 'cancellation_checks': result.cancellation_checks,
                        'alternate_starts': result.alternate_starts, 'points': trace, 'sides': values}

    def case(group, initial, coefficient, formula, abort=0,alias=False,pairs=None):
        status, actual = run(initial, coefficient, formula, abort,alias=alias,pairs=pairs)
        expected = native(initial, coefficient, formula, abort,pairs=pairs)
        outcomes[expected['firmware_status']] = outcomes.get(expected['firmware_status'],0)+1
        for key in ('root','residual','variable','firmware_status','evaluations','cancellation_checks','alternate_starts','points','sides'):
            counts[group] = counts.get(group,0)+1
            if status or actual[key] != expected[key]:
                def serial(value):
                    if isinstance(value,bytes): return value.hex()
                    if isinstance(value,list): return [serial(item) for item in value]
                    return value
                failures.append({'group':group,'initial':initial.raw().hex(), 'coefficient':coefficient.raw().hex(),
                                 'formula':formula,'abort':abort,'key':key,'host_status':status,
                                 'actual':serial(actual[key]),'expected':serial(expected[key])})

    for formula, point, coefficient in [('linear','0','2'),('linear','10','-3'),('square','1','2'),
        ('square','-1','2'),('cube','0','8'),('sqrt','1','2'),('reciprocal','1','2'),('ln','1','2'),
        ('constant','1','1'),('constant','0','0')]:
        case('canonical', literal(point),literal(coefficient),formula)
    for point in ('0','1e-99','1e-94','1e-93','1e-92','1e-50','1e-15','1e-12','-1e-99','-1e-93','1e93','1e99'):
        for coefficient in ('0','1','-1','1e-99','1e-15'):
            case('decimal-boundary',literal(point),literal(coefficient),'equation')
    initial_records = [literal('1')]
    fraction = Number(); assert lib.fx_rational_encode(C.byref(fraction),C.byref(Rational(1,3,0))) == 0
    initial_records.append(fraction)
    for base in (literal('1'),fraction):
        marked = Number.from_buffer_copy(base.raw()); marked.bytes[0] |= 0x40; initial_records.append(marked)
    surd = Number(); assert lib.fx_number_sqrt(C.byref(surd),C.byref(literal('2')),1) == 0
    initial_records.append(surd)
    marked_zero = literal('0'); marked_zero.bytes[0] = 0x40; initial_records.append(marked_zero)
    for code in range(16):
        value = Number(); value.bytes[0] = 0xf0 | code; initial_records.append(value)
    for initial in initial_records:
        for formula, coefficient in (('equation','1'),('constant','1'),('syntax','0')):
            case('initial-record',initial,literal(coefficient),formula)
    for coefficient in initial_records[:4]:
        for formula in ('equation','equation_square','affine','offset'):
            case('callback-metadata',literal('2'),coefficient,formula)
    for formula,initial,coefficient in [('square','1','2'),('constant','1','1'),('ln','1','-10'),('reciprocal','1','0')]:
        for abort in (1,2,3,14,15,16,30,40,41,100):
            case('cancellation',literal(initial),literal(coefficient),formula,abort)
    for exponent in (-99,-94,-93,-92,-50,-15,-13,-12,-7,0,7,15,50,93,99):
        for sign in ('','-'):
            for formula in ('linear','square','reciprocal','offset'):
                case('scaled-boundary',literal(sign+'1.23456789012345e'+str(exponent)),literal('1'),formula)
    for formula,initial,coefficient in [('equation','1','2'),('square','1','2'),('constant','1','1'),('pole','0','0')]:
        case('output-alias',literal(initial),literal(coefficient),formula,alias=True)
        for host_error in (-1,-2,-3):
            status,_ = run(literal(initial),literal(coefficient),formula,0,host_error,alias=True)
            counts['host-failure-and-canaries'] = counts.get('host-failure-and-canaries',0)+1
            assert status == host_error
    for after in (2,3,4,6,10):
        status,actual = run(literal('1'),literal('2'),'square',0,-3,alias=True,host_error_after=after)
        counts['late-host-failure-and-canaries'] = counts.get('late-host-failure-and-canaries',0)+1
        assert status == -3 and len(actual['points']) == after
    one,zero = literal('1').raw().hex(),literal('0').raw().hex()
    for code in tuple(range(1,17))+(36,255):
        for initial in (literal('1'),initial_records[1],initial_records[3],initial_records[4]):
            case('prepared-callback-status',initial,literal('1'),'equation',pairs=[(one,zero,code)])
    for code in range(16):
        error = ('f%1x'%code)+'00'*9
        case('prepared-successful-error-record',literal('1'),literal('1'),'equation',pairs=[(error,zero,0)])
    for fixture in json.loads((ROOT/'analysis/native-fixtures/solve-callback-contracts.json').read_text()):
        case('prepared-counter-persistence',Number.from_buffer_copy(bytes.fromhex(fixture['initial'])),literal('1'),
             'equation',pairs=fixture['pairs'])
    for _ in range(args.random_cases):
        formula = rng.choice([name for name in formulas if name != 'syntax'])
        case('random',literal(rng.randint(-1000,1000)),literal(rng.randint(-1000,1000)),formula)
    report = {'implementation':'Readable prepared SOLVE Newton/recovery/rounding kernel',
              'counts':counts,'checks':sum(counts.values()),'mismatch_count':len(failures),
              'mismatches':failures,'native_status_outcomes':outcomes,
              'scope':'Prepared SOLVE canonical scalar inputs, raw result/persistent records, status, every cleaned callback point/normalized pair, cancellation and restarts',
              'oracle_modes':'Ordinary expressions execute original171F4; explicit callback fixtures substitute only its documented external pair/status boundary',
              'gaps':['Noncanonical tagged zero mantissas have known intermediate callback differences',
                      'Expression cursor/history/display, physical timer and malformed scalar/reference payloads are outside this API']}
    if not args.no_report:
        write_report(ROOT/'analysis/c-verification/numeric_solve.json',report,
                     sources+headers+['firmware/fx-991es-plus-c-ver4.bin','tools/nxu8/harness.c',
                                      'tools/nxu8/vendor/SimU8/core.c','tools/nxu8/vendor/SimU8/core.h',
                                      'tools/nxu8/vendor/SimU8/mmu.h','tools/c_verification.py',
                                      'analysis/native-fixtures/solve-callback-contracts.json',
                                      'csrc/numeric/solve/manifest.json', 'csrc/numeric/solve/understood_ranges.json'],
                     'tools/test_numeric_solve_c.py')
    (build/'preview.json').write_text(json.dumps(report,indent=2)+'\n')
    previews = []
    for failure in failures[:12]:
        item = dict(failure)
        if item['key'] in ('points','sides'):
            actual,expected = item.pop('actual'),item.pop('expected')
            i = next((i for i,(a,b) in enumerate(zip(actual,expected)) if a != b), min(len(actual),len(expected)))
            item.update(first_difference=i,actual_length=len(actual),expected_length=len(expected),
                        actual=actual[i] if i<len(actual) else None,expected=expected[i] if i<len(expected) else None)
        previews.append(item)
    print({'checks':report['checks'],'mismatches':len(failures),'outcomes':outcomes,'first':previews})
    return bool(failures)


if __name__ == '__main__': raise SystemExit(main())
