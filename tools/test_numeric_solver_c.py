#!/usr/bin/env python3
"""Differential checks for readable prepared EQN solver kernels.

Original firmware execution is confined to this independent native oracle.
The numerical boundary precedes result history/display callbacks at 15658.
"""
import argparse
import ctypes as C
import json
import itertools
from pathlib import Path
import random
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from nxu8.machine import Machine
from trace_natural_result import settings
from c_verification import write_report


class Number(C.Structure):
    _fields_ = [('bytes', C.c_uint8 * 10)]
    def raw(self): return bytes(self.bytes)


class Complex(C.Structure):
    _fields_ = [('real', Number), ('imaginary', Number)]
    def raw(self): return self.real.raw() + self.imaginary.raw()


class Context(C.Structure):
    _fields_ = [('exact_math', C.c_uint8), ('real_only', C.c_uint8), ('cancel_at', C.c_uint32)]


class Result(C.Structure):
    _fields_ = [('roots', Complex * 3), ('count', C.c_uint8), ('firmware_status', C.c_uint8),
                ('cancellation_checks', C.c_uint32), ('coefficient_work', Number * 9),
                ('root_work', Number * 9), ('coefficient_rows', C.c_uint8),
                ('coefficient_columns', C.c_uint8), ('root_rows', C.c_uint8),
                ('root_columns', C.c_uint8)]


class GuardedResult(C.Structure):
    _fields_ = [('before', C.c_uint8 * 16), ('value', Result), ('after', C.c_uint8 * 16)]


class Rational(C.Structure):
    _fields_ = [('numerator', C.c_int64), ('denominator', C.c_uint64), ('flags', C.c_uint8)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--random-cases', type=int, default=5000)
    parser.add_argument('--explore', action='store_true')
    parser.add_argument('--no-publish', action='store_true')
    args = parser.parse_args()
    build = ROOT / 'analysis/build/numeric/solver'; build.mkdir(parents=True, exist_ok=True)
    sources = ['csrc/numeric/fx_solver.c', 'csrc/numeric/fx_solver_classifier.c', 'csrc/numeric/fx_numeric.c',
               'csrc/linalg/fx_linalg.c', 'csrc/complex/fx_complex.c',
               'csrc/complex/fx_complex_round.c', 'csrc/numeric/fx_root.c',
               'csrc/numeric/fx_transcend.c', 'csrc/trig/fx_trig_inverse.c',
               'csrc/trig/fx_trig_math.c', 'csrc/trig/fx_trig.c',
                 'csrc/numeric/fx_surd_components.c',
                 'csrc/numeric/fx_raw_decimal_divide.c',
                 'csrc/numeric/fx_raw_decimal_multiply_add.c',
                 'csrc/numeric/fx_raw_decimal_parts.c'
]
    headers = ['csrc/numeric/fx_solver.h', 'csrc/numeric/fx_solver_stage.h', 'csrc/numeric/fx_numeric.h',
               'csrc/linalg/fx_linalg.h', 'csrc/linalg/fx_linalg_stage.h', 'csrc/complex/fx_complex.h',
               'csrc/complex/fx_complex_round.h', 'csrc/numeric/fx_root.h',
               'csrc/numeric/fx_transcend.h', 'csrc/numeric/fx_transcend_internal.h', 'csrc/numeric/fx_transcend_guarded.h',
               'csrc/trig/fx_trig_inverse.h', 'csrc/trig/fx_trig_math.h', 'csrc/trig/fx_trig.h',
                 'csrc/numeric/fx_surd_components.h',
                 'csrc/numeric/fx_numeric_components.h',
                 'csrc/numeric/fx_raw_decimal_divide.h',
                 'csrc/numeric/fx_raw_decimal_multiply_add.h',
                 'csrc/numeric/fx_raw_decimal_parts.h'
]
    library = build / 'solver.so'
    subprocess.run(['gcc', '-std=c99', '-O3', '-Wall', '-Wextra', '-Werror', '-pedantic',
                    '-shared', '-fPIC', *(str(ROOT / p) for p in sources), '-o', str(library)], check=True)
    lib = C.CDLL(str(library)); ptr = C.POINTER(Number)
    lib.fx_decimal_parse.argtypes = [ptr, C.c_char_p]
    lib.fx_rational_encode.argtypes = [ptr, C.POINTER(Rational)]
    lib.fx_surd_pack.argtypes = [ptr, ptr]
    lib.fx_solver_solve.argtypes = [C.POINTER(Result), ptr, C.c_int, C.POINTER(Context)]
    lib.fx_solver_cleanup.argtypes = [C.POINTER(Result), C.POINTER(Result)]
    lib.fx_solver_classify_degenerate.argtypes = [C.POINTER(C.c_uint8), ptr, C.c_int]
    oracle = build / 'oracle'; oracle.mkdir(parents=True, exist_ok=True)
    helper = oracle / 'solver-oracle.c'
    helper.write_text('''#define harness_run original_harness_run
#include "%s"
#undef harness_run
int harness_run(uint64_t limit,uint32_t stop,bool cancellation) {
    return original_harness_run(limit,stop,cancellation);
}
int solver_run(uint64_t limit) {
    for(uint64_t i=0;i<limit;++i) {
        uint32_t pc=harness_get_pc();
        if(pc==0x2fffe) return 100;
        if(pc==0x5564) return 104;
        if(pc==0x15658) return 105;
        int status=original_harness_run(1,0x2fffe,false);
        if(status!=103) return status;
    }
    return 103;
}
''' % (ROOT / 'tools/nxu8/harness.c'))
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
                    str(helper), str(ROOT / 'tools/nxu8/vendor/SimU8/core.c'),
                    '-o', str(oracle / 'nxu8-harness.so')], check=True)
    m = Machine((ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes(), oracle)
    m.lib.solver_run.argtypes = [C.c_uint64]
    checks, failures = {}, []
    rng = random.Random(0x14f0c)
    kinds = [1, 2, 3, 4]

    def decimal(text):
        out = Number(); assert lib.fx_decimal_parse(C.byref(out), str(text).encode()) == 0
        return out.raw()

    def rational(n, d, flags=0):
        out = Number(); assert lib.fx_rational_encode(C.byref(out), C.byref(Rational(n, d, flags))) == 0
        return out.raw()

    def surd(n, rad, den):
        parts = (Number * 6)()
        for i, value in enumerate([n, rad, den, 0, 1, 1]):
            parts[i] = Number.from_buffer_copy(decimal(value))
        out = Number(); assert lib.fx_surd_pack(C.byref(out), parts) == 0
        return out.raw()

    def put(address, raw):
        for i, value in enumerate(raw): m.ram[address+i] = value

    def native(coefficients, kind, context):
        m.reset(); settings(m)
        m.ram[0x80f9] = 0x4b if context.real_only else 0x49
        m.ram[0x80fa] = kind; m.ram[0x8106] = context.exact_math
        for i, record in enumerate(coefficients):
            address = (0x82f8 + 10*(i-9) if kind == 2 and i >= 9 else
                       0x82f8 if kind == 4 and i == 3 else 0x829e + 10*i)
            put(address, record)
        m.lib.harness_set_sp(0x8dee); m.lib.harness_set_lr(0x2fffe); m.lib.harness_set_pc(0x14f0c)
        polls = 0
        for _ in range(300):
            stage = m.lib.solver_run(3000000)
            if stage in [100, 105]: break
            assert stage == 104, (stage, hex(m.lib.harness_get_pc()))
            polls += 1; m.ram[0x8e00] = 2 if context.cancel_at == polls else 0
            assert m.lib.harness_run(1, 0x2fffe, False) == 103
        else: raise AssertionError('solver did not terminate')
        count = m.reg(8) if stage == 105 else 0
        coefficient_work = bytes(m.ram[0x8406:0x8460]); root_work = bytes(m.ram[0x8460:0x84ba])
        values = coefficient_work if kind < 3 else root_work
        roots = [values[i*30:i*30+20] if i < count else bytes(20) for i in range(3)]
        return (0 if stage == 105 else m.reg(0), count, polls, coefficient_work,
                root_work, bytes(m.ram[0x80e8:0x80ec]), roots)

    def native_cleanup(roots, count):
        output, native_status = list(roots), 0
        for i in range(count):
            m.reset(); settings(m); put(0x8300, roots[i]); m.er(0, 0x8300); m.call(0x18724)
            output[i] = bytes(m.ram[0x8300:0x8314]); native_status = m.reg(0)
            if native_status: break
        return native_status, output

    def test_classifier(group, records, kind):
        m.reset(); settings(m); m.ram[0x80f9] = 0x49; m.ram[0x80fa] = kind
        for i, record in enumerate(records): put(0x829e + 10*i, record)
        m.call(0x112f6); expected = m.reg(0)
        inputs = (Number * 12)()
        for i, record in enumerate(records): inputs[i] = Number.from_buffer_copy(record)
        original = bytes(inputs); classification = C.c_uint8(0xa5)
        status = lib.fx_solver_classify_degenerate(C.byref(classification), inputs, kind)
        detail = {'kind':kind,'coefficients':[record.hex() for record in records]}
        check(group, (status, classification.value, bytes(inputs)), (0, expected, original), detail)
        check(group + '_native_inputs', bytes(m.ram[0x829e:0x8316]), original, detail)

    def serial(value):
        if isinstance(value, bytes): return value.hex()
        if isinstance(value, (list, tuple)): return [serial(item) for item in value]
        return value

    def check(group, actual, expected, detail):
        checks[group] = checks.get(group, 0) + 1
        if actual != expected:
            failures.append({'group': group, 'actual': serial(actual), 'native': serial(expected), 'input': detail})
            if not args.explore: raise AssertionError(json.dumps(failures[-1]))

    def test(group, records, kind, math=1, real_only=0, cancel=0, alias=False):
        context = Context(math, real_only, cancel)
        expected = native(records, kind, context)
        inputs = (Number * 12)()
        for i, record in enumerate(records): inputs[i] = Number.from_buffer_copy(record)
        original = bytes(inputs); result = Result()
        detail = {'kind': kind, 'math': math, 'real_only': real_only, 'cancel_at': cancel,
                  'coefficients': [record.hex() for record in records]}
        status = lib.fx_solver_solve(C.byref(result), inputs, kind, C.byref(context))
        check(group + '_host_status', status, 0, detail)
        check(group + '_inputs', bytes(inputs), original, detail)
        actual = (result.firmware_status, result.count, result.cancellation_checks,
                  bytes(result.coefficient_work), bytes(result.root_work),
                  bytes([result.coefficient_rows, result.coefficient_columns, result.root_rows, result.root_columns]),
                  [root.raw() for root in result.roots])
        check(group, actual, expected, detail)
        if not expected[0]:
            cleaned = Result()
            status = lib.fx_solver_cleanup(C.byref(cleaned), C.byref(result))
            check(group + '_cleanup', (status, cleaned.firmware_status, [root.raw() for root in cleaned.roots]),
                  (0, *native_cleanup(expected[6], expected[1])), detail)
            if alias:
                status = lib.fx_solver_cleanup(C.byref(result), C.byref(result))
                check(group + '_cleanup_alias', (status, bytes(result)), (0, bytes(cleaned)), detail)
        if alias:
            aliased = Result()
            alias_inputs = C.cast(C.byref(aliased, Result.coefficient_work.offset), ptr)
            C.memmove(alias_inputs, inputs, C.sizeof(inputs))
            status = lib.fx_solver_solve(C.byref(aliased), alias_inputs, kind, C.byref(context))
            check(group + '_solve_alias', (status, aliased.firmware_status, aliased.count,
                                          bytes(aliased.coefficient_work), bytes(aliased.root_work)),
                  (0, expected[0], expected[1], expected[3], expected[4]), detail)
            guarded = GuardedResult()
            C.memset(C.byref(guarded), 0xa5, C.sizeof(guarded))
            status = lib.fx_solver_solve(C.byref(guarded.value), inputs, kind, C.byref(context))
            check(group + '_output_bounds', (status, bytes(guarded.before), bytes(guarded.after)),
                  (0, b'\xa5'*16, b'\xa5'*16), detail)

    fixtures = {
        1: [[1,0,2,0,1,3], [1,1,2,1,-1,0], [0]*6, [1,2,3,2,4,6], [1,2,3,2,4,7],
            [0,1,0,0,0,0], [0,0,1,0,0,0]],
        2: [[1,0,0,0,1,0,0,0,1,2,3,4], [1,2,3,2,3,1,3,1,2,14,11,11], [0]*12,
            [1,2,3,2,4,6,3,6,9,1,2,4]],
        3: [[1,0,-1], [1,-3,2], [1,0,1], [1,-2,1], [1,0,0], [1,2,0], [1,0,-2],
            [0,1,-1], [15,1,1], [9,-2,-11], [1,'1e14',1], [1,'1e-14',1]],
        4: [[1,0,0,-1], [1,-6,11,-6], [1,0,0,1], [1,0,1,1], [1,-3,3,-1], [1,0,-3,2],
            [8,0,0,-1], [8,0,0,1], [-6,32,32,-66], [-4,-55,0,52],
            [1,0,-1,0], [1,2,0,0], [1,0,0,0], [0,1,2,3]]}
    for kind in kinds:
        for values in fixtures[kind]:
            records = [decimal(value) for value in values]
            for math in [0,1]:
                test('canonical', records, kind, math, alias=True)
                if kind >= 3: test('inequality', records, kind, math, real_only=1)
            polls = native(records, kind, Context(1,0,0))[2]
            for cancel in range(1, polls+2): test('cancellation', records, kind, cancel=cancel)
    scalar_records = [decimal(0), decimal(1), decimal(-1), decimal('0.333333333333333'),
                      rational(1,3), rational(-27,17), rational(1,3,0x40),
                      surd(1,2,1), surd(-3,5,7)]
    scalar_records += [bytes([0xf0+i])+bytes(9) for i in range(16)]
    for scalar in scalar_records:
        # 0xcx is not a marked compact scalar; it is outside the number
        # representation API and is not generated by the coefficient editor.
        for marked in ([0,0x40] if scalar[0] < 0x80 else [0]):
            record = bytes([scalar[0] | marked]) + scalar[1:]
            for kind in kinds:
                base = [decimal(v) for v in fixtures[kind][0]]
                for index in range(len(base)):
                    records = list(base); records[index] = record
                    for math in [0,1]: test('record_admission', records, kind, math)
    for exponent in [-99,-50,-15,-1,0,1,7,14,15,50,99]:
        for sign in ['', '-']:
            for kind in kinds:
                records = [decimal(v) for v in fixtures[kind][0]]
                for index in range(len(records)):
                    altered = list(records); altered[index] = decimal(f'{sign}1.23456789012345e{exponent}')
                    test('exponent_boundary', altered, kind)
    for i in range(args.random_cases):
        kind = rng.choice(kinds); length = {1:6,2:12,3:3,4:4}[kind]
        if i % 4 == 0:
            records = [rational(rng.randint(-999,999),rng.randint(1,999)) for _ in range(length)]
        elif i % 4 == 1:
            records = [decimal(f'{rng.randint(-999999,999999)}e{rng.randint(-5,5)}') for _ in range(length)]
        else: records = [decimal(rng.randint(-99,99)) for _ in range(length)]
        test('random', records, kind, rng.randrange(2), real_only=int(kind>=3 and i%17==0))
    for values in itertools.product([-1,0,1], repeat=6):
        test_classifier('classifier_exhaustive_linear2', [decimal(v) for v in values], 1)
    classifier_fixtures = {
        1: [[1,1,1,1,'1.000000000001',1], [1,1,1,1,'1.0000000000001',1],
            [1,1,1,1,'1.00000000000001',1], [1,1,1,1,1,'1.000000000001'],
            [1,1,1,1,1,'1.0000000000001'], ['1e-99']*6, ['1e99']*6],
        2: [[0,0,0,0,0,1,0,0,2,0,1,99], [1,2,3,2,4,6,3,6,9,1,2,3],
            [1,2,3,2,4,6,3,6,9,1,2,4], ['1e-99']*12, ['1e99']*12]}
    for kind, cases in classifier_fixtures.items():
        for values in cases: test_classifier('classifier_boundary', [decimal(v) for v in values], kind)
    for kind in [1,2]:
        for scalar in scalar_records:
            for index in range(6 if kind == 1 else 12):
                records = [decimal(0)]*(6 if kind == 1 else 12); records[index] = scalar
                test_classifier('classifier_record_admission', records, kind)
    for i in range(args.random_cases):
        kind = rng.choice([1,2]); length = 6 if kind == 1 else 12
        if kind == 2 and i%7 in [0,1]:
            first = [rng.randint(-9,9) for _ in range(3)]
            if i%7 == 0:
                weights = [rng.randint(-9,9) for _ in range(3)]
                rhs = rng.randint(-9,9)
                values = [weight*value for weight in weights for value in first] + [weight*rhs for weight in weights]
            else:
                second = [rng.randint(-9,9) for _ in range(3)]
                rhs = [rng.randint(-9,9),rng.randint(-9,9)]
                values = first + second + [a+b for a,b in zip(first,second)] + rhs + [sum(rhs)]
            if i%14 in [0,1]: values[-1] += 1
            records = [decimal(value) for value in values]
        elif kind == 1 and i%7 == 0:
            row = [rng.randint(-9,9) for _ in range(3)]; weight = rng.randint(-9,9)
            values = row + [value*weight for value in row]
            if i%14 == 0: values[-1] += 1
            records = [decimal(value) for value in values]
        elif i%3 == 0: records = [rational(rng.randint(-99,99),rng.randint(1,99),0x40 if i%9==0 else 0) for _ in range(length)]
        elif i%3 == 1: records = [decimal(f'{rng.randint(-9999,9999)}e{rng.randint(-99,99)}') for _ in range(length)]
        else: records = [decimal(rng.randint(-9,9)) for _ in range(length)]
        test_classifier('classifier_random', records, kind)
    report = {'status':'FAIL' if failures else 'PASS', 'checks':sum(checks.values()),
              'groups':checks, 'mismatches':failures, 'random_cases':args.random_cases,
              'numeric_boundary':'0x14f0c to 0x15658; subsequent result history/display excluded',
              'implemented_kinds':kinds}
    path = ROOT / 'analysis/c-verification/numeric_solver.json'
    if args.no_publish: print(json.dumps(report, indent=2))
    else:
        write_report(path, report, [*sources,*headers,'tools/trace_natural_result.py','tools/c_verification.py',
                                   'csrc/numeric/solver/manifest.json','csrc/numeric/solver/understood_ranges.json'],
                     'tools/test_numeric_solver_c.py')
        print(json.dumps({'report':str(path),'status':report['status'],'checks':report['checks'],
                          'mismatches':len(failures)}))
    if failures: raise SystemExit(1)


if __name__ == '__main__': main()
